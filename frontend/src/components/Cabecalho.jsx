// Topo de todas as telas, na linguagem do Gadosso CRM: a logo, as abas em pílula (a ativa em preto), o status
// em rótulo mono e o gasto na API. Fica grudado no topo, translúcido, com o conteúdo passando por baixo.
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api";

const ABAS = [
  { para: "/", rotulo: "Início", fim: true },
  { para: "/projetos", rotulo: "Projetos" },
  { para: "/configuracoes", rotulo: "Configurações" },
];

export default function Cabecalho() {
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

  const claudeOk = sistema?.tem_chave && !sistema?.claude_erro;
  const status = sistema === false
    ? { cor: "bg-vermelho", texto: "Servidor offline", ping: false }
    : sistema?.fila > 0 || sistema?.job_atual
      ? { cor: "bg-azul", texto: sistema?.fila > 0 ? `Processando · ${sistema.fila} na fila` : "Processando", ping: true }
      : !sistema
        ? { cor: "bg-apagado", texto: "Conectando", ping: false }
        : !sistema.tem_chave
          ? { cor: "bg-amarelo", texto: "Claude sem chave", ping: false }
          : sistema.claude_erro
            ? { cor: "bg-amarelo", texto: sistema.claude_erro.includes("créditos") ? "Claude sem créditos" : "Claude com erro", ping: false }
            : { cor: "bg-verde", texto: "Pronto", ping: true };
  const discoBaixo = sistema?.disco_livre != null && sistema.disco_livre < 5 * 1024 ** 3;

  return (
    <header className="sticky top-0 z-40 border-b border-black/[0.06] bg-fundo/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-[1600px] items-center gap-2 px-4 md:gap-8 md:px-6">
        <NavLink to="/" aria-label="Gadosso Edit: início" className="flex shrink-0 items-center gap-2.5">
          <img src="/logo-gadosso.png" alt="gadosso" width={1200} height={297} className="h-[19px] w-auto select-none md:h-6" draggable={false} />
          <span className="rotulo-mono rounded-full border border-black/15 px-2 py-0.5 text-black/60">edit</span>
        </NavLink>

        <nav aria-label="Seções" className="-mx-1 flex min-w-0 flex-1 gap-0.5 overflow-x-auto px-1 md:gap-1">
          {ABAS.map((aba) => (
            <NavLink
              key={aba.para}
              to={aba.para}
              end={aba.fim}
              className={({ isActive }) =>
                `rounded-full px-2.5 py-1.5 text-sm whitespace-nowrap transition-colors md:px-4 ${
                  isActive ? "bg-black text-white" : "text-black/55 hover:bg-black/[0.05] hover:text-black"
                }`
              }
            >
              {aba.rotulo}
            </NavLink>
          ))}
        </nav>

        {discoBaixo && (
          <NavLink to="/configuracoes" className="rotulo-mono hidden items-center gap-2 text-vermelho hover:underline lg:flex" title="Libere espaço em Configurações > Armazenamento">
            <span className="size-2 rounded-full bg-vermelho" />
            Disco {(sistema.disco_livre / 1024 ** 3).toFixed(1).replace(".", ",")} GB
          </NavLink>
        )}

        <span className="rotulo-mono hidden items-center gap-2 text-black/45 md:flex" title={sistema?.gpu || ""}>
          <span className="relative flex size-2">
            {status.ping && <span className={`absolute inline-flex size-full animate-ping rounded-full opacity-50 motion-reduce:hidden ${status.cor}`} />}
            <span className={`relative inline-flex size-2 rounded-full ${status.cor}`} />
          </span>
          {status.texto}
        </span>

        <span
          className="rotulo-mono hidden shrink-0 items-center rounded-full border border-black/10 px-3 py-1.5 text-black/60 sm:flex"
          title={claudeOk ? `Gasto estimado na API do Claude. GPU: ${sistema?.gpu || "nenhuma"}` : "Gasto estimado na API do Claude"}
        >
          US$ {custo != null ? custo.toFixed(2) : "…"}
        </span>
      </div>
    </header>
  );
}
