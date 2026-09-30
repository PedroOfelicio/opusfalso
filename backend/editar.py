"""
Uso pelo terminal:

    python editar.py video.mp4 "5 melhores momentos, vertical, legenda amarela" --modo falado
    python editar.py gameplay.mkv "3 clipes curtos, zoom nas kills" --modo gameplay --clips 3

Cria um projeto (o mesmo que aparece na interface web) e salva os clipes em
<pasta_saida>/<nome_do_video>/clip_01.mp4, clip_02.mp4...
"""
import argparse
import sys
import time
from pathlib import Path

import config
import custos
import pipeline
import projetos

DURACOES = {"15-30": (15, 30), "30-60": (30, 60), "60-90": (60, 90)}


def main():
    ap = argparse.ArgumentParser(description="Editor de vídeo local com IA")
    ap.add_argument("video", help="caminho do vídeo (mp4, mov, mkv)")
    ap.add_argument("instrucao", nargs="?", default="", help="o que você quer, em linguagem natural")
    ap.add_argument("--modo", choices=["falado", "gameplay"], default="falado")
    ap.add_argument("--clips", type=int, default=3, help="número de clipes (a instrução pode mudar)")
    ap.add_argument("--duracao", choices=list(DURACOES), default="30-60")
    ap.add_argument("--formato", choices=["9:16", "16:9", "1:1"], default="9:16")
    ap.add_argument("--preset", default="opus", help="preset de legenda (estilos.json)")
    ap.add_argument("--animada", action="store_true", help="legenda animada (Remotion)")
    ap.add_argument("--layout", default="auto", choices=["auto", "rosto", "centro", "inteiro", "split", "dupla"])
    ap.add_argument("--musica", help="arquivo de música de fundo")
    ap.add_argument("--apoio", help="vídeo de apoio para a parte de baixo (gameplay)")
    ap.add_argument("--refinar", action="store_true", help="gameplay: confirmar momentos enviando frames ao Claude")
    args = ap.parse_args()

    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        sys.exit(f"Arquivo não encontrado: {video}")
    config.preparar_pastas()

    opcoes = {
        "num_clips": args.clips, "duracao": DURACOES[args.duracao], "formato": args.formato,
        "preset": args.preset, "estilo_legenda": "animada" if args.animada else "simples",
        "layout": args.layout, "musica_caminho": args.musica, "video_apoio": args.apoio,
        "refinar_frames": args.refinar,
    }
    meta = projetos.criar(video, video.name, args.modo, args.instrucao, opcoes)
    custo_antes = custos.resumo()["total"]
    t0 = time.time()
    print(f"Projeto {meta['id']} | {video.name} | modo {args.modo}")

    try:
        meta = pipeline.processar(meta["id"], imprimir=True)
    except KeyboardInterrupt:
        projetos.atualizar(meta["id"], lambda m: m.update(status="cancelado"))
        sys.exit("\nCancelado.")
    except Exception as e:
        projetos.atualizar(meta["id"], lambda m: m.update(status="erro", erro=str(e)))
        sys.exit(f"\nERRO: {e}")

    print("\n")
    print("=" * 70)
    print(f"Pronto em {time.time() - t0:.0f}s. Clipes em: {meta['saida_dir']}")
    for c in meta["clips"]:
        print(f"  {c['id']}  nota {c['nota']:>3}  {c['duracao']:5.1f}s  {c['titulo']}")
        print(f"            {c['justificativa']}")
    if meta["nao_atendido"]:
        print("\nNão atendido (fora das ações suportadas):")
        for x in meta["nao_atendido"]:
            print(f"  - {x}")
    if meta["avisos"]:
        print("\nAvisos:")
        for x in meta["avisos"]:
            print(f"  - {x}")
    print(f"\nCusto estimado da API nesta execução: US$ {custos.resumo()['total'] - custo_antes:.4f}")


if __name__ == "__main__":
    main()
