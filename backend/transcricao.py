"""
Transcrição local com faster-whisper (timestamp por palavra).

- Usa a GPU (CUDA) se disponível; se faltar memória ou der erro, cai para um
  modelo menor e por fim para a CPU.
- Cache: o resultado fica em DADOS/cache/<hash_do_video>/transcricao.json e
  nunca é refeito para o mesmo arquivo.

Formato salvo:
{
  "idioma": "pt", "duracao": 139.1, "modelo": "large-v3-turbo",
  "segmentos": [{"inicio": 0.0, "fim": 4.2, "texto": "..."}],
  "palavras":  [{"p": "Olá,", "i": 0.0, "f": 0.4}]
}
"""
import hashlib
import threading
import logging
import os
import site
import sys
import time
from pathlib import Path

import config
from config import Cancelado
from editor_ffmpeg import ler_audio

log = logging.getLogger("transcricao")

_modelo_cache = {"chave": None, "modelo": None}


def _preparar_dlls_cuda():
    """No Windows, as DLLs do cuBLAS/cuDNN instaladas via pip ficam em
    site-packages/nvidia/*/bin. Adiciona essas pastas ao PATH do processo."""
    if sys.platform != "win32":
        return
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        nvidia = Path(base) / "nvidia"
        if not nvidia.exists():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]


_preparar_dlls_cuda()


def hash_arquivo(caminho: str | Path) -> str:
    """Hash rápido: tamanho + 3 pedaços de 1 MB (início, meio, fim).
    Suficiente para identificar o mesmo vídeo sem ler gigabytes."""
    caminho = Path(caminho)
    tamanho = caminho.stat().st_size
    h = hashlib.sha1(str(tamanho).encode())
    with open(caminho, "rb") as f:
        for pos in (0, tamanho // 2, max(0, tamanho - 1_048_576)):
            f.seek(pos)
            h.update(f.read(1_048_576))
    return h.hexdigest()[:16]


_trava_indice = threading.Lock()


def pasta_cache(caminho_video: str | Path) -> Path:
    """Pasta de cache do vídeo (transcrição, análise de áudio), pelo conteúdo do arquivo. Guarda também
    caminho -> hash: um vídeo baixado por link e já apagado continua achando a transcrição dele."""
    caminho = Path(caminho_video)
    arq_indice = config.PASTA_CACHE / "indice_videos.json"
    if caminho.exists():
        chave = hash_arquivo(caminho)
        with _trava_indice:
            indice = config.ler_json(arq_indice, {}) or {}
            if indice.get(str(caminho)) != chave:
                indice[str(caminho)] = chave
                config.gravar_json(arq_indice, indice)
    else:
        chave = (config.ler_json(arq_indice, {}) or {}).get(str(caminho))
        if not chave:
            raise FileNotFoundError(f"Vídeo não encontrado: {caminho}")
    pasta = config.PASTA_CACHE / chave
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def gpu_disponivel() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _tentativas(nome: str, usar_gpu: bool):
    """Ordem de tentativas: (modelo, dispositivo, tipo de cálculo)."""
    lista = []
    if usar_gpu and gpu_disponivel():
        # int8_float16 cabe numa GPU de 4 GB com folga
        lista.append((nome, "cuda", "int8_float16"))
        if nome != "medium":
            lista.append(("medium", "cuda", "int8_float16"))
    lista.append((nome, "cpu", "int8"))
    return lista


def _carregar_modelo(nome: str, dispositivo: str, tipo: str):
    from faster_whisper import WhisperModel
    chave = (nome, dispositivo, tipo)
    if _modelo_cache["chave"] != chave:
        log.info("Carregando Whisper '%s' em %s (%s)...", nome, dispositivo, tipo)
        _modelo_cache["modelo"] = None  # libera o anterior antes de carregar outro
        _modelo_cache["modelo"] = WhisperModel(nome, device=dispositivo, compute_type=tipo,
                                               download_root=str(config.PASTA_MODELOS / "whisper"))
        _modelo_cache["chave"] = chave
    return _modelo_cache["modelo"]


def transcrever(caminho_video: str | Path, progresso=None, cancelado=None) -> dict:
    """Transcreve (ou lê do cache). progresso(pct 0-1, msg) é opcional."""
    caminho_video = Path(caminho_video)
    arq_cache = pasta_cache(caminho_video) / "transcricao.json"
    em_cache = config.ler_json(arq_cache)
    if em_cache:
        log.info("Transcrição encontrada no cache (%s palavras)", len(em_cache["palavras"]))
        if progresso:
            progresso(1.0, "Transcrição em cache")
        return em_cache

    cfg = config.carregar()
    idioma = cfg.get("idioma") or None
    ultimo_erro = None
    for nome, dispositivo, tipo in _tentativas(cfg["modelo_whisper"], cfg["usar_gpu"]):
        try:
            resultado = _executar(caminho_video, nome, dispositivo, tipo, idioma, progresso, cancelado)
            config.gravar_json(arq_cache, resultado)
            return resultado
        except Cancelado:
            raise
        except Exception as e:  # falta de memória na GPU, DLL ausente etc.
            ultimo_erro = e
            log.warning("Falhou com %s/%s: %s. Tentando alternativa...", nome, dispositivo, e)
            _modelo_cache.update(chave=None, modelo=None)
    raise RuntimeError(f"Não foi possível transcrever: {ultimo_erro}")


def _executar(caminho_video, nome, dispositivo, tipo, idioma, progresso, cancelado) -> dict:
    modelo = _carregar_modelo(nome, dispositivo, tipo)
    t0 = time.time()
    # Decodificamos com o FFmpeg (mais robusto que o PyAV embutido) e passamos o array
    audio = ler_audio(caminho_video, 16000)
    segmentos_iter, info = modelo.transcribe(
        audio,
        language=idioma,
        word_timestamps=True,
        vad_filter=True,                   # pula trechos sem voz (mais rápido)
        beam_size=5,
        condition_on_previous_text=False,  # evita "loops" de alucinação
    )
    log.info("Idioma: %s (%.0f%%), duração %.1fs", info.language, info.language_probability * 100, info.duration)

    segmentos, palavras = [], []
    for seg in segmentos_iter:  # o gerador transcreve sob demanda
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()
        segmentos.append({"inicio": round(float(seg.start), 2), "fim": round(float(seg.end), 2), "texto": seg.text.strip()})
        for w in seg.words or []:
            texto = w.word.strip()
            if texto:
                palavras.append({"p": texto, "i": round(float(w.start), 3), "f": round(float(w.end), 3)})
        if progresso and info.duration:
            progresso(min(seg.end / info.duration, 1.0), f"{seg.end:.0f}s de {info.duration:.0f}s")

    log.info("Transcrito em %.1fs: %d segmentos, %d palavras", time.time() - t0, len(segmentos), len(palavras))
    return {
        "idioma": info.language, "duracao": round(float(info.duration), 2), "modelo": nome,
        "dispositivo": dispositivo, "segmentos": segmentos, "palavras": palavras,
    }


def palavras_no_intervalo(transcricao: dict, inicio: float, fim: float) -> list[dict]:
    """Palavras cujo meio cai dentro de [inicio, fim]."""
    return [w for w in transcricao["palavras"] if inicio <= (w["i"] + w["f"]) / 2 <= fim]
