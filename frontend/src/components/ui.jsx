// Peças pequenas de interface usadas em várias telas.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, RefreshCw, X } from "lucide-react";

export function Botao({ variante = "secundario", tamanho = "md", carregando, icone: Icone, children, className = "", ...props }) {
  const base =
    "inline-flex items-center justify-center gap-2 font-semibold rounded-xl transition-all duration-150 " +
    "disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-roxo/60 cursor-pointer";
  const tamanhos = { sm: "text-xs px-3 py-1.5", md: "text-sm px-4 py-2.5", lg: "text-base px-6 py-3.5" };
  const variantes = {
    primario: "gradiente text-white shadow-[0_8px_24px_-8px_rgba(124,58,237,0.7)] hover:brightness-110 active:scale-[0.98]",
    secundario: "bg-card-2 border border-borda hover:border-borda-forte hover:bg-[#20202a] text-texto",
    fantasma: "text-suave hover:text-texto hover:bg-white/5",
    perigo: "bg-vermelho/10 text-vermelho border border-vermelho/30 hover:bg-vermelho/20",
  };
  return (
    <button className={`${base} ${tamanhos[tamanho]} ${variantes[variante]} ${className}`} disabled={carregando || props.disabled} {...props}>
      {carregando ? <Loader2 className="size-4 animate-spin" /> : Icone ? <Icone className="size-4" /> : null}
      {children}
    </button>
  );
}

export function Chip({ ativo, children, className = "", ...props }) {
  return (
    <button
      type="button"
      className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors cursor-pointer ${
        ativo ? "gradiente border-transparent text-white" : "border-borda text-suave hover:text-texto hover:border-borda-forte bg-card-2"
      } ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

// Seletor segmentado (ex.: Falado | Gameplay)
export function Segmentado({ opcoes, valor, aoMudar, tamanho = "md" }) {
  return (
    <div className="inline-flex p-1 rounded-xl bg-fundo border border-borda gap-1">
      {opcoes.map(({ valor: v, rotulo, icone: Icone }) => (
        <button
          key={v}
          type="button"
          onClick={() => aoMudar(v)}
          className={`flex items-center gap-2 rounded-lg font-semibold transition-all cursor-pointer ${
            tamanho === "sm" ? "px-2.5 py-1 text-xs" : "px-4 py-2 text-sm"
          } ${valor === v ? "gradiente text-white shadow-md" : "text-suave hover:text-texto"}`}
        >
          {Icone && <Icone className="size-4" />}
          {rotulo}
        </button>
      ))}
    </div>
  );
}

export function Alternador({ ativo, aoMudar, rotulo, descricao }) {
  return (
    <label className="flex items-center justify-between gap-4 cursor-pointer select-none py-1">
      <span>
        <span className="text-sm font-medium">{rotulo}</span>
        {descricao && <span className="block text-xs text-apagado mt-0.5">{descricao}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={ativo}
        onClick={() => aoMudar(!ativo)}
        className={`relative w-10 h-6 rounded-full transition-colors shrink-0 cursor-pointer ${ativo ? "gradiente" : "bg-borda-forte"}`}
      >
        <span className={`absolute top-1 size-4 rounded-full bg-white transition-all ${ativo ? "left-5" : "left-1"}`} />
      </button>
    </label>
  );
}

export function Esqueleto({ className = "" }) {
  return <div className={`esqueleto ${className}`} />;
}

export function EstadoVazio({ icone: Icone, titulo, texto, acao }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-20 px-6 animate-surgir">
      <div className="size-16 rounded-2xl bg-card border border-borda flex items-center justify-center mb-5">
        {Icone && <Icone className="size-7 text-suave" />}
      </div>
      <h3 className="text-lg font-semibold">{titulo}</h3>
      {texto && <p className="text-sm text-suave mt-1.5 max-w-sm">{texto}</p>}
      {acao && <div className="mt-6">{acao}</div>}
    </div>
  );
}

export function EstadoErro({ mensagem, aoTentar }) {
  return (
    <div className="cartao p-6 flex items-start gap-4 border-vermelho/30 animate-surgir">
      <div className="size-10 rounded-xl bg-vermelho/10 flex items-center justify-center shrink-0">
        <AlertTriangle className="size-5 text-vermelho" />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="font-semibold">Algo deu errado</h3>
        <p className="text-sm text-suave mt-1 break-words whitespace-pre-wrap">{mensagem}</p>
      </div>
      {aoTentar && (
        <Botao icone={RefreshCw} onClick={aoTentar}>
          Tentar de novo
        </Botao>
      )}
    </div>
  );
}

export function Aviso({ tipo = "info", titulo, children }) {
  const estilos = {
    info: "border-azul/30 bg-azul/5 text-azul",
    alerta: "border-amarelo/30 bg-amarelo/5 text-amarelo",
    erro: "border-vermelho/30 bg-vermelho/5 text-vermelho",
  };
  const Icone = tipo === "info" ? Info : AlertTriangle;
  return (
    <div className={`rounded-xl border px-4 py-3 flex gap-3 text-sm ${estilos[tipo]}`}>
      <Icone className="size-4 mt-0.5 shrink-0" />
      <div className="text-texto/90 min-w-0">
        {titulo && <div className="font-semibold mb-0.5">{titulo}</div>}
        {children}
      </div>
    </div>
  );
}

// Tooltip simples por CSS (aparece ao passar o mouse)
export function Dica({ texto, children, lado = "baixo" }) {
  if (!texto) return children;
  const pos = lado === "cima" ? "bottom-full mb-2" : "top-full mt-2";
  return (
    <span className="relative group/dica inline-flex">
      {children}
      <span
        className={`pointer-events-none absolute ${pos} right-0 z-30 w-60 rounded-xl bg-[#0f0f15] border border-borda-forte px-3 py-2 text-xs leading-relaxed text-texto shadow-suave opacity-0 translate-y-1 group-hover/dica:opacity-100 group-hover/dica:translate-y-0 transition-all`}
      >
        {texto}
      </span>
    </span>
  );
}

// ---------- notificações (toasts)
const ContextoAvisos = createContext(() => {});
export const useAvisar = () => useContext(ContextoAvisos);

export function ProvedorAvisos({ children }) {
  const [lista, setLista] = useState([]);
  const avisar = useCallback((texto, tipo = "ok") => {
    const id = Math.random();
    setLista((l) => [...l, { id, texto, tipo }]);
    setTimeout(() => setLista((l) => l.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ContextoAvisos.Provider value={avisar}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 w-80">
        {lista.map((a) => (
          <div key={a.id} className="cartao px-4 py-3 flex items-start gap-3 shadow-suave animate-surgir">
            {a.tipo === "erro" ? (
              <AlertTriangle className="size-4 text-vermelho mt-0.5 shrink-0" />
            ) : (
              <CheckCircle2 className="size-4 text-verde mt-0.5 shrink-0" />
            )}
            <span className="text-sm flex-1">{a.texto}</span>
            <button className="text-apagado hover:text-texto cursor-pointer" onClick={() => setLista((l) => l.filter((x) => x.id !== a.id))}>
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ContextoAvisos.Provider>
  );
}

// ---------- confirmação modal
export function Confirmar({ aberto, titulo, texto, rotuloOk = "Confirmar", perigo, aoConfirmar, aoFechar, children }) {
  useEffect(() => {
    if (!aberto) return;
    const tecla = (e) => e.key === "Escape" && aoFechar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [aberto, aoFechar]);
  if (!aberto) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={aoFechar}>
      <div className="cartao w-full max-w-md p-6 shadow-suave animate-surgir" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">{titulo}</h3>
        {texto && <p className="text-sm text-suave mt-2">{texto}</p>}
        {children}
        <div className="flex justify-end gap-2 mt-6">
          <Botao variante="fantasma" onClick={aoFechar}>
            Cancelar
          </Botao>
          <Botao variante={perigo ? "perigo" : "primario"} onClick={aoConfirmar}>
            {rotuloOk}
          </Botao>
        </div>
      </div>
    </div>
  );
}

// Polling: chama `buscar` a cada `intervalo` ms enquanto `ativo`
export function usePolling(buscar, intervalo, ativo = true) {
  useEffect(() => {
    if (!ativo) return;
    const id = setInterval(buscar, intervalo);
    return () => clearInterval(id);
  }, [buscar, intervalo, ativo]);
}
