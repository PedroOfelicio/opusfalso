// Configurações: chave da API, modelo, pasta de saída, GPU/Whisper e custo acumulado.
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ChevronDown, Copy, Cpu, DollarSign, Download, Eye, EyeOff, FolderOpen, HardDrive, KeyRound, Music, Pause, Play, Save, Trash2 } from "lucide-react";
import { api, CLIMAS } from "../api";
import { Alternador, Aviso, Botao, Confirmar, EstadoErro, Esqueleto, useAvisar } from "../components/ui";

const MODELOS = [
  { id: "claude-sonnet-5-5", rotulo: "Claude Sonnet 5.5 (padrão: mais novo e mais barato)" },
  { id: "claude-sonnet-4-6", rotulo: "Claude Sonnet 4.6" },
  { id: "claude-opus-5-5", rotulo: "Claude Opus 5.5 (mais capaz)" },
  { id: "claude-haiku-4-5", rotulo: "Claude Haiku 4.5 (mais econômico)" },
];
const WHISPER = [
  { id: "large-v3-turbo", rotulo: "large-v3-turbo (recomendado)" },
  { id: "medium", rotulo: "medium (mais leve)" },
  { id: "small", rotulo: "small (rápido, menos preciso)" },
];
const IDIOMAS = [
  { id: "", rotulo: "Detectar automaticamente" },
  { id: "pt", rotulo: "Português" },
  { id: "en", rotulo: "Inglês" },
  { id: "es", rotulo: "Espanhol" },
];

function Secao({ icone: Icone, titulo, descricao, children, id }) {
  return (
    <section id={id} className="cartao p-6 animate-surgir scroll-mt-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="size-9 rounded-xl bg-card-2 border border-borda flex items-center justify-center shrink-0">
          <Icone className="size-4 text-roxo" />
        </div>
        <div>
          <h2 className="font-semibold">{titulo}</h2>
          {descricao && <p className="text-sm text-suave mt-0.5">{descricao}</p>}
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

export default function Configuracoes() {
  const avisar = useAvisar();
  const [cfg, setCfg] = useState(null);
  const [sistema, setSistema] = useState(null);
  const [custos, setCustos] = useState(null);
  const [erro, setErro] = useState(null);
  const [novaChave, setNovaChave] = useState("");
  const [mostrarChave, setMostrarChave] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [zerando, setZerando] = useState(false);

  const carregar = () => {
    Promise.all([api.config(), api.sistema(), api.custos()])
      .then(([c, s, k]) => {
        setCfg(c);
        setSistema(s);
        setCustos(k);
      })
      .catch((e) => setErro(e.message));
  };
  useEffect(carregar, []);

  const salvar = async () => {
    setSalvando(true);
    try {
      const dados = { modelo: cfg.modelo, modelo_rapido: cfg.modelo_rapido, pasta_saida: cfg.pasta_saida, usar_gpu: cfg.usar_gpu, modelo_whisper: cfg.modelo_whisper, idioma: cfg.idioma, workspace_id: (cfg.workspace_id || "").trim() };
      if (novaChave.trim()) dados.api_key = novaChave.trim();
      setCfg(await api.salvarConfig(dados));
      setNovaChave("");
      avisar("Configurações salvas");
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setSalvando(false);
    }
  };

  if (erro) return <div className="max-w-3xl mx-auto p-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!cfg)
    return (
      <div className="max-w-3xl mx-auto p-8 space-y-4">
        {[0, 1, 2].map((i) => <Esqueleto key={i} className="h-48" />)}
      </div>
    );

  const mudar = (k) => (e) => setCfg({ ...cfg, [k]: e?.target ? e.target.value : e });

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 space-y-5">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight">Configurações</h1>
          <p className="text-sm text-suave mt-1">Tudo fica salvo em {sistema?.dados}\config.json</p>
        </div>
        <Botao variante="primario" icone={Save} onClick={salvar} carregando={salvando}>Salvar</Botao>
      </div>

      <Secao icone={KeyRound} titulo="Claude (API da Anthropic)" descricao="Usado para entender a instrução e escolher os melhores trechos.">
        <div>
          <label className="rotulo">Chave da API</label>
          <div className="flex gap-2 mt-2">
            <div className="relative flex-1">
              <input
                type={mostrarChave ? "text" : "password"}
                value={novaChave}
                onChange={(e) => setNovaChave(e.target.value)}
                placeholder={cfg.api_key || "sk-ant-…"}
                className="campo font-mono text-[13px] !pr-10"
                autoComplete="off"
              />
              <button onClick={() => setMostrarChave(!mostrarChave)} className="absolute right-3 top-1/2 -translate-y-1/2 text-apagado hover:text-texto cursor-pointer">
                {mostrarChave ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
          <p className="text-xs text-apagado mt-2">
            {cfg.api_key_origem === "ambiente"
              ? "Usando a variável de ambiente ANTHROPIC_API_KEY. Digite uma chave acima para salvar localmente."
              : cfg.api_key_origem === "config"
                ? "Chave salva localmente (mascarada). Digite outra para trocar."
                : "Nenhuma chave configurada: o planejador local será usado."}
          </p>
        </div>
        <div>
          <label className="rotulo">ID do workspace (opcional)</label>
          <input value={cfg.workspace_id || ""} onChange={mudar("workspace_id")} placeholder="wrkspc_…" className="campo font-mono text-[13px] mt-2" autoComplete="off" />
          <p className="text-xs text-apagado mt-2">Só preencha se a API reclamar que a chave não está vinculada a um workspace. O ID aparece em console.anthropic.com → Settings → Workspaces.</p>
        </div>
        <div>
          <label className="rotulo">Modelo</label>
          <select value={MODELOS.some((m) => m.id === cfg.modelo) ? cfg.modelo : "outro"} onChange={(e) => e.target.value !== "outro" && mudar("modelo")(e)} className="campo mt-2 cursor-pointer">
            {MODELOS.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
            {!MODELOS.some((m) => m.id === cfg.modelo) && <option value="outro">{cfg.modelo}</option>}
          </select>
          <p className="text-xs text-apagado mt-2">Entende a instrução e escolhe os melhores trechos (1-2 chamadas por vídeo).</p>
        </div>
        <div>
          <label className="rotulo">Modelo da revisão fina</label>
          <select value={cfg.modelo_rapido || ""} onChange={mudar("modelo_rapido")} className="campo mt-2 cursor-pointer">
            <option value="">O mesmo do modelo acima (recomendado)</option>
            {MODELOS.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
          </select>
          <p className="text-xs text-apagado mt-2">Olha ~1 quadro por segundo de cada clipe de gameplay e tira fase de compra, telas de fim de round e tempo morto. Sonnet 5.5: ~US$ 0,005 por clipe. Haiku: metade do preço, mas deixa passar inimigos pequenos.</p>
        </div>
      </Secao>

      <Secao icone={FolderOpen} titulo="Pasta de saída" descricao="Os clipes vão para <pasta>/<nome_do_video>/clip_01.mp4">
        <input value={cfg.pasta_saida} onChange={mudar("pasta_saida")} className="campo font-mono text-[13px]" />
      </Secao>

      <Secao icone={Cpu} titulo="Processamento" descricao={sistema?.gpu ? `GPU detectada: ${sistema.gpu}` : "Nenhuma GPU NVIDIA detectada"}>
        <Alternador ativo={cfg.usar_gpu} aoMudar={mudar("usar_gpu")} rotulo="Usar GPU (CUDA) na transcrição" descricao="Se faltar memória, cai sozinho para um modelo menor e depois para a CPU." />
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="rotulo">Modelo do Whisper</label>
            <select value={cfg.modelo_whisper} onChange={mudar("modelo_whisper")} className="campo mt-2 cursor-pointer">
              {WHISPER.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
            </select>
          </div>
          <div>
            <label className="rotulo">Idioma dos vídeos</label>
            <select value={cfg.idioma} onChange={mudar("idioma")} className="campo mt-2 cursor-pointer">
              {IDIOMAS.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
            </select>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className={`px-2.5 py-1 rounded-full border ${sistema?.cuda ? "border-verde/30 text-verde" : "border-borda text-suave"}`}>CUDA {sistema?.cuda ? "ativo" : "indisponível"}</span>
          <span className={`px-2.5 py-1 rounded-full border ${sistema?.remotion ? "border-verde/30 text-verde" : "border-amarelo/30 text-amarelo"}`}>Remotion {sistema?.remotion ? "instalado" : "não instalado"}</span>
        </div>
      </Secao>

      <BibliotecaAudio />

      <Armazenamento />

      <Secao icone={DollarSign} titulo="Custo acumulado estimado" descricao="Soma de todas as chamadas ao Claude (tokens × preço do modelo).">
        <div className="flex items-end justify-between">
          <div>
            <div className="text-4xl font-extrabold tabular-nums">US$ {custos?.total.toFixed(4)}</div>
            <div className="text-sm text-suave">{custos?.chamadas} chamada(s)</div>
          </div>
          <Botao variante="fantasma" icone={Trash2} onClick={() => setZerando(true)}>Zerar</Botao>
        </div>
        {custos?.historico.length > 0 && (
          <div className="rounded-xl border border-borda overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-card-2 text-suave">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Quando</th>
                  <th className="text-left px-3 py-2 font-medium">Motivo</th>
                  <th className="text-right px-3 py-2 font-medium">Tokens</th>
                  <th className="text-right px-3 py-2 font-medium">Custo</th>
                </tr>
              </thead>
              <tbody>
                {custos.historico.slice(0, 12).map((h, i) => (
                  <tr key={i} className="border-t border-borda">
                    <td className="px-3 py-2 text-suave tabular-nums">{h.quando.slice(5, 16)}</td>
                    <td className="px-3 py-2">{h.motivo}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-suave">{h.entrada + h.saida}</td>
                    <td className="px-3 py-2 text-right tabular-nums">${h.custo.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Secao>

      <Confirmar
        aberto={zerando}
        titulo="Zerar o custo acumulado?"
        texto="Apaga só o histórico local de estimativas. Não afeta sua conta na Anthropic."
        rotuloOk="Zerar"
        perigo
        aoConfirmar={async () => {
          setZerando(false);
          await api.zerarCustos();
          carregar();
        }}
        aoFechar={() => setZerando(false)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ armazenamento

const gb = (b) => `${(b / 1024 ** 3).toFixed(1).replace(".", ",")} GB`;

function Armazenamento() {
  const avisar = useAvisar();
  const [dados, setDados] = useState(null);
  const [agindo, setAgindo] = useState(null);
  const [confirmando, setConfirmando] = useState(false);

  const carregar = () => api.armazenamento().then(setDados).catch(() => setDados(false));
  useEffect(() => {
    carregar();
  }, []);

  const executar = async (acao, rotulo) => {
    setAgindo(rotulo);
    try {
      const r = await acao();
      setDados(r);
      avisar(`${gb(r.liberado)} liberados`);
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setAgindo(null);
    }
  };

  return (
    <Secao icone={HardDrive} titulo="Armazenamento" descricao={dados ? `Dados do app em ${dados.pasta}` : "Espaço em disco usado pelo app"}>
      {dados === null ? (
        <Esqueleto className="h-24" />
      ) : dados === false ? (
        <p className="text-sm text-suave">Não consegui ler o disco.</p>
      ) : (
        <>
          <div>
            <div className="flex justify-between text-sm mb-2">
              <span className={dados.livre < 5 * 1024 ** 3 ? "text-vermelho font-semibold" : "text-suave"}>{gb(dados.livre)} livres</span>
              <span className="text-apagado">de {gb(dados.total)}</span>
            </div>
            <div className="h-2 rounded-full bg-card-2 overflow-hidden">
              <div className={`h-full ${dados.livre < 5 * 1024 ** 3 ? "bg-vermelho" : "gradiente"}`} style={{ width: `${Math.min(100, (1 - dados.livre / dados.total) * 100)}%` }} />
            </div>
          </div>
          {dados.livre < 5 * 1024 ** 3 && (
            <Aviso tipo="alerta">Disco quase cheio. Um vídeo longo em 1080p precisa de alguns GB livres para renderizar; abaixo de 2 GB o app não começa projetos novos.</Aviso>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            {[
              ["Vídeos enviados", dados.videos],
              ["Temporários", dados.temporarios],
              ["Clipes e vídeos prontos", dados.saidas],
              ["Modelos de IA", dados.modelos],
            ].map(([rotulo, v]) => (
              <div key={rotulo} className="rounded-xl border border-borda p-3">
                <div className="font-bold tabular-nums">{gb(v)}</div>
                <div className="text-xs text-suave mt-0.5">{rotulo}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="flex-1 rounded-xl border border-borda p-4">
              <div className="font-semibold text-sm flex items-center gap-2"><Copy className="size-4 text-roxo" /> Vídeos repetidos</div>
              <p className="text-xs text-suave mt-1">O mesmo vídeo enviado mais de uma vez fica guardado uma vez só. Os projetos continuam funcionando.</p>
              <Botao className="mt-3" tamanho="sm" onClick={() => executar(api.juntarRepetidos, "juntar")} carregando={agindo === "juntar"} disabled={!dados.repetidos}>
                {dados.repetidos ? `Juntar (libera ${gb(dados.repetidos)})` : "Nada repetido"}
              </Botao>
            </div>
            <div className="flex-1 rounded-xl border border-borda p-4">
              <div className="font-semibold text-sm flex items-center gap-2"><Trash2 className="size-4 text-roxo" /> Temporários</div>
              <p className="text-xs text-suave mt-1">Cortes intermediários, blocos em cache e prévias. São refeitos sozinhos quando precisar; só o próximo render fica mais lento.</p>
              <Botao className="mt-3" tamanho="sm" onClick={() => setConfirmando(true)} carregando={agindo === "limpar"} disabled={!dados.temporarios}>
                {dados.temporarios ? `Limpar (libera ${gb(dados.temporarios)})` : "Nada para limpar"}
              </Botao>
            </div>
          </div>
          <Confirmar
            aberto={confirmando}
            titulo="Limpar os temporários?"
            texto="Os vídeos prontos, os projetos e os vídeos enviados ficam. Reexportar um clipe ou remontar um vídeo longo depois disso leva o tempo de um render completo."
            rotuloOk="Limpar"
            aoConfirmar={() => {
              setConfirmando(false);
              executar(api.limparTemporarios, "limpar");
            }}
            aoFechar={() => setConfirmando(false)}
          />
        </>
      )}
    </Secao>
  );
}

// ------------------------------------------------------------------ biblioteca de áudio

function BibliotecaAudio() {
  const avisar = useAvisar();
  const local = useLocation();
  const secao = useRef(null);
  const player = useRef(null);
  const [audio, setAudio] = useState(null);
  const [aberto, setAberto] = useState(null); // clima com a lista de faixas aberta
  const [tocando, setTocando] = useState(null);
  const [apagando, setApagando] = useState(null);

  const tocar = (caminho) => {
    const p = player.current;
    if (!p) return;
    if (tocando === caminho) {
      p.pause();
      setTocando(null);
      return;
    }
    p.src = api.urlAudio(caminho);
    p.play().then(() => setTocando(caminho)).catch(() => avisar("Não consegui tocar a faixa", "erro"));
  };
  const apagar = async () => {
    const caminho = apagando;
    setApagando(null);
    if (tocando === caminho) {
      player.current?.pause();
      setTocando(null);
    }
    try {
      setAudio(await api.excluirAudio(caminho));
      avisar("Faixa apagada");
    } catch (e) {
      avisar(e.message, "erro");
    }
  };
  const nomeFaixa = (caminho) => {
    const d = audio?.detalhes?.[caminho];
    return d ? `${d.titulo} · ${d.artista}` : caminho.split(/[\\/]/).pop();
  };

  const carregar = () => api.audio().then(setAudio).catch(() => setAudio(false));
  useEffect(() => {
    carregar();
  }, []);
  // Veio do link "baixar o pacote grátis" da tela inicial (rola uma vez, quando a seção carrega)
  useEffect(() => {
    if (audio && local.hash === "#audio" && !secao.current?.dataset.rolou) {
      secao.current.dataset.rolou = "1";
      document.getElementById("audio")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [audio, local.hash]);
  // Enquanto baixa, acompanha o progresso
  const baixando = !!audio?.pacote?.baixando;
  useEffect(() => {
    if (!baixando) return;
    const t = setInterval(() => {
      api.audio().then((a) => {
        setAudio(a);
        if (!a.pacote.baixando) {
          const erros = a.pacote.erros.length;
          avisar(erros ? `${erros} faixa(s) não baixaram: ${a.pacote.erros[0]}` : "Músicas baixadas", erros ? "erro" : undefined);
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [baixando]); // eslint-disable-line react-hooks/exhaustive-deps

  const baixar = async () => {
    try {
      setAudio(await api.baixarPacoteMusicas());
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  const total = audio ? Object.values(audio.musicas).reduce((s, l) => s + l.length, 0) : 0;
  return (
    <Secao id="audio" icone={Music} titulo="Biblioteca de áudio" descricao="Músicas de fundo por clima e efeitos sonoros usados nos clipes e vídeos longos.">
      {audio === null ? (
        <Esqueleto className="h-24" />
      ) : audio === false ? (
        <p className="text-sm text-suave">Não consegui ler a biblioteca.</p>
      ) : (
        <div ref={secao} className="space-y-4">
          <audio ref={player} onEnded={() => setTocando(null)} className="hidden" />
          <div className="flex flex-wrap gap-2">
            {Object.entries(CLIMAS).map(([k, rotulo]) => (
              <button
                key={k}
                onClick={() => setAberto(aberto === k ? null : k)}
                disabled={!audio.musicas[k]?.length}
                className={`text-xs px-2.5 py-1 rounded-full border inline-flex items-center gap-1 cursor-pointer disabled:cursor-default ${
                  aberto === k ? "border-roxo text-texto bg-roxo/10" : audio.musicas[k]?.length ? "border-borda text-texto hover:border-borda-forte" : "border-amarelo/30 text-amarelo"
                }`}
              >
                {rotulo}: {audio.musicas[k]?.length || 0}
                {audio.musicas[k]?.length > 0 && <ChevronDown className={`size-3 transition-transform ${aberto === k ? "rotate-180" : ""}`} />}
              </button>
            ))}
          </div>
          {aberto && audio.musicas[aberto]?.length > 0 && (
            <div className="rounded-xl border border-borda divide-y divide-borda">
              {audio.musicas[aberto].map((c) => (
                <div key={c} className="flex items-center gap-3 px-3 py-2">
                  <button onClick={() => tocar(c)} className="size-8 rounded-lg bg-card-2 hover:bg-white/10 flex items-center justify-center shrink-0 cursor-pointer" aria-label={tocando === c ? "Pausar" : "Ouvir"}>
                    {tocando === c ? <Pause className="size-4 text-roxo" /> : <Play className="size-4" />}
                  </button>
                  <span className="text-sm flex-1 min-w-0 truncate" title={c}>{nomeFaixa(c)}</span>
                  <button onClick={() => setApagando(c)} className="p-1.5 rounded-lg text-suave hover:text-vermelho hover:bg-vermelho/10 cursor-pointer" aria-label="Apagar faixa">
                    <Trash2 className="size-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <Confirmar
            aberto={!!apagando}
            titulo="Apagar esta faixa?"
            texto={apagando ? `${nomeFaixa(apagando)} sai da biblioteca e não volta a ser sorteada. Clipes já prontos não mudam.` : ""}
            rotuloOk="Apagar"
            perigo
            aoConfirmar={apagar}
            aoFechar={() => setApagando(null)}
          />
          {audio.pacote.faltando > 0 || baixando ? (
            <div className="rounded-xl border border-borda p-4">
              <div className="font-semibold text-sm">Pacote grátis de músicas</div>
              <p className="text-xs text-suave mt-1">
                {audio.pacote.total_pacote} faixas instrumentais de domínio público (CC0) de HoliznaCC0, Komiku e Loyalty Freak Music, do Free Music Archive: 3 ou 4 por clima, livres para usar em qualquer vídeo, inclusive monetizado, sem dar crédito.
                {total === 0 && " Sem músicas na biblioteca, pedir música não faz nada."}
              </p>
              <Botao className="mt-3" tamanho="sm" icone={Download} onClick={baixar} carregando={baixando} disabled={baixando}>
                {baixando
                  ? `Baixando ${Math.min(audio.pacote.feitos + 1, audio.pacote.total)} de ${audio.pacote.total}…`
                  : `Baixar ${audio.pacote.faltando} música(s) (${Math.round(audio.pacote.bytes / 1e6)} MB)`}
              </Botao>
            </div>
          ) : (
            <p className="text-xs text-suave">Pacote grátis instalado. Os créditos estão em musica\CREDITOS.txt.</p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Botao tamanho="sm" variante="fantasma" icone={FolderOpen} onClick={() => api.abrirPastaAudio()}>Abrir a pasta</Botao>
            <span className="text-xs text-apagado">Para usar as suas, solte arquivos em musica\&lt;clima&gt; ou efeitos\&lt;tipo&gt;. O volume de cada faixa é igualado sozinho.</span>
          </div>
        </div>
      )}
    </Secao>
  );
}
