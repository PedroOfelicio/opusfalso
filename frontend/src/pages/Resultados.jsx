// Resultados: grade de clipes, ordenação/filtros, ajustes em linguagem natural e download.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckSquare, Download, FolderOpen, Gamepad2, Mic, RotateCcw, Send, Sparkles, Square } from "lucide-react";
import { api, formatarDuracao } from "../api";
import VideoCard from "../components/VideoCard";
import { Aviso, Botao, Chip, Confirmar, EstadoVazio, useAvisar } from "../components/ui";

const FILTROS = {
  todos: { rotulo: "Todas", teste: () => true },
  curtos: { rotulo: "< 30s", teste: (d) => d < 30 },
  medios: { rotulo: "30–60s", teste: (d) => d >= 30 && d <= 60 },
  longos: { rotulo: "> 60s", teste: (d) => d > 60 },
};
const ORDENS = {
  nota: { rotulo: "Maior nota", fn: (a, b) => b.nota - a.nota },
  ordem: { rotulo: "Ordem no vídeo", fn: (a, b) => a.inicio - b.inicio },
  duracao: { rotulo: "Mais curtos", fn: (a, b) => a.duracao - b.duracao },
};
const SUGESTOES = ["deixa mais curto", "troca a legenda pra verde", "legenda animada", "sem título", "estilo hormozi"];

export default function Resultados({ projeto, recarregar, setProjeto }) {
  const avisar = useAvisar();
  const [selecionados, setSelecionados] = useState([]);
  const [ordem, setOrdem] = useState("nota");
  const [filtro, setFiltro] = useState("todos");
  const [pedido, setPedido] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [confirmar, setConfirmar] = useState(null); // {tipo, clip}

  const clipes = useMemo(
    () => projeto.clips.filter((c) => FILTROS[filtro].teste(c.duracao)).sort(ORDENS[ordem].fn),
    [projeto.clips, filtro, ordem],
  );
  const todosSelecionados = clipes.length > 0 && clipes.every((c) => selecionados.includes(c.id));
  const alternar = (cid) => setSelecionados((s) => (s.includes(cid) ? s.filter((x) => x !== cid) : [...s, cid]));

  const acao = async (fn, msg) => {
    try {
      const p = await fn();
      if (p?.id) setProjeto(p);
      if (msg) avisar(msg);
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  const aplicarAjuste = async () => {
    const alvo = selecionados.length ? selecionados : projeto.clips.map((c) => c.id);
    if (!pedido.trim()) return;
    setEnviando(true);
    await acao(() => api.ajustar(projeto.id, pedido, alvo), `Ajustando ${alvo.length} clipe(s)…`);
    setEnviando(false);
    setPedido("");
  };

  const salvarTitulo = (clip, titulo) =>
    acao(async () => {
      await api.editarClip(projeto.id, clip.id, { titulo });
      return api.renderizar(projeto.id, clip.id); // o título é queimado no vídeo: renderiza de novo
    }, "Título salvo, atualizando o vídeo…");

  const executarConfirmacao = () => {
    const { tipo, clip } = confirmar;
    setConfirmar(null);
    if (tipo === "excluir") {
      setSelecionados((s) => s.filter((x) => x !== clip.id));
      acao(() => api.excluirClip(projeto.id, clip.id), "Clipe excluído");
    } else acao(() => api.regenerar(projeto.id, clip.id), "Procurando outro momento…");
  };

  const prontos = projeto.clips.filter((c) => c.video_url).length;

  return (
    <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8">
      <Link to="/projetos" className="inline-flex items-center gap-1.5 text-sm text-suave hover:text-texto mb-5">
        <ArrowLeft className="size-4" /> Projetos
      </Link>

      {/* Cabeçalho */}
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-suave mb-1">
            {projeto.modo === "gameplay" ? <Gamepad2 className="size-3.5" /> : <Mic className="size-3.5" />}
            {projeto.modo === "gameplay" ? "Gameplay" : "Falado"} · vídeo de {formatarDuracao(projeto.duracao_video)} · {prontos} clipe(s)
            {projeto.custo > 0 && <> · US$ {projeto.custo.toFixed(3)}</>}
          </div>
          <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight truncate">{projeto.nome}</h1>
        </div>
        <div className="flex gap-2">
          <Botao icone={FolderOpen} onClick={() => api.abrirPasta(projeto.id)}>Abrir pasta</Botao>
          <Botao icone={RotateCcw} variante="fantasma" onClick={() => setConfirmar({ tipo: "reprocessar" })}>Refazer</Botao>
          <a href={api.urlZip(projeto.id, selecionados)}>
            <Botao variante="primario" icone={Download} disabled={!prontos}>
              {selecionados.length ? `Baixar ${selecionados.length} (ZIP)` : "Baixar todos (ZIP)"}
            </Botao>
          </a>
        </div>
      </div>

      {projeto.arquivos_sumidos > 0 && (
        <div className="mb-4">
          <Aviso tipo="alerta" titulo={`${projeto.arquivos_sumidos} clipe(s) sem o arquivo de vídeo`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>Os arquivos foram apagados ou movidos da pasta de saída. Dá para refazer a partir do vídeo original, sem custo na API.</span>
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
                Refazer os arquivos
              </Botao>
            </div>
          </Aviso>
        </div>
      )}

      {/* Ajuste em linguagem natural */}
      <div className="cartao p-2 pl-4 flex items-center gap-3 mb-3 focus-within:border-roxo/60 transition-colors">
        <Sparkles className="size-5 text-roxo shrink-0" />
        <input
          value={pedido}
          onChange={(e) => setPedido(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && aplicarAjuste()}
          placeholder={`Peça um ajuste para ${selecionados.length ? `os ${selecionados.length} selecionados` : "todos os clipes"}: “deixa mais curto”, “troca a legenda pra verde”…`}
          className="flex-1 bg-transparent outline-none text-sm py-2 min-w-0"
        />
        <Botao variante="primario" icone={Send} onClick={aplicarAjuste} carregando={enviando} disabled={!pedido.trim()}>
          Aplicar
        </Botao>
      </div>
      <div className="flex flex-wrap gap-2 mb-6">
        {SUGESTOES.map((s) => (
          <Chip key={s} onClick={() => setPedido(s)}>{s}</Chip>
        ))}
      </div>

      {["erro", "cancelado"].includes(projeto.status) && (
        <div className="mb-4">
          <Aviso tipo="erro" titulo={projeto.status === "erro" ? "O processamento parou no meio" : "Processamento cancelado"}>
            {projeto.erro || "Alguns clipes podem estar faltando."}{" "}
            <button className="underline cursor-pointer" onClick={() => setConfirmar({ tipo: "reprocessar" })}>Refazer</button>
          </Aviso>
        </div>
      )}
      {(projeto.nao_atendido?.length > 0 || projeto.avisos?.length > 0) && (
        <div className="space-y-2 mb-6">
          {projeto.nao_atendido?.length > 0 && (
            <Aviso tipo="alerta" titulo="Não atendido (fora das ações suportadas)">{projeto.nao_atendido.join(" · ")}</Aviso>
          )}
          {[...new Set(projeto.avisos)].slice(-3).map((a) => (
            <Aviso key={a}>{a}</Aviso>
          ))}
        </div>
      )}

      {/* Barra de ferramentas */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setSelecionados(todosSelecionados ? [] : clipes.map((c) => c.id))}
            className="inline-flex items-center gap-2 text-sm text-suave hover:text-texto cursor-pointer"
          >
            {todosSelecionados ? <CheckSquare className="size-4 text-roxo" /> : <Square className="size-4" />}
            {selecionados.length ? `${selecionados.length} selecionado(s)` : "Selecionar todos"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {Object.entries(FILTROS).map(([k, f]) => (
            <Chip key={k} ativo={filtro === k} onClick={() => setFiltro(k)}>{f.rotulo}</Chip>
          ))}
          <select value={ordem} onChange={(e) => setOrdem(e.target.value)} className="campo !w-auto !py-1.5 !text-xs cursor-pointer ml-1">
            {Object.entries(ORDENS).map(([k, o]) => (
              <option key={k} value={k}>{o.rotulo}</option>
            ))}
          </select>
        </div>
      </div>

      {clipes.length === 0 ? (
        <EstadoVazio icone={Square} titulo="Nenhum clipe aqui" texto={projeto.clips.length ? "Nenhum clipe nesse filtro de duração." : "Todos os clipes foram excluídos."} />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
          {clipes.map((c) => (
            <VideoCard
              key={c.id}
              clip={c}
              projetoId={projeto.id}
              selecionado={selecionados.includes(c.id)}
              aoSelecionar={() => alternar(c.id)}
              aoSalvarTitulo={(t) => salvarTitulo(c, t)}
              aoRegenerar={() => setConfirmar({ tipo: "regenerar", clip: c })}
              aoExcluir={() => setConfirmar({ tipo: "excluir", clip: c })}
            />
          ))}
        </div>
      )}

      <Confirmar
        aberto={confirmar?.tipo === "excluir" || confirmar?.tipo === "regenerar"}
        titulo={confirmar?.tipo === "excluir" ? "Excluir este clipe?" : "Regenerar este clipe?"}
        texto={
          confirmar?.tipo === "excluir"
            ? "O arquivo do clipe será apagado da pasta de saída."
            : "Ele será substituído por outro momento do vídeo que ainda não virou clipe. As preferências de estilo são mantidas."
        }
        rotuloOk={confirmar?.tipo === "excluir" ? "Excluir" : "Regenerar"}
        perigo={confirmar?.tipo === "excluir"}
        aoConfirmar={executarConfirmacao}
        aoFechar={() => setConfirmar(null)}
      />
      <Confirmar
        aberto={confirmar?.tipo === "reprocessar"}
        titulo="Refazer o projeto do zero?"
        texto="Os clipes atuais serão substituídos e o Claude escolhe os trechos de novo (custa de novo na API). A transcrição vem do cache."
        rotuloOk="Refazer"
        aoConfirmar={() => {
          setConfirmar(null);
          acao(() => api.reprocessar(projeto.id)).then(recarregar);
        }}
        aoFechar={() => setConfirmar(null)}
      />
    </div>
  );
}
