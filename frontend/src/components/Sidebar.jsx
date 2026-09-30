// Barra lateral fixa com navegação e status do sistema.
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Cpu, FolderOpen, Home, Palette, Settings, Sparkles } from "lucide-react";
import { api } from "../api";

const itens = [
  { para: "/", rotulo: "Início", icone: Home, fim: true },
  { para: "/projetos", rotulo: "Projetos", icone: FolderOpen },
  { para: "/estilos", rotulo: "Estilos", icone: Palette },
  { para: "/configuracoes", rotulo: "Configurações", icone: Settings },
];

export default function Sidebar() {
  const [sistema, setSistema] = useState(null);
  const [custo, setCusto] = useState(null);

  useEffect(() => {
    const carregar = () => {
      api.sistema().then(setSistema).catch(() => setSistema(false));
      api.custos().then((c) => setCusto(c.total)).catch(() => {});
    };
    carregar();
    const id = setInterval(carregar, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside className="w-60 shrink-0 h-full border-r border-borda bg-[#0d0d12] flex flex-col">
      <div className="px-5 h-16 flex items-center gap-2.5">
        <div className="size-8 rounded-[10px] gradiente flex items-center justify-center shadow-[0_6px_20px_-6px_rgba(124,58,237,0.8)]">
          <Sparkles className="size-4 text-white" />
        </div>
        <span className="font-bold text-[17px] tracking-tight">Clipador</span>
      </div>

      <nav className="px-3 mt-2 flex flex-col gap-1">
        {itens.map(({ para, rotulo, icone: Icone, fim }) => (
          <NavLink
            key={para}
            to={para}
            end={fim}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                isActive ? "gradiente text-white shadow-[0_6px_20px_-8px_rgba(124,58,237,0.8)]" : "text-suave hover:text-texto hover:bg-white/5"
              }`
            }
          >
            <Icone className="size-[18px]" />
            {rotulo}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto p-3">
        <div className="rounded-xl border border-borda bg-card p-3 text-xs space-y-2">
          {sistema === false ? (
            <div className="flex items-center gap-2 text-vermelho">
              <span className="size-2 rounded-full bg-vermelho" /> Servidor offline
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 text-suave" title={sistema?.gpu || ""}>
                <Cpu className="size-3.5" />
                <span className="truncate">{sistema ? (sistema.cuda ? sistema.gpu?.split(",")[0].replace("NVIDIA GeForce ", "") : "CPU") : "…"}</span>
              </div>
              <div className="flex items-center gap-2 text-suave" title={sistema?.claude_erro || ""}>
                <span className={`size-2 rounded-full shrink-0 ${sistema?.tem_chave && !sistema?.claude_erro ? "bg-verde" : "bg-amarelo"}`} />
                <span className="truncate">
                  {!sistema?.tem_chave ? "Claude sem chave" : sistema?.claude_erro ? (sistema.claude_erro.includes("créditos") ? "Claude sem créditos" : "Claude com erro") : "Claude configurado"}
                </span>
              </div>
              {sistema?.fila > 0 && <div className="text-azul">{sistema.fila} job(s) na fila</div>}
            </>
          )}
          <div className="pt-2 border-t border-borda flex justify-between">
            <span className="text-apagado">Gasto na API</span>
            <span className="font-semibold tabular-nums">US$ {custo != null ? custo.toFixed(3) : "…"}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
