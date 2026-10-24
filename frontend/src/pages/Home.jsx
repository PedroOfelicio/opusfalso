// Início: o vídeo (link, caminho ou arquivo) e o que fazer com ele: clipes curtos ou vídeo longo.
// O essencial fica à vista; o resto, em "Mais opções".
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { BrainCircuit, ChevronDown, Cpu, FileVideo, Film, Gamepad2, Mic, Scissors, Smartphone, Sparkles, Trophy, Upload, X } from "lucide-react";
import { api, CLIMAS, criarLongo, criarProjeto, formatarBytes } from "../api";
import { Alternador, Aviso, Botao, Chip, Segmentado, useAvisar } from "../components/ui";

const EXTENSOES = [".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"];
const DURACOES = { "15-30s": [15, 30], "30-60s": [30, 60], "60-90s": [60, 90] };
const ALVOS = [3, 5, 10, 15, 20];
const CHAVE_IA = "gadosso.comIa"; // a última escolha (com/sem IA) fica lembrada neste PC

function lerComIa() {
  try {
    const v = localStorage.getItem(CHAVE_IA);
    return v === null ? null : v === "1";
  } catch {
    return null;
  }
}

const IDIOMAS = { "": "Mesmo idioma do vídeo", en: "Inglês", es: "Espanhol", pt: "Português", fr: "Francês", it: "Italiano", de: "Alemão" };

export default function Home() {
  const navegar = useNavigate();
  const avisar = useAvisar();
  const [parametros] = useSearchParams();
  const entradaArquivo = useRef(null);

  // vídeo
  const [arquivo, setArquivo] = useState(null);
  const [caminho, setCaminho] = useState("");
  const [arrastando, setArrastando] = useState(false);
  // o que fazer
  const [tipo, setTipo] = useState("curto"); // curto | longo
  const [modo, setModo] = useState("falado");
  const [instrucao, setInstrucao] = useState("");
  const [maisOpcoes, setMaisOpcoes] = useState(false);
  const [comIa, setComIaEstado] = useState(() => lerComIa() ?? true);
  const [temChave, setTemChave] = useState(true);
  // clipes curtos
  const [numClips, setNumClips] = useState(5);
  const [duracao, setDuracao] = useState("30-60s");
  const [preset, setPreset] = useState("gamer");
  const [animada, setAnimada] = useState(true);
  const [formato, setFormato] = useState("9:16");
  const [layout, setLayout] = useState("auto");
  const [idiomaLegenda, setIdiomaLegenda] = useState("");
  const [titulo, setTitulo] = useState(true);
  const [silencios, setSilencios] = useState(true);
  const [reacoes, setReacoes] = useState(true);
  const [diretor, setDiretor] = useState(true);
  const [apoio, setApoio] = useState("");
  const [replay, setReplay] = useState(true);
  const [loop, setLoop] = useState(true);
  // vídeo longo
  const [modoLongo, setModoLongo] = useState("enxugar");
  const [alvo, setAlvo] = useState(10);
  const [ritmo, setRitmo] = useState("dinamico");
  const [removerErros, setRemoverErros] = useState(true);
  const [cortarParado, setCortarParado] = useState(true);
  const [legendaLonga, setLegendaLonga] = useState(false);
  // comuns
  const [musica, setMusica] = useState("");
  const [efeitos, setEfeitos] = useState(true);
  const [zoom, setZoom] = useState(true);
  const [abertura, setAbertura] = useState(true);
  const [broll, setBroll] = useState(true);
  const [verImagens, setVerImagens] = useState(true);
  const [limparVoz, setLimparVoz] = useState(null); // null = automático (fala sim, gameplay não)

  const [estilos, setEstilos] = useState({});
  const [audio, setAudio] = useState(null);
  const [enviando, setEnviando] = useState(null); // progresso do envio 0-1

  useEffect(() => {
    api.estilos().then(setEstilos).catch(() => {});
    api.audio().then(setAudio).catch(() => {});
    // sem chave do Claude e sem escolha lembrada: já começa no "Sem IA"
    api.sistema().then((s) => {
      setTemChave(!!s?.tem_chave);
      if (!s?.tem_chave && lerComIa() === null) setComIaEstado(false);
    }).catch(() => {});
  }, []);

  const setComIa = (v) => {
    setComIaEstado(v);
    try {
      localStorage.setItem(CHAVE_IA, v ? "1" : "0");
    } catch {
      /* sem armazenamento: vale só nesta tela */
    }
  };
  useEffect(() => {
    const ids = Object.keys(estilos);
    if (ids.length && !estilos[preset]) setPreset(ids[0]);
  }, [estilos, preset]);

  // Vindo de um vídeo longo ("Gerar clipes curtos"): já abre com o mesmo vídeo (a transcrição está em cache)
  useEffect(() => {
    const c = parametros.get("caminho");
    if (c) {
      setCaminho(c);
      setTipo("curto");
    }
    const m = parametros.get("modo");
    if (m === "falado" || m === "gameplay") setModo(m);
  }, [parametros]);

  const escolherArquivo = (f) => {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXTENSOES.includes(ext)) return avisar(`Formato não suportado: ${ext}`, "erro");
    setArquivo(f);
    setCaminho("");
  };

  const mudarNumClips = (n) => {
    const novo = Math.max(1, Math.min(100, n));
    if (novo > 20 && numClips <= 20 && animada) {
      setAnimada(false);
      avisar("Com muitos clipes, troquei para a legenda simples (renderiza ~4x mais rápido). Dá para voltar em Mais opções.");
    }
    setNumClips(novo);
  };

  const link = /^\s*https?:\/\//.test(caminho);
  const pronto = !!arquivo || caminho.trim().length > 3;

  const enviar = useCallback(async () => {
    if (!pronto || enviando !== null) return;
    setEnviando(0);
    const base = { arquivo, caminho: arquivo ? "" : caminho, instrucao, modo };
    try {
      if (tipo === "curto") {
        const p = await criarProjeto({
          ...base,
          opcoes: {
            num_clips: numClips, duracao: DURACOES[duracao], formato, preset, estilo_legenda: animada ? "animada" : "simples",
            layout, zoom, remover_silencios: silencios, titulo, abertura, limpar_voz: limparVoz,
            musica, efeitos_sonoros: efeitos, video_apoio: apoio || null, ver_imagens: verImagens,
            diretor: comIa && diretor, broll: comIa && broll, reacoes: comIa && reacoes,
            idioma_legenda: comIa ? idiomaLegenda : "", replay, loop, sem_ia: !comIa,
          },
        }, setEnviando);
        navegar(`/projetos/${p.id}`);
      } else {
        const p = await criarLongo({
          ...base,
          opcoes: {
            modo_longo: modoLongo, alvo_min: alvo, abertura, zoom, legenda: legendaLonga, preset, efeitos, musica,
            ver_imagens: comIa && verImagens, cortar_parado: cortarParado, remover_erros: removerErros,
            diretor: comIa && diretor, broll: comIa && broll, ritmo, limpar_voz: limparVoz, sem_ia: !comIa,
          },
        }, setEnviando);
        navegar(`/longos/${p.id}`);
      }
    } catch (e) {
      avisar(e.message, "erro");
      setEnviando(null);
    }
  }, [pronto, enviando, arquivo, caminho, instrucao, modo, tipo, numClips, duracao, formato, preset, animada, layout, zoom, silencios, titulo, abertura, limparVoz, musica, efeitos, apoio, verImagens, diretor, broll, reacoes, idiomaLegenda, replay, loop, modoLongo, alvo, legendaLonga, cortarParado, removerErros, ritmo, comIa, navegar, avisar]);

  // Ctrl+Enter = começar
  useEffect(() => {
    const tecla = (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        enviar();
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [enviar]);

  const semMusicas = audio && Object.values(audio.musicas).every((l) => !l.length);

  return (
    <div className="max-w-3xl mx-auto px-6 py-10 lg:py-14">
      <div className="text-center mb-8 animate-surgir">
        <p className="rotulo-mono text-black/45">Edição com ou sem IA · roda no seu computador</p>
        <h1 className="text-4xl lg:text-5xl font-light tracking-[-0.03em] mt-3">O que vamos editar hoje?</h1>
      </div>

      {/* 1. O vídeo */}
      <div
        className={`cartao p-5 transition-colors ${arrastando ? "ring-2 ring-black" : ""}`}
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
      >
        <div className="rotulo mb-3">1 · O vídeo</div>
        <input ref={entradaArquivo} type="file" accept={EXTENSOES.join(",")} className="hidden" onChange={(e) => escolherArquivo(e.target.files?.[0])} />
        {arquivo ? (
          <div className="flex items-center gap-4 rounded-xl border border-black/10 p-3">
            <div className="size-11 rounded-xl gradiente flex items-center justify-center shrink-0"><FileVideo className="size-5" /></div>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{arquivo.name}</div>
              <div className="text-xs text-suave">{formatarBytes(arquivo.size)}</div>
            </div>
            <button onClick={() => setArquivo(null)} className="p-2 rounded-full text-suave hover:text-texto hover:bg-black/[0.05] cursor-pointer" aria-label="Remover">
              <X className="size-4" />
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                value={caminho}
                onChange={(e) => setCaminho(e.target.value)}
                placeholder="Cole o link do YouTube ou o caminho do vídeo no PC"
                className="campo font-mono text-[13px] flex-1"
              />
              <Botao icone={Upload} onClick={() => entradaArquivo.current?.click()}>Escolher arquivo</Botao>
            </div>
            <p className="text-xs text-apagado mt-2">
              {link
                ? "Link: o vídeo é baixado (até 1080p), editado e o original é apagado no fim. Só o resultado fica no seu PC."
                : "Também dá para arrastar o arquivo para cá. Caminho local não é copiado: é lido direto de onde está."}
            </p>
          </>
        )}
      </div>

      {/* 2. O que fazer */}
      <div className="cartao p-5 mt-4">
        <div className="rotulo mb-3">2 · O que fazer</div>
        <div className="grid sm:grid-cols-2 gap-3">
          {[
            { id: "curto", icone: Smartphone, titulo: "Clipes curtos", texto: "Os melhores momentos viram clipes verticais para TikTok, Reels e Shorts, com legenda, título e texto do post." },
            { id: "longo", icone: Film, titulo: "Vídeo longo", texto: "Para o YouTube: o vídeo inteiro enxuto ou uma compilação dos melhores momentos, com capítulos e thumbnails." },
          ].map(({ id, icone: Icone, titulo: t, texto }) => (
            <button
              key={id}
              onClick={() => setTipo(id)}
              className={`text-left rounded-2xl border p-4 transition-colors cursor-pointer ${tipo === id ? "border-black bg-black/[0.03]" : "border-black/10 hover:border-black/25"}`}
            >
              <div className="flex items-center gap-3">
                <div className={`size-10 rounded-xl flex items-center justify-center ${tipo === id ? "gradiente" : "bg-card-2 text-texto"}`}>
                  <Icone className="size-5" />
                </div>
                <div className="font-medium text-[17px]">{t}</div>
              </div>
              <p className="text-sm text-suave mt-3">{texto}</p>
            </button>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-x-8 gap-y-4">
          <div>
            <div className="rotulo mb-2">Conteúdo</div>
            <Segmentado
              valor={modo}
              aoMudar={setModo}
              opcoes={[
                { valor: "falado", rotulo: "Falado", icone: Mic },
                { valor: "gameplay", rotulo: "Gameplay", icone: Gamepad2 },
              ]}
            />
          </div>

          {tipo === "curto" ? (
            <>
              <div>
                <div className="rotulo mb-2">Clipes</div>
                <div className="flex items-center gap-2">
                  <div className="inline-flex items-center rounded-full border border-black/10 bg-white">
                    <button className="px-3 py-1.5 text-suave hover:text-texto cursor-pointer" onClick={() => mudarNumClips(numClips > 10 ? numClips - 5 : numClips - 1)}>−</button>
                    <span className="w-8 text-center font-medium tabular-nums">{numClips}</span>
                    <button className="px-3 py-1.5 text-suave hover:text-texto cursor-pointer" onClick={() => mudarNumClips(numClips >= 10 ? numClips + 5 : numClips + 1)}>+</button>
                  </div>
                  {[10, 30, 70].map((n) => (
                    <Chip key={n} ativo={numClips === n} onClick={() => mudarNumClips(n)}>{n}</Chip>
                  ))}
                </div>
              </div>
              <div>
                <div className="rotulo mb-2">Duração</div>
                <div className="flex gap-2">
                  {Object.keys(DURACOES).map((d) => (
                    <Chip key={d} ativo={duracao === d} onClick={() => setDuracao(d)}>{d}</Chip>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div>
              <div className="rotulo mb-2">Edição</div>
              <div className="flex flex-wrap gap-2">
                <Chip ativo={modoLongo === "enxugar"} onClick={() => setModoLongo("enxugar")}><Scissors className="inline size-3 mr-1" />Enxugar o vídeo inteiro</Chip>
                <Chip ativo={modoLongo === "melhores"} onClick={() => setModoLongo("melhores")}><Trophy className="inline size-3 mr-1" />Melhores momentos</Chip>
              </div>
            </div>
          )}
        </div>

        {tipo === "longo" && modoLongo === "melhores" && (
          <div className="mt-4">
            <div className="rotulo mb-2">Duração da compilação</div>
            <div className="flex flex-wrap gap-2">
              {ALVOS.map((m) => <Chip key={m} ativo={alvo === m} onClick={() => setAlvo(m)}>{m} min</Chip>)}
            </div>
          </div>
        )}

        <div className="mt-5">
          <label className="rotulo">Instrução (opcional)</label>
          <textarea
            value={instrucao}
            onChange={(e) => setInstrucao(e.target.value)}
            rows={2}
            placeholder={!comIa
              ? "Sem IA, só comandos simples. Ex.: sem música, legenda amarela, clipes de 30 a 45 segundos"
              : tipo === "curto" ? "Ex.: só as kills de faca, legenda amarela, sem música" : "Ex.: tira a parte do patrocínio e a conversa do final"}
            className="campo mt-2 resize-none"
          />
        </div>

        {/* Mais opções */}
        <button onClick={() => setMaisOpcoes(!maisOpcoes)} className="mt-4 text-xs text-suave hover:text-texto inline-flex items-center gap-1 cursor-pointer">
          <ChevronDown className={`size-3.5 transition-transform ${maisOpcoes ? "rotate-180" : ""}`} /> Mais opções
        </button>
        {maisOpcoes && (
          <div className="mt-4 grid sm:grid-cols-2 gap-x-6 gap-y-4 animate-surgir">
            {tipo === "curto" && (
              <>
                <div>
                  <label className="rotulo">Legenda</label>
                  <div className="flex items-center gap-2 mt-2">
                    <select value={preset} onChange={(e) => setPreset(e.target.value)} className="campo cursor-pointer">
                      {Object.entries(estilos).map(([id, e]) => <option key={id} value={id}>{e.nome || id}</option>)}
                    </select>
                    <Chip ativo={animada} onClick={() => setAnimada(!animada)}>Animada</Chip>
                  </div>
                </div>
                {comIa && <div>
                  <label className="rotulo">Idioma da legenda</label>
                  <select value={idiomaLegenda} onChange={(e) => setIdiomaLegenda(e.target.value)} className="campo mt-2 cursor-pointer">
                    {Object.entries(IDIOMAS).map(([k, r]) => <option key={k} value={k}>{r}</option>)}
                  </select>
                </div>}
                <div>
                  <label className="rotulo">Formato</label>
                  <select value={formato} onChange={(e) => setFormato(e.target.value)} className="campo mt-2 cursor-pointer">
                    <option value="9:16">Vertical 9:16 (TikTok, Reels, Shorts)</option>
                    <option value="1:1">Quadrado 1:1</option>
                    <option value="16:9">Horizontal 16:9</option>
                  </select>
                </div>
                <div>
                  <label className="rotulo">Enquadramento</label>
                  <select value={layout} onChange={(e) => setLayout(e.target.value)} className="campo mt-2 cursor-pointer">
                    <option value="auto">Automático</option>
                    <option value="rosto">Seguir quem fala</option>
                    <option value="dupla">Duas pessoas (tela dividida)</option>
                    <option value="centro">Recorte central fixo</option>
                    <option value="inteiro">Vídeo inteiro + fundo desfocado</option>
                    <option value="jogo">Gameplay em destaque</option>
                    <option value="split">Gameplay em cima + facecam embaixo</option>
                  </select>
                </div>
              </>
            )}
            {tipo === "longo" && modo === "falado" && (
              <div>
                <label className="rotulo">Ritmo</label>
                <div className="mt-2">
                  <Segmentado tamanho="sm" valor={ritmo} aoMudar={setRitmo} opcoes={[{ valor: "natural", rotulo: "Natural" }, { valor: "dinamico", rotulo: "Dinâmico" }, { valor: "rapido", rotulo: "Rápido" }]} />
                </div>
              </div>
            )}
            <div>
              <label className="rotulo">Música de fundo</label>
              <select value={musica} onChange={(e) => setMusica(e.target.value)} className="campo mt-2 cursor-pointer">
                <option value="">Sem música</option>
                <option value="auto">Automática (pelo clima)</option>
                {Object.entries(CLIMAS).map(([k, r]) => <option key={k} value={k}>{r}</option>)}
              </select>
              {semMusicas && musica && (
                <Link to="/configuracoes#audio" className="text-xs underline mt-1 inline-block">Biblioteca vazia: baixar o pacote grátis</Link>
              )}
            </div>

            {comIa && <Alternador ativo={diretor} aoMudar={setDiretor} rotulo="Diretor de arte (IA)" descricao="Cor, transições, zoom e efeitos escolhidos pelo clima de cada trecho" />}
            <Alternador ativo={efeitos} aoMudar={setEfeitos} rotulo="Efeitos sonoros" descricao="Whoosh, impacto e pop nos momentos certos" />
            <Alternador ativo={zoom} aoMudar={setZoom} rotulo="Zoom" descricao="Nas ênfases e para esconder os cortes secos" />
            <Alternador ativo={abertura} aoMudar={setAbertura} rotulo="Abrir com o melhor momento" descricao="Teaser no começo, para segurar quem chegou" />
            <Alternador ativo={limparVoz ?? modo === "falado"} aoMudar={setLimparVoz} rotulo="Melhorar a voz" descricao="Tira ruído de fundo e zumbido" />
            {comIa && modo === "falado" && (
              <Alternador ativo={broll} aoMudar={setBroll} rotulo="B-roll" descricao="Vídeos de apoio quando a fala cita algo concreto (chave do Pixabay)" />
            )}
            {tipo === "curto" && (
              <>
                <Alternador ativo={titulo} aoMudar={setTitulo} rotulo="Título gancho" descricao="Nos primeiros segundos do clipe" />
                {comIa && <Alternador ativo={reacoes} aoMudar={setReacoes} rotulo="Textos de reação" descricao="“ESPERA...”, “KKKK” no susto e na virada" />}
                <Alternador ativo={silencios} aoMudar={setSilencios} rotulo="Cortar silêncios" descricao="Pausas longas e “hum”, “é”, “tipo”" />
                <Alternador ativo={loop} aoMudar={setLoop} rotulo="Final em loop" descricao="Termina sem fade, emendando no começo quando o vídeo repete" />
                {modo === "gameplay" && (
                  <Alternador ativo={replay} aoMudar={setReplay} rotulo="Replay em câmera lenta" descricao="O lance repete no fim, a meia velocidade, com som grave" />
                )}
              </>
            )}
            {tipo === "longo" && modo === "falado" && (
              <Alternador ativo={removerErros} aoMudar={setRemoverErros} rotulo="Tirar erros de gravação" descricao="Frases repetidas, começos em falso e desvios" />
            )}
            {tipo === "longo" && (
              <Alternador ativo={legendaLonga} aoMudar={setLegendaLonga} rotulo="Legenda na tela" descricao="O .srt para o YouTube sai sempre" />
            )}
            {modo === "gameplay" && (
              <>
                {comIa && <Alternador ativo={verImagens} aoMudar={setVerImagens} rotulo="Claude vê a tela do jogo" descricao="Descarta menus, loading e tempo parado" />}
                {tipo === "longo" && (
                  <Alternador ativo={cortarParado} aoMudar={setCortarParado} rotulo="Cortar tempo parado" descricao="Andanças longas sem nada acontecendo" />
                )}
                {tipo === "curto" && (
                  <div>
                    <label className="rotulo">Vídeo de apoio (sem facecam)</label>
                    <input value={apoio} onChange={(e) => setApoio(e.target.value)} placeholder="C:\videos\satisfatorio.mp4" className="campo mt-2 font-mono text-[13px]" />
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* 3. Com ou sem IA */}
      <div className="cartao p-5 mt-4">
        <div className="rotulo mb-3">3 · Quem escolhe os momentos</div>
        <div className="grid sm:grid-cols-2 gap-3">
          {[
            {
              id: true, icone: BrainCircuit, titulo: "Com IA", selo: "~US$ 0,01 a 0,05",
              texto: "O Claude assiste, escolhe os melhores momentos e escreve títulos, textos do post e a direção de arte.",
            },
            {
              id: false, icone: Cpu, titulo: "Sem IA", selo: "grátis",
              texto: modo === "gameplay"
                ? "Escolhe pelos picos de áudio (tiros, gritos, explosões). Não usa a API: custo zero."
                : "Escolhe pelas frases com mais gancho e impacto. Não usa a API: custo zero.",
            },
          ].map(({ id, icone: Icone, titulo: t, selo, texto }) => (
            <button
              key={String(id)}
              onClick={() => setComIa(id)}
              className={`text-left rounded-2xl border p-4 transition-colors cursor-pointer ${comIa === id ? "border-black bg-black/[0.03]" : "border-black/10 hover:border-black/25"}`}
            >
              <div className="flex items-center gap-3">
                <div className={`size-10 rounded-xl flex items-center justify-center ${comIa === id ? "gradiente" : "bg-card-2 text-texto"}`}>
                  <Icone className="size-5" />
                </div>
                <div className="font-medium text-[17px]">{t}</div>
                <span className="rotulo-mono ml-auto rounded-full border border-black/10 px-2.5 py-1 text-black/55">{selo}</span>
              </div>
              <p className="text-sm text-suave mt-3">{texto}</p>
            </button>
          ))}
        </div>
        {comIa && !temChave && (
          <div className="mt-3">
            <Aviso tipo="alerta">Sem chave do Claude configurada: a edição vai sair no modo sem IA. Configure a chave em <Link to="/configuracoes" className="underline">Configurações</Link>.</Aviso>
          </div>
        )}
        {!comIa && (
          <p className="text-xs text-apagado mt-3">
            Legenda, cortes, zoom, música, efeitos{modo === "gameplay" ? ", replay" : ""} e loop continuam iguais. Ficam de fora só o que depende da IA: direção de arte, textos de reação, B-roll, tradução da legenda e títulos criativos.
          </p>
        )}
      </div>

      {modo === "gameplay" && (!verImagens || !comIa) && tipo === "longo" && modoLongo === "enxugar" && (
        <div className="mt-4">
          <Aviso tipo="alerta">Sem a tela, o tempo morto é cortado só pelo áudio, o que quase não tira nada em jogo com som constante.</Aviso>
        </div>
      )}

      <div className="mt-6 flex flex-col items-center gap-3">
        <Botao variante="primario" tamanho="lg" icone={Sparkles} onClick={enviar} disabled={!pronto} carregando={enviando !== null} className="w-full sm:w-auto sm:min-w-72">
          {enviando !== null
            ? enviando < 1 ? `Enviando ${Math.round(enviando * 100)}%` : "Criando projeto…"
            : (tipo === "curto" ? `Gerar ${numClips} clipe${numClips > 1 ? "s" : ""}` : "Editar o vídeo") + (comIa ? "" : " · grátis")}
        </Botao>
        <span className="rotulo-mono text-black/35">Ctrl + Enter</span>
      </div>
    </div>
  );
}
