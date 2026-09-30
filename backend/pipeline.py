"""
Pipeline completo, usado pelo CLI (editar.py) e pela API (api.py).

Etapas: Transcrevendo -> Analisando -> Escolhendo trechos -> Cortando -> Legendando

O Claude é usado para interpretar a instrução e escolher os trechos. Se a API
não estiver disponível (sem chave/créditos/internet), entra o planejador local
e um aviso é registrado no projeto.
"""
import logging
import os
import random
import time
from pathlib import Path

import analise_audio
import config
import custos
import editor_ffmpeg as ef
import legendas
import planejador_llm as llm
import planejador_local as local
import projetos
import reenquadramento as rq
import transcricao as tr
from config import Cancelado
from modelos import Corte, PlanoEdicao

log = logging.getLogger("pipeline")

ETAPAS = [
    ("transcrevendo", "Transcrevendo"),
    ("analisando", "Analisando"),
    ("escolhendo", "Escolhendo trechos"),
    ("cortando", "Cortando"),
    ("legendando", "Legendando"),
]
PESOS = {"transcrevendo": 0.25, "analisando": 0.08, "escolhendo": 0.07, "cortando": 0.2, "legendando": 0.4}


# ================================================================ progresso

class Progresso:
    """Atualiza etapas e % no meta.json (com no máximo ~3 gravações por segundo)."""

    def __init__(self, pid: str, imprimir: bool = False):
        self.pid = pid
        self.imprimir = imprimir
        self.atual = None
        self.concluido = 0.0
        self._ultima_gravacao = 0.0

    def etapa(self, nome: str):
        agora = time.time()
        anterior = self.atual
        if anterior:
            self.concluido += PESOS[anterior]
        concluido = self.concluido

        def f(meta):
            if anterior:
                meta["etapas"][anterior].update(status="ok", fim=agora)
            meta["etapas"][nome] = {"status": "ativo", "inicio": agora, "fim": None, "detalhe": ""}
            meta["etapa"] = nome
            meta["progresso"] = round(concluido, 4)
        self.atual = nome
        projetos.atualizar(self.pid, f)
        if self.imprimir:
            print(f"\n==> {dict(ETAPAS)[nome]}...")

    def __call__(self, p: float, detalhe: str = ""):
        total = self.concluido + PESOS.get(self.atual, 0) * max(0.0, min(p, 1.0))
        agora = time.time()
        if agora - self._ultima_gravacao < 0.35 and p < 1:
            return
        self._ultima_gravacao = agora

        def f(meta):
            meta["progresso"] = round(total, 4)
            if detalhe and self.atual:
                meta["etapas"][self.atual]["detalhe"] = detalhe
        projetos.atualizar(self.pid, f)
        if self.imprimir:
            print(f"\r    {total * 100:5.1f}%  {detalhe[:60]:<60}", end="", flush=True)

    def finalizar(self):
        agora = time.time()

        def f(meta):
            if self.atual:
                meta["etapas"][self.atual].update(status="ok", fim=agora)
            meta["progresso"] = 1.0
        projetos.atualizar(self.pid, f)


def _claude_falhou(pid: str, erro: Exception):
    _aviso(pid, f"Claude indisponível: {str(erro).rstrip('.')}. Usando o planejador local (mais simples).")


def _aviso(pid: str, texto: str):
    log.warning(texto)
    projetos.atualizar(pid, lambda m: m["avisos"].append(texto) if texto not in m["avisos"] else None)


# ================================================================ configuração efetiva de um clipe

def plano_base(opcoes: dict) -> PlanoEdicao:
    """Plano inicial a partir das opções rápidas da interface/CLI."""
    dados = {
        "num_clips": opcoes.get("num_clips", 3),
        "formato": opcoes.get("formato", "9:16"),
        "legenda": {"preset": opcoes.get("preset", "opus"), "estilo": opcoes.get("estilo_legenda", "simples")},
        "musica_caminho": opcoes.get("musica_caminho") or None,
    }
    if opcoes.get("duracao"):
        dados["duracao_min"], dados["duracao_max"] = opcoes["duracao"]
    if opcoes.get("cor"):
        dados["legenda"]["cor"] = opcoes["cor"]
    return PlanoEdicao.model_validate(dados)


def config_clip(meta: dict, clip: dict) -> dict:
    plano, c = meta["plano"], clip.get("config", {})
    leg = plano["legenda"]
    return {
        "formato": c.get("formato", plano["formato"]),
        "legenda_ativa": c.get("legenda_ativa", leg["ativa"]),
        "estilo": c.get("estilo", leg["estilo"]),
        "preset": c.get("preset", leg["preset"]),
        "cor": c.get("cor", leg["cor"]),
        "titulo_ativo": c.get("titulo_ativo", plano["titulo_gancho"]),
        "zoom": c.get("zoom", plano["zoom_em_enfase"]),
        "remover_silencios": c.get("remover_silencios", plano["remover_silencios"]),
        "normalizar": c.get("normalizar", plano["normalizar_audio"]),
        "musica": c.get("musica", plano["musica_caminho"] if plano["musica_fundo"] else None),
        "layout": c.get("layout", meta["opcoes"].get("layout", "auto")),
        "deslocamento_x": float(c.get("deslocamento_x", 0.0)),
        "video_apoio": meta["opcoes"].get("video_apoio") or None,
    }


def _palavras_editadas(transcricao: dict, clip: dict) -> list[dict]:
    """Aplica as edições de texto feitas no editor (chave = início da palavra)."""
    edicoes = clip.get("palavras_editadas") or {}
    if not edicoes:
        return transcricao["palavras"]
    resultado = []
    for w in transcricao["palavras"]:
        novo = edicoes.get(f"{w['i']:.3f}")
        if novo is None:
            resultado.append(w)
        elif novo.strip():
            resultado.append({**w, "p": novo.strip()})
    return resultado


# ================================================================ render de um clipe

def renderizar_clip(pid: str, cid: str, transcricao: dict | None = None, progresso=None, cancelado=None) -> dict:
    """Corta + reenquadra + legenda um clipe. Pode ser chamado de novo após edições."""
    meta = projetos.ler(pid)
    clip = projetos.clip(meta, cid)
    cfg = config_clip(meta, clip)
    transcricao = transcricao or tr.transcrever(meta["video"])
    palavras = _palavras_editadas(transcricao, clip)
    pasta = projetos.pasta(pid)
    tmp = pasta / "tmp"
    tmp.mkdir(exist_ok=True)

    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(status="renderizando", progresso=0.0, erro=None))
    ultimo = [0.0]

    def prog(fase, p):  # fase 0 = corte (30%), fase 1 = render (70%)
        total = (0.3 * p) if fase == 0 else (0.3 + 0.7 * p)
        if progresso:
            progresso(total)
        if time.time() - ultimo[0] > 0.5:  # progresso do próprio clipe (para o card na interface)
            ultimo[0] = time.time()
            projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(progresso=round(total, 3)))

    # 1) Trechos (removendo silêncios se pedido) e corte
    if cfg["remover_silencios"]:
        trechos = ef.intervalos_de_fala(palavras, clip["inicio"], clip["fim"])
    else:
        trechos = [(clip["inicio"], clip["fim"])]
    corte = tmp / f"{cid}_corte.mp4"
    assinatura = repr((trechos, cfg["normalizar"], cfg["musica"]))
    if not (corte.exists() and clip.get("corte_assinatura") == assinatura):
        ef.cortar(meta["video"], trechos, corte, normalizar=cfg["normalizar"], musica=cfg["musica"],
                  progresso=lambda p: prog(0, p), cancelado=cancelado)
    duracao = ef.duracao_trechos(trechos)

    # 2) Palavras no tempo do clipe + momentos de zoom
    pal_clip = legendas.palavras_do_clipe(palavras, trechos, clip.get("palavras_enfase"), clip.get("emojis"))
    zoom = legendas.momentos_de_zoom(pal_clip) if cfg["zoom"] else []
    if cfg["zoom"] and clip.get("pico") is not None:
        t_pico = ef.mapear_tempo(clip["pico"], trechos)
        if t_pico is not None:
            zoom.append((max(0, t_pico - 0.4), t_pico + 0.9))

    # 3) Estilo, título e render
    est = legendas.estilo(cfg["preset"], cfg["cor"])
    titulo = clip.get("titulo") if cfg["titulo_ativo"] else None
    largura, altura = rq.RESOLUCOES[cfg["formato"]]
    saida_dir = Path(meta["saida_dir"])
    saida = saida_dir / f"{cid}.mp4"
    barra = est.get("barra_progresso", {})
    opc = rq.OpcoesRender(
        formato=cfg["formato"], layout=cfg["layout"], modo=meta["modo"], deslocamento_x=cfg["deslocamento_x"],
        zoom_momentos=zoom, video_apoio=cfg["video_apoio"],
        barra_progresso={"cor": est["cor_destaque"], "altura": barra.get("altura", 10)} if barra.get("ativa") else None,
    )

    info, usou_remotion = None, False
    if cfg["estilo"] == "animada" and (cfg["legenda_ativa"] or titulo):
        try:
            base = tmp / f"{cid}_base.mp4"
            opc_base = rq.OpcoesRender(**{**opc.__dict__, "barra_progresso": None})
            info = rq.renderizar(corte, base, opc_base, progresso=lambda p: prog(1, p * 0.4), cancelado=cancelado)
            legendas.renderizar_remotion(
                base, saida, pal_clip if cfg["legenda_ativa"] else [], est, titulo, duracao, largura, altura,
                barra=bool(barra.get("ativa")), progresso=lambda p: prog(1, 0.4 + 0.6 * p), cancelado=cancelado)
            usou_remotion = True
        except Cancelado:
            raise
        except Exception as e:
            _aviso(pid, f"Legenda animada (Remotion) falhou no {cid}, usando legenda simples: {str(e)[:200]}")
    if not usou_remotion:
        arq_ass = tmp / f"{cid}.ass"
        legendas.gerar_ass(pal_clip, est, arq_ass, largura, altura, duracao, titulo, cfg["legenda_ativa"])
        opc.arquivo_ass = os.path.relpath(arq_ass, config.DADOS).replace("\\", "/")
        info = rq.renderizar(corte, saida, opc, progresso=lambda p: prog(1, p), cancelado=cancelado)

    thumb = pasta / "thumbs" / f"{cid}.jpg"
    ef.extrair_frame(saida, min(1.2, duracao / 2), thumb, largura=540)

    def f(m):
        c = projetos.clip(m, cid)
        c.update(trechos=trechos, corte_assinatura=assinatura, arquivo=str(saida), thumb=str(thumb),
                 duracao=round(duracao, 2), versao=int(time.time()), status="pronto", erro=None,
                 layout_usado=info.get("layout") if info else None,
                 legenda_usada="animada" if usou_remotion else "simples")
    projetos.atualizar(pid, f)
    return projetos.clip(projetos.ler(pid), cid)


# ================================================================ escolha de trechos

TITULOS_GAMEPLAY = ["Olha isso!", "Não acredito nisso", "Que jogada!", "Momento insano", "Isso foi sério?",
                    "Ninguém esperava", "A melhor jogada", "Clutch absurdo"]


def _plano(meta: dict, pid: str) -> PlanoEdicao:
    base = plano_base(meta["opcoes"])
    try:
        return llm.interpretar_instrucao(meta["instrucao"], meta["modo"], base, pid)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        return local.interpretar_instrucao(meta["instrucao"], base)


def _cortes_falado(transcricao, plano, pid, excluir=None, quantidade=None) -> list[Corte]:
    if not transcricao["palavras"]:
        raise ValueError("Nenhuma fala encontrada no vídeo. Para gameplay sem voz use o modo Gameplay.")
    try:
        return llm.escolher_cortes_falado(transcricao, plano, pid, excluir, quantidade)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        return local.escolher_cortes_falado(transcricao, plano, excluir, quantidade)


def _cortes_gameplay(video, transcricao, analise, plano, pid, excluir=None, quantidade=None,
                     refinar=False, cancelado=None) -> list[Corte]:
    quantidade = quantidade or plano.num_clips
    tem_fala = len(transcricao["palavras"]) >= 20
    candidatos = analise_audio.candidatos_gameplay(
        analise, transcricao if tem_fala else None, plano.duracao_min, plano.duracao_max,
        maximo=min(15, quantidade * 3), excluir=excluir)
    if not candidatos:
        raise ValueError("Nenhum pico de energia encontrado no áudio.")

    # Etapa 11 (opcional): confirma os melhores candidatos olhando frames
    if refinar:
        candidatos = refinar_por_frames(video, candidatos, quantidade, pid, cancelado)

    try:
        resposta = llm.escolher_cortes_gameplay(candidatos, quantidade, pid)
        por_id = {c["id"]: c for c in candidatos}
        cortes = []
        for e in resposta.escolhas:
            c = por_id.get(e.id)
            if c:
                cortes.append(Corte(inicio=c["inicio"], fim=c["fim"], titulo=e.titulo, nota=e.nota, pico=c["pico"],
                                    justificativa=e.justificativa, palavras_enfase=e.palavras_enfase, emojis=e.emojis))
        if cortes:
            return cortes[:quantidade]
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)

    melhores = sorted(candidatos, key=lambda c: c.get("nota_refino", c["energia"]), reverse=True)[:quantidade]
    titulos = random.sample(TITULOS_GAMEPLAY, len(TITULOS_GAMEPLAY))
    cortes = []
    for c in melhores:
        corte = Corte(inicio=c["inicio"], fim=c["fim"], titulo=c.get("titulo_refino") or titulos[len(cortes) % len(titulos)],
                      nota=int(c.get("nota_refino", c["energia"])),
                      justificativa=c.get("justificativa_refino") or f"Pico de energia no áudio ({c['picos']} pico(s) no trecho)",
                      pico=c["pico"])
        cortes.append(corte)
    return cortes


def refinar_por_frames(video, candidatos, quantidade, pid, cancelado=None) -> list[dict]:
    """Envia 4 frames de cada pré-selecionado ao Claude (só os melhores, para economizar)."""
    import tempfile
    pre = sorted(candidatos, key=lambda c: c["energia"], reverse=True)[:min(len(candidatos), quantidade + 2)]
    with tempfile.TemporaryDirectory() as tmp:
        for c in pre:
            if cancelado is not None and cancelado.is_set():
                raise Cancelado()
            frames = []
            for k, frac in enumerate((0.2, 0.5, 0.65, 0.85)):
                t = c["inicio"] + (c["fim"] - c["inicio"]) * frac
                arq = ef.extrair_frame(video, t, Path(tmp) / f"{c['id']}_{k}.jpg", largura=640)
                if arq.exists():
                    frames.append(arq.read_bytes())
            try:
                r = llm.confirmar_frames(frames, f"energia {c['energia']:.0f}/100; fala: {c['fala'][:200] or '(sem fala)'}", pid)
            except llm.ErroClaude as e:
                _aviso(pid, f"Refino por frames indisponível: {str(e).rstrip('.')}.")
                return candidatos
            c["nota_refino"] = r.nota if r.bom_momento else min(r.nota, 30)
            c["titulo_refino"], c["justificativa_refino"] = r.titulo, r.justificativa
            c["energia"] = round(0.5 * c["energia"] + 0.5 * c["nota_refino"], 1)
    return sorted(pre, key=lambda c: c["energia"], reverse=True)


def _novo_clip(cid: str, corte: Corte) -> dict:
    return {
        "id": cid, "inicio": corte.inicio, "fim": corte.fim, "titulo": corte.titulo, "nota": corte.nota,
        "justificativa": corte.justificativa, "palavras_enfase": corte.palavras_enfase,
        "emojis": [e.model_dump() for e in corte.emojis], "pico": corte.pico,
        "config": {}, "palavras_editadas": {}, "status": "fila", "arquivo": None, "thumb": None,
        "duracao": round(corte.fim - corte.inicio, 2), "versao": 0,
    }


# ================================================================ projeto completo

def processar(pid: str, cancelado=None, imprimir: bool = False) -> dict:
    meta = projetos.ler(pid)
    prog = Progresso(pid, imprimir)
    video = meta["video"]
    if not Path(video).exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {video}")

    def inicio(m):
        m.update(status="processando", iniciado_em=time.time(), erro=None, progresso=0.0, etapas={}, avisos=[])
    projetos.atualizar(pid, inicio)

    info = ef.sondar(video)
    if not (config.PASTA_PROJETOS / pid / "thumb.jpg").exists():
        ef.extrair_frame(video, info["duracao"] * 0.1, projetos.pasta(pid) / "thumb.jpg", largura=640)
    projetos.atualizar(pid, lambda m: m.update(
        duracao_video=info["duracao"], resolucao=f"{info['largura']}x{info['altura']}",
        saida_dir=m.get("saida_dir") or str(projetos.pasta_saida_para(m["nome"], pid))))

    # Refazendo um projeto: apaga os clipes antigos para não sobrar arquivo de outra rodada
    for antigo in Path(projetos.ler(pid)["saida_dir"]).glob("clip_*.mp4"):
        antigo.unlink(missing_ok=True)
    projetos.atualizar(pid, lambda m: m.update(clips=[]))

    # 1. Transcrição (também no gameplay: captura os comentários do jogador)
    prog.etapa("transcrevendo")
    transcricao = tr.transcrever(video, prog, cancelado)

    # 2. Plano + análise de áudio
    prog.etapa("analisando")
    plano = _plano(meta, pid)
    prog(0.4, "Plano de edição pronto")
    analise = None
    if meta["modo"] == "gameplay":
        analise = analise_audio.analisar(video, lambda p, d="": prog(0.4 + 0.6 * p, d), cancelado)
    projetos.atualizar(pid, lambda m: m.update(plano=plano.model_dump(), nao_atendido=list(plano.nao_atendido)))
    if plano.nao_atendido:
        log.warning("Não atendido: %s", "; ".join(plano.nao_atendido))

    # 3. Escolha dos trechos
    prog.etapa("escolhendo")
    if meta["modo"] == "gameplay":
        cortes = _cortes_gameplay(video, transcricao, analise, plano, pid,
                                  refinar=bool(meta["opcoes"].get("refinar_frames")), cancelado=cancelado)
    else:
        cortes = _cortes_falado(transcricao, plano, pid)
    if not cortes:
        raise ValueError("Nenhum trecho adequado foi encontrado.")
    cortes.sort(key=lambda c: c.nota, reverse=True)
    clips = [_novo_clip(f"clip_{i:02d}", c) for i, c in enumerate(cortes, 1)]
    projetos.atualizar(pid, lambda m: m.update(clips=clips))

    # 4 e 5. Corte e render de cada clipe
    n = len(clips)
    prog.etapa("cortando")
    for k, c in enumerate(clips):
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()
        _cortar_so(pid, c["id"], transcricao, lambda p, k=k: prog((k + p) / n, f"Clipe {k + 1} de {n}"), cancelado)
    prog.etapa("legendando")
    for k, c in enumerate(clips):
        renderizar_clip(pid, c["id"], transcricao, lambda p, k=k: prog((k + p) / n, f"Clipe {k + 1} de {n}"), cancelado)

    prog.finalizar()
    custo = sum(h["custo"] for h in custos.resumo()["historico"] if h.get("projeto") == pid)
    return projetos.atualizar(pid, lambda m: m.update(status="pronto", custo=round(custo, 5), terminado_em=time.time()))


def _cortar_so(pid, cid, transcricao, progresso, cancelado):
    """Faz só o corte (etapa 'Cortando'); o render reaproveita o arquivo."""
    meta = projetos.ler(pid)
    clip = projetos.clip(meta, cid)
    cfg = config_clip(meta, clip)
    palavras = _palavras_editadas(transcricao, clip)
    if cfg["remover_silencios"]:
        trechos = ef.intervalos_de_fala(palavras, clip["inicio"], clip["fim"])
    else:
        trechos = [(clip["inicio"], clip["fim"])]
    corte = projetos.pasta(pid) / "tmp" / f"{cid}_corte.mp4"
    ef.cortar(meta["video"], trechos, corte, normalizar=cfg["normalizar"], musica=cfg["musica"],
              progresso=progresso, cancelado=cancelado)
    assinatura = repr((trechos, cfg["normalizar"], cfg["musica"]))
    projetos.atualizar(pid, lambda m: projetos.clip(m, cid).update(corte_assinatura=assinatura, status="cortado"))


# ================================================================ ações sobre clipes prontos

def regenerar_clip(pid: str, cid: str, progresso=None, cancelado=None) -> dict:
    """Troca o clipe por OUTRO momento do vídeo (que ainda não virou clipe)."""
    meta = projetos.ler(pid)
    plano = PlanoEdicao.model_validate(meta["plano"])
    transcricao = tr.transcrever(meta["video"])
    ocupados = [(c["inicio"], c["fim"]) for c in meta["clips"]] + meta.get("descartados", [])
    if meta["modo"] == "gameplay":
        analise = analise_audio.analisar(meta["video"])
        novos = _cortes_gameplay(meta["video"], transcricao, analise, plano, pid, excluir=ocupados, quantidade=1)
    else:
        novos = _cortes_falado(transcricao, plano, pid, excluir=ocupados, quantidade=1)
    if not novos:
        raise ValueError("Não encontrei outro trecho bom que ainda não tenha virado clipe.")
    novo = _novo_clip(cid, novos[0])

    def f(m):
        antigo = projetos.clip(m, cid)
        m.setdefault("descartados", []).append((antigo["inicio"], antigo["fim"]))
        novo["config"] = antigo.get("config", {})  # mantém as preferências visuais
        m["clips"] = [novo if c["id"] == cid else c for c in m["clips"]]
    projetos.atualizar(pid, f)
    return renderizar_clip(pid, cid, transcricao, progresso, cancelado)


def aplicar_ajuste(pid: str, pedido: str, cids: list[str], progresso=None, cancelado=None) -> dict:
    """Pedido em linguagem natural aplicado aos clipes selecionados."""
    meta = projetos.ler(pid)
    selecionados = [c for c in meta["clips"] if c["id"] in cids]
    try:
        ajuste = llm.interpretar_ajuste(pedido, selecionados, pid)
    except llm.ErroClaude as e:
        _claude_falhou(pid, e)
        ajuste = local.interpretar_ajuste(pedido, selecionados)
    transcricao = tr.transcrever(meta["video"])

    def f(m):
        for c in m["clips"]:
            if c["id"] not in cids:
                continue
            cfg = c.setdefault("config", {})
            mapa = {"cor_legenda": "cor", "preset": "preset", "estilo_legenda": "estilo", "legenda_ativa": "legenda_ativa",
                    "titulo_ativo": "titulo_ativo", "zoom_em_enfase": "zoom", "remover_silencios": "remover_silencios",
                    "normalizar_audio": "normalizar", "formato": "formato"}
            for campo, chave in mapa.items():
                valor = getattr(ajuste, campo)
                if valor is not None:
                    cfg[chave] = valor
            if ajuste.novo_titulo:
                c["titulo"] = ajuste.novo_titulo
            if ajuste.duracao_alvo:
                c["inicio"], c["fim"] = _nova_duracao(c, ajuste.duracao_alvo, transcricao, m["duracao_video"])
            c["status"] = "fila"
    projetos.atualizar(pid, f)
    for k, cid in enumerate(cids):
        renderizar_clip(pid, cid, transcricao,
                        (lambda p, k=k: progresso((k + p) / len(cids))) if progresso else None, cancelado)
    return {"ajuste": ajuste.model_dump(), "nao_atendido": ajuste.nao_atendido}


def _nova_duracao(clip: dict, alvo: float, transcricao: dict, duracao_video: float) -> tuple[float, float]:
    """Mantém o início (o gancho) e procura um fim de frase perto da nova duração.
    No gameplay mantém o pico dentro do clipe."""
    inicio = clip["inicio"]
    if clip.get("pico") is not None and not transcricao["palavras"]:
        inicio = max(0.0, clip["pico"] - alvo * 0.6)
        return round(inicio, 2), round(min(duracao_video, inicio + alvo), 2)
    candidatas = [w for w in transcricao["palavras"] if w["f"] > inicio and w["f"] - inicio <= alvo * 1.1]
    frases = [w for w in candidatas if w["p"].rstrip().endswith((".", "!", "?")) and w["f"] - inicio >= alvo * 0.7]
    escolhida = (frases or candidatas or [None])[-1]
    fim = escolhida["f"] + 0.25 if escolhida else inicio + alvo
    return round(inicio, 2), round(min(duracao_video, fim), 2)
