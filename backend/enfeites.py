"""
Enfeites desenhados pelo próprio app (sem imagem de fora, sem risco de direitos autorais):

- Texto de reação ("ESPERA...", "KKKKK", "CLUTCH!") que pula na tela no pico do clipe: o Claude escolhe o
  instante e o texto; aqui vira uma figurinha RGBA (letra grossa, contorno, leve inclinação) que o render
  aplica quadro a quadro com animação de "pop".
- Capa vertical (1080x1920) de cada Short: o melhor quadro do clipe (nítido, bem iluminado, com rosto se
  houver), enquadrado no rosto, com o título em letra grossa sobre uma sombra.
"""
import math

import numpy as np

import config

CORES_REACAO = [((255, 230, 0), (0, 0, 0)), ((255, 255, 255), (225, 30, 60)), ((60, 230, 255), (0, 0, 0))]


def _fonte(tamanho: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(config.PASTA_FONTES / "Anton-Regular.ttf"), tamanho)


def figurinha_reacao(texto: str, largura_tela: int, estilo: int = 0) -> np.ndarray:
    """Texto de reação como imagem BGRA (para o render compor com transparência)."""
    from PIL import Image, ImageDraw
    texto = texto.strip().upper()[:18]
    cor, contorno = CORES_REACAO[estilo % len(CORES_REACAO)]
    alvo = largura_tela * 0.78
    tam = 170
    while tam > 50 and _fonte(tam).getbbox(texto)[2] > alvo:
        tam -= 6
    fonte = _fonte(tam)
    x0, y0, x1, y1 = fonte.getbbox(texto)
    borda = max(6, tam // 11)
    w, h = x1 - x0 + 4 * borda, y1 - y0 + 4 * borda
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((2 * borda - x0 + 6, 2 * borda - y0 + 8), texto, font=fonte, fill=(0, 0, 0, 150))  # sombra
    d.text((2 * borda - x0, 2 * borda - y0), texto, font=fonte, fill=cor, stroke_width=borda, stroke_fill=contorno)
    img = img.rotate(-5 if estilo % 2 == 0 else 4, resample=Image.BICUBIC, expand=True)
    rgba = np.array(img)
    return rgba[:, :, [2, 1, 0, 3]].copy()  # RGBA -> BGRA


def compor_reacao(quadro: np.ndarray, fig: np.ndarray, t: float, inicio: float, duracao: float = 1.4,
                  centro_y: float = 0.30) -> np.ndarray:
    """Aplica a figurinha no quadro com "pop" (cresce até 115% e assenta em 100%) e some no fim."""
    dt = t - inicio
    if not 0 <= dt < duracao:
        return quadro
    if dt < 0.18:
        escala = 0.4 + 0.75 * math.sin(dt / 0.18 * math.pi / 2)  # 0,4 -> 1,15
    elif dt < 0.3:
        escala = 1.15 - 0.15 * (dt - 0.18) / 0.12
    else:
        escala = 1.0
    alfa_geral = min(1.0, (duracao - dt) / 0.3)
    import cv2
    H, W = quadro.shape[:2]
    fh, fw = fig.shape[:2]
    nw, nh = max(1, int(fw * escala)), max(1, int(fh * escala))
    if nw > W:
        nh, nw = int(nh * W / nw), W
    f = cv2.resize(fig, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x, y = (W - nw) // 2, int(H * centro_y - nh / 2)
    y0, y1, x0, x1 = max(0, y), min(H, y + nh), max(0, x), min(W, x + nw)
    if y1 <= y0 or x1 <= x0:
        return quadro
    pedaco = f[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (pedaco[:, :, 3:4].astype(np.float32) / 255.0) * alfa_geral
    regiao = quadro[y0:y1, x0:x1].astype(np.float32)
    quadro = quadro.copy()
    quadro[y0:y1, x0:x1] = (regiao * (1 - a) + pedaco[:, :, :3].astype(np.float32) * a).astype(np.uint8)
    return quadro


# ---------------------------------------------------------------- capa vertical

def melhor_quadro(video: str, n: int = 14, com_rosto: bool = True):
    """(quadro BGR, centro x do rosto 0-1 ou None) mais forte do vídeo: nitidez x cor x luz x rosto."""
    import cv2

    import reenquadramento as rq
    det = rq.DetectorRostos() if com_rosto else None
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    melhor = None
    try:
        for k in range(n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (0.08 + 0.84 * k / max(1, n - 1))))
            ok, q = cap.read()
            if not ok:
                continue
            h, w = q.shape[:2]
            peq = cv2.resize(q, (480, int(480 * h / w)))
            cinza = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
            nitidez = cv2.Laplacian(cinza, cv2.CV_64F).var() ** 0.5
            brilho = float(cinza.mean())
            cor = float(cv2.cvtColor(peq, cv2.COLOR_BGR2HSV)[..., 1].mean())
            rosto, area = None, 0.0
            if det is not None:
                faces = det(peq)
                if faces:
                    x, y, fw, fh, _ = max(faces, key=lambda f: f[2] * f[3])
                    area, rosto = fw * fh / (peq.shape[0] * peq.shape[1]), (x + fw / 2) / peq.shape[1]
            nota = nitidez * (0.6 + cor / 255) * (1.0 if 45 < brilho < 210 else 0.3) * (1 + 12 * area)
            if melhor is None or nota > melhor[0]:
                melhor = (nota, q, rosto)
    finally:
        cap.release()
    return (melhor[1], melhor[2]) if melhor else (None, None)


def capa_vertical(quadro_bgr: np.ndarray, texto: str, centro_x: float | None = None, W: int = 1080, H: int = 1920):
    """Capa 9:16: quadro enquadrado (no rosto, se houver), sombra embaixo e o título em Anton, com a última
    linha amarela, no terço de baixo (onde o TikTok/Shorts não cobre com botões)."""
    import cv2
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.fromarray(cv2.cvtColor(quadro_bgr, cv2.COLOR_BGR2RGB))
    w, h = img.size
    escala = max(W / w, H / h)
    img = img.resize((int(w * escala + 0.5), int(h * escala + 0.5)), Image.LANCZOS)
    cx = (centro_x if centro_x is not None else 0.5) * img.width
    x0 = int(min(max(0, cx - W / 2), img.width - W))
    y0 = (img.height - H) // 2
    img = img.crop((x0, y0, x0 + W, y0 + H)).convert("RGB")

    linha = Image.new("L", (1, H))  # sombra em degradê na metade de baixo
    linha.putdata([int(max(0.0, (y / H - 0.42) / 0.58) ** 1.3 * 215) for y in range(H)])
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, linha.resize((W, H)))

    palavras = texto.upper().split()
    if not palavras:
        return img
    melhor = None
    for n_linhas in range(1, min(4, len(palavras)) + 1):
        por = -(-len(palavras) // n_linhas)
        linhas = [" ".join(palavras[i:i + por]) for i in range(0, len(palavras), por)]
        for tam in range(220, 60, -6):
            fonte = _fonte(tam)
            larguras = [fonte.getbbox(l)[2] for l in linhas]
            if max(larguras) <= W * 0.88 and len(linhas) * tam * 1.05 <= H * 0.30:
                if melhor is None or tam > melhor[0]:
                    melhor = (tam, linhas, fonte, larguras)
                break
    if melhor is None:
        return img
    tam, linhas, fonte, larguras = melhor
    camada = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(camada), ImageDraw.Draw(sombra)
    y = H * 0.70 - len(linhas) * tam * 1.05 / 2
    borda = max(5, tam // 14)
    for k, (texto_linha, lw) in enumerate(zip(linhas, larguras)):
        x = (W - lw) / 2
        cor = (255, 230, 0) if k == len(linhas) - 1 and len(linhas) > 1 else (255, 255, 255)
        ds.text((x + 8, y + 12), texto_linha, font=fonte, fill=(0, 0, 0, 210))
        d.text((x, y), texto_linha, font=fonte, fill=cor, stroke_width=borda, stroke_fill=(0, 0, 0))
        y += tam * 1.05
    img = img.convert("RGBA")
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(12)))
    img.alpha_composite(camada)
    return img.convert("RGB")
