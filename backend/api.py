"""
API local (FastAPI). Rodar com:

    uvicorn api:app --port 8000        (dentro da pasta backend/)

Sem login: só escuta em 127.0.0.1. Jobs longos rodam na fila (jobs.py) e a
interface acompanha o progresso fazendo polling em GET /api/projetos/{id}.
"""
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

import config
import custos
import legendas
import pipeline
import projetos
import transcricao as tr
from jobs import fila

log = logging.getLogger("api")
config.preparar_pastas()

app = FastAPI(title="Editor de vídeo local com IA")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

EXTENSOES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


@app.on_event("startup")
def _inicio():
    # Jobs que estavam rodando quando o servidor caiu não voltam sozinhos
    for meta in projetos.listar():
        mudou = False
        if meta["status"] in ("fila", "processando"):
            meta.update(status="erro", erro="Processamento interrompido (o servidor foi reiniciado). Use 'Tentar de novo'.")
            mudou = True
        for c in meta.get("clips", []):
            if c.get("status") in ("fila", "renderizando", "cortado"):
                c["status"] = "pronto" if c.get("arquivo") else "erro"
                mudou = True
        if mudou:
            projetos.salvar(meta)
    fila.iniciar()
    log.info("API pronta. Dados em %s", config.DADOS)


# ================================================================ utilidades

def _meta(pid: str) -> dict:
    try:
        meta = projetos.ler(pid)
    except ValueError:
        meta = None
    if not meta:
        raise HTTPException(404, "Projeto não encontrado")
    return meta


def _publico(meta: dict) -> dict:
    """Versão do meta para a interface: sem caminhos internos, com ETA e URLs."""
    m = json.loads(json.dumps(meta))
    pid = m["id"]
    m["thumb_url"] = f"/api/projetos/{pid}/thumb"
    agora = time.time()
    if m["status"] == "processando" and m.get("iniciado_em") and m.get("progresso", 0) > 0.02:
        decorrido = agora - m["iniciado_em"]
        m["restante_s"] = round(decorrido * (1 - m["progresso"]) / m["progresso"])
    for c in m.get("clips", []):
        v = c.get("versao", 0)
        c["video_url"] = f"/api/projetos/{pid}/clips/{c['id']}/video?v={v}" if c.get("arquivo") else None
        c["thumb_url"] = f"/api/projetos/{pid}/clips/{c['id']}/thumb?v={v}" if c.get("thumb") else None
        c["config_efetiva"] = pipeline.config_clip(meta, c) if meta.get("plano") else None
        for chave in ("arquivo", "thumb", "corte_assinatura"):
            c.pop(chave, None)
    m["fila_pendentes"] = fila.pendentes()
    return m


def _resumo(meta: dict) -> dict:
    return {
        "id": meta["id"], "nome": meta["nome"], "modo": meta["modo"], "status": meta["status"],
        "criado_em": meta["criado_em"], "progresso": meta.get("progresso", 0), "etapa": meta.get("etapa"),
        "num_clips": len([c for c in meta.get("clips", []) if c.get("arquivo")]),
        "melhor_nota": max([c.get("nota", 0) for c in meta.get("clips", [])] or [0]),
        "duracao_video": meta.get("duracao_video"), "thumb_url": f"/api/projetos/{meta['id']}/thumb",
        "erro": meta.get("erro"),
    }


# ================================================================ sistema e configurações

@app.get("/api/sistema")
def sistema():
    gpu = None
    try:
        saida = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=5)
        gpu = saida.stdout.strip() or None
    except Exception:
        pass
    return {
        "gpu": gpu, "cuda": tr.gpu_disponivel(), "remotion": legendas.remotion_disponivel(),
        "tem_chave": bool(config.api_key()), "dados": str(config.DADOS), "fila": fila.pendentes(),
        "claude_erro": pipeline.llm.estado["ultimo_erro"],
        "job_atual": ({k: fila.atual[k] for k in ("pid", "tipo", "cid")} if fila.atual else None),
    }


def _mascarar(chave: str) -> str:
    return f"{chave[:7]}••••••••{chave[-4:]}" if len(chave) > 12 else ("••••" if chave else "")


@app.get("/api/config")
def ler_config():
    cfg = config.carregar()
    chave_ambiente = bool(__import__("os").environ.get("ANTHROPIC_API_KEY"))
    return {**cfg, "api_key": _mascarar(config.api_key()), "api_key_origem":
            "config" if cfg.get("api_key") else ("ambiente" if chave_ambiente else None)}


class ConfigEntrada(BaseModel):
    api_key: str | None = None
    modelo: str | None = None
    pasta_saida: str | None = None
    usar_gpu: bool | None = None
    modelo_whisper: str | None = None
    idioma: str | None = None


@app.put("/api/config")
def salvar_config(dados: ConfigEntrada):
    novos = {k: v for k, v in dados.model_dump().items() if v is not None}
    if "api_key" in novos and "••" in novos["api_key"]:
        novos.pop("api_key")  # veio a versão mascarada: não altera
    if "pasta_saida" in novos:
        Path(novos["pasta_saida"]).mkdir(parents=True, exist_ok=True)
    config.salvar(novos)
    return ler_config()


@app.get("/api/custos")
def ler_custos():
    r = custos.resumo()
    return {"total": r["total"], "chamadas": r["chamadas"], "historico": r["historico"][-50:][::-1]}


@app.delete("/api/custos")
def zerar_custos():
    custos.zerar()
    return {"ok": True}


# ================================================================ estilos e fontes

@app.get("/api/estilos")
def listar_estilos():
    return legendas.carregar_estilos()


@app.put("/api/estilos/{nome}")
def salvar_estilo(nome: str, estilo: dict):
    if not re.fullmatch(r"[a-z0-9_\-]{2,30}", nome):
        raise HTTPException(400, "Nome inválido (use letras minúsculas, números, - ou _)")
    obrigatorios = {"fonte", "tamanho", "cor_texto", "cor_destaque"}
    if not obrigatorios <= estilo.keys():
        raise HTTPException(400, f"Campos obrigatórios: {', '.join(sorted(obrigatorios))}")
    estilos = legendas.carregar_estilos()
    estilos[nome] = estilo
    config.gravar_json(config.ARQ_ESTILOS, estilos)
    return estilos


@app.delete("/api/estilos/{nome}")
def excluir_estilo(nome: str):
    estilos = legendas.carregar_estilos()
    if len(estilos) <= 1:
        raise HTTPException(400, "Precisa existir pelo menos um estilo")
    estilos.pop(nome, None)
    config.gravar_json(config.ARQ_ESTILOS, estilos)
    return estilos


def _nome_fonte(caminho: Path) -> str:
    """Lê o nome da fonte na tabela 'name' do TTF/OTF (o mesmo que o libass usa)."""
    import struct
    try:
        dados = caminho.read_bytes()
        for i in range(struct.unpack(">H", dados[4:6])[0]):
            tag, _, inicio, _ = struct.unpack(">4sIII", dados[12 + 16 * i: 28 + 16 * i])
            if tag != b"name":
                continue
            _, qtd, base = struct.unpack(">HHH", dados[inicio:inicio + 6])
            nomes = {}
            for j in range(qtd):
                plat, _, _, nid, tam, off = struct.unpack(">HHHHHH", dados[inicio + 6 + 12 * j: inicio + 18 + 12 * j])
                bruto = dados[inicio + base + off: inicio + base + off + tam]
                if plat == 3:
                    nomes.setdefault(nid, bruto.decode("utf-16-be", "ignore"))
                elif plat == 1:
                    nomes.setdefault(nid, bruto.decode("latin-1"))
            # "Anton" (Regular) -> nome da família; "Montserrat Black" -> nome completo
            return nomes.get(1) if nomes.get(2) == "Regular" else (nomes.get(4) or nomes.get(1))
    except Exception:
        pass
    return caminho.stem


@app.get("/api/fontes")
def listar_fontes():
    return [{"arquivo": f.name, "nome": _nome_fonte(f), "url": f"/api/fontes/{f.name}"}
            for f in sorted(config.PASTA_FONTES.glob("*.[ot]tf"))]


@app.get("/api/fontes/{arquivo}")
def baixar_fonte(arquivo: str):
    caminho = config.PASTA_FONTES / Path(arquivo).name
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho, headers={"Cache-Control": "max-age=86400"})


# ================================================================ projetos

@app.get("/api/projetos")
def listar_projetos():
    return [_resumo(m) for m in projetos.listar()]


@app.post("/api/projetos")
async def criar_projeto(
    instrucao: str = Form(""),
    modo: str = Form("falado"),
    opcoes: str = Form("{}"),
    caminho: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    if modo not in ("falado", "gameplay"):
        raise HTTPException(400, "Modo deve ser 'falado' ou 'gameplay'")
    try:
        opc = json.loads(opcoes or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "opcoes deve ser JSON")

    if arquivo is not None and arquivo.filename:
        ext = Path(arquivo.filename).suffix.lower()
        if ext not in EXTENSOES:
            raise HTTPException(400, f"Formato não suportado: {ext}")
        meta = projetos.criar("", arquivo.filename, modo, instrucao, opc, ja_copiado=True)
        destino = projetos.pasta(meta["id"]) / f"original{ext}"
        with open(destino, "wb") as f:
            while bloco := await arquivo.read(4 * 1024 * 1024):
                f.write(bloco)
        meta = projetos.atualizar(meta["id"], lambda m: m.update(video=str(destino)))
    elif caminho.strip():
        video = Path(caminho.strip().strip('"')).expanduser()
        if not video.is_file():
            raise HTTPException(400, f"Arquivo não encontrado: {video}")
        if video.suffix.lower() not in EXTENSOES:
            raise HTTPException(400, f"Formato não suportado: {video.suffix}")
        meta = projetos.criar(video.resolve(), video.name, modo, instrucao, opc)
    else:
        raise HTTPException(400, "Envie um arquivo de vídeo ou informe o caminho local")

    _enfileirar_processamento(meta["id"])
    return _publico(projetos.ler(meta["id"]))


def _enfileirar_processamento(pid: str):
    projetos.atualizar(pid, lambda m: m.update(status="fila", erro=None, progresso=0.0, etapas={}))
    fila.enviar(pid, "processar", lambda ev: pipeline.processar(pid, ev))


@app.get("/api/projetos/{pid}")
def ver_projeto(pid: str):
    return _publico(_meta(pid))


@app.delete("/api/projetos/{pid}")
def excluir_projeto(pid: str, apagar_saida: bool = False):
    _meta(pid)
    fila.cancelar(pid)
    projetos.excluir(pid, apagar_saida)
    return {"ok": True}


@app.post("/api/projetos/{pid}/cancelar")
def cancelar(pid: str):
    meta = _meta(pid)
    fila.cancelar(pid)
    if meta["status"] == "fila":
        projetos.atualizar(pid, lambda m: m.update(status="cancelado"))
    return {"ok": True}


@app.post("/api/projetos/{pid}/reprocessar")
def reprocessar(pid: str):
    meta = _meta(pid)
    if meta["status"] in ("fila", "processando"):
        raise HTTPException(409, "O projeto já está sendo processado")
    _enfileirar_processamento(pid)
    return _publico(projetos.ler(pid))


@app.get("/api/projetos/{pid}/thumb")
def thumb_projeto(pid: str):
    arq = projetos.pasta(pid) / "thumb.jpg"
    if not arq.exists():
        raise HTTPException(404)
    return FileResponse(arq)


@app.get("/api/projetos/{pid}/video")
def video_original(pid: str):
    meta = _meta(pid)
    if not Path(meta["video"]).exists():
        raise HTTPException(404, "Vídeo original não encontrado")
    return FileResponse(meta["video"])


@app.get("/api/projetos/{pid}/palavras")
def palavras(pid: str, inicio: float, fim: float, cid: str | None = None):
    """Palavras do vídeo original num intervalo (para o editor), com as edições do clipe."""
    meta = _meta(pid)
    transcricao = tr.transcrever(meta["video"])  # vem do cache
    edicoes = projetos.clip(meta, cid).get("palavras_editadas", {}) if cid else {}
    resultado = []
    for w in transcricao["palavras"]:
        if inicio - 0.05 <= w["i"] <= fim + 0.05:
            chave = f"{w['i']:.3f}"
            resultado.append({"chave": chave, "original": w["p"], "p": edicoes.get(chave, w["p"]),
                              "i": w["i"], "f": w["f"]})
    return resultado


# ================================================================ clipes

def _arquivo_clip(pid: str, cid: str) -> Path:
    meta = _meta(pid)
    try:
        c = projetos.clip(meta, cid)
    except KeyError:
        raise HTTPException(404, "Clipe não encontrado")
    if not c.get("arquivo") or not Path(c["arquivo"]).exists():
        raise HTTPException(404, "Clipe ainda não renderizado")
    return Path(c["arquivo"])


@app.get("/api/projetos/{pid}/clips/{cid}/video")
def video_clip(pid: str, cid: str, download: bool = False):
    arq = _arquivo_clip(pid, cid)
    if download:
        meta = _meta(pid)
        return FileResponse(arq, filename=f"{meta['nome']}_{arq.name}", media_type="video/mp4")
    return FileResponse(arq, media_type="video/mp4")


@app.get("/api/projetos/{pid}/clips/{cid}/thumb")
def thumb_clip(pid: str, cid: str):
    meta = _meta(pid)
    try:
        c = projetos.clip(meta, cid)
    except KeyError:
        raise HTTPException(404)
    if not c.get("thumb") or not Path(c["thumb"]).exists():
        raise HTTPException(404)
    return FileResponse(c["thumb"])


class EdicaoClip(BaseModel):
    titulo: str | None = None
    inicio: float | None = None
    fim: float | None = None
    config: dict | None = None               # preferências (preset, cor, layout, formato...)
    palavras_editadas: dict[str, str] | None = None


CHAVES_CONFIG = {"formato", "legenda_ativa", "estilo", "preset", "cor", "titulo_ativo", "zoom",
                 "remover_silencios", "normalizar", "layout", "deslocamento_x", "musica"}


@app.patch("/api/projetos/{pid}/clips/{cid}")
def editar_clip(pid: str, cid: str, dados: EdicaoClip):
    meta = _meta(pid)
    if dados.inicio is not None and dados.fim is not None and dados.fim - dados.inicio < 2:
        raise HTTPException(400, "O clipe precisa ter pelo menos 2 segundos")

    def f(m):
        c = projetos.clip(m, cid)
        if dados.titulo is not None:
            c["titulo"] = dados.titulo.strip()[:120]
        if dados.inicio is not None:
            c["inicio"] = max(0.0, round(dados.inicio, 2))
        if dados.fim is not None:
            c["fim"] = min(meta.get("duracao_video") or dados.fim, round(dados.fim, 2))
        if dados.config is not None:
            cfg = c.setdefault("config", {})
            for k, v in dados.config.items():
                if k in CHAVES_CONFIG:
                    if v is None:
                        cfg.pop(k, None)
                    else:
                        cfg[k] = v
        if dados.palavras_editadas is not None:
            c["palavras_editadas"] = {k: v for k, v in dados.palavras_editadas.items()}
        c["editado"] = True
    try:
        return _publico(projetos.atualizar(pid, f))
    except KeyError:
        raise HTTPException(404, "Clipe não encontrado")


@app.post("/api/projetos/{pid}/clips/{cid}/renderizar")
def renderizar(pid: str, cid: str):
    _meta(pid)
    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(status="fila", progresso=0.0))
    fila.enviar(pid, "renderizar", lambda ev: pipeline.renderizar_clip(pid, cid, cancelado=ev), cid)
    return _publico(projetos.ler(pid))


@app.post("/api/projetos/{pid}/clips/{cid}/regenerar")
def regenerar(pid: str, cid: str):
    _meta(pid)
    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(status="fila", progresso=0.0))
    fila.enviar(pid, "regenerar", lambda ev: pipeline.regenerar_clip(pid, cid, cancelado=ev), cid)
    return _publico(projetos.ler(pid))


@app.delete("/api/projetos/{pid}/clips/{cid}")
def excluir_clip(pid: str, cid: str):
    meta = _meta(pid)
    try:
        c = projetos.clip(meta, cid)
    except KeyError:
        raise HTTPException(404)
    for chave in ("arquivo", "thumb"):
        if c.get(chave):
            Path(c[chave]).unlink(missing_ok=True)

    def f(m):
        m.setdefault("descartados", []).append((c["inicio"], c["fim"]))
        m["clips"] = [x for x in m["clips"] if x["id"] != cid]
    return _publico(projetos.atualizar(pid, f))


class PedidoAjuste(BaseModel):
    pedido: str
    clips: list[str]


@app.post("/api/projetos/{pid}/ajustar")
def ajustar(pid: str, dados: PedidoAjuste):
    meta = _meta(pid)
    ids = [c["id"] for c in meta["clips"] if c["id"] in dados.clips]
    if not ids or not dados.pedido.strip():
        raise HTTPException(400, "Selecione clipes e escreva o ajuste")

    def f(m):
        for c in m["clips"]:
            if c["id"] in ids:
                c.update(status="fila", progresso=0.0)
    projetos.atualizar(pid, f)
    fila.enviar(pid, "ajustar", lambda ev: pipeline.aplicar_ajuste(pid, dados.pedido, ids, cancelado=ev))
    return _publico(projetos.ler(pid))


@app.get("/api/projetos/{pid}/zip")
def baixar_zip(pid: str, clips: str = ""):
    meta = _meta(pid)
    ids = set(filter(None, clips.split(","))) or {c["id"] for c in meta["clips"]}
    arquivos = [Path(c["arquivo"]) for c in meta["clips"] if c["id"] in ids and c.get("arquivo") and Path(c["arquivo"]).exists()]
    if not arquivos:
        raise HTTPException(404, "Nenhum clipe pronto para baixar")
    tmp = Path(tempfile.mkdtemp()) / f"{meta['nome']}_clipes.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # mp4 já é comprimido
        for arq in arquivos:
            z.write(arq, arq.name)
    return FileResponse(tmp, filename=tmp.name, media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, tmp.parent, True))


@app.post("/api/projetos/{pid}/abrir-pasta")
def abrir_pasta(pid: str):
    """Abre a pasta de saída no Explorer (é uma ferramenta local)."""
    meta = _meta(pid)
    if meta.get("saida_dir") and Path(meta["saida_dir"]).exists():
        subprocess.Popen(["explorer", meta["saida_dir"]])
    return {"ok": True}


# ================================================================ interface compilada (opcional)

DIST = config.RAIZ / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str):
        if caminho.startswith("api/"):
            return JSONResponse({"detail": "Não encontrado"}, status_code=404)
        arq = DIST / caminho
        return FileResponse(arq if caminho and arq.is_file() else DIST / "index.html")
