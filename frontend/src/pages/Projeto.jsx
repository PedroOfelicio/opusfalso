// Página de um projeto: mostra "Processando" enquanto roda e "Resultados" quando pronto.
import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { api } from "../api";
import { EstadoErro, Esqueleto, usePolling } from "../components/ui";
import Processando from "./Processando";
import Resultados from "./Resultados";

export default function Projeto() {
  const { id } = useParams();
  const [projeto, setProjeto] = useState(null);
  const [erro, setErro] = useState(null);

  const carregar = useCallback(() => {
    api
      .projeto(id)
      .then((p) => {
        setProjeto(p);
        setErro(null);
      })
      .catch((e) => setErro(e.message));
  }, [id]);

  useEffect(carregar, [carregar]);

  // Atualiza rápido enquanto algo está rodando; devagar quando está tudo parado
  const rodando =
    projeto && (["fila", "processando"].includes(projeto.status) || projeto.clips.some((c) => ["fila", "renderizando"].includes(c.status)));
  usePolling(carregar, rodando ? 1000 : 8000, !!projeto);

  if (erro && !projeto)
    return (
      <div className="max-w-3xl mx-auto p-8">
        <EstadoErro mensagem={erro} aoTentar={carregar} />
      </div>
    );
  if (!projeto)
    return (
      <div className="max-w-6xl mx-auto p-8 space-y-6">
        <Esqueleto className="h-10 w-72" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
          {[0, 1, 2, 3].map((i) => (
            <Esqueleto key={i} className="aspect-[9/16]" />
          ))}
        </div>
      </div>
    );

  if (projeto.tipo === "longo") return <Navigate to={`/longos/${id}`} replace />;
  const temClipes = projeto.clips.some((c) => c.video_url);
  if (projeto.status === "pronto" || (temClipes && !["fila", "processando"].includes(projeto.status)))
    return <Resultados projeto={projeto} recarregar={carregar} setProjeto={setProjeto} />;
  return <Processando projeto={projeto} recarregar={carregar} />;
}
