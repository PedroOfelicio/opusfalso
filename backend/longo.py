"""
Vídeos longos para o YouTube (aba "Vídeos longos").

Dois modos:
- "enxugar": o vídeo inteiro, mais enxuto. Fala: sem silêncios, vícios e erros de gravação (o Claude lê a
  transcrição inteira e marca takes repetidos, começos em falso e desvios). Gameplay: sem menus, loading,
  fase de compra e tempo parado (o Claude rotula 1 quadro a cada 3 s).
- "melhores": compilação dos melhores momentos com duração-alvo (ex.: 10 min de uma live de 2 h).

Nos dois: abertura com o melhor momento (teaser), punch-in nos cortes secos (com moderação), voz limpa,
capítulos (no MP4 e na descrição), legenda .srt corrigida, 3 títulos, descrição, tags e thumbnails com texto.

Fluxo: as decisões ficam salvas no projeto ("edicao": o que saiu e por quê, capítulos, momentos, ritmo,
abertura, correções). O vídeo é montado a partir delas; na revisão o usuário devolve trechos, muda o ritmo
ou renomeia capítulos e `remontar` refaz só os blocos que mudaram (os outros vêm do cache).

Render: FFmpeg em blocos (editor_ffmpeg.renderizar_bloco + juntar_blocos), 16:9 até 1080p, sem reenquadrar.
"""
import bisect
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import analise_audio
import biblioteca_audio as biblioteca
import config
import custos
import editor_ffmpeg as ef
import legendas
import pipeline
import planejador_llm as llm
import planejador_local as local
import projetos
import transcricao as tr
import youtube
from config import Cancelado
from modelos import CLIMAS, Corte, MomentoLongo, PlanoEdicao

log = logging.getLogger("longo")

ETAPAS = [
    ("transcrevendo", "Transcrevendo"),
    ("analisando", "Analisando"),
    ("decidindo", "Decidindo a edição"),
    ("montando", "Montando o vídeo"),
    ("finalizando", "Finalizando"),
]
PESOS = {"transcrevendo": 0.28, "analisando": 0.06, "decidindo": 0.16, "montando": 0.45, "finalizando": 0.05}
PESOS_REMONTAR = {"transcrevendo": 0.0, "analisando": 0.0, "decidindo": 0.0, "montando": 0.88, "finalizando": 0.12}

# Ritmo da fala: pausa máxima que fica entre frases e o respiro deixado em volta de cada trecho
RITMOS = {"natural": (0.9, 0.2), "dinamico": (0.6, 0.12), "rapido": (0.35, 0.06)}

PADROES = {
    "modo_longo": "enxugar",   # enxugar | melhores
    "alvo_min": 10,            # duração da compilação (modo melhores)
    "ritmo": "dinamico",       # natural | dinamico | rapido (fala)
    "legenda": False,          # legenda queimada no vídeo (o .srt sai sempre)
    "preset": "minimalista",
    "cor": None,
    "zoom": True,              # punch-in alternado nos cortes secos
    "abertura": True,          # teaser com o melhor momento no começo
    "limpar_voz": None,        # None = ligado na fala, desligado no gameplay (não mexe no som do jogo)
    "musica": "",              # "" | "auto" | clima | caminho
    "efeitos": False,          # whoosh nas transições
    "ver_imagens": True,       # gameplay: o Claude olha os quadros (menus, fase de compra, tempo parado)
    "cortar_parado": True,     # gameplay: tira andanças longas sem nada acontecendo
    "remover_erros": True,     # fala: aplica os cortes de erros de gravação (senão ficam só como sugestão)
}


def _opcoes(meta: dict) -> dict:
    opc = {**PADROES, **(meta.get("opcoes") or {})}
    if opc["limpar_voz"] is None:
        opc["limpar_voz"] = meta["modo"] == "falado"
    if opc["ritmo"] not in RITMOS:
        opc["ritmo"] = "dinamico"
    return opc


# ================================================================ processamento

def processar(pid: str, cancelado=None) -> dict:
    meta = projetos.ler(pid)
    opc = _opcoes(meta)
    prog = pipeline.Progresso(pid, etapas=ETAPAS, pesos=PESOS)
    video = meta["video"]

    projetos.atualizar(pid, lambda m: m.update(status="processando", iniciado_em=time.time(), erro=None,
                                               progresso=0.0, etapas={}, avisos=[], nao_atendido=[], longo=None,
                                               edicao=None))  # "Tentar de novo" só remonta se a edição for desta rodada
    pipeline.aviso_disco(pid)
    baixou = pipeline.baixar_se_link(pid, meta, prog, cancelado)
    info = ef.sondar(video)
    if not (projetos.pasta(pid) / "thumb.jpg").exists():
        ef.extrair_frame(video, info["duracao"] * 0.1, projetos.pasta(pid) / "thumb.jpg", largura=640)
    projetos.atualizar(pid, lambda m: m.update(
        duracao_video=info["duracao"], resolucao=f"{info['largura']}x{info['altura']}",
        saida_dir=m.get("saida_dir") or str(projetos.pasta_saida_para(m["nome"], pid))))
    meta = projetos.ler(pid)

    if not baixou:
        prog.etapa("transcrevendo")
    transcricao = tr.transcrever(video, pipeline.progresso_apos_download(prog, baixou), cancelado)

    prog.etapa("analisando")
    analise = None
    if meta["modo"] == "gameplay":
        analise = analise_audio.analisar(video, lambda p, d="": prog(p, d), cancelado)
    prog(1.0, "Análise pronta")

    prog.etapa("decidindo")
    if meta["modo"] == "gameplay":
        edl = _decidir_gameplay(pid, meta, opc, transcricao, analise, prog, cancelado)
    else:
        edl = _decidir_falado(pid, meta, opc, transcricao, prog)
    projetos.atualizar(pid, lambda m: m.update(edicao=edl, nao_atendido=edl["nao_atendido"]))
    return _montar_e_finalizar(pid, opc, edl, transcricao, info, prog, cancelado)


def remontar(pid: str, cancelado=None) -> dict:
    """Depois da revisão: monta de novo com a edição salva, sem chamar o Claude.
    Blocos que não mudaram vêm do cache, então costuma levar segundos."""
    meta = projetos.ler(pid)
    opc = _opcoes(meta)
    prog = pipeline.Progresso(pid, etapas=ETAPAS, pesos=PESOS_REMONTAR)
    projetos.atualizar(pid, lambda m: m.update(status="processando", iniciado_em=time.time(), erro=None,
                                               progresso=0.0, etapas={}))
    for etapa in ("transcrevendo", "analisando", "decidindo"):  # já feitas: só marca como concluídas
        prog.etapa(etapa)
    youtube.garantir_video(pid, None, cancelado)  # vídeo de link já apagado: baixa de novo
    info = ef.sondar(meta["video"])
    transcricao = tr.transcrever(meta["video"])  # cache
    return _montar_e_finalizar(pid, opc, meta["edicao"], transcricao, info, prog, cancelado)


def _montar_e_finalizar(pid, opc, edl, transcricao, info, prog, cancelado) -> dict:
    meta = projetos.ler(pid)
    prog.etapa("montando")
    res = _montar(pid, meta, opc, edl, transcricao, info, prog, cancelado)
    alvo = float(opc["alvo_min"]) * 60
    if opc["modo_longo"] == "melhores" and res["duracao"] < 0.7 * alvo:
        pipeline._aviso(pid, f"O vídeo só tinha {res['duracao'] / 60:.1f} min de momentos fortes (pedido: "
                             f"{alvo / 60:.0f} min). Para uma compilação maior, use uma gravação mais longa.")
    prog.etapa("finalizando")
    longo = _finalizar(pid, meta, edl, res, prog)
    prog.finalizar()
    custo = sum(h["custo"] for h in custos.resumo()["historico"] if h.get("projeto") == pid)
    return projetos.atualizar(pid, lambda m: m.update(status="pronto", longo=longo, custo=round(custo, 5),
                                                     terminado_em=time.time()))


def aplicar_revisao(pid: str, dados: dict) -> dict:
    """Aplica as escolhas da revisão na edição salva: trechos que voltam, ritmo, abertura, capítulos e momentos."""
    def f(m):
        edl = m["edicao"]
        if dados.get("ritmo") in RITMOS:
            edl["ritmo"] = dados["ritmo"]
        if dados.get("abertura_ativa") is not None:
            edl["abertura_ativa"] = bool(dados["abertura_ativa"])
        manter = {int(r["id"]): bool(r.get("manter")) for r in dados.get("remocoes") or [] if "id" in r}
        for r in edl["remocoes"]:
            if r["id"] in manter:
                r["manter"] = manter[r["id"]]
        for chave in ("capitulos", "momentos"):
            novos = {int(x["id"]): x for x in dados.get(chave) or [] if "id" in x}
            for item in edl[chave]:
                if item["id"] in novos:
                    n = novos[item["id"]]
                    if (n.get("titulo") or "").strip():
                        item["titulo"] = n["titulo"].strip()[:80]
                    campo = "ativo" if chave == "capitulos" else "manter"
                    if campo in n:
                        item[campo] = bool(n[campo])
    return projetos.atualizar(pid, f)


# ================================================================ decisões: fala

def _decidir_falado(pid, meta, opc, transcricao, prog) -> dict:
    palavras = transcricao["palavras"]
    duracao = transcricao["duracao"]
    if not palavras:
        raise ValueError("Nenhuma fala encontrada no vídeo. Para gameplay sem voz, use o tipo Gameplay.")
    modo = opc["modo_longo"]
    prog(0.05, "O Claude está lendo a transcrição inteira")
    ed = None
    try:
        ed = llm.decidir_longo(transcricao, modo, meta.get("instrucao") or "", float(opc["alvo_min"]), pid)
    except llm.ErroClaude as e:
        pipeline._claude_falhou(pid, e)
    prog(0.8, "Decisões de edição prontas")

    remocoes = []
    for r in (ed.remover if ed else []):
        enc = _encaixar(r.inicio, r.fim, palavras)
        if enc:
            remocoes.append({"id": len(remocoes) + 1, "inicio": enc[0], "fim": enc[1],
                             "motivo": r.motivo or "erro de gravação", "texto": _texto_trecho(palavras, *enc),
                             "manter": not opc["remover_erros"], "origem": "claude"})
    momentos, capitulos = [], []
    if modo == "melhores":
        fontes = ed.momentos if ed and ed.momentos else _momentos_locais(transcricao, float(opc["alvo_min"]))
        for m in sorted(fontes, key=lambda m: m.inicio):
            a, b = _encaixar(m.inicio, m.fim, palavras) or (m.inicio, m.fim)
            momentos.append({"id": len(momentos) + 1, "inicio": a, "fim": b, "manter": True, "remover": [],
                             "titulo": (m.titulo or "").strip() or f"Momento {len(momentos) + 1}"})
    else:
        if ed and ed.capitulos:
            fontes = [(c.inicio, c.titulo) for c in sorted(ed.capitulos, key=lambda c: c.inicio)]
        else:
            fontes = _capitulos_por_tempo(ef.intervalos_de_fala(palavras, 0.0, duracao))
        capitulos = [{"id": k + 1, "t_origem": t, "titulo": titulo, "ativo": True} for k, (t, titulo) in enumerate(fontes)]

    abertura = None
    if ed and ed.abertura:
        enc = _encaixar(*ed.abertura, palavras)
        if enc and 5 <= enc[1] - enc[0] <= 30:
            abertura = list(enc)
    return {
        "tipo": "falado", "modo_longo": modo, "ritmo": opc["ritmo"], "remocoes": remocoes, "momentos": momentos,
        "capitulos": capitulos, "abertura": abertura, "abertura_ativa": bool(opc["abertura"]),
        "correcoes": [c.model_dump() for c in ed.correcoes] if ed else [],
        "titulos": ed.titulos if ed else [], "descricao": ed.descricao if ed else "",
        "tags": ed.tags if ed else [], "texto_thumb": ed.texto_thumb if ed else "",
        "nao_atendido": ed.nao_atendido if ed else [], "zoom_fator": 1.15,
    }


def _encaixar(a: float, b: float, palavras: list[dict]) -> tuple[float, float] | None:
    """Ajusta [a, b] às bordas das palavras: não corta palavra no meio."""
    inicios = [w["i"] for w in palavras]
    k = bisect.bisect_left(inicios, a - 0.15)
    dentro = []
    while k < len(palavras) and palavras[k]["i"] < b:
        if palavras[k]["f"] <= b + 0.15:
            dentro.append(palavras[k])
        k += 1
    if not dentro:
        return None
    return round(max(0.0, dentro[0]["i"] - 0.05), 3), round(dentro[-1]["f"] + 0.08, 3)


def _texto_trecho(palavras: list[dict], a: float, b: float, limite: int = 220) -> str:
    texto = " ".join(w["p"] for w in palavras if w["i"] >= a - 0.05 and w["f"] <= b + 0.1).strip()
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "…"


def _corrigir_todas(palavras: list[dict], correcoes: list[dict] | None) -> list[dict]:
    """Aplica as correções da transcrição em TODAS as ocorrências (uma passada, da esquerda para a direita)."""
    if not correcoes:
        return palavras
    alvos = []
    for c in correcoes:
        seq = [pipeline._norm(x) for x in c["de"].split() if pipeline._norm(x)]
        if seq and c.get("para", "").strip() and seq != [pipeline._norm(x) for x in c["para"].split()]:
            alvos.append((seq, c["para"].split()))
    if not alvos:
        return palavras
    saida, k = [], 0
    norm = [pipeline._norm(w["p"]) for w in palavras]
    while k < len(palavras):
        for seq, novas in alvos:
            n = len(seq)
            if norm[k:k + n] == seq:
                bloco = palavras[k:k + n]
                passo = (bloco[-1]["f"] - bloco[0]["i"]) / len(novas)
                saida += [{**bloco[0], "p": p, "i": round(bloco[0]["i"] + j * passo, 3),
                           "f": round(bloco[0]["i"] + (j + 1) * passo, 3)} for j, p in enumerate(novas)]
                k += n
                break
        else:
            saida.append(palavras[k])
            k += 1
    return saida


def _momentos_locais(transcricao: dict, alvo_min: float) -> list[MomentoLongo]:
    """Sem Claude: os trechos que o planejador local acha mais fortes (1-3 min cada)."""
    plano = PlanoEdicao(num_clips=min(20, max(3, round(alvo_min * 60 / 100))), duracao_min=60, duracao_max=180)
    cortes = local.escolher_cortes_falado(transcricao, plano)
    return [MomentoLongo(inicio=c.inicio, fim=c.fim, titulo=c.titulo) for c in cortes]


def _capitulos_por_tempo(corpo: list[tuple[float, float]], a_cada: float = 300.0) -> list[tuple[float, str]]:
    """Sem Claude: um capítulo a cada ~5 min, no começo de um trecho mantido."""
    capitulos, proximo = [], 0.0
    for a, _ in corpo:
        if a >= proximo:
            capitulos.append((a, f"Parte {len(capitulos) + 1}"))
            proximo = a + a_cada
    return capitulos


# ================================================================ decisões: gameplay

MOTIVO_MENU = "menu, loading ou fase de compra"
MOTIVO_PARADO = "tempo parado"


def _decidir_gameplay(pid, meta, opc, transcricao, analise, prog, cancelado) -> dict:
    video = meta["video"]
    duracao = analise["duracao"]
    palavras = transcricao["palavras"]
    modo = opc["modo_longo"]
    remocoes, momentos, capitulos, destaque, amostras = [], [], [], None, []
    if modo == "enxugar":
        amostras = _rotular_inteiro(video, duracao, pid, prog, cancelado) if opc["ver_imagens"] else []
        if amostras:
            brutas, origem = _remocoes_por_rotulos(amostras, opc["cortar_parado"]), "imagens"
        else:
            mortos = (analise_audio.trechos_mortos(analise, palavras, 0.0, duracao, minimo=8.0, margem=1.0)
                      if opc["cortar_parado"] else [])
            brutas, origem = [(a, b, "tempo parado (pelo áudio)") for a, b in mortos], "audio"
        corpo = pipeline._subtrair([(0.0, duracao)], [(a, b) for a, b, _ in brutas])
        if corpo:  # tela preta no começo/fim (morte, loading, fim da gravação)
            limpo = pipeline._aparar_escuro(video, Corte(inicio=corpo[0][0], fim=corpo[-1][1]))
            if limpo.inicio > corpo[0][0] + 0.2:
                brutas.append((corpo[0][0], limpo.inicio, "tela preta"))
            if limpo.fim < corpo[-1][1] - 0.2:
                brutas.append((limpo.fim, corpo[-1][1], "tela preta"))
        brutas.sort()
        remocoes = [{"id": k + 1, "inicio": round(a, 2), "fim": round(b, 2), "motivo": motivo, "texto": "",
                     "manter": False, "origem": origem} for k, (a, b, motivo) in enumerate(brutas)]
        corpo = pipeline._subtrair([(0.0, duracao)], [(a, b) for a, b, _ in brutas])
        capitulos = [{"id": k + 1, "t_origem": t, "titulo": f"Parte {k + 1}", "ativo": True}
                     for k, t in enumerate(_partidas(corpo))]
        destaque = _momento_mais_forte(analise, corpo, amostras)
    else:
        n = min(20, max(3, round(float(opc["alvo_min"]) * 60 / 32)))
        plano = PlanoEdicao(num_clips=n, duracao_min=20, duracao_max=45)
        prog(0.05, f"Escolhendo {n} momentos")
        cortes = pipeline._cortes_gameplay(video, transcricao, analise, plano, pid, quantidade=n,
                                           ver_imagens=opc["ver_imagens"], cancelado=cancelado,
                                           max_candidatos=min(40, n * 2 + 6))
        for c in sorted(cortes, key=lambda c: c.inicio):
            momentos.append({"id": len(momentos) + 1, "inicio": c.inicio, "fim": c.fim, "titulo": c.titulo,
                             "manter": True, "remover": [list(x) for x in c.remover]})
        if cortes:
            destaque = max(cortes, key=lambda c: c.nota).pico
    prog(0.85, "Dando nome aos capítulos")

    edl = {"tipo": "gameplay", "modo_longo": modo, "ritmo": None, "remocoes": remocoes, "momentos": momentos,
           "capitulos": capitulos, "abertura": None, "abertura_ativa": bool(opc["abertura"]), "correcoes": [],
           "titulos": [], "descricao": "", "tags": [], "texto_thumb": "", "nao_atendido": [], "zoom_fator": 1.1}
    itens = capitulos if modo == "enxugar" else momentos
    try:
        r = llm.titulos_gameplay_longo(_capitulos_com_fala(itens, modo, transcricao), projeto_id=pid)
        if len(r.capitulos) == len(itens):
            for item, titulo in zip(itens, r.capitulos):
                if titulo:
                    item["titulo"] = titulo[:80]
        edl.update(titulos=r.titulos, descricao=r.descricao, tags=r.tags, texto_thumb=r.texto_thumb)
    except llm.ErroClaude as e:
        pipeline._claude_falhou(pid, e)
    if len(palavras) >= 40:  # narração: corrige o que o som do jogo atrapalhou (para a legenda .srt)
        prog(0.93, "Corrigindo a transcrição da narração")
        try:
            edl["correcoes"] = [c.model_dump() for c in llm.corrigir_transcricao(transcricao, pid).correcoes]
        except llm.ErroClaude as e:
            log.warning("Correções da transcrição indisponíveis: %s", e)

    if destaque is not None:
        intervalos = (pipeline._subtrair([(0.0, duracao)], [(r["inicio"], r["fim"]) for r in remocoes])
                      if modo == "enxugar" else [(m["inicio"], m["fim"]) for m in momentos])
        for a, b in intervalos:
            if a <= destaque <= b:
                ini, fim = max(a, destaque - 4.0), min(b, destaque + 2.0)
                if fim - ini >= 3:
                    edl["abertura"] = [round(ini, 2), round(fim, 2)]
                break
    return edl


def _rotular_inteiro(video, duracao: float, pid: str, prog, cancelado, espaco: float = 3.0,
                     janela: float = 96.0) -> list[tuple[float, float, str]]:
    """Rotula o vídeo inteiro (1 quadro a cada 3 s, folhas de 32 quadros), 3 folhas em paralelo.
    Se o Claude não responder na primeira folha, desiste logo (cai no corte pelo áudio)."""
    pedacos = []
    a = 0.0
    while a < duracao - 2:
        pedacos.append((a, min(duracao, a + janela)))
        a += janela
    if not pedacos:
        return []
    prog(0.02, f"Olhando as imagens: 1 de {len(pedacos)} trechos")
    try:
        amostras = pipeline._rotular(video, *pedacos[0], pid, espaco)
    except llm.ErroClaude as e:
        pipeline._aviso(pid, f"Sem análise de imagens ({str(e).rstrip('.')}): o tempo morto foi cortado só pelo áudio.")
        return []
    feitos = 1
    with ThreadPoolExecutor(max_workers=3) as ex:
        futuros = [ex.submit(pipeline._rotular, video, x, y, pid, espaco) for x, y in pedacos[1:]]
        for f in as_completed(futuros):
            if cancelado is not None and cancelado.is_set():
                ex.shutdown(cancel_futures=True)
                raise Cancelado()
            try:
                amostras += f.result()
            except llm.ErroClaude as e:
                log.warning("Folha sem rótulo: %s", e)
            feitos += 1
            prog(0.02 + 0.78 * feitos / len(pedacos), f"Olhando as imagens: {feitos} de {len(pedacos)} trechos")
    return sorted(amostras)


def _remocoes_por_rotulos(amostras, cortar_parado: bool = True, parado_max: int = 5) -> list[tuple]:
    """O que sai do vídeo inteiro, com o motivo: menu com 2+ quadros seguidos (~6 s: fase de compra, loading,
    placar) e, se pedido, jogador parado/andando à toa por 5+ quadros (~15 s), guardando 1 quadro de cada ponta."""
    n = len(amostras)
    rot = [r for _, _, r in amostras]
    fora = [None] * n
    k = 0
    while k < n:
        j = k
        while j < n and rot[j] == rot[k]:
            j += 1
        if rot[k] == "menu" and j - k >= 2:
            fora[k:j] = [MOTIVO_MENU] * (j - k)
        elif rot[k] == "morto" and cortar_parado and j - k >= parado_max:
            fora[k + 1:j - 1] = [MOTIVO_PARADO] * (j - k - 2)
        k = j
    for _ in range(2):  # menu isolado grudado num corte vai junto
        for k in range(n):
            if rot[k] == "menu" and fora[k] is None and ((k > 0 and fora[k - 1]) or (k + 1 < n and fora[k + 1])):
                fora[k] = MOTIVO_MENU
    saida = []
    for (t, p, _), motivo in zip(amostras, fora):
        if not motivo:
            continue
        a, b = t - p / 2, t + p / 2
        if saida and saida[-1][2] == motivo and a - saida[-1][1] < 0.05:
            saida[-1] = (saida[-1][0], b, motivo)
        else:
            saida.append((a, b, motivo))
    return [(round(a, 3), round(b, 3), m) for a, b, m in saida]


def _partidas(corpo: list[tuple[float, float]], pausa: float = 30.0, maximo: int = 15) -> list[float]:
    """Capítulos do gameplay: começam depois de cada pausa longa removida (lobby/loading entre partidas).
    Muitas pausas: ficam as maiores. Poucas: divide o que ficou em partes de ~5 min (até 8)."""
    if not corpo:
        return []
    saltos = sorted(((corpo[k][0] - corpo[k - 1][1], corpo[k][0]) for k in range(1, len(corpo))
                     if corpo[k][0] - corpo[k - 1][1] >= pausa), reverse=True)[:maximo - 1]
    inicios = sorted([corpo[0][0]] + [t for _, t in saltos])
    if len(inicios) >= 3:
        return inicios
    total = ef.duracao_trechos(corpo)
    partes = min(8, int(total // 300))
    alvos = [total * k / partes for k in range(1, partes)] if partes >= 2 else []
    acum = 0.0
    for a, b in corpo:
        while alvos and acum + (b - a) >= alvos[0]:
            t = a + (alvos.pop(0) - acum)
            if all(abs(t - x) > 60 for x in inicios):
                inicios.append(round(t, 2))
        acum += b - a
    return sorted(inicios)


def _momento_mais_forte(analise: dict, corpo, amostras) -> float | None:
    """Segundo de mais energia no áudio dentro do que ficou (de preferência num quadro de ação)."""
    curva = analise.get("curva") or []
    acao = [(t - p / 2, t + p / 2) for t, p, r in amostras if r == "acao"]
    melhor, valor = None, -1.0
    for a, b in acao or corpo:
        for s in range(int(a), min(int(b) + 1, len(curva))):
            if curva[s] > valor and any(x <= s + 0.5 <= y for x, y in corpo):
                melhor, valor = s + 0.5, curva[s]
    return melhor


def _capitulos_com_fala(itens: list[dict], modo: str, transcricao: dict) -> list[dict]:
    """Para o Claude dar nome: intervalo e o que foi falado em cada capítulo (ou momento)."""
    saida = []
    for k, c in enumerate(itens):
        if modo == "melhores":
            a, b, sugestao = c["inicio"], c["fim"], c.get("titulo", "")
        else:
            a = c["t_origem"]
            b = itens[k + 1]["t_origem"] if k + 1 < len(itens) else transcricao["duracao"]
            sugestao = ""
        fala = " ".join(w["p"] for w in tr.palavras_no_intervalo(transcricao, a, b))
        saida.append({"inicio": a, "fim": b, "fala": fala[:300], "titulo_sugerido": sugestao})
    return saida


# ================================================================ da edição aos blocos

def _blocos(edl: dict, palavras: list[dict], duracao: float) -> tuple[list[dict], list[dict]]:
    """Monta a lista de blocos (e os capítulos) a partir da edição salva. Determinístico: a mesma edição
    gera os mesmos blocos, o que permite reaproveitar os já renderizados."""
    ativas = [(r["inicio"], r["fim"]) for r in edl["remocoes"] if not r.get("manter")]
    pausa, folga = RITMOS.get(edl.get("ritmo") or "dinamico", RITMOS["dinamico"])
    blocos, capitulos = [], []
    if edl["modo_longo"] == "enxugar":
        if edl["tipo"] == "falado":
            base = ef.intervalos_de_fala(palavras, 0.0, duracao, pausa_max=pausa, folga=folga)
        else:
            base = [(0.0, duracao)]
        corpo = pipeline._subtrair(base, ativas) if ativas else base
        blocos = [{"tipo": "corpo", "trechos": t} for t in _fatiar(corpo)]
        capitulos = [{"t_origem": c["t_origem"], "titulo": c["titulo"]} for c in edl["capitulos"] if c.get("ativo", True)]
    else:
        for m in sorted((m for m in edl["momentos"] if m.get("manter", True)), key=lambda m: m["inicio"]):
            if edl["tipo"] == "falado":
                base = ef.intervalos_de_fala(palavras, m["inicio"], m["fim"], pausa_max=pausa, folga=folga)
            else:
                base = [(m["inicio"], m["fim"])]
            trechos = pipeline._subtrair(pipeline._subtrair(base, [tuple(x) for x in m.get("remover") or []]), ativas)
            if ef.duracao_trechos(trechos) < 5:
                continue
            blocos.append({"tipo": "momento", "trechos": trechos, "titulo": m["titulo"], "flash": bool(blocos)})
            capitulos.append({"bloco": len(blocos) - 1, "titulo": m["titulo"]})
    if edl.get("abertura_ativa", True) and edl.get("abertura"):
        blocos.insert(0, {"tipo": "abertura", "trechos": [tuple(edl["abertura"])]})
        for c in capitulos:
            if "bloco" in c:
                c["bloco"] += 1
    for bl in blocos:  # grade de quadros: render, legenda e capítulos usam exatamente os mesmos trechos
        bl["trechos"] = ef.trechos_na_grade(bl["trechos"])
    return [bl for bl in blocos if bl["trechos"]], capitulos


def _fatiar(corpo: list[tuple[float, float]], max_span: float = 360.0, max_gap: float = 30.0) -> list[list]:
    """Agrupa os trechos mantidos em blocos de render: até ~6 min do original por bloco e sem pausa removida
    maior que 30 s dentro (o bloco decodifica o intervalo inteiro, então não vale atravessar buracos grandes)."""
    blocos, atual = [], []
    for a, b in corpo:
        if atual and (a - atual[-1][1] > max_gap or b - atual[0][0] > max_span):
            blocos.append(atual)
            atual = []
        atual.append((a, b))
    if atual:
        blocos.append(atual)
    return blocos


def _zoom_bloco(trechos, fator: float, intervalo_min: float = 6.0, pulo_min: float = 0.3) -> list:
    """Punch-in alternado nos cortes secos (a pesquisa: 15-20% de zoom nas quebras de frase esconde o pulo),
    mas trocando no máximo a cada 6 s: zoom em toda frase cansa quem assiste vídeo longo."""
    zoom, t, fechado, ultimo, desde = [], 0.0, False, 0.0, 0.0
    for k, (a, b) in enumerate(trechos):
        if k > 0 and a - trechos[k - 1][1] >= pulo_min and t - ultimo >= intervalo_min:
            if fechado:
                zoom.append((round(desde, 3), round(t, 3), fator))
            else:
                desde = t
            fechado, ultimo = not fechado, t
        t += b - a
    if fechado:
        zoom.append((round(desde, 3), round(t + 1, 3), fator))
    return zoom


def _musica(opc: dict, meta: dict, pid: str, capitulos: list[dict], duracao: float):
    """Música de fundo do vídeo longo. Com um clima (ou automática) e mais de uma faixa na pasta, troca de
    faixa no começo dos capítulos, com crossfade: uma faixa só em loop por meia hora cansa."""
    escolha = (opc.get("musica") or "").strip()
    if not escolha:
        return None
    if escolha == "auto" or escolha in CLIMAS:
        clima = escolha if escolha in CLIMAS else ("energetica" if meta["modo"] == "gameplay" else "calma")
        faixas = biblioteca.sequencia_musicas(clima, meta["id"])
        if not faixas:
            pipeline._aviso(pid, "Música pedida, mas a biblioteca está vazia. Em Configurações > Biblioteca de "
                                 "áudio dá para baixar o pacote grátis.")
            return None
        if len(faixas) == 1:
            return str(faixas[0])
        pontos = [0.0]
        for c in capitulos:  # capítulo curto demais (ou colado no fim) não troca a faixa
            if c["t"] - pontos[-1] >= 45 and duracao - c["t"] >= 45:
                pontos.append(c["t"])
        return [(t, str(faixas[k % len(faixas)])) for k, t in enumerate(pontos)]
    return escolha if Path(escolha).exists() else None


def _montar(pid, meta, opc, edl, transcricao, info, prog, cancelado) -> dict:
    """Renderiza os blocos (reaproveitando os que não mudaram) e junta tudo."""
    video = meta["video"]
    palavras = _corrigir_todas(transcricao["palavras"], edl.get("correcoes"))
    blocos, capitulos_brutos = _blocos(edl, palavras, info["duracao"])
    if not blocos:
        raise ValueError("Não sobrou nada para montar o vídeo (tudo foi considerado tempo morto).")
    pasta = projetos.pasta(pid) / "tmp" / "longo"
    pasta.mkdir(parents=True, exist_ok=True)
    largura, altura = ef.tamanho_saida(info)
    est = legendas.estilo(opc["preset"], opc["cor"])

    # 1) Prepara cada bloco e calcula a assinatura (mudou algo? então re-renderiza)
    preparados = []
    for k, bl in enumerate(blocos):
        dur = ef.duracao_trechos(bl["trechos"])
        zoom = []
        if opc["zoom"]:
            zoom = ([(0.0, dur + 1, edl["zoom_fator"])] if bl["tipo"] == "abertura"
                    else _zoom_bloco(bl["trechos"], edl["zoom_fator"]))
        pal = legendas.palavras_do_clipe(palavras, bl["trechos"]) if palavras else []
        texto_ass = None
        if (opc["legenda"] and pal) or bl.get("titulo"):
            rascunho = pasta / f"rascunho_{k:03d}.ass"
            legendas.gerar_ass(pal if opc["legenda"] else [], est, rascunho, largura, altura, dur,
                               bl.get("titulo"), bool(opc["legenda"]))
            texto_ass = rascunho.read_text(encoding="utf-8-sig")
            rascunho.unlink(missing_ok=True)
        chave = hashlib.sha1(repr((str(video), bl["trechos"], zoom, texto_ass, bool(bl.get("flash")),
                                   largura, altura)).encode("utf-8")).hexdigest()[:16]
        preparados.append({"bloco": bl, "dur": dur, "zoom": zoom, "pal": pal, "ass": texto_ass,
                           "arq": pasta / f"bloco_{chave}.mkv"})

    # 2) Renderiza só os que não estão no cache
    pendentes = [p for p in preparados if not p["arq"].exists()]
    total = sum(p["dur"] for p in pendentes) or 1.0
    feito = 0.0
    for k, p in enumerate(preparados):
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()
        if p["arq"].exists():
            continue
        ass_rel = None
        if p["ass"]:
            arq_ass = p["arq"].with_suffix(".ass")
            arq_ass.write_text(p["ass"], encoding="utf-8-sig")
            ass_rel = os.path.relpath(arq_ass, config.DADOS).replace("\\", "/")
        parcial = p["arq"].with_name(p["arq"].stem + "_parcial.mkv")
        ef.renderizar_bloco(
            video, p["bloco"]["trechos"], parcial, info, zoom=p["zoom"], arquivo_ass=ass_rel,
            flash=bool(p["bloco"].get("flash")),
            progresso=lambda x, feito=feito, dur=p["dur"], k=k: prog(
                0.9 * (feito + x * dur) / total, f"Bloco {k + 1} de {len(preparados)}"),
            cancelado=cancelado)
        os.replace(parcial, p["arq"])
        feito += p["dur"]
    reaproveitados = len(preparados) - len(pendentes)
    usados = {p["arq"].name for p in preparados} | {p["arq"].with_suffix(".ass").name for p in preparados}
    for velho in pasta.glob("bloco_*"):  # cache só da versão atual (os blocos ocupam espaço)
        if velho.name not in usados:
            velho.unlink(missing_ok=True)

    # 3) Tempos finais, capítulos, efeitos e junção
    duracoes = [p["dur"] for p in preparados]
    offsets = [sum(duracoes[:k]) for k in range(len(duracoes))]
    duracao = sum(duracoes)
    palavras_finais = [{**w, "i": w["i"] + offsets[k], "f": w["f"] + offsets[k]}
                       for k, p in enumerate(preparados) for w in p["pal"]]
    capitulos = _capitulos_finais(capitulos_brutos, blocos, offsets, duracao)
    efeitos = []
    if opc["efeitos"]:
        whoosh = biblioteca.escolher_efeito("whoosh", meta["id"])
        if whoosh:
            viradas = [offsets[k] for k, bl in enumerate(blocos)
                       if k > 0 and (bl.get("flash") or blocos[k - 1]["tipo"] == "abertura")]
            efeitos = [(max(0.0, t - 0.25), str(whoosh), 0.45) for t in viradas]

    nome = projetos._nome_seguro(meta["nome"])
    destino = projetos.garantir_saida(meta) / f"{nome}_editado.mp4"
    temporario = destino.with_name(destino.stem + "_novo.mp4")
    ef.juntar_blocos([p["arq"] for p in preparados], temporario, duracao, normalizar=True,
                     musica=_musica(opc, meta, pid, capitulos, duracao), efeitos=efeitos,
                     limpar_voz=bool(opc["limpar_voz"]),
                     capitulos=[(c["t"], c["titulo"]) for c in capitulos],
                     progresso=lambda x: prog(0.9 + 0.1 * x, "Juntando os blocos e mixando o áudio"),
                     cancelado=cancelado)
    saida = _substituir(temporario, destino)
    cortes = sum(max(0, len(bl["trechos"]) - 1) for bl in blocos) + len(blocos) - 1
    log.info("Vídeo longo: %d blocos (%d do cache), %.1f s", len(blocos), reaproveitados, duracao)
    return {"arquivo": saida, "duracao": duracao, "capitulos": capitulos, "palavras": palavras_finais,
            "cortes": cortes, "blocos": blocos, "offsets": offsets, "reaproveitados": reaproveitados}


def _substituir(novo: Path, destino: Path) -> Path:
    """Troca o vídeo final pelo novo. Se o antigo estiver aberto (tocando no navegador ou num player),
    o Windows não deixa: tenta por alguns segundos e, se não der, grava com outro nome."""
    for _ in range(20):
        try:
            os.replace(novo, destino)
            return destino
        except PermissionError:
            time.sleep(0.5)
    alternativo = destino.with_name(f"{destino.stem}_{int(time.time())}.mp4")
    os.replace(novo, alternativo)
    return alternativo


def _capitulos_finais(capitulos: list[dict], blocos: list[dict], offsets: list[float], duracao: float) -> list[dict]:
    """Converte os capítulos para o tempo do vídeo final e aplica as regras do YouTube:
    o primeiro em 0:00 e cada um com pelo menos 10 s."""
    finais = []
    for c in capitulos:
        if "bloco" in c:
            t = offsets[c["bloco"]]
        else:
            t = _posicao_final(c["t_origem"], blocos, offsets)
            if t is None:
                continue
        finais.append({"t": round(t, 2), "titulo": c["titulo"].strip()[:80] or "Parte"})
    finais.sort(key=lambda c: c["t"])
    if finais:
        finais[0]["t"] = 0.0  # a abertura entra no primeiro capítulo
    limpos = []
    for c in finais:
        if limpos and c["t"] - limpos[-1]["t"] < 10:
            continue
        if duracao - c["t"] < 10 and limpos:
            continue
        limpos.append(c)
    return limpos


def _posicao_final(t: float, blocos: list[dict], offsets: list[float]) -> float | None:
    """Tempo no vídeo final de um instante do original (se ele foi cortado, o começo do próximo trecho)."""
    for k, bl in enumerate(blocos):
        if bl["tipo"] == "abertura":
            continue
        acum = offsets[k]
        for a, b in bl["trechos"]:
            if t < a:
                return acum
            if t <= b:
                return acum + (t - a)
            acum += b - a
    return None


# ================================================================ saída: srt, texto do YouTube, thumbnails

def _tempo_yt(t: float) -> str:
    t = int(t)
    h, resto = divmod(t, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _finalizar(pid, meta, edl, res, prog) -> dict:
    """Legenda .srt, texto pronto para o YouTube (títulos, descrição com capítulos, tags) e thumbnails."""
    saida = res["arquivo"]
    srt = legendas.gerar_srt(res["palavras"], saida.with_suffix(".srt")) if res["palavras"] else None
    prog(0.2, "Legenda .srt pronta")

    capitulos_txt = "\n".join(f"{_tempo_yt(c['t'])} {c['titulo']}" for c in res["capitulos"])
    descricao = (edl.get("descricao") or "").strip()
    completa = descricao
    if len(res["capitulos"]) >= 3:
        completa = f"{descricao}\n\nCapítulos:\n{capitulos_txt}".strip()
    titulos = [t for t in edl.get("titulos", []) if t][:3] or [meta["nome"]]
    tags = edl.get("tags", [])
    texto = saida.with_name(projetos._nome_seguro(meta["nome"]) + "_youtube.txt")
    texto.write_text(
        "TÍTULOS SUGERIDOS\n" + "\n".join(f"{k}. {t}" for k, t in enumerate(titulos, 1))
        + f"\n\nDESCRIÇÃO\n{completa}\n\nTAGS\n{', '.join(tags)}\n", encoding="utf-8")
    prog(0.35, "Criando as thumbnails")
    texto_thumb = (edl.get("texto_thumb") or " ".join(titulos[0].split()[:4])).strip()
    thumbs = _thumbnails(pid, meta["video"], res, texto_thumb, meta["modo"])
    return {
        "arquivo": str(saida), "duracao": round(res["duracao"], 2),
        "duracao_original": round(meta.get("duracao_video") or 0, 2),
        "modo_longo": edl["modo_longo"], "cortes": res["cortes"], "capitulos": res["capitulos"],
        "titulos": titulos, "descricao": descricao, "descricao_completa": completa, "tags": tags,
        "texto_thumb": texto_thumb, "srt": str(srt) if srt else None, "texto": str(texto), "thumbs": thumbs,
        "reaproveitados": res["reaproveitados"], "blocos": len(res["blocos"]), "versao": int(time.time()),
    }


_trava_thumb = threading.Lock()


def _no_original(t: float, blocos: list[dict], offsets: list[float]) -> float:
    """Instante do vídeo original que aparece no segundo `t` do vídeo final."""
    for k in range(len(blocos) - 1, -1, -1):
        if t >= offsets[k]:
            resto = t - offsets[k]
            for a, b in blocos[k]["trechos"]:
                if resto <= b - a:
                    return a + resto
                resto -= b - a
            return blocos[k]["trechos"][-1][1]
    return blocos[0]["trechos"][0][0]


def _thumbnails(pid: str, video: str, res: dict, texto: str, modo: str) -> list[str]:
    """3 thumbnails 1280x720: quadros nítidos e bem iluminados (na fala, com o rosto grande) com o texto
    de impacto em letra grossa do lado oposto ao rosto, sobre uma sombra para dar leitura.
    Os quadros vêm do vídeo ORIGINAL (sem legenda nem título queimados), de trechos que ficaram no final."""
    import cv2
    from PIL import Image

    import reenquadramento as rq
    duracao = res["duracao"]
    candidatos = []
    with _trava_thumb:
        det = rq.DetectorRostos() if modo == "falado" else None
        cap = cv2.VideoCapture(str(video))
        try:
            for k in range(18):
                t = duracao * (0.03 + 0.94 * k / 17)
                cap.set(cv2.CAP_PROP_POS_MSEC, _no_original(t, res["blocos"], res["offsets"]) * 1000)
                ok, quadro = cap.read()
                if not ok:
                    continue
                h, w = quadro.shape[:2]
                peq = cv2.resize(quadro, (640, int(640 * h / w)))
                cinza = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
                nitidez = cv2.Laplacian(cinza, cv2.CV_64F).var() ** 0.5
                brilho = float(cinza.mean())
                cor = float(cv2.cvtColor(peq, cv2.COLOR_BGR2HSV)[..., 1].mean())
                rosto, area = None, 0.0
                if det is not None:
                    faces = det(peq)
                    if faces:
                        x, y, fw, fh, _ = max(faces, key=lambda f: f[2] * f[3])
                        area = fw * fh / (peq.shape[0] * peq.shape[1])
                        rosto = (x + fw / 2) / peq.shape[1]
                nota = nitidez * (0.6 + cor / 255) * (1.0 if 45 < brilho < 210 else 0.3) * (1 + 10 * area)
                candidatos.append((nota, t, quadro, rosto))
        finally:
            cap.release()
    escolhidos = []
    for c in sorted(candidatos, key=lambda c: -c[0]):
        if all(abs(c[1] - e[1]) > duracao * 0.12 for e in escolhidos):
            escolhidos.append(c)
        if len(escolhidos) == 3:
            break
    arquivos = []
    for k, (_, _, quadro, rosto) in enumerate(escolhidos, 1):
        img = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
        img = _compor_thumb(img, texto, "direita" if rosto is not None and rosto < 0.5 else "esquerda")
        arq = projetos.pasta(pid) / "thumbs" / f"longo_{k}.jpg"
        arq.parent.mkdir(exist_ok=True)
        img.save(arq, quality=90)
        arquivos.append(str(arq))
    return arquivos


def _compor_thumb(img, texto: str, lado: str):
    """Quadro em 1280x720 + sombra do lado do texto + texto em Anton, branco com a última linha amarela."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    W, H = 1280, 720
    w, h = img.size
    escala = max(W / w, H / h)
    img = img.resize((int(w * escala + 0.5), int(h * escala + 0.5)), Image.LANCZOS)
    x0, y0 = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((x0, y0, x0 + W, y0 + H)).convert("RGB")
    palavras = texto.upper().split()
    if not palavras:
        return img

    # sombra em degradê do lado do texto
    linha = Image.new("L", (W, 1))
    linha.putdata([int(max(0.0, 1 - (x / W if lado == "esquerda" else 1 - x / W) / 0.62) ** 1.4 * 190)
                   for x in range(W)])
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, linha.resize((W, H)))

    fonte_arq = config.PASTA_FONTES / "Anton-Regular.ttf"
    # divide em até 3 linhas equilibradas e acha o maior tamanho que cabe em ~46% da largura
    melhor = None
    for n_linhas in range(1, min(3, len(palavras)) + 1):
        por = -(-len(palavras) // n_linhas)
        linhas = [" ".join(palavras[i:i + por]) for i in range(0, len(palavras), por)]
        for tam in range(210, 50, -6):
            fonte = ImageFont.truetype(str(fonte_arq), tam)
            larguras = [fonte.getbbox(l)[2] for l in linhas]
            altura_total = len(linhas) * tam * 1.02
            if max(larguras) <= W * 0.46 and altura_total <= H * 0.78:
                if melhor is None or tam > melhor[0]:
                    melhor = (tam, linhas, fonte, larguras)
                break
    if melhor is None:
        return img
    tam, linhas, fonte, larguras = melhor
    camada = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(camada), ImageDraw.Draw(sombra)
    y = (H - len(linhas) * tam * 1.02) / 2
    borda = max(4, tam // 16)
    for k, (linha, lw) in enumerate(zip(linhas, larguras)):
        x = 64 if lado == "esquerda" else W - 64 - lw
        cor = (255, 230, 0) if k == len(linhas) - 1 and len(linhas) > 1 else (255, 255, 255)
        ds.text((x + 8, y + 10), linha, font=fonte, fill=(0, 0, 0, 200))
        d.text((x, y), linha, font=fonte, fill=cor, stroke_width=borda, stroke_fill=(0, 0, 0))
        y += tam * 1.02
    img = img.convert("RGBA")
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(10)))
    img.alpha_composite(camada)
    return img.convert("RGB")
