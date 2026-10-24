"""
Gera os ícones do Gadosso Edit em alta qualidade a partir de um desenho em 1024 px (bordas suaves):
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


def desenho_pequeno(fonte: Path) -> Image.Image:
    """Versão para 16-64 px (barra de tarefas, bandeja): sem o "EDIT", que vira borrão nesses tamanhos,
    com o desenho ocupando quase o quadrado todo, traço um pouco mais grosso e sem o contorno fino."""
    tinta = ImageChops.invert(Image.open(fonte).convert("L"))      # preto da arte -> 255
    tinta = tinta.crop(tinta.point(lambda v: 255 if v > 60 else 0).getbbox())
    lado = int(N * 0.90)
    escala = lado / max(tinta.size)
    tinta = tinta.resize((round(tinta.width * escala), round(tinta.height * escala)), Image.LANCZOS)
    tinta = tinta.filter(ImageFilter.MaxFilter(9))                 # engrossa o traço uns 4 px em 1024
    camada = Image.new("L", (N, N), 0)
    camada.paste(tinta, ((N - tinta.width) // 2, (N - tinta.height) // 2))

    m4 = Image.new("L", (N * 4, N * 4), 0)
    ImageDraw.Draw(m4).rounded_rectangle((0, 0, N * 4 - 1, N * 4 - 1), radius=int(N * 4 * 0.22), fill=255)
    img = Image.new("RGBA", (N, N), (255, 255, 255, 255))
    img = Image.composite(Image.new("RGBA", (N, N), (10, 10, 10, 255)), img, camada)
    img.putalpha(m4.resize((N, N), Image.LANCZOS))
    return img


def reduzir(img: Image.Image, lado: int) -> Image.Image:
    menor = img.resize((lado, lado), Image.LANCZOS)
    if lado <= 48:  # em tamanho de ícone, um pouco de nitidez evita o aspecto "borrado"
        menor = menor.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=0))
    return menor


def main():
    # Gadosso Edit: o "g" da marca Gadosso (app/icone_marca.png); sem ele, o desenho antigo do play.
    # Até 64 px entra a versão sem o "EDIT" (app/icone_fonte_pequeno.png), que fica legível na barra de tarefas.
    marca = RAIZ / "app" / "icone_marca.png"
    mestre = Image.open(marca).convert("RGBA") if marca.exists() else desenhar()
    fonte_pequena = RAIZ / "app" / "icone_fonte_pequeno.png"
    pequeno = desenho_pequeno(fonte_pequena) if fonte_pequena.exists() else mestre

    def icone(lado: int) -> Image.Image:
        return reduzir(pequeno if lado <= 64 else mestre, lado)

    tamanhos = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    imagens = [icone(t) for t in tamanhos]
    imagens[-1].save(RAIZ / "app" / "icone.ico", format="ICO", sizes=[(t, t) for t in tamanhos],
                     append_images=imagens[:-1])
    icone(64).save(RAIZ / "app" / "icone_bandeja.png")
    publico = RAIZ / "frontend" / "public"
    for t in (16, 32, 48, 64, 96, 180, 192, 512):
        icone(t).save(publico / f"icone-{t}.png")
    # favicon.ico com vários tamanhos: o Windows pega o certo para a barra de tarefas em vez de esticar o de 16/32
    fav = [16, 20, 24, 32, 40, 48, 64]
    icone(64).save(publico / "favicon.ico", format="ICO", sizes=[(t, t) for t in fav],
                   append_images=[icone(t) for t in fav[:-1]])
    mestre.save(RAIZ / "app" / "icone_1024.png")
    print("ícones gerados")


if __name__ == "__main__":
    main()
