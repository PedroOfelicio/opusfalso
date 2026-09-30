"""
Tudo que fala com o FFmpeg: leitura de informações, extração de áudio/frames,
cortes (com remoção de silêncios e vícios), normalização e música de fundo.
"""
import functools
import logging
import re
import subprocess
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("ffmpeg")

FPS_SAIDA = 30

# Janela do console não deve piscar ao chamar o ffmpeg a partir da API no Windows
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ErroFFmpeg(RuntimeError):
    pass


from config import Cancelado  # noqa: E402  (mesma exceção em todo o pipeline)


# ---------------------------------------------------------------- informações

def sondar(caminho: str | Path) -> dict:
    """Duração, resolução, fps e se tem áudio (via ffprobe)."""
    import json
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(caminho)],
        capture_output=True, text=True, encoding="utf-8", creationflags=_SEM_JANELA,
    )
    if saida.returncode != 0:
        raise ErroFFmpeg(f"Não consegui ler o vídeo: {saida.stderr.strip()[-300:]}")
    dados = json.loads(saida.stdout)
    video = next((s for s in dados["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in dados["streams"] if s["codec_type"] == "audio"), None)
    if not video:
        raise ErroFFmpeg("O arquivo não tem trilha de vídeo")
    num, den = (video.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    largura, altura = int(video["width"]), int(video["height"])
    # Vídeos de celular podem vir com rotação nos metadados
    rotacao = 0
    for sd in video.get("side_data_list", []):
        if "rotation" in sd:
            rotacao = abs(int(sd["rotation"]))
    if rotacao in (90, 270):
        largura, altura = altura, largura
    return {
        "duracao": float(dados["format"].get("duration", 0)),
        "largura": largura, "altura": altura, "fps": fps or 30.0,
        "tem_audio": audio is not None,
    }


def ler_audio(caminho: str | Path, taxa: int = 16000, inicio: float | None = None,
              duracao: float | None = None) -> np.ndarray:
    """Decodifica o áudio em mono float32 (usado pelo Whisper e pela análise de picos)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error"]
    if inicio is not None:
        cmd += ["-ss", f"{inicio:.3f}"]
    if duracao is not None:
        cmd += ["-t", f"{duracao:.3f}"]
    cmd += ["-i", str(caminho), "-vn", "-ac", "1", "-ar", str(taxa), "-f", "f32le", "-"]
    saida = subprocess.run(cmd, capture_output=True, creationflags=_SEM_JANELA)
    if saida.returncode != 0:
        raise ErroFFmpeg(f"Falha ao extrair áudio: {saida.stderr.decode(errors='ignore')[-300:]}")
    return np.frombuffer(saida.stdout, dtype=np.float32).copy()


@functools.lru_cache(maxsize=1)
def encoder_video() -> tuple[str, ...]:
    """Usa NVENC (GPU NVIDIA) se funcionar; senão libx264."""
    teste = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
        capture_output=True, creationflags=_SEM_JANELA,
    )
    if teste.returncode == 0:
        log.info("Encoder de vídeo: h264_nvenc (GPU)")
        return ("-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0", "-pix_fmt", "yuv420p")
    log.info("Encoder de vídeo: libx264 (CPU)")
    return ("-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p")


# ---------------------------------------------------------------- execução

def rodar(args: list[str], duracao: float | None = None, progresso=None, cancelado=None, cwd=None) -> None:
    """Roda o ffmpeg reportando progresso (0-1) e permitindo cancelar."""
    cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"] + args
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                            text=True, encoding="utf-8", errors="ignore", creationflags=_SEM_JANELA)
    try:
        for linha in proc.stdout:
            if cancelado is not None and cancelado.is_set():
                proc.kill()
                raise Cancelado()
            if progresso and duracao and linha.startswith("out_time_us="):
                valor = linha.split("=", 1)[1].strip()
                if valor.isdigit():
                    progresso(min(int(valor) / 1e6 / duracao, 1.0))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        erro = proc.stderr.read()[-800:]
        raise ErroFFmpeg(f"FFmpeg falhou (código {proc.returncode}): {erro}")


def extrair_frame(video: str | Path, tempo: float, saida: str | Path, largura: int = 480) -> Path:
    """Salva um JPG (thumbnail)."""
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{max(tempo, 0):.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={largura}:-2", "-q:v", "4", str(saida)],
        capture_output=True, creationflags=_SEM_JANELA,
    )
    return saida


# ---------------------------------------------------------------- silêncios e vícios

VICIOS_SEMPRE = {"hum", "hmm", "hm", "humm", "ãh", "ã", "ah", "ahn", "eh", "éh", "uh", "um", "uhm", "hã", "han", "ééé"}
VICIOS_COM_PAUSA = {"é", "tipo", "né", "então"}  # só são vício quando isolados por pausas


def _limpa(p: str) -> str:
    return re.sub(r"[^\wÀ-ÿ]", "", p.lower())


def _eh_vicio(palavras: list[dict], idx: int) -> bool:
    w = palavras[idx]
    limpa = _limpa(w["p"])
    if limpa in VICIOS_SEMPRE:
        return True
    if limpa in VICIOS_COM_PAUSA:
        antes = w["i"] - palavras[idx - 1]["f"] if idx > 0 else 1
        depois = palavras[idx + 1]["i"] - w["f"] if idx + 1 < len(palavras) else 1
        return antes >= 0.25 and depois >= 0.25
    return False


def intervalos_de_fala(palavras: list[dict], inicio: float, fim: float, pausa_max: float = 0.6,
                       folga: float = 0.12, remover_vicios: bool = True) -> list[tuple[float, float]]:
    """Divide [inicio, fim] em trechos com fala, removendo pausas longas e vícios.
    Retorna intervalos no tempo do vídeo original."""
    ws = [w for w in palavras if w["i"] >= inicio - 0.05 and w["f"] <= fim + 0.05]
    if not ws:
        return [(inicio, fim)]
    trechos, a, b = [], None, None
    forcar, pend_ini, pend_fim = False, None, None
    for idx, w in enumerate(ws):
        if remover_vicios and _eh_vicio(ws, idx):
            if pend_ini is None:
                pend_ini = w["i"]
            pend_fim, forcar = w["f"], True
            continue
        if a is None:
            a = max(inicio, w["i"] - folga, pend_fim or 0)
        else:
            gap = w["i"] - b
            if forcar or gap > pausa_max:
                fecha = b + min(folga, gap / 2)
                abre = w["i"] - min(folga, gap / 2)
                if forcar:
                    fecha, abre = min(fecha, pend_ini), max(abre, pend_fim)
                trechos.append((a, fecha))
                a = abre
        b = w["f"]
        forcar, pend_ini, pend_fim = False, None, None
    trechos.append((a, min(fim, b + folga + 0.15)))
    return [(round(x, 3), round(y, 3)) for x, y in trechos if y - x > 0.05]


def mapear_tempo(t: float, trechos: list[tuple[float, float]]) -> float | None:
    """Converte um tempo do vídeo original para o tempo do clipe cortado.
    Retorna None se o instante foi removido."""
    acumulado = 0.0
    for a, b in trechos:
        if t < a:
            return None
        if t <= b:
            return acumulado + (t - a)
        acumulado += b - a
    return None


def duracao_trechos(trechos) -> float:
    return sum(b - a for a, b in trechos)


# ---------------------------------------------------------------- corte

def cortar(video: str | Path, trechos: list[tuple[float, float]], saida: str | Path,
           normalizar: bool = True, musica: str | None = None, info: dict | None = None,
           progresso=None, cancelado=None) -> Path:
    """Gera um clipe com os trechos concatenados (vídeo em resolução original, 30 fps).
    O enquadramento e a legenda são feitos depois, em cima deste arquivo."""
    info = info or sondar(video)
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    base = trechos[0][0]
    total = trechos[-1][1] - base
    duracao_final = duracao_trechos(trechos)

    # Com -ss antes do -i o tempo recomeça em 0; os trechos viram relativos a "base"
    sel = "+".join(f"between(t,{a - base:.3f},{b - base:.3f})" for a, b in trechos)
    filtros = [f"[0:v]fps={FPS_SAIDA},select='{sel}',setpts=N/{FPS_SAIDA}/TB[v]"]

    entradas = ["-ss", f"{base:.3f}", "-t", f"{total + 0.1:.3f}", "-i", str(video)]
    if info["tem_audio"]:
        filtros.append(f"[0:a]aselect='{sel}',asetpts=N/SR/TB,aresample=48000[a0]")
    else:
        entradas += ["-f", "lavfi", "-t", f"{duracao_final:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        filtros.append("[1:a]anull[a0]")
    atual = "a0"
    if normalizar:
        # Padrão das redes sociais: -14 LUFS
        filtros.append(f"[{atual}]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[an]")
        atual = "an"
    if musica and Path(musica).exists():
        idx = len([x for x in entradas if x == "-i"])
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
        # "Ducking": a música abaixa sozinha quando há voz
        filtros.append(f"[{atual}]asplit=2[voz][sc]")
        filtros.append(f"[{idx}:a]volume=0.35,aresample=48000[mus]")
        filtros.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[musd]")
        filtros.append("[voz][musd]amix=inputs=2:duration=first:normalize=0[am]")
        atual = "am"

    args = entradas + [
        "-filter_complex", ";".join(filtros),
        "-map", "[v]", "-map", f"[{atual}]",
        *encoder_video(), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{duracao_final:.3f}", "-movflags", "+faststart", str(saida),
    ]
    rodar(args, duracao=duracao_final, progresso=progresso, cancelado=cancelado)
    return saida
