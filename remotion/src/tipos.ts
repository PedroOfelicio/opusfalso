// Props enviadas pelo Python (backend/legendas.py -> renderizar_remotion)

export type Palavra = {
  p: string;        // texto já tratado (maiúsculas, sem pontuação)
  i: number;        // início (s)
  f: number;        // fim (s)
  enfase: boolean;
  emoji: string | null;
};

export type Grupo = { inicio: number; fim: number; palavras: Palavra[] };

export type Estilo = {
  fonte: string;
  arquivo_fonte?: string;
  tamanho: number;
  cor_texto: string;
  cor_destaque: string;
  cor_contorno: string;
  contorno: number;
  sombra: number;
  posicao_y: number;
  animacao: "pop" | "fade" | string;
  escala_pop: number;
  duracao_pop_ms: number;
  titulo?: { cor_fundo: string; cor_texto: string; tamanho: number };
  barra_progresso?: { ativa: boolean; cor: string; altura: number };
};

export type PropsClip = {
  video: string;          // caminho relativo à pasta public (ex.: "clips/abc.mp4")
  largura: number;
  altura: number;
  fps: number;
  duracao: number;        // segundos
  grupos: Grupo[];
  estilo: Estilo;
  titulo: string | null;
  barra: boolean;
};
