"""
Reenquadramento (ex.: 16:9 -> 9:16) seguindo o rosto de quem fala.

Funciona em duas passadas sobre o clipe já cortado:
1. ANÁLISE: detecta rostos ~6x por segundo, liga as detecções em "trilhas"
   (pessoas) e mede o movimento da boca de cada uma para saber quem fala.
2. RENDER: calcula uma câmera virtual suave (sem tremer) e recorta cada frame,
   aplicando zoom de ênfase e barra de progresso. Os frames vão direto para o
   FFmpeg, que junta o áudio e (opcionalmente) queima a legenda ASS.

Layouts:
- "rosto":   segue quem fala (alterna entre pessoas com corte seco)
- "centro":  recorte fixo (com deslocamento manual -1..1)
- "inteiro": vídeo inteiro no meio, fundo desfocado
- "split":   gameplay em cima, facecam (ou vídeo de apoio) embaixo
- "jogo":    gameplay em destaque: recorte 4:5 do centro (mira) ocupando ~70% da altura,
             fundo desfocado em cima (título) e embaixo
- "dupla":   duas pessoas, uma em cima e outra embaixo
- "auto":    escolhe sozinho conforme o modo e os rostos encontrados
"""
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import config
from config import Cancelado
from editor_ffmpeg import FPS_SAIDA, _SEM_JANELA, encoder_video

log = logging.getLogger("reenquadramento")

RESOLUCOES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
AMOSTRAS_POR_SEGUNDO = 6
LARGURA_ANALISE = 640


# ============================================================== detecção de rostos

class DetectorRostos:
    """YuNet (OpenCV) -> MediaPipe (tasks) -> Haar (OpenCV), trocando se um não achar rostos."""

    def __init__(self, ordem=("yunet", "mediapipe", "haar")):
        self.ordem = list(ordem)
        self.nome = None
        self._det = None
        self._proximo()

    def _proximo(self) -> bool:
        while self.ordem:
            nome = self.ordem.pop(0)
            try:
                self._det = getattr(self, f"_criar_{nome}")()
                self.nome = nome
                log.info("Detector de rostos: %s", nome)
                return True
            except Exception as e:
                # o Haar é só a última reserva (e o OpenCV 5 nem traz o arquivo): não precisa de alerta
                (log.debug if nome == "haar" else log.warning)("Detector %s indisponível: %s", nome, e)
        return False

    def trocar(self) -> bool:
        """Passa para o próximo detector (usado quando um não acha nenhum rosto)."""
        return self._proximo()

    def _criar_mediapipe(self):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        modelo = config.PASTA_MODELOS / "blaze_face_short_range.tflite"
        opcoes = vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(modelo)),
            min_detection_confidence=0.5)
        det = vision.FaceDetector.create_from_options(opcoes)

        def detectar(bgr):
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            res = det.detect(img)
            return [(d.bounding_box.origin_x, d.bounding_box.origin_y, d.bounding_box.width,
                     d.bounding_box.height, d.categories[0].score) for d in res.detections]
        return detectar

    def _criar_yunet(self):
        modelo = config.PASTA_MODELOS / "face_detection_yunet_2023mar.onnx"
        det = cv2.FaceDetectorYN.create(str(modelo), "", (320, 320), 0.6, 0.3, 50)

        def detectar(bgr):
            h, w = bgr.shape[:2]
            det.setInputSize((w, h))
            _, faces = det.detect(bgr)
            if faces is None:
                return []
            return [(f[0], f[1], f[2], f[3], float(f[14])) for f in faces]
        return detectar

    def _criar_haar(self):
        caminho = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascata = cv2.CascadeClassifier(str(caminho))
        if cascata.empty():  # o OpenCV 5 não traz mais os arquivos .xml do Haar
            raise RuntimeError("arquivo haarcascade não encontrado")

        def detectar(bgr):
            cinza = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            faces = cascata.detectMultiScale(cinza, 1.1, 5, minSize=(30, 30))
            return [(x, y, w, h, 0.8) for (x, y, w, h) in faces]
        return detectar

    def __call__(self, bgr):
        if not self._det:
            return []
        try:
            return self._det(bgr)
        except cv2.error as e:
            # Um detector com problema não pode derrubar o render: conta como "sem rosto"
            log.warning("Detector %s falhou (%s); seguindo sem rosto neste frame", self.nome, str(e)[:120])
            return []


# ============================================================== análise

@dataclass
class Trilha:
    """Uma pessoa acompanhada ao longo do clipe."""
    id: int
    amostras: dict = field(default_factory=dict)   # índice da amostra -> (cx, cy, w, h) em pixels originais
    movimento: dict = field(default_factory=dict)  # índice da amostra -> movimento da boca
    _ultimo_recorte: np.ndarray | None = None
    _ultima: int = -99


@dataclass
class Analise:
    largura: int
    altura: int
    fps: float
    total_frames: int
    tempos: list            # tempo (s) de cada amostra
    trilhas: list           # [Trilha]
    detector: str = ""


def _patch_boca(cinza, box, escala):
    """Recorte da metade de baixo do rosto (boca), normalizado para 24x12."""
    x, y, w, h = [v * escala for v in box[:4]]
    x0, y0 = int(max(0, x + w * 0.2)), int(max(0, y + h * 0.55))
    x1, y1 = int(min(cinza.shape[1], x + w * 0.8)), int(min(cinza.shape[0], y + h * 0.95))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return cv2.resize(cinza[y0:y1, x0:x1], (24, 12)).astype(np.float32)


def analisar(video: str | Path, cancelado=None, progresso=None) -> Analise:
    """Detecta e rastreia rostos. Se o detector atual acertar pouco nas primeiras
    amostras, recomeça com o próximo detector."""
    detector = DetectorRostos()
    while True:
        resultado = _passada(video, detector, cancelado, progresso)
        if resultado is not None:
            return resultado
        log.info("Poucos rostos com %s, tentando outro detector", detector.nome)
        if not detector.trocar():
            return _passada(video, None, cancelado, progresso)


def _passada(video, detector, cancelado, progresso) -> Analise | None:
    cap = cv2.VideoCapture(str(video))
    largura = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    altura = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_SAIDA
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    passo = max(1, round(fps / AMOSTRAS_POR_SEGUNDO))
    escala_det = LARGURA_ANALISE / largura  # detecta numa imagem menor (bem mais rápido)

    trilhas: list[Trilha] = []
    tempos = []
    com_rosto = 0
    idx_frame = 0
    idx_amostra = 0
    while True:
        if idx_frame % passo != 0:
            if not cap.grab():
                break
            idx_frame += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        if cancelado is not None and cancelado.is_set():
            cap.release()
            raise Cancelado()
        pequeno = cv2.resize(frame, (LARGURA_ANALISE, int(altura * escala_det)))
        faces = [f for f in detector(pequeno) if f[4] >= 0.5] if detector else []
        com_rosto += bool(faces)
        # Depois de 12 amostras (~2 s): se achou rosto em menos de 30%, pede outro detector
        if detector and idx_amostra == 11 and com_rosto < 4 and detector.ordem:
            cap.release()
            return None
        cinza = cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY)
        tempos.append(idx_frame / fps)
        _associar(trilhas, faces, idx_amostra, cinza, 1 / escala_det, largura)
        idx_amostra += 1
        idx_frame += 1
        if progresso and total:
            progresso(min(idx_frame / total, 1.0))
    cap.release()

    # Descarta trilhas curtas (falsos positivos): precisam aparecer em >= 15% das amostras
    minimo = max(3, int(0.15 * len(tempos)))
    trilhas = [t for t in trilhas if len(t.amostras) >= minimo]
    nome = detector.nome if detector else ""
    log.info("Análise (%s): %d amostras, %d pessoa(s) encontrada(s)", nome, len(tempos), len(trilhas))
    return Analise(largura, altura, fps, total, tempos, trilhas, nome)


def _associar(trilhas, faces, idx, cinza, escala_px, largura):
    """Liga cada rosto detectado à trilha mais próxima (ou cria uma nova)."""
    usados = set()
    for f in sorted(faces, key=lambda f: -f[2] * f[3]):
        cx = (f[0] + f[2] / 2) * escala_px
        cy = (f[1] + f[3] / 2) * escala_px
        box = (cx, cy, f[2] * escala_px, f[3] * escala_px)
        melhor, dist_min = None, 0.18 * largura
        for t in trilhas:
            if t.id in usados or idx - t._ultima > 12:  # sumiu por mais de ~2 s
                continue
            ult = t.amostras[t._ultima]
            d = abs(ult[0] - cx) + abs(ult[1] - cy) * 0.5
            if d < dist_min:
                melhor, dist_min = t, d
        if melhor is None:
            melhor = Trilha(id=len(trilhas))
            trilhas.append(melhor)
        usados.add(melhor.id)
        patch = _patch_boca(cinza, f, 1.0)
        if patch is not None and melhor._ultimo_recorte is not None and idx - melhor._ultima == 1:
            melhor.movimento[idx] = float(np.mean(np.abs(patch - melhor._ultimo_recorte)))
        melhor._ultimo_recorte = patch
        melhor.amostras[idx] = box
        melhor._ultima = idx


# ============================================================== quem fala / câmera

def _falante_por_amostra(analise: Analise) -> list[int | None]:
    """Índice da trilha ativa em cada amostra, com histerese (não fica pulando)."""
    n = len(analise.tempos)
    trilhas = analise.trilhas
    if not trilhas:
        return [None] * n
    if len(trilhas) == 1:
        return [0 if i in trilhas[0].amostras else None for i in range(n)]
    energia = {k: 0.0 for k in range(len(trilhas))}
    atual, candidato, desde = None, None, 0
    resultado = []
    for i in range(n):
        presentes = [k for k, t in enumerate(trilhas) if i in t.amostras]
        for k in presentes:
            energia[k] = 0.7 * energia[k] + 0.3 * trilhas[k].movimento.get(i, 0.0)
        if not presentes:
            resultado.append(atual)
            continue
        melhor = max(presentes, key=lambda k: energia[k])
        if atual not in presentes:
            atual = melhor
        elif melhor != atual and energia[melhor] > energia[atual] * 1.3:
            # só troca se o outro for claramente mais ativo por ~0,8 s seguidos
            if candidato == melhor:
                desde += 1
            else:
                candidato, desde = melhor, 1
            if desde >= int(0.8 * AMOSTRAS_POR_SEGUNDO):
                atual, candidato, desde = melhor, None, 0
        else:
            candidato, desde = None, 0
        resultado.append(atual)
    return resultado


def _suavizar_segmento(valores: np.ndarray, zona_morta: float, fps: float) -> np.ndarray:
    """Câmera 'de operador': mediana contra ruído, zona morta (não mexe por pouco),
    aproximação suave e um filtro gaussiano final."""
    if len(valores) < 3:
        return valores
    jan = max(3, int(fps) | 1)  # ~1 s, ímpar
    pad = np.pad(valores, jan // 2, mode="edge")
    mediana = np.array([np.median(pad[i:i + jan]) for i in range(len(valores))])
    cam = np.empty_like(mediana)
    atual = mediana[0]
    for i, alvo in enumerate(mediana):
        if abs(alvo - atual) > zona_morta:
            atual += (alvo - atual) * 0.06
        cam[i] = atual
    sigma = fps * 0.25
    raio = int(sigma * 3)
    nucleo = np.exp(-0.5 * (np.arange(-raio, raio + 1) / sigma) ** 2)
    nucleo /= nucleo.sum()
    return np.convolve(np.pad(cam, raio, mode="edge"), nucleo, mode="valid")


def trajetoria_camera(analise: Analise, total_frames: int) -> tuple[np.ndarray, np.ndarray]:
    """Centro (x, y) desejado para cada frame, em pixels do vídeo original."""
    W, H = analise.largura, analise.altura
    cx = np.full(total_frames, W / 2.0)
    cy = np.full(total_frames, H / 2.0)
    falantes = _falante_por_amostra(analise)
    if not analise.trilhas or all(f is None for f in falantes):
        return cx, cy

    # Alvo por amostra (segura o último conhecido quando o rosto some)
    alvo_x, alvo_y, dono = [], [], []
    ult = (W / 2, H / 2, None)
    for i, k in enumerate(falantes):
        if k is not None and i in analise.trilhas[k].amostras:
            b = analise.trilhas[k].amostras[i]
            ult = (b[0], b[1] - b[3] * 0.15, k)  # olhos um pouco acima do centro
        alvo_x.append(ult[0])
        alvo_y.append(ult[1])
        dono.append(ult[2])
    # Primeiras amostras sem ninguém herdam o primeiro alvo válido
    primeiro = next((i for i, d in enumerate(dono) if d is not None), None)
    for i in range(primeiro or 0):
        alvo_x[i], alvo_y[i], dono[i] = alvo_x[primeiro], alvo_y[primeiro], dono[primeiro]

    # Expande para cada frame
    t_frames = np.arange(total_frames) / analise.fps
    idx_amostra = np.clip(np.searchsorted(analise.tempos, t_frames, side="right") - 1, 0, len(analise.tempos) - 1)
    fx = np.array(alvo_x)[idx_amostra]
    fy = np.array(alvo_y)[idx_amostra]
    fdono = np.array([-1 if d is None else d for d in dono])[idx_amostra]

    # Suaviza cada trecho de um mesmo falante separadamente (troca de falante = corte seco)
    inicio = 0
    for i in range(1, total_frames + 1):
        if i == total_frames or fdono[i] != fdono[inicio]:
            cx[inicio:i] = _suavizar_segmento(fx[inicio:i], 0.035 * W, analise.fps)
            cy[inicio:i] = _suavizar_segmento(fy[inicio:i], 0.05 * H, analise.fps)
            inicio = i
    return cx, cy


def zoom_por_frame(total_frames: int, fps: float, momentos: list[tuple[float, float]], intensidade=0.12,
                   base: list[tuple[float, float, float]] | None = None) -> np.ndarray:
    """Fator de zoom (>=1) por frame: sobe em 0,2 s, segura e desce em 0,35 s (easing suave).
    `base` dá um zoom fixo por trecho (corte seco = mudança instantânea de enquadramento, o
    "punch-in" que esconde o pulo do jump cut); os momentos de ênfase somam por cima."""
    t = np.arange(total_frames) / fps
    fixo = np.ones(total_frames)
    for a, b, fator in base or []:
        fixo[(t >= a) & (t < b)] = fator
    z = np.ones(total_frames)
    for a, b in momentos:
        subida = np.clip((t - (a - 0.1)) / 0.2, 0, 1)
        descida = np.clip(1 - (t - (b + 0.35)) / 0.35, 0, 1)
        env = np.minimum(subida, descida)
        env = env * env * (3 - 2 * env)  # smoothstep
        z = np.maximum(z, 1 + intensidade * env)
    return z * fixo


# ============================================================== geometria

def _recorte(W, H, aspecto, cx, cy, z=1.0):
    """Retângulo (x0, y0, w, h) com o aspecto pedido, centrado em (cx, cy), dentro do frame."""
    if W / H > aspecto:
        cw, ch = H * aspecto, H
    else:
        cw, ch = W, W / aspecto
    cw, ch = cw / z, ch / z
    x0 = int(round(min(max(cx - cw / 2, 0), W - cw)))
    y0 = int(round(min(max(cy - ch / 2, 0), H - ch)))
    return x0, y0, int(round(cw)), int(round(ch))


def _cobrir(img, largura, altura):
    """Redimensiona preenchendo toda a área (corta o excesso), como CSS object-fit: cover."""
    h, w = img.shape[:2]
    x0, y0, cw, ch = _recorte(w, h, largura / altura, w / 2, h / 2)
    return cv2.resize(img[y0:y0 + ch, x0:x0 + cw], (largura, altura), interpolation=cv2.INTER_LINEAR)


def _fundo_desfocado(frame, largura, altura):
    pequeno = _cobrir(frame, largura // 8, altura // 8)
    pequeno = cv2.GaussianBlur(pequeno, (0, 0), 6)
    return (cv2.resize(pequeno, (largura, altura)) * 0.55).astype(np.uint8)


def _facecam(analise: Analise):
    """Região fixa da facecam (rosto que aparece quase sempre no mesmo lugar)."""
    if not analise.trilhas:
        return None
    melhor = max(analise.trilhas, key=lambda t: len(t.amostras))
    if len(melhor.amostras) < 0.4 * len(analise.tempos):
        return None
    caixas = np.array(list(melhor.amostras.values()))
    cx, cy, w, h = np.median(caixas, axis=0)
    if np.std(caixas[:, 0]) > 0.05 * analise.largura:
        return None  # rosto se move muito: não é facecam
    return cx, cy, w, h


# ============================================================== render

@dataclass
class OpcoesRender:
    formato: str = "9:16"
    layout: str = "auto"
    modo: str = "falado"
    deslocamento_x: float = 0.0        # -1 (esquerda) .. 1 (direita), usado em "centro"
    zoom_momentos: list = field(default_factory=list)  # [(inicio, fim)] no tempo do clipe
    zoom_base: list = field(default_factory=list)      # [(inicio, fim, fator)]: zoom fixo por trecho (pulsos)
    barra_progresso: dict | None = None  # {"cor": "#FFE600", "altura": 10}
    arquivo_ass: str | None = None     # legenda para queimar (caminho relativo a DADOS)
    video_apoio: str | None = None     # vídeo para a metade de baixo no layout split
    # Direção de arte (direcao.py)
    look: str | None = None            # filtro de cor do FFmpeg, aplicado antes da legenda
    zoom_intensidade: float = 0.12     # força do zoom nas ênfases
    transicao: str = "pulso"           # efeito nos cortes grandes
    cortes: list = field(default_factory=list)     # instantes dos cortes grandes (tempo do clipe)
    impacto: str = "nenhum"            # efeito nos picos de ação
    impactos: list = field(default_factory=list)   # instantes dos picos (tempo do clipe)
    broll: list = field(default_factory=list)      # [(início, fim, arquivo)]: vídeo de apoio cobrindo a tela


def _hex_bgr(cor: str):
    cor = cor.lstrip("#")
    return int(cor[4:6], 16), int(cor[2:4], 16), int(cor[0:2], 16)


def escolher_layout(opc: OpcoesRender, analise: Analise) -> str:
    if opc.layout != "auto":
        return opc.layout
    if opc.formato != "9:16":
        return "rosto" if analise.trilhas else "centro"
    if opc.modo == "gameplay":
        return "split" if (_facecam(analise) or opc.video_apoio) else "jogo"
    return "rosto" if analise.trilhas else "inteiro"


def renderizar(entrada: str | Path, saida: str | Path, opc: OpcoesRender,
               progresso=None, cancelado=None) -> dict:
    """Gera o vídeo final reenquadrado. Retorna informações (layout usado etc.)."""
    entrada, saida = Path(entrada), Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    def prog(fase, p):
        if progresso:
            progresso(fase * 0.3 + p * (0.3 if fase == 0 else 0.7))

    analise = analisar(entrada, cancelado, lambda p: prog(0, p))
    layout = escolher_layout(opc, analise)
    LW, LH = RESOLUCOES[opc.formato]
    aspecto = LW / LH
    W, H = analise.largura, analise.altura
    total = analise.total_frames
    fps = analise.fps
    log.info("Layout: %s | %dx%d -> %dx%d", layout, W, H, LW, LH)

    cx, cy = trajetoria_camera(analise, total)
    if layout == "centro" or (layout == "rosto" and not analise.trilhas):
        cx[:] = W / 2 + opc.deslocamento_x * (W / 2)
        cy[:] = H / 2
    z = zoom_por_frame(total, fps, opc.zoom_momentos, intensidade=opc.zoom_intensidade, base=opc.zoom_base)
    efeitos = _efeitos_por_quadro(opc, total, fps, z)

    facecam = _facecam(analise) if layout == "split" else None
    apoio = cv2.VideoCapture(opc.video_apoio) if (layout == "split" and opc.video_apoio and not facecam) else None
    if layout == "split" and not facecam and apoio is None:
        layout = "jogo"  # sem facecam nem vídeo de apoio

    dupla = None
    if layout == "dupla":
        pessoas = sorted(analise.trilhas, key=lambda t: -len(t.amostras))[:2]
        if len(pessoas) < 2:
            layout = "rosto"
        else:
            pessoas.sort(key=lambda t: np.median([b[0] for b in t.amostras.values()]))
            dupla = [np.median(np.array(list(t.amostras.values())), axis=0) for t in pessoas]

    # Processo do FFmpeg que recebe os frames crus pelo stdin
    cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{LW}x{LH}", "-r", str(FPS_SAIDA), "-i", "-",
           "-i", str(entrada), "-map", "0:v", "-map", "1:a?"]
    filtros = [f for f in (opc.look, f"ass={opc.arquivo_ass}:fontsdir=fontes" if opc.arquivo_ass else None) if f]
    if filtros:
        cmd += ["-vf", ",".join(filtros)]
    cmd += [*encoder_video(leve=True), "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(saida)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(config.DADOS), creationflags=_SEM_JANELA)

    barra_cor = _hex_bgr(opc.barra_progresso["cor"]) if opc.barra_progresso else None
    barra_alt = int(opc.barra_progresso.get("altura", 10)) if opc.barra_progresso else 0
    cap = cv2.VideoCapture(str(entrada))
    brolls: dict[int, cv2.VideoCapture] = {}
    i = 0
    try:
        while i < total:
            ok, frame = cap.read()
            if not ok:
                break
            if cancelado is not None and cancelado.is_set():
                raise Cancelado()
            quadro = _compor(frame, layout, i, LW, LH, aspecto, cx, cy, z, facecam, apoio, dupla)
            if opc.broll:
                quadro = _sobrepor_broll(quadro, i / FPS_SAIDA, opc.broll, brolls, LW, LH)
            if i in efeitos:
                quadro = _aplicar_efeito(quadro, *efeitos[i], i)
            if barra_cor:
                cv2.rectangle(quadro, (0, 0), (int(LW * (i + 1) / total), barra_alt), barra_cor, -1)
            proc.stdin.write(quadro.tobytes())
            i += 1
            if i % 15 == 0:
                prog(1, i / total)
        proc.stdin.close()
        proc.wait()
    except (BrokenPipeError, OSError):
        proc.wait()
    except Cancelado:
        proc.kill()
        raise
    finally:
        cap.release()
        for b in brolls.values():
            b.release()
        if apoio is not None:
            apoio.release()
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou no reenquadramento: {proc.stderr.read().decode(errors='ignore')[-600:]}")
    return {"layout": layout, "pessoas": len(analise.trilhas), "detector": analise.detector}


def _sobrepor_broll(quadro, t: float, lista, abertos: dict, LW: int, LH: int):
    """No intervalo de um b-roll, a tela mostra o vídeo de apoio (com 0,15 s de fusão na entrada e na saída)."""
    for k, (a, b, arquivo) in enumerate(lista):
        if not a <= t < b:
            continue
        cap = abertos.get(k)
        if cap is None:
            cap = abertos[k] = cv2.VideoCapture(arquivo)
        ok, f = cap.read()
        if not ok:  # vídeo de apoio mais curto que o intervalo: recomeça
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, f = cap.read()
        if not ok:
            return quadro
        alfa = max(0.0, min(1.0, (t - a) / 0.15, (b - t) / 0.15))
        return cv2.addWeighted(quadro, 1 - alfa, _cobrir(f, LW, LH), alfa, 0)
    return quadro


DURACAO_EFEITO = {"flash": 0.15, "zoom_rapido": 0.3, "desfoque": 0.25, "tremor": 0.3, "glitch": 0.15}


def _efeitos_por_quadro(opc: OpcoesRender, total: int, fps: float, z: np.ndarray) -> dict[int, tuple[str, float]]:
    """Quadro -> (efeito, força 0-1, caindo até 0). O zoom rápido entra direto no zoom do quadro."""
    efeitos: dict[int, tuple[str, float]] = {}
    pedidos = [(t, opc.transicao) for t in opc.cortes if opc.transicao not in ("pulso", None)]
    pedidos += [(t, opc.impacto) for t in opc.impactos if opc.impacto not in ("nenhum", None)]
    for t, tipo in pedidos:
        dur = DURACAO_EFEITO.get(tipo, 0.2)
        for i in range(int(t * fps), min(total, int((t + dur) * fps) + 1)):
            forca = max(0.0, 1 - (i / fps - t) / dur)
            if tipo == "zoom_rapido":
                z[i] *= 1 + 0.22 * forca * forca
            elif forca > 0:
                efeitos[i] = (tipo, forca)
    return efeitos


def _aplicar_efeito(q: np.ndarray, tipo: str, forca: float, i: int) -> np.ndarray:
    h, w = q.shape[:2]
    if tipo == "flash":
        return cv2.addWeighted(q, 1 - 0.85 * forca, np.full_like(q, 255), 0.85 * forca, 0)
    if tipo == "desfoque":
        k = int(45 * forca) // 2 * 2 + 1
        return cv2.GaussianBlur(q, (k, k), 0) if k > 1 else q
    if tipo == "tremor":
        a = 0.02 * w * forca
        m = np.float32([[1, 0, a * np.sin(i * 2.1)], [0, 1, a * np.cos(i * 2.9)]])
        return cv2.warpAffine(q, m, (w, h), borderMode=cv2.BORDER_REFLECT)
    if tipo == "glitch":
        d = max(1, int(0.018 * w * forca))
        saida = q.copy()
        saida[:, :, 2] = np.roll(q[:, :, 2], d, axis=1)
        saida[:, :, 0] = np.roll(q[:, :, 0], -d, axis=1)
        faixa = slice(int(h * (0.3 + 0.4 * ((i * 37) % 10) / 10)), None)
        saida[faixa] = np.roll(saida[faixa], d * 2, axis=1)[: saida[faixa].shape[0]]
        return saida
    return q


def _compor(frame, layout, i, LW, LH, aspecto, cx, cy, z, facecam, apoio, dupla):
    H, W = frame.shape[:2]
    if layout in ("rosto", "centro"):
        x0, y0, cw, ch = _recorte(W, H, aspecto, cx[i], cy[i], z[i])
        return cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (LW, LH), interpolation=cv2.INTER_LINEAR)

    if layout == "inteiro":
        fundo = _fundo_desfocado(frame, LW, LH)
        escala = min(LW / W, LH / H) * z[i]
        fw, fh = int(W * escala), int(H * escala)
        img = cv2.resize(frame, (fw, fh), interpolation=cv2.INTER_LINEAR)
        # Com zoom o vídeo pode passar da largura: corta o centro
        cx0, cy0 = max(0, (fw - LW) // 2), max(0, (fh - LH) // 2)
        img = img[cy0:cy0 + LH, cx0:cx0 + LW]
        fh, fw = img.shape[:2]
        y = int(LH * 0.42 - fh / 2)
        y = max(0, min(LH - fh, y))
        x = (LW - fw) // 2
        fundo[y:y + fh, x:x + fw] = img
        return fundo

    if layout == "jogo":
        # Recorte 4:5 centrado na mira: bem maior que o vídeo inteiro encolhido e ainda mostra
        # contexto (inimigos dos lados). Numa fonte 1080p o recorte é ~864x1080 (quase sem upscale).
        fundo = _fundo_desfocado(frame, LW, LH)
        alto = int(min(LH, LW * 1.25))
        x0, y0, cw, ch = _recorte(W, H, LW / alto, W / 2, H / 2, z[i])
        img = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (LW, alto), interpolation=cv2.INTER_LINEAR)
        y = int((LH - alto) * 0.45)
        fundo[y:y + alto] = img
        return fundo

    if layout == "split":
        alto_topo = int(LH * 0.6)
        x0, y0, cw, ch = _recorte(W, H, LW / alto_topo, W / 2, H / 2, z[i])
        topo = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (LW, alto_topo), interpolation=cv2.INTER_LINEAR)
        alto_base = LH - alto_topo
        if facecam:
            fcx, fcy, fw, fh = facecam
            # Área ao redor do rosto (2,4x a altura do rosto), no aspecto da metade de baixo
            ch2 = min(H, fh * 2.4)
            cw2 = ch2 * LW / alto_base
            if cw2 > W:
                cw2, ch2 = W, W * alto_base / LW
            bx0 = int(min(max(fcx - cw2 / 2, 0), W - cw2))
            by0 = int(min(max(fcy - ch2 / 2, 0), H - ch2))
            base = cv2.resize(frame[by0:by0 + int(ch2), bx0:bx0 + int(cw2)], (LW, alto_base))
        else:
            ok, fa = apoio.read()
            if not ok:  # vídeo de apoio acabou: volta ao início
                apoio.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, fa = apoio.read()
            base = _cobrir(fa, LW, alto_base) if ok else np.zeros((alto_base, LW, 3), np.uint8)
        return np.vstack([topo, base])

    if layout == "dupla":
        metade = LH // 2
        partes = []
        for (pcx, pcy, pw, ph) in dupla:
            ch2 = min(H, ph * 3.0)
            cw2 = ch2 * LW / metade
            if cw2 > W:
                cw2, ch2 = W, W * metade / LW
            x0 = int(min(max(pcx - cw2 / 2, 0), W - cw2))
            y0 = int(min(max(pcy - ch2 / 2, 0), H - ch2))
            partes.append(cv2.resize(frame[y0:y0 + int(ch2), x0:x0 + int(cw2)], (LW, metade)))
        return np.vstack(partes)

    raise ValueError(f"Layout desconhecido: {layout}")
