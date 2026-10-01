// Lista de etapas do processamento com status e tempo gasto em cada uma.
import { AudioLines, Check, Clapperboard, Loader2, Scissors, Sparkles, Subtitles } from "lucide-react";

export const ETAPAS = [
  { id: "transcrevendo", rotulo: "Transcrevendo", icone: AudioLines, texto: "Convertendo a fala em texto com tempo por palavra" },
  { id: "analisando", rotulo: "Analisando", icone: Sparkles, texto: "Entendendo a instrução e a energia do áudio" },
  { id: "escolhendo", rotulo: "Escolhendo trechos", icone: Clapperboard, texto: "Procurando os momentos com mais potencial" },
  { id: "cortando", rotulo: "Cortando", icone: Scissors, texto: "Recortando os trechos escolhidos" },
  { id: "legendando", rotulo: "Legendando", icone: Subtitles, texto: "Reenquadrando e aplicando legendas" },
];

const duracao = (e) => {
  if (!e?.inicio) return "";
  const s = (e.fim || Date.now() / 1000) - e.inicio;
  return s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}min ${Math.round(s % 60)}s`;
};

export default function StepProgress({ etapas = {}, atual, parado, lista = ETAPAS }) {
  return (
    <ol className="space-y-1">
      {lista.map(({ id, rotulo, icone: Icone, texto }, idx) => {
        const e = etapas[id];
        const status = e?.status === "ok" ? "ok" : id === atual && !parado ? "ativo" : "pendente";
        return (
          <li
            key={id}
            className={`flex items-center gap-4 rounded-xl px-4 py-3 transition-colors ${status === "ativo" ? "bg-roxo/10 border border-roxo/30" : "border border-transparent"}`}
          >
            <div
              className={`size-9 rounded-full flex items-center justify-center shrink-0 transition-all ${
                status === "ok" ? "bg-verde/15 text-verde" : status === "ativo" ? "gradiente text-white" : "bg-card-2 text-apagado border border-borda"
              }`}
            >
              {status === "ok" ? <Check className="size-4" /> : status === "ativo" ? <Loader2 className="size-4 animate-spin" /> : <Icone className="size-4" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-sm font-semibold ${status === "pendente" ? "text-apagado" : ""}`}>
                <span className="text-apagado mr-1.5 tabular-nums">{idx + 1}.</span>
                {rotulo}
              </div>
              <div className="text-xs text-apagado truncate">{status === "ativo" && e?.detalhe ? e.detalhe : texto}</div>
            </div>
            <span className="text-xs text-suave tabular-nums">{status !== "pendente" ? duracao(e) : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}
