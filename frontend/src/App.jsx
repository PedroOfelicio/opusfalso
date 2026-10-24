import { Navigate, Route, Routes } from "react-router-dom";
import Cabecalho from "./components/Cabecalho";
import Fundo from "./components/Fundo";
import { EstadoVazio, ProvedorAvisos } from "./components/ui";
import Home from "./pages/Home";
import Projetos from "./pages/Projetos";
import Projeto from "./pages/Projeto";
import Editor from "./pages/Editor";
import Configuracoes from "./pages/Configuracoes";
import ProjetoLongo from "./pages/ProjetoLongo";
import PrimeiroUso from "./components/PrimeiroUso";
import { Compass, Sparkles } from "lucide-react";
import { MODO_DEMO } from "./api";

export default function App() {
  return (
    <ProvedorAvisos>
      <Fundo />
      <div className="relative z-10 flex h-full flex-col">
        <PrimeiroUso />
        {MODO_DEMO && (
          <div className="flex items-center justify-center gap-2 px-4 py-2 text-xs sm:text-sm bg-black text-white">
            <Sparkles className="size-4 shrink-0" />
            <span>
              <strong>Demonstração</strong> com projetos reais já processados pelo Gadosso Edit. A edição roda no PC (GPU, FFmpeg e Claude); aqui você navega pelos resultados.
            </span>
          </div>
        )}
        <Cabecalho />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/longos" element={<Navigate to="/projetos" replace />} />
            <Route path="/longos/:id" element={<ProjetoLongo />} />
            <Route path="/projetos" element={<Projetos />} />
            <Route path="/projetos/:id" element={<Projeto />} />
            <Route path="/projetos/:id/clips/:cid" element={<Editor />} />
            <Route path="/configuracoes" element={<Configuracoes />} />
            <Route path="*" element={<EstadoVazio icone={Compass} titulo="Página não encontrada" />} />
          </Routes>
        </main>
      </div>
    </ProvedorAvisos>
  );
}
