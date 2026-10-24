"""
Vídeos por link (YouTube e os outros sites que o yt-dlp aceita), sem guardar o arquivo bruto.

O projeto guarda o link (`origem_url`) e o caminho onde o vídeo fica quando baixado
(DADOS/videos/links/<id do vídeo>.mp4). O vídeo é baixado na hora de processar e apagado quando
não há mais trabalho na fila para o projeto (opção `apagar_original`, ligada por padrão). Se depois
for preciso de novo (reexportar um clipe, revisar o vídeo longo), ele é baixado de novo pelo link.
"""
import logging
import re
import threading
from pathlib import Path

import armazenamento
import projetos
from config import Cancelado

log = logging.getLogger("youtube")

PASTA = armazenamento.PASTA_VIDEOS / "links"
ALTURA_MAX = 1080  # para clipe vertical e vídeo de YouTube, 1080p basta; 4K só ocuparia disco
_travas: dict[str, threading.Lock] = {}
_trava_geral = threading.Lock()


class ErroLink(RuntimeError):
    pass


class _Silencio:
    """O yt-dlp escreve os erros no terminal mesmo em modo quieto; aqui eles viram só a mensagem da exceção."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def e_link(texto: str) -> bool:
    return bool(re.match(r"^\s*https?://\S+\s*$", texto or ""))


def _opcoes(extra: dict | None = None) -> dict:
    return {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True, **(extra or {})}


def informacoes(url: str) -> dict:
    """Título, duração e id do vídeo, sem baixar (valida o link na hora de criar o projeto)."""
    import yt_dlp
    try:
        # extract_flat: numa playlist só lê o tipo, sem visitar cada vídeo (que levaria minutos)
        with yt_dlp.YoutubeDL(_opcoes({"extract_flat": "in_playlist", "logger": _Silencio()})) as ydl:
            info = ydl.extract_info(url.strip(), download=False)
    except yt_dlp.utils.DownloadError as e:
        raise ErroLink(_mensagem(e)) from e
    if info.get("_type") == "playlist":
        raise ErroLink("Esse link é de uma playlist: mande o link de um vídeo só.")
    if info.get("is_live"):
        raise ErroLink("A live ainda está no ar. Espere ela terminar (e o YouTube processar o vídeo) e mande o link de novo.")
    ident = re.sub(r"[^A-Za-z0-9_-]", "_", f"{info.get('extractor_key', 'video')}_{info['id']}")
    return {"titulo": info.get("title") or ident, "duracao": float(info.get("duration") or 0), "id": ident}


def _mensagem(e: Exception) -> str:
    texto = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    if "Private video" in texto or "privado" in texto.lower():
        return "O vídeo é privado. Deixe como público ou não listado para o app conseguir baixar."
    if "unavailable" in texto or "not available" in texto:
        return "O vídeo não existe ou está indisponível (confira o link)."
    if "Sign in to confirm" in texto:
        return "O YouTube pediu login para baixar esse vídeo (restrição de idade ou verificação de robô)."
    return f"Não consegui acessar o link: {texto[:300]}"


def caminho_local(info: dict) -> Path:
    return PASTA / f"{info['id']}.mp4"


def _trava(pid: str) -> threading.Lock:
    with _trava_geral:
        return _travas.setdefault(pid, threading.Lock())


def garantir_video(pid: str, progresso=None, cancelado=None) -> None:
    """Se o projeto veio de um link e o vídeo não está no disco, baixa (de novo)."""
    meta = projetos.ler(pid)
    if not meta or not meta.get("origem_url"):
        return
    destino = Path(meta["video"])
    with _trava(pid):
        if destino.exists():
            return
        log.info("Baixando %s", meta["origem_url"])
        baixar(meta["origem_url"], destino, progresso, cancelado)


def baixar(url: str, destino: Path, progresso=None, cancelado=None) -> Path:
    import yt_dlp
    destino.parent.mkdir(parents=True, exist_ok=True)

    def gancho(d):
        if cancelado is not None and cancelado.is_set():
            raise yt_dlp.utils.DownloadCancelled("cancelado")
        if progresso and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                # vídeo e áudio vêm separados: a fração é de cada parte, o suficiente para mostrar andamento
                progresso(min(1.0, d.get("downloaded_bytes", 0) / total),
                          f"Baixando do link: {d.get('downloaded_bytes', 0) / 1e6:.0f} de {total / 1e6:.0f} MB")

    opcoes = _opcoes({
        "format": (f"bv*[height<={ALTURA_MAX}][ext=mp4]+ba[ext=m4a]/b[height<={ALTURA_MAX}][ext=mp4]/"
                   f"bv*[height<={ALTURA_MAX}]+ba/b[height<={ALTURA_MAX}]/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(destino.with_suffix("")) + ".%(ext)s",
        "progress_hooks": [gancho],
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
        "logger": _Silencio(),
    })
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadCancelled:
        raise Cancelado()
    except yt_dlp.utils.DownloadError as e:
        if cancelado is not None and cancelado.is_set():
            raise Cancelado()
        raise ErroLink(_mensagem(e)) from e
    if not destino.exists():
        achados = [p for p in destino.parent.glob(destino.stem + ".*") if p.suffix not in (".part", ".ytdl")]
        if not achados:
            raise ErroLink("O download terminou, mas o arquivo não apareceu.")
        achados[0].replace(destino)
    log.info("Baixado: %s (%.0f MB)", destino.name, destino.stat().st_size / 1e6)
    return destino


def liberar_video(pid: str, pendentes: int = 0) -> None:
    """Apaga o vídeo baixado quando o projeto não tem mais trabalho na fila (só os vindos de link)."""
    meta = projetos.ler(pid)
    if not meta or not meta.get("origem_url") or meta.get("opcoes", {}).get("apagar_original") is False:
        return
    video = Path(meta["video"])
    if pendentes or video.parent != PASTA or not video.exists():
        return
    if armazenamento.em_uso(video, exceto=pid):
        return
    with _trava(pid):
        try:
            tamanho = video.stat().st_size
            video.unlink()
            log.info("Original apagado (%.0f MB): pode ser baixado de novo pelo link", tamanho / 1e6)
        except OSError as e:  # em uso (ex.: o navegador tocando o original): fica para a próxima
            log.warning("Não consegui apagar %s: %s", video.name, e)
