// Postar: fila do dia nos canais do YouTube, sem a API. Cada canal recebe os seus clipes (nenhum se repete) e a
// postagem é: abrir a pasta -> abrir o Studio e arrastar os vídeos (o título vem do nome do arquivo) -> marcar.
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, ExternalLink, FolderOpen, Plus, Shuffle, Trash2, Undo2, X } from "lucide-react";
import { api } from "../api";
import { corDaNota } from "../components/ScoreBadge";
import { Aviso, Botao, Confirmar, EstadoErro, Esqueleto, useAvisar } from "../components/ui";

export default function Postar() {
  const avisar = useAvisar();
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [montando, setMontando] = useState(false);

  const carregar = useCallback(() => {
    api.postagem().then((d) => {
      setDados(d);
      setErro(null);
    }).catch((e) => setErro(e.message));
  }, []);
  useEffect(carregar, [carregar]);

  const acao = async (promessa, mensagem) => {
    try {
      setDados(await promessa);
      if (mensagem) avisar(mensagem);
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  const montar = async () => {
    setMontando(true);
    await acao(api.montarFila(), "Fila de hoje montada");
    setMontando(false);
  };

  if (erro && !dados) return <div className="max-w-[1400px] mx-auto px-6 py-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!dados) {
    return (
      <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-4">
        <Esqueleto className="h-10 w-64" />
        <Esqueleto className="h-40" />
      </div>
    );
  }

  const feitos = dados.fila.filter((i) => i.postado).length;
  const naFila = dados.fila.reduce((s, i) => s + i.clips.length, 0);
  return (
    <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">Postar</h1>
          <p className="text-sm text-suave mt-1">
            {dados.disponiveis} clipe(s) prontos esperando · {naFila} na fila de hoje · {dados.postados_total} já postados
          </p>
        </div>
        <Botao variante="primario" icone={Shuffle} onClick={montar} carregando={montando} disabled={!dados.canais.some((c) => c.ativo)}>
          {dados.fila.length ? "Refazer a fila de hoje" : "Montar a fila de hoje"}
        </Botao>
      </div>

      <Aviso titulo="Como postar em ~1 minuto por canal">
        <b>1.</b> Abrir pasta · <b>2.</b> Abrir Studio e arrastar todos os vídeos da pasta de uma vez (o título já vem do nome
        do arquivo) · <b>3.</b> Marcar como postado. Dica: em cada canal, configure uma vez em Studio &gt; Configurações &gt;
        Padrões de upload a visibilidade <b>Pública</b> e uma descrição com #shorts; assim não precisa digitar nada.
      </Aviso>

      <Canais dados={dados} acao={acao} />

      {dados.fila.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold">Fila de hoje</h2>
            <div className="flex-1 max-w-xs h-1.5 rounded-full bg-black/[0.07] overflow-hidden">
              <div className="h-full gradiente transition-all" style={{ width: `${(feitos / dados.fila.length) * 100}%` }} />
            </div>
            <span className="rotulo-mono text-black/50">{feitos} de {dados.fila.length} canais</span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-5">
            {dados.fila.map((item, k) => <CartaoCanal key={item.canal.id} item={item} numero={k + 1} acao={acao} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function Canais({ dados, acao }) {
  const [novo, setNovo] = useState({ nome: "", url: "", por_dia: 5 });
  const [apagando, setApagando] = useState(null);

  const adicionar = async (e) => {
    e.preventDefault();
    if (!novo.nome.trim()) return;
    await acao(api.criarCanal(novo), "Canal adicionado");
    setNovo({ nome: "", url: "", por_dia: novo.por_dia });
  };

  return (
    <section className="cartao p-5">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="text-lg font-semibold">Canais <span className="text-suave font-normal text-sm">({dados.canais.length})</span></h2>
        <span className="text-xs text-apagado">O link do canal faz o “Abrir Studio” cair direto no upload dele</span>
      </div>
      {dados.canais.length > 0 && (
        <div className="divide-y divide-borda mb-4">
          {dados.canais.map((c) => (
            <div key={c.id} className="flex flex-wrap items-center gap-2 py-2">
              <input defaultValue={c.nome} onBlur={(e) => e.target.value !== c.nome && acao(api.editarCanal(c.id, { nome: e.target.value }))} className="campo !py-1.5 flex-1 min-w-40" aria-label="Nome do canal" />
              <input defaultValue={c.url} placeholder="youtube.com/@canal" onBlur={(e) => e.target.value !== c.url && acao(api.editarCanal(c.id, { url: e.target.value }))} className="campo !py-1.5 flex-[2] min-w-56" aria-label="Link do canal" />
              <label className="flex items-center gap-1.5 text-xs text-suave">
                <input type="number" min={1} max={50} defaultValue={c.por_dia} onBlur={(e) => Number(e.target.value) !== c.por_dia && acao(api.editarCanal(c.id, { por_dia: Number(e.target.value) || 5 }))} className="campo !py-1.5 !w-16 text-center" />
                por dia
              </label>
              <span className={`text-[11px] px-2 py-0.5 rounded-md ${c.channel_id ? "bg-verde/15 text-verde" : "bg-amarelo/15 text-amarelo"}`} title={c.channel_id || "Sem o id do canal: o Studio abre no canal que estiver selecionado"}>
                {c.channel_id ? "link ok" : "sem link"}
              </span>
              <button onClick={() => acao(api.editarCanal(c.id, { ativo: !c.ativo }))} className={`text-xs px-2.5 py-1 rounded-full border cursor-pointer ${c.ativo ? "border-borda text-texto" : "border-borda text-apagado line-through"}`}>
                {c.ativo ? "ativo" : "pausado"}
              </button>
              <button onClick={() => setApagando(c)} className="p-1.5 rounded-lg text-suave hover:text-vermelho hover:bg-vermelho/10 cursor-pointer" aria-label="Remover canal">
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>
      )}
      <form onSubmit={adicionar} className="flex flex-wrap items-center gap-2">
        <input value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} placeholder="Nome do canal" className="campo !py-1.5 flex-1 min-w-40" />
        <input value={novo.url} onChange={(e) => setNovo({ ...novo, url: e.target.value })} placeholder="Link (youtube.com/@canal ou /channel/UC...)" className="campo !py-1.5 flex-[2] min-w-56" />
        <label className="flex items-center gap-1.5 text-xs text-suave">
          <input type="number" min={1} max={50} value={novo.por_dia} onChange={(e) => setNovo({ ...novo, por_dia: Number(e.target.value) || 5 })} className="campo !py-1.5 !w-16 text-center" />
          por dia
        </label>
        <Botao type="submit" tamanho="sm" icone={Plus} disabled={!novo.nome.trim()}>Adicionar</Botao>
      </form>
      <Confirmar
        aberto={!!apagando}
        titulo={`Remover “${apagando?.nome}”?`}
        texto="Sai da lista e da fila de hoje. O que já foi postado continua marcado como postado."
        rotuloOk="Remover"
        perigo
        aoConfirmar={() => {
          acao(api.excluirCanal(apagando.id), "Canal removido");
          setApagando(null);
        }}
        aoFechar={() => setApagando(null)}
      />
    </section>
  );
}

function CartaoCanal({ item, numero, acao }) {
  const avisar = useAvisar();
  const { canal, clips, postado } = item;

  const copiar = async (texto, rotulo) => {
    try {
      await navigator.clipboard.writeText(texto);
      avisar(`${rotulo} copiado`);
    } catch {
      avisar("Não consegui copiar", "erro");
    }
  };

  return (
    <div className={`cartao p-4 flex flex-col gap-3 transition-opacity ${postado ? "opacity-55" : ""}`}>
      <div className="flex items-center gap-3">
        <span className={`size-8 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${postado ? "bg-verde text-white" : "bg-black/[0.06]"}`}>
          {postado ? <Check className="size-4" /> : numero}
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold truncate">{canal.nome}</div>
          <div className="text-xs text-suave">{clips.length} vídeo(s){!canal.channel_id && " · sem link: confira o canal no Studio"}</div>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {clips.map((c) => (
          <div key={c.chave} className="group relative w-24 shrink-0">
            <a href={c.video_url} target="_blank" rel="noreferrer" className="block aspect-[9/16] rounded-lg overflow-hidden bg-card-2">
              <img src={c.thumb_url} alt="" className="size-full object-cover" />
            </a>
            <span className="absolute top-1 left-1 text-[10px] font-semibold px-1.5 rounded bg-black/70 text-white" style={{ boxShadow: `inset 0 -2px 0 ${corDaNota(c.nota)}` }}>{c.nota}</span>
            {!postado && (
              <div className="absolute top-1 right-1 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => copiar(c.descricao, "Descrição")} title="Copiar descrição" className="p-1 rounded bg-black/70 text-white cursor-pointer"><Copy className="size-3" /></button>
                <button onClick={() => acao(api.pularClipe(c.chave), "Clipe tirado da fila")} title="Pular este clipe (nunca mais entra na fila)" className="p-1 rounded bg-black/70 text-white hover:text-vermelho cursor-pointer"><X className="size-3" /></button>
              </div>
            )}
            <button onClick={() => copiar(c.titulo, "Título")} title="Copiar título" className="mt-1 text-[11px] leading-tight text-left line-clamp-2 hover:underline cursor-pointer">{c.titulo || "(sem título)"}</button>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 mt-auto">
        {postado ? (
          <Botao tamanho="sm" variante="fantasma" icone={Undo2} onClick={() => acao(api.marcarPostado(canal.id, false))}>Desfazer</Botao>
        ) : (
          <>
            <Botao tamanho="sm" icone={FolderOpen} onClick={() => acao(api.abrirPastaCanal(canal.id).then(() => api.postagem()))}>1. Abrir pasta</Botao>
            <a href={item.studio_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full bg-white border border-black/10 hover:border-black/25">
              <ExternalLink className="size-4" />2. Abrir Studio
            </a>
            <Botao tamanho="sm" variante="primario" icone={Check} onClick={() => acao(api.marcarPostado(canal.id, true), `${canal.nome}: postado`)}>3. Postado</Botao>
          </>
        )}
      </div>
    </div>
  );
}
