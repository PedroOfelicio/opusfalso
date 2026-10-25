"""
Direção de arte por clipe: o Claude escolhe, numa lista FECHADA, o visual de cada clipe conforme o conteúdo
(legenda, cor, look de cor, transição nos cortes, força do zoom, efeito nos impactos); o código executa.

Sem o Claude (ou sem escolha), vale o padrão do clima do clipe. Tudo pode ser trocado no editor do clipe.
"""
import re

# Look de cor: filtro do FFmpeg aplicado ao vídeo antes da legenda (a legenda não muda de cor)
LOOKS = {
    "natural": ("sem alteração de cor", None),
    "vibrante": ("cores fortes, contraste alto (gameplay, energia)", "eq=saturation=1.35:contrast=1.08"),
    "cinema": ("sombras azuladas, pele alaranjada, vinheta (história, drama)",
               "colorbalance=rs=-0.05:bs=0.07:rh=0.07:bh=-0.05,eq=contrast=1.1:saturation=1.05,vignette=PI/5"),
    "quente": ("tons dourados (conquista, nostalgia, conselho)", "colorbalance=rm=0.07:bm=-0.05,eq=saturation=1.1"),
    "frio": ("tons azulados (tensão, mistério, tecnologia)",
             "colorbalance=rm=-0.04:bm=0.07,eq=saturation=0.95:contrast=1.05"),
    "dramatico": ("contraste duro, menos cor, vinheta (clutch, momento decisivo)",
                  "eq=contrast=1.25:saturation=0.85:brightness=-0.02,vignette=PI/4"),
    "preto_branco": ("preto e branco com contraste (reflexão, impacto emocional)", "hue=s=0,eq=contrast=1.2"),
    "retro": ("cara de filme antigo (memória, humor nostálgico)", "curves=preset=vintage,eq=saturation=0.9"),
}

# Transição nos cortes grandes (mudança de assunto/lance); os cortes secos pequenos ficam só com o pulso de zoom
TRANSICOES = {
    "pulso": ("só o pulso de zoom de sempre (discreto, para fala)", 0.0),
    "flash": ("clarão branco rápido (gameplay, virada)", 0.15),
    "zoom_rapido": ("aproxima de repente e volta (energia, meme)", 0.3),
    "desfoque": ("desfoca e foca de novo (história, passagem de tempo)", 0.25),
    "tremor": ("a tela treme (impacto, susto, raiva)", 0.3),
    "glitch": ("falha digital colorida (tecnologia, caos, humor)", 0.15),
    "risco": ("risco branco cruzando a tela na diagonal (troca de assunto, estilo YouTuber de jogo)", 0.28),
    "blur_zoom": ("aproxima borrando e volta (virada rápida, meme, energia)", 0.3),
}

ZOOMS = {"suave": 0.07, "medio": 0.12, "forte": 0.2}

# Efeito no instante do pico (kill, explosão, grito); só no gameplay, onde o pico é medido no áudio
IMPACTOS = {"nenhum": 0.0, "tremor": 0.35, "flash": 0.15, "glitch": 0.2}

# Padrão por clima (sem o Claude, ou campo que ele não escolheu)
PADRAO_CLIMA = {
    "energetica": {"preset": "gamer", "look": "vibrante", "transicao": "risco", "zoom": "forte", "impacto": "tremor"},
    "tensa": {"preset": "cinema", "look": "dramatico", "transicao": "tremor", "zoom": "medio", "impacto": "flash"},
    "calma": {"preset": "minimalista", "look": "quente", "transicao": "pulso", "zoom": "suave", "impacto": "nenhum"},
    "engracada": {"preset": "roblox", "look": "vibrante", "transicao": "blur_zoom", "zoom": "forte", "impacto": "glitch"},
    "epica": {"preset": "cinema", "look": "cinema", "transicao": "flash", "zoom": "medio", "impacto": "flash"},
}
PADRAO = {"preset": None, "look": "natural", "transicao": "pulso", "zoom": "medio", "impacto": "nenhum"}


def texto_catalogo(presets: list[str]) -> str:
    """Trecho do prompt com as opções (o Claude só pode escolher daqui)."""
    def lista(d):
        return "; ".join(f'"{k}" ({v[0]})' for k, v in d.items())
    return (
        "- direcao: o visual DESTE clipe, escolhido pelo conteúdo e pela emoção do trecho (varie entre os clipes "
        "quando o clima mudar). Objeto com:\n"
        f"  preset (estilo da legenda): um de {presets}; cor: \"#RRGGBB\" da palavra em destaque, ou null;\n"
        f"  look (cor do vídeo): um de {lista(LOOKS)};\n"
        f"  transicao (nas mudanças de lance/assunto): um de {lista(TRANSICOES)};\n"
        '  zoom: "suave" | "medio" | "forte";\n'
        '  impacto (efeito no pico de ação, só gameplay): "nenhum" | "tremor" | "flash" | "glitch".')


def valida(v, presets: list[str]) -> dict:
    """Aceita o que o Claude mandar e devolve só campos válidos (o resto fica com o padrão)."""
    if not isinstance(v, dict):
        return {}
    saida = {}
    for campo, opcoes in (("look", LOOKS), ("transicao", TRANSICOES), ("zoom", ZOOMS), ("impacto", IMPACTOS)):
        x = str(v.get(campo) or "").strip().lower().replace(" ", "_").replace("é", "e").replace("á", "a")
        if x in opcoes:
            saida[campo] = x
    if str(v.get("preset") or "").lower() in presets:
        saida["preset"] = str(v["preset"]).lower()
    cor = str(v.get("cor") or "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", cor):
        saida["cor"] = cor.upper()
    return saida


def efetiva(direcao: dict | None, clima: str | None) -> dict:
    """Direção final de um clipe: o que o Claude escolheu, completado pelo padrão do clima."""
    return {**PADRAO, **PADRAO_CLIMA.get(clima or "", {}), **(direcao or {})}


def filtro_look(look: str | None) -> str | None:
    return LOOKS.get(look or "natural", LOOKS["natural"])[1]


def cortes_grandes(partes: list[tuple[float, float]], com_abertura: bool, pulo_min: float = 1.5,
                   intervalo_min: float = 2.0) -> list[float]:
    """Instantes (no tempo do clipe) das mudanças de lance/assunto: fim da abertura e cortes que pulam 1,5 s
    ou mais do original. Os cortes de silêncio (pulos curtos) não ganham transição, senão cansaria."""
    tempos, t = [], 0.0
    for k, (a, b) in enumerate(partes):
        if k > 0:
            anterior = partes[k - 1]
            grande = (com_abertura and k == 1) or a - anterior[1] >= pulo_min or a < anterior[0]
            if grande and (not tempos or t - tempos[-1] >= intervalo_min):
                tempos.append(round(t, 3))
        t += b - a
    return tempos
