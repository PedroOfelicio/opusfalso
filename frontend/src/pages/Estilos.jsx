// Estilos: lista de presets de legenda com preview ao vivo; criar, duplicar, editar e excluir.
import { useEffect, useMemo, useState } from "react";
import { Copy, Palette, Plus, Save, Trash2 } from "lucide-react";
import { api } from "../api";
import PreviewLegenda from "../components/PreviewLegenda";
import { Alternador, Botao, Confirmar, EstadoErro, Esqueleto, Segmentado, useAvisar } from "../components/ui";

function Faixa({ rotulo, valor, min, max, passo = 1, aoMudar, formato = (v) => v }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-suave">{rotulo}</span>
        <span className="tabular-nums font-semibold">{formato(valor)}</span>
      </div>
      <input type="range" min={min} max={max} step={passo} value={valor} onChange={(e) => aoMudar(Number(e.target.value))} className="w-full accent-roxo cursor-pointer" />
    </div>
  );
}

function Cor({ rotulo, valor, aoMudar }) {
  return (
    <label className="flex items-center gap-3 rounded-xl border border-borda bg-fundo px-3 py-2 cursor-pointer hover:border-borda-forte">
      <input type="color" value={valor} onChange={(e) => aoMudar(e.target.value.toUpperCase())} className="size-7 rounded-md bg-transparent cursor-pointer border-0 p-0" />
      <span className="flex-1 min-w-0">
        <span className="block text-xs text-suave">{rotulo}</span>
        <span className="block text-sm font-mono">{valor}</span>
      </span>
    </label>
  );
}

const idValido = (id) => /^[a-z0-9_-]{2,30}$/.test(id);

export default function Estilos() {
  const avisar = useAvisar();
  const [estilos, setEstilos] = useState(null);
  const [fontes, setFontes] = useState([]);
  const [erro, setErro] = useState(null);
  const [selecionado, setSelecionado] = useState(null);
  const [rascunho, setRascunho] = useState(null);
  const [novoId, setNovoId] = useState(null); // id editável enquanto o preset ainda não foi salvo
  const [salvando, setSalvando] = useState(false);
  const [excluindo, setExcluindo] = useState(false);
  const [fundo, setFundo] = useState(null); // miniatura de um projeto para o preview

  const carregar = () =>
    Promise.all([api.estilos(), api.fontes()])
      .then(([e, f]) => {
        setEstilos(e);
        setFontes(f);
        const primeiro = Object.keys(e)[0];
        setSelecionado((s) => (s && e[s] ? s : primeiro));
        setRascunho((r) => r ?? structuredClone(e[primeiro]));
      })
      .catch((e) => setErro(e.message));
  useEffect(() => {
    carregar();
    api.projetos().then((l) => l[0] && setFundo(l[0].thumb_url)).catch(() => {});
  }, []);

  const alterado = useMemo(
    () => novoId !== null || (estilos && selecionado && JSON.stringify(estilos[selecionado]) !== JSON.stringify(rascunho)),
    [estilos, selecionado, rascunho, novoId],
  );

  const escolher = (id) => {
    setSelecionado(id);
    setRascunho(structuredClone(estilos[id]));
    setNovoId(null);
  };
  const mudar = (caminho, valor) =>
    setRascunho((r) => {
      const copia = structuredClone(r);
      const partes = caminho.split(".");
      let alvo = copia;
      partes.slice(0, -1).forEach((p) => (alvo = alvo[p] ??= {}));
      alvo[partes.at(-1)] = valor;
      return copia;
    });

  const duplicar = (base) => {
    let id = `${selecionado}_copia`;
    for (let n = 2; estilos[id]; n++) id = `${selecionado}_copia${n}`;
    setRascunho({ ...structuredClone(base), nome: `${base.nome || selecionado} (cópia)` });
    setNovoId(id);
    setSelecionado(null);
  };

  const salvar = async () => {
    const id = novoId ?? selecionado;
    if (!idValido(id)) return avisar("Identificador inválido: use 2-30 letras minúsculas, números, - ou _", "erro");
    if (novoId && estilos[novoId]) return avisar("Já existe um estilo com esse identificador", "erro");
    setSalvando(true);
    try {
      const atualizados = await api.salvarEstilo(id, rascunho);
      setEstilos(atualizados);
      setSelecionado(id);
      setNovoId(null);
      avisar("Estilo salvo");
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setSalvando(false);
    }
  };

  const excluir = async () => {
    setExcluindo(false);
    try {
      const atualizados = await api.excluirEstilo(selecionado);
      setEstilos(atualizados);
      const primeiro = Object.keys(atualizados)[0];
      setSelecionado(primeiro);
      setRascunho(structuredClone(atualizados[primeiro]));
      avisar("Estilo excluído");
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  if (erro) return <div className="max-w-4xl mx-auto p-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!estilos || !rascunho)
    return (
      <div className="max-w-6xl mx-auto p-8 grid grid-cols-[260px_1fr] gap-6">
        <Esqueleto className="h-96" />
        <Esqueleto className="h-[600px]" />
      </div>
    );

  const r = rascunho;
  return (
    <div className="max-w-[1300px] mx-auto px-6 lg:px-8 py-8">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight">Estilos de legenda</h1>
          <p className="text-sm text-suave mt-1">Presets usados pela IA e pelo editor. Salvos em backend/estilos.json.</p>
        </div>
        <Botao icone={Plus} onClick={() => duplicar(estilos.opus || Object.values(estilos)[0])}>Novo estilo</Botao>
      </div>

      <div className="grid lg:grid-cols-[250px_1fr] gap-6 items-start">
        {/* Lista */}
        <div className="cartao p-2 space-y-1 lg:sticky lg:top-6">
          {novoId && (
            <div className="rounded-xl px-3 py-2.5 gradiente text-white">
              <div className="text-sm font-semibold truncate">{r.nome}</div>
              <div className="text-xs opacity-80">Novo (não salvo)</div>
            </div>
          )}
          {Object.entries(estilos).map(([id, e]) => (
            <button
              key={id}
              onClick={() => escolher(id)}
              className={`w-full text-left rounded-xl px-3 py-2.5 transition-colors cursor-pointer ${selecionado === id ? "bg-roxo/15 border border-roxo/40" : "border border-transparent hover:bg-white/5"}`}
            >
              <div className="flex items-center gap-2">
                <span className="size-3 rounded-full shrink-0" style={{ background: e.cor_destaque }} />
                <span className="text-sm font-semibold truncate">{e.nome || id}</span>
              </div>
              <div className="text-xs text-apagado mt-0.5 line-clamp-2">{e.descricao || e.fonte}</div>
            </button>
          ))}
        </div>

        {/* Editor + preview */}
        <div className="cartao p-6 grid xl:grid-cols-[1fr_auto] gap-8">
          <div className="space-y-6 min-w-0">
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="rotulo">Nome</label>
                <input value={r.nome || ""} onChange={(e) => mudar("nome", e.target.value)} className="campo mt-2" />
              </div>
              <div>
                <label className="rotulo">Identificador</label>
                <input
                  value={novoId ?? selecionado}
                  disabled={novoId === null}
                  onChange={(e) => setNovoId(e.target.value.toLowerCase())}
                  className={`campo mt-2 font-mono text-[13px] disabled:opacity-60 ${novoId !== null && !idValido(novoId) ? "!border-vermelho" : ""}`}
                />
              </div>
              <div className="sm:col-span-2">
                <label className="rotulo">Descrição</label>
                <input value={r.descricao || ""} onChange={(e) => mudar("descricao", e.target.value)} className="campo mt-2" />
              </div>
            </div>

            <div>
              <div className="rotulo mb-3">Texto</div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-suave">Fonte</label>
                  <select
                    value={r.arquivo_fonte}
                    onChange={(e) => {
                      const f = fontes.find((x) => x.arquivo === e.target.value);
                      setRascunho({ ...r, arquivo_fonte: f.arquivo, fonte: f.nome });
                    }}
                    className="campo mt-1.5 cursor-pointer"
                  >
                    {fontes.map((f) => <option key={f.arquivo} value={f.arquivo}>{f.nome}</option>)}
                  </select>
                </div>
                <div className="flex items-end pb-1">
                  <Alternador ativo={!!r.maiusculas} aoMudar={(v) => mudar("maiusculas", v)} rotulo="MAIÚSCULAS" />
                </div>
                <Faixa rotulo="Tamanho" valor={r.tamanho} min={40} max={160} aoMudar={(v) => mudar("tamanho", v)} formato={(v) => `${v}px`} />
                <Faixa rotulo="Palavras por vez" valor={r.palavras_por_vez || 3} min={1} max={5} aoMudar={(v) => mudar("palavras_por_vez", v)} />
                <Faixa rotulo="Contorno" valor={r.contorno} min={0} max={16} aoMudar={(v) => mudar("contorno", v)} />
                <Faixa rotulo="Sombra" valor={r.sombra} min={0} max={14} aoMudar={(v) => mudar("sombra", v)} />
                <Faixa rotulo="Posição vertical" valor={r.posicao_y} min={0.4} max={0.85} passo={0.01} aoMudar={(v) => mudar("posicao_y", v)} formato={(v) => `${Math.round(v * 100)}%`} />
              </div>
            </div>

            <div>
              <div className="rotulo mb-3">Cores</div>
              <div className="grid sm:grid-cols-3 gap-3">
                <Cor rotulo="Texto" valor={r.cor_texto} aoMudar={(v) => mudar("cor_texto", v)} />
                <Cor rotulo="Palavra falada" valor={r.cor_destaque} aoMudar={(v) => mudar("cor_destaque", v)} />
                <Cor rotulo="Contorno" valor={r.cor_contorno} aoMudar={(v) => mudar("cor_contorno", v)} />
              </div>
            </div>

            <div>
              <div className="rotulo mb-3">Animação da palavra falada</div>
              <div className="flex flex-wrap items-center gap-5">
                <Segmentado
                  tamanho="sm"
                  valor={r.animacao}
                  aoMudar={(v) => mudar("animacao", v)}
                  opcoes={[{ valor: "pop", rotulo: "Pop" }, { valor: "fade", rotulo: "Revelar" }, { valor: "nenhuma", rotulo: "Só cor" }]}
                />
                {r.animacao === "pop" && (
                  <div className="flex-1 min-w-48 grid grid-cols-2 gap-4">
                    <Faixa rotulo="Escala do pop" valor={r.escala_pop} min={1} max={1.4} passo={0.01} aoMudar={(v) => mudar("escala_pop", v)} formato={(v) => `${Math.round(v * 100)}%`} />
                    <Faixa rotulo="Duração" valor={r.duracao_pop_ms} min={60} max={300} passo={10} aoMudar={(v) => mudar("duracao_pop_ms", v)} formato={(v) => `${v}ms`} />
                  </div>
                )}
              </div>
            </div>

            <div>
              <div className="rotulo mb-3">Título gancho e barra</div>
              <div className="grid sm:grid-cols-3 gap-3">
                <Cor rotulo="Fundo do título" valor={r.titulo?.cor_fundo || "#FFE600"} aoMudar={(v) => mudar("titulo.cor_fundo", v)} />
                <Cor rotulo="Texto do título" valor={r.titulo?.cor_texto || "#000000"} aoMudar={(v) => mudar("titulo.cor_texto", v)} />
                <Faixa rotulo="Tamanho do título" valor={r.titulo?.tamanho || 64} min={36} max={100} aoMudar={(v) => mudar("titulo.tamanho", v)} formato={(v) => `${v}px`} />
              </div>
              <div className="grid sm:grid-cols-2 gap-4 mt-4">
                <Alternador ativo={!!r.barra_progresso?.ativa} aoMudar={(v) => mudar("barra_progresso.ativa", v)} rotulo="Barra de progresso" descricao="Linha fina no topo, na cor de destaque" />
                {r.barra_progresso?.ativa && (
                  <Faixa rotulo="Espessura" valor={r.barra_progresso?.altura || 10} min={4} max={24} aoMudar={(v) => mudar("barra_progresso.altura", v)} formato={(v) => `${v}px`} />
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2 pt-4 border-t border-borda">
              <Botao variante="primario" icone={Save} onClick={salvar} carregando={salvando} disabled={!alterado}>
                {novoId ? "Criar estilo" : "Salvar alterações"}
              </Botao>
              {!novoId && <Botao icone={Copy} onClick={() => duplicar(r)}>Duplicar</Botao>}
              {novoId ? (
                <Botao variante="fantasma" onClick={() => escolher(Object.keys(estilos)[0])}>Descartar</Botao>
              ) : (
                <Botao variante="perigo" icone={Trash2} onClick={() => setExcluindo(true)} disabled={Object.keys(estilos).length <= 1}>Excluir</Botao>
              )}
            </div>
          </div>

          <div className="flex flex-col items-center gap-3 xl:sticky xl:top-6 self-start">
            <PreviewLegenda estilo={r} largura={280} fundo={fundo} />
            <span className="text-xs text-apagado inline-flex items-center gap-1.5"><Palette className="size-3.5" /> Preview ao vivo</span>
          </div>
        </div>
      </div>

      <Confirmar aberto={excluindo} titulo={`Excluir o estilo “${r.nome}”?`} texto="Clipes que usam esse preset passam a usar o primeiro da lista." rotuloOk="Excluir" perigo aoConfirmar={excluir} aoFechar={() => setExcluindo(false)} />
    </div>
  );
}
