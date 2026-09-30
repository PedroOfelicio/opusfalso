// Legenda animada estilo "shorts": grupos de 2-4 palavras, palavra falada muda de cor
// e dá um "pop" de escala, emoji opcional, título gancho no início e barra de progresso.
import { useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  Easing,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Estilo, Grupo, PropsClip } from "./tipos";

// Carrega a fonte do preset (arquivo em public/fontes) antes de renderizar
const useFonte = (estilo: Estilo) => {
  useState(() => {
    if (!estilo.arquivo_fonte) return null;
    const handle = delayRender(`fonte ${estilo.fonte}`);
    const face = new FontFace(estilo.fonte, `url(${staticFile(`fontes/${estilo.arquivo_fonte}`)})`);
    face
      .load()
      .then((f) => {
        document.fonts.add(f);
        continueRender(handle);
      })
      .catch((e) => {
        console.error("Falha ao carregar fonte", e);
        continueRender(handle);
      });
    return null;
  });
};

export const Clip: React.FC<PropsClip> = ({ video, grupos, estilo, titulo, barra }) => {
  useFonte(estilo);
  const frame = useCurrentFrame();
  const { durationInFrames, width } = useVideoConfig();
  const escala = width / 1080; // presets são pensados para 1080 de largura

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <OffthreadVideo src={staticFile(video)} />
      <Legenda grupos={grupos} estilo={estilo} escala={escala} />
      {titulo ? <Titulo texto={titulo} estilo={estilo} escala={escala} /> : null}
      {barra ? (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            height: (estilo.barra_progresso?.altura ?? 10) * escala,
            width: `${((frame + 1) / durationInFrames) * 100}%`,
            background: estilo.cor_destaque,
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

const Legenda: React.FC<{ grupos: Grupo[]; estilo: Estilo; escala: number }> = ({ grupos, estilo, escala }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const t = frame / fps;
  const grupo = grupos.find((g) => t >= g.inicio && t < g.fim);
  if (!grupo) return null;

  // Entrada do grupo: cresce levemente e aparece
  const entrada = spring({ frame: Math.round((t - grupo.inicio) * fps), fps, config: { damping: 14, stiffness: 220 } });
  const emoji = grupo.palavras.find((w) => w.emoji && t >= w.i)?.emoji;
  const tamanho = estilo.tamanho * escala;
  const contorno = estilo.contorno * escala;

  return (
    <div
      style={{
        position: "absolute",
        top: estilo.posicao_y * height,
        left: "6%",
        width: "88%",
        transform: `translateY(-50%) scale(${0.85 + 0.15 * entrada})`,
        opacity: Math.min(1, entrada * 1.5),
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      {emoji ? <Emoji emoji={emoji} desde={grupo.palavras.find((w) => w.emoji === emoji)!.i} tamanho={tamanho} /> : null}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: `0 ${tamanho * 0.3 + contorno * 2}px`,
          fontFamily: `"${estilo.fonte}", sans-serif`,
          fontSize: tamanho,
          lineHeight: 1.12,
          textAlign: "center",
        }}
      >
        {grupo.palavras.map((w, k) => {
          const proxima = grupo.palavras[k + 1]?.i ?? grupo.fim;
          const ativa = t >= w.i && t < proxima;
          const dur = estilo.duracao_pop_ms / 1000;
          const pop =
            estilo.animacao === "pop" && ativa
              ? interpolate(t - w.i, [0, dur / 2, dur], [1, estilo.escala_pop, 1], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.out(Easing.quad),
                })
              : 1;
          const jaFalada = t >= w.i;
          return (
            <span
              key={k}
              style={{
                display: "inline-block",
                color: ativa ? estilo.cor_destaque : estilo.cor_texto,
                transform: `scale(${pop})`,
                // no estilo "fade" as palavras ainda não faladas ficam mais apagadas
                opacity: estilo.animacao === "fade" && !jaFalada ? 0.55 : 1,
                WebkitTextStroke: `${contorno * 2}px ${estilo.cor_contorno}`,
                paintOrder: "stroke fill",
                textShadow: `0 ${estilo.sombra * escala}px ${estilo.sombra * 2 * escala}px rgba(0,0,0,0.55)`,
              }}
            >
              {w.p}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const Emoji: React.FC<{ emoji: string; desde: number; tamanho: number }> = ({ emoji, desde, tamanho }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: Math.max(0, frame - Math.round(desde * fps)), fps, config: { damping: 9, stiffness: 180 } });
  return (
    <div style={{ fontSize: tamanho * 1.1, transform: `scale(${s}) rotate(${(1 - s) * -20}deg)`, marginBottom: tamanho * 0.1 }}>
      {emoji}
    </div>
  );
};

const Titulo: React.FC<{ texto: string; estilo: Estilo; escala: number }> = ({ texto, estilo, escala }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const fimTitulo = 2.8 * fps;
  if (frame > fimTitulo) return null;
  const entrada = spring({ frame, fps, config: { damping: 12, stiffness: 200 } });
  const saida = interpolate(frame, [fimTitulo - 8, fimTitulo], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const cfg = estilo.titulo ?? { cor_fundo: "#FFE600", cor_texto: "#000000", tamanho: 64 };
  return (
    <div
      style={{
        position: "absolute",
        top: height * 0.13,
        left: "8%",
        width: "84%",
        display: "flex",
        justifyContent: "center",
        opacity: saida,
        transform: `translateY(${(1 - entrada) * -40}px) scale(${0.9 + 0.1 * entrada})`,
      }}
    >
      <div
        style={{
          background: cfg.cor_fundo,
          color: cfg.cor_texto,
          fontFamily: `"${estilo.fonte}", sans-serif`,
          fontSize: cfg.tamanho * escala,
          lineHeight: 1.15,
          padding: `${18 * escala}px ${30 * escala}px`,
          borderRadius: 18 * escala,
          textAlign: "center",
          boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
        }}
      >
        {texto}
      </div>
    </div>
  );
};
