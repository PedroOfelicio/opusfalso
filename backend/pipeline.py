"""
Pipeline completo, usado pelo CLI (editar.py) e pela API (api.py).

Etapas: Transcrevendo -> Analisando -> Escolhendo trechos -> Cortando -> Legendando

O Claude é usado para interpretar a instrução e escolher os trechos. Se a API
não estiver disponível (sem chave/créditos/internet), entra o planejador local
e um aviso é registrado no projeto.
"""
import json
import logging
import math
import os
import random
import re
import time
from pathlib import Path

import analise_audio
import armazenamento
import biblioteca_audio as biblioteca
import config
import custos
import direcao
import editor_ffmpeg as ef
import legendas
import planejador_llm as llm
import planejador_local as local
import projetos
import reenquadramento as rq
import transcricao as tr
import youtube
from config import Cancelado
from modelos import CLIMAS, Corte, PlanoEdicao

log = logging.getLogger("pipeline")

ETAPAS = [
    ("transcrevendo", "Transcrevendo"),
    ("analisando", "Analisando"),
    ("escolhendo", "Escolhendo trechos"),
    ("cortando", "Cortando"),
    ("legendando", "Legendando"),
]
PESOS = {"transcrevendo": 0.25, "analisando": 0.08, "escolhendo": 0.07, "cortando": 0.2, "legendando": 0.4}


# ================================================================ progresso

class Progresso:
    """Atualiza etapas e % no meta.json (com no máximo ~3 gravações por segundo)."""

    def __init__(self, pid: str, imprimir: bool = False, etapas=None, pesos=None):
        self.pid = pid
        self.imprimir = imprimir
        self.nomes = dict(etapas or ETAPAS)
        self.pesos = pesos or PESOS
        self.atual = None
        self.concluido = 0.0
        self._ultima_gravacao = 0.0

    def etapa(self, nome: str):
        agora = time.time()
        anterior = self.atual
        if anterior:
            self.concluido += self.pesos[anterior]
        concluido = self.concluido

        def f(meta):
            if anterior:
                meta["etapas"][anterior].update(status="ok", fim=agora)
            meta["etapas"][nome] = {"status": "ativo", "inicio": agora, "fim": None, "detalhe": ""}
            meta["etapa"] = nome
            meta["progresso"] = round(concluido, 4)
        self.atual = nome
        projetos.atualizar(self.pid, f)
        if self.imprimir:
            print(f"\n==> {self.nomes[nome]}...")

    def __call__(self, p: float, detalhe: str = ""):
        total = self.concluido + self.pesos.get(self.atual, 0) * max(0.0, min(p, 1.0))
        agora = time.time()
        if agora - self._ultima_gravacao < 0.35 and p < 1:
            return
        self._ultima_gravacao = agora

        def f(meta):
            meta["progresso"] = round(total, 4)
            if detalhe and self.atual:
                meta["etapas"][self.atual]["detalhe"] = detalhe
        projetos.atualizar(self.pid, f)
        if self.imprimir:
            print(f"\r    {total * 100:5.1f}%  {detalhe[:60]:<60}", end="", flush=True)

    def finalizar(self):
        agora = time.time()

        def f(meta):
            if self.atual:
                meta["etapas"][self.atual].update(status="ok", fim=agora)
            meta["progresso"] = 1.0
        projetos.atualizar(self.pid, f)


def _claude_falhou(pid: str, erro: Exception):
    _aviso(pid, f"Claude indisponível: {str(erro).rstrip('.')}. Usando o planejador local (mais simples).")


def baixar_se_link(pid: str, meta: dict, prog, cancelado) -> bool:
    """Projeto de link (YouTube) com o vídeo ainda não baixado, ou já apagado: baixa agora, como primeira
    parte da etapa de transcrição. Devolve True se baixou."""
    if Path(meta["video"]).exists():
        return False
    if not meta.get("origem_url"):
        raise FileNotFoundError(f"Vídeo não encontrado: {meta['video']}")
    prog.etapa("transcrevendo")
    prog(0.0, "Baixando o vídeo do link")
    youtube.garantir_video(pid, lambda p, d="": prog(0.35 * p, d), cancelado)
    return True


def progresso_apos_download(prog, baixou: bool):
    """Depois de baixar, a transcrição ocupa o resto da etapa (35% -> 100%)."""
    return (lambda p, d="": prog(0.35 + 0.65 * p, d)) if baixou else prog


def aviso_disco(pid: str):
    livre = armazenamento.livre()
    if livre < armazenamento.ALERTA_LIVRE:
        _aviso(pid, f"Disco quase cheio: {livre / armazenamento.GB:.1f} GB livres. Se faltar espaço o render falha; "
                    "libere em Configurações > Armazenamento.")


def _aviso(pid: str, texto: str):
    log.warning(texto)
    projetos.atualizar(pid, lambda m: m["avisos"].append(texto) if texto not in m["avisos"] else None)


# ================================================================ configuração efetiva de um clipe

def plano_base(opcoes: dict) -> PlanoEdicao:
    """Plano inicial a partir das opções rápidas da interface/CLI."""
    dados = {
        "num_clips": opcoes.get("num_clips", 3),
        "formato": opcoes.get("formato", "9:16"),
        "legenda": {"preset": opcoes.get("preset", "opus"), "estilo": opcoes.get("estilo_legenda", "simples")},
        "efeitos_sonoros": bool(opcoes.get("efeitos_sonoros")),
    }
    musica = (opcoes.get("musica") or opcoes.get("musica_caminho") or "").strip()
    if musica == "auto":
        dados["musica_fundo"] = True
    elif musica in CLIMAS:
        dados.update(musica_fundo=True, musica_clima=musica)
    elif musica:
        dados.update(musica_fundo=True, musica_caminho=musica)
    if opcoes.get("duracao"):
        dados["duracao_min"], dados["duracao_max"] = opcoes["duracao"]
    if opcoes.get("cor"):
        dados["legenda"]["cor"] = opcoes["cor"]
    # Opções que vêm dos templates (ausentes = padrão do plano)
    for opcao, campo in (("zoom", "zoom_em_enfase"), ("remover_silencios", "remover_silencios"),
                         ("titulo", "titulo_gancho"), ("barra", "barra_progresso"), ("abertura", "abertura_climax"),
                         ("limpar_voz", "limpar_voz")):
        if opcoes.get(opcao) is not None:
            dados[campo] = bool(opcoes[opcao])
    return PlanoEdicao.model_validate(dados)


def config_clip(meta: dict, clip: dict) -> dict:
    plano, c = meta["plano"], clip.get("config", {})
    leg = plano["legenda"]
    # Diretor de arte ligado: o visual vem da escolha do Claude para o clipe (completada pelo clima);
    # desligado: tudo igual ao plano/template. O que o usuário mudar no editor (c) sempre vence.
    if meta["opcoes"].get("diretor"):
        d = direcao.efetiva(clip.get("direcao"), clip.get("clima"))
        preset_auto = d["preset"] or leg["preset"]
        cor_auto = leg["cor"] or d.get("cor")  # cor pedida na instrução vence a do diretor
    else:
        d = direcao.efetiva({}, None)
        preset_auto, cor_auto = leg["preset"], leg["cor"]
    return {
        "look": c.get("look", d["look"]),
        "transicao": c.get("transicao", d["transicao"]),
        "zoom_forca": c.get("zoom_forca", d["zoom"]),
        "impacto": c.get("impacto", d["impacto"]),
        "formato": c.get("formato", plano["formato"]),
        "legenda_ativa": c.get("legenda_ativa", leg["ativa"]),
        "estilo": c.get("estilo", leg["estilo"]),
        "preset": c.get("preset", preset_auto),
        "cor": c.get("cor", cor_auto),
        "titulo_ativo": c.get("titulo_ativo", plano["titulo_gancho"]),
        "barra": c.get("barra", plano.get("barra_progresso")),
        "zoom": c.get("zoom", plano["zoom_em_enfase"]),
        "remover_silencios": c.get("remover_silencios", plano["remover_silencios"]),
        "normalizar": c.get("normalizar", plano["normalizar_audio"]),
        "musica": c["musica"] if "musica" in c else _musica_do_plano(meta, clip),
        "efeitos": c.get("efeitos", plano.get("efeitos_sonoros", False)),
        "abertura": c.get("abertura", plano.get("abertura_climax", True)),
        "limpar_voz": c.get("limpar_voz", plano.get("limpar_voz") if plano.get("limpar_voz") is not None
                            else meta["modo"] == "falado"),
        "layout": c.get("layout", meta["opcoes"].get("layout", "auto")),
        "deslocamento_x": float(c.get("deslocamento_x", 0.0)),
        "video_apoio": meta["opcoes"].get("video_apoio") or None,
    }


def _musica_do_plano(meta: dict, clip: dict) -> str | None:
    """Arquivo informado no plano ou, se não houver, uma faixa da biblioteca local
    no clima do clipe (sempre a mesma para o mesmo clipe)."""
    plano = meta["plano"]
    if not plano["musica_fundo"]:
        return None
    if plano.get("musica_caminho"):
        return plano["musica_caminho"]
    clima = (plano.get("musica_clima") or clip.get("clima")
             or ("energetica" if meta.get("modo") == "gameplay" else "calma"))
    faixa = biblioteca.escolher_musica(clima, f"{meta['id']}/{clip['id']}")
    return str(faixa) if faixa else None


def _efeitos_sonoros(semente: str, titulo: bool, zoom: list, picos: list[float], duracao: float,
                     transicao: float | None = None) -> list:
    """Whoosh na entrada do título e na volta da abertura com o clímax, impacto nos picos do
    gameplay e pop nos zooms de ênfase. Espaçados (mín. 2,5 s) e no máximo 6 por clipe."""
    candidatos = []
    if titulo:
        candidatos.append((0.05, "whoosh", 0.55))
    if transicao is not None:
        candidatos.append((max(0.0, transicao - 0.2), "whoosh", 0.6))
    candidatos += [(max(0.0, t - 0.05), "impacto", 0.8) for t in picos]
    candidatos += [(a, "pop", 0.45) for a, _ in zoom]
    prioridade = {"impacto": 0, "whoosh": 1, "pop": 2}
    escolhidos = []
    for t, tipo, vol in sorted(candidatos, key=lambda e: prioridade[e[1]]):
        # 2,5 s entre efeitos do mesmo tipo, 0,8 s entre tipos diferentes (whoosh + impacto combinam)
        longe = all(abs(t - e[0]) >= (2.5 if e[1] == tipo else 0.8) for e in escolhidos)
        if t < duracao - 0.3 and longe and len(escolhidos) < 6:
            escolhidos.append((t, tipo, vol))
    resultado = []
    for k, (t, tipo, vol) in enumerate(sorted(escolhidos)):
        arq = biblioteca.escolher_efeito(tipo, f"{semente}/{k}")
        if arq:
            resultado.append((round(t, 2), str(arq), vol))
    return resultado


def _norm(p: str) -> str:
    return re.sub(r"[^\wÀ-ÿ]", "", p.lower())


def _aplicar_correcoes(palavras: list[dict], correcoes: list[dict] | None, inicio: float, fim: float) -> list[dict]:
    """Troca sequências erradas da transcrição ("meu jeep" -> "meu Deus") dentro do clipe,
    redistribuindo o tempo entre as palavras novas."""
    if not correcoes:
        return palavras
    resultado = list(palavras)
    for c in correcoes:
        alvo = [_norm(x) for x in c["de"].split() if _norm(x)]
        if not alvo:
            continue
        n = len(alvo)
        for k in range(len(resultado) - n + 1):
            bloco = resultado[k:k + n]
            if bloco[0]["i"] < inicio - 0.5 or bloco[-1]["f"] > fim + 0.5:
                continue
            if [_norm(w["p"]) for w in bloco] != alvo:
                continue
            novas = c["para"].split()
            passo = (bloco[-1]["f"] - bloco[0]["i"]) / max(len(novas), 1)
            resultado[k:k + n] = [{**bloco[0], "p": p, "i": round(bloco[0]["i"] + j * passo, 3),
                                   "f": round(bloco[0]["i"] + (j + 1) * passo, 3)} for j, p in enumerate(novas)]
            break
    return resultado


def _subtrair(trechos: list[tuple[float, float]], remover) -> list[tuple[float, float]]:
    """Tira os intervalos de `remover` dos trechos (jump cuts). Pedaços < 0,3 s somem."""
    resultado = list(trechos)
    for a, b in sorted(remover or []):
        novos = []
        for x, y in resultado:
            if b <= x or a >= y:
                novos.append((x, y))
                continue
            if a - x >= 0.3:
                novos.append((x, a))
            if y - b >= 0.3:
                novos.append((b, y))
        resultado = novos
    return resultado if ef.duracao_trechos(resultado) >= 3 else list(trechos)


def _cortes_na_batida(trechos: list[tuple[float, float]], inicio_saida: float, musica: str,
                      palavras: list[dict], maximo: float = 0.35) -> list[tuple[float, float]]:
    """Gameplay com música: puxa cada corte seco para a batida mais próxima (no tempo do clipe), mexendo só no
    fim do trecho anterior: no máximo meio tempo (e 0,35 s), sem cortar palavra, sem encostar no trecho
    seguinte e sem deixar trecho com menos de 1 s. A escolha dos lances (rótulos a cada 1,5 s) já tem uma
    incerteza maior que isso; o que muda é que a montagem passa a "bater" com a música."""
    m = ef.medir_musica(musica)
    if not m.get("batidas") or m.get("confianca", 0) < 0.3:
        return trechos
    batidas = [b - m["inicio"] for b in m["batidas"] if b >= m["inicio"]]  # a música começa no início útil
    if len(batidas) < 4:
        return trechos
    limite = min(maximo, m["periodo"] / 2)
    novos = [list(t) for t in trechos]
    t = inicio_saida
    for k in range(len(novos) - 1):
        a, b = novos[k]
        corte = t + (b - a)
        d = min(batidas, key=lambda x: abs(x - corte)) - corte
        nb = b + d
        if (abs(d) <= limite + 1e-6 and nb - a >= 1.0 and nb <= novos[k + 1][0] - 0.05
                and not any(w["i"] + 0.03 < nb < w["f"] - 0.03 for w in palavras)):
            novos[k][1] = round(nb, 3)
        t += novos[k][1] - a
    return [(a, b) for a, b in novos]


def _escolher_abertura(meta: dict, clip: dict, trechos: list) -> tuple[float, float] | None:
    """Trecho de 1,2-4 s para abrir o clipe antes do contexto (a técnica que mais segura nos 3 primeiros s).
    Falado: a frase "gancho" que o Claude marcou. Gameplay: o segundo de mais energia no áudio.
    Só vale se o momento estiver DEPOIS dos 3 primeiros segundos (senão o clipe já começa forte)."""
    def dentro(t):
        for a, b in trechos:
            if a <= t <= b:
                return a, b
        return None

    if meta["modo"] == "gameplay":
        curva = analise_audio.analisar(meta["video"]).get("curva") or []
        candidatos = [s + 0.5 for a, b in trechos for s in range(int(a), int(b)) if s < len(curva)]
        candidatos = [t for t in candidatos if (ef.mapear_tempo(t, trechos) or 0) >= 3]
        if not candidatos:
            return None
        t = max(candidatos, key=lambda x: curva[int(x)])
        a, b = dentro(t)
        ini, fim = max(a, t - 1.6), min(b, t + 0.6)  # o tiro vem antes do grito de reação
    else:
        g = clip.get("gancho")
        if not g or dentro(g[0]) is None or (ef.mapear_tempo(g[0], trechos) or 0) < 3:
            return None
        a, b = dentro(g[0])
        ini, fim = g[0], min(b, g[1], g[0] + 4.0)
    return (round(ini, 2), round(fim, 2)) if fim - ini >= 1.2 else None


def _pulsos_de_zoom(partes: list, com_abertura: bool) -> list[tuple[float, float, float]]:
    """Zoom fixo por trecho: a abertura mais fechada e, depois de cada corte seco, o enquadramento
    alterna entre normal e levemente fechado (esconde o pulo do jump cut)."""
    saida, t = [], 0.0
    for k, (a, b) in enumerate(partes):
        d = b - a
        if com_abertura and k == 0:
            fator = 1.12
        else:
            n = k - (1 if com_abertura else 0)
            fator = 1.07 if n % 2 else 1.0
        if fator != 1.0:
            saida.append((round(t, 3), round(t + d, 3), fator))
        t += d
    return saida


def _palavras_editadas(transcricao: dict, clip: dict) -> list[dict]:
    """Aplica as edições de texto feitas no editor (chave = início da palavra)."""
    edicoes = clip.get("palavras_editadas") or {}
    if not edicoes:
        return transcricao["palavras"]
    resultado = []
    for w in transcricao["palavras"]:
        novo = edicoes.get(f"{w['i']:.3f}")
        if novo is None:
            resultado.append(w)
        elif novo.strip():
            resultado.append({**w, "p": novo.strip()})
    return resultado


# ================================================================ render de um clipe

def _preparar_corte(meta: dict, clip: dict, cfg: dict, palavras: list[dict], pid: str, cid: str) -> dict:
    """Tudo o que define o arquivo de corte de um clipe: trechos, abertura, zoom, efeitos e a assinatura
    (se a assinatura não mudou, o corte já feito é reaproveitado). Usado pela etapa "Cortando" e pelo render."""
    # 1) Trechos: tira silêncios/tempo morto (se pedido) e o que o Claude marcou para remover
    if cfg["remover_silencios"] and meta["modo"] == "gameplay":
        # No gameplay a ação quase não tem fala: corta pelo áudio (sem energia E sem fala),
        # mas sem deixar o clipe abaixo de ~70% da duração mínima pedida
        mortos = analise_audio.trechos_mortos(analise_audio.analisar(meta["video"]), palavras,
                                              clip["inicio"], clip["fim"])
        trechos = _subtrair(_subtrair([(clip["inicio"], clip["fim"])], clip.get("remover")), mortos)
        if ef.duracao_trechos(trechos) < max(8.0, meta["plano"]["duracao_min"] * 0.9):
            trechos = [(clip["inicio"], clip["fim"])]
    elif cfg["remover_silencios"]:
        trechos = ef.intervalos_de_fala(palavras, clip["inicio"], clip["fim"])
    else:
        trechos = [(clip["inicio"], clip["fim"])]
    trechos = _subtrair(trechos, clip.get("remover"))

    # Abertura com o clímax: 1-2 s do melhor momento antes de tudo (teaser)
    abertura = _escolher_abertura(meta, clip, trechos) if cfg["abertura"] else None
    desloc = abertura[1] - abertura[0] if abertura else 0.0
    if meta["modo"] == "gameplay" and cfg["musica"] and len(trechos) > 1:
        trechos = _cortes_na_batida(trechos, desloc, cfg["musica"], palavras)
    partes = ([abertura] if abertura else []) + trechos
    duracao = ef.duracao_trechos(partes)

    # 2) Palavras no tempo do clipe + zoom (ênfase, pico e pulsos nos cortes secos)
    pal_clip = legendas.palavras_do_clipe(palavras, partes, clip.get("palavras_enfase"), clip.get("emojis"))
    zoom = legendas.momentos_de_zoom(pal_clip) if cfg["zoom"] else []
    picos = [a for a, _ in ef.mapear_intervalo(clip["pico"], clip["pico"], partes)] if clip.get("pico") is not None else []
    if cfg["zoom"]:
        zoom += [(max(0, t - 0.4), t + 0.9) for t in picos]
    zoom_base = _pulsos_de_zoom(partes, bool(abertura))
    titulo = clip.get("titulo") if cfg["titulo_ativo"] else None
    efeitos = (_efeitos_sonoros(f"{pid}/{cid}", bool(titulo), legendas.momentos_de_zoom(pal_clip), picos, duracao,
                                transicao=desloc if abertura else None)
               if cfg["efeitos"] else [])

    assinatura = repr((partes, cfg["normalizar"], cfg["musica"], efeitos, cfg["limpar_voz"]))
    return {"trechos": trechos, "abertura": abertura, "partes": partes, "duracao": duracao, "pal_clip": pal_clip,
            "zoom": zoom, "zoom_base": zoom_base, "titulo": titulo, "efeitos": efeitos, "assinatura": assinatura,
            "cortes": direcao.cortes_grandes(partes, bool(abertura)), "impactos": picos if meta["modo"] == "gameplay" else []}


def renderizar_clip(pid: str, cid: str, transcricao: dict | None = None, progresso=None, cancelado=None) -> dict:
    """Corta + reenquadra + legenda um clipe. Pode ser chamado de novo após edições."""
    meta = projetos.ler(pid)
    clip = projetos.clip(meta, cid)
    cfg = config_clip(meta, clip)
    transcricao = transcricao or tr.transcrever(meta["video"])
    palavras = _aplicar_correcoes(_palavras_editadas(transcricao, clip), clip.get("correcoes"),
                                  clip["inicio"], clip["fim"])
    pasta = projetos.pasta(pid)
    tmp = pasta / "tmp"
    tmp.mkdir(exist_ok=True)

    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(status="renderizando", progresso=0.0, erro=None))
    ultimo = [0.0]

    def prog(fase, p):  # fase 0 = corte (30%), fase 1 = render (70%)
        total = (0.3 * p) if fase == 0 else (0.3 + 0.7 * p)
        if progresso:
            progresso(total)
        if time.time() - ultimo[0] > 0.5:  # progresso do próprio clipe (para o card na interface)
            ultimo[0] = time.time()
            projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(progresso=round(total, 3)))

    p = _preparar_corte(meta, clip, cfg, palavras, pid, cid)
    trechos, abertura, duracao, pal_clip = p["trechos"], p["abertura"], p["duracao"], p["pal_clip"]
    zoom, zoom_base, titulo, efeitos = p["zoom"], p["zoom_base"], p["titulo"], p["efeitos"]

    # 3) Corte com o áudio final (normalização, música e efeitos)
    corte = tmp / f"{cid}_corte.mp4"
    assinatura = p["assinatura"]
    if not (corte.exists() and clip.get("corte_assinatura") == assinatura):
        ef.cortar(meta["video"], trechos, corte, normalizar=cfg["normalizar"], musica=cfg["musica"],
                  efeitos=efeitos, abertura=abertura, limpar_voz=cfg["limpar_voz"],
                  progresso=lambda p: prog(0, p), cancelado=cancelado)

    # 4) Estilo, título e render
    est = legendas.estilo(cfg["preset"], cfg["cor"])
    largura, altura = rq.RESOLUCOES[cfg["formato"]]
    saida_dir = projetos.garantir_saida(meta)
    saida = saida_dir / f"{cid}.mp4"
    barra = dict(est.get("barra_progresso") or {})
    if cfg["barra"] is not None:
        barra["ativa"] = cfg["barra"]
    opc = rq.OpcoesRender(
        formato=cfg["formato"], layout=cfg["layout"], modo=meta["modo"], deslocamento_x=cfg["deslocamento_x"],
        zoom_momentos=zoom, zoom_base=zoom_base, video_apoio=cfg["video_apoio"],
        barra_progresso={"cor": est["cor_destaque"], "altura": barra.get("altura", 10)} if barra.get("ativa") else None,
        look=direcao.filtro_look(cfg["look"]), zoom_intensidade=direcao.ZOOMS.get(cfg["zoom_forca"], 0.12),
        transicao=cfg["transicao"], cortes=p["cortes"], impacto=cfg["impacto"], impactos=p["impactos"],
    )

    info, usou_remotion = None, False
    if cfg["estilo"] == "animada" and (cfg["legenda_ativa"] or titulo):
        try:
            base = tmp / f"{cid}_base.mp4"
            opc_base = rq.OpcoesRender(**{**opc.__dict__, "barra_progresso": None})
            info = rq.renderizar(corte, base, opc_base, progresso=lambda p: prog(1, p * 0.4), cancelado=cancelado)
            legendas.renderizar_remotion(
                base, saida, pal_clip if cfg["legenda_ativa"] else [], est, titulo, duracao, largura, altura,
                barra=bool(barra.get("ativa")), progresso=lambda p: prog(1, 0.4 + 0.6 * p), cancelado=cancelado)
            usou_remotion = True
        except Cancelado:
            raise
        except Exception as e:
            _aviso(pid, f"Legenda animada (Remotion) falhou no {cid}, usando legenda simples: {str(e)[:200]}")
    if not usou_remotion:
        arq_ass = tmp / f"{cid}.ass"
        legendas.gerar_ass(pal_clip, est, arq_ass, largura, altura, duracao, titulo, cfg["legenda_ativa"])
        opc.arquivo_ass = os.path.relpath(arq_ass, config.DADOS).replace("\\", "/")
        info = rq.renderizar(corte, saida, opc, progresso=lambda p: prog(1, p), cancelado=cancelado)

    thumb = pasta / "thumbs" / f"{cid}.jpg"
    ef.extrair_frame(saida, min(1.2, duracao / 2), thumb, largura=540)

    def f(m):
        c = projetos.clip(m, cid)
        c.update(trechos=trechos, corte_assinatura=assinatura, arquivo=str(saida), thumb=str(thumb),
                 duracao=round(duracao, 2), versao=int(time.time()), status="pronto", erro=None,
                 layout_usado=info.get("layout") if info else None,
                 legenda_usada="animada" if usou_remotion else "simples")
    meta = projetos.atualizar(pid, f)
    escrever_posts(meta)
    return projetos.clip(meta, cid)


def texto_dos_posts(clips: list[dict]) -> str:
    """Título, legenda e hashtags de cada clipe, prontos para colar no TikTok/Reels/Shorts."""
    blocos = []
    for c in clips:
        linhas = [f"{Path(c['arquivo']).name if c.get('arquivo') else c['id']}  (nota {c.get('nota', 0)})",
                  f"Título: {c.get('titulo') or '-'}"]
        if c.get("legenda_post"):
            linhas.append(c["legenda_post"])
        if c.get("hashtags"):
            linhas.append(" ".join(c["hashtags"]))
        blocos.append("\n".join(linhas))
    return "\n\n".join(blocos) + "\n"


def escrever_posts(meta: dict) -> None:
    """posts.txt na pasta de saída, junto dos clipes (atualizado a cada render)."""
    prontos = [c for c in meta.get("clips", []) if c.get("status") == "pronto" and c.get("arquivo")]
    if not prontos or not meta.get("saida_dir"):
        return
    try:
        (Path(meta["saida_dir"]) / "posts.txt").write_text(texto_dos_posts(prontos), encoding="utf-8")
    except OSError as e:
        log.warning("Não consegui escrever posts.txt: %s", e)


# ================================================================ escolha de trechos

TITULOS_GAMEPLAY = ["Olha isso!", "Não acredito nisso", "Que jogada!", "Momento insano", "Isso foi sério?",
                    "Ninguém esperava", "A melhor jogada", "Clutch absurdo"]


def _plano(meta: dict, pid: str) -> PlanoEdicao:
    base = plano_base(meta["opcoes"])
    try:
        plano = llm.interpretar_instrucao(meta["instrucao"], meta["modo"], base, pid)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        plano = local.interpretar_instrucao(meta["instrucao"], base)
    pasta = biblioteca.PASTA_AUDIO
    if plano.musica_fundo and not plano.musica_caminho and not biblioteca.musicas():
        plano.musica_fundo = False
        plano.nao_atendido.append(f"música de fundo (biblioteca vazia: coloque músicas em {pasta / 'musica'})")
    if plano.efeitos_sonoros and not any(biblioteca.resumo()["efeitos"].values()):
        plano.nao_atendido.append(f"efeitos sonoros (biblioteca vazia: coloque efeitos em {pasta / 'efeitos'})")
    return plano


MUITOS_CLIPES = 8     # acima disso, a escolha é feita por janelas do vídeo
POR_JANELA = 6        # clipes pedidos em cada janela


def janelas(duracao: float, quantidade: int, por_janela: int = POR_JANELA) -> list[tuple[float, float, int]]:
    """Divide o vídeo em janelas iguais para pedir muitos clipes (ex.: live de 2 h, 70 clipes = 12 janelas de
    10 min, ~6 clipes cada). Cada pedido ao Claude fica pequeno e os clipes saem espalhados pela live inteira."""
    n = max(1, math.ceil(quantidade / por_janela))
    passo = duracao / n
    base, resto = divmod(quantidade, n)
    return [(round(k * passo, 2), round((k + 1) * passo, 2), base + (1 if k < resto else 0)) for k in range(n)]


def _cortes_falado(transcricao, plano, pid, excluir=None, quantidade=None, progresso=None) -> list[Corte]:
    if not transcricao["palavras"]:
        raise ValueError("Nenhuma fala encontrada no vídeo. Para gameplay sem voz use o modo Gameplay.")
    quantidade = quantidade or plano.num_clips
    if quantidade > MUITOS_CLIPES:
        cortes: list[Corte] = []
        partes = janelas(transcricao["duracao"], quantidade)
        for k, (a, b, q) in enumerate(partes):
            if progresso:
                progresso(k / len(partes), f"Parte {k + 1} de {len(partes)} do vídeo")
            # a janela vai até um clipe depois do fim, para o último clipe poder terminar a ideia
            limite = b + plano.duracao_max
            parcial = {**transcricao,
                       "segmentos": [s for s in transcricao["segmentos"] if s["inicio"] >= a and s["fim"] <= limite],
                       "palavras": [w for w in transcricao["palavras"] if a <= w["i"] <= limite]}
            if len(parcial["palavras"]) < 20:
                continue
            ocupados = list(excluir or []) + [(c.inicio, c.fim) for c in cortes]
            cortes += _cortes_falado(parcial, plano, pid, ocupados, q)
        return cortes
    try:
        return llm.escolher_cortes_falado(transcricao, plano, pid, excluir, quantidade)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        return local.escolher_cortes_falado(transcricao, plano, excluir, quantidade)


def _cortes_gameplay(video, transcricao, analise, plano, pid, excluir=None, quantidade=None,
                     ver_imagens=True, cancelado=None, max_candidatos: int | None = None,
                     progresso=None, em_janela: bool = False) -> list[Corte]:
    quantidade = quantidade or plano.num_clips
    if quantidade > MUITOS_CLIPES and not em_janela:
        cortes: list[Corte] = []
        total = analise["duracao"]
        partes = janelas(total, quantidade)
        for k, (a, b, q) in enumerate(partes):
            if cancelado is not None and cancelado.is_set():
                raise Cancelado()
            if progresso:
                progresso(k / len(partes), f"Parte {k + 1} de {len(partes)} do vídeo")
            fora = [(0.0, a), (b, total)] + list(excluir or []) + [(c.inicio, c.fim) for c in cortes]
            try:
                cortes += _cortes_gameplay(video, transcricao, analise, plano, pid, fora, q, ver_imagens, cancelado,
                                           max_candidatos=q * 2, em_janela=True)
            except ValueError:  # parte sem nenhum pico de energia (ex.: pausa da live)
                continue
        return cortes
    tem_fala = len(transcricao["palavras"]) >= 20
    # Janela maior que o clipe final: o Claude apara início/fim olhando os quadros
    janela = min(plano.duracao_max + 8, 100)
    candidatos = analise_audio.candidatos_gameplay(
        analise, transcricao if tem_fala else None, janela, janela,
        maximo=max_candidatos or min(12, quantidade * 3), excluir=excluir)
    if not candidatos:
        raise ValueError("Nenhum pico de energia encontrado no áudio.")
    for c in candidatos:
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()
        if tem_fala:
            c["fala_tempos"] = _fala_com_tempos(transcricao, c["inicio"], c["fim"])
        if ver_imagens:
            c["folha"] = _folha_de_quadros(video, c["inicio"], c["fim"])

    try:
        resposta = llm.escolher_cortes_gameplay(candidatos, quantidade, pid, plano.duracao_min, plano.duracao_max)
        por_id = {c["id"]: c for c in candidatos}
        cortes = []
        for e in resposta.escolhas:
            c = por_id.get(e.id)
            if not c:
                continue
            inicio, fim = _aparar(c, e.inicio, e.fim, plano)
            remover = [(max(a, inicio), min(b, fim)) for a, b in e.remover if min(b, fim) - max(a, inicio) >= 1.0]
            cortes.append(Corte(inicio=inicio, fim=fim, titulo=e.titulo, nota=e.nota, pico=c["pico"],
                                justificativa=e.justificativa, palavras_enfase=e.palavras_enfase, emojis=e.emojis,
                                clima=e.clima, remover=remover, correcoes=e.correcoes,
                                legenda_post=e.legenda_post, hashtags=e.hashtags, direcao=e.direcao))
        if cortes:
            cortes = cortes[:quantidade]
            if ver_imagens:
                revisados = []
                for k, c in enumerate(cortes):
                    proibidos = ([(x.inicio, x.fim) for x in revisados] + [(x.inicio, x.fim) for x in cortes[k + 1:]]
                                 + list(excluir or []))
                    revisados.append(_revisar(video, c, pid, plano.duracao_min, plano.duracao_max,
                                              analise["duracao"], proibidos, cancelado))
                cortes = revisados
            return cortes
        # O Claude respondeu, mas descartou todos os candidatos (ex.: só menu, tela parada, vídeo que não é jogo)
        if em_janela:
            return []  # muitos clipes: uma parte fraca da live simplesmente não dá clipe
        recusados = True
        _aviso(pid, "O Claude não achou nenhum momento com ação real" + (" nas imagens" if ver_imagens else "")
               + ": os clipes foram escolhidos só pelos picos de áudio e estão com nota baixa.")
    except llm.ErroClaude as e:
        recusados = False
        _claude_falhou(pid, e)

    melhores = sorted(candidatos, key=lambda c: c["energia"], reverse=True)[:quantidade]
    titulos = random.sample(TITULOS_GAMEPLAY, len(TITULOS_GAMEPLAY))
    cortes = []
    for c in melhores:
        inicio, fim = _aparar(c, None, None, plano)
        nota = min(int(c["energia"]), 40) if recusados else int(c["energia"])
        motivo = "; o Claude não viu ação real neste trecho" if recusados else ""
        cortes.append(Corte(inicio=inicio, fim=fim, titulo=titulos[len(cortes) % len(titulos)], nota=nota,
                            justificativa=f"Pico de energia no áudio ({c['picos']} pico(s) no trecho{motivo})",
                            pico=c["pico"]))
    return cortes


VIVO = ("acao", "reacao")
LETRAS = {"acao": "A", "reacao": "R", "morto": "o", "menu": "M"}


def _rotular(video, a: float, b: float, pid: str, espaco: float = 1.5) -> list[tuple[float, float, str]]:
    """Amostras (centro, duração, rótulo) de [a, b]: ~1 quadro a cada `espaco` s (máx. 32 por folha),
    rotulados pelo modelo da revisão fina. Lista vazia se não der para rotular."""
    dur = b - a
    if dur < 2:
        return []
    n = max(8, min(32, int(round(dur / espaco / 4)) * 4))
    folha = _folha_de_quadros(video, a, b, n=n)
    if not folha:
        return []
    r = llm.revisar_clipe_gameplay(folha, n, pid)
    if len(r.quadros) != n:
        return []
    passo = dur / n
    return [(a + (k + 0.5) * passo, passo, r.quadros[k]) for k in range(n)]


def _revisar(video, corte: Corte, pid: str, minimo: float, maximo: float, duracao_video: float,
             proibidos: list | None = None, cancelado=None) -> Corte:
    """Revisão fina: rotula os quadros do trecho e monta o clipe só com jogo (sem menus, fase de compra,
    telas de fim de round). Se a ação não bastar para a duração mínima, amplia a janela em até 2 x 30 s
    para cada lado (sem invadir os outros clipes) e emenda os lances vizinhos em montagem."""
    if cancelado is not None and cancelado.is_set():
        raise Cancelado()
    # limites: não entra no trecho de outro clipe
    antes = max([y for x, y in proibidos or [] if y <= corte.inicio + 1] + [0.0])
    depois = min([x for x, y in proibidos or [] if x >= corte.fim - 1] + [duracao_video])
    try:
        amostras = _rotular(video, corte.inicio, corte.fim, pid)
        for _ in range(2):
            if not amostras:
                break
            montado = _montar(corte, amostras, minimo, maximo)
            if montado is None or _util(montado, amostras) >= minimo:
                break
            j0 = amostras[0][0] - amostras[0][1] / 2
            j1 = amostras[-1][0] + amostras[-1][1] / 2
            novo0, novo1 = max(antes, j0 - 30), min(depois, j1 + 30)
            if novo0 >= j0 - 2 and novo1 <= j1 + 2:
                break  # sem espaço para crescer
            if novo0 < j0 - 2:
                amostras = _rotular(video, novo0, j0, pid) + amostras
            if novo1 > j1 + 2:
                amostras = amostras + _rotular(video, j1, novo1, pid)
    except llm.ErroClaude as e:
        log.warning("Revisão do clipe indisponível: %s", e)
        return corte
    if not amostras:
        return corte
    montado = _montar(corte, amostras, minimo, maximo) or corte
    novo = _aparar_escuro(video, montado)
    log.info("Revisão %s: %.1f-%.1f -> %.1f-%.1f (%.1f s úteis), remover %s",
             "".join(LETRAS[x[2]] for x in amostras), corte.inicio, corte.fim, novo.inicio, novo.fim,
             _util(novo, amostras), novo.remover)
    return novo


def _util(corte: Corte, amostras) -> float:
    """Duração final do clipe (sem os trechos removidos)."""
    return corte.fim - corte.inicio - sum(b - a for a, b in corte.remover)


def _montar(corte: Corte, amostras: list[tuple[float, float, str]], minimo: float, maximo: float) -> Corte | None:
    """Monta o clipe a partir das amostras rotuladas, como uma sequência de lances:
    cada lance = ação + ~1 quadro de preparação/reação colado nela. Tempo parado longe da ação e menus
    viram corte seco. Se a ação do trecho não bastar, emenda os lances vizinhos até a duração mínima."""
    rot = [x[2] for x in amostras]
    n = len(amostras)
    nucleo = [k for k, (t, _, r) in enumerate(amostras) if r in VIVO and corte.inicio <= t <= corte.fim]
    nucleo = nucleo or [k for k, r in enumerate(rot) if r in VIVO]
    if not nucleo:
        return None

    def fica(k):  # ação, ou quadro de jogo colado numa ação (preparação/reação)
        if rot[k] in VIVO:
            return True
        return rot[k] != "menu" and any(0 <= j < n and rot[j] in VIVO for j in (k - 1, k + 1))

    def util(x, y):
        return sum(amostras[k][1] for k in range(x, y + 1) if fica(k))

    def ate_vivo(k, passo):
        d = 0
        while 0 <= k < n:
            if rot[k] in VIVO:
                return d
            k, d = k + passo, d + 1
        return 99

    a, b = nucleo[0], nucleo[-1]
    # cresce para o lado onde o próximo lance está mais perto (empate: depois, a história continua)
    while util(a, b) < minimo:
        pode_frente, pode_tras = b + 1 < n, a - 1 >= 0
        if not (pode_frente or pode_tras):
            break
        if pode_frente and (not pode_tras or ate_vivo(b + 1, 1) <= ate_vivo(a - 1, -1)):
            b += 1
        else:
            a -= 1
        if util(a, b) > maximo:
            break
    while a < b and not fica(a):
        a += 1
    while b > a and not fica(b):
        b -= 1
    if util(a, b) < 5:
        return None

    remover, k = [], a
    while k <= b:
        if fica(k):
            k += 1
            continue
        j = k
        while j <= b and not fica(j) and (rot[j] == "menu") == (rot[k] == "menu"):
            j += 1  # blocos separados: menu de um lado, movimentação do outro
        r0 = amostras[k][0] - amostras[k][1] / 2
        r1 = amostras[j - 1][0] + amostras[j - 1][1] / 2
        so_menu = rot[k] == "menu"
        if r1 - r0 >= 1.0:
            remover.append((round(r0 + 0.1, 2), round(r1 - 0.1, 2), so_menu))
        k = j
    # Pouca ação no vídeo: devolve os menores trechos de movimentação (nunca menu) até a duração mínima
    total = util(a, b)
    for r in sorted([r for r in remover if not r[2]], key=lambda r: r[1] - r[0]):
        if total >= minimo:
            break
        remover.remove(r)
        total += r[1] - r[0]
    inicio = amostras[a][0] - amostras[a][1] / 2
    fim = amostras[b][0] + amostras[b][1] / 2
    return corte.model_copy(update={"inicio": round(inicio, 2), "fim": round(fim, 2),
                                    "remover": [(x, y) for x, y, _ in remover]})


def _aparar_escuro(video, corte: Corte, janela: float = 3.0, passo: float = 0.25) -> Corte:
    """Tira das pontas a tela preta/escurecendo (morte, respawn, transição), medindo o brilho
    dos quadros nos primeiros e últimos `janela` segundos. Sem custo de API."""
    import cv2

    cap = cv2.VideoCapture(str(video))

    def escuro(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        return ok and float(cv2.cvtColor(cv2.resize(f, (160, 90)), cv2.COLOR_BGR2GRAY).mean()) < 22

    try:
        inicio, fim = corte.inicio, corte.fim
        pontos = [inicio + k * passo for k in range(int(janela / passo))]
        escuros = [t for t in pontos if t < fim and escuro(t)]
        if escuros:
            inicio = escuros[-1] + passo  # começa depois do último quadro escuro do começo
        pontos = [fim - k * passo for k in range(1, int(janela / passo) + 1)]
        escuros = [t for t in pontos if t > inicio and escuro(t)]
        if escuros:
            fim = escuros[-1]  # termina antes do primeiro quadro escuro do fim
    finally:
        cap.release()
    if (inicio, fim) == (corte.inicio, corte.fim) or fim - inicio < 5:
        return corte
    log.info("Tela escura aparada: %.1f-%.1f -> %.1f-%.1f", corte.inicio, corte.fim, inicio, fim)
    remover = [(max(a, inicio), min(b, fim)) for a, b in corte.remover if min(b, fim) - max(a, inicio) >= 1.0]
    return corte.model_copy(update={"inicio": round(inicio, 2), "fim": round(fim, 2), "remover": remover})


def _aparar(c: dict, inicio: float | None, fim: float | None, plano: PlanoEdicao) -> tuple[float, float]:
    """Início/fim sugeridos pelo Claude, presos à janela do candidato. Sem sugestão válida,
    usa a duração-alvo com o pico em ~60% do clipe."""
    a, b = c["inicio"], c["fim"]
    if inicio is not None and fim is not None:
        inicio, fim = max(a, float(inicio)), min(b, float(fim))
        if fim - inicio >= min(8.0, plano.duracao_min):
            return round(inicio, 2), round(fim, 2)
    alvo = min((plano.duracao_min + plano.duracao_max) / 2, b - a)
    inicio = min(max(a, c["pico"] - alvo * 0.6), b - alvo)
    return round(inicio, 2), round(inicio + alvo, 2)


def _fala_com_tempos(transcricao: dict, inicio: float, fim: float) -> str:
    """Fala do trecho em frases curtas com o segundo de início: "[101.2] vai vai ele tá aí"."""
    frases, atual = [], []
    for w in tr.palavras_no_intervalo(transcricao, inicio, fim):
        if atual and (w["i"] - atual[-1]["f"] > 0.8 or len(atual) >= 14):
            frases.append(atual)
            atual = []
        atual.append(w)
    if atual:
        frases.append(atual)
    return " ".join(f"[{f[0]['i']:.1f}] " + " ".join(w["p"] for w in f) for f in frases)


def _folha_de_quadros(video, inicio: float, fim: float, n: int = 8, largura: int = 320) -> bytes | None:
    """n quadros do trecho numa imagem 4 x 2 (~600 tokens para o Claude), com o segundo escrito em cada um."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    quadros = []
    try:
        for k in range(n):
            t = inicio + (k + 0.5) * (fim - inicio) / n
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, f = cap.read()
            if not ok:
                continue
            h, w = f.shape[:2]
            f = cv2.resize(f, (largura, int(h * largura / w)), interpolation=cv2.INTER_AREA)
            rotulo = f"t={t:.1f}"
            cv2.putText(f, rotulo, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(f, rotulo, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            quadros.append(f)
    finally:
        cap.release()
    if len(quadros) < n // 2:
        return None
    while len(quadros) % 4:
        quadros.append(np.zeros_like(quadros[0]))
    folha = np.vstack([np.hstack(quadros[i:i + 4]) for i in range(0, len(quadros), 4)])
    ok, buf = cv2.imencode(".jpg", folha, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def _novo_clip(cid: str, corte: Corte) -> dict:
    return {
        "id": cid, "inicio": corte.inicio, "fim": corte.fim, "titulo": corte.titulo, "nota": corte.nota,
        "justificativa": corte.justificativa, "palavras_enfase": corte.palavras_enfase,
        "emojis": [e.model_dump() for e in corte.emojis], "pico": corte.pico, "clima": corte.clima,
        "remover": corte.remover, "correcoes": [c.model_dump() for c in corte.correcoes], "gancho": corte.gancho,
        "legenda_post": corte.legenda_post, "hashtags": list(corte.hashtags),
        "direcao": direcao.valida(corte.direcao, list(llm.presets_disponiveis())),
        "config": {}, "palavras_editadas": {}, "status": "fila", "arquivo": None, "thumb": None,
        "duracao": round(corte.fim - corte.inicio, 2), "versao": 0,
    }


# ================================================================ projeto completo

def processar(pid: str, cancelado=None, imprimir: bool = False) -> dict:
    meta = projetos.ler(pid)
    prog = Progresso(pid, imprimir)
    video = meta["video"]

    # Continuando depois de um erro/cancelamento: os clipes da rodada anterior que saírem iguais
    # (as respostas do Claude vêm do cache do projeto) não são cortados nem renderizados de novo
    retomar = bool(meta.get("retomar"))
    antigos = {c["id"]: c for c in meta.get("clips", [])} if retomar else {}

    def inicio(m):
        m.update(status="processando", iniciado_em=time.time(), erro=None, progresso=0.0, etapas={}, avisos=[])
    projetos.atualizar(pid, inicio)
    aviso_disco(pid)
    baixou = baixar_se_link(pid, meta, prog, cancelado)

    info = ef.sondar(video)
    if not (config.PASTA_PROJETOS / pid / "thumb.jpg").exists():
        ef.extrair_frame(video, info["duracao"] * 0.1, projetos.pasta(pid) / "thumb.jpg", largura=640)
    projetos.atualizar(pid, lambda m: m.update(
        duracao_video=info["duracao"], resolucao=f"{info['largura']}x{info['altura']}",
        saida_dir=m.get("saida_dir") or str(projetos.pasta_saida_para(m["nome"], pid))))

    saida_dir = Path(projetos.ler(pid)["saida_dir"])
    if not retomar:  # Refazendo do zero: apaga os clipes antigos para não sobrar arquivo de outra rodada
        for antigo in saida_dir.glob("clip_*.mp4"):
            antigo.unlink(missing_ok=True)
        projetos.atualizar(pid, lambda m: m.update(clips=[]))

    # 1. Transcrição (também no gameplay: captura os comentários do jogador)
    if not baixou:
        prog.etapa("transcrevendo")
    transcricao = tr.transcrever(video, progresso_apos_download(prog, baixou), cancelado)

    # 2. Plano + análise de áudio
    prog.etapa("analisando")
    plano = _plano(meta, pid)
    prog(0.4, "Plano de edição pronto")
    analise = None
    if meta["modo"] == "gameplay":
        analise = analise_audio.analisar(video, lambda p, d="": prog(0.4 + 0.6 * p, d), cancelado)
    projetos.atualizar(pid, lambda m: m.update(plano=plano.model_dump(), nao_atendido=list(plano.nao_atendido)))
    if plano.nao_atendido:
        log.warning("Não atendido: %s", "; ".join(plano.nao_atendido))

    # 3. Escolha dos trechos
    prog.etapa("escolhendo")
    if meta["modo"] == "gameplay":
        cortes = _cortes_gameplay(video, transcricao, analise, plano, pid,
                                  ver_imagens=meta["opcoes"].get("ver_imagens", True), cancelado=cancelado,
                                  progresso=prog)
    else:
        cortes = _cortes_falado(transcricao, plano, pid, progresso=prog)
    if not cortes:
        llm.esquecer_respostas(pid)  # tentar de novo deve perguntar de novo, não repetir a mesma resposta
        raise ValueError("Nenhum trecho adequado foi encontrado.")
    if len(cortes) < plano.num_clips:
        _aviso(pid, f"Só encontrei conteúdo bom para {len(cortes)} de {plano.num_clips} clipe(s) de "
                    f"{plano.duracao_min:.0f}-{plano.duracao_max:.0f} s sem repetir trechos. Para mais clipes, "
                    "use um vídeo mais longo ou uma duração menor.")
    cortes.sort(key=lambda c: c.nota, reverse=True)
    clips = [_novo_clip(f"clip_{i:02d}", c) for i, c in enumerate(cortes, 1)]
    prontos = sum(_reaproveitar(c, antigos.get(c["id"])) for c in clips)
    if retomar:
        manter = {f"{c['id']}.mp4" for c in clips if c["status"] == "pronto"}
        for antigo in saida_dir.glob("clip_*.mp4"):
            if antigo.name not in manter:
                antigo.unlink(missing_ok=True)
        if prontos:
            log.info("Continuando: %d de %d clipe(s) já estavam prontos", prontos, len(clips))
    projetos.atualizar(pid, lambda m: m.update(clips=clips))

    # 4 e 5. Corte e render de cada clipe
    n = len(clips)
    prog.etapa("cortando")
    if n > MUITOS_CLIPES:
        # Muitos clipes: corta e renderiza um de cada vez e apaga os intermediários logo em seguida
        # (70 cortes intermediários juntos ocupariam ~4 GB). Os primeiros clipes já ficam prontos para ver.
        prog.etapa("legendando")
        for k, c in enumerate(clips):
            if cancelado is not None and cancelado.is_set():
                raise Cancelado()
            if c["status"] == "pronto":
                continue
            _cortar_so(pid, c["id"], transcricao, lambda p, k=k: prog((k + 0.3 * p) / n, f"Clipe {k + 1} de {n}"),
                       cancelado)
            renderizar_clip(pid, c["id"], transcricao,
                            lambda p, k=k: prog((k + 0.3 + 0.7 * p) / n, f"Clipe {k + 1} de {n}"), cancelado)
            for intermediario in (projetos.pasta(pid) / "tmp").glob(f"{c['id']}_*.mp4"):
                intermediario.unlink(missing_ok=True)
    else:
        for k, c in enumerate(clips):
            if cancelado is not None and cancelado.is_set():
                raise Cancelado()
            if c["status"] != "pronto":
                _cortar_so(pid, c["id"], transcricao, lambda p, k=k: prog((k + p) / n, f"Clipe {k + 1} de {n}"), cancelado)
        prog.etapa("legendando")
        for k, c in enumerate(clips):
            if c["status"] != "pronto":
                renderizar_clip(pid, c["id"], transcricao, lambda p, k=k: prog((k + p) / n, f"Clipe {k + 1} de {n}"), cancelado)

    prog.finalizar()
    custo = sum(h["custo"] for h in custos.resumo()["historico"] if h.get("projeto") == pid)
    return projetos.atualizar(pid, lambda m: m.update(status="pronto", custo=round(custo, 5), terminado_em=time.time()))


# Campos que definem o resultado de um clipe (decididos pelo Claude ou pelo plano local)
CAMPOS_CLIP = ("inicio", "fim", "titulo", "remover", "correcoes", "gancho", "clima", "emojis", "palavras_enfase", "pico",
               "direcao")


def _reaproveitar(novo: dict, antigo: dict | None) -> bool:
    """Ao continuar um processamento: se o clipe saiu igual ao da rodada anterior (e não foi editado à
    mão), reaproveita o corte já feito e, se o arquivo final ainda existe, o clipe pronto."""
    if not antigo or antigo.get("config") or antigo.get("palavras_editadas"):
        return False
    def comparavel(v):  # o clipe novo tem tuplas; o salvo no meta.json, listas
        return json.loads(json.dumps(v, default=str))
    if any(comparavel(novo.get(k)) != comparavel(antigo.get(k)) for k in CAMPOS_CLIP):
        return False
    if antigo.get("corte_assinatura"):
        novo["corte_assinatura"] = antigo["corte_assinatura"]  # _cortar_so confere com o arquivo em tmp/
    if antigo.get("status") != "pronto" or not antigo.get("arquivo") or not Path(antigo["arquivo"]).exists():
        return False
    for k in ("trechos", "arquivo", "thumb", "duracao", "versao", "layout_usado", "legenda_usada"):
        if k in antigo:
            novo[k] = antigo[k]
    novo.update(status="pronto", erro=None)
    return True


def _cortar_so(pid, cid, transcricao, progresso, cancelado):
    """Faz só o corte (etapa 'Cortando'); o render reaproveita o arquivo (mesma assinatura)."""
    meta = projetos.ler(pid)
    clip = projetos.clip(meta, cid)
    cfg = config_clip(meta, clip)
    palavras = _aplicar_correcoes(_palavras_editadas(transcricao, clip), clip.get("correcoes"),
                                  clip["inicio"], clip["fim"])
    p = _preparar_corte(meta, clip, cfg, palavras, pid, cid)
    corte = projetos.pasta(pid) / "tmp" / f"{cid}_corte.mp4"
    if corte.exists() and clip.get("corte_assinatura") == p["assinatura"]:
        projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(status="cortado"))
        return
    ef.cortar(meta["video"], p["trechos"], corte, normalizar=cfg["normalizar"], musica=cfg["musica"],
              efeitos=p["efeitos"], abertura=p["abertura"], limpar_voz=cfg["limpar_voz"],
              progresso=progresso, cancelado=cancelado)
    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(corte_assinatura=p["assinatura"], status="cortado"))


# ================================================================ ações sobre clipes prontos

def regenerar_clip(pid: str, cid: str, progresso=None, cancelado=None) -> dict:
    """Troca o clipe por OUTRO momento do vídeo (que ainda não virou clipe)."""
    meta = projetos.ler(pid)
    plano = PlanoEdicao.model_validate(meta["plano"])
    transcricao = tr.transcrever(meta["video"])
    ocupados = [(c["inicio"], c["fim"]) for c in meta["clips"]] + meta.get("descartados", [])
    if meta["modo"] == "gameplay":
        analise = analise_audio.analisar(meta["video"])
        novos = _cortes_gameplay(meta["video"], transcricao, analise, plano, pid, excluir=ocupados, quantidade=1,
                                 ver_imagens=meta["opcoes"].get("ver_imagens", True), cancelado=cancelado)
    else:
        novos = _cortes_falado(transcricao, plano, pid, excluir=ocupados, quantidade=1)
    if not novos:
        raise ValueError("Não encontrei outro trecho bom que ainda não tenha virado clipe.")
    novo = _novo_clip(cid, novos[0])

    def f(m):
        antigo = projetos.clip(m, cid)
        m.setdefault("descartados", []).append((antigo["inicio"], antigo["fim"]))
        novo["config"] = antigo.get("config", {})  # mantém as preferências visuais
        m["clips"] = [novo if c["id"] == cid else c for c in m["clips"]]
    projetos.atualizar(pid, f)
    return renderizar_clip(pid, cid, transcricao, progresso, cancelado)


def aplicar_ajuste(pid: str, pedido: str, cids: list[str], progresso=None, cancelado=None) -> dict:
    """Pedido em linguagem natural aplicado aos clipes selecionados."""
    meta = projetos.ler(pid)
    selecionados = [c for c in meta["clips"] if c["id"] in cids]
    try:
        ajuste = llm.interpretar_ajuste(pedido, selecionados, pid)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        ajuste = local.interpretar_ajuste(pedido, selecionados)
    transcricao = tr.transcrever(meta["video"])

    def f(m):
        for c in m["clips"]:
            if c["id"] not in cids:
                continue
            cfg = c.setdefault("config", {})
            mapa = {"cor_legenda": "cor", "preset": "preset", "estilo_legenda": "estilo", "legenda_ativa": "legenda_ativa",
                    "titulo_ativo": "titulo_ativo", "zoom_em_enfase": "zoom", "remover_silencios": "remover_silencios",
                    "normalizar_audio": "normalizar", "formato": "formato", "efeitos_sonoros": "efeitos",
                    "limpar_voz": "limpar_voz"}
            for campo, chave in mapa.items():
                valor = getattr(ajuste, campo)
                if valor is not None:
                    cfg[chave] = valor
            if ajuste.novo_titulo:
                c["titulo"] = ajuste.novo_titulo
            if ajuste.duracao_alvo:
                c["inicio"], c["fim"] = _nova_duracao(c, ajuste.duracao_alvo, transcricao, m["duracao_video"])
            c["status"] = "fila"
    projetos.atualizar(pid, f)
    for k, cid in enumerate(cids):
        renderizar_clip(pid, cid, transcricao,
                        (lambda p, k=k: progresso((k + p) / len(cids))) if progresso else None, cancelado)
    return {"ajuste": ajuste.model_dump(), "nao_atendido": ajuste.nao_atendido}


def _nova_duracao(clip: dict, alvo: float, transcricao: dict, duracao_video: float) -> tuple[float, float]:
    """Mantém o início (o gancho) e procura um fim de frase perto da nova duração.
    No gameplay mantém o pico dentro do clipe."""
    inicio = clip["inicio"]
    if clip.get("pico") is not None and not transcricao["palavras"]:
        inicio = max(0.0, clip["pico"] - alvo * 0.6)
        return round(inicio, 2), round(min(duracao_video, inicio + alvo), 2)
    candidatas = [w for w in transcricao["palavras"] if w["f"] > inicio and w["f"] - inicio <= alvo * 1.1]
    frases = [w for w in candidatas if w["p"].rstrip().endswith((".", "!", "?")) and w["f"] - inicio >= alvo * 0.7]
    escolhida = (frases or candidatas or [None])[-1]
    fim = escolhida["f"] + 0.25 if escolhida else inicio + alvo
    return round(inicio, 2), round(min(duracao_video, fim), 2)
