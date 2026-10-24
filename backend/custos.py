"""
Estimativa de custo das chamadas ao Claude.

Cada chamada registra tokens de entrada/saída; o total acumulado fica em
DADOS/custos.json e aparece na tela Configurações e no fim do CLI.
Também soma, na hora, no projeto (meta "custo" e "custo_etapas") e em quem estiver medindo com medir()
(ex.: o custo próprio de um clipe).
Preços em US$ por milhão de tokens (entrada, saída).
"""
import logging
import threading
import time
from contextlib import contextmanager

import config

PRECOS = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5-1": (10.00, 50.00),
}
PRECO_PADRAO = (3.00, 15.00)

_trava = threading.Lock()
_local = threading.local()


@contextmanager
def medir():
    """Soma o custo das chamadas feitas nesta thread dentro do bloco:
    with medir() as gasto: ...  ->  gasto["custo"]. Medições aninhadas somam também na de fora."""
    de_fora = getattr(_local, "medida", None)
    gasto = {"custo": 0.0}
    _local.medida = gasto
    try:
        yield gasto
    finally:
        _local.medida = de_fora
        if de_fora is not None:
            de_fora["custo"] += gasto["custo"]


def _somar_no_projeto(projeto_id: str, custo: float, motivo: str) -> None:
    import projetos  # aqui dentro: projetos não depende de custos, mas evita ciclo na importação

    def f(m):
        m["custo"] = round((m.get("custo") or 0) + custo, 6)
        etapas = m.setdefault("custo_etapas", {})
        chave = motivo or "outros"
        etapas[chave] = round(etapas.get(chave, 0) + custo, 6)
    try:
        projetos.atualizar(projeto_id, f)
    except Exception as e:  # projeto apagado no meio: o custo fica só no total geral
        logging.getLogger("custos").warning("Custo fora do projeto %s: %s", projeto_id, e)


def calcular(modelo: str, tokens_entrada: int, tokens_saida: int) -> float:
    pe, ps = PRECOS.get(modelo, PRECO_PADRAO)
    return (tokens_entrada * pe + tokens_saida * ps) / 1_000_000


def registrar(modelo: str, usage, projeto_id: str | None = None, motivo: str = "") -> float:
    """Soma o custo de uma resposta da API ao acumulado. Retorna o custo da chamada."""
    entrada = getattr(usage, "input_tokens", 0) or 0
    entrada += getattr(usage, "cache_creation_input_tokens", 0) or 0
    entrada += getattr(usage, "cache_read_input_tokens", 0) or 0
    saida = getattr(usage, "output_tokens", 0) or 0
    custo = calcular(modelo, entrada, saida)
    with _trava:
        dados = config.ler_json(config.ARQ_CUSTOS, {"total": 0.0, "chamadas": 0, "historico": []})
        dados["total"] = round(dados["total"] + custo, 6)
        dados["chamadas"] += 1
        dados["historico"].append({
            "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
            "modelo": modelo, "entrada": entrada, "saida": saida,
            "custo": round(custo, 6), "projeto": projeto_id, "motivo": motivo,
        })
        dados["historico"] = dados["historico"][-500:]  # não deixa o arquivo crescer para sempre
        config.gravar_json(config.ARQ_CUSTOS, dados)
    medida = getattr(_local, "medida", None)
    if medida is not None:
        medida["custo"] += custo
    if projeto_id:
        _somar_no_projeto(projeto_id, custo, motivo)
    return custo


def resumo() -> dict:
    return config.ler_json(config.ARQ_CUSTOS, {"total": 0.0, "chamadas": 0, "historico": []})


def zerar() -> None:
    config.gravar_json(config.ARQ_CUSTOS, {"total": 0.0, "chamadas": 0, "historico": []})
