"""
Tudo que fala com o FFmpeg: leitura de informações, extração de áudio/frames,
cortes (com remoção de silêncios e vícios), normalização e música de fundo.
"""
import functools
import logging
import re
import subprocess
import threading
from pathlib import Path

import numpy as np

import config

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


def encoder_video(leve: bool = False) -> tuple[str, ...]:
    """Usa NVENC (GPU NVIDIA) se funcionar; senão libx264. leve=True (clipe final para as redes):
    qualidade um pouco menor e teto de 8 Mbps; um clipe de 34 s cai de ~50 MB para ~20-30 MB."""
    base = _encoder_base()
    if not leve:
        return base
    if base[1] == "h264_nvenc":
        return ("-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "6M", "-maxrate", "8M",
                "-bufsize", "16M", "-pix_fmt", "yuv420p")
    return ("-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
            "-pix_fmt", "yuv420p")


@functools.lru_cache(maxsize=1)
def _encoder_base() -> tuple[str, ...]:
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


def mapear_intervalo(i: float, f: float, partes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Todas as posições (no tempo do clipe) de um intervalo do vídeo original. Com a abertura
    com o clímax, o mesmo instante aparece duas vezes: no começo e no lugar dele."""
    saida, acumulado = [], 0.0
    for a, b in partes:
        x, y = max(i, a), min(f, b)
        if y > x or (i == f and a <= i <= b):
            saida.append((acumulado + x - a, acumulado + y - a))
        acumulado += b - a
    return saida


# "Melhorar a voz" (tudo local): tira ronco/zumbido (passa-alta íngreme em 90 Hz), reduz o ruído de fundo
# (afftdn acompanhando o ruído), abaixa o ruído que sobra nas pausas (expansor suave: -12 dB no máximo,
# só abaixo de -45 dB, longe do nível de fala), tira o "abafado" (-2 dB em 250 Hz), dá presença (+2,5 dB
# em 3,5 kHz), suaviza o "s" e comprime de leve. Num teste com ruído de sala: ruído nas pausas -45 -> -73 dB,
# fala no mesmo nível.
CADEIA_VOZ = ("highpass=f=90:p=2,highpass=f=90:p=2,afftdn=nr=20:nf=-50:tn=1,"
              "agate=threshold=0.0056:ratio=2:attack=10:release=250:range=0.25,"
              "equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3500:t=q:w=1.2:g=2.5,deesser=i=0.35,"
              "acompressor=threshold=0.09:ratio=3:attack=10:release=150:makeup=1.6")


# ---------------------------------------------------------------- música de fundo

ALVO_MUSICA_LUFS = -14.0   # cada faixa é levada a este volume antes do volume relativo (0.35 / 0.22)
TROCA_MUSICA = 3.0         # crossfade (s) quando a faixa troca no começo de um capítulo
_ARQ_MEDIDAS = config.DADOS / "cache" / "musicas.json"
_trava_medidas = threading.Lock()
VERSAO_MEDIDA = 3          # sobe quando a medição muda (as medidas antigas são refeitas)


def medir_musica(arquivo: str | Path) -> dict:
    """Volume integrado (LUFS, EBU R128), onde a faixa "começa de verdade" (pula introdução quase em
    silêncio, que num clipe de 30 s seria metade do tempo sem música) e a batida (período, fase e
    confiança, para os cortes caírem no ritmo). Medido uma vez por arquivo."""
    p = Path(arquivo)
    try:
        st = p.stat()
    except OSError:
        return {"lufs": ALVO_MUSICA_LUFS, "inicio": 0.0}
    chave = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    with _trava_medidas:
        medidas = config.ler_json(_ARQ_MEDIDAS, {}) or {}
    if chave in medidas and medidas[chave].get("v") == VERSAO_MEDIDA:
        return medidas[chave]
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", str(p), "-vn",
                        "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_SEM_JANELA)
    achados = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)
    lufs = float(achados[-1]) if achados else ALVO_MUSICA_LUFS
    inicio, batida = 0.0, {}
    try:
        taxa = 11025
        x = ler_audio(p, taxa=taxa, duracao=90)
        inicio = _inicio_util(x[:60 * taxa], taxa)
        batida = _batida(x, taxa)
    except ErroFFmpeg:
        pass
    medida = {"v": VERSAO_MEDIDA, "lufs": round(lufs, 1), "inicio": round(inicio, 1), **batida}
    with _trava_medidas:
        medidas = config.ler_json(_ARQ_MEDIDAS, {}) or {}
        medidas[chave] = medida
        config.gravar_json(_ARQ_MEDIDAS, medidas)
    return medida


def _inicio_util(x: np.ndarray, taxa: int) -> float:
    """Primeiro ponto a partir do qual a música fica "cheia" por 3 s seguidos (uma batida solta seguida de
    silêncio não conta). Janelas de 0,5 s; "cheia" = até 6 dB abaixo do percentil 75."""
    w = taxa // 2
    n = len(x) // w
    if n < 8:
        return 0.0
    db = 20 * np.log10(np.sqrt((x[:n * w].reshape(n, w) ** 2).mean(axis=1)) + 1e-9)
    cheio = (db >= np.percentile(db, 75) - 6).astype(int)
    seguidos = np.convolve(cheio, np.ones(6, dtype=int), mode="valid")
    achou = np.flatnonzero(seguidos == 6)
    return min(45.0, float(achou[0]) * 0.5) if len(achou) else 0.0


def _batida(x: np.ndarray, taxa: int, hop: int = 256, n_fft: int = 1024, aperto: float = 100.0) -> dict:
    """Onde caem as batidas (s), o período e a confiança (0-1: quão marcada é a batida; música ambiente fica
    perto de 0). Rastreamento por programação dinâmica (Ellis 2007, o mesmo do librosa): o fluxo espectral marca
    onde o som "ataca", a autocorrelação dá o andamento (com preferência por ~120 BPM, para não pegar o dobro ou
    a metade) e cada batida é escolhida casando ataque forte com distância regular da anterior. Em cliques
    sintéticos de 95 a 174 BPM: andamento certo, todas as batidas, erro de no máximo ~12 ms."""
    if len(x) < taxa * 15:
        return {}
    quadros = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop] * np.hanning(n_fft)
    espectro = np.log1p(10 * np.abs(np.fft.rfft(quadros, axis=1)))
    fluxo = np.maximum(0.0, np.diff(espectro, axis=0)).sum(axis=1)
    fps = taxa / hop
    janela = max(1, int(fps * 0.4))
    fluxo = np.maximum(0.0, fluxo - np.convolve(fluxo, np.ones(janela) / janela, mode="same"))
    if not fluxo.any():
        return {}
    # andamento: autocorrelação do envelope (suavizado, para período que não cai num número inteiro de quadros)
    suave = np.convolve(fluxo, [0.25, 0.5, 0.25], mode="same")
    centrado = suave - suave.mean()
    ac = np.correlate(centrado, centrado, mode="full")[len(centrado) - 1:]
    lags = np.arange(len(ac))
    bpm = 60 * fps / np.maximum(lags, 1)
    pontos = np.where((bpm >= 60) & (bpm <= 180), ac * np.exp(-0.5 * np.log2(bpm / 120) ** 2), -np.inf)
    lag = int(np.argmax(pontos))
    ajuste = 0.0
    if 1 <= lag < len(ac) - 1:  # refina o período entre dois quadros (interpolação parabólica)
        y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
        if y0 - 2 * y1 + y2:
            ajuste = max(-0.5, min(0.5, 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)))
    periodo = lag + ajuste
    # batidas: programação dinâmica sobre o envelope (penaliza distância diferente do período)
    o = fluxo / (fluxo.std() + 1e-9)
    larg = max(1.0, periodo / 32)
    local = np.convolve(o, np.exp(-0.5 * (np.arange(-int(4 * larg), int(4 * larg) + 1) / larg) ** 2), mode="same")
    n = len(local)
    passos = np.arange(-int(round(2 * periodo)), -int(round(periodo / 2)) + 1)
    custo = -aperto * np.log(-passos / periodo) ** 2
    nota, antes = local.copy(), np.full(n, -1)
    for t in range(n):
        idx = t + passos
        ok = idx >= 0
        if ok.any():
            cand = nota[idx[ok]] + custo[ok]
            k = int(np.argmax(cand))
            if cand[k] > 0:
                nota[t] = local[t] + cand[k]
                antes[t] = idx[ok][k]
    t = n - 1 - int(periodo) + int(np.argmax(nota[n - 1 - int(periodo):]))
    lista = []
    while t >= 0:
        lista.append(t)
        t = antes[t]
    lista = np.array(lista[::-1])
    forte = np.flatnonzero(local[lista] > 0.5 * np.median(local[lista]))  # sem batidas no silêncio das pontas
    if len(forte):
        lista = lista[forte[0]:forte[-1] + 1]
    # o fluxo do quadro i compara as janelas i e i+1; o ataque fica ~1 hop depois do centro da janela i+1
    atraso = (2 * hop + n_fft / 2) / taxa
    return {"batidas": [round(float(b), 3) for b in lista / fps + atraso], "periodo": round(periodo / fps, 4),
            "confianca": round(float(max(0.0, ac[lag]) / (ac[0] + 1e-9)), 2)}


def _ganho_musica(arquivo) -> float:
    """dB para levar a faixa a ALVO_MUSICA_LUFS (faixas de fontes diferentes variam 20 dB entre si)."""
    return max(-20.0, min(15.0, ALVO_MUSICA_LUFS - medir_musica(arquivo)["lufs"]))


def _n_entradas(entradas: list) -> int:
    return len([x for x in entradas if x == "-i"])


def _cama_musical(entradas: list, filtros: list, musica, volume: float, duracao: float | None) -> None:
    """Cria o rótulo [mus]. `musica` é um arquivo (em loop, a partir do início útil, com fade no fim) ou uma
    trilha [(início no vídeo, arquivo), ...]: cada faixa entra no seu ponto com crossfade (vídeos longos)."""
    if isinstance(musica, (list, tuple)) and len(musica) == 1:
        musica = musica[0][1]
    if not isinstance(musica, (list, tuple)):
        m = medir_musica(musica)
        idx = _n_entradas(entradas)
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
        cadeia = (f"[{idx}:a]atrim=start={m['inicio']:.2f},asetpts=PTS-STARTPTS,"
                  f"volume={_ganho_musica(musica):.1f}dB,volume={volume:.2f},aresample=48000")
        if duracao:
            cadeia += f",afade=t=in:d=0.4,afade=t=out:st={max(0.0, duracao - 1.5):.2f}:d=1.5"
        filtros.append(cadeia + "[mus]")
        return
    rotulos = []
    for k, (t, arquivo) in enumerate(musica):
        fim = musica[k + 1][0] + TROCA_MUSICA if k + 1 < len(musica) else (duracao or t + 3600.0)
        idx = _n_entradas(entradas)
        entradas += ["-stream_loop", "-1", "-i", str(arquivo)]
        filtros.append(f"[{idx}:a]atrim=start={medir_musica(arquivo)['inicio']:.2f}:duration={fim - t:.3f},"
                       f"asetpts=PTS-STARTPTS,volume={_ganho_musica(arquivo):.1f}dB,"
                       f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[mtr{k}]")
        rotulos.append(f"mtr{k}")
    atual = rotulos[0]
    for k in range(1, len(rotulos)):
        filtros.append(f"[{atual}][{rotulos[k]}]acrossfade=d={TROCA_MUSICA}:c1=qsin:c2=qsin[mxf{k}]")
        atual = f"mxf{k}"
    cadeia = f"[{atual}]volume={volume:.2f}"
    if duracao:
        cadeia += f",afade=t=out:st={max(0.0, duracao - 3):.2f}:d=3"
    filtros.append(cadeia + "[mus]")


def _musica_existe(musica) -> bool:
    if isinstance(musica, (list, tuple)):
        return bool(musica) and all(Path(a).exists() for _, a in musica)
    return bool(musica) and Path(musica).exists()


def _mixar_audio(entradas: list, filtros: list, atual: str, normalizar: bool, musica,
                 efeitos: list | None, volume_musica: float = 0.35, limpar_voz: bool = False,
                 duracao: float | None = None) -> str:
    """Limpeza de voz (opcional), normalização (-14 LUFS), música com ducking e efeitos sonoros por cima
    do rótulo `atual`. Acrescenta entradas/filtros nas listas e devolve o rótulo do áudio final.
    musica: um arquivo ou uma trilha [(início, arquivo), ...] (ver _cama_musical)."""
    if limpar_voz:
        filtros.append(f"[{atual}]{CADEIA_VOZ}[avoz]")
        atual = "avoz"
    if normalizar:
        # Padrão das redes sociais e do YouTube: -14 LUFS
        filtros.append(f"[{atual}]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[an]")
        atual = "an"
    if _musica_existe(musica):
        # "Ducking": a música abaixa sozinha quando há voz
        filtros.append(f"[{atual}]asplit=2[voz][sc]")
        _cama_musical(entradas, filtros, musica, volume_musica, duracao)
        filtros.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[musd]")
        filtros.append("[voz][musd]amix=inputs=2:duration=first:normalize=0[am]")
        atual = "am"
    efeitos = [e for e in (efeitos or []) if Path(e[1]).exists()]
    if efeitos:
        rotulos = []
        for k, (tempo, arquivo, volume) in enumerate(efeitos):
            idx = len([x for x in entradas if x == "-i"])
            entradas += ["-i", str(arquivo)]
            ms = int(max(0.0, tempo) * 1000)
            # Só os 2 primeiros segundos do efeito, com fade no fim (efeitos com cauda longa)
            filtros.append(f"[{idx}:a]atrim=0:2,afade=t=out:st=1.6:d=0.4,aresample=48000,"
                           f"aformat=channel_layouts=stereo,volume={volume:.2f},adelay={ms}:all=1[fx{k}]")
            rotulos.append(f"[fx{k}]")
        filtros.append(f"[{atual}]{''.join(rotulos)}amix=inputs={len(rotulos) + 1}:duration=first:normalize=0,"
                       "alimiter=limit=0.95[afx]")
        atual = "afx"
    return atual


# ---------------------------------------------------------------- vídeos longos (em blocos)

def na_grade(t: float) -> float:
    """Arredonda para a grade de quadros (1/30 s). Vídeo e áudio cortados exatamente no mesmo ponto:
    com centenas de cortes, meio quadro de diferença em cada um viraria segundos de dessincronia."""
    return round(t * FPS_SAIDA) / FPS_SAIDA


def trechos_na_grade(trechos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Trechos arredondados para a grade de quadros (sem os que ficam com menos de 1 quadro).
    Render, duração, legenda e capítulos usam exatamente estes trechos: nada escorrega."""
    grade = [(na_grade(a), na_grade(b)) for a, b in trechos]
    return [(a, b) for a, b in grade if b - a >= 1 / FPS_SAIDA - 1e-9]


def _expr_trechos(trechos: list[tuple[float, float]], base: float) -> str:
    """Seleciona os quadros k/30 com a <= k/30 < b. Os limites ficam no MEIO entre dois quadros
    (a - 1/60, b - 1/60): assim o arredondamento nunca inclui ou perde um quadro na borda."""
    meio = 0.5 / FPS_SAIDA
    return "+".join(f"between(t,{a - base - meio:.5f},{b - base - meio:.5f})" for a, b in trechos)


def tamanho_saida(info: dict, altura_max: int = 1080) -> tuple[int, int]:
    """Resolução do vídeo longo: a do original, limitada a 1080p (encode rápido), sempre par."""
    altura = min(info["altura"], altura_max)
    largura = int(round(info["largura"] * altura / info["altura"] / 2)) * 2
    return largura, altura - altura % 2


def renderizar_bloco(video: str | Path, trechos: list[tuple[float, float]], saida: str | Path, info: dict,
                     zoom: list[tuple[float, float, float]] | None = None, arquivo_ass: str | None = None,
                     flash: bool = False, altura_max: int = 1080, progresso=None, cancelado=None) -> float:
    """Renderiza um bloco de vídeo longo: `trechos` (em ordem) de um pedaço contínuo do original, com
    jump cuts na grade de quadros, zoom fixo por intervalo (tempo do bloco), legenda .ass (caminho relativo
    a DADOS) e flash branco no começo (transição). Sai em .mkv com áudio PCM, para juntar os blocos sem
    recodificar o vídeo e sem o atraso do AAC entre eles. Devolve a duração do bloco."""
    trechos = trechos_na_grade(trechos)
    if not trechos:
        raise ValueError("Bloco sem trechos")
    base = trechos[0][0]
    total = trechos[-1][1] - base
    duracao = sum(b - a for a, b in trechos)
    sel = _expr_trechos(trechos, base)
    largura, altura = tamanho_saida(info, altura_max)

    cadeia = [f"setpts=PTS-STARTPTS,fps={FPS_SAIDA},select='{sel}',setpts=N/{FPS_SAIDA}/TB"]
    if (largura, altura) != (info["largura"], info["altura"]):
        cadeia.append(f"scale={largura}:{altura}")
    if zoom:
        # Punch-in: zoom fixo em cada intervalo (esconde o pulo do jump cut); fora deles, enquadramento normal
        z = "+".join(f"between(it,{a:.3f},{b:.3f})*{f - 1:.3f}" for a, b, f in zoom)
        cadeia.append(f"zoompan=z='1+{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={largura}x{altura}:fps={FPS_SAIDA}")
    if flash:
        cadeia.append("drawbox=c=white@0.75:t=fill:enable='lt(t,0.07)',drawbox=c=white@0.35:t=fill:enable='between(t,0.07,0.16)'")
    if arquivo_ass:
        cadeia.append(f"ass={arquivo_ass}:fontsdir=fontes")
    cadeia.append("format=yuv420p")
    filtros = [f"[0:v]{','.join(cadeia)}[v]"]
    if info["tem_audio"]:
        # Pacotes de áudio de exatamente 1 quadro (1600 amostras a 48 kHz): o mesmo `select` corta
        # vídeo e áudio nos mesmos pontos
        filtros.append(f"[0:a]asetpts=PTS-STARTPTS,aresample=48000,asetnsamples=n={48000 // FPS_SAIDA}:p=1,"
                       f"aselect='{sel}',asetpts=N/SR/TB[a]")
    else:
        filtros.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duracao:.3f}[a]")
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    roteiro = saida.with_suffix(".filtro.txt")
    roteiro.write_text(";".join(filtros), encoding="utf-8")
    args = ["-ss", f"{base:.4f}", "-t", f"{total + 0.2:.4f}", "-i", str(video),
            "-/filter_complex", str(roteiro), "-map", "[v]", "-map", "[a]",
            *encoder_video(), "-c:a", "pcm_s16le", "-ar", "48000", "-t", f"{duracao:.4f}", str(saida)]
    rodar(args, duracao=duracao, progresso=progresso, cancelado=cancelado, cwd=str(config.DADOS) if arquivo_ass else None)
    roteiro.unlink(missing_ok=True)
    return duracao


def _escapar_meta(texto: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", texto)


def juntar_blocos(blocos: list[Path], saida: str | Path, duracao: float, normalizar: bool = True,
                  musica=None, efeitos: list | None = None,
                  capitulos: list[tuple[float, str]] | None = None, limpar_voz: bool = False,
                  progresso=None, cancelado=None) -> Path:
    """Junta os blocos sem recodificar o vídeo (concat), mixa o áudio final (normalização, música, efeitos)
    e grava os capítulos no MP4 (aparecem como marcadores nos players)."""
    saida = Path(saida)
    lista = saida.with_suffix(".blocos.txt")
    lista.write_text("ffconcat version 1.0\n" + "".join(
        f"file '{Path(b).as_posix()}'\n" for b in blocos), encoding="utf-8")
    entradas = ["-f", "concat", "-safe", "0", "-i", str(lista)]
    filtros = ["[0:a]anull[a0]"]
    atual = _mixar_audio(entradas, filtros, "a0", normalizar, musica, efeitos, volume_musica=0.22,
                         limpar_voz=limpar_voz, duracao=duracao)
    extra = []
    if capitulos:
        meta = saida.with_suffix(".capitulos.txt")
        linhas = [";FFMETADATA1"]
        for k, (t, titulo) in enumerate(capitulos):
            fim = capitulos[k + 1][0] if k + 1 < len(capitulos) else duracao
            linhas += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}", f"END={int(fim * 1000)}",
                       f"title={_escapar_meta(titulo)}"]
        meta.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        idx = len([x for x in entradas if x == "-i"])
        entradas += ["-i", str(meta)]
        extra = ["-map_chapters", str(idx)]
    roteiro = saida.with_suffix(".filtro.txt")
    roteiro.write_text(";".join(filtros), encoding="utf-8")
    args = entradas + ["-/filter_complex", str(roteiro), "-map", "0:v", "-map", f"[{atual}]", *extra,
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                       "-t", f"{duracao:.3f}", "-movflags", "+faststart", str(saida)]
    rodar(args, duracao=duracao, progresso=progresso, cancelado=cancelado)
    for arq in (lista, roteiro, saida.with_suffix(".capitulos.txt")):
        arq.unlink(missing_ok=True)
    return saida


# ---------------------------------------------------------------- corte

def cortar(video: str | Path, trechos: list[tuple[float, float]], saida: str | Path,
           normalizar: bool = True, musica: str | None = None, info: dict | None = None,
           efeitos: list[tuple[float, str, float]] | None = None, abertura: tuple[float, float] | None = None,
           limpar_voz: bool = False, progresso=None, cancelado=None) -> Path:
    """Gera um clipe com os trechos concatenados (vídeo em resolução original, 30 fps).
    O enquadramento e a legenda são feitos depois, em cima deste arquivo.
    efeitos: (tempo no clipe, arquivo, volume) de cada efeito sonoro.
    abertura: trecho (fora de ordem) que vai antes de tudo, como teaser do clímax."""
    info = info or sondar(video)
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    base = trechos[0][0]
    total = trechos[-1][1] - base
    duracao_final = duracao_trechos(trechos) + (abertura[1] - abertura[0] if abertura else 0)

    # Com -ss antes do -i o tempo recomeça em 0; os trechos viram relativos a "base"
    sel = "+".join(f"between(t,{a - base:.3f},{b - base:.3f})" for a, b in trechos)
    filtros = [f"[0:v]fps={FPS_SAIDA},select='{sel}',setpts=N/{FPS_SAIDA}/TB[v]"]

    entradas = ["-ss", f"{base:.3f}", "-t", f"{total + 0.1:.3f}", "-i", str(video)]
    if info["tem_audio"]:
        filtros.append(f"[0:a]aselect='{sel}',asetpts=N/SR/TB,aresample=48000[a0]")
    else:
        entradas += ["-f", "lavfi", "-t", f"{duracao_final:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        filtros.append("[1:a]anull[a0]")
    if abertura:
        # Segunda leitura do mesmo arquivo só com o teaser; concatena antes do corpo
        idx = len([x for x in entradas if x == "-i"])
        entradas += ["-ss", f"{abertura[0]:.3f}", "-t", f"{abertura[1] - abertura[0]:.3f}", "-i", str(video)]
        filtros[0] = filtros[0].replace("[v]", "[vcorpo]")
        filtros.append(f"[{idx}:v]fps={FPS_SAIDA},setpts=PTS-STARTPTS[vab]")
        if info["tem_audio"]:
            filtros.append(f"[{idx}:a]asetpts=PTS-STARTPTS,aresample=48000[aab]")
        else:
            filtros.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{abertura[1] - abertura[0]:.3f}[aab]")
        filtros.append("[vab][aab][vcorpo][a0]concat=n=2:v=1:a=1[v][acat]")
        filtros.append("[acat]aresample=48000[a1]")
        atual = "a1"
    else:
        atual = "a0"
    atual = _mixar_audio(entradas, filtros, atual, normalizar, musica, efeitos, limpar_voz=limpar_voz,
                         duracao=duracao_final)

    args = entradas + [
        "-filter_complex", ";".join(filtros),
        "-map", "[v]", "-map", f"[{atual}]",
        *encoder_video(), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{duracao_final:.3f}", "-movflags", "+faststart", str(saida),
    ]
    rodar(args, duracao=duracao_final, progresso=progresso, cancelado=cancelado)
    return saida
