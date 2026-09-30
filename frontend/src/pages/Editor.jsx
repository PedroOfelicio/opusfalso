// Editor de clipe: player, abas (Legendas, Enquadramento, Título, Áudio), linha do tempo e exportar.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft, AudioLines, Crop, Download, Loader2, Minus, Pause, Play, Plus, RotateCcw, Save, Subtitles, Type, Upload,
} from "lucide-react";
import { api, formatarTempoPreciso } from "../api";
import ScoreBadge from "../components/ScoreBadge";
import { Alternador, Aviso, Botao, EstadoErro, Esqueleto, Segmentado, usePolling, useAvisar } from "../components/ui";

const CHAVES = ["formato", "legenda_ativa", "estilo", "preset", "cor", "titulo_ativo", "zoom", "remover_silencios", "normalizar", "layout", "deslocamento_x", "musica"];
const CORES_RAPIDAS = ["#FFE600", "#22FF6B", "#3B82F6", "#FF4FD8", "#FF8A00", "#FFFFFF"];
const LAYOUTS = [
  { id: "auto", rotulo: "Automático", texto: "Escolhe conforme o vídeo e os rostos encontrados" },
  { id: "rosto", rotulo: "Seguir quem fala", texto: "Câmera suave no rosto; alterna entre pessoas" },
  { id: "dupla", rotulo: "Duas pessoas", texto: "Tela dividida: uma pessoa em cima, outra embaixo" },
  { id: "centro", rotulo: "Recorte fixo", texto: "Recorte parado, com ajuste horizontal manual" },
  { id: "inteiro", rotulo: "Vídeo inteiro", texto: "Vídeo completo no meio com fundo desfocado" },
  { id: "split", rotulo: "Gameplay + facecam", texto: "Jogo em cima, facecam ou vídeo de apoio embaixo" },
];
const ABAS = [
  { id: "legendas", rotulo: "Legendas", icone: Subtitles },
  { id: "enquadramento", rotulo: "Enquadramento", icone: Crop },
  { id: "titulo", rotulo: "Título", icone: Type },
  { id: "audio", rotulo: "Áudio", icone: AudioLines },
];

const ASPECTO = { "9:16": 9 / 16, "1:1": 1, "16:9": 16 / 9 };

function rascunhoDe(clip) {
  const efetiva = clip.config_efetiva || {};
  return {
    titulo: clip.titulo,
    inicio: clip.inicio,
    fim: clip.fim,
    config: Object.fromEntries(CHAVES.map((k) => [k, efetiva[k] ?? null])),
    palavras_editadas: { ...(clip.palavras_editadas || {}) },
  };
}

export default function Editor() {
  const { id, cid } = useParams();
  const avisar = useAvisar();
  const video = useRef(null);
  const [projeto, setProjeto] = useState(null);
  const [erro, setErro] = useState(null);
  const [rascunho, setRascunho] = useState(null);
  const [original, setOriginal] = useState(null); // para saber se há alterações
  const [palavras, setPalavras] = useState([]);
  const [aba, setAba] = useState("legendas");
  const [fonte, setFonte] = useState("final"); // "final" = clipe renderizado | "original" = vídeo fonte
  const [tocando, setTocando] = useState(false);
  const [tempoAtual, setTempoAtual] = useState(0);
  const [editandoPalavra, setEditandoPalavra] = useState(null);
  const [estilos, setEstilos] = useState({});
  const [salvando, setSalvando] = useState(false);

  const clip = projeto?.clips.find((c) => c.id === cid);
  const renderizando = clip && ["fila", "renderizando"].includes(clip.status);

  const carregar = useCallback(() => {
    api
      .projeto(id)
      .then((p) => {
        setProjeto(p);
        const c = p.clips.find((x) => x.id === cid);
        if (!c) throw new Error("Clipe não encontrado");
        setRascunho((r) => r ?? rascunhoDe(c));
        setOriginal((o) => o ?? rascunhoDe(c));
      })
      .catch((e) => setErro(e.message));
  }, [id, cid]);
  useEffect(carregar, [carregar]);
  useEffect(() => {
    api.estilos().then(setEstilos).catch(() => {});
  }, []);
  usePolling(carregar, 1000, !!renderizando);

  // Palavras do trecho (com uma folga para quando o usuário estende o clipe)
  useEffect(() => {
    if (!rascunho) return;
    const t = setTimeout(() => {
      api.palavras(id, rascunho.inicio, rascunho.fim, cid).then(setPalavras).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [id, cid, rascunho?.inicio, rascunho?.fim]); // eslint-disable-line react-hooks/exhaustive-deps

  const alterado = useMemo(() => JSON.stringify(rascunho) !== JSON.stringify(original), [rascunho, original]);
  const mudarConfig = (k, v) => setRascunho((r) => ({ ...r, config: { ...r.config, [k]: v } }));

  // ---------- player
  const alternarPlay = useCallback(() => {
    const v = video.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => {});
    else v.pause();
  }, []);

  useEffect(() => {
    const tecla = (e) => {
      const tag = document.activeElement?.tagName;
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) {
        e.preventDefault();
        alternarPlay();
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [alternarPlay]);

  const aoAtualizarTempo = () => {
    const v = video.current;
    if (!v) return;
    setTempoAtual(v.currentTime);
    // No modo original, toca só o intervalo escolhido
    if (fonte === "original" && rascunho && (v.currentTime > rascunho.fim || v.currentTime < rascunho.inicio - 0.5)) {
      v.currentTime = rascunho.inicio;
      if (v.currentTime > rascunho.fim) v.pause();
    }
  };

  // ---------- salvar / exportar
  const salvar = async (exportar = false) => {
    setSalvando(true);
    try {
      let p = await api.editarClip(id, cid, rascunho);
      if (exportar) p = await api.renderizar(id, cid);
      setProjeto(p);
      setOriginal(rascunho);
      avisar(exportar ? "Exportando… o vídeo será atualizado ao terminar" : "Alterações salvas (use Exportar para gerar o vídeo)");
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setSalvando(false);
    }
  };

  if (erro) return <div className="max-w-3xl mx-auto p-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!projeto || !clip || !rascunho)
    return (
      <div className="p-8 grid lg:grid-cols-[1fr_420px] gap-6">
        <Esqueleto className="h-[70vh]" />
        <Esqueleto className="h-[70vh]" />
      </div>
    );

  const formato = fonte === "final" ? clip.config_efetiva?.formato || "9:16" : "16:9";
  const cfg = rascunho.config;
  const duracao = rascunho.fim - rascunho.inicio;

  return (
    <div className="h-full flex flex-col">
      {/* Barra superior */}
      <header className="h-16 shrink-0 border-b border-borda px-6 flex items-center gap-4">
        <Link to={`/projetos/${id}`} className="p-2 -ml-2 rounded-lg text-suave hover:text-texto hover:bg-white/5"><ArrowLeft className="size-5" /></Link>
        <div className="min-w-0 flex-1">
          <div className="text-xs text-suave">{projeto.nome} · {clip.id.replace("_", " ")}</div>
          <div className="font-semibold truncate">{rascunho.titulo || "Sem título"}</div>
        </div>
        {alterado && <span className="text-xs text-amarelo">Alterações não exportadas</span>}
        {clip.video_url && (
          <a href={`${clip.video_url.split("?")[0]}?download=true`}>
            <Botao variante="fantasma" icone={Download}>Baixar</Botao>
          </a>
        )}
        <Botao icone={Save} onClick={() => salvar(false)} disabled={!alterado || salvando}>Salvar</Botao>
        <Botao variante="primario" icone={Upload} onClick={() => salvar(true)} carregando={salvando || renderizando}>
          {renderizando ? `Exportando ${Math.round((clip.progresso || 0) * 100)}%` : "Exportar"}
        </Botao>
      </header>

      <div className="flex-1 min-h-0 grid lg:grid-cols-[1fr_440px]">
        {/* Player */}
        <section className="min-h-0 flex flex-col p-6 gap-4 overflow-y-auto">
          <div className="flex items-center justify-between">
            <Segmentado
              tamanho="sm"
              valor={fonte}
              aoMudar={(v) => {
                setFonte(v);
                setTocando(false);
              }}
              opcoes={[{ valor: "final", rotulo: "Clipe exportado" }, { valor: "original", rotulo: "Vídeo original" }]}
            />
            <span className="text-xs text-apagado">
              <kbd className="px-1.5 py-0.5 rounded bg-card border border-borda">Espaço</kbd> play/pause
            </span>
          </div>

          <div className="flex-1 min-h-[420px] flex items-center justify-center rounded-2xl bg-[#07070a] border border-borda relative overflow-hidden">
            <div className="relative h-full max-h-[72vh] max-w-full" style={{ aspectRatio: ASPECTO[formato] }}>
              {fonte === "final" && !clip.video_url ? (
                <div className="absolute inset-0 flex items-center justify-center text-suave text-sm">Clipe ainda não exportado</div>
              ) : (
                <video
                  key={fonte + (clip.versao || 0)}
                  ref={video}
                  src={fonte === "final" ? clip.video_url : `/api/projetos/${id}/video`}
                  className="absolute inset-0 size-full object-contain rounded-xl"
                  onClick={alternarPlay}
                  onPlay={() => setTocando(true)}
                  onPause={() => setTocando(false)}
                  onTimeUpdate={aoAtualizarTempo}
                  onLoadedMetadata={(e) => fonte === "original" && (e.currentTarget.currentTime = rascunho.inicio)}
                  controls={fonte === "final"}
                  playsInline
                />
              )}
              {renderizando && (
                <div className="absolute inset-0 bg-black/70 backdrop-blur-sm flex flex-col items-center justify-center gap-3 rounded-xl">
                  <Loader2 className="size-8 animate-spin text-roxo" />
                  <span className="text-sm font-semibold">Exportando {Math.round((clip.progresso || 0) * 100)}%</span>
                </div>
              )}
            </div>
            {fonte === "original" && (
              <button onClick={alternarPlay} className="absolute bottom-4 left-1/2 -translate-x-1/2 size-12 rounded-full gradiente flex items-center justify-center shadow-suave cursor-pointer">
                {tocando ? <Pause className="size-5 text-white" /> : <Play className="size-5 text-white ml-0.5" />}
              </button>
            )}
          </div>

          <LinhaDoTempo
            inicio={rascunho.inicio}
            fim={rascunho.fim}
            total={projeto.duracao_video || rascunho.fim + 30}
            cursor={fonte === "original" ? tempoAtual : null}
            aoMudar={(ini, fim) => setRascunho((r) => ({ ...r, inicio: ini, fim }))}
          />
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <AjusteTempo rotulo="Início" valor={rascunho.inicio} aoMudar={(v) => setRascunho((r) => ({ ...r, inicio: Math.max(0, Math.min(v, r.fim - 2)) }))} />
            <AjusteTempo rotulo="Fim" valor={rascunho.fim} aoMudar={(v) => setRascunho((r) => ({ ...r, fim: Math.min(projeto.duracao_video || v, Math.max(v, r.inicio + 2)) }))} />
            <span className="text-suave">Duração: <b className="text-texto tabular-nums">{duracao.toFixed(1)}s</b></span>
            {(rascunho.inicio !== original.inicio || rascunho.fim !== original.fim) && (
              <button className="text-xs text-suave hover:text-texto inline-flex items-center gap-1 cursor-pointer" onClick={() => setRascunho((r) => ({ ...r, inicio: original.inicio, fim: original.fim }))}>
                <RotateCcw className="size-3" /> desfazer
              </button>
            )}
          </div>
        </section>

        {/* Painel lateral */}
        <aside className="min-h-0 border-l border-borda flex flex-col bg-[#0d0d12]">
          <nav className="flex border-b border-borda px-2 shrink-0">
            {ABAS.map(({ id: a, rotulo, icone: Icone }) => (
              <button
                key={a}
                onClick={() => setAba(a)}
                className={`flex-1 flex flex-col items-center gap-1 py-3 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${aba === a ? "border-roxo text-texto" : "border-transparent text-apagado hover:text-suave"}`}
              >
                <Icone className="size-4" />
                {rotulo}
              </button>
            ))}
          </nav>

          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {aba === "legendas" && (
              <>
                <Alternador ativo={!!cfg.legenda_ativa} aoMudar={(v) => mudarConfig("legenda_ativa", v)} rotulo="Mostrar legenda" />
                <div>
                  <div className="rotulo mb-2">Estilo</div>
                  <Segmentado tamanho="sm" valor={cfg.estilo} aoMudar={(v) => mudarConfig("estilo", v)} opcoes={[{ valor: "simples", rotulo: "Simples (rápida)" }, { valor: "animada", rotulo: "Animada (Remotion)" }]} />
                </div>
                <div>
                  <div className="rotulo mb-2">Preset</div>
                  <div className="grid grid-cols-3 gap-2">
                    {Object.entries(estilos).map(([k, e]) => (
                      <button
                        key={k}
                        onClick={() => mudarConfig("preset", k)}
                        className={`rounded-xl border px-2 py-2.5 text-xs font-semibold transition-colors cursor-pointer ${cfg.preset === k ? "border-roxo bg-roxo/10" : "border-borda hover:border-borda-forte"}`}
                      >
                        <span className="block size-3 rounded-full mx-auto mb-1.5" style={{ background: e.cor_destaque }} />
                        {e.nome || k}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="rotulo mb-2">Cor da palavra falada</div>
                  <div className="flex items-center gap-2">
                    {CORES_RAPIDAS.map((c) => (
                      <button key={c} onClick={() => mudarConfig("cor", c)} className={`size-7 rounded-full border-2 cursor-pointer ${cfg.cor?.toUpperCase() === c ? "border-white" : "border-transparent"}`} style={{ background: c }} aria-label={c} />
                    ))}
                    <input type="color" value={cfg.cor || estilos[cfg.preset]?.cor_destaque || "#FFE600"} onChange={(e) => mudarConfig("cor", e.target.value.toUpperCase())} className="size-7 rounded-full bg-transparent cursor-pointer" />
                  </div>
                  <button
                    onClick={() => mudarConfig("cor", null)}
                    className={`mt-2 text-xs cursor-pointer ${cfg.cor ? "text-suave hover:text-texto underline" : "text-roxo"}`}
                  >
                    {cfg.cor ? "Usar a cor do preset" : "Usando a cor do preset"}
                  </button>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="rotulo">Texto (clique para editar)</div>
                    {Object.keys(rascunho.palavras_editadas).length > 0 && (
                      <button className="text-xs text-suave hover:text-texto cursor-pointer" onClick={() => setRascunho((r) => ({ ...r, palavras_editadas: {} }))}>Restaurar original</button>
                    )}
                  </div>
                  <div className="rounded-xl border border-borda bg-fundo p-3 flex flex-wrap gap-1.5 max-h-72 overflow-y-auto">
                    {palavras.length === 0 && <span className="text-xs text-apagado">Sem fala neste trecho.</span>}
                    {palavras.map((w) => {
                      const editada = rascunho.palavras_editadas[w.chave];
                      const texto = editada ?? w.original;
                      const removida = editada === "";
                      const ativa = fonte === "original" && tempoAtual >= w.i && tempoAtual <= w.f;
                      return editandoPalavra === w.chave ? (
                        <input
                          key={w.chave}
                          autoFocus
                          defaultValue={texto}
                          className="campo !w-28 !py-0.5 !px-2 text-xs"
                          onBlur={(e) => {
                            const novo = e.target.value.trim();
                            setRascunho((r) => {
                              const ed = { ...r.palavras_editadas };
                              if (novo === w.original) delete ed[w.chave];
                              else ed[w.chave] = novo;
                              return { ...r, palavras_editadas: ed };
                            });
                            setEditandoPalavra(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") e.currentTarget.blur();
                            if (e.key === "Escape") setEditandoPalavra(null);
                          }}
                        />
                      ) : (
                        <button
                          key={w.chave}
                          onClick={() => setEditandoPalavra(w.chave)}
                          title={`${w.i.toFixed(2)}s · deixe vazio para remover`}
                          className={`px-1.5 py-0.5 rounded-md text-xs transition-colors cursor-pointer ${
                            ativa ? "gradiente text-white" : removida ? "line-through text-apagado" : editada != null ? "bg-amarelo/15 text-amarelo" : "hover:bg-white/10"
                          }`}
                        >
                          {removida ? w.original : texto}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-xs text-apagado mt-2">Palavras editadas ficam em amarelo. Apague o texto para remover a palavra da legenda.</p>
                </div>
              </>
            )}

            {aba === "enquadramento" && (
              <>
                <div>
                  <div className="rotulo mb-2">Formato</div>
                  <Segmentado tamanho="sm" valor={cfg.formato} aoMudar={(v) => mudarConfig("formato", v)} opcoes={["9:16", "1:1", "16:9"].map((f) => ({ valor: f, rotulo: f }))} />
                </div>
                <div>
                  <div className="rotulo mb-2">Layout</div>
                  <div className="space-y-2">
                    {LAYOUTS.map((l) => (
                      <button
                        key={l.id}
                        onClick={() => mudarConfig("layout", l.id)}
                        className={`w-full text-left rounded-xl border px-3.5 py-2.5 transition-colors cursor-pointer ${cfg.layout === l.id ? "border-roxo bg-roxo/10" : "border-borda hover:border-borda-forte"}`}
                      >
                        <div className="text-sm font-semibold">{l.rotulo}</div>
                        <div className="text-xs text-apagado">{l.texto}</div>
                      </button>
                    ))}
                  </div>
                  {clip.layout_usado && <p className="text-xs text-apagado mt-2">Último export usou: <b>{clip.layout_usado}</b></p>}
                </div>
                {cfg.layout === "centro" && (
                  <div>
                    <div className="flex justify-between text-xs mb-1.5">
                      <span className="text-suave">Posição horizontal do recorte</span>
                      <span className="tabular-nums">{Math.round((cfg.deslocamento_x || 0) * 100)}</span>
                    </div>
                    <input type="range" min={-1} max={1} step={0.02} value={cfg.deslocamento_x || 0} onChange={(e) => mudarConfig("deslocamento_x", Number(e.target.value))} className="w-full accent-roxo" />
                  </div>
                )}
                <Alternador ativo={!!cfg.zoom} aoMudar={(v) => mudarConfig("zoom", v)} rotulo="Zoom automático" descricao="Aproxima suavemente nas palavras de ênfase e nos picos (gameplay)" />
              </>
            )}

            {aba === "titulo" && (
              <>
                <div className="flex items-center gap-4 rounded-xl border border-borda bg-fundo p-4">
                  <ScoreBadge nota={clip.nota} tamanho={52} />
                  <div className="text-sm text-suave">{clip.justificativa}</div>
                </div>
                <Alternador ativo={!!cfg.titulo_ativo} aoMudar={(v) => mudarConfig("titulo_ativo", v)} rotulo="Mostrar título gancho" descricao="Aparece nos primeiros 2,8 segundos com fundo destacado" />
                <div>
                  <div className="rotulo mb-2">Título</div>
                  <textarea rows={3} value={rascunho.titulo} onChange={(e) => setRascunho((r) => ({ ...r, titulo: e.target.value }))} className="campo resize-none" />
                </div>
              </>
            )}

            {aba === "audio" && (
              <>
                <Alternador ativo={!!cfg.normalizar} aoMudar={(v) => mudarConfig("normalizar", v)} rotulo="Normalizar volume" descricao="Padrão das redes (-14 LUFS)" />
                <Alternador ativo={!!cfg.remover_silencios} aoMudar={(v) => mudarConfig("remover_silencios", v)} rotulo="Remover silêncios e vícios" descricao="Corta pausas longas e “hum”, “é”, “tipo” isolados" />
                <div>
                  <div className="rotulo mb-2">Música de fundo</div>
                  <input value={cfg.musica || ""} onChange={(e) => mudarConfig("musica", e.target.value || null)} placeholder="C:\musicas\lofi.mp3 (vazio = sem música)" className="campo font-mono text-[13px]" />
                  <p className="text-xs text-apagado mt-2">A música abaixa sozinha quando há voz.</p>
                </div>
              </>
            )}

            {alterado && (
              <Aviso tipo="info">Clique em <b>Exportar</b> para gerar o vídeo com as alterações.</Aviso>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function AjusteTempo({ rotulo, valor, aoMudar }) {
  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-suave">{rotulo}</span>
      <div className="inline-flex items-center rounded-lg border border-borda bg-card">
        <button className="px-2 py-1 text-suave hover:text-texto cursor-pointer" onClick={() => aoMudar(+(valor - 0.5).toFixed(2))}><Minus className="size-3.5" /></button>
        <span className="px-1 tabular-nums font-semibold text-sm min-w-14 text-center">{formatarTempoPreciso(valor)}</span>
        <button className="px-2 py-1 text-suave hover:text-texto cursor-pointer" onClick={() => aoMudar(+(valor + 0.5).toFixed(2))}><Plus className="size-3.5" /></button>
      </div>
    </div>
  );
}

// Linha do tempo com alças arrastáveis para início/fim (janela de ±30s ao redor do clipe)
function LinhaDoTempo({ inicio, fim, total, cursor, aoMudar }) {
  const barra = useRef(null);
  const [janela] = useState(() => [Math.max(0, inicio - 30), Math.min(total, fim + 30)]);
  const [ja, jb] = [Math.min(janela[0], inicio), Math.max(janela[1], fim)];
  const pos = (t) => ((t - ja) / (jb - ja)) * 100;

  const arrastar = (qual) => (e) => {
    e.preventDefault();
    const rect = barra.current.getBoundingClientRect();
    const mover = (ev) => {
      const t = ja + ((ev.clientX - rect.left) / rect.width) * (jb - ja);
      const tt = Math.round(Math.max(ja, Math.min(jb, t)) * 10) / 10;
      if (qual === "inicio") aoMudar(Math.min(tt, fim - 2), fim);
      else aoMudar(inicio, Math.max(tt, inicio + 2));
    };
    const soltar = () => {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
    };
    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
  };

  const marcas = [];
  const passo = jb - ja > 90 ? 15 : jb - ja > 40 ? 10 : 5;
  for (let t = Math.ceil(ja / passo) * passo; t <= jb; t += passo) marcas.push(t);

  return (
    <div className="select-none">
      <div ref={barra} className="relative h-14 rounded-xl bg-card border border-borda overflow-hidden">
        {marcas.map((t) => (
          <div key={t} className="absolute top-0 bottom-0 border-l border-white/5" style={{ left: `${pos(t)}%` }}>
            <span className="absolute bottom-1 left-1 text-[10px] text-apagado tabular-nums">{Math.floor(t / 60)}:{String(Math.floor(t % 60)).padStart(2, "0")}</span>
          </div>
        ))}
        <div className="absolute top-0 bottom-0 bg-roxo/25 border-y-2 border-roxo" style={{ left: `${pos(inicio)}%`, width: `${pos(fim) - pos(inicio)}%` }} />
        {["inicio", "fim"].map((q) => (
          <div
            key={q}
            onPointerDown={arrastar(q)}
            className="absolute top-0 bottom-0 w-3 -ml-1.5 gradiente rounded-md cursor-ew-resize flex items-center justify-center shadow-lg touch-none"
            style={{ left: `${pos(q === "inicio" ? inicio : fim)}%` }}
          >
            <div className="w-0.5 h-5 bg-white/80 rounded" />
          </div>
        ))}
        {cursor != null && cursor >= ja && cursor <= jb && <div className="absolute top-0 bottom-0 w-0.5 bg-white pointer-events-none" style={{ left: `${pos(cursor)}%` }} />}
      </div>
    </div>
  );
}
