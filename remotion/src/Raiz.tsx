// Registra a composição "Clip". Tamanho, fps e duração vêm das props enviadas pelo Python.
import { Composition } from "remotion";
import { Clip } from "./Clip";
import type { PropsClip } from "./tipos";

// Props de exemplo (usadas só no Remotion Studio: npm run studio)
const exemplo: PropsClip = {
  video: "clips/exemplo.mp4",
  largura: 1080,
  altura: 1920,
  fps: 30,
  duracao: 5,
  titulo: "Ninguém te conta isso",
  barra: true,
  grupos: [
    {
      inicio: 0.2,
      fim: 1.6,
      palavras: [
        { p: "NINGUÉM", i: 0.2, f: 0.6, enfase: true, emoji: "🤫" },
        { p: "TE", i: 0.6, f: 0.8, enfase: false, emoji: null },
        { p: "CONTA", i: 0.8, f: 1.3, enfase: false, emoji: null },
      ],
    },
  ],
  estilo: {
    fonte: "Montserrat Black",
    arquivo_fonte: "Montserrat-Black.ttf",
    tamanho: 88,
    cor_texto: "#FFFFFF",
    cor_destaque: "#FFE600",
    cor_contorno: "#000000",
    contorno: 9,
    sombra: 5,
    posicao_y: 0.68,
    animacao: "pop",
    escala_pop: 1.15,
    duracao_pop_ms: 120,
    titulo: { cor_fundo: "#FFE600", cor_texto: "#000000", tamanho: 64 },
    barra_progresso: { ativa: true, cor: "#FFE600", altura: 10 },
  },
};

export const Raiz: React.FC = () => (
  <Composition
    id="Clip"
    component={Clip}
    defaultProps={exemplo}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={150}
    calculateMetadata={({ props }) => ({
      width: props.largura,
      height: props.altura,
      fps: props.fps,
      durationInFrames: Math.max(1, Math.round(props.duracao * props.fps)),
    })}
  />
);
