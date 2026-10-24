// Aba "Vídeos longos": enxugar o vídeo inteiro ou montar os melhores momentos para o YouTube.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Film, FileVideo, FolderInput, Gamepad2, Mic, Scissors, Sparkles, Trophy, Upload, X } from "lucide-react";
import { api, CLIMAS, criarLongo, formatarBytes, formatarData, formatarDuracao } from "../api";
import { Alternador, Aviso, Botao, Chip, Esqueleto, Segmentado, usePolling, useAvisar } from "../components/ui";

const EXTENSOES = [".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"];
const ALVOS = [3, 5, 10, 15, 20];
const MODOS = [
  {
    id: "enxugar",
    icone: Scissors,
    titulo: "Enxugar o vídeo inteiro",
    texto: {
      falado: "Tira silêncios, “hum/é/tipo” e erros de gravação (frase repetida, começo em falso). O conteúdo fica todo, com capítulos.",
      gameplay: "Tira menus, loading, fase de compra, tela preta e tempo parado. A gameplay fica toda, com capítulos por partida.",
    },
  },
  {
    id: "melhores",
    icone: Trophy,
    titulo: "Melhores momentos",
    texto: {
      falado: "Compilação com os trechos mais fortes do vídeo, cada um virando um capítulo, na duração que você escolher.",
      gameplay: "Compilação com os melhores lances da live, com transição e título em cada um, na duração que você escolher.",
    },
  },
];
const CUSTO = {
  falado: { enxugar: "~US$ 0,05 por hora de vídeo", melhores: "~US$ 0,05 por hora de vídeo" },
  gameplay: { enxugar: "~US$ 0,20 por hora com imagens (~US$ 0,01 sem)", melhores: "~US$ 0,15-0,25 por compilação com imagens" },
};
const STATUS = {
  pronto: "bg-verde/15 text-verde",
  processando: "bg-azul/15 text-azul",
  fila: "bg-azul/15 text-azul",
  erro: "bg-vermelho/15 text-vermelho",
  cancelado: "bg-white/10 text-suave",
};
const ROTULO_STATUS = { pronto: "Pronto", processando: "Processando", fila: "Na fila", erro: "Erro", cancelado: "Cancelado" };

export default function Longos() {
  const navegar = useNavigate();
  const avisar = useAvisar();
  const entrada = useRef(null);
  const [usarArquivo, setUsarArquivo] = useState(false);
  const [arquivo, setArquivo] = useState(null);
  const [caminho, setCaminho] = useState("");
  const [modo, setModo] = useState("falado");
  const [modoLongo, setModoLongo] = useState("enxugar");
  const [alvo, setAlvo] = useState(10);
  const [instrucao, setInstrucao] = useState("");
  const [abertura, setAbertura] = useState(true);
  const [zoom, setZoom] = useState(true);
  const [legenda, setLegenda] = useState(false);
  const [preset, setPreset] = useState("minimalista");
  const [efeitos, setEfeitos] = useState(false);
  const [musica, setMusica] = useState("");
  const [verImagens, setVerImagens] = useState(true);
  const [cortarParado, setCortarParado] = useState(true);
  const [removerErros, setRemoverErros] = useState(true);
  const [ritmo, setRitmo] = useState("dinamico");
  const [limparVoz, setLimparVoz] = useState(null); // null = automático (fala sim, gameplay não)
  const [estilos, setEstilos] = useState({});
  const [lista, setLista] = useState(null);
  const [enviando, setEnviando] = useState(null);

  const carregar = useCallback(() => {
    api.projetos().then((l) => setLista(l.filter((p) => p.tipo === "longo"))).catch(() => setLista([]));
  }, []);
  useEffect(() => {
    carregar();
    api.estilos().then(setEstilos).catch(() => {});
  }, [carregar]);
  usePolling(carregar, 2000, !!lista?.some((p) => ["fila", "processando"].includes(p.status)));

  // Compilação de gameplay costuma ter música e efeitos; vídeo falado inteiro, não
  useEffect(() => {
    setEfeitos(modoLongo === "melhores" && modo === "gameplay");
  }, [modoLongo, modo]);

  const escolher = (f) => {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXTENSOES.includes(ext)) return avisar(`Formato não suportado: ${ext}`, "erro");
    setArquivo(f);
  };

  const pronto = usarArquivo ? !!arquivo : caminho.trim().length > 3;

  const editar = async () => {
    if (!pronto || enviando !== null) return;
    setEnviando(0);
    try {
      const projeto = await criarLongo(
        {
          arquivo: usarArquivo ? arquivo : null,
          caminho,
          instrucao,
          modo,
          opcoes: {
            modo_longo: modoLongo, alvo_min: alvo, abertura, zoom, legenda, preset, efeitos, musica,
            ver_imagens: verImagens, cortar_parado: cortarParado, remover_erros: removerErros,
            ritmo, limpar_voz: limparVoz,
          },
        },
        setEnviando,
      );
      navegar(`/longos/${projeto.id}`);
    } catch (e) {
      avisar(e.message, "erro");
      setEnviando(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight flex items-center gap-3">
          <Film className="size-7 text-roxo" /> Vídeos longos
        </h1>
        <p className="text-sm text-suave mt-1">
          Para o YouTube: o vídeo inteiro mais enxuto, ou uma compilação dos melhores momentos. Sai com capítulos, legenda .srt, títulos, descrição e tags.
        </p>
      </div>

      {/* Vídeo */}
      <div className="cartao p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="rotulo">Vídeo</div>
          <button onClick={() => setUsarArquivo(!usarArquivo)} className="text-xs text-suave hover:text-texto inline-flex items-center gap-1.5 cursor-pointer">
            {usarArquivo ? <FolderInput className="size-3.5" /> : <Upload className="size-3.5" />}
            {usarArquivo ? "Usar um link ou caminho local" : "Enviar arquivo em vez disso"}
          </button>
        </div>
        {usarArquivo ? (
          arquivo ? (
            <div className="flex items-center gap-4 rounded-xl border border-borda p-3">
              <FileVideo className="size-6 text-roxo shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{arquivo.name}</div>
                <div className="text-xs text-suave">{formatarBytes(arquivo.size)}</div>
              </div>
              <button onClick={() => setArquivo(null)} className="p-2 rounded-lg text-suave hover:text-texto hover:bg-white/5 cursor-pointer" aria-label="Remover">
                <X className="size-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => entrada.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                escolher(e.dataTransfer.files?.[0]);
              }}
              className="w-full rounded-xl border-2 border-dashed border-borda hover:border-borda-forte py-8 text-center cursor-pointer"
            >
              <Upload className="size-6 text-roxo mx-auto mb-2" />
              <div className="font-semibold text-sm">Arraste o vídeo ou clique para escolher</div>
              <div className="text-xs text-suave mt-1">Arquivos grandes: prefira o caminho local (não copia nada)</div>
            </button>
          )
        ) : (
          <>
            <input value={caminho} onChange={(e) => setCaminho(e.target.value)} placeholder="https://youtube.com/watch?v=...  ou  C:\Users\voce\Videos\live_de_ontem.mp4" className="campo font-mono text-[13px]" />
            <p className="text-xs text-apagado mt-2">
              {/^\s*https?:\/\//.test(caminho)
                ? "Link: o vídeo é baixado (até 1080p), editado e o original é apagado no fim. Para revisar ou remontar depois, ele é baixado de novo sozinho."
                : "Link do YouTube ou caminho local (o arquivo não é enviado nem copiado, é lido direto de onde está)."}
            </p>
          </>
        )}
        <input ref={entrada} type="file" accept={EXTENSOES.join(",")} className="hidden" onChange={(e) => escolher(e.target.files?.[0])} />

        <div className="mt-5 flex flex-wrap items-center gap-4">
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
          <p className="text-xs text-apagado flex-1 min-w-60">
            {modo === "falado" ? "Podcast, aula, vlog, entrevista: a edição segue a fala." : "Live ou gravação de jogo: a edição segue a ação na tela e no áudio."}
          </p>
        </div>
      </div>

      {/* O que fazer */}
      <div className="grid sm:grid-cols-2 gap-3 mt-4">
        {MODOS.map(({ id, icone: Icone, titulo, texto }) => (
          <button
            key={id}
            onClick={() => setModoLongo(id)}
            className={`text-left rounded-2xl border p-5 transition-colors cursor-pointer ${modoLongo === id ? "border-roxo bg-roxo/10" : "border-borda bg-card hover:border-borda-forte"}`}
          >
            <div className="flex items-center gap-3">
              <div className={`size-10 rounded-xl flex items-center justify-center ${modoLongo === id ? "gradiente text-white" : "bg-card-2 text-roxo"}`}>
                <Icone className="size-5" />
              </div>
              <div className="font-bold">{titulo}</div>
            </div>
            <p className="text-sm text-suave mt-3">{texto[modo]}</p>
          </button>
        ))}
      </div>

      <div className="cartao p-5 mt-4 space-y-5">
        {modoLongo === "melhores" && (
          <div>
            <div className="rotulo mb-2">Duração da compilação</div>
            <div className="flex flex-wrap gap-2">
              {ALVOS.map((m) => (
                <Chip key={m} ativo={alvo === m} onClick={() => setAlvo(m)}>{m} min</Chip>
              ))}
            </div>
          </div>
        )}
        <div>
          <label className="rotulo">Instrução (opcional)</label>
          <textarea
            value={instrucao}
            onChange={(e) => setInstrucao(e.target.value)}
            rows={2}
            placeholder={modo === "falado" ? "Ex.: tira a parte do patrocínio e a conversa no final" : "Ex.: só as partidas de ranqueada"}
            className="campo mt-2 resize-none"
          />
        </div>

        {modo === "falado" && (
          <div>
            <div className="rotulo mb-2">Ritmo</div>
            <Segmentado
              tamanho="sm"
              valor={ritmo}
              aoMudar={setRitmo}
              opcoes={[
                { valor: "natural", rotulo: "Natural" },
                { valor: "dinamico", rotulo: "Dinâmico" },
                { valor: "rapido", rotulo: "Rápido" },
              ]}
            />
            <p className="text-xs text-apagado mt-2">
              {ritmo === "natural" ? "Deixa pausas de até ~0,9 s: bom para aula e entrevista." : ritmo === "rapido" ? "Pausas mínimas, estilo YouTube acelerado." : "Pausas curtas (~0,6 s): o padrão dos canais de conversa."}
            </p>
          </div>
        )}

        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-4">
          <Alternador ativo={limparVoz ?? modo === "falado"} aoMudar={setLimparVoz} rotulo="Melhorar a voz" descricao="Tira ruído de fundo e zumbido, dá presença (automático na fala)" />
          <Alternador ativo={abertura} aoMudar={setAbertura} rotulo="Abrir com o melhor momento" descricao="Teaser de alguns segundos antes de começar (segura quem chegou agora)" />
          <Alternador ativo={zoom} aoMudar={setZoom} rotulo="Zoom nos cortes" descricao="Punch-in alternado para esconder os cortes secos, com moderação" />
          {modo === "falado" ? (
            <Alternador ativo={removerErros} aoMudar={setRemoverErros} rotulo="Tirar erros de gravação" descricao="O Claude acha frases repetidas, começos em falso e desvios" />
          ) : (
            <>
              <Alternador ativo={verImagens} aoMudar={setVerImagens} rotulo="Claude vê as imagens" descricao="Acha menus, fase de compra e tempo parado olhando a tela" />
              <Alternador ativo={cortarParado} aoMudar={setCortarParado} rotulo="Cortar tempo parado" descricao="Tira andanças longas sem nada acontecendo (15 s ou mais)" />
            </>
          )}
          <Alternador ativo={efeitos} aoMudar={setEfeitos} rotulo="Efeitos nas transições" descricao="Whoosh na virada da abertura e entre os momentos" />
          <div>
            <Alternador ativo={legenda} aoMudar={setLegenda} rotulo="Legenda na tela" descricao="O arquivo .srt para o YouTube sai sempre" />
            {legenda && (
              <select value={preset} onChange={(e) => setPreset(e.target.value)} className="campo mt-2 cursor-pointer">
                {Object.entries(estilos).map(([id, e]) => <option key={id} value={id}>{e.nome || id}</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="rotulo">Música de fundo</label>
            <select value={musica} onChange={(e) => setMusica(e.target.value)} className="campo mt-2 cursor-pointer">
              <option value="">Sem música</option>
              <option value="auto">Automática</option>
              {Object.entries(CLIMAS).map(([k, r]) => <option key={k} value={k}>{r}</option>)}
            </select>
          </div>
        </div>

        {modo === "gameplay" && modoLongo === "enxugar" && !verImagens && (
          <Aviso tipo="alerta">
            Sem as imagens, o tempo morto é cortado só pelo áudio, e em jogo com som ambiente constante (como Valorant) isso quase não tira nada. Menus e fase de compra só saem com o Claude vendo a tela.
          </Aviso>
        )}
        <Aviso tipo="info">
          Custo estimado na API: {CUSTO[modo][modoLongo]}. Transcrição, cortes e render rodam no seu computador.
        </Aviso>
      </div>

      <div className="mt-6 flex justify-center">
        <Botao variante="primario" tamanho="lg" icone={Sparkles} onClick={editar} disabled={!pronto} carregando={enviando !== null} className="w-full sm:w-auto sm:min-w-72">
          {enviando !== null ? (enviando < 1 ? `Enviando ${Math.round(enviando * 100)}%` : "Criando projeto…") : "Editar vídeo"}
        </Botao>
      </div>

      {/* Lista */}
      <div className="mt-12">
        <h2 className="font-bold text-lg mb-4">Seus vídeos longos</h2>
        {!lista ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => <Esqueleto key={i} className="aspect-video" />)}
          </div>
        ) : lista.length === 0 ? (
          <p className="text-sm text-suave">Nenhum vídeo longo ainda.</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {lista.map((p) => {
              const rodando = ["fila", "processando"].includes(p.status);
              return (
                <Link key={p.id} to={`/longos/${p.id}`} className="group cartao overflow-hidden hover:border-borda-forte transition-all">
                  <div className="relative aspect-video bg-card-2 overflow-hidden">
                    <img src={p.thumb_url} alt="" className="size-full object-cover" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                    <span className={`absolute top-3 left-3 text-[11px] font-semibold px-2 py-0.5 rounded-md backdrop-blur ${STATUS[p.status] || STATUS.cancelado}`}>
                      {ROTULO_STATUS[p.status] || p.status}
                    </span>
                    {rodando && (
                      <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
                        <div className="h-full gradiente transition-all" style={{ width: `${(p.progresso || 0) * 100}%` }} />
                      </div>
                    )}
                  </div>
                  <div className="p-4">
                    <div className="font-semibold truncate">{p.nome}</div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-suave">
                      {p.modo === "gameplay" ? <Gamepad2 className="size-3.5" /> : <Mic className="size-3.5" />}
                      {p.modo_longo === "melhores" ? "Melhores momentos" : "Enxugado"}
                      <span className="ml-auto tabular-nums">
                        {rodando
                          ? `${Math.round((p.progresso || 0) * 100)}%`
                          : p.duracao_final
                            ? `${formatarDuracao(p.duracao_video)} → ${formatarDuracao(p.duracao_final)}`
                            : formatarData(p.criado_em)}
                      </span>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
