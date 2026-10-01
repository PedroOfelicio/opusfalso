// Tela inicial: envio do vídeo + instrução + opções rápidas.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  AudioLines, Check, ChevronDown, FileVideo, FolderInput, Gamepad2, LayoutTemplate, Mic, Music, RectangleHorizontal, RectangleVertical,
  Save, SlidersHorizontal, Sparkles, Square, Trash2, Upload, Wand2, X, ZoomIn,
} from "lucide-react";
import PreviewLegenda from "../components/PreviewLegenda";
import { api, CLIMAS, criarProjeto, formatarBytes, formatarData } from "../api";
import { Alternador, Aviso, Botao, Chip, Segmentado, useAvisar } from "../components/ui";

const EXEMPLOS = [
  "5 melhores momentos",
  "legenda amarela",
  "legenda animada",
  "zoom nas partes importantes",
  "remover silêncios",
  "música energética",
  "efeitos sonoros",
  "zoom nas kills",
  "título chamativo",
];
const DURACOES = { "15-30s": [15, 30], "30-60s": [30, 60], "60-90s": [60, 90] };
const FORMATOS = [
  { valor: "9:16", rotulo: "9:16", icone: RectangleVertical },
  { valor: "1:1", rotulo: "1:1", icone: Square },
  { valor: "16:9", rotulo: "16:9", icone: RectangleHorizontal },
];
const EXTENSOES = [".mp4", ".mov", ".mkv", ".webm", ".m4v"];

export default function Home() {
  const navegar = useNavigate();
  const avisar = useAvisar();
  const [parametros] = useSearchParams();
  const entradaArquivo = useRef(null);
  const [arquivo, setArquivo] = useState(null);
  const [caminho, setCaminho] = useState("");
  const [usarCaminho, setUsarCaminho] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const [instrucao, setInstrucao] = useState("");
  const [modo, setModo] = useState("falado");
  const [numClips, setNumClips] = useState(3);
  const [duracao, setDuracao] = useState("30-60s");
  const [formato, setFormato] = useState("9:16");
  const [preset, setPreset] = useState("opus");
  const [animada, setAnimada] = useState(false);
  const [avancado, setAvancado] = useState(false);
  const [layout, setLayout] = useState("auto");
  const [musica, setMusica] = useState(""); // "" | "auto" | clima | "arquivo"
  const [musicaArquivo, setMusicaArquivo] = useState("");
  const [efeitos, setEfeitos] = useState(false);
  const [audio, setAudio] = useState(null);
  const [cor, setCor] = useState(null);
  const [zoom, setZoom] = useState(false);
  const [silencios, setSilencios] = useState(false);
  const [titulo, setTitulo] = useState(true);
  const [barra, setBarra] = useState(null); // null = padrão do estilo de legenda
  const [abertura, setAbertura] = useState(true);
  const [limparVoz, setLimparVoz] = useState(null); // null = automático (fala sim, gameplay não)
  const [templates, setTemplates] = useState({});
  const [template, setTemplate] = useState(null);
  const [apoio, setApoio] = useState("");
  const [verImagens, setVerImagens] = useState(true);
  const [estilos, setEstilos] = useState({});
  const [sistema, setSistema] = useState(null);
  const [recentes, setRecentes] = useState([]);
  const [enviando, setEnviando] = useState(null); // progresso do upload 0-1

  useEffect(() => {
    api.estilos().then(setEstilos).catch(() => {});
    api.sistema().then(setSistema).catch(() => {});
    api.audio().then(setAudio).catch(() => {});
    api.templates().then(setTemplates).catch(() => {});
    api.projetos().then((p) => setRecentes(p.slice(0, 4))).catch(() => {});
  }, []);

  // Vindo de um vídeo longo ("Gerar clipes curtos"): já abre com o mesmo arquivo (a transcrição está em cache)
  useEffect(() => {
    const c = parametros.get("caminho");
    if (c) {
      setUsarCaminho(true);
      setCaminho(c);
    }
    const m = parametros.get("modo");
    if (m === "falado" || m === "gameplay") setModo(m);
  }, [parametros]);

  const escolherArquivo = (f) => {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXTENSOES.includes(ext)) return avisar(`Formato não suportado: ${ext}`, "erro");
    setArquivo(f);
    setUsarCaminho(false);
  };

  // Estilo padrão apagado (ex.: "opus"): usa o primeiro que existir
  useEffect(() => {
    const ids = Object.keys(estilos);
    if (ids.length && !estilos[preset]) setPreset(ids[0]);
  }, [estilos, preset]);

  const aplicarTemplate = (id) => {
    const t = templates[id];
    setTemplate(id);
    if (!t) return;
    if (t.modo) setModo(t.modo);
    setPreset(t.preset);
    setCor(t.cor || null);
    setAnimada(!!t.animada);
    setFormato(t.formato);
    setLayout(t.layout);
    const chave = Object.keys(DURACOES).find((k) => DURACOES[k][0] === t.duracao[0] && DURACOES[k][1] === t.duracao[1]);
    if (chave) setDuracao(chave);
    setTitulo(t.titulo);
    setBarra(t.barra ?? null);
    setZoom(!!t.zoom);
    setSilencios(!!t.remover_silencios);
    setMusica(t.musica || "");
    setEfeitos(!!t.efeitos);
    setAbertura(t.abertura ?? true);
  };

  const salvarComoTemplate = async () => {
    const nome = window.prompt("Nome do template:", template && templates[template] ? `${templates[template].nome} (meu)` : "Meu template");
    if (!nome?.trim()) return;
    const id = nome.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30).padEnd(2, "_") || "template";
    try {
      const lista = await api.salvarTemplate(id, {
        nome: nome.trim().slice(0, 40), descricao: "Criado a partir das opções atuais", modo, preset, cor, animada, formato, layout,
        duracao: DURACOES[duracao], titulo, barra, zoom, remover_silencios: silencios,
        musica: musica === "arquivo" ? "" : musica, efeitos, abertura,
      });
      setTemplates(lista);
      setTemplate(id);
      avisar("Template salvo");
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  const excluirTemplate = async (id) => {
    if (!window.confirm(`Excluir o template "${templates[id]?.nome}"?`)) return;
    try {
      setTemplates(await api.excluirTemplate(id));
      if (template === id) setTemplate(null);
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  const adicionarExemplo = (texto) =>
    setInstrucao((atual) => (atual.trim() ? `${atual.trim().replace(/[,.]$/, "")}, ${texto}` : texto));

  const pronto = usarCaminho ? caminho.trim().length > 3 : !!arquivo;

  const gerar = useCallback(async () => {
    if (!pronto || enviando !== null) return;
    setEnviando(0);
    try {
      const projeto = await criarProjeto(
        {
          arquivo: usarCaminho ? null : arquivo,
          caminho,
          instrucao,
          modo,
          opcoes: {
            num_clips: numClips, duracao: DURACOES[duracao], formato, preset,
            estilo_legenda: animada ? "animada" : "simples", layout, cor, template,
            zoom, remover_silencios: silencios, titulo, barra, abertura, limpar_voz: limparVoz,
            musica: musica === "arquivo" ? musicaArquivo.trim() : musica, efeitos_sonoros: efeitos,
            video_apoio: apoio || null, ver_imagens: verImagens,
          },
        },
        setEnviando,
      );
      navegar(`/projetos/${projeto.id}`);
    } catch (e) {
      avisar(e.message, "erro");
      setEnviando(null);
    }
  }, [pronto, enviando, usarCaminho, arquivo, caminho, instrucao, modo, numClips, duracao, formato, preset, animada, layout, musica, musicaArquivo, efeitos, cor, template, zoom, silencios, titulo, barra, abertura, limparVoz, apoio, verImagens, navegar, avisar]);

  // Ctrl+Enter = gerar
  useEffect(() => {
    const tecla = (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        gerar();
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [gerar]);

  return (
    <div className="max-w-3xl mx-auto px-6 py-12 lg:py-16">
      <div className="text-center mb-10 animate-surgir">
        <div className="inline-flex items-center gap-2 text-xs font-semibold text-suave border border-borda bg-card rounded-full px-3 py-1 mb-5">
          <Sparkles className="size-3.5 text-roxo" /> Tudo roda no seu computador
        </div>
        <h1 className="text-4xl lg:text-5xl font-extrabold tracking-tight">
          O que vamos <span className="texto-gradiente">criar hoje?</span>
        </h1>
        <p className="text-suave mt-3">Envie um vídeo longo e descreva o que você quer. A IA encontra os melhores momentos.</p>
      </div>

      {sistema && !sistema.tem_chave && (
        <div className="mb-5">
          <Aviso tipo="alerta" titulo="Chave da API não configurada">
            Sem a chave, a seleção de trechos usa o planejador local (mais simples).{" "}
            <Link to="/configuracoes" className="underline">Configurar</Link>
          </Aviso>
        </div>
      )}

      <div className="cartao p-2 shadow-suave">
        {/* Área de envio */}
        {!usarCaminho ? (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={(e) => {
              e.preventDefault();
              setArrastando(false);
              escolherArquivo(e.dataTransfer.files?.[0]);
            }}
            onClick={() => !arquivo && entradaArquivo.current?.click()}
            className={`rounded-xl border-2 border-dashed transition-all px-6 ${arquivo ? "py-5 border-borda cursor-default" : "py-10 cursor-pointer"} ${
              arrastando ? "border-roxo bg-roxo/10" : "border-borda hover:border-borda-forte hover:bg-white/[0.02]"
            }`}
          >
            <input ref={entradaArquivo} type="file" accept={EXTENSOES.join(",")} className="hidden" onChange={(e) => escolherArquivo(e.target.files?.[0])} />
            {arquivo ? (
              <div className="flex items-center gap-4">
                <div className="size-12 rounded-xl gradiente flex items-center justify-center shrink-0">
                  <FileVideo className="size-6 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{arquivo.name}</div>
                  <div className="text-xs text-suave">{formatarBytes(arquivo.size)}</div>
                </div>
                <button onClick={() => setArquivo(null)} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5 cursor-pointer" aria-label="Remover">
                  <X className="size-4" />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center text-center">
                <div className="size-14 rounded-2xl bg-card-2 border border-borda flex items-center justify-center mb-4">
                  <Upload className="size-6 text-roxo" />
                </div>
                <div className="font-semibold">Arraste seu vídeo aqui</div>
                <div className="text-sm text-suave mt-1">ou clique para escolher · MP4, MOV, MKV</div>
              </div>
            )}
          </div>
        ) : (
          <div className="p-3">
            <label className="rotulo">Caminho do vídeo no seu computador</label>
            <input
              autoFocus
              value={caminho}
              onChange={(e) => setCaminho(e.target.value)}
              placeholder="C:\Users\voce\Videos\podcast.mp4"
              className="campo mt-2 font-mono text-[13px]"
            />
            <p className="text-xs text-apagado mt-2">O arquivo não é copiado: o processamento lê direto de onde ele está.</p>
          </div>
        )}
        <div className="flex justify-center py-2">
          <button onClick={() => setUsarCaminho(!usarCaminho)} className="text-xs text-suave hover:text-texto inline-flex items-center gap-1.5 cursor-pointer">
            <FolderInput className="size-3.5" />
            {usarCaminho ? "Enviar arquivo em vez disso" : "Ou colar um caminho local (sem upload, mais rápido)"}
          </button>
        </div>

        {/* Instrução */}
        <div className="px-3 pb-3">
          <textarea
            value={instrucao}
            onChange={(e) => setInstrucao(e.target.value)}
            rows={3}
            placeholder='Ex.: "5 melhores momentos, vertical, legenda amarela, zoom nas partes importantes, sem música"'
            className="campo resize-none text-[15px] leading-relaxed !bg-card-2"
          />
          <div className="flex flex-wrap gap-2 mt-3">
            {EXEMPLOS.map((ex) => (
              <Chip key={ex} onClick={() => adicionarExemplo(ex)}>
                + {ex}
              </Chip>
            ))}
          </div>
        </div>
      </div>

      {/* Templates */}
      <div className="cartao p-5 mt-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="rotulo inline-flex items-center gap-1.5"><LayoutTemplate className="size-3.5" /> Template visual</div>
          <button onClick={salvarComoTemplate} className="text-xs text-suave hover:text-texto inline-flex items-center gap-1 cursor-pointer">
            <Save className="size-3.5" /> Salvar opções atuais como template
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            onClick={() => setTemplate(null)}
            className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors cursor-pointer ${template === null ? "border-roxo bg-roxo/10" : "border-borda hover:border-borda-forte"}`}
          >
            <div className="w-[90px] h-[160px] rounded-xl border border-dashed border-borda flex items-center justify-center shrink-0">
              <SlidersHorizontal className="size-6 text-apagado" />
            </div>
            <div className="min-w-0">
              <div className="font-semibold text-sm">Personalizado</div>
              <div className="text-xs text-suave mt-1">Escolha cada opção abaixo, uma por uma.</div>
            </div>
          </button>
          {Object.entries(templates).map(([id, t]) => (
            <div
              key={id}
              role="button"
              tabIndex={0}
              onClick={() => aplicarTemplate(id)}
              onKeyDown={(e) => e.key === "Enter" && aplicarTemplate(id)}
              className={`group relative flex items-center gap-3 rounded-xl border p-3 text-left transition-colors cursor-pointer ${template === id ? "border-roxo bg-roxo/10" : "border-borda hover:border-borda-forte"}`}
            >
              {estilos[t.preset] ? (
                <PreviewLegenda
                  estilo={{ ...estilos[t.preset], cor_destaque: t.cor || estilos[t.preset].cor_destaque, barra_progresso: { ...estilos[t.preset].barra_progresso, ativa: t.barra ?? estilos[t.preset].barra_progresso?.ativa } }}
                  titulo={t.titulo ? t.nome : null}
                  largura={90}
                  fundo={recentes[0]?.thumb_url}
                />
              ) : (
                <div className="w-[90px] h-[160px] rounded-xl bg-card-2 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-sm flex items-center gap-1.5">
                  {template === id && <Check className="size-3.5 text-roxo shrink-0" />}
                  <span className="truncate">{t.nome}</span>
                </div>
                <div className="text-xs text-suave mt-1 line-clamp-2">{t.descricao}</div>
                <div className="flex flex-wrap gap-1 mt-2 text-[10px] text-apagado">
                  <span className="rounded-md bg-card-2 px-1.5 py-0.5">{t.formato}</span>
                  <span className="rounded-md bg-card-2 px-1.5 py-0.5">{t.duracao[0]}-{t.duracao[1]}s</span>
                  {t.modo && <span className="rounded-md bg-card-2 px-1.5 py-0.5">{t.modo === "gameplay" ? "Gameplay" : "Falado"}</span>}
                  {t.zoom && <span className="rounded-md bg-card-2 px-1.5 py-0.5 inline-flex items-center gap-0.5"><ZoomIn className="size-2.5" />zoom</span>}
                  {t.musica && <span className="rounded-md bg-card-2 px-1.5 py-0.5 inline-flex items-center gap-0.5"><Music className="size-2.5" />{CLIMAS[t.musica] || "auto"}</span>}
                  {t.efeitos && <span className="rounded-md bg-card-2 px-1.5 py-0.5 inline-flex items-center gap-0.5"><AudioLines className="size-2.5" />efeitos</span>}
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); excluirTemplate(id); }}
                className="absolute top-2 right-2 p-1 rounded-md text-apagado opacity-0 group-hover:opacity-100 hover:text-texto hover:bg-white/5 cursor-pointer"
                aria-label="Excluir template"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Opções rápidas */}
      <div className="cartao p-5 mt-4 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="rotulo mb-2">Tipo de vídeo</div>
            <Segmentado
              valor={modo}
              aoMudar={setModo}
              opcoes={[
                { valor: "falado", rotulo: "Falado", icone: Mic },
                { valor: "gameplay", rotulo: "Gameplay", icone: Gamepad2 },
              ]}
            />
          </div>
          <div>
            <div className="rotulo mb-2">Nº de clipes</div>
            <div className="inline-flex items-center rounded-xl border border-borda bg-fundo">
              <button className="px-3 py-2 text-suave hover:text-texto cursor-pointer" onClick={() => setNumClips(Math.max(1, numClips - 1))}>−</button>
              <span className="w-8 text-center font-semibold tabular-nums">{numClips}</span>
              <button className="px-3 py-2 text-suave hover:text-texto cursor-pointer" onClick={() => setNumClips(Math.min(15, numClips + 1))}>+</button>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-5">
          <div>
            <div className="rotulo mb-2">Duração</div>
            <div className="flex gap-2">
              {Object.keys(DURACOES).map((d) => (
                <Chip key={d} ativo={duracao === d} onClick={() => setDuracao(d)}>{d}</Chip>
              ))}
            </div>
          </div>
          <div>
            <div className="rotulo mb-2">Formato</div>
            <Segmentado valor={formato} aoMudar={setFormato} opcoes={FORMATOS} tamanho="sm" />
          </div>
          <div>
            <div className="rotulo mb-2">Legenda</div>
            <div className="flex items-center gap-2">
              <select value={preset} onChange={(e) => setPreset(e.target.value)} className="campo !w-auto !py-1.5 cursor-pointer">
                {Object.entries(estilos).map(([id, e]) => (
                  <option key={id} value={id}>{e.nome || id}</option>
                ))}
              </select>
              <Chip ativo={animada} onClick={() => setAnimada(!animada)}>
                <Wand2 className="inline size-3 mr-1" />Animada
              </Chip>
            </div>
          </div>
        </div>

        <button onClick={() => setAvancado(!avancado)} className="text-xs text-suave hover:text-texto inline-flex items-center gap-1 cursor-pointer">
          <ChevronDown className={`size-3.5 transition-transform ${avancado ? "rotate-180" : ""}`} /> Opções avançadas
        </button>
        {avancado && (
          <div className="grid sm:grid-cols-2 gap-4 animate-surgir">
            <div>
              <label className="rotulo">Enquadramento</label>
              <select value={layout} onChange={(e) => setLayout(e.target.value)} className="campo mt-2 cursor-pointer">
                <option value="auto">Automático</option>
                <option value="rosto">Seguir quem fala</option>
                <option value="dupla">Duas pessoas (tela dividida)</option>
                <option value="centro">Recorte central fixo</option>
                <option value="inteiro">Vídeo inteiro + fundo desfocado</option>
                <option value="jogo">Gameplay em destaque (recorte 4:5)</option>
                <option value="split">Gameplay em cima + facecam/apoio embaixo</option>
              </select>
            </div>
            <div>
              <label className="rotulo">Música de fundo</label>
              <select value={musica} onChange={(e) => setMusica(e.target.value)} className="campo mt-2 cursor-pointer">
                <option value="">Sem música</option>
                <option value="auto">Automática (o Claude escolhe o clima)</option>
                {Object.entries(CLIMAS).map(([k, r]) => (
                  <option key={k} value={k}>{r} ({audio?.musicas?.[k]?.length ?? 0})</option>
                ))}
                <option value="arquivo">Arquivo específico…</option>
              </select>
              {musica === "arquivo" && (
                <input value={musicaArquivo} onChange={(e) => setMusicaArquivo(e.target.value)} placeholder="C:\musicas\lofi.mp3" className="campo mt-2 font-mono text-[13px]" />
              )}
            </div>
            <div className="flex flex-col justify-end gap-1">
              <Alternador ativo={efeitos} aoMudar={setEfeitos} rotulo="Efeitos sonoros" descricao="Whoosh no título, impacto nas kills, pop nos zooms" />
              {audio && Object.values(audio.musicas).every((l) => !l.length) && (
                <Link to="/configuracoes#audio" className="text-xs text-roxo hover:underline text-left">
                  Sem músicas na biblioteca: baixar o pacote grátis
                </Link>
              )}
            </div>
            <Alternador ativo={zoom} aoMudar={setZoom} rotulo="Zoom automático" descricao="Nas palavras de ênfase e nos picos do gameplay" />
            <Alternador ativo={silencios} aoMudar={setSilencios} rotulo="Remover silêncios e vícios" descricao="Corta pausas longas e “hum”, “é”, “tipo” isolados" />
            <Alternador ativo={titulo} aoMudar={setTitulo} rotulo="Título gancho" descricao="Aparece nos primeiros segundos" />
            <Alternador ativo={limparVoz ?? modo === "falado"} aoMudar={setLimparVoz} rotulo="Melhorar a voz" descricao="Tira ruído de fundo e zumbido (automático na fala)" />
            <Alternador ativo={abertura} aoMudar={setAbertura} rotulo="Abrir com o clímax" descricao="1-2 s do melhor momento antes do contexto (segura nos 3 primeiros segundos)" />
            <Alternador ativo={barra ?? !!estilos[preset]?.barra_progresso?.ativa} aoMudar={setBarra} rotulo="Barra de progresso" descricao="Enche no topo durante o clipe" />
            {modo === "gameplay" && (
              <>
                <div>
                  <label className="rotulo">Vídeo de apoio (se não houver facecam)</label>
                  <input value={apoio} onChange={(e) => setApoio(e.target.value)} placeholder="C:\videos\satisfatorio.mp4" className="campo mt-2 font-mono text-[13px]" />
                </div>
                <div className="flex items-end">
                  <Alternador ativo={verImagens} aoMudar={setVerImagens} rotulo="Claude vê as imagens do jogo" descricao="8 quadros por momento: descarta menus e tempo morto, apara início e fim (~US$ 0,01 por vídeo)" />
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-col items-center gap-3">
        <Botao variante="primario" tamanho="lg" icone={Sparkles} onClick={gerar} disabled={!pronto} carregando={enviando !== null} className="w-full sm:w-auto sm:min-w-72">
          {enviando !== null ? (enviando < 1 ? `Enviando ${Math.round(enviando * 100)}%` : "Criando projeto…") : "Gerar clipes"}
        </Botao>
        <span className="text-xs text-apagado">
          <kbd className="px-1.5 py-0.5 rounded bg-card border border-borda">Ctrl</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-card border border-borda">Enter</kbd>
        </span>
      </div>

      {recentes.length > 0 && (
        <div className="mt-14">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-suave">Recentes</h2>
            <Link to="/projetos" className="text-xs text-suave hover:text-texto">Ver todos</Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {recentes.map((p) => (
              <Link key={p.id} to={`/projetos/${p.id}`} className="cartao overflow-hidden hover:border-borda-forte transition-colors">
                <img src={p.thumb_url} alt="" className="aspect-video w-full object-cover bg-card-2" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                <div className="p-2.5">
                  <div className="text-xs font-semibold truncate">{p.nome}</div>
                  <div className="text-[11px] text-apagado">{formatarData(p.criado_em)}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
