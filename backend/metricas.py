"""
Métricas do canal do YouTube, de dois jeitos:
- Chave de API (grátis, sem login): os números PÚBLICOS da YouTube Data API v3 (inscritos, views, vídeos e, por vídeo,
  views, likes e comentários).
- Login com o Google (OAuth, cliente "App para computador" do Google Cloud): tudo isso e mais a YouTube Analytics API
  (views, tempo assistido e inscritos por dia de verdade e, por vídeo, retenção, duração média e inscritos ganhos).
  O próprio usuário entra na conta no navegador; o app só guarda o token em DADOS/youtube_oauth_token.json.

A Data API só dá o total de agora: cada atualização guarda um retrato do dia (o último do dia vale) e, sem login, as
views por dia saem da diferença entre retratos. O servidor atualiza sozinho a cada 3 h enquanto está aberto.

Cada vídeo do canal é ligado ao item da aba Prontos de mesmo título (o arquivo sobe com nome = título), para saber
quais cortes do app já estão no ar e quanto cada um rendeu.

Cota da Data API: 1 unidade por chamada; um canal de 500 vídeos gasta ~21 por atualização (a grátis é 10.000 por dia).
Tudo em DADOS/metricas.json.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import postagem

log = logging.getLogger("metricas")

ARQ = config.DADOS / "metricas.json"
ARQ_CLIENTE = config.DADOS / "youtube_oauth_cliente.json"
ARQ_TOKEN = config.DADOS / "youtube_oauth_token.json"
API = "https://www.googleapis.com/youtube/v3/"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
ESCOPOS = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"
PERIODOS_VIDEO = (7, 30, 90, 0)  # dias do relatório por vídeo (0 = desde a criação do canal)
MAX_VIDEOS = 500            # os mais recentes; o resto fica de fora (e não gasta cota)
DIAS_HISTORICO = 400
ATUALIZAR_A_CADA = 3 * 3600
_trava = threading.Lock()


class ErroYoutube(RuntimeError):
    pass


def chave() -> str:
    return (config.carregar().get("youtube_key") or "").strip()


def _ler() -> dict:
    d = config.ler_json(ARQ, {}) or {}
    d.setdefault("canal", None)
    d.setdefault("videos", {})
    d.setdefault("historico", {})   # "AAAA-MM-DD" -> {"inscritos", "views", "videos": {id: views}}
    d.setdefault("atualizado_em", None)
    d.setdefault("erro", None)
    return d


def _get(rota: str, **params) -> dict:
    """GET na Data API (rota relativa) ou numa URL completa (Analytics). Com login usa o token; senão, a chave."""
    cabecalhos = {"Accept": "application/json"}
    token = _token_acesso()
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    else:
        params["key"] = chave()
    url = (rota if rota.startswith("http") else API + rota) + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cabecalhos), timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            erro = json.loads(e.read().decode("utf-8"))["error"]
            motivo = (erro.get("errors") or [{}])[0].get("reason", "")
            texto = erro.get("message", "")
        except Exception:
            motivo, texto = "", str(e)
        if motivo == "keyInvalid" or "API key not valid" in texto:
            raise ErroYoutube("Chave do YouTube inválida. Confira em Métricas > Chave.")
        if motivo == "accessNotConfigured" or "has not been used" in texto or "is disabled" in texto:
            nome = "YouTube Analytics API" if "youtubeanalytics" in url else "YouTube Data API v3"
            raise ErroYoutube(f"A {nome} não está ativada no projeto do Google Cloud (APIs e serviços > Biblioteca).")
        if motivo in ("quotaExceeded", "dailyLimitExceeded"):
            raise ErroYoutube("Cota diária da API do YouTube esgotada. Volta amanhã.")
        if e.code == 401:
            raise ErroYoutube("O Google recusou o login (token vencido ou revogado). Conecte de novo em Métricas.")
        raise ErroYoutube(f"Erro da API do YouTube ({e.code}): {texto[:200]}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ErroYoutube(f"Sem conexão com a API do YouTube: {e}")


def segundos(duracao_iso: str) -> int:
    """'PT1H2M5S' -> 3725."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duracao_iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def atualizar() -> dict:
    """Busca o canal e os vídeos (e, com login, o Analytics) e grava o retrato de hoje."""
    logado = conectado()
    if not chave() and not logado:
        raise ErroYoutube("Falta a chave da YouTube Data API ou o login com o Google.")
    canal_id = postagem._ler()["canal"].get("channel_id")
    if not canal_id and not logado:
        raise ErroYoutube("Falta o link do canal (cole na aba Prontos ou aqui em Métricas).")
    with _trava:
        filtro = {"mine": "true"} if logado else {"id": canal_id}
        itens = _get("channels", part="snippet,statistics,contentDetails", **filtro).get("items") or []
        if not itens:
            raise ErroYoutube("Canal não encontrado. Confira o link (ou entre com a conta dona do canal).")
        ch = itens[0]
        canal_id = ch["id"]
        if logado and postagem._ler()["canal"].get("channel_id") != canal_id:  # o canal do login vale também no Prontos
            postagem.salvar_canal(f"https://www.youtube.com/channel/{canal_id}")
        est = ch.get("statistics", {})
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        ids, pagina = [], None
        while len(ids) < MAX_VIDEOS:
            params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
            if pagina:
                params["pageToken"] = pagina
            r = _get("playlistItems", **params)
            ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
            pagina = r.get("nextPageToken")
            if not pagina:
                break
        videos = {}
        for k in range(0, len(ids), 50):
            for v in _get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[k:k + 50])).get("items", []):
                sn, st = v["snippet"], v.get("statistics", {})
                thumbs = sn.get("thumbnails", {})
                videos[v["id"]] = {
                    "titulo": sn.get("title", ""), "publicado": _ts(sn["publishedAt"]),
                    "duracao": segundos(v.get("contentDetails", {}).get("duration")),
                    "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                    "comentarios": int(st.get("commentCount", 0)),
                    "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
                }
        d = _ler()
        d["canal"] = {
            "id": canal_id, "nome": ch["snippet"].get("title", ""),
            "thumb": (ch["snippet"].get("thumbnails", {}).get("default") or {}).get("url"),
            "inscritos": int(est.get("subscriberCount", 0)), "inscritos_ocultos": bool(est.get("hiddenSubscriberCount")),
            "views": int(est.get("viewCount", 0)), "videos": int(est.get("videoCount", 0)),
        }
        d["videos"] = videos
        d["historico"][date.today().isoformat()] = {
            "inscritos": d["canal"]["inscritos"], "views": d["canal"]["views"],
            "videos": {i: v["views"] for i, v in videos.items()},
        }
        limite = (date.today() - timedelta(days=DIAS_HISTORICO)).isoformat()
        d["historico"] = {dia: r for dia, r in sorted(d["historico"].items()) if dia >= limite}
        d["atualizado_em"] = time.time()
        d["erro"] = None
        d["aviso_analytics"] = None
        if logado:
            try:
                d["analytics"] = _analytics()
            except ErroYoutube as e:  # a Data API funcionou: guarda o resto e avisa
                d["aviso_analytics"] = str(e)
        config.gravar_json(ARQ, d)
    log.info("Métricas: %s, %d inscritos, %d vídeos", d["canal"]["nome"], d["canal"]["inscritos"], len(videos))
    return d


def atualizar_se_preciso(forcar: bool = False) -> None:
    """Atualiza se passou do intervalo (ou se forçar). Erro não derruba nada: fica guardado para a tela mostrar."""
    d = _ler()
    if not conectado() and (not chave() or not postagem._ler()["canal"].get("channel_id")):
        return
    if not forcar and d["atualizado_em"] and time.time() - d["atualizado_em"] < ATUALIZAR_A_CADA:
        return
    try:
        atualizar()
    except ErroYoutube as e:
        d = _ler()
        d["erro"] = str(e)
        config.gravar_json(ARQ, d)
        if forcar:
            raise


def em_segundo_plano() -> None:
    """Retrato a cada 3 h enquanto o servidor estiver aberto (o histórico sem login depende disso)."""
    def laco():
        while True:
            try:
                atualizar_se_preciso()
            except Exception as e:
                log.warning("Métricas em segundo plano: %s", e)
            time.sleep(600)
    threading.Thread(target=laco, daemon=True, name="metricas").start()


# ================================================================ YouTube Analytics (só com login)

def _relatorio(**params) -> list[dict]:
    r = _get(ANALYTICS, ids="channel==MINE", **params)
    nomes = [c["name"] for c in r.get("columnHeaders", [])]
    return [dict(zip(nomes, linha)) for linha in r.get("rows") or []]


def _analytics() -> dict:
    """Por dia (último ano) e por vídeo em cada período. O Analytics atrasa ~2-3 dias."""
    hoje = date.today()
    por_dia = _relatorio(startDate=(hoje - timedelta(days=365)).isoformat(), endDate=hoje.isoformat(),
                         metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost", dimensions="day",
                         sort="day")
    metricas_video = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"
    por_video = {}
    for dias in PERIODOS_VIDEO:
        inicio = (hoje - timedelta(days=dias)).isoformat() if dias else "2005-04-23"
        linhas = _relatorio(startDate=inicio, endDate=hoje.isoformat(), metrics=metricas_video, dimensions="video",
                            sort="-views", maxResults=200)
        por_video[str(dias)] = {l["video"]: {k: v for k, v in l.items() if k != "video"} for l in linhas}
    return {"dias": por_dia, "videos": por_video, "em": time.time()}


# ================================================================ login com o Google (OAuth, cliente Desktop)

_pendentes: dict[str, tuple[str, str]] = {}  # state -> (code_verifier, redirect_uri)


def cliente() -> dict | None:
    return (config.ler_json(ARQ_CLIENTE, None) or {}).get("installed")


def salvar_cliente(caminho: str) -> None:
    """Copia o client_secret_....json (tipo "App para computador") baixado do Google Cloud para DADOS."""
    origem = Path(caminho.strip().strip('"'))
    try:
        d = json.loads(origem.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErroYoutube("Não consegui ler esse arquivo JSON.")
    if "installed" not in d:
        raise ErroYoutube('O cliente OAuth precisa ser do tipo "App para computador", não "Aplicativo da Web".')
    ARQ_CLIENTE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, ARQ_CLIENTE)


def conectado() -> bool:
    return bool((config.ler_json(ARQ_TOKEN, {}) or {}).get("refresh_token")) and cliente() is not None


def url_login(redirect_uri: str) -> str:
    c = cliente()
    if not c:
        raise ErroYoutube("Falta o arquivo do cliente OAuth (client_secret_....json).")
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    estado_oauth = secrets.token_urlsafe(16)
    _pendentes.clear()
    _pendentes[estado_oauth] = (verificador, redirect_uri)
    return c["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": ESCOPOS,
        "access_type": "offline", "prompt": "consent", "state": estado_oauth,
        "code_challenge": desafio, "code_challenge_method": "S256"})


def _post_token(dados: dict) -> dict:
    c = cliente()
    corpo = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"], **dados}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(c["token_uri"], data=corpo), timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            erro = json.loads(e.read().decode("utf-8"))
        except ValueError:
            erro = {}
        if erro.get("error") == "invalid_grant":
            ARQ_TOKEN.unlink(missing_ok=True)
            raise ErroYoutube("O login com o Google expirou (no modo Teste do Google Cloud ele vale 7 dias). "
                              "Conecte de novo em Métricas.")
        raise ErroYoutube(f"Erro no login com o Google: {erro.get('error_description') or erro.get('error') or e}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ErroYoutube(f"Sem conexão com o Google: {e}")


def concluir_login(codigo: str, estado_oauth: str) -> None:
    if estado_oauth not in _pendentes:
        raise ErroYoutube("Login fora de ordem: comece de novo pelo botão em Métricas.")
    verificador, redirect_uri = _pendentes.pop(estado_oauth)
    r = _post_token({"code": codigo, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                     "code_verifier": verificador})
    if not r.get("refresh_token"):
        raise ErroYoutube("O Google não devolveu o token de renovação. Tente conectar de novo.")
    config.gravar_json(ARQ_TOKEN, {"refresh_token": r["refresh_token"], "access_token": r["access_token"],
                                   "expira": time.time() + int(r.get("expires_in", 3600)) - 60, "em": time.time()})
    d = _ler()
    d["atualizado_em"] = None  # a próxima consulta já busca o Analytics
    config.gravar_json(ARQ, d)


def desconectar() -> None:
    ARQ_TOKEN.unlink(missing_ok=True)
    d = _ler()
    d.pop("analytics", None)
    d.pop("aviso_analytics", None)
    config.gravar_json(ARQ, d)


def _token_acesso() -> str | None:
    t = config.ler_json(ARQ_TOKEN, {}) or {}
    if not t.get("refresh_token") or cliente() is None:
        return None
    if time.time() < t.get("expira", 0):
        return t["access_token"]
    r = _post_token({"refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    t.update(access_token=r["access_token"], expira=time.time() + int(r.get("expires_in", 3600)) - 60)
    config.gravar_json(ARQ_TOKEN, t)
    return t["access_token"]


# ================================================================ ligação com a aba Prontos

def normalizar(titulo: str) -> str:
    """Título comparável: sem caixa, espaços e pontuação (o '?' vira '？' no nome do arquivo)."""
    return re.sub(r"[\W_]+", "", (titulo or "").lower())


def _do_app() -> dict[str, dict]:
    return {normalizar(i["titulo"]): i for i in postagem.itens() if i["titulo"]}


def marcar_publicados() -> int:
    """Marca como postados os itens da aba Prontos que já estão no canal (mesmo título). Devolve quantos."""
    do_app = _do_app()
    n = 0
    for v in _ler()["videos"].values():
        it = do_app.get(normalizar(v["titulo"]))
        if it and it["estado"] == "pendente":
            postagem.marcar(it["chave"], "postado")
            n += 1
    return n


# ================================================================ estado para a interface

def estado() -> dict:
    d = _ler()
    do_app = _do_app()
    dias = sorted(d["historico"])
    serie = [{"dia": dia, "inscritos": d["historico"][dia]["inscritos"], "views": d["historico"][dia]["views"]}
             for dia in dias]
    videos, pendentes_no_ar = [], 0
    for vid, v in d["videos"].items():
        it = do_app.get(normalizar(v["titulo"]))
        if it and it["estado"] == "pendente":
            pendentes_no_ar += 1
        # views de cada vídeo em cada retrato (para somar o ganho no período escolhido na tela)
        hist = {dia: d["historico"][dia]["videos"][vid] for dia in dias if vid in d["historico"][dia].get("videos", {})}
        videos.append({**v, "id": vid, "tipo": "short" if 0 < v["duracao"] <= 180 else "longo",
                       "url": f"https://www.youtube.com/watch?v={vid}" if v["duracao"] > 180 else f"https://youtube.com/shorts/{vid}",
                       "app": {"chave": it["chave"], "projeto": it["projeto"], "nota": it["nota"]} if it else None,
                       "historico": hist})
    videos.sort(key=lambda v: -v["publicado"])
    canal_prontos = postagem._ler()["canal"]
    return {"tem_chave": bool(chave()), "tem_cliente": cliente() is not None, "conectado": conectado(),
            "analytics": d.get("analytics"), "aviso_analytics": d.get("aviso_analytics"),
            "canal_link": canal_prontos.get("url", ""), "canal_id": canal_prontos.get("channel_id"),
            "canal": d["canal"], "serie": serie, "videos": videos, "atualizado_em": d["atualizado_em"],
            "erro": d["erro"], "pendentes_no_ar": pendentes_no_ar}
