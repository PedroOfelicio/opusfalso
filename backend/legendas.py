"""
Legendas por palavra.

- agrupar(): junta 2-4 palavras por vez, quebrando em pausas naturais e pontuação
- gerar_ass(): legenda "simples" queimada pelo FFmpeg/libass, já com destaque
  da palavra falada (cor + pop de escala) e título gancho com fundo colorido
- A legenda "animada" (Remotion) usa os mesmos grupos: ver remotion/ e legendas_remotion()

Estilos vêm de estilos.json (presets). Para criar um novo preset, copie um
bloco existente no arquivo (ou use a tela Estilos).
"""
import json
import re
from pathlib import Path

import config
from editor_ffmpeg import mapear_intervalo

PONTUACAO_REMOVIDA = ".,;:…\"“”"


DURACAO_TITULO = 4.0  # segundos na tela (cobre a abertura com o clímax)


def carregar_estilos() -> dict:
    return config.ler_json(config.ARQ_ESTILOS, {})


def estilo(preset: str, cor: str | None = None) -> dict:
    estilos = carregar_estilos()
    e = dict(estilos.get(preset) or estilos.get("opus") or next(iter(estilos.values())))
    if cor:
        e["cor_destaque"] = cor
    return e


def palavras_do_clipe(palavras: list[dict], trechos: list[tuple[float, float]],
                      enfase: list[str] | None = None, emojis: list[dict] | None = None) -> list[dict]:
    """Converte palavras do vídeo original para o tempo do clipe (depois dos cortes).
    Marca as de ênfase e anexa emojis sugeridos."""
    enfase_norm = {_norm(p) for p in (enfase or [])}
    emoji_por = {_norm(e["palavra"]): e["emoji"] for e in (emojis or [])}
    inicio, fim = min(a for a, _ in trechos), max(b for _, b in trechos)
    resultado = []
    for w in palavras:
        if w["f"] < inicio or w["i"] > fim:
            continue
        n = _norm(w["p"])
        # Uma palavra pode aparecer 2x (na abertura com o clímax e no lugar dela)
        for i, f in mapear_intervalo(w["i"], w["f"], trechos):
            resultado.append({"p": w["p"], "i": round(i, 3), "f": round(max(f, i + 0.05), 3),
                              "enfase": n in enfase_norm, "emoji": emoji_por.get(n)})
    resultado.sort(key=lambda w: w["i"])
    vistos = set()
    for w in resultado:  # emoji só na primeira vez que a palavra aparece
        if w["emoji"] and _norm(w["p"]) in vistos:
            w["emoji"] = None
        vistos.add(_norm(w["p"]))
    return resultado


def _norm(p: str) -> str:
    return re.sub(r"[^\wÀ-ÿ]", "", p.lower())


def agrupar(palavras: list[dict], max_palavras: int = 3, max_chars: int = 18, pausa: float = 0.35) -> list[list[dict]]:
    """Quebra por pausa natural, pontuação, número de palavras ou tamanho da linha."""
    grupos, atual = [], []
    for w in palavras:
        if atual:
            gap = w["i"] - atual[-1]["f"]
            chars = sum(len(x["p"]) + 1 for x in atual) + len(w["p"])
            fim_frase = atual[-1]["p"].rstrip()[-1:] in ".!?,;:"
            if gap > pausa or fim_frase or len(atual) >= max_palavras or chars > max_chars:
                grupos.append(atual)
                atual = []
        atual.append(w)
    if atual:
        grupos.append(atual)
    return grupos


def _texto(p: str, maiusculas: bool, pontuacao: bool = False) -> str:
    p = p.strip() if pontuacao else p.strip().strip(PONTUACAO_REMOVIDA)
    p = p.replace("{", "(").replace("}", ")")
    return p.upper() if maiusculas else p


def _ass_cor(hexa: str, alfa: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (formato do ASS)."""
    h = hexa.lstrip("#")
    return f"&H{alfa:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _tempo(t: float) -> str:
    t = max(t, 0)
    h, resto = divmod(t, 3600)
    m, s = divmod(resto, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def gerar_ass(palavras: list[dict], est: dict, saida: str | Path, largura: int, altura: int,
              duracao: float, titulo: str | None = None, legenda_ativa: bool = True) -> Path:
    """Cria o arquivo .ass. `palavras` já no tempo do clipe."""
    escala = (largura / 1080) if altura >= largura else (altura / 1080) * 0.8
    tam = int(est["tamanho"] * escala)
    fonte = est["fonte"]
    largura_char = 0.45 if "anton" in fonte.lower() else 0.6
    max_chars = int(largura * 0.88 / (tam * largura_char))
    y = int(altura * est.get("posicao_y", 0.68))
    tit = est.get("titulo", {})
    # Sombra dura (estilo YouTuber): deslocada e sem transparência; senão, sombra suave translúcida
    cor_sombra = "&H00000000" if est.get("sombra_dura") else "&H96000000"
    tam_tit = int(tit.get("tamanho", 64) * 1.35 * escala)  # título grande: é o gancho em texto

    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {largura}", f"PlayResY: {altura}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Legenda,{fonte},{tam},{_ass_cor(est['cor_texto'])},&H000000FF,{_ass_cor(est['cor_contorno'])},"
        f"{cor_sombra},0,0,0,0,100,100,1,0,1,{est.get('contorno', 8) * escala:.1f},{est.get('sombra', 4) * escala:.1f},5,60,60,0,1",
        # BorderStyle 3 = caixa opaca atrás do texto (a cor da caixa é a OutlineColour)
        f"Style: Titulo,{est['fonte']},{tam_tit},{_ass_cor(tit.get('cor_texto', '#000000'))},&H000000FF,"
        f"{_ass_cor(tit.get('cor_fundo', '#FFE600'))},&H64000000,0,0,0,0,100,100,0,0,3,{18 * escala:.1f},0,8,90,90,{int(altura * 0.13)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if titulo:
        linhas.append(
            f"Dialogue: 1,{_tempo(0)},{_tempo(min(DURACAO_TITULO, duracao))},Titulo,,0,0,0,,"
            r"{\fad(150,250)\fscx92\fscy92\t(0,180,\fscx104\fscy104)\t(180,320,\fscx100\fscy100)}"
            + titulo.replace("{", "(").replace("}", ")")
        )

    if legenda_ativa and palavras:
        destaque = _ass_cor(est["cor_destaque"])
        maius = est.get("maiusculas", True)
        pont = bool(est.get("pontuacao"))
        pop = est.get("animacao", "pop") == "pop"
        escala_pop = int(est.get("escala_pop", 1.15) * 100)
        meio = int(est.get("duracao_pop_ms", 120) / 2)
        grupos = agrupar(palavras, est.get("palavras_por_vez", 3), max_chars)
        for gi, grupo in enumerate(grupos):
            inicio_grupo = grupo[0]["i"]
            proximo = grupos[gi + 1][0]["i"] if gi + 1 < len(grupos) else duracao
            fim_grupo = min(proximo, grupo[-1]["f"] + 0.6)
            if est.get("destaque") == "enfase":
                # Só as palavras-chave mudam de cor: uma linha por grupo, que entra com a animação do estilo
                partes = [("{" + rf"\c{destaque}" + "}" + _texto(w["p"], maius, pont) + r"{\r}") if w.get("enfase")
                          else _texto(w["p"], maius, pont) for w in grupo]
                texto = "{" + rf"\an5\pos({largura // 2},{y}){_entrada(est)}" + "}" + " ".join(partes)
                linhas.append(f"Dialogue: 0,{_tempo(inicio_grupo)},{_tempo(fim_grupo)},Legenda,,0,0,0,,{texto}")
                continue
            for k, w in enumerate(grupo):
                t0 = inicio_grupo if k == 0 else w["i"]
                t1 = grupo[k + 1]["i"] if k + 1 < len(grupo) else fim_grupo
                if t1 - t0 < 0.02:
                    continue
                partes = []
                for j, outra in enumerate(grupo):
                    txt = _texto(outra["p"], maius, pont)
                    if j == k:
                        efeito = rf"\c{destaque}"
                        if pop:
                            efeito += (rf"\t(0,{meio},\fscx{escala_pop}\fscy{escala_pop})"
                                       rf"\t({meio},{meio * 2},\fscx100\fscy100)")
                        partes.append("{" + efeito + "}" + txt + r"{\r}")
                    else:
                        partes.append(txt)
                entrada = _entrada(est) if k == 0 else ""
                texto = "{" + rf"\an5\pos({largura // 2},{y}){entrada}" + "}" + " ".join(partes)
                linhas.append(f"Dialogue: 0,{_tempo(t0)},{_tempo(t1)},Legenda,,0,0,0,,{texto}")

    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n".join(linhas) + "\n", encoding="utf-8-sig")
    return saida


def _entrada(est: dict) -> str:
    """Animação de entrada do grupo no ASS. "elastico": nasce pequeno e borrado, passa do tamanho e assenta."""
    animacao = est.get("animacao", "pop")
    if animacao == "elastico":
        dur = int(est.get("duracao_pop_ms", 130))
        meio, pico = int(dur * 0.45), int(est.get("escala_pop", 1.15) * 100)
        return (rf"\fscx40\fscy40\blur4\t(0,{meio},\fscx{pico}\fscy{pico}\blur0)"
                rf"\t({meio},{dur},\fscx100\fscy100)")
    return "" if animacao == "pop" else r"\fad(80,0)"


def momentos_de_zoom(palavras_clipe: list[dict]) -> list[tuple[float, float]]:
    """Intervalos (tempo do clipe) das palavras de ênfase, para o zoom automático."""
    momentos = []
    for w in palavras_clipe:
        if w.get("enfase"):
            if momentos and w["i"] - momentos[-1][1] < 0.8:
                momentos[-1] = (momentos[-1][0], w["f"])  # junta ênfases próximas
            else:
                momentos.append((w["i"], w["f"]))
    return momentos


# ================================================================ legenda animada (Remotion)

PASTA_REMOTION = config.RAIZ / "remotion"
PUBLIC_REMOTION = config.DADOS / "remotion_public"   # vídeos temporários + fontes (fora do OneDrive)


def remotion_disponivel() -> bool:
    return (PASTA_REMOTION / "node_modules" / "@remotion" / "cli" / "remotion-cli.js").exists()


def grupos_para_remotion(palavras: list[dict], est: dict, largura: int, altura: int, duracao: float) -> list[dict]:
    """Mesmos grupos da legenda simples, já com o texto tratado."""
    escala = (largura / 1080) if altura >= largura else (altura / 1080) * 0.8
    tam = est["tamanho"] * escala
    largura_char = 0.45 if "anton" in est["fonte"].lower() else 0.6
    # no navegador o contorno e o espaçamento ocupam mais: margem de 20%
    max_chars = int(largura * 0.88 / (tam * largura_char) * 0.8)
    grupos = agrupar(palavras, est.get("palavras_por_vez", 3), max_chars)
    resultado = []
    for gi, g in enumerate(grupos):
        proximo = grupos[gi + 1][0]["i"] if gi + 1 < len(grupos) else duracao
        resultado.append({
            "inicio": g[0]["i"], "fim": min(proximo, g[-1]["f"] + 0.6),
            "palavras": [{"p": _texto(w["p"], est.get("maiusculas", True), bool(est.get("pontuacao"))), "i": w["i"], "f": w["f"],
                          "enfase": bool(w.get("enfase")), "emoji": w.get("emoji")} for w in g],
        })
    return resultado


def renderizar_remotion(base, saida, palavras, est, titulo, duracao, largura, altura,
                        barra=True, progresso=None, cancelado=None) -> Path:
    """Renderiza a legenda animada por cima do vídeo base (já reenquadrado)."""
    import os
    import shutil
    import subprocess
    import uuid
    from config import Cancelado
    from editor_ffmpeg import FPS_SAIDA, _SEM_JANELA

    if not remotion_disponivel():
        raise RuntimeError("Remotion não instalado (rode 'npm install' na pasta remotion)")
    (PUBLIC_REMOTION / "clips").mkdir(parents=True, exist_ok=True)
    (PUBLIC_REMOTION / "fontes").mkdir(exist_ok=True)
    for f in config.PASTA_FONTES.glob("*.[ot]tf"):
        alvo = PUBLIC_REMOTION / "fontes" / f.name
        if not alvo.exists():
            shutil.copy2(f, alvo)

    nome = f"{uuid.uuid4().hex[:10]}.mp4"
    video_public = PUBLIC_REMOTION / "clips" / nome
    shutil.copy2(base, video_public)
    props = {
        "video": f"clips/{nome}", "largura": largura, "altura": altura, "fps": FPS_SAIDA,
        "duracao": round(duracao, 3), "grupos": grupos_para_remotion(palavras, est, largura, altura, duracao),
        "estilo": est, "titulo": titulo, "barra": barra,
    }
    arq_props = PUBLIC_REMOTION / f"{nome}.json"
    arq_props.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    tmp_saida = saida.with_suffix(".remotion.mp4")

    cmd = ["node", str(PASTA_REMOTION / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"),
           "render", "src/index.ts", "Clip", str(tmp_saida),
           f"--props={arq_props}", f"--public-dir={PUBLIC_REMOTION}",
           "--codec=h264", "--crf=22",  # 22: leve para as redes, sem perda visível
           "--log=info", f"--concurrency={max(1, (os.cpu_count() or 4) // 2)}"]
    proc = subprocess.Popen(cmd, cwd=str(PASTA_REMOTION), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="ignore", creationflags=_SEM_JANELA)
    ultimas = []
    try:
        for linha in proc.stdout:
            if cancelado is not None and cancelado.is_set():
                proc.kill()
                raise Cancelado()
            ultimas = (ultimas + [linha.strip()])[-15:]
            m = re.search(r"Rendered (\d+)/(\d+)", linha) or re.search(r"(\d+)/(\d+)", linha)
            if m and progresso and int(m.group(2)) > 0:
                progresso(min(int(m.group(1)) / int(m.group(2)), 1.0) * 0.95)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        video_public.unlink(missing_ok=True)
        arq_props.unlink(missing_ok=True)
    if proc.returncode != 0 or not tmp_saida.exists():
        raise RuntimeError("Remotion falhou: " + " | ".join(ultimas[-6:]))
    os.replace(tmp_saida, saida)
    if progresso:
        progresso(1.0)
    return saida


# ================================================================ legenda .srt (vídeos longos, para subir no YouTube)

def _tempo_srt(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def gerar_srt(palavras: list[dict], saida: str | Path, max_chars: int = 42) -> Path:
    """Linhas de até ~42 caracteres (padrão de legenda), quebradas em pausas e pontuação.
    `palavras` já no tempo do vídeo final."""
    grupos = agrupar(palavras, max_palavras=12, max_chars=max_chars, pausa=0.6)
    linhas = []
    for k, g in enumerate(grupos, 1):
        texto = " ".join(w["p"].strip() for w in g).strip()
        if texto:
            fim = max(g[-1]["f"], g[0]["i"] + 0.5)
            linhas += [str(k), f"{_tempo_srt(g[0]['i'])} --> {_tempo_srt(fim)}", texto, ""]
    saida = Path(saida)
    saida.write_text("\n".join(linhas), encoding="utf-8")
    return saida
