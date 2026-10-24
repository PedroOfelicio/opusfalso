"""
Legenda traduzida dos clipes (ex.: vídeo em português, legenda em inglês para alcançar fora do Brasil).

As palavras do clipe são agrupadas em frases (pausa, pontuação ou ~10 palavras); o Claude traduz todas as frases
do clipe e o título numa chamada só (resposta guardada no projeto, então reexportar não paga de novo). Cada frase
traduzida ocupa o mesmo tempo da original, com as palavras distribuídas pelo tamanho; as palavras de ênfase vêm
marcadas com *asteriscos* pelo Claude e continuam em destaque.
"""
import re

from pydantic import BaseModel, Field, field_validator

import planejador_llm as llm

IDIOMAS = {"en": "inglês", "es": "espanhol", "pt": "português", "fr": "francês", "it": "italiano", "de": "alemão"}

SISTEMA = """Você traduz legendas de vídeos curtos (TikTok/Reels/Shorts) mantendo o tom falado, curto e natural
(gírias viram gírias equivalentes, não tradução literal). Responda APENAS com JSON:
{"frases": ["...", "..."], "titulo": "..."}
- frases: a MESMA quantidade e a mesma ordem das frases recebidas, cada uma traduzida por inteiro.
- Palavras marcadas com *asteriscos* na original são ênfase: marque a palavra equivalente na tradução com *asteriscos*.
- titulo: o título traduzido, curto e chamativo (máx. 8 palavras). Vazio se não houver título."""


class Traducao(BaseModel):
    frases: list[str] = Field(default_factory=list)
    titulo: str = ""

    @field_validator("frases", mode="before")
    @classmethod
    def _frases(cls, v):
        return [str(x) for x in v] if isinstance(v, list) else []


def frases(palavras: list[dict], pausa: float = 0.6, maximo: int = 10) -> list[list[dict]]:
    """Agrupa as palavras do clipe em frases de legenda."""
    grupos, atual = [], []
    for w in palavras:
        if atual and (w["i"] - atual[-1]["f"] > pausa or len(atual) >= maximo):
            grupos.append(atual)
            atual = []
        atual.append(w)
        if re.search(r"[.!?…]$", w["p"]):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def redistribuir(grupo: list[dict], texto: str) -> list[dict]:
    """Palavras traduzidas no tempo da frase original, cada uma com tempo proporcional ao tamanho."""
    novas = texto.split()
    if not novas:
        return []
    inicio, fim = grupo[0]["i"], grupo[-1]["f"]
    pesos = [len(p.strip("*")) + 2 for p in novas]
    total, acumulado, saida = sum(pesos), 0, []
    for p, peso in zip(novas, pesos):
        a = inicio + (fim - inicio) * acumulado / total
        acumulado += peso
        b = inicio + (fim - inicio) * acumulado / total
        enfase = p.startswith("*") and p.rstrip(".,!?").endswith("*")
        saida.append({"p": p.replace("*", ""), "i": round(a, 3), "f": round(max(b, a + 0.05), 3),
                      "enfase": enfase, "emoji": None})
    return saida


def traduzir_clipe(pid: str, palavras: list[dict], titulo: str | None, idioma: str) -> tuple[list[dict], str | None]:
    """(palavras traduzidas no tempo do clipe, título traduzido). Sem fala: só o título."""
    grupos = frases(palavras)
    originais = [" ".join(f"*{w['p']}*" if w.get("enfase") else w["p"] for w in g) for g in grupos]
    pedido = (f"Traduza para {IDIOMAS.get(idioma, idioma)}.\nTÍTULO: {titulo or ''}\nFRASES:\n"
              + "\n".join(f"{k + 1}. {f}" for k, f in enumerate(originais)))
    try:
        r = llm._chamar_json(SISTEMA, pedido, Traducao, pid, "tradução da legenda", max_tokens=3000, rapido=True)
    except llm.ErroClaude:
        return palavras, titulo  # sem o Claude, fica a legenda original
    if len(r.frases) != len(grupos):
        return palavras, titulo  # resposta desalinhada: melhor a original do que legenda fora de tempo
    traduzidas = [w for g, t in zip(grupos, r.frases) for w in redistribuir(g, t)]
    return traduzidas, (r.titulo.strip() or titulo) if titulo else titulo
