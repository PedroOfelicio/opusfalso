"""
Gera a demonstração estática (para a Vercel) a partir do servidor local rodando em :8000.

    1. cd frontend && set VITE_DEMO=1 && npx vite build --outDir dist-demo
    2. C:\\opusfalso-dados\\venv\\Scripts\\python scripts\\capturar_demo.py
    3. cd frontend\\dist-demo && vercel deploy --prod

Copia as respostas da API (GET) para dist-demo/demo/*.json, no nome que o modo demonstração do
frontend procura (api.js -> arquivoDemo), e os vídeos/imagens para dist-demo/demo/media, com os
vídeos reduzidos para 720p (a demo fica com poucas dezenas de MB). Nada sensível vai junto: a chave
da API e o workspace são apagados e só entram os projetos da lista VITRINE.
"""
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
SAIDA = Path(__file__).resolve().parent.parent / "frontend" / "dist-demo"

# id do projeto -> nome mostrado na demonstração
VITRINE = {
    "0647bda6a090": "Valorant: melhores jogadas (clipes curtos)",
    "704c1c5685e8": "Podcast sobre estudos (clipes curtos, voz sintética)",
    "d6bf6d6ff1c6": "Valorant: melhores momentos (vídeo longo)",
    "4f2e3fb1d0a3": "Podcast enxugado (vídeo longo, 5 erros de gravação plantados)",
}


def get(caminho: str) -> bytes:
    with urllib.request.urlopen(API + caminho, timeout=120) as r:
        return r.read()


def get_json(caminho: str):
    return json.loads(get(caminho))


def arquivo_demo(caminho: str) -> Path:
    """Mesmo nome que api.js (arquivoDemo) calcula no navegador."""
    rota, _, busca = caminho.partition("?")
    busca = re.sub(r"(^|&)v=\d+", "", busca)
    busca = re.sub(r"[^a-zA-Z0-9]+", "_", busca).strip("_")
    return SAIDA / ("demo" + rota + (f"__{busca}" if busca else "") + ".json")


def gravar(caminho: str, dados) -> None:
    arq = arquivo_demo(caminho)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def num_js(x: float) -> str:
    """Como o JavaScript escreve o número numa URL (85.0 -> "85")."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


_midias: dict[str, str] = {}


def midia(url: str) -> str:
    """Baixa um arquivo da API local para demo/media e devolve o endereço estático novo."""
    if url in _midias:
        return _midias[url]
    rota = url.split("?")[0]
    nome = re.sub(r"[^a-zA-Z0-9]+", "_", rota.removeprefix("/api/")).strip("_")
    with urllib.request.urlopen(API + url, timeout=300) as r:
        tipo = r.headers.get("content-type", "")
        dados = r.read()
    ext = {"video/mp4": ".mp4", "image/jpeg": ".jpg", "image/png": ".png", "application/x-subrip": ".srt"}.get(
        tipo.split(";")[0], ".mp4" if rota.endswith("/video") else ".txt" if "texto" in rota or "srt" in rota else ".jpg")
    destino = SAIDA / "demo" / "media" / (nome + ext)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".mp4":
        bruto = destino.with_suffix(".orig.mp4")
        bruto.write_bytes(dados)
        # 720 no lado menor, bom para tela e leve para a Vercel
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(bruto), "-vf",
                        "scale='if(gt(iw,ih),-2,720)':'if(gt(iw,ih),720,-2)'", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "26", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destino)], check=True)
        bruto.unlink()
    else:
        destino.write_bytes(dados)
    _midias[url] = f"/demo/media/{destino.name}"
    print("  mídia", destino.name, f"{destino.stat().st_size / 1e6:.1f} MB")
    return _midias[url]


def trocar_midias(x):
    if isinstance(x, dict):
        return {k: trocar_midias(v) for k, v in x.items()}
    if isinstance(x, list):
        return [trocar_midias(v) for v in x]
    if isinstance(x, str) and x.startswith("/api/projetos/"):
        return midia(x)
    return x


def main():
    shutil.rmtree(SAIDA / "demo", ignore_errors=True)
    if not (SAIDA / "index.html").exists():
        raise SystemExit("Rode antes o build da demonstração (frontend/dist-demo).")

    # Sistema e configurações (sem chave nem workspace)
    sistema = get_json("/api/sistema")
    sistema.update(dados="C:\\opusfalso-dados", fila=0, claude_erro=None, job_atual=None)
    gravar("/api/sistema", sistema)
    cfg = get_json("/api/config")
    cfg.update(api_key="sk-ant-••••••••", workspace_id="", api_key_origem="config")
    gravar("/api/config", cfg)
    for rota in ("/api/estilos", "/api/templates", "/api/fontes", "/api/armazenamento", "/api/audio"):
        gravar(rota, get_json(rota))

    # Custos: só as chamadas dos projetos da vitrine
    custos = get_json("/api/custos")
    hist = [h for h in custos.get("historico", []) if h.get("projeto") in VITRINE]
    custos.update(historico=hist, total=round(sum(h["custo"] for h in hist), 5), chamadas=len(hist))
    gravar("/api/custos", custos)

    # Projetos
    lista = []
    for p in get_json("/api/projetos"):
        if p["id"] in VITRINE:
            lista.append(trocar_midias({**p, "nome": VITRINE[p["id"]]}))
    gravar("/api/projetos", lista)
    for pid, nome in VITRINE.items():
        print(nome)
        p = get_json(f"/api/projetos/{pid}")
        p = trocar_midias({**p, "nome": nome, "video": "", "saida_dir": ""})
        gravar(f"/api/projetos/{pid}", p)
        for c in p.get("clips", []):  # palavras do editor (mesma URL que o Editor.jsx monta)
            busca = f"inicio={num_js(c['inicio'])}&fim={num_js(c['fim'])}&cid={c['id']}"
            try:
                palavras = get_json(f"/api/projetos/{pid}/palavras?{busca}")
            except urllib.error.HTTPError:
                palavras = []  # vídeo de origem não existe mais: o editor mostra "sem fala"
            gravar(f"/api/projetos/{pid}/palavras?{busca}", palavras)

    # Fontes das legendas (o preview carrega /api/fontes/<arquivo> direto)
    fontes = SAIDA / "api" / "fontes"
    fontes.mkdir(parents=True, exist_ok=True)
    for estilo in get_json("/api/estilos").values():
        arq = estilo.get("arquivo_fonte")
        if arq and not (fontes / arq).exists():
            (fontes / arq).write_bytes(get(f"/api/fontes/{arq}"))

    (SAIDA / "vercel.json").write_text(json.dumps({
        "rewrites": [{"source": "/((?!demo/|api/|assets/).*)", "destination": "/index.html"}],
    }, indent=2), encoding="utf-8")
    total = sum(f.stat().st_size for f in SAIDA.rglob("*") if f.is_file())
    print(f"Pronto: {SAIDA} ({total / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
