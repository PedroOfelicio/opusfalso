// Card de um clipe: preview ao passar o mouse, nota viral, título editável e ações.
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Copy, Download, ImageDown, Loader2, Pencil, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import { formatarDuracao } from "../api";
import ScoreBadge from "./ScoreBadge";
import { Dica } from "./ui";

const ASPECTOS = { "9:16": "aspect-[9/16]", "1:1": "aspect-square", "16:9": "aspect-video" };

export default function VideoCard({ clip, projetoId, selecionado, aoSelecionar, aoSalvarTitulo, aoRegenerar, aoExcluir }) {
  const video = useRef(null);
  const [emFoco, setEmFoco] = useState(false);
  const [editando, setEditando] = useState(false);
  const [titulo, setTitulo] = useState(clip.titulo);
  const [copiado, setCopiado] = useState(false);
  const textoPost = [clip.legenda_post, (clip.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
  const copiarPost = async () => {
    try {
      await navigator.clipboard.writeText(textoPost);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    } catch {
      /* sem permissão de área de transferência: não faz nada */
    }
  };
  const ocupado = clip.status === "fila" || clip.status === "renderizando";
  const formato = clip.config_efetiva?.formato || "9:16";

  const entrar = () => {
    setEmFoco(true);
    video.current?.play().catch(() => {});
  };
  const sair = () => {
    setEmFoco(false);
    if (video.current) {
      video.current.pause();
      video.current.currentTime = 0;
    }
  };
  const salvar = () => {
    setEditando(false);
    const novo = titulo.trim();
    if (novo && novo !== clip.titulo) aoSalvarTitulo(novo);
    else setTitulo(clip.titulo);
  };

  return (
    <div className={`group cartao overflow-hidden transition-all duration-200 animate-surgir hover:-translate-y-0.5 hover:shadow-suave ${selecionado ? "ring-2 ring-roxo border-transparent" : "hover:border-borda-forte"}`}>
      <div className={`relative ${ASPECTOS[formato]} bg-black overflow-hidden`} onMouseEnter={entrar} onMouseLeave={sair}>
        {clip.thumb_url && <img src={clip.thumb_url} alt="" className={`absolute inset-0 size-full object-cover transition-opacity ${emFoco ? "opacity-0" : "opacity-100"}`} />}
        {clip.video_url && (
          <video ref={video} src={clip.video_url} muted loop playsInline preload="none" className={`absolute inset-0 size-full object-cover transition-opacity ${emFoco ? "opacity-100" : "opacity-0"}`} />
        )}
        <div className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-black/60 to-transparent pointer-events-none" />
        <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/70 to-transparent pointer-events-none" />

        <button
          onClick={aoSelecionar}
          className={`absolute top-3 left-3 size-6 rounded-md border-2 flex items-center justify-center transition-all cursor-pointer ${
            selecionado ? "gradiente border-transparent" : "border-white/60 bg-black/30 opacity-0 group-hover:opacity-100"
          }`}
          aria-label="Selecionar clipe"
        >
          {selecionado && <Check className="size-4 text-white" />}
        </button>
        <div className="absolute top-2.5 right-2.5">
          <ScoreBadge nota={clip.nota} justificativa={clip.justificativa} />
        </div>
        <span className="absolute bottom-2.5 right-2.5 text-xs font-semibold bg-black/70 backdrop-blur px-2 py-0.5 rounded-md tabular-nums">
          {formatarDuracao(clip.duracao)}
        </span>
        {clip.config_efetiva?.estilo === "animada" && (
          <span className="absolute bottom-2.5 left-2.5 text-[10px] font-bold uppercase tracking-wider bg-black/70 backdrop-blur px-2 py-0.5 rounded-md text-roxo">
            animada
          </span>
        )}

        {ocupado && (
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm flex flex-col items-center justify-center gap-3">
            <Loader2 className="size-8 animate-spin text-roxo" />
            <div className="text-sm font-semibold">{clip.status === "fila" ? "Na fila…" : `Renderizando ${Math.round((clip.progresso || 0) * 100)}%`}</div>
            <div className="w-2/3 h-1 rounded-full bg-white/10 overflow-hidden">
              <div className="h-full gradiente transition-all" style={{ width: `${(clip.progresso || 0) * 100}%` }} />
            </div>
          </div>
        )}
        {clip.sem_arquivo && !ocupado && (
          <div className="absolute inset-0 bg-black/70 flex flex-col items-center justify-center text-center p-4 gap-1">
            <div className="text-sm font-semibold">Arquivo não encontrado</div>
            <div className="text-xs text-suave">Foi apagado ou movido da pasta de saída</div>
          </div>
        )}
        {clip.status === "erro" && !ocupado && (
          <div className="absolute inset-0 bg-black/75 flex flex-col items-center justify-center gap-2 p-4 text-center">
            <TriangleAlert className="size-7 text-vermelho" />
            <div className="text-xs text-suave line-clamp-4">{clip.erro || "Falha ao renderizar"}</div>
          </div>
        )}
      </div>

      <div className="p-3.5">
        {editando ? (
          <input
            autoFocus
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            onBlur={salvar}
            onKeyDown={(e) => {
              if (e.key === "Enter") salvar();
              if (e.key === "Escape") {
                setTitulo(clip.titulo);
                setEditando(false);
              }
            }}
            className="campo !py-1.5 text-sm font-semibold"
          />
        ) : (
          <button onClick={() => setEditando(true)} className="w-full text-left text-sm font-semibold leading-snug line-clamp-2 min-h-[2.5rem] hover:text-white group/titulo cursor-text" title="Clique para editar o título">
            {clip.titulo || <span className="text-apagado">Sem título</span>}
            <Pencil className="inline size-3 ml-1.5 text-apagado opacity-0 group-hover/titulo:opacity-100" />
          </button>
        )}
        {clip.hashtags?.length > 0 && <div className="text-xs text-apagado truncate mt-1" title={textoPost}>{clip.hashtags.join(" ")}</div>}
        <div className="flex items-center gap-1 mt-3 -mx-1">
          <Dica texto="Baixar" lado="cima">
            <a
              href={clip.video_url ? `${clip.video_url.split("?")[0]}?download=true` : undefined}
              className={`p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5 ${!clip.video_url && "pointer-events-none opacity-40"}`}
            >
              <Download className="size-4" />
            </a>
          </Dica>
          {clip.capa_url && (
            <Dica texto="Baixar a capa (1080x1920, com o título)" lado="cima">
              <a href={`${clip.capa_url.split("?")[0]}?download=true`} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5">
                <ImageDown className="size-4" />
              </a>
            </Dica>
          )}
          <Dica texto="Editar" lado="cima">
            <Link to={`/projetos/${projetoId}/clips/${clip.id}`} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5">
              <Pencil className="size-4" />
            </Link>
          </Dica>
          {textoPost && (
            <Dica texto="Copiar legenda e hashtags do post" lado="cima">
              <button onClick={copiarPost} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5 cursor-pointer">
                {copiado ? <Check className="size-4 text-verde" /> : <Copy className="size-4" />}
              </button>
            </Dica>
          )}
          <Dica texto="Regenerar: trocar por outro momento do vídeo" lado="cima">
            <button onClick={aoRegenerar} disabled={ocupado} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5 disabled:opacity-40 cursor-pointer">
              <RefreshCw className="size-4" />
            </button>
          </Dica>
          <div className="flex-1" />
          <Dica texto="Excluir" lado="cima">
            <button onClick={aoExcluir} disabled={ocupado} className="p-2 rounded-lg text-suave hover:text-vermelho hover:bg-vermelho/10 disabled:opacity-40 cursor-pointer">
              <Trash2 className="size-4" />
            </button>
          </Dica>
        </div>
      </div>
    </div>
  );
}
