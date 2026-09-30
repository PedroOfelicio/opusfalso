"""
Análise de áudio para o modo Gameplay: encontra picos de energia
(explosões, tiros, gritos, risadas) combinando dois sinais:

- volume (RMS em dB), bom para gritos e momentos intensos longos
- fluxo espectral (quanto o espectro "muda" de repente), bom para tiros e explosões

O resultado fica em cache (DADOS/cache/<hash>/audio.json).
"""
import logging

import numpy as np

import config
from config import Cancelado
from editor_ffmpeg import ler_audio
from transcricao import palavras_no_intervalo, pasta_cache

log = logging.getLogger("audio")

TAXA = 11025        # suficiente para energia; bem mais leve que 44.1 kHz
PASSO = 0.05        # resolução de 50 ms


def _suavizar(x: np.ndarray, segundos: float) -> np.ndarray:
    n = max(1, int(segundos / PASSO))
    return np.convolve(x, np.ones(n) / n, mode="same")


def _zscore(x: np.ndarray) -> np.ndarray:
    return (x - np.median(x)) / (np.std(x) + 1e-9)


def analisar(video, progresso=None, cancelado=None) -> dict:
    arq = pasta_cache(video) / "audio.json"
    em_cache = config.ler_json(arq)
    if em_cache:
        log.info("Análise de áudio encontrada no cache (%d picos)", len(em_cache["picos"]))
        return em_cache

    audio = ler_audio(video, TAXA)
    if cancelado is not None and cancelado.is_set():
        raise Cancelado()
    tam = int(TAXA * PASSO)
    n = len(audio) // tam
    if n < 20:
        raise ValueError("Áudio curto demais para análise")
    quadros = audio[: n * tam].reshape(n, tam)

    # Volume em dB
    rms = np.sqrt(np.mean(quadros ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)

    # Fluxo espectral, em blocos para não estourar memória em vídeos longos
    janela = np.hanning(tam)
    fluxo = np.zeros(n)
    anterior = None
    for ini in range(0, n, 4000):
        mag = np.abs(np.fft.rfft(quadros[ini:ini + 4000] * janela, axis=1))
        mag = np.log1p(mag)
        if anterior is not None:
            mag_ext = np.vstack([anterior[None], mag])
        else:
            mag_ext = np.vstack([mag[:1], mag])
        fluxo[ini:ini + len(mag)] = np.maximum(np.diff(mag_ext, axis=0), 0).sum(axis=1)
        anterior = mag[-1]
        if progresso:
            progresso(min((ini + 4000) / n, 1.0), "Analisando energia do áudio")
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()

    energia = 0.6 * _zscore(_suavizar(db, 0.5)) + 0.4 * _zscore(_suavizar(fluxo, 0.3))
    energia_1s = _suavizar(energia, 1.0)

    # Picos: máximos locais acima do percentil 85, com pelo menos 6 s entre eles
    limite = max(np.percentile(energia_1s, 85), 0.8)
    distancia = int(6 / PASSO)
    ordem = np.argsort(energia_1s)[::-1]
    picos, ocupado = [], np.zeros(n, dtype=bool)
    for idx in ordem:
        if energia_1s[idx] < limite:
            break
        if ocupado[idx]:
            continue
        picos.append({"t": round(float(idx * PASSO), 2), "score": round(float(energia_1s[idx]), 3)})
        ocupado[max(0, idx - distancia): idx + distancia] = True
        if len(picos) >= 60:
            break

    # Curva de 1 em 1 s (0-100), útil para a interface
    passos_1s = int(1 / PASSO)
    curva = energia_1s[::passos_1s]
    curva = np.clip((curva - curva.min()) / (np.ptp(curva) + 1e-9) * 100, 0, 100)

    resultado = {
        "duracao": round(n * PASSO, 2),
        "picos": picos,
        "curva": [round(float(v), 1) for v in curva],
        "db_medio": round(float(np.median(db)), 1),
    }
    config.gravar_json(arq, resultado)
    log.info("Áudio analisado: %d picos encontrados", len(picos))
    return resultado


PALAVRAS_REACAO = {"caraca", "nossa", "meu", "deus", "mano", "kkk", "kkkk", "caramba", "vai", "morreu",
                   "matei", "pegou", "não", "nao", "socorro", "vamo", "vamos", "boa", "insano", "absurdo"}


def candidatos_gameplay(analise: dict, transcricao: dict | None, dmin: float, dmax: float,
                        maximo: int = 15, excluir=None) -> list[dict]:
    """Transforma picos em janelas de clipe, com margem antes (preparação)
    e depois (reação). O pico fica em ~60% do clipe."""
    duracao_video = analise["duracao"]
    dmin, dmax = min(dmin, duracao_video), min(dmax, duracao_video)
    alvo = (dmin + dmax) / 2
    picos = analise["picos"]
    if not picos:
        return []
    scores = np.array([p["score"] for p in picos])
    ocupados = list(excluir or [])
    candidatos = []
    for p in picos:
        inicio = max(0.0, p["t"] - alvo * 0.6)
        fim = min(duracao_video, inicio + alvo)
        inicio = max(0.0, fim - alvo)
        if any(min(fim, b) - max(inicio, a) > 0.3 * alvo for a, b in ocupados):
            continue
        dentro = [q for q in picos if inicio <= q["t"] <= fim]
        # energia 0-100: posição relativa do pico entre todos + bônus por vários picos seguidos
        energia = float((scores <= p["score"]).mean() * 85 + min(len(dentro) - 1, 3) * 5)
        fala = ""
        if transcricao:
            palavras = palavras_no_intervalo(transcricao, inicio, fim)
            fala = " ".join(w["p"] for w in palavras)
            reacoes = sum(1 for w in palavras if w["p"].lower().strip(".,!?") in PALAVRAS_REACAO)
            energia += min(reacoes * 3, 10)
            # Não corta no meio de uma palavra
            cruzando = [w for w in transcricao["palavras"] if w["i"] < fim < w["f"]]
            if cruzando:
                fim = min(duracao_video, cruzando[0]["f"] + 0.2)
        candidatos.append({
            "id": len(candidatos) + 1, "inicio": round(float(inicio), 2), "fim": round(float(fim), 2), "pico": p["t"],
            "energia": round(min(energia, 100), 1), "picos": len(dentro), "fala": fala,
        })
        ocupados.append((inicio, fim))
        if len(candidatos) >= maximo:
            break
    return candidatos
