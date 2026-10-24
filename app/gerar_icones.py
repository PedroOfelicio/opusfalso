"""
Gera os ícones do Clipador em alta qualidade a partir de um desenho em 1024 px (bordas suaves):
  app/icone.ico                (atalho e bandeja: 16 a 256 px, cada tamanho reduzido com LANCZOS)
  app/icone_bandeja.png        (64 px, já reduzido: o pystray encolheria mal o de 256)
  frontend/public/icone-*.png  (janela/barra de tarefas: favicons e ícones do manifesto)
Rodar: C:\\opusfalso-dados\\venv\\Scripts\\python app\\gerar_icones.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

RAIZ = Path(__file__).resolve().parent.parent
N = 1024
ROXO, AZUL = (124, 58, 237), (59, 130, 246)


def desenhar() -> Image.Image:
    # fundo: degradê diagonal roxo -> azul, com um brilho suave no canto de cima
    import numpy as np
    y, x = np.mgrid[0:N, 0:N]
    eixo = Image.fromarray(((x + y) / (2 * (N - 1)) * 255).astype("uint8"), "L")
    fundo = Image.composite(Image.new("RGB", (N, N), AZUL), Image.new("RGB", (N, N), ROXO), eixo)
    brilho = Image.new("L", (N, N), 0)
    ImageDraw.Draw(brilho).ellipse((-N * 0.35, -N * 0.55, N * 0.95, N * 0.45), fill=70)
    fundo = Image.composite(Image.new("RGB", (N, N), (255, 255, 255)), fundo, brilho.filter(ImageFilter.GaussianBlur(N / 10)))

    # cantos arredondados (desenhado 4x maior e reduzido: borda lisa)
    m4 = Image.new("L", (N * 4, N * 4), 0)
    ImageDraw.Draw(m4).rounded_rectangle((0, 0, N * 4 - 1, N * 4 - 1), radius=int(N * 4 * 0.27), fill=255)
    mascara = m4.resize((N, N), Image.LANCZOS)

    # play com pontas arredondadas e sombra leve
    t4 = Image.new("L", (N * 4, N * 4), 0)
    d = ImageDraw.Draw(t4)
    s = N * 4 / 32
    pontos = [(12.3 * s, 9.3 * s), (12.3 * s, 22.7 * s), (23.6 * s, 16 * s)]
    d.polygon(pontos, fill=255)
    for x, y in pontos:  # arredonda as pontas
        d.ellipse((x - 1.1 * s, y - 1.1 * s, x + 1.1 * s, y + 1.1 * s), fill=255)
    d.line(pontos + [pontos[0]], fill=255, width=int(2.2 * s), joint="curve")
    play = t4.resize((N, N), Image.LANCZOS)
    sombra = ImageChops.offset(play, int(N * 0.012), int(N * 0.02)).filter(ImageFilter.GaussianBlur(N * 0.02))

    img = fundo.convert("RGBA")
    img = Image.composite(Image.new("RGBA", (N, N), (30, 20, 80, 255)), img, sombra.point(lambda v: v * 0.35))
    img = Image.composite(Image.new("RGBA", (N, N), (255, 255, 255, 255)), img, play)
    img.putalpha(mascara)
    return img


def reduzir(img: Image.Image, lado: int) -> Image.Image:
    menor = img.resize((lado, lado), Image.LANCZOS)
    if lado <= 32:  # em tamanho de ícone, um pouco de nitidez evita o aspecto "borrado"
        menor = menor.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=0))
    return menor


def main():
    mestre = desenhar()
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    imagens = [reduzir(mestre, t) for t in tamanhos]
    imagens[-1].save(RAIZ / "app" / "icone.ico", format="ICO", sizes=[(t, t) for t in tamanhos],
                     append_images=imagens[:-1])
    reduzir(mestre, 64).save(RAIZ / "app" / "icone_bandeja.png")
    publico = RAIZ / "frontend" / "public"
    for t in (16, 32, 48, 180, 192, 512):
        reduzir(mestre, t).save(publico / f"icone-{t}.png")
    mestre.save(RAIZ / "app" / "icone_1024.png")
    print("ícones gerados")


if __name__ == "__main__":
    main()
