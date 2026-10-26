"""
Modo volume: o vídeo INTEIRO vira clipes curtos, todos diferentes (nenhum trecho se repete), com uma nota para a
fila de postagem saber quais são os melhores. Custo zero: nada de IA na escolha.

1. Tira o que não presta para ninguém: tempo morto (sem energia e sem fala, pelo áudio) e tela parada
   (menu, loading, pausa: quadros-chave quase iguais por 4 s ou mais).
2. Corta o que sobra em pedaços seguidos de `dmin` a `dmax` segundos, sempre em ponto natural: numa pausa da fala
   (nunca no meio de uma palavra) e, entre as opções, no som mais baixo (fim de lance, não no meio do tiro).
3. Dá nota a cada pedaço: energia do áudio, rajadas de ataques (tiros, golpes), reações faladas e movimento na
   tela; as notas são espalhadas de 20 a 98 pela posição de cada clipe entre todos do vídeo.
4. Cada clipe sai com o "pico" (segundo mais forte, que vira a abertura do clipe e o centro do zoom), o gancho,
   título e palavras de ênfase locais.
"""
import logging
import re
import subprocess
import threading

import numpy as np

import analise_audio
import config
import planejador_local as local
from editor_ffmpeg import _SEM_JANELA
from modelos import Corte
from transcricao import pasta_cache

log = logging.getLogger("volume")

PARADO = 2.5              # diferença média (0-255) abaixo disso = tela parada
PARADO_MIN = 4.0          # tela parada por 4 s ou mais sai do vídeo

TITULOS = ["Olha isso!", "Não acredito nisso", "Que jogada!", "Momento insano", "Isso foi sério?",
           "Ninguém esperava", "A melhor jogada", "Espera o final", "Isso aconteceu mesmo", "Que sorte!",
           "Olha o que ele fez", "Não era pra dar certo"]


# ================================================================ movimento na tela

def movimento(video, cancelado=None) -> list[list[float]]:
    """[[instante, diferença média para o quadro-chave anterior (0-255)], ...]. Só os quadros-chave (rápido até em
    live de horas), cada um com o seu instante real (o espaço entre eles varia de vídeo para vídeo; repetir
    quadros para fechar um ritmo fixo daria diferença 0 falsa). Em cache por vídeo."""
    arq = pasta_cache(video) / "movimento.json"
    em_cache = config.ler_json(arq)
    if em_cache is not None:
        return em_cache
    w, h = 64, 36
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-skip_frame", "nokey", "-i", str(video),
           "-vf", f"scale={w}:{h},format=gray,showinfo", "-fps_mode", "passthrough", "-an", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_SEM_JANELA)
    tempos = []

    def ler_tempos():  # o showinfo escreve o instante de cada quadro no stderr
        for linha in proc.stderr:
            m = re.search(rb"pts_time:\s*([\d.]+)", linha)
            if m and b"Parsed_showinfo" in linha:
                tempos.append(float(m.group(1)))
    leitor = threading.Thread(target=ler_tempos, daemon=True)
    leitor.start()
    dados = proc.stdout.read()
    proc.wait()
    leitor.join(5)
    if cancelado is not None and cancelado.is_set():
        from config import Cancelado
        raise Cancelado()
    quadros = np.frombuffer(dados, np.uint8)[: len(dados) // (w * h) * w * h].reshape(-1, h, w).astype(np.float32)
    n = min(len(quadros), len(tempos))
    if n < 2:
        return []
    saida = [[round(tempos[0], 2), 99.0]]
    saida += [[round(tempos[k], 2), round(float(np.abs(quadros[k] - quadros[k - 1]).mean()), 2)] for k in range(1, n)]
    config.gravar_json(arq, saida)
    return saida


def trechos_parados(mov: list[list[float]], duracao: float) -> list[tuple[float, float]]:
    """Intervalos de tela parada: quadros-chave seguidos quase iguais cobrindo PARADO_MIN s ou mais."""
    saida, comeco = [], None
    for k in range(1, len(mov) + 1):
        parado = k < len(mov) and mov[k][1] < PARADO
        if parado and comeco is None:
            comeco = mov[k - 1][0]
        elif not parado and comeco is not None:
            fim = mov[k - 1][0]
            if fim - comeco >= PARADO_MIN:
                saida.append((round(comeco, 2), round(min(fim, duracao), 2)))
            comeco = None
    return saida


# ================================================================ corte em pedaços

def _subtrair(base: list[tuple[float, float]], remover: list[tuple[float, float]]) -> list[tuple[float, float]]:
    resultado = list(base)
    for a, b in sorted(remover):
        novos = []
        for x, y in resultado:
            if b <= x or a >= y:
                novos.append((x, y))
                continue
            if a > x:
                novos.append((x, a))
            if b < y:
                novos.append((b, y))
        resultado = novos
    return resultado


def pontos_de_corte(palavras: list[dict], a: float, b: float) -> list[tuple[float, float]]:
    """(instante, qualidade) dos lugares bons para cortar em [a, b]: o meio de cada pausa entre palavras
    (pausa maior = melhor) e, onde ninguém fala, cada meio segundo (qualidade baixa, desempata pelo áudio)."""
    dentro = [w for w in palavras if w["f"] > a and w["i"] < b]
    pontos = []
    for w0, w1 in zip(dentro, dentro[1:]):
        pausa = w1["i"] - w0["f"]
        if pausa >= 0.15:
            fim_frase = w0["p"].rstrip()[-1:] in ".!?"
            pontos.append(((w0["f"] + w1["i"]) / 2, min(pausa, 1.5) + (0.8 if fim_frase else 0)))
    falando = [(w["i"] - 0.1, w["f"] + 0.1) for w in dentro]
    t = a + 0.5
    while t < b:
        if not any(x <= t <= y for x, y in falando):
            pontos.append((t, 0.3))
        t += 0.5
    return sorted(pontos)


def fatiar(trecho: tuple[float, float], palavras: list[dict], curva: list[float],
           dmin: float, dmax: float) -> list[tuple[float, float]]:
    """Pedaços seguidos de dmin a dmax s dentro do trecho, cortados nos melhores pontos. A sobra menor que
    dmin vai para o último pedaço (se couber em dmax + 8 s) ou é descartada."""
    a, b = trecho
    alvo = (dmin + dmax) / 2
    pontos = pontos_de_corte(palavras, a, b)
    pedacos, ini = [], a
    while b - ini >= dmin:
        if b - ini <= dmax:
            pedacos.append((ini, b))
            ini = b
            break
        opcoes = [(t, q) for t, q in pontos if ini + dmin <= t <= ini + dmax]
        if opcoes:
            def nota(p):
                t, q = p
                s = int(t)
                silencio = 1 - (curva[s] / 100 if 0 <= s < len(curva) else 0.5)
                return q + 0.8 * silencio - 0.08 * abs(t - (ini + alvo))
            fim = max(opcoes, key=nota)[0]
        else:  # fala corrida o tempo todo: corta onde der (fim de palavra mais perto do alvo)
            fins = [w["f"] for w in palavras if ini + dmin <= w["f"] <= ini + dmax]
            fim = min(fins, key=lambda t: abs(t - (ini + alvo))) if fins else ini + alvo
        pedacos.append((ini, fim))
        ini = fim
    if pedacos and b - ini > 0.5 and b - pedacos[-1][0] <= dmax + 8:
        pedacos[-1] = (pedacos[-1][0], b)
    return [(round(x, 2), round(y, 2)) for x, y in pedacos]


# ================================================================ nota

def _bruto(x: float, y: float, analise: dict, palavras: list[dict], mov: list[float]) -> float:
    curva = analise.get("curva") or []
    seg = [curva[s] for s in range(int(x), int(y)) if s < len(curva)]
    energia = float(np.mean(sorted(seg)[-3:])) if seg else 0.0                 # os 3 segundos mais fortes
    ataques = analise_audio.ataques_no_intervalo(analise, x, y) / max(y - x, 1)  # por segundo
    falas = [w for w in palavras if x <= w["i"] < y]
    reacoes = sum(1 for w in falas if w["p"].lower().strip(".,!?") in analise_audio.PALAVRAS_REACAO)
    reacoes += sum(1 for w in falas if w["p"].rstrip().endswith("!"))
    m = [d for t, d in mov if x < t <= y and d < 99]
    movimento_medio = float(np.mean(m)) if m else 0.0
    return (0.45 * energia + 0.25 * min(ataques * 40, 100) + 0.15 * min(reacoes * 15, 100)
            + 0.15 * min(movimento_medio * 4, 100))


def pico(x: float, y: float, analise: dict) -> float:
    curva, at = analise.get("curva") or [], analise.get("ataques") or []
    melhor, valor = (x + y) / 2, -1.0
    for s in range(int(x), int(y)):
        v = (curva[s] if s < len(curva) else 0) + 10 * sum(at[j] for j in (s - 1, s, s + 1) if 0 <= j < len(at))
        if v > valor:
            melhor, valor = s + 0.5, v
    return round(min(max(melhor, x), y), 2)


# ================================================================ tudo junto

def cortes(video, transcricao: dict, analise: dict, dmin: float = 15, dmax: float = 30,
           cancelado=None, progresso=None) -> list[Corte]:
    """O vídeo inteiro em clipes curtos diferentes, do melhor para o pior."""
    duracao = analise["duracao"]
    palavras = transcricao["palavras"]
    if progresso:
        progresso(0.1, "Procurando tela parada")
    mov = movimento(video, cancelado)
    remover = analise_audio.trechos_mortos(analise, palavras, 0, duracao, minimo=4.0) + trechos_parados(mov, duracao)
    uteis = [(x, y) for x, y in _subtrair([(0.0, duracao)], remover) if y - x >= dmin]
    if progresso:
        progresso(0.6, f"Cortando {sum(y - x for x, y in uteis) / 60:.0f} min aproveitáveis")
    pedacos = [p for t in uteis for p in fatiar(t, palavras, analise.get("curva") or [], dmin, dmax)]
    if not pedacos:
        return []
    brutos = np.array([_bruto(x, y, analise, palavras, mov) for x, y in pedacos])
    posicao = brutos.argsort().argsort() / max(len(brutos) - 1, 1)  # 0 = pior, 1 = melhor
    resultado = []
    for k, ((x, y), p) in enumerate(zip(pedacos, posicao)):
        falas = [w for w in palavras if x <= w["i"] < y]
        t = pico(x, y, analise)
        resultado.append(Corte(
            inicio=x, fim=y, nota=int(round(20 + 78 * p)), pico=t,
            gancho=(round(max(x, t - 1.5), 2), round(min(y, t + 1.5), 2)),
            titulo=local._titulo_de(falas) if len(falas) >= 4 else TITULOS[k % len(TITULOS)],
            palavras_enfase=local._enfase_de(falas),
            justificativa=f"Modo volume: trecho {_hms(x)}–{_hms(y)} do vídeo",
        ))
    resultado.sort(key=lambda c: (-c.nota, c.inicio))
    log.info("Modo volume: %d clipes de %d trechos aproveitáveis (%d removidos)", len(resultado), len(uteis), len(remover))
    return resultado


def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
