// Tela de primeiro uso: aparece enquanto não houver chave do Claude. Explica como criar a chave, testa e salva;
// pede a chave (opcional) do Pixabay para o B-roll e mostra se o PC tem GPU NVIDIA.
import { useEffect, useState } from "react";
import { Check, Cpu, ExternalLink, KeyRound, Sparkles, X } from "lucide-react";
import { api, MODO_DEMO } from "../api";
import { Botao } from "./ui";

export default function PrimeiroUso() {
  const [sistema, setSistema] = useState(null);
  const [aberto, setAberto] = useState(false);
  const [chave, setChave] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [pixabay, setPixabay] = useState("");
  const [testando, setTestando] = useState(false);
  const [resultado, setResultado] = useState(null);

  useEffect(() => {
    if (MODO_DEMO) return;
    api.sistema().then((s) => {
      setSistema(s);
      let pulou = false;
      try {
        pulou = sessionStorage.getItem("primeiro_uso_pulado") === "1";
      } catch {
        /* sem armazenamento: mostra */
      }
      if (!s.tem_chave && !pulou) setAberto(true);
    }).catch(() => {});
  }, []);

  if (!aberto) return null;

  const testar = async () => {
    setTestando(true);
    setResultado(null);
    try {
      await api.salvarConfig({ api_key: chave.trim(), workspace_id: workspace.trim(), ...(pixabay.trim() ? { pixabay_key: pixabay.trim() } : {}) });
      setResultado(await api.testarChave());
    } catch (e) {
      setResultado({ ok: false, mensagem: e.message });
    } finally {
      setTestando(false);
    }
  };
  const pular = () => {
    try {
      sessionStorage.setItem("primeiro_uso_pulado", "1");
    } catch {
      /* ok */
    }
    setAberto(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="cartao w-full max-w-xl p-7 shadow-suave animate-surgir max-h-[92vh] overflow-y-auto">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="size-11 rounded-xl gradiente flex items-center justify-center"><Sparkles className="size-5 text-white" /></div>
            <div>
              <h2 className="text-xl font-semibold">Bem-vindo ao Gadosso Edit</h2>
              <p className="text-sm text-suave">Falta só uma coisa para começar: a sua chave do Claude.</p>
            </div>
          </div>
          <button onClick={pular} className="p-1.5 rounded-lg text-apagado hover:text-texto cursor-pointer" aria-label="Fechar"><X className="size-5" /></button>
        </div>

        <div className="mt-6 space-y-5">
          <div>
            <div className="font-semibold text-sm flex items-center gap-2"><KeyRound className="size-4 text-roxo" /> Chave da API do Claude</div>
            <ol className="text-xs text-suave mt-2 space-y-1 list-decimal list-inside">
              <li>
                Entre em{" "}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="text-roxo hover:underline inline-flex items-center gap-0.5">
                  console.anthropic.com <ExternalLink className="size-3" />
                </a>{" "}
                (crie a conta, se não tiver).
              </li>
              <li>Em <b>Plans &amp; Billing</b>, coloque créditos (US$ 5 rendem centenas de vídeos: ~US$ 0,05 por vídeo).</li>
              <li>Em <b>API Keys</b>, crie uma chave e cole aqui. Ela começa com <code>sk-ant-</code>.</li>
            </ol>
            <input value={chave} onChange={(e) => setChave(e.target.value)} placeholder="sk-ant-..." className="campo font-mono text-[13px] mt-3" autoComplete="off" />
            <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} placeholder="ID do workspace (só se o teste pedir): wrkspc_..." className="campo font-mono text-[13px] mt-2" autoComplete="off" />
          </div>

          <div>
            <div className="font-semibold text-sm">Chave do Pixabay <span className="text-apagado font-normal">(opcional, para o B-roll)</span></div>
            <p className="text-xs text-suave mt-1">
              Grátis: crie a conta no Pixabay e, logado, a chave aparece em{" "}
              <a href="https://pixabay.com/api/docs/" target="_blank" rel="noreferrer" className="text-roxo hover:underline">pixabay.com/api/docs</a>.
            </p>
            <input value={pixabay} onChange={(e) => setPixabay(e.target.value)} placeholder="cole aqui (pode deixar para depois)" className="campo font-mono text-[13px] mt-2" autoComplete="off" />
          </div>

          {sistema && (
            <div className="rounded-xl border border-borda p-3 text-xs text-suave flex gap-2">
              <Cpu className="size-4 text-roxo shrink-0" />
              <span>
                {sistema.cuda
                  ? `Placa de vídeo: ${sistema.gpu}. A transcrição vai ser rápida.`
                  : "Sem placa NVIDIA: funciona, mas a transcrição usa o processador e fica mais lenta (uma live de 2 h pode levar mais de 1 h)."}{" "}
                Na primeira transcrição, o app baixa a IA de reconhecimento de voz (~1,5 GB), uma vez só.
              </span>
            </div>
          )}

          {resultado && (
            <div className={`rounded-xl p-3 text-sm ${resultado.ok ? "bg-verde/10 text-verde" : "bg-vermelho/10 text-vermelho"}`}>
              {resultado.ok ? <Check className="inline size-4 mr-1" /> : null}
              {resultado.mensagem}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Botao variante="fantasma" onClick={pular}>Fazer depois</Botao>
            {resultado?.ok ? (
              <Botao variante="primario" onClick={() => setAberto(false)}>Começar</Botao>
            ) : (
              <Botao variante="primario" onClick={testar} carregando={testando} disabled={!chave.trim().startsWith("sk-ant-")}>
                Testar e salvar
              </Botao>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
