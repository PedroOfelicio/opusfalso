"""
Projetos em disco: DADOS/projetos/<id>/meta.json

Estrutura de um projeto:
  meta.json      metadados (status, etapas, plano, clipes...)
  original.mp4   vídeo enviado (quando veio por upload; caminhos locais não são copiados)
  thumb.jpg      miniatura do vídeo
  tmp/           arquivos intermediários (cortes, .ass, props do Remotion)
  thumbs/        miniaturas dos clipes
Os clipes finais vão para <pasta_saida>/<nome_do_video>/clip_01.mp4 ...
"""
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import config

_trava = threading.RLock()


def pasta(pid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{8,32}", pid or ""):
        raise ValueError("id de projeto inválido")
    return config.PASTA_PROJETOS / pid


def ler(pid: str) -> dict | None:
    return config.ler_json(pasta(pid) / "meta.json")


def salvar(meta: dict) -> dict:
    with _trava:
        meta["atualizado_em"] = time.time()
        config.gravar_json(pasta(meta["id"]) / "meta.json", meta)
    return meta


def atualizar(pid: str, funcao) -> dict:
    """Lê, aplica funcao(meta) e grava, tudo sob trava (seguro entre threads)."""
    with _trava:
        meta = ler(pid)
        if meta is None:
            raise KeyError(pid)
        funcao(meta)
        return salvar(meta)


def listar() -> list[dict]:
    projetos = []
    for p in config.PASTA_PROJETOS.glob("*/meta.json"):
        meta = config.ler_json(p)
        if meta:
            projetos.append(meta)
    return sorted(projetos, key=lambda m: m.get("criado_em", 0), reverse=True)


def excluir(pid: str, apagar_saida: bool = False) -> None:
    meta = ler(pid)
    if apagar_saida and meta and meta.get("saida_dir"):
        shutil.rmtree(meta["saida_dir"], ignore_errors=True)
    shutil.rmtree(pasta(pid), ignore_errors=True)


def _nome_seguro(nome: str) -> str:
    nome = re.sub(r"[^\w\-. ]", "_", nome, flags=re.UNICODE).strip(" .")
    return nome[:80] or "video"


def pasta_saida_para(nome_video: str, pid: str) -> Path:
    """saida/<nome_do_video>/ ; se já pertencer a outro projeto, usa <nome>_2, _3..."""
    base = config.pasta_saida()
    nome = _nome_seguro(nome_video)
    candidato, n = base / nome, 1
    while True:
        marcador = candidato / ".projeto"
        if not candidato.exists() or (marcador.exists() and marcador.read_text().strip() == pid):
            break
        n += 1
        candidato = base / f"{nome}_{n}"
    candidato.mkdir(parents=True, exist_ok=True)
    (candidato / ".projeto").write_text(pid)
    return candidato


def criar(video: str | Path, nome_original: str, modo: str, instrucao: str, opcoes: dict,
          ja_copiado: bool = False) -> dict:
    """Cria o projeto. `video` é o caminho do arquivo (upload já salvo ou caminho local)."""
    pid = uuid.uuid4().hex[:12]
    p = pasta(pid)
    (p / "tmp").mkdir(parents=True, exist_ok=True)
    (p / "thumbs").mkdir(exist_ok=True)
    nome = Path(nome_original).stem
    meta = {
        "id": pid,
        "nome": nome,
        "video": str(video),
        "video_copiado": ja_copiado,
        "modo": modo,
        "instrucao": instrucao,
        "opcoes": opcoes,
        "criado_em": time.time(),
        "status": "fila",           # fila | processando | pronto | erro | cancelado
        "etapa": None,
        "progresso": 0.0,
        "etapas": {},
        "iniciado_em": None,
        "erro": None,
        "avisos": [],
        "nao_atendido": [],
        "plano": None,
        "clips": [],
        "saida_dir": None,
        "custo": 0.0,
    }
    return salvar(meta)


def clip(meta: dict, cid: str) -> dict:
    for c in meta["clips"]:
        if c["id"] == cid:
            return c
    raise KeyError(f"clipe {cid} não encontrado")
