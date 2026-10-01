"""
Biblioteca local de áudio (músicas e efeitos sonoros).

    DADOS/audio/musica/<clima>/*.mp3   ex.: musica/energetica/batida.mp3
    DADOS/audio/efeitos/<tipo>/*.mp3   ex.: efeitos/whoosh/whoosh1.wav

O usuário só solta os arquivos nas pastas; o app escolhe sozinho. A escolha é
estável por clipe (mesma semente = mesma faixa), então re-renderizar não troca a música.
"""
import hashlib
import json
import logging
import os
import shutil
import threading
import urllib.request
from pathlib import Path

import config
from modelos import CLIMAS

log = logging.getLogger("audio")

PASTA_AUDIO = config.DADOS / "audio"
PASTA_MUSICA = PASTA_AUDIO / "musica"
PASTA_EFEITOS = PASTA_AUDIO / "efeitos"
EXTENSOES = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}

# Tipo de efeito -> onde entra no clipe
EFEITOS = {
    "whoosh": "entrada do título gancho",
    "impacto": "picos do gameplay (kills, explosões)",
    "pop": "zoom nas palavras de ênfase",
}

LEIAME = """Biblioteca de áudio do Clipador
================================

Solte arquivos de áudio (mp3, wav, m4a, ogg) nas pastas abaixo. O app escolhe sozinho.

musica\\<clima>\\   músicas de fundo. O Claude escolhe o clima conforme o trecho.
{climas}

efeitos\\<tipo>\\   efeitos sonoros curtos (até ~2 s são usados).
{efeitos}

Pacote inicial: em Configurações > Biblioteca de áudio, "Baixar o pacote grátis" coloca 16 músicas
de domínio público (CC0) nas pastas de clima. Os créditos ficam em musica\\CREDITOS.txt.

Fontes grátis sem direitos autorais: Pixabay (pixabay.com/music e /sound-effects),
YouTube Audio Library (YouTube Studio), Freesound.org (confira a licença de cada som).
Evite música famosa: TikTok/Reels/Shorts silenciam ou derrubam o vídeo.
"""


def preparar() -> None:
    """Cria as pastas vazias e o LEIAME.txt."""
    for clima in CLIMAS:
        (PASTA_MUSICA / clima).mkdir(parents=True, exist_ok=True)
    for tipo in EFEITOS:
        pasta = PASTA_EFEITOS / tipo
        pasta.mkdir(parents=True, exist_ok=True)
        # Efeitos de fábrica (sintetizados, sem direitos autorais) só entram em pasta vazia:
        # quem colocar os próprios arquivos pode apagar os "padrao_*"
        origem = config.RECURSOS / "efeitos" / tipo
        if origem.exists() and not _arquivos(pasta):
            for arq in _arquivos(origem):
                shutil.copy2(arq, pasta / arq.name)
    leiame = PASTA_AUDIO / "LEIAME.txt"
    if not leiame.exists():
        leiame.write_text(LEIAME.format(
            climas="\n".join(f"    {c:<11} {d}" for c, d in CLIMAS.items()),
            efeitos="\n".join(f"    {t:<11} {d}" for t, d in EFEITOS.items()),
        ), encoding="utf-8")


def _arquivos(pasta: Path) -> list[Path]:
    if not pasta.exists():
        return []
    return sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in EXTENSOES)


def _sortear(opcoes: list[Path], semente: str) -> Path | None:
    if not opcoes:
        return None
    n = int(hashlib.md5(semente.encode("utf-8")).hexdigest(), 16)
    return opcoes[n % len(opcoes)]


def musicas(clima: str | None = None) -> list[Path]:
    if clima:
        return _arquivos(PASTA_MUSICA / clima)
    return [p for c in CLIMAS for p in _arquivos(PASTA_MUSICA / c)]


def escolher_musica(clima: str | None, semente: str) -> Path | None:
    """Faixa do clima pedido; se a pasta estiver vazia, qualquer faixa da biblioteca."""
    return _sortear(musicas(clima) or musicas(), semente)


def sequencia_musicas(clima: str | None, semente: str) -> list[Path]:
    """Todas as faixas do clima, começando por uma sorteada pela semente (para trocar a cada capítulo)."""
    opcoes = musicas(clima) or musicas()
    if not opcoes:
        return []
    k = int(hashlib.md5(semente.encode("utf-8")).hexdigest(), 16) % len(opcoes)
    return opcoes[k:] + opcoes[:k]


def escolher_efeito(tipo: str, semente: str) -> Path | None:
    return _sortear(_arquivos(PASTA_EFEITOS / tipo), semente)


def resumo() -> dict:
    faltando = pacote_faltando()
    do_pacote = {(f["clima"], f["arquivo"]): f for f in _pacote()}
    return {
        "pasta": str(PASTA_AUDIO),
        "musicas": {c: [str(p) for p in _arquivos(PASTA_MUSICA / c)] for c in CLIMAS},
        # título e artista das faixas do pacote (as do usuário aparecem pelo nome do arquivo)
        "detalhes": {str(PASTA_MUSICA / c / n): {"titulo": f["titulo"], "artista": f["artista"]}
                     for (c, n), f in do_pacote.items() if (PASTA_MUSICA / c / n).exists()},
        "efeitos": {t: len(_arquivos(PASTA_EFEITOS / t)) for t in EFEITOS},
        "pacote": {**estado_pacote, "erros": list(estado_pacote["erros"]), "faltando": len(faltando),
                   "total_pacote": len(_pacote()), "bytes": sum(f.get("bytes", 0) for f in faltando)},
    }


# ---------------------------------------------------------------- pacote inicial (músicas CC0)

PACOTE = config.RECURSOS / "pacote_musicas.json"
estado_pacote = {"baixando": False, "feitos": 0, "total": 0, "erros": []}
_trava_pacote = threading.Lock()


def _pacote() -> list[dict]:
    """Faixas escolhidas a dedo no Free Music Archive, todas CC0 (domínio público: dá para usar em vídeo
    monetizado, sem pedir licença nem dar crédito). Licença conferida na página de cada faixa."""
    dados = config.ler_json(PACOTE, {}) or {}
    return [f for f in dados.get("faixas", []) if f.get("clima") in CLIMAS]


_ARQ_RECUSADAS = PASTA_AUDIO / ".pacote_removidas.json"


def pacote_faltando() -> list[dict]:
    """Faixas do pacote que não estão na biblioteca (menos as que o usuário apagou de propósito)."""
    recusadas = set(config.ler_json(_ARQ_RECUSADAS, []) or [])
    return [f for f in _pacote() if not (PASTA_MUSICA / f["clima"] / f["arquivo"]).exists()
            and f["arquivo"] not in recusadas]


def arquivo_da_biblioteca(caminho: str) -> Path | None:
    """O caminho só vale se for um arquivo de áudio DENTRO da biblioteca (nada de servir/apagar outro arquivo)."""
    try:
        p = Path(caminho).resolve()
        base = PASTA_AUDIO.resolve()
    except (OSError, ValueError):
        return None
    if base in p.parents and p.is_file() and p.suffix.lower() in EXTENSOES:
        return p
    return None


def excluir(caminho: str) -> bool:
    p = arquivo_da_biblioteca(caminho)
    if not p:
        return False
    p.unlink()
    if any(f["arquivo"] == p.name for f in _pacote()):  # não oferece baixar de novo o que foi apagado
        recusadas = set(config.ler_json(_ARQ_RECUSADAS, []) or []) | {p.name}
        config.gravar_json(_ARQ_RECUSADAS, sorted(recusadas))
    return True


def baixar_pacote() -> bool:
    """Baixa em segundo plano as faixas do pacote que ainda não estão na biblioteca. False se já está baixando."""
    with _trava_pacote:
        if estado_pacote["baixando"]:
            return False
        faltando = pacote_faltando()
        estado_pacote.update(baixando=True, feitos=0, total=len(faltando), erros=[])
    threading.Thread(target=_baixar, args=(faltando,), daemon=True, name="pacote-musicas").start()
    return True


def _baixar(faixas: list[dict]) -> None:
    try:
        for f in faixas:
            destino = PASTA_MUSICA / f["clima"] / f["arquivo"]
            parcial = destino.with_name(destino.name + ".part")  # .part não aparece na biblioteca
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                pedido = urllib.request.Request(f["url"], headers={"User-Agent": "Mozilla/5.0 (Clipador)"})
                with urllib.request.urlopen(pedido, timeout=60) as resposta, open(parcial, "wb") as saida:
                    shutil.copyfileobj(resposta, saida, 1024 * 1024)
                if parcial.stat().st_size < 200_000:
                    raise OSError("arquivo veio incompleto")
                os.replace(parcial, destino)
            except OSError as e:  # erros de rede (URLError) também são OSError
                parcial.unlink(missing_ok=True)
                estado_pacote["erros"].append(f"{f['titulo']}: {e}")
                log.warning("Pacote de músicas: falhou %s (%s)", f["titulo"], e)
            estado_pacote["feitos"] += 1
        _escrever_creditos()
    finally:
        estado_pacote["baixando"] = False


def _escrever_creditos() -> None:
    presentes = [f for f in _pacote() if (PASTA_MUSICA / f["clima"] / f["arquivo"]).exists()]
    if not presentes:
        return
    linhas = ["Músicas do pacote inicial do Clipador", "=" * 37, "",
              "Todas em CC0 1.0 (domínio público): podem ser usadas em qualquer vídeo, inclusive monetizado,",
              "sem pedir licença e sem dar crédito. Créditos aos artistas, por gentileza:", ""]
    for f in presentes:
        linhas.append(f"{f['clima']}\\{f['arquivo']}")
        linhas.append(f"    \"{f['titulo']}\" de {f['artista']} (álbum {f['album']}), {f['licenca']}")
        linhas.append(f"    {f['pagina']}")
    (PASTA_MUSICA / "CREDITOS.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
