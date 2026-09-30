"""
Estimativa de custo das chamadas ao Claude.

Cada chamada registra tokens de entrada/saída; o total acumulado fica em
DADOS/custos.json e aparece na tela Configurações e no fim do CLI.
Preços em US$ por milhão de tokens (entrada, saída).
"""
import threading
import time

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
    return custo


def resumo() -> dict:
    return config.ler_json(config.ARQ_CUSTOS, {"total": 0.0, "chamadas": 0, "historico": []})


def zerar() -> None:
    config.gravar_json(config.ARQ_CUSTOS, {"total": 0.0, "chamadas": 0, "historico": []})
