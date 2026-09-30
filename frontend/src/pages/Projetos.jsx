// Meus projetos: grade de cards com busca e filtro por status.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Clapperboard, Gamepad2, Mic, Plus, Search, Trash2 } from "lucide-react";
import { api, formatarData, formatarDuracao } from "../api";
import { corDaNota } from "../components/ScoreBadge";
import { Alternador, Botao, Chip, Confirmar, EstadoErro, EstadoVazio, Esqueleto, usePolling, useAvisar } from "../components/ui";

const STATUS = {
  pronto: { rotulo: "Pronto", cor: "bg-verde/15 text-verde" },
  processando: { rotulo: "Processando", cor: "bg-azul/15 text-azul" },
  fila: { rotulo: "Na fila", cor: "bg-azul/15 text-azul" },
  erro: { rotulo: "Erro", cor: "bg-vermelho/15 text-vermelho" },
  cancelado: { rotulo: "Cancelado", cor: "bg-white/10 text-suave" },
};
const FILTROS = { todos: "Todos", pronto: "Prontos", processando: "Processando", erro: "Com erro", cancelado: "Cancelados" };

export default function Projetos() {
  const navegar = useNavigate();
  const avisar = useAvisar();
  const [lista, setLista] = useState(null);
  const [erro, setErro] = useState(null);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState("todos");
  const [excluindo, setExcluindo] = useState(null);
  const [apagarSaida, setApagarSaida] = useState(false);

  const carregar = useCallback(() => {
    api.projetos().then((l) => {
      setLista(l);
      setErro(null);
    }).catch((e) => setErro(e.message));
  }, []);
  useEffect(carregar, [carregar]);
  usePolling(carregar, 2000, !!lista?.some((p) => ["fila", "processando"].includes(p.status)));

  const visiveis = useMemo(() => {
    if (!lista) return [];
    const termo = busca.trim().toLowerCase();
    return lista.filter(
      (p) =>
        (filtro === "todos" || p.status === filtro || (filtro === "processando" && p.status === "fila")) &&
        (!termo || p.nome.toLowerCase().includes(termo)),
    );
  }, [lista, busca, filtro]);

  const excluir = async () => {
    const p = excluindo;
    setExcluindo(null);
    try {
      await api.excluirProjeto(p.id, apagarSaida);
      avisar("Projeto excluído");
      carregar();
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  return (
    <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight">Meus projetos</h1>
          <p className="text-sm text-suave mt-1">{lista ? `${lista.length} projeto(s)` : "Carregando…"}</p>
        </div>
        <Botao variante="primario" icone={Plus} onClick={() => navegar("/")}>Novo projeto</Botao>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="relative flex-1 min-w-60 max-w-md">
          <Search className="size-4 text-apagado absolute left-3 top-1/2 -translate-y-1/2" />
          <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar projeto…" className="campo !pl-9" />
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(FILTROS).map(([k, r]) => (
            <Chip key={k} ativo={filtro === k} onClick={() => setFiltro(k)}>{r}</Chip>
          ))}
        </div>
      </div>

      {erro && !lista ? (
        <EstadoErro mensagem={erro} aoTentar={carregar} />
      ) : !lista ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="cartao overflow-hidden">
              <Esqueleto className="aspect-video !rounded-none" />
              <div className="p-4 space-y-2">
                <Esqueleto className="h-4 w-2/3" />
                <Esqueleto className="h-3 w-1/3" />
              </div>
            </div>
          ))}
        </div>
      ) : visiveis.length === 0 ? (
        <EstadoVazio
          icone={lista.length ? Search : Clapperboard}
          titulo={lista.length ? "Nada encontrado" : "Nenhum projeto ainda"}
          texto={lista.length ? "Tente outra busca ou filtro." : "Envie seu primeiro vídeo e deixe a IA achar os melhores momentos."}
          acao={!lista.length && <Botao variante="primario" icone={Plus} onClick={() => navegar("/")}>Criar projeto</Botao>}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {visiveis.map((p) => {
            const st = STATUS[p.status] || STATUS.cancelado;
            const rodando = ["fila", "processando"].includes(p.status);
            return (
              <Link key={p.id} to={`/projetos/${p.id}`} className="group cartao overflow-hidden hover:border-borda-forte hover:-translate-y-0.5 hover:shadow-suave transition-all animate-surgir">
                <div className="relative aspect-video bg-card-2 overflow-hidden">
                  <img src={p.thumb_url} alt="" className="size-full object-cover group-hover:scale-[1.03] transition-transform duration-500" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                  <span className={`absolute top-3 left-3 text-[11px] font-semibold px-2 py-0.5 rounded-md backdrop-blur ${st.cor}`}>{st.rotulo}</span>
                  {p.duracao_video && (
                    <span className="absolute bottom-3 right-3 text-[11px] font-semibold bg-black/70 px-2 py-0.5 rounded-md tabular-nums">{formatarDuracao(p.duracao_video)}</span>
                  )}
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      setApagarSaida(false);
                      setExcluindo(p);
                    }}
                    className="absolute top-2.5 right-2.5 p-1.5 rounded-lg bg-black/60 text-suave hover:text-vermelho opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                    aria-label="Excluir projeto"
                  >
                    <Trash2 className="size-4" />
                  </button>
                  {rodando && (
                    <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
                      <div className="h-full gradiente transition-all" style={{ width: `${(p.progresso || 0) * 100}%` }} />
                    </div>
                  )}
                </div>
                <div className="p-4">
                  <div className="font-semibold truncate">{p.nome}</div>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-suave">
                    <span className="inline-flex items-center gap-1">
                      {p.modo === "gameplay" ? <Gamepad2 className="size-3.5" /> : <Mic className="size-3.5" />}
                      {formatarData(p.criado_em)}
                    </span>
                    <span className="ml-auto inline-flex items-center gap-1.5">
                      {rodando ? `${Math.round((p.progresso || 0) * 100)}%` : `${p.num_clips} clipe(s)`}
                      {p.num_clips > 0 && <span className="size-2 rounded-full" style={{ background: corDaNota(p.melhor_nota) }} title={`Melhor nota: ${p.melhor_nota}`} />}
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <Confirmar aberto={!!excluindo} titulo={`Excluir “${excluindo?.nome}”?`} texto="Remove o projeto da lista e os arquivos temporários." rotuloOk="Excluir" perigo aoConfirmar={excluir} aoFechar={() => setExcluindo(null)}>
        <div className="mt-4 rounded-xl border border-borda p-3">
          <Alternador ativo={apagarSaida} aoMudar={setApagarSaida} rotulo="Apagar também os clipes exportados" descricao="Os arquivos na pasta de saída" />
        </div>
      </Confirmar>
    </div>
  );
}
