"""
Gadosso Edit como app de PC: dois cliques no atalho e ele
  1. liga o servidor local (sem janela preta), se ainda não estiver no ar;
  2. abre a interface numa janela própria (Edge/Chrome em modo aplicativo: sem barra de endereço nem abas);
  3. fica com um ícone na bandeja do relógio: fechar a janela não para o processamento; pelo ícone dá para
     abrir de novo ou sair de vez; e o Windows avisa quando um projeto termina (ou dá erro).

Abrir o atalho de novo com o app já rodando só traz a janela de volta.
Roda com o pythonw.exe do ambiente do app (sem console).
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
# Instalado pelo instalador: <pasta>/app (codigo), <pasta>/venv e <pasta>/dados. Desenvolvimento: C:/opusfalso-dados
if os.environ.get("OPUSFALSO_DADOS"):
    DADOS = Path(os.environ["OPUSFALSO_DADOS"])
elif (RAIZ / "versao.txt").exists():
    DADOS = RAIZ.parent / "dados"
else:
    DADOS = Path(r"C:\opusfalso-dados")
PORTA = int(os.environ.get("CLIPADOR_PORTA", "8000"))
URL = f"http://127.0.0.1:{PORTA}"
PORTA_TRAVA = PORTA + 765  # só uma instância do lançador por vez
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

servidor: subprocess.Popen | None = None  # só é nosso se fomos nós que ligamos


def pedir(caminho: str, metodo: str = "GET", timeout: float = 3):
    req = urllib.request.Request(URL + caminho, method=metodo)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def no_ar() -> bool:
    try:
        pedir("/api/sistema", timeout=2)
        return True
    except Exception:
        return False


def ligar_servidor() -> None:
    global servidor
    DADOS.mkdir(parents=True, exist_ok=True)
    # python.exe (não o pythonw) com o console ESCONDIDO: os programas que o servidor chama (ffmpeg, node,
    # nvidia-smi...) usam esse console invisível em vez de abrir, cada um, uma janela preta piscando
    python = Path(sys.executable).with_name("python.exe")
    servidor = subprocess.Popen(
        [str(python), "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", str(PORTA), "--no-access-log"],
        cwd=str(BACKEND), stdout=open(DADOS / "api.log", "ab"), stderr=open(DADOS / "api_err.log", "ab"),
        env={**os.environ, "OPUSFALSO_DADOS": str(DADOS)}, creationflags=SEM_JANELA)


def esperar_servidor(limite: float = 90) -> bool:
    fim = time.time() + limite
    while time.time() < fim:
        if no_ar():
            return True
        if servidor is not None and servidor.poll() is not None:
            return False  # o servidor caiu ao ligar (veja api_err.log)
        time.sleep(0.5)
    return False


def navegador_app() -> str | None:
    for base in (os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("PROGRAMFILES", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = Path(base) / rel
            if p.exists():
                return str(p)
    return None


def abrir_janela(*_):
    exe = navegador_app()
    if not exe:
        webbrowser.open(URL)
        return
    subprocess.Popen([exe, f"--app={URL}", f"--user-data-dir={DADOS / 'janela'}", "--window-size=1440,900",
                      "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
                     creationflags=SEM_JANELA)


def sair(icone, *_):
    """Desliga o servidor (o que estiver processando pode ser continuado depois, de onde parou)."""
    try:
        pedir("/api/sistema/desligar", "POST")
    except Exception:
        pass
    if servidor is not None and servidor.poll() is None:
        time.sleep(1.5)
        if servidor.poll() is None:
            servidor.kill()
    icone.stop()


def versao_local() -> dict | None:
    """versao.txt é escrito pelo instalador (repo, ramo, sha). Sem ele (instalação de desenvolvimento), não
    procura atualização."""
    try:
        return json.loads((RAIZ / "versao.txt").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


nova_versao = {"disponivel": False}


def procurar_atualizacao(icone) -> None:
    v = versao_local()
    if not v or not v.get("sha") or v["sha"] == "desconhecida":
        return
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{v['repo']}/commits/{v.get('ramo', 'main')}",
                                     headers={"User-Agent": "Clipador"})
        with urllib.request.urlopen(req, timeout=10) as r:
            remoto = json.loads(r.read())
    except Exception:
        return  # sem internet: tenta na próxima abertura
    if remoto.get("sha") and remoto["sha"] != v["sha"]:
        nova_versao["disponivel"] = True
        icone.update_menu()
        mensagem = (remoto.get("commit", {}).get("message") or "").splitlines()[0][:80]
        icone.notify(f"Nova versão do Gadosso Edit: {mensagem}. Clique no ícone > Atualizar.", "Gadosso Edit")


def atualizar(icone, *_):
    """Desliga o servidor, roda o instalador em modo atualização (numa janela, para ver o andamento) e sai;
    o instalador abre o app de novo no fim."""
    instalador = RAIZ / "instalador" / "instalar.ps1"
    v = versao_local() or {}
    try:
        pedir("/api/sistema/desligar", "POST")
    except Exception:
        pass
    destino = RAIZ.parent  # %LOCALAPPDATA%\Clipador (app, venv, dados)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(instalador), "-Atualizar",
                      "-Destino", str(destino), "-Repo", v.get("repo", "PedroOfelicio/opusfalso"),
                      "-Ramo", v.get("ramo", "main")], creationflags=subprocess.CREATE_NEW_CONSOLE)
    icone.stop()


def vigiar(icone) -> None:
    """Avisa (notificação do Windows) quando um projeto termina ou dá erro, e mostra o andamento na dica do ícone."""
    anteriores: dict[str, str] = {}
    while True:
        try:
            projetos = pedir("/api/projetos")
            ativos = []
            for p in projetos:
                antes, agora = anteriores.get(p["id"]), p["status"]
                if antes in ("fila", "processando") and agora != antes:
                    nome = p.get("nome", "Projeto")[:60]
                    if agora == "pronto":
                        n = p.get("num_clips") if p.get("tipo") != "longo" else None
                        icone.notify(f"{nome}: pronto" + (f" ({n} clipes)" if n else ""), "Gadosso Edit")
                    elif agora == "erro":
                        icone.notify(f"{nome}: deu erro. Abra o app para tentar de novo.", "Gadosso Edit")
                anteriores[p["id"]] = agora
                if agora == "processando":
                    ativos.append(f"{p.get('nome', '')[:30]} {round((p.get('progresso') or 0) * 100)}%")
            icone.title = "Gadosso Edit" + (f" - processando: {', '.join(ativos)}" if ativos else "")
        except Exception:
            icone.title = "Gadosso Edit (servidor fora do ar)"
        time.sleep(5)


def main():
    try:
        trava = socket.socket()
        trava.bind(("127.0.0.1", PORTA_TRAVA))  # fica aberta enquanto o lançador roda
    except OSError:
        abrir_janela()  # já tem um Gadosso Edit rodando: só abre a janela
        return

    import pystray
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import icone_janela
    icone = pystray.Icon("Gadosso Edit", Image.open(Path(__file__).with_name("icone_bandeja.png")), "Gadosso Edit (ligando...)",
                         menu=pystray.Menu(pystray.MenuItem("Abrir o Gadosso Edit", abrir_janela, default=True),
                                           pystray.MenuItem("Atualizar o Gadosso Edit", atualizar,
                                                            visible=lambda _: nova_versao["disponivel"]),
                                           pystray.MenuItem("Sair (desliga o servidor)", sair)))

    def iniciar(icone):
        icone.visible = True
        if not no_ar():
            ligar_servidor()
            if not esperar_servidor():
                icone.notify(f"Não consegui ligar o servidor. Veja {DADOS / 'api_err.log'}", "Gadosso Edit")
                return
        abrir_janela()
        threading.Thread(target=icone_janela.vigiar, daemon=True).start()  # ícone nítido na barra de tarefas
        threading.Thread(target=vigiar, args=(icone,), daemon=True).start()
        threading.Thread(target=procurar_atualizacao, args=(icone,), daemon=True).start()

    icone.run(setup=iniciar)
    trava.close()


if __name__ == "__main__":
    main()
