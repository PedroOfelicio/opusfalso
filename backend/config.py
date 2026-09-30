"""
Configuração central do projeto.

Tudo que é pesado (vídeos, cache, projetos, clipes renderizados) fica em DADOS,
fora do OneDrive. O caminho pode ser trocado pela variável OPUSFALSO_DADOS.
As preferências do usuário ficam em DADOS/config.json (editável pela tela
Configurações).
"""
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path

# Pasta do código (backend/) e raiz do repositório
PASTA_BACKEND = Path(__file__).resolve().parent
RAIZ = PASTA_BACKEND.parent

# Pasta de dados (fora do OneDrive)
DADOS = Path(os.environ.get("OPUSFALSO_DADOS", r"C:\opusfalso-dados"))
PASTA_PROJETOS = DADOS / "projetos"
PASTA_CACHE = DADOS / "cache"
PASTA_FONTES = DADOS / "fontes"       # sem espaços no caminho: o FFmpeg/libass agradece
PASTA_MODELOS = DADOS / "modelos"
ARQ_CONFIG = DADOS / "config.json"
ARQ_CUSTOS = DADOS / "custos.json"
ARQ_ESTILOS = PASTA_BACKEND / "estilos.json"

# Recursos versionados no repositório (copiados para DADOS na primeira execução)
RECURSOS = PASTA_BACKEND / "recursos"

PADRAO = {
    "api_key": "",                      # vazio = usa a variável ANTHROPIC_API_KEY
    "modelo": "claude-sonnet-4-6",
    "pasta_saida": str(DADOS / "saida"),
    "usar_gpu": True,
    "modelo_whisper": "large-v3-turbo",
    "idioma": "",                       # vazio = detectar automaticamente
}

_trava = threading.Lock()


class Cancelado(Exception):
    """Levantada quando o usuário cancela um job."""


# Console do Windows: força UTF-8 para acentos saírem certos nos logs
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# O httpx loga cada requisição em INFO; deixamos só avisos
logging.getLogger("httpx").setLevel(logging.WARNING)


def preparar_pastas():
    """Cria as pastas de dados e copia fontes/modelos do repositório se faltarem."""
    for pasta in (DADOS, PASTA_PROJETOS, PASTA_CACHE, PASTA_FONTES, PASTA_MODELOS):
        pasta.mkdir(parents=True, exist_ok=True)
    for sub, destino in (("fontes", PASTA_FONTES), ("modelos", PASTA_MODELOS)):
        origem = RECURSOS / sub
        if origem.exists():
            for arq in origem.iterdir():
                alvo = destino / arq.name
                if not alvo.exists():
                    shutil.copy2(arq, alvo)
    Path(carregar()["pasta_saida"]).mkdir(parents=True, exist_ok=True)


def carregar() -> dict:
    """Lê config.json mesclando com os padrões."""
    cfg = dict(PADRAO)
    if ARQ_CONFIG.exists():
        try:
            cfg.update(json.loads(ARQ_CONFIG.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            logging.getLogger("config").warning("config.json inválido, usando padrões")
    return cfg


def salvar(novos: dict) -> dict:
    """Atualiza só as chaves conhecidas e grava em disco."""
    with _trava:
        cfg = carregar()
        for k, v in novos.items():
            if k in PADRAO:
                cfg[k] = v
        DADOS.mkdir(parents=True, exist_ok=True)
        ARQ_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return cfg


def api_key() -> str:
    """Chave salva na tela Configurações; se não houver, a do ambiente."""
    return carregar().get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")


def pasta_saida() -> Path:
    return Path(carregar()["pasta_saida"])


def ler_json(caminho: Path, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho: Path, dados) -> None:
    """Grava de forma atômica (arquivo temporário + rename) para não corromper."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, caminho)
