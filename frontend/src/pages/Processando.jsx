// Tela de processamento: etapas, % real, tempo estimado e cancelar.
import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Ban, Gamepad2, Mic, RotateCcw, XCircle } from "lucide-react";
import { api, formatarDuracao, formatarRestante } from "../api";
import StepProgress from "../components/StepProgress";
import { Aviso, Botao, Confirmar, EstadoErro, useAvisar } from "../components/ui";

export default function Processando({ projeto, recarregar }) {
  const avisar = useAvisar();
  const [confirmando, setConfirmando] = useState(false);
  const [agindo, setAgindo] = useState(false);
  const pct = Math.round((projeto.progresso || 0) * 100);
  const parado = ["erro", "cancelado"].includes(projeto.status);

  const cancelar = async () => {
    setConfirmando(false);
    try {
      await api.cancelar(projeto.id);
      avisar("Cancelamento solicitado");
      recarregar();
    } catch (e) {
      avisar(e.message, "erro");
    }
  };
  const tentarDeNovo = async () => {
    setAgindo(true);
    try {
      await api.reprocessar(projeto.id);
      recarregar();
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setAgindo(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <Link to="/projetos" className="inline-flex items-center gap-1.5 text-sm text-suave hover:text-texto mb-6">
        <ArrowLeft className="size-4" /> Projetos
      </Link>

      <div className="cartao overflow-hidden shadow-suave animate-surgir">
        <div className="flex gap-5 p-5 border-b border-borda">
          <div className="w-40 aspect-video rounded-xl overflow-hidden bg-card-2 shrink-0 relative">
            <img src={projeto.thumb_url} alt="" className="size-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
            {!parado && <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent bg-[length:200%_100%] animate-brilho" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-xs text-suave">
              {projeto.modo === "gameplay" ? <Gamepad2 className="size-3.5" /> : <Mic className="size-3.5" />}
              {projeto.modo === "gameplay" ? "Gameplay" : "Falado"}
              {projeto.duracao_video ? <> · {formatarDuracao(projeto.duracao_video)}</> : null}
            </div>
            <h1 className="text-xl font-bold truncate mt-1">{projeto.nome}</h1>
            {projeto.instrucao && <p className="text-sm text-suave mt-1 line-clamp-2">“{projeto.instrucao}”</p>}
          </div>
        </div>

        <div className="p-5">
          {projeto.status === "erro" ? (
            <EstadoErro mensagem={projeto.erro} aoTentar={tentarDeNovo} />
          ) : projeto.status === "cancelado" ? (
            <div className="flex items-center gap-4 rounded-xl border border-borda bg-card-2 p-4">
              <XCircle className="size-6 text-suave" />
              <div className="flex-1">
                <div className="font-semibold">Processamento cancelado</div>
                <div className="text-sm text-suave">Você pode recomeçar quando quiser. Transcrição e análise ficam em cache.</div>
              </div>
              <Botao icone={RotateCcw} onClick={tentarDeNovo} carregando={agindo}>Recomeçar</Botao>
            </div>
          ) : (
            <>
              <div className="flex items-end justify-between mb-2">
                <div>
                  <div className="text-3xl font-extrabold tabular-nums">{pct}%</div>
                  <div className="text-sm text-suave">
                    {projeto.status === "fila" ? `Na fila${projeto.fila_pendentes ? ` (${projeto.fila_pendentes} antes)` : ""}…` : formatarRestante(projeto.restante_s)}
                  </div>
                </div>
                <Botao variante="fantasma" icone={Ban} onClick={() => setConfirmando(true)}>Cancelar</Botao>
              </div>
              <div className="h-2 rounded-full bg-card-2 overflow-hidden">
                <div className="h-full gradiente transition-all duration-700 ease-out relative" style={{ width: `${Math.max(pct, 2)}%` }}>
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent bg-[length:200%_100%] animate-brilho" />
                </div>
              </div>
            </>
          )}

          <div className="mt-6">
            <StepProgress etapas={projeto.etapas} atual={projeto.etapa} parado={parado} />
          </div>

          {(projeto.nao_atendido?.length > 0 || projeto.avisos?.length > 0) && (
            <div className="mt-5 space-y-2">
              {projeto.nao_atendido?.length > 0 && (
                <Aviso tipo="alerta" titulo="Partes do pedido que não serão atendidas">
                  {projeto.nao_atendido.join(" · ")}
                </Aviso>
              )}
              {projeto.avisos?.map((a) => (
                <Aviso key={a} tipo="info">{a}</Aviso>
              ))}
            </div>
          )}
        </div>
      </div>

      <Confirmar
        aberto={confirmando}
        titulo="Cancelar processamento?"
        texto="O que já foi transcrito fica guardado em cache, então recomeçar depois é mais rápido."
        rotuloOk="Cancelar processamento"
        perigo
        aoConfirmar={cancelar}
        aoFechar={() => setConfirmando(false)}
      />
    </div>
  );
}
