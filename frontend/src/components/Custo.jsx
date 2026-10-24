// Quanto o projeto custou na API do Claude: uma pílula que abre a conta por etapa.
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Receipt } from "lucide-react";
import { detalheCusto, formatarCusto } from "../api";

export default function CustoProjeto({ projeto, porClipe = false }) {
  const [aberto, setAberto] = useState(false);
  const caixa = useRef(null);
  const etapas = detalheCusto(projeto.custo_etapas);
  const semIa = !!projeto.opcoes?.sem_ia;
  const clipes = (projeto.clips || []).filter((c) => c.custo_estimado != null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e) => caixa.current && !caixa.current.contains(e.target) && setAberto(false);
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [aberto]);

  return (
    <div ref={caixa} className="relative inline-block">
      <button
        onClick={() => setAberto(!aberto)}
        className="inline-flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-1.5 text-sm hover:border-black/25 cursor-pointer"
        aria-expanded={aberto}
      >
        <Receipt className="size-3.5 text-suave" />
        <span className="text-suave">Custo</span>
        <span className="font-medium tabular-nums">{formatarCusto(projeto.custo)}</span>
        <ChevronDown className={`size-3.5 text-suave transition-transform ${aberto ? "rotate-180" : ""}`} />
      </button>

      {aberto && (
        <div className="absolute left-0 top-full z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-black/10 bg-white p-4 shadow-lg animate-surgir">
          <div className="rotulo mb-3">Quanto custou na API do Claude</div>
          {!projeto.custo ? (
            <p className="text-sm text-suave">
              {semIa ? "Feito no modo Sem IA: nenhuma chamada ao Claude." : "Nenhuma chamada paga ao Claude (respostas reaproveitadas ou feito sem IA)."}
            </p>
          ) : (
            <>
              {etapas.length > 0 && (
                <ul className="space-y-1.5 text-sm">
                  {etapas.map(([nome, v]) => (
                    <li key={nome} className="flex justify-between gap-4">
                      <span className="text-suave">{nome}</span>
                      <span className="tabular-nums">{formatarCusto(v)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {porClipe && clipes.length > 0 && (
                <>
                  <div className="rotulo mt-4 mb-2">Por clipe</div>
                  <ul className="max-h-48 overflow-y-auto space-y-1.5 text-sm pr-1">
                    {clipes.map((c, k) => (
                      <li key={c.id} className="flex justify-between gap-4">
                        <span className="truncate text-suave">{k + 1}. {c.titulo || "Sem título"}</span>
                        <span className="tabular-nums shrink-0">{formatarCusto(c.custo_estimado)}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-xs text-apagado mt-3">
                    Cada clipe leva o que foi gasto só com ele (tradução, trocar o momento, ajustes) mais uma parte igual da escolha dos momentos, que vale para todos.
                  </p>
                </>
              )}
              <div className="flex justify-between gap-4 border-t border-black/[0.08] mt-3 pt-3 text-sm font-medium">
                <span>Total</span>
                <span className="tabular-nums">{formatarCusto(projeto.custo)}</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
