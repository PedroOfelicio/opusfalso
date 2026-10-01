"""
Espaço em disco do app.

- Vídeos enviados pela interface ficam em DADOS/videos/<hash>.<ext>: o mesmo vídeo enviado de novo não
  ocupa espaço outra vez (antes cada projeto guardava a própria cópia em projetos/<id>/original.<ext>).
- `resumo()` diz quanto cada parte ocupa e quanto dá para liberar.
- `juntar_repetidos()` troca as cópias antigas repetidas por um arquivo só (compara byte a byte antes).
- `limpar_temporarios()` apaga cortes intermediários, blocos em cache, prévias e quadros (tudo é refeito
  sozinho quando precisar; só o próximo render/remontagem fica mais lento).
"""
import filecmp
import logging
import os
import shutil
import uuid
from pathlib import Path

import config
import projetos
import transcricao as tr

log = logging.getLogger("armazenamento")

PASTA_VIDEOS = config.DADOS / "videos"
GB = 1024 ** 3
MINIMO_LIVRE = 2 * GB    # abaixo disso nem começa (render longo precisa de espaço)
ALERTA_LIVRE = 5 * GB


def tamanho(caminho: Path) -> int:
    caminho = Path(caminho)
    if not caminho.exists():
        return 0
    if caminho.is_file():
        return caminho.stat().st_size
    total = 0
    for raiz, _, arquivos in os.walk(caminho):
        for nome in arquivos:
            try:
                total += os.path.getsize(os.path.join(raiz, nome))
            except OSError:
                pass
    return total


def livre() -> int:
    return shutil.disk_usage(config.DADOS).free


def _copia_antiga(meta: dict) -> Path | None:
    """Cópia do vídeo dentro da pasta do próprio projeto (jeito antigo de guardar uploads)."""
    video = Path(meta.get("video") or "")
    if meta.get("video_copiado") and video.is_file() and video.parent == projetos.pasta(meta["id"]):
        return video
    return None


def guardar_envio(temporario: Path, extensao: str) -> Path:
    """Guarda um vídeo recém-enviado pelo conteúdo. Se o mesmo vídeo já existe, reaproveita e apaga o novo."""
    PASTA_VIDEOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_VIDEOS / f"{tr.hash_arquivo(temporario)}{extensao.lower()}"
    if destino.exists():
        if destino.stat().st_size == temporario.stat().st_size and filecmp.cmp(destino, temporario, shallow=False):
            temporario.unlink()
            log.info("Vídeo já estava guardado: reaproveitando %s", destino.name)
            return destino
        destino = PASTA_VIDEOS / f"{destino.stem}_{uuid.uuid4().hex[:6]}{extensao.lower()}"  # colisão de hash
    os.replace(temporario, destino)
    return destino


def em_uso(video: Path, exceto: str | None = None) -> bool:
    video = Path(video)
    return any(Path(m.get("video") or "") == video for m in projetos.listar() if m["id"] != exceto)


def resumo() -> dict:
    metas = projetos.listar()
    antigos = [v for v in (_copia_antiga(m) for m in metas) if v]
    temporarios = sum(tamanho(projetos.pasta(m["id"]) / "tmp") for m in metas)
    temporarios += tamanho(config.DADOS / "remotion_public" / "clips")
    # quanto sai juntando as cópias repetidas (mesmo tamanho e mesmo hash)
    grupos: dict[tuple, list[Path]] = {}
    for v in antigos + [p for p in PASTA_VIDEOS.glob("*") if p.is_file()] if PASTA_VIDEOS.exists() else antigos:
        try:
            grupos.setdefault((v.stat().st_size, tr.hash_arquivo(v)), []).append(v)
        except OSError:
            pass
    repetidos = sum(chave[0] * (len(lista) - 1) for chave, lista in grupos.items() if len(lista) > 1)
    uso = shutil.disk_usage(config.DADOS)
    return {
        "livre": uso.free, "total": uso.total, "pasta": str(config.DADOS),
        "videos": sum(v.stat().st_size for v in antigos) + tamanho(PASTA_VIDEOS),
        "temporarios": temporarios, "saidas": tamanho(config.pasta_saida()),
        "modelos": tamanho(config.PASTA_MODELOS), "repetidos": repetidos,
    }


def juntar_repetidos(ocupados: set[str]) -> int:
    """Move as cópias antigas para DADOS/videos (uma por conteúdo) e aponta os projetos para lá.
    Cópias iguais (comparadas byte a byte) são apagadas. Devolve os bytes liberados."""
    PASTA_VIDEOS.mkdir(parents=True, exist_ok=True)
    liberado = 0
    for meta in projetos.listar():
        video = _copia_antiga(meta)
        if not video or meta["id"] in ocupados or meta["status"] in ("fila", "processando"):
            continue
        destino = PASTA_VIDEOS / f"{tr.hash_arquivo(video)}{video.suffix.lower()}"
        try:
            if destino.exists():
                if destino.stat().st_size != video.stat().st_size or not filecmp.cmp(destino, video, shallow=False):
                    continue
                projetos.atualizar(meta["id"], lambda m, d=str(destino): m.update(video=d))
                tamanho_video = video.stat().st_size
                video.unlink()
                liberado += tamanho_video
            else:
                os.replace(video, destino)  # mesmo disco: só muda de pasta
                projetos.atualizar(meta["id"], lambda m, d=str(destino): m.update(video=d))
        except OSError as e:  # arquivo aberto (tocando em algum player): fica para a próxima
            log.warning("Não deu para mover %s: %s", video, e)
    log.info("Vídeos repetidos: %.2f GB liberados", liberado / GB)
    return liberado


def limpar_temporarios(ocupados: set[str]) -> int:
    """Apaga os temporários dos projetos parados. Tudo é refeito quando precisar."""
    liberado = 0
    for meta in projetos.listar():
        rodando = meta["status"] in ("fila", "processando") or any(
            c.get("status") in ("fila", "renderizando", "cortado") for c in meta.get("clips", []))
        if meta["id"] in ocupados or rodando:
            continue
        tmp = projetos.pasta(meta["id"]) / "tmp"
        liberado += tamanho(tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(exist_ok=True)
    if not ocupados:
        clips = config.DADOS / "remotion_public" / "clips"
        liberado += tamanho(clips)
        shutil.rmtree(clips, ignore_errors=True)
    log.info("Temporários: %.2f GB liberados", liberado / GB)
    return liberado
