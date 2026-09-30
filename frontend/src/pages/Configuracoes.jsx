// Configurações: chave da API, modelo, pasta de saída, GPU/Whisper e custo acumulado.
import { useEffect, useState } from "react";
import { Cpu, DollarSign, Eye, EyeOff, FolderOpen, KeyRound, Save, Trash2 } from "lucide-react";
import { api } from "../api";
import { Alternador, Botao, Confirmar, EstadoErro, Esqueleto, useAvisar } from "../components/ui";

const MODELOS = [
  { id: "claude-sonnet-4-6", rotulo: "Claude Sonnet 4.6 (padrão)" },
  { id: "claude-sonnet-5-5", rotulo: "Claude Sonnet 5.5 (mais novo, mais barato)" },
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

function Secao({ icone: Icone, titulo, descricao, children }) {
  return (
    <section className="cartao p-6 animate-surgir">
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
      const dados = { modelo: cfg.modelo, pasta_saida: cfg.pasta_saida, usar_gpu: cfg.usar_gpu, modelo_whisper: cfg.modelo_whisper, idioma: cfg.idioma };
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
          <label className="rotulo">Modelo</label>
          <select value={MODELOS.some((m) => m.id === cfg.modelo) ? cfg.modelo : "outro"} onChange={(e) => e.target.value !== "outro" && mudar("modelo")(e)} className="campo mt-2 cursor-pointer">
            {MODELOS.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
            {!MODELOS.some((m) => m.id === cfg.modelo) && <option value="outro">{cfg.modelo}</option>}
          </select>
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
