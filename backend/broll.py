"""
B-roll: vídeos de apoio de banco (Pixabay ou Pexels: grátis, uso comercial liberado, sem dar crédito) que cobrem a tela por
2-3 s quando a fala cita algo concreto ("ganhei 10 mil reais" -> pilha de dinheiro). O Claude marca onde e o que
buscar (em inglês, que o banco entende melhor); aqui só se busca, baixa (com cache) e devolve o arquivo.

Precisa de uma chave grátis do Pixabay (pixabay.com/api/docs, aparece logado) ou do Pexels em Configurações
(ou nas variáveis PIXABAY_API_KEY / PEXELS_API_KEY). Com as duas, tenta o Pexels primeiro.
"""
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import config

log = logging.getLogger("broll")

PASTA = config.PASTA_CACHE / "broll"
API = "https://api.pexels.com/videos/search"
API_PIXABAY = "https://pixabay.com/api/videos/"


def chave_pexels() -> str:
    return (config.carregar().get("pexels_key") or os.environ.get("PEXELS_API_KEY", "")).strip()


def chave_pixabay() -> str:
    return (config.carregar().get("pixabay_key") or os.environ.get("PIXABAY_API_KEY", "")).strip()


def chave() -> str:
    """Alguma fonte configurada? (para avisar o usuário quando não houver)"""
    return chave_pexels() or chave_pixabay()


def _nome(busca: str, orientacao: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", busca.lower()).strip("_")[:60] + f"_{orientacao}"


def _pedir(url: str, chave_api: str):
    pedido = urllib.request.Request(url, headers={"Authorization": chave_api, "User-Agent": "Clipador/1.0"})
    return urllib.request.urlopen(pedido, timeout=30)


def escolher_arquivo(video: dict, orientacao: str) -> dict | None:
    """O arquivo mais leve que ainda tem boa resolução (lado menor >= 720), sem passar de 1080."""
    arquivos = [f for f in video.get("video_files", []) if f.get("link") and f.get("width") and f.get("height")]
    bons = [f for f in arquivos if 720 <= min(f["width"], f["height"]) <= 1080]
    if orientacao == "portrait":
        bons = [f for f in bons if f["height"] >= f["width"]] or bons
    else:
        bons = [f for f in bons if f["width"] >= f["height"]] or bons
    return min(bons, key=lambda f: f["width"] * f["height"]) if bons else None


def buscar(busca: str, orientacao: str = "portrait") -> Path | None:
    """Arquivo local de um vídeo de apoio para a busca (cache por busca + orientação). None se não achar."""
    busca = (busca or "").strip()
    if not busca:
        return None
    destino = PASTA / f"{_nome(busca, orientacao)}.mp4"
    if destino.exists():
        return destino
    if chave_pexels() and _pexels(busca, orientacao, destino, chave_pexels()):
        return destino
    if chave_pixabay() and _pixabay(busca, orientacao, destino, chave_pixabay()):
        return destino
    return None


def _baixar(url: str, destino: Path) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".part")
    pedido = urllib.request.Request(url, headers={"User-Agent": "Clipador/1.0"})
    with urllib.request.urlopen(pedido, timeout=60) as r, open(parcial, "wb") as f:
        while bloco := r.read(1 << 20):
            f.write(bloco)
    parcial.replace(destino)


def escolher_pixabay(hit: dict) -> dict | None:
    """Pixabay dá large/medium/small/tiny: fica a menor com lado menor >= 720 (sem passar de 1080)."""
    opcoes = [v for v in (hit.get("videos") or {}).values() if v.get("url") and v.get("width") and v.get("height")]
    bons = ([v for v in opcoes if 720 <= min(v["width"], v["height"]) <= 1080]
            or [v for v in opcoes if min(v["width"], v["height"]) >= 540])
    return min(bons, key=lambda v: v["width"] * v["height"]) if bons else None


_VAZIAS = {"the", "and", "with", "for", "from", "into", "of", "on", "at", "in", "a", "an", "to", "up", "out"}


def _raiz(p: str) -> str:
    return p[:-1] if len(p) > 4 and p.endswith("s") else p  # "graduates" ~ "graduate"


def relevancia(busca: str, descricao: str) -> int:
    """Quantas palavras da busca aparecem na descrição do vídeo (tags do Pixabay, endereço do Pexels)."""
    termos = {_raiz(t) for t in re.findall(r"[a-z]+", busca.lower()) if t not in _VAZIAS and len(t) > 2}
    achadas = {_raiz(t) for t in re.findall(r"[a-z]+", descricao.lower())}
    return len(termos & achadas)


def minimo_relevancia(busca: str) -> int:
    """A busca do banco é frouxa ("doctor looking at scan" já trouxe um cachorro): exige que o vídeo tenha
    pelo menos 2 das palavras da busca (1, se a busca só tem uma palavra que conta)."""
    termos = [t for t in re.findall(r"[a-z]+", busca.lower()) if t not in _VAZIAS and len(t) > 2]
    return min(2, len(termos)) or 1


def _vertical(hit: dict) -> bool:
    v = (hit.get("videos") or {}).get("medium") or {}
    return v.get("height", 0) >= v.get("width", 1)


def _pixabay(busca: str, orientacao: str, destino: Path, chave_api: str) -> bool:
    try:
        url = API_PIXABAY + "?" + urllib.parse.urlencode({"key": chave_api, "q": busca, "per_page": 12,
                                                          "safesearch": "true"})
        pedido = urllib.request.Request(url, headers={"User-Agent": "Clipador/1.0"})
        with urllib.request.urlopen(pedido, timeout=30) as r:
            hits = json.load(r).get("hits", [])
        # Só os que batem com a busca; os mais relevantes primeiro e, entre eles, os da orientação pedida
        # (a API de vídeos do Pixabay não filtra orientação)
        minimo = minimo_relevancia(busca)
        hits = [h for h in hits if relevancia(busca, h.get("tags", "")) >= minimo]
        hits.sort(key=lambda h: (-relevancia(busca, h.get("tags", "")), _vertical(h) != (orientacao == "portrait")))
        for h in hits:
            if (h.get("duration") or 0) < 3:
                continue
            arquivo = escolher_pixabay(h)
            if arquivo:
                _baixar(arquivo["url"], destino)
                log.info("B-roll '%s' (Pixabay): %s (%.1f MB)", busca, h.get("pageURL", ""),
                         destino.stat().st_size / 1e6)
                return True
    except OSError as e:  # rede, chave inválida (HTTPError é OSError), limite de pedidos
        log.warning("B-roll '%s' no Pixabay falhou: %s", busca, e)
    return False


def _pexels(busca: str, orientacao: str, destino: Path, chave_api: str) -> bool:
    try:
        url = API + "?" + urllib.parse.urlencode({"query": busca, "orientation": orientacao, "size": "medium",
                                                  "per_page": 8})
        with _pedir(url, chave_api) as r:
            videos = json.load(r).get("videos", [])
        minimo = minimo_relevancia(busca)
        for v in sorted(videos, key=lambda v: abs((v.get("duration") or 0) - 8)):  # 5-15 s é o ideal
            if (v.get("duration") or 0) < 3 or relevancia(busca, v.get("url", "")) < minimo:
                continue
            arquivo = escolher_arquivo(v, orientacao)
            if not arquivo:
                continue
            _baixar(arquivo["link"], destino)
            log.info("B-roll \"%s\": %s (%.1f MB)", busca, v.get("url", ""), destino.stat().st_size / 1e6)
            return True
    except OSError as e:  # rede, chave inválida (HTTPError é OSError), limite de pedidos
        log.warning("B-roll '%s' no Pexels falhou: %s", busca, e)
    return False
