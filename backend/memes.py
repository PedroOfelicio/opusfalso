"""
Memes e figurinhas do próprio usuário (o app não busca meme na internet: direitos autorais).

    DADOS/memes/rindo.png             o nome do arquivo diz quando usar: "rindo" na fala -> figurinha
    DADOS/memes/susto_grito.mp4       várias palavras separadas por _ - ou espaço
    DADOS/memes/dinheiro/qualquer.gif ou uma subpasta com o nome da palavra

Imagem (png/jpg/webp, de preferência png com fundo transparente) pula na tela por ~1,4 s, como os textos de
impacto. Vídeo curto (mp4/mov/webm/gif) cobre a tela por até 1,5 s, como um corte para o meme (sem o som dele).
No máximo 2 por clipe, espaçados; a escolha é estável por clipe (re-renderizar não troca o meme).
"""
import hashlib
import re
import unicodedata
from pathlib import Path

import numpy as np

import config

PASTA = config.DADOS / "memes"
IMAGENS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm", ".gif", ".m4v"}
DURACAO_VIDEO = 1.5

LEIAME = """Memes e figurinhas do Gadosso Edit
==================================

Solte aqui imagens (png com fundo transparente fica melhor) e vídeos curtos de meme.
O NOME do arquivo diz quando usar: se alguém falar essa palavra no clipe, o meme entra.

    rindo.png              entra quando falarem "rindo"
    susto_grito.mp4        entra com "susto" ou "grito"
    dinheiro\\qualquer.gif  subpasta com o nome da palavra: vale para todos os arquivos dentro

Imagem: pula na tela por ~1,4 s. Vídeo: cobre a tela por até 1,5 s (sem o som do meme).
No máximo 2 memes por clipe. Use só material que você pode usar.
"""


def preparar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    leiame = PASTA / "LEIAME.txt"
    if not leiame.exists():
        leiame.write_text(LEIAME, encoding="utf-8")


def _norm(p: str) -> str:
    p = "".join(c for c in unicodedata.normalize("NFD", p.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", p)


def listar(pasta: Path | None = None) -> list[dict]:
    """[{arquivo, tipo: imagem|video, palavras}] de tudo que dá para usar na pasta."""
    pasta = pasta or PASTA
    if not pasta.exists():
        return []
    itens = []
    for arq in sorted(pasta.rglob("*")):
        ext = arq.suffix.lower()
        if not arq.is_file() or ext not in IMAGENS | VIDEOS:
            continue
        nomes = re.split(r"[_\-\s.]+", arq.stem)
        if arq.parent != pasta:
            nomes.append(arq.parent.name)
        palavras = {_norm(n) for n in nomes if len(_norm(n)) >= 2 and not _norm(n).isdigit()}
        if palavras:
            itens.append({"arquivo": str(arq), "tipo": "imagem" if ext in IMAGENS else "video",
                          "palavras": sorted(palavras)})
    return itens


def _casa(palavra: str, chave: str) -> bool:
    """Igual, ou mesma raiz em palavras de 4+ letras ("rindo" ~ "rindoo", "gritou" ~ "grito")."""
    if palavra == chave:
        return True
    return len(chave) >= 4 and len(palavra) >= 4 and (palavra.startswith(chave) or chave.startswith(palavra))


def escolher(palavras_clipe: list[dict], semente: str, duracao: float, inicio_min: float = 1.0,
             maximo: int = 2, espaco: float = 4.0, pasta: Path | None = None) -> list[tuple[float, str, str]]:
    """Memes para as palavras do clipe (já no tempo do clipe): [(instante, arquivo, tipo)]."""
    itens = listar(pasta)
    if not itens:
        return []
    escolhidos: list[tuple[float, str, str]] = []
    usados = set()
    for w in palavras_clipe:
        t = w["i"]
        if t < inicio_min or t > duracao - 1.0 or any(abs(t - e[0]) < espaco for e in escolhidos):
            continue
        p = _norm(w["p"])
        if len(p) < 2:
            continue
        opcoes = [m for m in itens if m["arquivo"] not in usados and any(_casa(p, c) for c in m["palavras"])]
        if not opcoes:
            continue
        k = int(hashlib.md5(f"{semente}/{p}".encode()).hexdigest(), 16) % len(opcoes)
        m = opcoes[k]
        usados.add(m["arquivo"])
        escolhidos.append((round(t, 3), m["arquivo"], m["tipo"]))
        if len(escolhidos) >= maximo:
            break
    return escolhidos


def figurinha(arquivo: str, largura_tela: int) -> np.ndarray | None:
    """Imagem do meme como BGRA, com ~55% da largura da tela e contorno branco (cara de figurinha)."""
    import cv2
    img = cv2.imdecode(np.fromfile(arquivo, dtype=np.uint8), cv2.IMREAD_UNCHANGED)  # aceita caminho com acento
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    alvo = int(largura_tela * 0.55)
    h, w = img.shape[:2]
    img = cv2.resize(img, (alvo, max(1, int(h * alvo / w))), interpolation=cv2.INTER_AREA)
    borda = max(4, largura_tela // 120)
    img = cv2.copyMakeBorder(img, borda, borda, borda, borda, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    alfa = img[:, :, 3]
    contorno = cv2.dilate((alfa > 20).astype(np.uint8), np.ones((2 * borda + 1, 2 * borda + 1), np.uint8))
    branco = np.zeros_like(img)
    branco[:, :, :3] = 255
    branco[:, :, 3] = contorno * 255
    a = (alfa.astype(np.float32) / 255.0)[:, :, None]
    resultado = (img.astype(np.float32) * a + branco.astype(np.float32) * (1 - a)).astype(np.uint8)
    resultado[:, :, 3] = np.maximum(alfa, contorno * 255)
    return resultado
