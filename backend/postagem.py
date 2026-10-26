"""
Postagem nos canais do YouTube sem a API (enquanto a auditoria do Google não sai): o app monta a fila do dia e
deixa tudo pronto para subir pelo YouTube Studio em poucos cliques.

- Canais: nome, link e quantos shorts por dia. O id do canal (UC...) sai do link, para o botão "Abrir Studio"
  cair direto na tela de upload daquele canal.
- Fila do dia: os clipes prontos de todos os projetos que ainda não foram postados, do melhor para o pior,
  distribuídos em "serpentina" entre os canais (1º, 2º... último, último... 1º), para cada canal receber clipes
  bons e médios. Um clipe nunca vai para dois canais.
- Pasta por canal: os vídeos com o NOME DO ARQUIVO = TÍTULO (o Studio usa o nome do arquivo como título) e um
  descricoes.txt. Os vídeos são "hard links" do clipe pronto (não ocupam espaço a mais), ou cópia se não der.

Tudo em DADOS/postagem.json; pastas em DADOS/postar/<data>/.
"""
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import config
import projetos

ARQ = config.DADOS / "postagem.json"
PASTA = config.DADOS / "postar"
_trava = threading.RLock()

# Caracteres proibidos no nome de arquivo do Windows -> parecidos permitidos (o título continua legível)
TROCAS_NOME = {"?": "？", ":": "：", "/": "／", "\\": "＼", "*": "＊", '"': "''", "<": "‹", ">": "›", "|": "｜"}


def _ler() -> dict:
    d = config.ler_json(ARQ, {}) or {}
    d.setdefault("canais", [])
    d.setdefault("postados", {})   # "pid/cid" -> {"canal": id | None, "em": ts}   (None = pulado)
    d.setdefault("fila", None)     # {"data": "AAAA-MM-DD", "itens": [{"canal", "clips": ["pid/cid"], "postado"}]}
    return d


def _gravar(d: dict) -> dict:
    config.gravar_json(ARQ, d)
    return d


def _hoje() -> str:
    return date.today().isoformat()


# ================================================================ canais

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


def salvar_canal(dados: dict, cid: str | None = None) -> dict:
    with _trava:
        d = _ler()
        canal = next((c for c in d["canais"] if c["id"] == cid), None) if cid else None
        if cid and canal is None:
            raise KeyError(cid)
        if canal is None:
            canal = {"id": uuid.uuid4().hex[:8], "ativo": True, "criado_em": time.time()}
            d["canais"].append(canal)
        if "nome" in dados:
            canal["nome"] = str(dados["nome"]).strip()[:60] or "Canal"
        if "url" in dados and dados["url"] != canal.get("url"):
            canal["url"] = str(dados["url"] or "").strip()
            canal["channel_id"] = id_do_canal(canal["url"])
        if "por_dia" in dados:
            canal["por_dia"] = max(1, min(int(dados["por_dia"]), 50))
        if "ativo" in dados:
            canal["ativo"] = bool(dados["ativo"])
        canal.setdefault("por_dia", 5)
        canal.setdefault("url", "")
        canal.setdefault("channel_id", None)
        _gravar(d)
        return canal


def excluir_canal(cid: str) -> None:
    with _trava:
        d = _ler()
        d["canais"] = [c for c in d["canais"] if c["id"] != cid]
        if d["fila"]:
            d["fila"]["itens"] = [i for i in d["fila"]["itens"] if i["canal"] != cid]
        _gravar(d)


def url_studio(canal: dict) -> str:
    if canal.get("channel_id"):
        return f"https://studio.youtube.com/channel/{canal['channel_id']}/videos/upload?d=ud"
    return "https://studio.youtube.com/"


# ================================================================ clipes e fila

def _clipes_prontos() -> dict[str, dict]:
    """"pid/cid" -> dados do clipe, de todos os projetos de clipes curtos (só os com arquivo no disco)."""
    saida = {}
    for meta in projetos.listar():
        if meta.get("tipo", "curto") != "curto":
            continue
        for c in meta.get("clips", []):
            if c.get("status") == "pronto" and c.get("arquivo") and Path(c["arquivo"]).is_file():
                saida[f"{meta['id']}/{c['id']}"] = {
                    "pid": meta["id"], "cid": c["id"], "projeto": meta.get("nome", ""), "arquivo": c["arquivo"],
                    "titulo": (c.get("titulo") or "").strip(), "nota": int(c.get("nota") or 0),
                    "descricao": descricao(c), "duracao": c.get("duracao"), "versao": c.get("versao", 0),
                    "criado_em": meta.get("criado_em", 0),
                }
    return saida


def descricao(clip: dict) -> str:
    texto = (clip.get("legenda_post") or "").strip()
    tags = [t if t.startswith("#") else f"#{t}" for t in (clip.get("hashtags") or [])]
    if not any(t.lower() == "#shorts" for t in tags):
        tags.append("#shorts")
    return (texto + "\n\n" + " ".join(tags)).strip()


def distribuir(chaves: list[str], canais: list[dict]) -> dict[str, list[str]]:
    """Serpentina: rodada 1 do 1º ao último canal, rodada 2 do último ao 1º... até cada um ter o seu por_dia.
    `chaves` já vem do melhor para o pior clipe."""
    vagas = {c["id"]: c.get("por_dia", 5) for c in canais}
    saida = {c["id"]: [] for c in canais}
    ordem = [c["id"] for c in canais]
    k, rodada = 0, 0
    while k < len(chaves) and any(vagas.values()):
        for cid in (ordem if rodada % 2 == 0 else ordem[::-1]):
            if k >= len(chaves):
                break
            if vagas[cid] > 0:
                saida[cid].append(chaves[k])
                vagas[cid] -= 1
                k += 1
        rodada += 1
    return saida


def montar_fila() -> dict:
    """Refaz a fila de hoje com os clipes ainda não postados. Canais já marcados como postados hoje ficam como
    estão; os outros recebem os melhores clipes disponíveis."""
    with _trava:
        d = _ler()
        prontos = _clipes_prontos()
        fila = d["fila"] if d["fila"] and d["fila"]["data"] == _hoje() else {"data": _hoje(), "itens": []}
        feitos = [i for i in fila["itens"] if i.get("postado")]
        ocupados = {k for i in feitos for k in i["clips"]}
        livres = [k for k in prontos if k not in d["postados"] and k not in ocupados]
        livres.sort(key=lambda k: (-prontos[k]["nota"], -prontos[k]["criado_em"], k))
        canais = [c for c in d["canais"] if c.get("ativo", True) and c["id"] not in {i["canal"] for i in feitos}]
        partes = distribuir(livres, canais)
        fila["itens"] = feitos + [{"canal": c["id"], "clips": partes[c["id"]], "postado": False}
                                  for c in canais if partes[c["id"]]]
        ordem = {c["id"]: k for k, c in enumerate(d["canais"])}
        fila["itens"].sort(key=lambda i: ordem.get(i["canal"], 999))
        d["fila"] = fila
        _gravar(d)
    return estado()


def _item(d: dict, canal_id: str) -> dict:
    fila = d["fila"]
    if not fila or fila["data"] != _hoje():
        raise KeyError("Sem fila de hoje: monte a fila primeiro.")
    for i in fila["itens"]:
        if i["canal"] == canal_id:
            return i
    raise KeyError("Canal fora da fila de hoje.")


def pular(chave: str) -> dict:
    """Tira o clipe da fila e nunca mais o oferece (clipe ruim)."""
    with _trava:
        d = _ler()
        d["postados"][chave] = {"canal": None, "em": time.time()}
        if d["fila"]:
            for i in d["fila"]["itens"]:
                if chave in i["clips"] and not i.get("postado"):
                    i["clips"].remove(chave)
        _gravar(d)
    return estado()


def marcar_postado(canal_id: str, postado: bool = True) -> dict:
    with _trava:
        d = _ler()
        item = _item(d, canal_id)
        item["postado"] = postado
        for k in item["clips"]:
            if postado:
                d["postados"][k] = {"canal": canal_id, "em": time.time()}
            else:
                d["postados"].pop(k, None)
        _gravar(d)
    if postado:  # a pasta só servia para subir no Studio
        shutil.rmtree(_pasta_canal(canal_id), ignore_errors=True)
    return estado()


# ================================================================ pasta para o Studio

def nome_arquivo(titulo: str, usados: set[str]) -> str:
    """Título -> nome de arquivo válido no Windows, que o Studio transforma de volta no título."""
    nome = "".join(TROCAS_NOME.get(ch, ch) for ch in (titulo or "").strip())
    nome = re.sub(r"[\x00-\x1f]", "", nome).strip(" .")[:95] or "short"
    final, n = nome, 2
    while final.lower() in usados:
        final, n = f"{nome} ({n})", n + 1
    usados.add(final.lower())
    return final + ".mp4"


def _pasta_canal(canal_id: str) -> Path:
    d = _ler()
    canais = d["canais"]
    pos = next((k for k, c in enumerate(canais) if c["id"] == canal_id), None)
    nome = canais[pos]["nome"] if pos is not None else canal_id
    seguro = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .") or canal_id
    return PASTA / _hoje() / f"{(pos or 0) + 1:02d} - {seguro}"


def preparar_pasta(canal_id: str) -> Path:
    """Pasta do canal com os vídeos (nome = título) e o descricoes.txt. Refeita a cada chamada."""
    with _trava:
        d = _ler()
        item = _item(d, canal_id)
        prontos = _clipes_prontos()
        pasta = _pasta_canal(canal_id)
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)
        usados, linhas = set(), []
        for k in item["clips"]:
            c = prontos.get(k)
            if not c:
                continue
            arq = pasta / nome_arquivo(c["titulo"], usados)
            try:
                os.link(c["arquivo"], arq)  # mesmo disco: não ocupa espaço a mais
            except OSError:
                shutil.copy2(c["arquivo"], arq)
            linhas += [f"=== {arq.stem}", c["descricao"], ""]
        (pasta / "descricoes.txt").write_text("\n".join(linhas), encoding="utf-8-sig")
        _limpar_dias_antigos()
        return pasta


def _limpar_dias_antigos() -> None:
    for p in PASTA.glob("*"):
        if p.is_dir() and p.name < _hoje():
            shutil.rmtree(p, ignore_errors=True)


# ================================================================ estado para a interface

def estado() -> dict:
    d = _ler()
    prontos = _clipes_prontos()
    fila = d["fila"] if d["fila"] and d["fila"]["data"] == _hoje() else None
    na_fila = {k for i in (fila or {}).get("itens", []) for k in i["clips"]}
    por_canal = {c["id"]: c for c in d["canais"]}
    itens = []
    for i in (fila or {}).get("itens", []):
        canal = por_canal.get(i["canal"])
        if not canal:
            continue
        clips = []
        for k in i["clips"]:
            c = prontos.get(k)
            if not c:
                continue
            clips.append({"chave": k, "pid": c["pid"], "cid": c["cid"], "titulo": c["titulo"], "nota": c["nota"],
                          "descricao": c["descricao"], "projeto": c["projeto"], "duracao": c["duracao"],
                          "thumb_url": f"/api/projetos/{c['pid']}/clips/{c['cid']}/thumb?v={c['versao']}",
                          "video_url": f"/api/projetos/{c['pid']}/clips/{c['cid']}/video?v={c['versao']}"})
        itens.append({"canal": canal, "postado": bool(i.get("postado")), "clips": clips,
                      "studio_url": url_studio(canal)})
    disponiveis = sum(1 for k in prontos if k not in d["postados"] and k not in na_fila)
    return {"canais": d["canais"], "data": _hoje(), "fila": itens, "disponiveis": disponiveis,
            "postados_total": sum(1 for v in d["postados"].values() if v.get("canal"))}
