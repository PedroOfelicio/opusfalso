"""
Planejador LOCAL de reserva (sem Claude).

Usado automaticamente quando a API não está disponível (sem chave, sem créditos,
sem internet). É bem mais simples que o Claude:
- instrução -> plano por regras (palavras-chave, números, cores)
- escolha de trechos por heurística (frases de gancho, números, ritmo de fala)
"""
import re
import unicodedata

from modelos import CORES_NOMEADAS, AjusteClips, Corte, Emoji, PlanoEdicao, clima_valido

NUMEROS_ESCRITOS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5,
                    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}

# Palavras que costumam indicar gancho/momento forte em fala
GANCHOS = {"erro", "segredo", "nunca", "ninguém", "ninguem", "verdade", "maior", "melhor", "pior", "importante",
           "choque", "dinheiro", "descobri", "aposto", "cuidado", "atenção", "atencao", "problema", "lição", "licao",
           "dobrou", "milhão", "milhoes", "milhões", "ninguem", "sempre", "simples", "mentira", "incrível", "incrivel"}
EMOJI_POR_PALAVRA = {"dinheiro": "💰", "erro": "❌", "segredo": "🤫", "choque": "😱", "dobrou": "📈",
                     "importante": "⚠️", "fogo": "🔥", "amor": "❤️", "ideia": "💡", "tempo": "⏰", "clientes": "👥"}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _limpa(p: str) -> str:
    return re.sub(r"[^\wÀ-ÿ]", "", p.lower())


# ================================================================ instrução -> plano

def _regras():
    """Cada regra: (regex, função que aplica no dict do plano). Uma cláusula
    que não casar com nenhuma regra vai para 'nao_atendido'."""
    cores = "|".join(sorted(CORES_NOMEADAS, key=len, reverse=True))

    def num_clips(m, d):
        n = m.group(1)
        d["num_clips"] = int(n) if n.isdigit() else NUMEROS_ESCRITOS.get(n, 3)

    def faixa(m, d):
        a, b = sorted((float(m.group(1)), float(m.group(2))))
        d["duracao_min"], d["duracao_max"] = a, b

    def ate(m, d):
        d["duracao_max"] = float(m.group(1))
        d["duracao_min"] = min(d["duracao_min"], max(5.0, d["duracao_max"] / 2))

    def cor(m, d):
        d["legenda"]["cor"] = CORES_NOMEADAS[m.group(1)]

    return [
        (r"\b(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez)\s+(?:melhores|clipes?|cortes?|momentos?|clips?|v[ií]deos?|partes?|jogadas?|lances?|kills?)", num_clips),
        (r"(\d+)\s*(?:s|seg\w*)?\s*(?:a|-|até|ate|e)\s*(\d+)\s*(?:s\b|seg)", faixa),
        (r"(?:at[eé]|no m[aá]ximo|m[aá]x\.?)\s*(\d+)\s*(?:s\b|seg)", ate),
        (r"\bcurt[oa]s?\b", lambda m, d: d.update(duracao_min=15, duracao_max=30)),
        (r"\blong[oa]s?\b", lambda m, d: d.update(duracao_min=60, duracao_max=90)),
        (r"vertical|9:16|tiktok|reels?|shorts?", lambda m, d: d.update(formato="9:16")),
        (r"horizontal|16:9|youtube", lambda m, d: d.update(formato="16:9")),
        (r"quadrad|1:1|feed", lambda m, d: d.update(formato="1:1")),
        (r"sem legenda", lambda m, d: d["legenda"].update(ativa=False)),
        (rf"\b({cores})\b", cor),
        (r"animad|din[aâ]mic", lambda m, d: d["legenda"].update(estilo="animada", ativa=True)),
        (r"legenda simples", lambda m, d: d["legenda"].update(estilo="simples", ativa=True)),
        (r"\b(opus|hormozi|minimalista)\b", lambda m, d: d["legenda"].update(preset=m.group(1))),
        # As regras positivas ignoram o "sem X", senão "sem música" ligaria a música
        (r"(?<!sem )legenda", lambda m, d: d["legenda"].update(ativa=True)),
        (r"sem zoom", lambda m, d: d.update(zoom_em_enfase=False)),
        (r"(?<!sem )zoom", lambda m, d: d.update(zoom_em_enfase=True)),
        (r"sil[eê]ncio|pausa|\bhum\b|v[ií]cio", lambda m, d: d.update(remover_silencios=True)),
        (r"sem m[uú]sica", lambda m, d: d.update(musica_fundo=False)),
        (r"(?<!sem )m[uú]sica", lambda m, d: d.update(musica_fundo=True)),
        (r"(?<!sem )m[uú]sica\s+(\w+)", lambda m, d: d.update(musica_clima=clima_valido(m.group(1)) or d["musica_clima"])),
        (r"sem (?:efeitos?|sons|sfx)", lambda m, d: d.update(efeitos_sonoros=False)),
        (r"(?<!sem )(?:efeitos? sonoros?|\bsfx\b|whoosh|\bsons\b)", lambda m, d: d.update(efeitos_sonoros=True)),
        (r"sem barra", lambda m, d: d.update(barra_progresso=False)),
        (r"(?<!sem )barra|progresso", lambda m, d: d.update(barra_progresso=True)),
        (r"sem (?:teaser|abertura|cl[ií]max no in[ií]cio)", lambda m, d: d.update(abertura_climax=False)),
        (r"(?<!sem )(?:teaser|abr(?:ir|e) com o cl[ií]max|cl[ií]max no in[ií]cio)", lambda m, d: d.update(abertura_climax=True)),
        (r"sem (?:limpar|melhorar) (?:a )?(?:voz|[aá]udio)", lambda m, d: d.update(limpar_voz=False)),
        (r"(?<!sem )(?:ru[ií]do|chiado|zumbido|(?:limpar|melhorar) (?:a )?(?:voz|[aá]udio))", lambda m, d: d.update(limpar_voz=True)),
        (r"emoji", lambda m, d: None),  # a legenda animada já põe emoji nas palavras-chave
        (r"normaliz|volume|[aá]udio", lambda m, d: d.update(normalizar_audio=True)),
        (r"sem t[ií]tulo", lambda m, d: d.update(titulo_gancho=False)),
        (r"(?<!sem )(?:t[ií]tulo|gancho)", lambda m, d: d.update(titulo_gancho=True)),
        (r"melhores|momentos|virais?|destaques?", lambda m, d: None),  # genérico, já é o comportamento padrão
    ]


def interpretar_instrucao(instrucao: str, base: PlanoEdicao) -> PlanoEdicao:
    d = base.model_dump()
    d["nao_atendido"] = []
    texto = instrucao.lower().strip()
    if not texto:
        return base
    # Divide em cláusulas por vírgula, ponto e vírgula e " e " (menos em "entre 30 e 60")
    clausulas = [c.strip() for c in re.split(r"[,;\n]|(?<!\d)\s+e\s+(?!\d)", texto) if c.strip()]
    regras = _regras()
    for clausula in clausulas:
        casou = False
        for padrao, aplicar in regras:
            for m in re.finditer(padrao, clausula):
                aplicar(m, d)
                casou = True
        if not casou and len(clausula) > 2:
            d["nao_atendido"].append(clausula)
    if d["musica_fundo"] and not d.get("musica_caminho"):
        d["musica_caminho"] = base.musica_caminho
    return PlanoEdicao.model_validate(d)


# ================================================================ escolha de trechos (falado)

def _pontuar_trecho(palavras: list[dict]) -> tuple[float, list[str]]:
    """Nota heurística de 0-100 e os motivos."""
    if not palavras:
        return 0, []
    texto = " ".join(w["p"] for w in palavras)
    limpas = [_limpa(w["p"]) for w in palavras]
    duracao = max(palavras[-1]["f"] - palavras[0]["i"], 1)
    motivos, pontos = [], 40.0

    abertura = " ".join(limpas[:12])
    if any(g in abertura for g in GANCHOS) or "?" in " ".join(w["p"] for w in palavras[:12]):
        pontos += 15
        motivos.append("abre com gancho")
    ganchos = sum(1 for p in limpas if p in GANCHOS)
    if ganchos:
        pontos += min(ganchos * 4, 16)
        motivos.append("palavras de impacto")
    numeros = len(re.findall(r"\d+|cem|mil|setenta|trinta|cinco vezes|dobrou", texto.lower()))
    if numeros:
        pontos += min(numeros * 4, 12)
        motivos.append("números concretos")
    if "!" in texto or "?" in texto:
        pontos += 5
        motivos.append("tom emocional")
    ritmo = len(palavras) / duracao  # palavras por segundo
    if ritmo > 2.6:
        pontos += 5
        motivos.append("ritmo rápido")
    if _fim_frase(palavras[-1]["p"]):
        pontos += 4
    return min(pontos, 96), motivos


def _fim_frase(p: str) -> bool:
    return p.rstrip().endswith((".", "!", "?", "…"))


def _titulo_de(palavras: list[dict]) -> str:
    """Primeira(s) frase(s) do trecho com pelo menos 4 palavras, no máximo 8."""
    frase = []
    for w in palavras:
        frase.append(w["p"])
        if (_fim_frase(w["p"]) and len(frase) >= 4) or len(frase) >= 8:
            break
    titulo = " ".join(frase).strip(" .,;:")
    return titulo[:1].upper() + titulo[1:]


def _enfase_de(palavras: list[dict]) -> list[str]:
    candidatas = []
    for w in palavras:
        limpa = _limpa(w["p"])
        if limpa in GANCHOS or re.fullmatch(r"\d+", limpa) or limpa in ("setenta", "cem", "trinta", "dobrou"):
            if w["p"].strip(".,!?") not in candidatas:
                candidatas.append(w["p"].strip(".,!?"))
    return candidatas[:5]


def escolher_cortes_falado(transcricao: dict, plano: PlanoEdicao, excluir=None, quantidade=None) -> list[Corte]:
    quantidade = quantidade or plano.num_clips
    palavras = transcricao["palavras"]
    duracao_video = transcricao["duracao"]
    dmin, dmax = min(plano.duracao_min, duracao_video), min(plano.duracao_max, duracao_video)
    ocupados = list(excluir or [])

    # Candidatos: começam no início de cada frase e terminam no fim de frase que caiba na duração
    inicios = [0] + [i + 1 for i, w in enumerate(palavras[:-1]) if _fim_frase(w["p"])]
    candidatos = []
    for ini in inicios:
        t0 = palavras[ini]["i"]
        melhor_fim = None
        for j in range(ini, len(palavras)):
            dur = palavras[j]["f"] - t0
            if dur > dmax:
                break
            if dur >= dmin * 0.9 and _fim_frase(palavras[j]["p"]):
                melhor_fim = j  # fica com o fim de frase mais longo dentro do limite
        if melhor_fim is None:
            continue
        trecho = palavras[ini:melhor_fim + 1]
        nota, motivos = _pontuar_trecho(trecho)
        candidatos.append((nota, ini, melhor_fim, motivos))

    candidatos.sort(key=lambda c: c[0], reverse=True)
    cortes = []
    for nota, ini, fim, motivos in candidatos:
        a, b = max(0, palavras[ini]["i"] - 0.1), min(duracao_video, palavras[fim]["f"] + 0.25)
        if any(min(b, y) - max(a, x) > 0.3 * min(b - a, y - x) for x, y in ocupados):
            continue
        trecho = palavras[ini:fim + 1]
        enfase = _enfase_de(trecho)
        emojis = [Emoji(palavra=p, emoji=EMOJI_POR_PALAVRA[_limpa(p)]) for p in enfase if _limpa(p) in EMOJI_POR_PALAVRA]
        cortes.append(Corte(
            inicio=round(a, 2), fim=round(b, 2), titulo=_titulo_de(trecho), nota=int(nota),
            justificativa=("Seleção local: " + ", ".join(motivos)) if motivos else "Seleção local por duração",
            palavras_enfase=enfase, emojis=emojis[:3],
        ))
        ocupados.append((a, b))
        if len(cortes) >= quantidade:
            break
    return cortes


# ================================================================ textos de impacto (sem IA)

# (palavras sem acento que disparam, texto na tela, estilo da figurinha). Expressões de 2 palavras valem
# juntas ("meu deus"). Português e inglês: muito gameplay é narrado com termos do jogo em inglês.
IMPACTOS_POR_PALAVRA = [
    (("corre", "corram", "correr", "foge", "run"), "CORRE!!", "etiqueta"),
    (("socorro", "help"), "SOCORRO!", "etiqueta"),
    (("preso", "presa", "presos", "travado", "trapped", "stuck"), "PRESO!", "impacto"),
    (("morri", "morreu", "morto", "mataram", "died", "dead"), "MORREU!", "impacto"),
    (("meu deus", "mds", "omg", "nossa senhora"), "MEU DEUS!", "impacto"),
    (("nao acredito", "impossivel"), "QUE?!", "impacto"),
    (("ganhei", "venci", "vencemos", "ganhamos", "vitoria", "won"), "VITÓRIA!", "dinheiro"),
    (("robux", "dinheiro", "grana", "rico", "rica", "milionario", "money"), "$$$", "dinheiro"),
    (("banido", "banida", "ban", "banned", "expulso"), "BANIDO", "carimbo"),
    (("hacker", "hackeado", "hackearam", "hack"), "HACKER", "carimbo"),
    (("exposto", "exposed", "golpe", "golpista", "scam", "scammer", "fake"), "EXPOSED", "carimbo"),
    (("espera", "pera", "wait"), "ESPERA...", None),
    (("kkkk", "kkkkk", "kkkkkk", "hahaha", "hahahaha", "rsrs"), "KKKKK", None),
]


def reacoes_por_palavras(palavras: list[dict], inicio: float, fim: float, pico: float | None = None,
                         maximo: int = 2, espaco: float = 3.0) -> list[dict]:
    """Textos de impacto do trecho [inicio, fim] por palavra-chave (custo zero). Sem nenhuma e com pico de
    ação (gameplay), põe um "QUE ISSO?!" no pico. Cada texto aparece uma vez; espaçados de `espaco` s."""
    trecho = [w for w in palavras if inicio <= w["i"] <= fim]
    limpas = [_sem_acento(_limpa(w["p"])) for w in trecho]
    achados = []
    for k, (w, p) in enumerate(zip(trecho, limpas)):
        dupla = f"{p} {limpas[k + 1]}" if k + 1 < len(limpas) else ""
        for gatilhos, texto, estilo in IMPACTOS_POR_PALAVRA:
            if (p in gatilhos or dupla in gatilhos) and all(texto != a["texto"] for a in achados):
                if all(abs(w["i"] - a["t"]) >= espaco for a in achados):
                    achados.append({"t": round(w["i"], 2), "texto": texto, "estilo": estilo})
                break
        if len(achados) >= maximo:
            break
    if not achados and pico is not None and inicio <= pico <= fim:
        achados.append({"t": round(pico, 2), "texto": "QUE ISSO?!", "estilo": "impacto"})
    return achados


# ================================================================ ajustes

def interpretar_ajuste(pedido: str, clipes: list[dict]) -> AjusteClips:
    texto = pedido.lower()
    d: dict = {"nao_atendido": []}
    duracoes = [c["fim"] - c["inicio"] for c in clipes] or [30]
    media = sum(duracoes) / len(duracoes)
    if re.search(r"curt|menor|reduz", texto):
        d["duracao_alvo"] = max(5, round(media * 0.7))
    elif re.search(r"long|maior|aument", texto):
        d["duracao_alvo"] = min(180, round(media * 1.3))
    m = re.search(r"(\d+)\s*s(?:eg)?", texto)
    if m:
        d["duracao_alvo"] = float(m.group(1))
    for nome, hexa in CORES_NOMEADAS.items():
        if re.search(rf"\b{nome}\b", texto):
            d["cor_legenda"] = hexa
    for p in ("opus", "hormozi", "minimalista"):
        if p in texto:
            d["preset"] = p
    if "animad" in texto:
        d["estilo_legenda"] = "animada"
    if "sem legenda" in texto:
        d["legenda_ativa"] = False
    if "sem título" in texto or "sem titulo" in texto:
        d["titulo_ativo"] = False
    if re.search(r"sem (?:efeitos?|sons|sfx)", texto):
        d["efeitos_sonoros"] = False
    elif re.search(r"efeitos? sonoros?|\bsfx\b|whoosh", texto):
        d["efeitos_sonoros"] = True
    if "sem zoom" in texto:
        d["zoom_em_enfase"] = False
    elif "zoom" in texto:
        d["zoom_em_enfase"] = True
    if re.search(r"sil[eê]ncio|pausa", texto):
        d["remover_silencios"] = True
    for fmt, padrao in (("9:16", r"vertical|9:16"), ("16:9", r"horizontal|16:9"), ("1:1", r"quadrad|1:1")):
        if re.search(padrao, texto):
            d["formato"] = fmt
    if len(d) == 1:
        d["nao_atendido"].append(pedido)
    return AjusteClips.model_validate(d)
