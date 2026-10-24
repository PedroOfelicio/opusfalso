// Um vídeo longo: progresso enquanto processa; no fim, o vídeo com capítulos, títulos, descrição, tags e arquivos.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, AudioLines, Check, Clapperboard, Copy, Download, FileText, Film, FolderOpen, Gamepad2, ListChecks, Mic, Play,
  RotateCcw, Scissors, Smartphone, Sparkles, Subtitles, X,
} from "lucide-react";
import { api, formatarDuracao } from "../api";
import { Alternador, Aviso, Botao, Chip, Confirmar, EstadoErro, Esqueleto, Segmentado, usePolling, useAvisar } from "../components/ui";
import Processando from "./Processando";
import CustoProjeto from "../components/Custo";

// Mesmas etapas do backend (longo.ETAPAS)
const ETAPAS_LONGO = [
  { id: "transcrevendo", rotulo: "Transcrevendo", icone: AudioLines, texto: "Convertendo a fala em texto com tempo por palavra" },
  { id: "analisando", rotulo: "Analisando", icone: Sparkles, texto: "Medindo a energia do áudio" },
  { id: "decidindo", rotulo: "Decidindo a edição", icone: Clapperboard, texto: "O que sai, capítulos, abertura e textos do YouTube" },
  { id: "montando", rotulo: "Montando o vídeo", icone: Scissors, texto: "Cortes secos, zoom e áudio final" },
  { id: "finalizando", rotulo: "Finalizando", icone: Subtitles, texto: "Legenda .srt, texto do YouTube e thumbnails" },
];

const tempoYT = (t) => {
  const s = Math.floor(t);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const seg = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${seg}` : `${String(m).padStart(2, "0")}:${seg}`;
};

export default function ProjetoLongo() {
  const { id } = useParams();
  const [projeto, setProjeto] = useState(null);
  const [erro, setErro] = useState(null);

  const carregar = useCallback(() => {
    api
      .projeto(id)
      .then((p) => {
        setProjeto(p);
        setErro(null);
      })
      .catch((e) => setErro(e.message));
  }, [id]);
  useEffect(carregar, [carregar]);
  const rodando = projeto && ["fila", "processando"].includes(projeto.status);
  usePolling(carregar, rodando ? 1000 : 10000, !!projeto);

  if (erro && !projeto)
    return (
      <div className="max-w-3xl mx-auto p-8">
        <EstadoErro mensagem={erro} aoTentar={carregar} />
      </div>
    );
  if (!projeto)
    return (
      <div className="max-w-6xl mx-auto p-8 space-y-6">
        <Esqueleto className="h-10 w-72" />
        <Esqueleto className="aspect-video max-w-3xl" />
      </div>
    );
  if (projeto.status !== "pronto" || !projeto.longo)
    return <Processando projeto={projeto} recarregar={carregar} etapas={ETAPAS_LONGO} voltar={{ para: "/projetos", rotulo: "Projetos" }} />;
  return <Resultado projeto={projeto} recarregar={carregar} />;
}

function Resultado({ projeto, recarregar }) {
  const avisar = useAvisar();
  const navegar = useNavigate();
  const video = useRef(null);
  const [refazendo, setRefazendo] = useState(false);
  const [copiado, setCopiado] = useState(null);
  const lg = projeto.longo;
  const reducao = lg.duracao_original ? Math.round((1 - lg.duracao / lg.duracao_original) * 100) : 0;

  const copiar = async (texto, chave) => {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(chave);
      setTimeout(() => setCopiado(null), 1500);
    } catch {
      avisar("Não consegui copiar", "erro");
    }
  };
  const irPara = (t) => {
    if (!video.current) return;
    video.current.currentTime = t;
    video.current.play().catch(() => {});
  };
  const refazer = async () => {
    setRefazendo(false);
    try {
      await api.reprocessar(projeto.id);
      recarregar();
    } catch (e) {
      avisar(e.message, "erro");
    }
  };
  const BotaoCopiar = ({ texto, chave, rotulo = "Copiar" }) => (
    <button onClick={() => copiar(texto, chave)} className="text-xs text-suave hover:text-texto inline-flex items-center gap-1 cursor-pointer shrink-0">
      {copiado === chave ? <Check className="size-3.5 text-verde" /> : <Copy className="size-3.5" />}
      {copiado === chave ? "Copiado" : rotulo}
    </button>
  );

  return (
    <div className="max-w-[1300px] mx-auto px-6 lg:px-8 py-8">
      <Link to="/projetos" className="inline-flex items-center gap-1.5 text-sm text-suave hover:text-texto mb-4">
        <ArrowLeft className="size-4" /> Projetos
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-suave">
            {projeto.modo === "gameplay" ? <Gamepad2 className="size-3.5" /> : <Mic className="size-3.5" />}
            {lg.modo_longo === "melhores" ? "Melhores momentos" : "Vídeo inteiro enxugado"}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight truncate mt-1">{projeto.nome}</h1>
          <div className="mt-2"><CustoProjeto projeto={projeto} /></div>
        </div>
        <div className="flex flex-wrap gap-2">
          {projeto.edicao && (
            <Botao icone={ListChecks} onClick={() => document.getElementById("revisao")?.scrollIntoView({ behavior: "smooth" })}>Revisar a edição</Botao>
          )}
          <Botao icone={Smartphone} onClick={() => navegar(`/?caminho=${encodeURIComponent(projeto.video)}&modo=${projeto.modo}`)}>Gerar clipes curtos</Botao>
          <Botao icone={FolderOpen} onClick={() => api.abrirPasta(projeto.id)}>Abrir pasta</Botao>
          <Botao icone={RotateCcw} onClick={() => setRefazendo(true)}>Refazer</Botao>
          <a href={lg.video_url} download>
            <Botao variante="primario" icone={Download}>Baixar vídeo</Botao>
          </a>
        </div>
      </div>

      {lg.sem_arquivo && (
        <div className="mb-5">
          <Aviso tipo="alerta" titulo="O vídeo final não está mais na pasta de saída">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>Foi apagado ou movido. Dá para remontar com a edição salva, sem custo na API.</span>
              <Botao
                tamanho="sm"
                icone={RotateCcw}
                onClick={async () => {
                  try {
                    await api.refazerArquivos(projeto.id);
                    recarregar();
                  } catch (e) {
                    avisar(e.message, "erro");
                  }
                }}
              >
                Refazer o vídeo
              </Botao>
            </div>
          </Aviso>
        </div>
      )}

      {(projeto.avisos?.length > 0 || projeto.nao_atendido?.length > 0) && (
        <div className="space-y-2 mb-5">
          {projeto.nao_atendido?.length > 0 && <Aviso tipo="alerta" titulo="Partes do pedido que não foram atendidas">{projeto.nao_atendido.join(" · ")}</Aviso>}
          {projeto.avisos?.map((a) => <Aviso key={a} tipo="info">{a}</Aviso>)}
        </div>
      )}

      <div className="grid lg:grid-cols-[1fr_400px] gap-6 items-start">
        <div className="space-y-5 min-w-0">
          <div className="cartao overflow-hidden">
            <video ref={video} src={lg.video_url} controls className="w-full aspect-video bg-black" poster={lg.thumbs_url?.[0]} />
            <div className="grid grid-cols-3 divide-x divide-borda border-t border-borda text-center">
              <div className="p-3">
                <div className="text-lg font-bold tabular-nums">{formatarDuracao(lg.duracao)}</div>
                <div className="text-xs text-suave">de {formatarDuracao(lg.duracao_original)}{reducao > 0 ? ` (−${reducao}%)` : ""}</div>
              </div>
              <div className="p-3">
                <div className="text-lg font-bold tabular-nums">{lg.cortes}</div>
                <div className="text-xs text-suave">cortes secos</div>
              </div>
              <div className="p-3">
                <div className="text-lg font-bold tabular-nums">{lg.capitulos.length}</div>
                <div className="text-xs text-suave">capítulos</div>
              </div>
            </div>
          </div>

          {lg.thumbs_url?.length > 0 && (
            <div className="cartao p-5">
              <div className="rotulo mb-3">Sugestões de thumbnail</div>
              <div className="grid grid-cols-3 gap-3">
                {lg.thumbs_url.map((u, k) => (
                  <a key={u} href={u} download={`thumbnail_${k + 1}.jpg`} className="group relative rounded-xl overflow-hidden border border-borda">
                    <img src={u} alt="" className="w-full aspect-video object-cover" />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Download className="size-5" />
                    </span>
                  </a>
                ))}
              </div>
            </div>
          )}

          <div className="cartao p-5">
            <div className="rotulo mb-3">Arquivos</div>
            <div className="flex flex-wrap gap-2">
              <a href={lg.video_url} download><Botao icone={Film}>Vídeo (.mp4)</Botao></a>
              {lg.srt_url && <a href={lg.srt_url} download><Botao icone={Subtitles}>Legenda (.srt)</Botao></a>}
              <a href={lg.texto_url} download><Botao icone={FileText}>Texto do YouTube (.txt)</Botao></a>
            </div>
            <p className="text-xs text-apagado mt-3">
              Os capítulos já estão dentro do MP4. No YouTube, suba o .srt em Legendas e cole a descrição: os capítulos aparecem sozinhos.
            </p>
          </div>
        </div>

        <div className="space-y-5">
          <div className="cartao p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="rotulo">Capítulos</div>
              <BotaoCopiar texto={lg.capitulos.map((c) => `${tempoYT(c.t)} ${c.titulo}`).join("\n")} chave="capitulos" />
            </div>
            <ol className="space-y-1">
              {lg.capitulos.map((c) => (
                <li key={c.t}>
                  <button onClick={() => irPara(c.t)} className="w-full flex gap-3 text-left rounded-lg px-2 py-1.5 hover:bg-black/[0.05] cursor-pointer">
                    <span className="text-roxo tabular-nums text-sm font-semibold w-14 shrink-0">{tempoYT(c.t)}</span>
                    <span className="text-sm">{c.titulo}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>

          <div className="cartao p-5">
            <div className="rotulo mb-3">Títulos sugeridos</div>
            <div className="space-y-2">
              {lg.titulos.map((t, k) => (
                <div key={t} className="flex items-start gap-3 rounded-xl border border-borda p-3">
                  <span className="text-sm flex-1">{t}</span>
                  <BotaoCopiar texto={t} chave={`t${k}`} rotulo="" />
                </div>
              ))}
            </div>
          </div>

          <div className="cartao p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="rotulo">Descrição (com capítulos)</div>
              <BotaoCopiar texto={lg.descricao_completa} chave="descricao" />
            </div>
            <textarea readOnly value={lg.descricao_completa} rows={9} className="campo resize-none text-[13px] leading-relaxed" />
          </div>

          {lg.tags?.length > 0 && (
            <div className="cartao p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="rotulo">Tags</div>
                <BotaoCopiar texto={lg.tags.join(", ")} chave="tags" />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {lg.tags.map((t) => <span key={t} className="text-xs rounded-md bg-card-2 border border-borda px-2 py-1">{t}</span>)}
              </div>
            </div>
          )}
        </div>
      </div>

      {projeto.edicao && <Revisao projeto={projeto} recarregar={recarregar} />}

      <Confirmar
        aberto={refazendo}
        titulo="Refazer o vídeo?"
        texto="Roda a edição de novo com as mesmas opções. A transcrição e a análise vêm do cache; as decisões do Claude são refeitas (custa de novo)."
        rotuloOk="Refazer"
        aoConfirmar={refazer}
        aoFechar={() => setRefazendo(false)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ revisão da edição

const COR_MOTIVO = {
  "take repetido": "bg-amarelo/15 text-amarelo",
  "começo em falso": "bg-amarelo/15 text-amarelo",
  "desvio de assunto": "bg-azul/15 text-azul",
  bastidor: "bg-roxo/15 text-roxo",
  "pedido do usuário": "bg-verde/15 text-verde",
  "tela preta": "bg-black/[0.06] text-suave",
};
const RITMOS = [
  { valor: "natural", rotulo: "Natural" },
  { valor: "dinamico", rotulo: "Dinâmico" },
  { valor: "rapido", rotulo: "Rápido" },
];

function Revisao({ projeto, recarregar }) {
  const avisar = useAvisar();
  const edl = projeto.edicao;
  const falado = edl.tipo === "falado";
  const inicial = useMemo(
    () => ({
      ritmo: edl.ritmo || "dinamico",
      abertura: !!edl.abertura_ativa,
      manter: Object.fromEntries(edl.remocoes.map((r) => [r.id, !!r.manter])),
      capitulos: Object.fromEntries(edl.capitulos.map((c) => [c.id, { titulo: c.titulo, ativo: c.ativo !== false }])),
      momentos: Object.fromEntries(edl.momentos.map((m) => [m.id, { titulo: m.titulo, manter: m.manter !== false }])),
    }),
    [edl],
  );
  const [estado, setEstado] = useState(inicial);
  useEffect(() => setEstado(inicial), [inicial]);
  const [filtro, setFiltro] = useState("todos");
  const [previa, setPrevia] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const alterado = JSON.stringify(estado) !== JSON.stringify(inicial);

  const motivos = useMemo(() => {
    const cont = {};
    edl.remocoes.forEach((r) => (cont[r.motivo] = (cont[r.motivo] || 0) + 1));
    return cont;
  }, [edl]);
  const lista = edl.remocoes.filter((r) => filtro === "todos" || r.motivo === filtro);
  const removido = edl.remocoes.filter((r) => !estado.manter[r.id]).reduce((s, r) => s + (r.fim - r.inicio), 0);
  const voltam = edl.remocoes.filter((r) => estado.manter[r.id]).length;

  const mudar = (chave, id, campo, valor) =>
    setEstado((e) => ({ ...e, [chave]: { ...e[chave], [id]: { ...e[chave][id], [campo]: valor } } }));

  const aplicar = async () => {
    setEnviando(true);
    try {
      await api.revisarLongo(projeto.id, {
        ritmo: estado.ritmo,
        abertura_ativa: estado.abertura,
        remocoes: edl.remocoes.filter((r) => estado.manter[r.id] !== !!r.manter).map((r) => ({ id: r.id, manter: estado.manter[r.id] })),
        capitulos: edl.capitulos.map((c) => ({ id: c.id, ...estado.capitulos[c.id] })),
        momentos: edl.momentos.map((m) => ({ id: m.id, ...estado.momentos[m.id] })),
      });
      avisar("Remontando o vídeo com a sua revisão");
      recarregar();
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div id="revisao" className="cartao p-5 mt-6 scroll-mt-6">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="font-bold text-lg flex items-center gap-2"><ListChecks className="size-5 text-roxo" /> Revisar a edição</h2>
          <p className="text-sm text-suave mt-0.5">
            Devolva trechos, mude o ritmo ou renomeie capítulos. Só os blocos que mudarem são renderizados de novo, sem custo na API.
          </p>
        </div>
        <Botao variante="primario" icone={Scissors} onClick={aplicar} disabled={!alterado} carregando={enviando}>
          Aplicar e remontar
        </Botao>
      </div>

      {previa && (
        <div className="mb-5 rounded-xl border border-borda bg-fundo p-3 flex flex-col sm:flex-row gap-3 items-start">
          <video key={`${previa.inicio}-${previa.fim}`} src={api.urlPrevia(projeto.id, previa.inicio, previa.fim)} controls autoPlay className="w-full sm:w-96 aspect-video bg-black rounded-lg" />
          <div className="flex-1 text-sm">
            <div className="font-semibold">{previa.rotulo}</div>
            <div className="text-xs text-suave mt-1">Trecho do vídeo original, com 1 s antes e depois.</div>
            {previa.texto && <p className="text-sm text-suave mt-2">“{previa.texto}”</p>}
          </div>
          <button onClick={() => setPrevia(null)} className="p-1.5 rounded-lg text-suave hover:text-texto hover:bg-black/[0.05] cursor-pointer" aria-label="Fechar prévia">
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="grid lg:grid-cols-[360px_1fr] gap-6">
        <div className="space-y-5">
          {falado && (
            <div>
              <div className="rotulo mb-2">Ritmo (pausas entre as frases)</div>
              <Segmentado tamanho="sm" valor={estado.ritmo} aoMudar={(v) => setEstado((e) => ({ ...e, ritmo: v }))} opcoes={RITMOS} />
            </div>
          )}
          {edl.abertura && (
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <Alternador ativo={estado.abertura} aoMudar={(v) => setEstado((e) => ({ ...e, abertura: v }))} rotulo="Abrir com o melhor momento" descricao={`Teaser de ${Math.round(edl.abertura[1] - edl.abertura[0])} s antes de começar`} />
              </div>
              <button onClick={() => setPrevia({ inicio: edl.abertura[0], fim: edl.abertura[1], rotulo: "Abertura" })} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-black/[0.05] cursor-pointer" aria-label="Ver a abertura">
                <Play className="size-4" />
              </button>
            </div>
          )}
          {edl.modo_longo === "enxugar" ? (
            <div>
              <div className="rotulo mb-2">Capítulos</div>
              <div className="space-y-2">
                {edl.capitulos.map((c) => (
                  <div key={c.id} className="flex items-center gap-2">
                    <input type="checkbox" checked={estado.capitulos[c.id]?.ativo ?? true} onChange={(e) => mudar("capitulos", c.id, "ativo", e.target.checked)} className="accent-roxo size-4 cursor-pointer" />
                    <span className="text-xs text-apagado tabular-nums w-11 shrink-0">{tempoYT(c.t_origem)}</span>
                    <input value={estado.capitulos[c.id]?.titulo ?? ""} onChange={(e) => mudar("capitulos", c.id, "titulo", e.target.value)} className="campo !py-1.5 text-sm" />
                  </div>
                ))}
              </div>
              <p className="text-xs text-apagado mt-2">Tempos do vídeo original. Desmarque para tirar o capítulo.</p>
            </div>
          ) : (
            <div>
              <div className="rotulo mb-2">Momentos</div>
              <div className="space-y-2">
                {edl.momentos.map((m) => {
                  const ok = estado.momentos[m.id]?.manter ?? true;
                  return (
                    <div key={m.id} className={`flex items-center gap-2 ${ok ? "" : "opacity-50"}`}>
                      <input type="checkbox" checked={ok} onChange={(e) => mudar("momentos", m.id, "manter", e.target.checked)} className="accent-roxo size-4 cursor-pointer" />
                      <input value={estado.momentos[m.id]?.titulo ?? ""} onChange={(e) => mudar("momentos", m.id, "titulo", e.target.value)} className="campo !py-1.5 text-sm" />
                      <button onClick={() => setPrevia({ inicio: m.inicio, fim: Math.min(m.fim, m.inicio + 90), rotulo: m.titulo })} className="p-1.5 rounded-lg text-suave hover:text-texto hover:bg-black/[0.05] cursor-pointer" aria-label="Ver momento">
                        <Play className="size-4" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="rotulo">O que saiu ({edl.remocoes.length})</div>
            <div className="text-xs text-suave">
              {Math.round(removido)} s removidos{voltam > 0 ? ` · ${voltam} trecho(s) voltando` : ""}
              {falado ? " · silêncios e vícios saem pelo ritmo" : ""}
            </div>
          </div>
          {edl.remocoes.length === 0 ? (
            <p className="text-sm text-suave">Nada foi removido além de {falado ? "silêncios e vícios" : "tempo morto"}.</p>
          ) : (
            <>
              {Object.keys(motivos).length > 1 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  <Chip ativo={filtro === "todos"} onClick={() => setFiltro("todos")}>Todos ({edl.remocoes.length})</Chip>
                  {Object.entries(motivos).map(([m, n]) => (
                    <Chip key={m} ativo={filtro === m} onClick={() => setFiltro(m)}>{m} ({n})</Chip>
                  ))}
                </div>
              )}
              <div className="max-h-[520px] overflow-y-auto pr-1 space-y-1.5">
                {lista.map((r) => {
                  const volta = !!estado.manter[r.id];
                  return (
                    <div key={r.id} className={`flex items-center gap-3 rounded-xl border p-2.5 ${volta ? "border-verde/40 bg-verde/5" : "border-borda"}`}>
                      {!falado && (
                        <img loading="lazy" src={api.urlQuadro(projeto.id, (r.inicio + r.fim) / 2)} alt="" className="w-24 aspect-video object-cover rounded-md bg-card-2 shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className={`font-semibold px-1.5 py-0.5 rounded-md ${COR_MOTIVO[r.motivo] || "bg-card-2 text-suave"}`}>{r.motivo}</span>
                          <span className="text-suave tabular-nums">{tempoYT(r.inicio)} · {Math.round(r.fim - r.inicio)} s</span>
                        </div>
                        {r.texto && <p className="text-sm text-suave mt-1 line-clamp-2">“{r.texto}”</p>}
                      </div>
                      <button onClick={() => setPrevia({ inicio: r.inicio, fim: r.fim, rotulo: r.motivo, texto: r.texto })} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-black/[0.05] cursor-pointer shrink-0" aria-label="Ver trecho">
                        <Play className="size-4" />
                      </button>
                      <button
                        onClick={() => setEstado((e) => ({ ...e, manter: { ...e.manter, [r.id]: !volta } }))}
                        className={`text-xs font-semibold px-2.5 py-1.5 rounded-lg border shrink-0 cursor-pointer ${volta ? "border-verde/40 text-verde" : "border-borda text-suave hover:text-texto"}`}
                      >
                        {volta ? "Volta pro vídeo" : "Removido"}
                      </button>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
