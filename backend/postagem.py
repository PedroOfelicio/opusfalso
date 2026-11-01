"""
Prontos para postar: tudo que o app já terminou (cada corte curto e cada vídeo longo), com o título, a descrição e a
thumbnail prontos, e a marcação de postado, num canal só do YouTube (sem a API: o upload é pelo Studio).

- Item curto: chave "pid/cid"; item longo: chave "pid".
- Estado de cada item: "pendente" (padrão), "postado" ou "descartado" (corte ruim que não vale postar).
- Título e descrição podem ser editados aqui sem renderizar de novo (ficam por cima dos do projeto).
- "Abrir pasta": monta DADOS/postar/<título>/ com o vídeo (NOME DO ARQUIVO = TÍTULO, que o Studio usa como título),
  a thumbnail e a descrição em .txt, e abre no Explorer para arrastar no Studio. O vídeo é um "hard link" do
  arquivo pronto (não ocupa espaço a mais), ou cópia se não der. Some quando o item é marcado como postado.

Tudo em DADOS/postagem.json.
"""
import os
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

import config
import projetos

ARQ = config.DADOS / "postagem.json"
PASTA = config.DADOS / "postar"
ESTADOS = ("pendente", "postado", "descartado")
_trava = threading.RLock()

# Caracteres proibidos no nome de arquivo do Windows -> parecidos permitidos (o título continua legível)
TROCAS_NOME = {"?": "？", ":": "：", "/": "／", "\\": "＼", "*": "＊", '"': "''", "<": "‹", ">": "›", "|": "｜"}


def _ler() -> dict:
    d = config.ler_json(ARQ, {}) or {}
    d.setdefault("canal", {"url": "", "channel_id": None})
    d.setdefault("itens", {})   # chave -> {"estado": "postado"|"descartado", "em": ts, "titulo"?, "descricao"?}
    return d


def _gravar(d: dict) -> dict:
    config.gravar_json(ARQ, d)
    return d


# ================================================================ canal

def id_do_canal(url: str) -> str | None:
    """UC... a partir do link do canal. Link com @nome: lê a página pública do canal (sem API)."""
    url = (url or "").strip()
    m = re.search(r"(UC[\w-]{22})", url)
    if m:
        return m.group(1)
    if not re.search(r"youtube\.com/(@|c/|user/)", url):
        return None
    try:
        pedido = urllib.request.Request(url if url.startswith("http") else "https://" + url,
                                        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
        with urllib.request.urlopen(pedido, timeout=8) as r:
            html = r.read(600_000).decode("utf-8", "ignore")
    except Exception:
        return None
    m = (re.search(r'"externalId":"(UC[\w-]{22})"', html)
         or re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html))
    return m.group(1) if m else None


def url_studio(canal: dict) -> str:
    if canal.get("channel_id"):
        return f"https://studio.youtube.com/channel/{canal['channel_id']}/videos/upload?d=ud"
    return "https://studio.youtube.com/"


def salvar_canal(url: str) -> dict:
    url = (url or "").strip()
    canal = {"url": url, "channel_id": id_do_canal(url)}
    with _trava:
        d = _ler()
        d["canal"] = canal
        _gravar(d)
    return estado()


# ================================================================ itens prontos

def descricao(clip: dict) -> str:
    """Descrição de um Short: o texto do post e as hashtags, sempre com #shorts."""
    texto = (clip.get("legenda_post") or "").strip()
    tags = [t if t.startswith("#") else f"#{t}" for t in (clip.get("hashtags") or [])]
    if not any(t.lower() == "#shorts" for t in tags):
        tags.append("#shorts")
    return (texto + "\n\n" + " ".join(tags)).strip()


def _descricao_longo(lg: dict) -> str:
    texto = (lg.get("descricao_completa") or lg.get("descricao") or "").strip()
    tags = [t.strip() for t in lg.get("tags") or [] if t.strip()]
    if tags:  # as 3 primeiras viram hashtag (o YouTube mostra em cima do título)
        texto += "\n\n" + " ".join("#" + re.sub(r"\W+", "", t) for t in tags[:3])
    return texto.strip()


def _brutos() -> list[dict]:
    """Tudo que está pronto no disco, com os textos do projeto (antes das edições feitas aqui)."""
    saida = []
    for meta in projetos.listar():
        pid, nome, criado = meta["id"], meta.get("nome", ""), meta.get("criado_em", 0)
        if meta.get("tipo", "curto") == "longo":
            lg = meta.get("longo") or {}
            if not lg.get("arquivo") or not Path(lg["arquivo"]).is_file():
                continue
            v = lg.get("versao", 0)
            thumbs = [t for t in lg.get("thumbs") or [] if Path(t).is_file()]
            saida.append({
                "chave": pid, "tipo": "longo", "pid": pid, "cid": None, "projeto": nome, "criado_em": criado,
                "arquivo": lg["arquivo"], "thumbs": thumbs, "nota": None, "duracao": lg.get("duracao"),
                "titulo": ((lg.get("titulos") or [""])[0] or nome).strip(), "titulos": lg.get("titulos") or [],
                "descricao": _descricao_longo(lg), "tags": lg.get("tags") or [],
                "video_url": f"/api/projetos/{pid}/longo/video?v={v}",
                "thumbs_url": [f"/api/projetos/{pid}/longo/thumb/{k}?v={v}" for k in range(len(thumbs))],
            })
            continue
        for c in meta.get("clips", []):
            if c.get("status") != "pronto" or not c.get("arquivo") or not Path(c["arquivo"]).is_file():
                continue
            v, cid = c.get("versao", 0), c["id"]
            capa = c.get("capa") if c.get("capa") and Path(c["capa"]).is_file() else None
            saida.append({
                "chave": f"{pid}/{cid}", "tipo": "curto", "pid": pid, "cid": cid, "projeto": nome, "criado_em": criado,
                "arquivo": c["arquivo"], "thumbs": [capa] if capa else [], "nota": int(c.get("nota") or 0),
                "duracao": c.get("duracao"), "titulo": (c.get("titulo") or "").strip(), "titulos": [],
                "descricao": descricao(c), "tags": [],
                "video_url": f"/api/projetos/{pid}/clips/{cid}/video?v={v}",
                "thumbs_url": [f"/api/projetos/{pid}/clips/{cid}/capa?v={v}" if capa
                               else f"/api/projetos/{pid}/clips/{cid}/thumb?v={v}"],
            })
    return saida


def itens() -> list[dict]:
    """Os itens prontos com o estado e as edições aplicados: os mais novos primeiro e, no mesmo projeto, os curtos
    pela nota (melhores primeiro)."""
    marcas = _ler()["itens"]
    saida = []
    for it in _brutos():
        m = marcas.get(it["chave"]) or {}
        it["estado"] = m.get("estado", "pendente")
        it["marcado_em"] = m.get("em")
        it["titulo"] = m.get("titulo") or it["titulo"]
        it["descricao"] = m.get("descricao") if m.get("descricao") is not None else it["descricao"]
        it["editado"] = bool(m.get("titulo") or m.get("descricao") is not None)
        saida.append(it)
    saida.sort(key=lambda i: (-i["criado_em"], i["tipo"] != "longo", -(i["nota"] or 0), i["chave"]))
    return saida


def _item(chave: str) -> dict:
    for it in itens():
        if it["chave"] == chave:
            return it
    raise KeyError("Item não encontrado (o arquivo pode ter sido apagado).")


def marcar(chave: str, novo: str) -> dict:
    if novo not in ESTADOS:
        raise ValueError(f"Estado inválido: {novo}")
    _item(chave)
    with _trava:
        d = _ler()
        m = d["itens"].setdefault(chave, {})
        if novo == "pendente":
            m.pop("estado", None)
            m.pop("em", None)
        else:
            m.update(estado=novo, em=time.time())
        if not m:
            d["itens"].pop(chave)
        _gravar(d)
    if novo != "pendente":  # a pasta só servia para subir no Studio
        shutil.rmtree(_pasta_item(chave), ignore_errors=True)
    return estado()


def editar_textos(chave: str, titulo: str | None = None, descricao_nova: str | None = None) -> dict:
    """Troca o título ou a descrição do post (texto vazio no título = volta ao do projeto)."""
    _item(chave)
    with _trava:
        d = _ler()
        m = d["itens"].setdefault(chave, {})
        if titulo is not None:
            if titulo.strip():
                m["titulo"] = titulo.strip()[:100]
            else:
                m.pop("titulo", None)
        if descricao_nova is not None:
            m["descricao"] = descricao_nova.strip()[:5000]
        if not m:
            d["itens"].pop(chave)
        _gravar(d)
    return estado()


# ================================================================ pasta para o Studio

def nome_arquivo(titulo: str, usados: set[str] | None = None) -> str:
    """Título -> nome de arquivo válido no Windows, que o Studio transforma de volta no título."""
    usados = set() if usados is None else usados
    nome = "".join(TROCAS_NOME.get(ch, ch) for ch in (titulo or "").strip())
    nome = re.sub(r"[\x00-\x1f]", "", nome).strip(" .")[:95] or "video"
    final, n = nome, 2
    while final.lower() in usados:
        final, n = f"{nome} ({n})", n + 1
    usados.add(final.lower())
    return final + ".mp4"


def _pasta_item(chave: str) -> Path:
    return PASTA / re.sub(r"[^\w-]", "_", chave)


def _ligar(origem: str, destino: Path) -> None:
    try:
        os.link(origem, destino)  # mesmo disco: não ocupa espaço a mais
    except OSError:
        shutil.copy2(origem, destino)


def preparar_pasta(chave: str) -> Path:
    """Pasta do item com o vídeo (nome = título), a(s) thumbnail(s) e a descrição. Refeita a cada chamada."""
    it = _item(chave)
    pasta = _pasta_item(chave)
    with _trava:
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)
        _ligar(it["arquivo"], pasta / nome_arquivo(it["titulo"]))
        for k, t in enumerate(it["thumbs"], 1):
            _ligar(t, pasta / (f"thumbnail_{k}.jpg" if len(it["thumbs"]) > 1 else "thumbnail.jpg"))
        texto = f"TÍTULO\n{it['titulo']}\n\nDESCRIÇÃO\n{it['descricao']}\n"
        if it["tags"]:
            texto += f"\nTAGS\n{', '.join(it['tags'])}\n"
        (pasta / "descricao.txt").write_text(texto, encoding="utf-8-sig")
    return pasta


# ================================================================ estado para a interface

def estado() -> dict:
    d = _ler()
    lista = itens()
    publicos = [{k: v for k, v in it.items() if k not in ("arquivo", "thumbs")} for it in lista]
    contagem = {e: sum(1 for i in lista if i["estado"] == e) for e in ESTADOS}
    return {"canal": d["canal"], "studio_url": url_studio(d["canal"]), "itens": publicos, "contagem": contagem}
