// Prontos: tudo que já dá para postar no canal (cortes e vídeos longos), cada um com o vídeo, a thumbnail, o título
// e a descrição. Postar é: abrir a pasta (o nome do arquivo já é o título) -> arrastar no Studio -> marcar postado.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Copy, ExternalLink, FolderOpen, Inbox, Play, Undo2, X } from "lucide-react";
import { api, formatarDuracao } from "../api";
import { corDaNota } from "../components/ScoreBadge";
import { Botao, Chip, EstadoErro, EstadoVazio, Esqueleto, Segmentado, useAvisar } from "../components/ui";

const POR_PAGINA = 60;

export default function Prontos() {
  const avisar = useAvisar();
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [estado, setEstado] = useState("pendente");
  const [tipo, setTipo] = useState("todos");
  const [projeto, setProjeto] = useState("");
  const [limite, setLimite] = useState(POR_PAGINA);

  const carregar = useCallback(() => {
    api.prontos().then((d) => {
      setDados(d);
      setErro(null);
    }).catch((e) => setErro(e.message));
  }, []);
  useEffect(carregar, [carregar]);

  const acao = useCallback(async (promessa, mensagem) => {
    try {
      setDados(await promessa);
      if (mensagem) avisar(mensagem);
    } catch (e) {
      avisar(e.message, "erro");
    }
  }, [avisar]);

  const projetos = useMemo(() => {
    const vistos = new Map();
    for (const i of dados?.itens || []) if (!vistos.has(i.pid)) vistos.set(i.pid, i.projeto);
    return [...vistos.entries()];
  }, [dados]);

  const visiveis = useMemo(() => (dados?.itens || []).filter((i) =>
    i.estado === estado && (tipo === "todos" || i.tipo === tipo) && (!projeto || i.pid === projeto)), [dados, estado, tipo, projeto]);

  useEffect(() => setLimite(POR_PAGINA), [estado, tipo, projeto]);

  if (erro && !dados) return <div className="max-w-[1400px] mx-auto px-6 py-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!dados) {
    return (
      <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-4">
        <Esqueleto className="h-10 w-64" />
        <Esqueleto className="h-40" />
      </div>
    );
  }

  const { contagem } = dados;
  const longos = visiveis.filter((i) => i.tipo === "longo");
  const curtos = visiveis.filter((i) => i.tipo === "curto").slice(0, limite);
  const sobrando = visiveis.filter((i) => i.tipo === "curto").length - curtos.length;

  return (
    <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">Prontos</h1>
          <p className="text-sm text-suave mt-1">
            {contagem.pendente} para postar · {contagem.postado} postado(s) · {contagem.descartado} descartado(s)
          </p>
        </div>
        <Canal dados={dados} acao={acao} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmentado
          tamanho="sm"
          valor={estado}
          aoMudar={setEstado}
          opcoes={[
            { valor: "pendente", rotulo: `Para postar (${contagem.pendente})` },
            { valor: "postado", rotulo: `Postados (${contagem.postado})` },
            { valor: "descartado", rotulo: `Descartados (${contagem.descartado})` },
          ]}
        />
        <div className="flex gap-2">
          {[["todos", "Tudo"], ["curto", "Cortes"], ["longo", "Longos"]].map(([v, r]) => (
            <Chip key={v} ativo={tipo === v} onClick={() => setTipo(v)}>{r}</Chip>
          ))}
        </div>
        {projetos.length > 1 && (
          <select value={projeto} onChange={(e) => setProjeto(e.target.value)} className="campo !py-1.5 !w-auto max-w-72 cursor-pointer text-sm">
            <option value="">Todos os vídeos</option>
            {projetos.map(([pid, nome]) => <option key={pid} value={pid}>{nome}</option>)}
          </select>
        )}
      </div>

      {!visiveis.length && (
        <EstadoVazio
          icone={Inbox}
          titulo={estado === "pendente" ? "Nada esperando para postar" : estado === "postado" ? "Nada postado ainda" : "Nada descartado"}
          texto={estado === "pendente" ? "Os cortes e vídeos longos aparecem aqui assim que ficam prontos." : undefined}
          acao={estado === "pendente" ? <Link to="/"><Botao variante="primario">Editar um vídeo</Botao></Link> : undefined}
        />
      )}

      {longos.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          {longos.map((i) => <CartaoLongo key={i.chave} item={i} acao={acao} />)}
        </div>
      )}

      {curtos.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5 gap-4">
          {curtos.map((i) => <CartaoCurto key={i.chave} item={i} acao={acao} />)}
        </div>
      )}
      {sobrando > 0 && (
        <div className="flex justify-center">
          <Botao onClick={() => setLimite(limite + POR_PAGINA)}>Mostrar mais {Math.min(sobrando, POR_PAGINA)} de {sobrando}</Botao>
        </div>
      )}
    </div>
  );
}

function Canal({ dados, acao }) {
  const [url, setUrl] = useState(dados.canal.url || "");
  useEffect(() => setUrl(dados.canal.url || ""), [dados.canal.url]);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onBlur={() => url.trim() !== (dados.canal.url || "") && acao(api.salvarCanal(url), "Canal salvo")}
        placeholder="Link do seu canal (youtube.com/@canal)"
        className="campo !py-1.5 w-72 text-sm"
        aria-label="Link do canal"
        title={dados.canal.channel_id ? `Canal ${dados.canal.channel_id}: o Studio abre direto no upload dele` : "Com o link, o Studio abre direto na tela de upload do canal"}
      />
      <a href={dados.studio_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-full bg-white border border-black/10 hover:border-black/25">
        <ExternalLink className="size-4" />Abrir Studio
      </a>
    </div>
  );
}

function useCopiar() {
  const avisar = useAvisar();
  return async (texto, rotulo) => {
    try {
      await navigator.clipboard.writeText(texto);
      avisar(`${rotulo} copiado`);
    } catch {
      avisar("Não consegui copiar", "erro");
    }
  };
}

// Título e descrição editáveis (salvam ao sair do campo) com botão de copiar
function Textos({ item, acao, linhas = 3 }) {
  const copiar = useCopiar();
  const [titulo, setTitulo] = useState(item.titulo);
  const [descricao, setDescricao] = useState(item.descricao);
  useEffect(() => setTitulo(item.titulo), [item.titulo]);
  useEffect(() => setDescricao(item.descricao), [item.descricao]);
  const salvar = (campo, valor) => valor !== item[campo] && acao(api.editarItem(item.chave, { [campo]: valor }));
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-1">
        <textarea
          value={titulo}
          onChange={(e) => setTitulo(e.target.value.replace(/\n/g, " "))}
          onBlur={() => salvar("titulo", titulo)}
          rows={2}
          maxLength={100}
          className="flex-1 min-w-0 resize-none bg-transparent text-sm font-semibold leading-snug rounded-md px-1 -mx-1 hover:bg-black/[0.04] focus:bg-white focus:outline focus:outline-black/15"
          aria-label="Título"
        />
        <button onClick={() => copiar(titulo, "Título")} title="Copiar título" className="p-1 rounded text-suave hover:text-texto cursor-pointer"><Copy className="size-3.5" /></button>
      </div>
      <div className="flex items-start gap-1">
        <textarea
          value={descricao}
          onChange={(e) => setDescricao(e.target.value)}
          onBlur={() => salvar("descricao", descricao)}
          rows={linhas}
          className="flex-1 min-w-0 resize-y bg-transparent text-xs text-suave leading-relaxed rounded-md px-1 -mx-1 hover:bg-black/[0.04] focus:bg-white focus:outline focus:outline-black/15"
          aria-label="Descrição"
        />
        <button onClick={() => copiar(descricao, "Descrição")} title="Copiar descrição" className="p-1 rounded text-suave hover:text-texto cursor-pointer"><Copy className="size-3.5" /></button>
      </div>
    </div>
  );
}

function Acoes({ item, acao }) {
  if (item.estado !== "pendente") {
    return (
      <Botao tamanho="sm" variante="fantasma" icone={Undo2} onClick={() => acao(api.marcarItem(item.chave, "pendente"))}>
        Voltar para “Para postar”
      </Botao>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Botao tamanho="sm" icone={FolderOpen} onClick={() => api.abrirPastaItem(item.chave).catch(() => {})} title="Pasta com o vídeo (nome = título), a thumbnail e a descrição, para arrastar no Studio">
        Pasta
      </Botao>
      <Botao tamanho="sm" variante="primario" icone={Check} onClick={() => acao(api.marcarItem(item.chave, "postado"), "Marcado como postado")}>
        Postado
      </Botao>
      <button onClick={() => acao(api.marcarItem(item.chave, "descartado"), "Descartado")} title="Descartar (não vale postar)" className="ml-auto p-1.5 rounded-lg text-suave hover:text-vermelho hover:bg-vermelho/10 cursor-pointer">
        <X className="size-4" />
      </button>
    </div>
  );
}

function CartaoCurto({ item, acao }) {
  const [tocando, setTocando] = useState(false);
  return (
    <div className={`cartao p-3 flex flex-col gap-3 ${item.estado !== "pendente" ? "opacity-70" : ""}`}>
      <div className="relative aspect-[9/16] rounded-xl overflow-hidden bg-card-2">
        {tocando ? (
          <video src={item.video_url} controls autoPlay className="size-full object-contain bg-black" />
        ) : (
          <button onClick={() => setTocando(true)} className="group size-full cursor-pointer" aria-label="Assistir">
            <img src={item.thumbs_url[0]} alt="" loading="lazy" className="size-full object-cover" />
            <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/25">
              <span className="size-12 rounded-full bg-white/90 flex items-center justify-center"><Play className="size-5 text-black translate-x-0.5" /></span>
            </span>
          </button>
        )}
        {item.nota != null && (
          <span className="absolute top-2 left-2 text-[11px] font-semibold px-1.5 py-0.5 rounded bg-black/70 text-white" style={{ boxShadow: `inset 0 -2px 0 ${corDaNota(item.nota)}` }}>{item.nota}</span>
        )}
        {item.duracao != null && (
          <span className="absolute top-2 right-2 text-[11px] px-1.5 py-0.5 rounded bg-black/70 text-white tabular-nums">{formatarDuracao(item.duracao)}</span>
        )}
      </div>
      <Textos item={item} acao={acao} />
      <div className="mt-auto"><Acoes item={item} acao={acao} /></div>
    </div>
  );
}

function CartaoLongo({ item, acao }) {
  const copiar = useCopiar();
  const [thumb, setThumb] = useState(0);
  const [tocando, setTocando] = useState(false);
  return (
    <div className={`cartao p-4 flex flex-col gap-4 ${item.estado !== "pendente" ? "opacity-70" : ""}`}>
      <div className="flex items-center gap-2 text-xs text-suave">
        <span className="rotulo-mono rounded-full border border-black/10 px-2 py-0.5 text-black/60">Vídeo longo</span>
        <span className="truncate">{item.projeto}</span>
        {item.duracao != null && <span className="ml-auto tabular-nums">{formatarDuracao(item.duracao)}</span>}
      </div>
      <div className="relative aspect-video rounded-xl overflow-hidden bg-card-2">
        {tocando ? (
          <video src={item.video_url} controls autoPlay className="size-full bg-black" />
        ) : (
          <button onClick={() => setTocando(true)} className="group size-full cursor-pointer" aria-label="Assistir">
            {item.thumbs_url[thumb] && <img src={item.thumbs_url[thumb]} alt="" className="size-full object-cover" />}
            <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/25">
              <span className="size-14 rounded-full bg-white/90 flex items-center justify-center"><Play className="size-6 text-black translate-x-0.5" /></span>
            </span>
          </button>
        )}
      </div>
      {item.thumbs_url.length > 1 && (
        <div className="flex gap-2">
          {item.thumbs_url.map((u, k) => (
            <button key={u} onClick={() => { setThumb(k); setTocando(false); }} className={`w-28 aspect-video rounded-lg overflow-hidden border-2 cursor-pointer ${k === thumb ? "border-black" : "border-transparent"}`} title={`Thumbnail ${k + 1} (na pasta: thumbnail_${k + 1}.jpg)`}>
              <img src={u} alt="" className="size-full object-cover" />
            </button>
          ))}
        </div>
      )}
      <Textos item={item} acao={acao} linhas={6} />
      {item.titulos.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs text-apagado self-center">Outros títulos:</span>
          {item.titulos.filter((t) => t && t !== item.titulo).map((t) => (
            <Chip key={t} onClick={() => acao(api.editarItem(item.chave, { titulo: t }))} title="Usar este título">{t}</Chip>
          ))}
        </div>
      )}
      {item.tags.length > 0 && (
        <button onClick={() => copiar(item.tags.join(", "), "Tags")} className="text-left text-xs text-suave hover:text-texto cursor-pointer" title="Copiar tags">
          <Copy className="inline size-3 mr-1" />Tags: {item.tags.join(", ")}
        </button>
      )}
      <Acoes item={item} acao={acao} />
    </div>
  );
}
