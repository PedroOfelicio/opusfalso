// Preview ao vivo de um preset de legenda (imita o que o ASS/Remotion renderizam).
import { useEffect, useMemo, useState } from "react";

const FRASE = "ninguém te conta isso, mas o segredo é consistência todo santo dia.".split(" ");
const ENFASE = new Set(["segredo", "consistência"]); // palavras-chave da frase de exemplo
const fontesCarregadas = new Set();

// Registra a fonte do preset no navegador (vem de /api/fontes/<arquivo>)
export function useFonteDoPreset(estilo) {
  const [pronta, setPronta] = useState(0);
  useEffect(() => {
    if (!estilo?.arquivo_fonte || fontesCarregadas.has(estilo.fonte)) return;
    const face = new FontFace(estilo.fonte, `url(/api/fontes/${estilo.arquivo_fonte})`);
    face
      .load()
      .then((f) => {
        document.fonts.add(f);
        fontesCarregadas.add(estilo.fonte);
        setPronta((n) => n + 1);
      })
      .catch(() => {});
  }, [estilo?.fonte, estilo?.arquivo_fonte]);
  return pronta;
}

export default function PreviewLegenda({ estilo, fundo, titulo = "Ninguém te conta isso", largura = 270, frase = FRASE }) {
  useFonteDoPreset(estilo);
  const [indice, setIndice] = useState(0);
  const porVez = Math.max(1, estilo?.palavras_por_vez || 3);

  useEffect(() => {
    const id = setInterval(() => setIndice((i) => (i + 1) % frase.length), 380);
    return () => clearInterval(id);
  }, [frase.length]);

  const grupo = useMemo(() => {
    const inicio = Math.floor(indice / porVez) * porVez;
    return { inicio, palavras: frase.slice(inicio, inicio + porVez) };
  }, [indice, porVez, frase]);

  if (!estilo) return null;
  const escala = largura / 1080;
  const altura = largura * (16 / 9);
  const tituloCfg = estilo.titulo || {};
  const mostrarTitulo = indice < 7;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-borda bg-black shadow-suave shrink-0" style={{ width: largura, height: altura }}>
      {fundo ? (
        <img src={fundo} alt="" className="absolute inset-0 size-full object-cover opacity-80" />
      ) : (
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,#3b2a6b,transparent_55%),radial-gradient(circle_at_70%_80%,#1e3a6b,transparent_55%),#111]" />
      )}
      {estilo.barra_progresso?.ativa && (
        <div className="absolute top-0 left-0 transition-all duration-300" style={{ height: Math.max(2, estilo.barra_progresso.altura * escala), width: `${((indice + 1) / frase.length) * 100}%`, background: estilo.cor_destaque }} />
      )}
      {titulo && mostrarTitulo && (
        <div className="absolute inset-x-0 flex justify-center px-6" style={{ top: altura * 0.13 }}>
          <div
            className="text-center shadow-lg"
            style={{
              background: tituloCfg.cor_fundo,
              color: tituloCfg.cor_texto,
              fontFamily: `"${estilo.fonte}"`,
              fontSize: (tituloCfg.tamanho || 64) * 1.35 * escala,
              padding: `${18 * escala}px ${30 * escala}px`,
              borderRadius: 18 * escala,
              lineHeight: 1.15,
            }}
          >
            {titulo}
          </div>
        </div>
      )}
      <div className="absolute inset-x-0 flex flex-wrap justify-center px-[6%]" style={{ top: altura * (estilo.posicao_y ?? 0.68), transform: "translateY(-50%)", gap: `0 ${(estilo.tamanho * 0.3 + estilo.contorno * 2) * escala}px` }}>
        {grupo.palavras.map((p, k) => {
          const ativa = grupo.inicio + k === indice;
          const falada = grupo.inicio + k <= indice;
          const limpa = estilo.pontuacao ? p : p.replace(/[.,;:…]+$/, "");
          const texto = estilo.maiusculas ? limpa.toUpperCase() : limpa;
          const colorida = estilo.destaque === "enfase" ? ENFASE.has(p.replace(/[.,]/g, "")) : ativa;
          const sombra = estilo.sombra * escala;
          return (
            <span
              key={`${grupo.inicio}-${k}`}
              style={{
                display: "inline-block",
                fontFamily: `"${estilo.fonte}"`,
                fontSize: estilo.tamanho * escala,
                lineHeight: 1.12,
                color: colorida ? estilo.cor_destaque : estilo.cor_texto,
                WebkitTextStroke: `${estilo.contorno * escala * 2}px ${estilo.cor_contorno}`,
                paintOrder: "stroke fill",
                textShadow: estilo.sombra_dura ? `${sombra}px ${sombra}px 0 ${estilo.cor_contorno}` : `0 ${sombra}px ${sombra * 2}px rgba(0,0,0,.55)`,
                opacity: estilo.animacao === "fade" && !falada ? 0.55 : 1,
                animation: ativa && estilo.animacao === "pop" ? `pop-legenda ${estilo.duracao_pop_ms || 120}ms ease-out`
                  : estilo.animacao === "elastico" ? `elastico-legenda ${estilo.duracao_pop_ms || 130}ms ease-out` : undefined,
                "--escala-pop": estilo.escala_pop || 1.15,
              }}
            >
              {texto}
            </span>
          );
        })}
      </div>
      <style>{`@keyframes pop-legenda { 0%{transform:scale(1)} 50%{transform:scale(var(--escala-pop))} 100%{transform:scale(1)} }
@keyframes elastico-legenda { 0%{transform:scale(.4);filter:blur(2px)} 45%{transform:scale(var(--escala-pop));filter:blur(0)} 100%{transform:scale(1)} }`}</style>
    </div>
  );
}
