"""
Clipador como app de PC: dois cliques no atalho e ele
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
DADOS = Path(os.environ.get("OPUSFALSO_DADOS", r"C:\opusfalso-dados"))
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
        creationflags=SEM_JANELA)


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
                        icone.notify(f"{nome}: pronto" + (f" ({n} clipes)" if n else ""), "Clipador")
                    elif agora == "erro":
                        icone.notify(f"{nome}: deu erro. Abra o app para tentar de novo.", "Clipador")
                anteriores[p["id"]] = agora
                if agora == "processando":
                    ativos.append(f"{p.get('nome', '')[:30]} {round((p.get('progresso') or 0) * 100)}%")
            icone.title = "Clipador" + (f" - processando: {', '.join(ativos)}" if ativos else "")
        except Exception:
            icone.title = "Clipador (servidor fora do ar)"
        time.sleep(5)


def main():
    try:
        trava = socket.socket()
        trava.bind(("127.0.0.1", PORTA_TRAVA))  # fica aberta enquanto o lançador roda
    except OSError:
        abrir_janela()  # já tem um Clipador rodando: só abre a janela
        return

    import pystray
    from PIL import Image
    icone = pystray.Icon("Clipador", Image.open(Path(__file__).with_name("icone_bandeja.png")), "Clipador (ligando...)",
                         menu=pystray.Menu(pystray.MenuItem("Abrir o Clipador", abrir_janela, default=True),
                                           pystray.MenuItem("Sair (desliga o servidor)", sair)))

    def iniciar(icone):
        icone.visible = True
        if not no_ar():
            ligar_servidor()
            if not esperar_servidor():
                icone.notify(f"Não consegui ligar o servidor. Veja {DADOS / 'api_err.log'}", "Clipador")
                return
        abrir_janela()
        threading.Thread(target=vigiar, args=(icone,), daemon=True).start()

    icone.run(setup=iniciar)
    trava.close()


if __name__ == "__main__":
    main()
