// Tela inicial: envio do vídeo + instrução + opções rápidas.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ChevronDown, FileVideo, FolderInput, Gamepad2, Mic, RectangleHorizontal, RectangleVertical, Sparkles, Square, Upload, Wand2, X,
} from "lucide-react";
import { api, criarProjeto, formatarBytes, formatarData } from "../api";
import { Alternador, Aviso, Botao, Chip, Segmentado, useAvisar } from "../components/ui";

const EXEMPLOS = [
  "5 melhores momentos",
  "legenda amarela",
  "legenda animada",
  "zoom nas partes importantes",
  "remover silêncios",
  "sem música",
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
  const [musica, setMusica] = useState("");
  const [apoio, setApoio] = useState("");
  const [refinar, setRefinar] = useState(false);
  const [estilos, setEstilos] = useState({});
  const [sistema, setSistema] = useState(null);
  const [recentes, setRecentes] = useState([]);
  const [enviando, setEnviando] = useState(null); // progresso do upload 0-1

  useEffect(() => {
    api.estilos().then(setEstilos).catch(() => {});
    api.sistema().then(setSistema).catch(() => {});
    api.projetos().then((p) => setRecentes(p.slice(0, 4))).catch(() => {});
  }, []);

  const escolherArquivo = (f) => {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXTENSOES.includes(ext)) return avisar(`Formato não suportado: ${ext}`, "erro");
    setArquivo(f);
    setUsarCaminho(false);
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
            estilo_legenda: animada ? "animada" : "simples", layout,
            musica_caminho: musica || null, video_apoio: apoio || null, refinar_frames: refinar,
          },
        },
        setEnviando,
      );
      navegar(`/projetos/${projeto.id}`);
    } catch (e) {
      avisar(e.message, "erro");
      setEnviando(null);
    }
  }, [pronto, enviando, usarCaminho, arquivo, caminho, instrucao, modo, numClips, duracao, formato, preset, animada, layout, musica, apoio, refinar, navegar, avisar]);

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
                <option value="split">Gameplay em cima + facecam/apoio embaixo</option>
              </select>
            </div>
            <div>
              <label className="rotulo">Música de fundo (caminho, opcional)</label>
              <input value={musica} onChange={(e) => setMusica(e.target.value)} placeholder="C:\musicas\lofi.mp3" className="campo mt-2 font-mono text-[13px]" />
            </div>
            {modo === "gameplay" && (
              <>
                <div>
                  <label className="rotulo">Vídeo de apoio (se não houver facecam)</label>
                  <input value={apoio} onChange={(e) => setApoio(e.target.value)} placeholder="C:\videos\satisfatorio.mp4" className="campo mt-2 font-mono text-[13px]" />
                </div>
                <div className="flex items-end">
                  <Alternador ativo={refinar} aoMudar={setRefinar} rotulo="Refinar com imagens" descricao="Envia 4 frames dos melhores candidatos ao Claude (custa um pouco mais)" />
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
