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
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.background import BackgroundTask

import armazenamento
import biblioteca_audio as biblioteca
import config
import custos
import editor_ffmpeg as ef
import legendas
import longo
import pipeline
import planejador_llm as llm
import projetos
import transcricao as tr
import youtube
from jobs import fila
from modelos import Template

log = logging.getLogger("api")
config.preparar_pastas()
biblioteca.preparar()

app = FastAPI(title="Gadosso Edit")
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
        if meta.get("origem_url") and meta["status"] == "pronto":
            youtube.liberar_video(meta["id"])  # original de link baixado de novo só para uma prévia
    fila.antes = _antes_do_job
    fila.depois = youtube.liberar_video
    fila.iniciar()
    log.info("API pronta. Dados em %s", config.DADOS)


def _antes_do_job(pid: str, cancelado, tipo: str):
    """Vídeo de link já apagado: baixa de novo antes de reexportar, regenerar etc. (o processamento
    completo baixa por conta própria, mostrando o andamento)."""
    if tipo != "processar":
        youtube.garantir_video(pid, None, cancelado)


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
    sumidos = 0
    for c in m.get("clips", []):
        v = c.get("versao", 0)
        c["sem_arquivo"] = bool(c.get("arquivo")) and not Path(c["arquivo"]).exists()
        sumidos += c["sem_arquivo"]
        c["video_url"] = f"/api/projetos/{pid}/clips/{c['id']}/video?v={v}" if c.get("arquivo") and not c["sem_arquivo"] else None
        c["thumb_url"] = f"/api/projetos/{pid}/clips/{c['id']}/thumb?v={v}" if c.get("thumb") else None
        c["config_efetiva"] = pipeline.config_clip(meta, c) if meta.get("plano") else None
        c["capa_url"] = f"/api/projetos/{pid}/clips/{c['id']}/capa?v={v}" if c.get("capa") else None
        for chave in ("arquivo", "thumb", "corte_assinatura", "capa"):
            c.pop(chave, None)
    m["arquivos_sumidos"] = sumidos
    lg = m.get("longo")
    if lg:
        lg["sem_arquivo"] = not Path(lg.get("arquivo") or "").is_file()
        v = lg.get("versao", 0)
        lg["video_url"] = f"/api/projetos/{pid}/longo/video?v={v}"
        lg["srt_url"] = f"/api/projetos/{pid}/longo/srt?v={v}" if lg.get("srt") else None
        lg["texto_url"] = f"/api/projetos/{pid}/longo/texto?v={v}"
        lg["thumbs_url"] = [f"/api/projetos/{pid}/longo/thumb/{k}?v={v}" for k in range(len(lg.get("thumbs", [])))]
        for chave in ("arquivo", "srt", "texto", "thumbs"):
            lg.pop(chave, None)
    m["tipo"] = m.get("tipo", "curto")
    m["fila_pendentes"] = fila.pendentes()
    return m


def _resumo(meta: dict) -> dict:
    return {
        "id": meta["id"], "tipo": meta.get("tipo", "curto"), "nome": meta["nome"], "modo": meta["modo"],
        "status": meta["status"], "modo_longo": (meta.get("opcoes") or {}).get("modo_longo"),
        "duracao_final": (meta.get("longo") or {}).get("duracao"),
        "criado_em": meta["criado_em"], "progresso": meta.get("progresso", 0), "etapa": meta.get("etapa"),
        "num_clips": len([c for c in meta.get("clips", []) if c.get("arquivo")]),
        "melhor_nota": max([c.get("nota", 0) for c in meta.get("clips", [])] or [0]),
        "duracao_video": meta.get("duracao_video"), "thumb_url": f"/api/projetos/{meta['id']}/thumb",
        "erro": meta.get("erro"),
    }


# ================================================================ sistema e configurações

@app.post("/api/sistema/desligar")
def desligar():
    """Usado pelo ícone da bandeja ("Sair"): responde e desliga o servidor logo em seguida. O que estava
    processando pode ser continuado depois, de onde parou."""
    import os
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


_gpu_cache: list = []


def _nome_gpu() -> str | None:
    """Nome da placa NVIDIA (consultado uma vez só; o nvidia-smi abre console, então vai escondido)."""
    if not _gpu_cache:
        gpu = None
        try:
            saida = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                   capture_output=True, text=True, timeout=5,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            gpu = saida.stdout.strip() or None
        except Exception:
            pass
        _gpu_cache.append(gpu)
    return _gpu_cache[0]


@app.get("/api/sistema")
def sistema():
    return {
        "gpu": _nome_gpu(), "cuda": tr.gpu_disponivel(), "remotion": legendas.remotion_disponivel(),
        "tem_chave": bool(config.api_key()), "dados": str(config.DADOS), "fila": fila.pendentes(),
        "disco_livre": armazenamento.livre(),
        "claude_erro": llm.estado["ultimo_erro"],
        "job_atual": ({k: fila.atual[k] for k in ("pid", "tipo", "cid")} if fila.atual else None),
    }


def _mascarar(chave: str) -> str:
    return f"{chave[:7]}••••••••{chave[-4:]}" if len(chave) > 12 else ("••••" if chave else "")


@app.get("/api/config")
def ler_config():
    cfg = config.carregar()
    chave_ambiente = bool(__import__("os").environ.get("ANTHROPIC_API_KEY"))
    def mascara(v):
        return (v[:4] + "••••••••" + v[-4:]) if v else ""
    return {**cfg, "pexels_key": mascara(cfg.get("pexels_key") or ""),
            "pixabay_key": mascara(cfg.get("pixabay_key") or ""),
            "api_key": _mascarar(config.api_key()), "api_key_origem":
            "config" if cfg.get("api_key") else ("ambiente" if chave_ambiente else None)}


class ConfigEntrada(BaseModel):
    api_key: str | None = None
    pexels_key: str | None = None
    pixabay_key: str | None = None
    workspace_id: str | None = None
    modelo: str | None = None
    modelo_rapido: str | None = None
    pasta_saida: str | None = None
    usar_gpu: bool | None = None
    modelo_whisper: str | None = None
    idioma: str | None = None


@app.post("/api/config/testar")
def testar_chave():
    """Testa a chave do Claude com um pedido mínimo (~US$ 0,0001) e diz o que está errado, se estiver."""
    try:
        cliente = llm._cliente()
        modelo = config.carregar()["modelo"]
        cliente.messages.create(model=modelo, max_tokens=5, messages=[{"role": "user", "content": "Responda: ok"}])
        return {"ok": True, "mensagem": f"Chave funcionando ({modelo})."}
    except llm.ErroClaude as e:
        return {"ok": False, "mensagem": str(e)}
    except Exception as e:  # erros da API: chave inválida, sem créditos, workspace...
        texto = str(e)
        if "credit balance" in texto:
            texto = "A conta da API está sem créditos: adicione em console.anthropic.com (Plans & Billing)."
        elif "authentication" in texto.lower() or "401" in texto:
            texto = "Chave inválida: confira se copiou inteira (começa com sk-ant-)."
        elif "workspace" in texto:
            texto = "A chave precisa do ID do workspace: preencha o campo logo abaixo da chave."
        return {"ok": False, "mensagem": texto[:300]}


@app.get("/api/diagnostico")
def diagnostico():
    """Texto para o usuário copiar e mandar quando algo falhar: versões, GPU, disco, configuração SEM as
    chaves e o fim do log de erros."""
    import platform
    import sys

    def versao(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return (r.stdout or r.stderr).strip().splitlines()[0][:100]
        except Exception as e:
            return f"não encontrado ({type(e).__name__})"
    raiz = Path(__file__).resolve().parent.parent
    try:
        app_versao = (raiz / "versao.txt").read_text(encoding="utf-8").strip()
    except OSError:
        app_versao = "instalação de desenvolvimento"
    cfg = {k: v for k, v in config.carregar().items() if "key" not in k}
    try:
        log = (config.DADOS / "api_err.log").read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    except OSError:
        log = ["(sem log)"]
    linhas = [
        "=== Diagnóstico do Gadosso Edit ===",
        f"Versão do app: {app_versao}",
        f"Windows: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"FFmpeg: {versao(['ffmpeg', '-version'])}",
        f"Node: {versao(['node', '--version'])}",
        f"GPU: {_nome_gpu() or 'nenhuma NVIDIA'} | CUDA no Whisper: {tr.gpu_disponivel()}",
        f"Legenda animada (Remotion): {legendas.remotion_disponivel()}",
        f"Disco livre: {armazenamento.livre() / armazenamento.GB:.1f} GB | Dados em {config.DADOS}",
        f"Chave do Claude: {'configurada' if config.api_key() else 'FALTANDO'} | último erro: {llm.estado['ultimo_erro']}",
        f"Configuração: {json.dumps(cfg, ensure_ascii=False)}",
        "", "=== Fim do log de erros ===", *log,
    ]
    return {"texto": "\n".join(linhas)}


@app.put("/api/config")
def salvar_config(dados: ConfigEntrada):
    novos = {k: v for k, v in dados.model_dump().items() if v is not None}
    if "api_key" in novos and "••" in novos["api_key"]:
        novos.pop("api_key")  # veio a versão mascarada: não altera
    elif "api_key" in novos and not novos["api_key"].startswith("sk-ant-"):
        raise HTTPException(400, "Chave inválida: a chave da API da Anthropic começa com \"sk-ant-\".")
    for k in ("pexels_key", "pixabay_key"):
        if k in novos and "••" in novos[k]:
            novos.pop(k)  # versão mascarada: não altera
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


# ================================================================ templates

@app.get("/api/templates")
def listar_templates():
    return config.ler_json(config.ARQ_TEMPLATES, {})


@app.put("/api/templates/{nome}")
def salvar_template(nome: str, dados: dict):
    if not re.fullmatch(r"[a-z0-9_\-]{2,30}", nome):
        raise HTTPException(400, "Nome inválido (use letras minúsculas, números, - ou _)")
    try:
        template = Template.model_validate(dados)
    except ValidationError as e:
        raise HTTPException(400, f"Template inválido: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
    if template.preset not in legendas.carregar_estilos():
        raise HTTPException(400, f"Estilo de legenda '{template.preset}' não existe")
    templates = listar_templates()
    templates[nome] = template.model_dump()
    config.gravar_json(config.ARQ_TEMPLATES, templates)
    return templates


@app.delete("/api/templates/{nome}")
def excluir_template(nome: str):
    templates = listar_templates()
    templates.pop(nome, None)
    config.gravar_json(config.ARQ_TEMPLATES, templates)
    return templates


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
    return await _criar(instrucao, modo, opcoes, caminho, arquivo, "curto")


@app.post("/api/longos")
async def criar_longo(
    instrucao: str = Form(""),
    modo: str = Form("falado"),
    opcoes: str = Form("{}"),
    caminho: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    """Vídeo longo para o YouTube (aba "Vídeos longos"): enxugar o vídeo inteiro ou melhores momentos."""
    return await _criar(instrucao, modo, opcoes, caminho, arquivo, "longo")


async def _criar(instrucao: str, modo: str, opcoes: str, caminho: str, arquivo: UploadFile | None, tipo: str):
    if modo not in ("falado", "gameplay"):
        raise HTTPException(400, "Modo deve ser 'falado' ou 'gameplay'")
    try:
        opc = json.loads(opcoes or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "opcoes deve ser JSON")

    livre = armazenamento.livre()
    if livre < armazenamento.MINIMO_LIVRE:
        raise HTTPException(507, f"Pouco espaço em disco ({livre / armazenamento.GB:.1f} GB livres). "
                                 "Libere espaço em Configurações > Armazenamento antes de começar.")
    if arquivo is not None and arquivo.filename:
        ext = Path(arquivo.filename).suffix.lower()
        if ext not in EXTENSOES:
            raise HTTPException(400, f"Formato não suportado: {ext}")
        # Guarda pelo conteúdo: o mesmo vídeo enviado de novo não ocupa espaço outra vez
        armazenamento.PASTA_VIDEOS.mkdir(parents=True, exist_ok=True)
        temporario = armazenamento.PASTA_VIDEOS / f"envio_{uuid.uuid4().hex[:10]}.part"
        try:
            with open(temporario, "wb") as f:
                while bloco := await arquivo.read(4 * 1024 * 1024):
                    f.write(bloco)
            destino = armazenamento.guardar_envio(temporario, ext)
        finally:
            temporario.unlink(missing_ok=True)
        meta = projetos.criar(destino, arquivo.filename, modo, instrucao, opc, ja_copiado=True, tipo=tipo)
    elif youtube.e_link(caminho):
        try:
            info = youtube.informacoes(caminho)
        except youtube.ErroLink as e:
            raise HTTPException(400, str(e))
        meta = projetos.criar(youtube.caminho_local(info), info["titulo"], modo, instrucao, opc,
                              ja_copiado=True, tipo=tipo)
        meta = projetos.atualizar(meta["id"], lambda m: m.update(origem_url=caminho.strip(),
                                                                 duracao_video=info["duracao"]))
    elif caminho.strip():
        video = Path(caminho.strip().strip('"')).expanduser()
        if not video.is_file():
            raise HTTPException(400, f"Arquivo não encontrado: {video}")
        if video.suffix.lower() not in EXTENSOES:
            raise HTTPException(400, f"Formato não suportado: {video.suffix}")
        meta = projetos.criar(video.resolve(), video.name, modo, instrucao, opc, tipo=tipo)
    else:
        raise HTTPException(400, "Envie um arquivo de vídeo, o caminho local ou um link do YouTube")

    _enfileirar_processamento(meta["id"])
    return _publico(projetos.ler(meta["id"]))


def _enfileirar_processamento(pid: str):
    meta = projetos.atualizar(pid, lambda m: m.update(status="fila", erro=None, progresso=0.0, etapas={}))
    processar = longo.processar if meta.get("tipo") == "longo" else pipeline.processar
    fila.enviar(pid, "processar", lambda ev: processar(pid, ev))


@app.get("/api/projetos/{pid}/longo/{arquivo}")
def arquivo_longo(pid: str, arquivo: str):
    """Vídeo final, legenda .srt e texto do YouTube de um vídeo longo."""
    lg = _meta(pid).get("longo") or {}
    chave = {"video": "arquivo", "srt": "srt", "texto": "texto"}.get(arquivo)
    if not chave or not lg.get(chave) or not Path(lg[chave]).exists():
        raise HTTPException(404, "Arquivo não encontrado")
    caminho = Path(lg[chave])
    tipo = {"video": "video/mp4", "srt": "application/x-subrip", "texto": "text/plain; charset=utf-8"}[arquivo]
    return FileResponse(caminho, media_type=tipo, filename=caminho.name)


class Revisao(BaseModel):
    """Escolhas da revisão de um vídeo longo (só os campos que mudaram precisam vir)."""
    ritmo: str | None = None
    abertura_ativa: bool | None = None
    remocoes: list[dict] = []
    capitulos: list[dict] = []
    momentos: list[dict] = []


@app.put("/api/projetos/{pid}/edicao")
def revisar_longo(pid: str, dados: Revisao):
    """Aplica a revisão (trechos que voltam, ritmo, capítulos, momentos) e remonta o vídeo sem chamar o Claude."""
    meta = _meta(pid)
    if meta.get("tipo") != "longo" or not meta.get("edicao"):
        raise HTTPException(400, "Este projeto não tem uma edição para revisar")
    if meta["status"] in ("fila", "processando"):
        raise HTTPException(409, "O vídeo ainda está sendo processado")
    longo.aplicar_revisao(pid, dados.model_dump())
    projetos.atualizar(pid, lambda m: m.update(status="fila", erro=None, progresso=0.0))
    fila.enviar(pid, "processar", lambda ev: longo.remontar(pid, ev))
    return _publico(projetos.ler(pid))


_trava_previa = threading.BoundedSemaphore(2)
_baixando_de_novo: set[str] = set()


def _original_disponivel(meta: dict) -> None:
    """O original existe? Se veio de um link e foi apagado para economizar disco, começa a baixar de novo
    em segundo plano e responde 409 (a tela tenta de novo depois)."""
    if Path(meta["video"]).exists():
        return
    if not meta.get("origem_url"):
        raise HTTPException(404, "Vídeo original não encontrado")
    pid = meta["id"]
    if pid not in _baixando_de_novo:
        _baixando_de_novo.add(pid)

        def baixar():
            try:
                youtube.garantir_video(pid)
            except Exception as e:
                log.warning("Não consegui baixar de novo o original de %s: %s", pid, e)
            finally:
                _baixando_de_novo.discard(pid)
        threading.Thread(target=baixar, daemon=True).start()
    raise HTTPException(409, "O original veio de um link e foi apagado para economizar espaço. "
                             "Estou baixando de novo; tente em alguns minutos.")  # a lista pede várias prévias/quadros ao mesmo tempo


@app.get("/api/projetos/{pid}/previa")
def previa_trecho(pid: str, inicio: float, fim: float):
    """Trecho do vídeo ORIGINAL (com 1 s de folga de cada lado) em MP4 leve, para ouvir/ver o que saiu."""
    meta = _meta(pid)
    inicio, fim = max(0.0, inicio - 1), fim + 1
    if not 0 < fim - inicio <= 180:
        raise HTTPException(400, "Trecho inválido")
    arq = projetos.pasta(pid) / "tmp" / "previas" / f"{inicio:.2f}_{fim:.2f}.mp4"
    if not arq.exists():
        _original_disponivel(meta)
        arq.parent.mkdir(parents=True, exist_ok=True)
        with _trava_previa:
            parcial = arq.with_name(arq.stem + "_parcial.mp4")
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{inicio:.3f}", "-t", f"{fim - inicio:.3f}",
                            "-i", meta["video"], "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(parcial)],
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if not parcial.exists():
                raise HTTPException(500, "Não consegui gerar a prévia")
            parcial.replace(arq)
    return FileResponse(arq, media_type="video/mp4")


@app.get("/api/projetos/{pid}/quadro")
def quadro_original(pid: str, t: float):
    """Um quadro do vídeo original (miniatura dos trechos removidos na revisão)."""
    meta = _meta(pid)
    arq = projetos.pasta(pid) / "tmp" / "quadros" / f"{t:.1f}.jpg"
    if not arq.exists():
        _original_disponivel(meta)
        with _trava_previa:
            try:
                ef.extrair_frame(meta["video"], t, arq, largura=240)
            except Exception:
                raise HTTPException(404)
    return FileResponse(arq, media_type="image/jpeg")


@app.get("/api/projetos/{pid}/longo/thumb/{k}")
def thumb_longo(pid: str, k: int):
    thumbs = (_meta(pid).get("longo") or {}).get("thumbs") or []
    if not 0 <= k < len(thumbs) or not Path(thumbs[k]).exists():
        raise HTTPException(404)
    return FileResponse(thumbs[k], media_type="image/jpeg", filename=f"thumbnail_{k + 1}.jpg")


@app.get("/api/projetos/{pid}")
def ver_projeto(pid: str):
    return _publico(_meta(pid))


@app.delete("/api/projetos/{pid}")
def excluir_projeto(pid: str, apagar_saida: bool = False):
    meta = _meta(pid)
    fila.cancelar(pid)
    projetos.excluir(pid, apagar_saida)
    video = Path(meta.get("video") or "")
    if video.parent in (armazenamento.PASTA_VIDEOS, youtube.PASTA) and not armazenamento.em_uso(video):
        video.unlink(missing_ok=True)  # vídeo enviado que nenhum outro projeto usa
    return {"ok": True}


# ================================================================ armazenamento

def _ocupados() -> set[str]:
    return {fila.atual["pid"]} if fila.atual else set()


@app.get("/api/armazenamento")
def ver_armazenamento():
    return armazenamento.resumo()


@app.post("/api/armazenamento/limpar")
def limpar_temporarios():
    return {"liberado": armazenamento.limpar_temporarios(_ocupados()), **armazenamento.resumo()}


@app.post("/api/armazenamento/juntar")
def juntar_repetidos():
    return {"liberado": armazenamento.juntar_repetidos(_ocupados()), **armazenamento.resumo()}


@app.post("/api/projetos/{pid}/cancelar")
def cancelar(pid: str):
    meta = _meta(pid)
    fila.cancelar(pid)
    if meta["status"] == "fila":
        projetos.atualizar(pid, lambda m: m.update(status="cancelado"))
    return {"ok": True}


@app.post("/api/projetos/{pid}/reprocessar")
def reprocessar(pid: str, do_zero: bool = False):
    """Projeto pronto ("Refazer"): o Claude decide tudo de novo. Erro ou cancelado ("Tentar de novo"):
    continua de onde parou, sem pagar de novo as respostas do Claude que já chegaram e sem renderizar de
    novo o que já ficou pronto (clipes iguais; no vídeo longo, a edição salva e os blocos em cache).
    do_zero=true: recomeça tudo, inclusive as decisões do Claude (se o problema foi a própria decisão)."""
    meta = _meta(pid)
    if meta["status"] in ("fila", "processando"):
        raise HTTPException(409, "O projeto já está sendo processado")
    retomar = meta["status"] in ("erro", "cancelado") and not do_zero
    if not retomar:
        llm.esquecer_respostas(pid)
    projetos.atualizar(pid, lambda m: m.update(retomar=retomar))
    if retomar and meta.get("tipo") == "longo" and meta.get("edicao"):
        projetos.atualizar(pid, lambda m: m.update(status="fila", erro=None, progresso=0.0))
        fila.enviar(pid, "processar", lambda ev: longo.remontar(pid, ev))
    else:
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
    _original_disponivel(meta)
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


@app.get("/api/projetos/{pid}/clips/{cid}/capa")
def capa_clip(pid: str, cid: str, download: bool = False):
    meta = _meta(pid)
    try:
        c = projetos.clip(meta, cid)
    except KeyError:
        raise HTTPException(404)
    if not c.get("capa") or not Path(c["capa"]).exists():
        raise HTTPException(404, "Este clipe ainda não tem capa (exporte de novo para gerar)")
    return FileResponse(c["capa"], media_type="image/jpeg", filename=Path(c["capa"]).name if download else None)


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


CHAVES_CONFIG = {"look", "transicao", "zoom_forca", "impacto", "broll", "reacoes", "idioma_legenda", "replay", "loop","formato", "legenda_ativa", "estilo", "preset", "cor", "titulo_ativo", "zoom",
                 "remover_silencios", "normalizar", "layout", "deslocamento_x", "musica", "efeitos", "abertura",
                 "limpar_voz"}


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


@app.post("/api/projetos/{pid}/refazer-arquivos")
def refazer_arquivos(pid: str):
    """Refaz os vídeos que sumiram da pasta de saída (apagados ou movidos), sem chamar o Claude:
    clipes são renderizados de novo e o vídeo longo é remontado com a edição salva."""
    meta = _meta(pid)
    if meta["status"] in ("fila", "processando"):
        raise HTTPException(409, "O projeto já está sendo processado")
    if not Path(meta["video"]).exists() and not meta.get("origem_url"):
        raise HTTPException(400, "O vídeo de origem também não existe mais: não dá para refazer")
    if meta.get("tipo") == "longo":
        if not meta.get("edicao"):
            _enfileirar_processamento(pid)  # projeto antigo, sem a edição salva: refaz tudo
        else:
            projetos.atualizar(pid, lambda m: m.update(status="fila", erro=None, progresso=0.0))
            fila.enviar(pid, "processar", lambda ev: longo.remontar(pid, ev))
        return _publico(projetos.ler(pid))
    faltando = [c["id"] for c in meta["clips"] if c.get("arquivo") and not Path(c["arquivo"]).exists()]
    for cid in faltando:
        projetos.atualizar(pid, lambda m, cid=cid: projetos.clip(m, cid).update(status="fila", progresso=0.0))
        fila.enviar(pid, "renderizar", lambda ev, cid=cid: pipeline.renderizar_clip(pid, cid, cancelado=ev), cid)
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
    escolhidos = [c for c in meta["clips"] if c["id"] in ids and c.get("arquivo") and Path(c["arquivo"]).exists()]
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # mp4 já é comprimido
        for arq in arquivos:
            z.write(arq, arq.name)
        for c in escolhidos:  # capas junto
            if c.get("capa") and Path(c["capa"]).exists():
                z.write(c["capa"], Path(c["capa"]).name)
        z.writestr("posts.txt", pipeline.texto_dos_posts(escolhidos))
    return FileResponse(tmp, filename=tmp.name, media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, tmp.parent, True))


@app.post("/api/projetos/{pid}/abrir-pasta")
def abrir_pasta(pid: str):
    """Abre a pasta de saída no Explorer (é uma ferramenta local)."""
    meta = _meta(pid)
    if meta.get("saida_dir") and Path(meta["saida_dir"]).exists():
        subprocess.Popen(["explorer", meta["saida_dir"]], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"ok": True}


@app.get("/api/audio")
def biblioteca_audio():
    """Músicas por clima e quantidade de efeitos da biblioteca local."""
    return biblioteca.resumo()


@app.post("/api/audio/pacote")
def baixar_pacote_musicas():
    """Baixa em segundo plano o pacote inicial de músicas CC0 (acompanhe por GET /api/audio)."""
    biblioteca.preparar()
    faltando = biblioteca.pacote_faltando()
    if faltando and armazenamento.livre() < armazenamento.MINIMO_LIVRE:
        raise HTTPException(507, "Pouco espaço em disco para baixar as músicas.")
    if faltando:
        biblioteca.baixar_pacote()
    return biblioteca.resumo()


@app.get("/api/audio/arquivo")
def ouvir_audio(caminho: str):
    """Toca uma faixa da biblioteca (para ouvir antes de usar)."""
    arq = biblioteca.arquivo_da_biblioteca(caminho)
    if not arq:
        raise HTTPException(404, "Arquivo fora da biblioteca de áudio")
    return FileResponse(arq)


@app.delete("/api/audio/arquivo")
def excluir_audio(caminho: str):
    if not biblioteca.excluir(caminho):
        raise HTTPException(404, "Arquivo fora da biblioteca de áudio")
    return biblioteca.resumo()


@app.post("/api/audio/abrir-pasta")
def abrir_pasta_audio():
    biblioteca.preparar()
    subprocess.Popen(["explorer", str(biblioteca.PASTA_AUDIO)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
