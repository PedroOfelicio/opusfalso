import { Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import { EstadoVazio, ProvedorAvisos } from "./components/ui";
import Home from "./pages/Home";
import Projetos from "./pages/Projetos";
import Projeto from "./pages/Projeto";
import Editor from "./pages/Editor";
import Estilos from "./pages/Estilos";
import Configuracoes from "./pages/Configuracoes";
import Longos from "./pages/Longos";
import ProjetoLongo from "./pages/ProjetoLongo";
import { Compass, Sparkles } from "lucide-react";
import { MODO_DEMO } from "./api";

export default function App() {
  return (
    <ProvedorAvisos>
      <div className="flex h-full">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-y-auto">
          {MODO_DEMO && (
            <div className="sticky top-0 z-40 flex items-center justify-center gap-2 px-4 py-2 text-xs sm:text-sm bg-roxo/15 border-b border-roxo/30 backdrop-blur">
              <Sparkles className="size-4 text-roxo shrink-0" />
              <span>
                <strong>Demonstração</strong> com projetos reais já processados pelo Clipador. A edição roda no PC (GPU, FFmpeg e Claude); aqui você navega pelos resultados.
              </span>
            </div>
          )}
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/longos" element={<Longos />} />
            <Route path="/longos/:id" element={<ProjetoLongo />} />
            <Route path="/projetos" element={<Projetos />} />
            <Route path="/projetos/:id" element={<Projeto />} />
            <Route path="/projetos/:id/clips/:cid" element={<Editor />} />
            <Route path="/estilos" element={<Estilos />} />
            <Route path="/configuracoes" element={<Configuracoes />} />
            <Route path="*" element={<EstadoVazio icone={Compass} titulo="Página não encontrada" />} />
          </Routes>
        </main>
      </div>
    </ProvedorAvisos>
  );
}
