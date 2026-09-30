// Nota viral (0-100) num círculo colorido: verde >= 80, amarelo >= 60, vermelho abaixo.
import { Dica } from "./ui";

export const corDaNota = (nota) => (nota >= 80 ? "#22C55E" : nota >= 60 ? "#EAB308" : "#EF4444");

export default function ScoreBadge({ nota, justificativa, tamanho = 44 }) {
  const cor = corDaNota(nota);
  const raio = tamanho / 2 - 4;
  const circ = 2 * Math.PI * raio;
  return (
    <Dica texto={justificativa ? `Potencial viral ${nota}/100 — ${justificativa}` : null}>
      <div
        className="relative rounded-full bg-black/70 backdrop-blur-md flex items-center justify-center cursor-help"
        style={{ width: tamanho, height: tamanho, boxShadow: `0 0 18px -4px ${cor}` }}
      >
        <svg width={tamanho} height={tamanho} className="absolute inset-0 -rotate-90">
          <circle cx={tamanho / 2} cy={tamanho / 2} r={raio} stroke="rgba(255,255,255,0.12)" strokeWidth="3" fill="none" />
          <circle
            cx={tamanho / 2}
            cy={tamanho / 2}
            r={raio}
            stroke={cor}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - nota / 100)}
          />
        </svg>
        <span className="relative text-[13px] font-bold tabular-nums" style={{ color: cor }}>
          {nota}
        </span>
      </div>
    </Dica>
  );
}
