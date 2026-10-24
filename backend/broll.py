"""
B-roll: vídeos de apoio de banco (Pexels: grátis, uso comercial liberado, sem dar crédito) que cobrem a tela por
2-3 s quando a fala cita algo concreto ("ganhei 10 mil reais" -> pilha de dinheiro). O Claude marca onde e o que
buscar (em inglês, que o banco entende melhor); aqui só se busca, baixa (com cache) e devolve o arquivo.

Precisa de uma chave grátis do Pexels (pexels.com/api) em Configurações, ou na variável PEXELS_API_KEY.
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


def chave() -> str:
    return (config.carregar().get("pexels_key") or os.environ.get("PEXELS_API_KEY", "")).strip()


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
    chave_api = chave()
    if not chave_api:
        return None
    try:
        url = API + "?" + urllib.parse.urlencode({"query": busca, "orientation": orientacao, "size": "medium",
                                                  "per_page": 8})
        with _pedir(url, chave_api) as r:
            videos = json.load(r).get("videos", [])
        for v in sorted(videos, key=lambda v: abs((v.get("duration") or 0) - 8)):  # 5-15 s é o ideal
            if (v.get("duration") or 0) < 3:
                continue
            arquivo = escolher_arquivo(v, orientacao)
            if not arquivo:
                continue
            PASTA.mkdir(parents=True, exist_ok=True)
            parcial = destino.with_suffix(".part")
            with urllib.request.urlopen(urllib.request.Request(arquivo["link"], headers={"User-Agent": "Clipador/1.0"}),
                                        timeout=60) as r, open(parcial, "wb") as f:
                while bloco := r.read(1 << 20):
                    f.write(bloco)
            parcial.replace(destino)
            log.info("B-roll \"%s\": %s (%.1f MB)", busca, v.get("url", ""), destino.stat().st_size / 1e6)
            return destino
    except OSError as e:  # rede, chave inválida (HTTPError é OSError), limite de pedidos
        log.warning("B-roll \"%s\" falhou: %s", busca, e)
    return None
