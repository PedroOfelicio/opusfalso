import { Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import { EstadoVazio, ProvedorAvisos } from "./components/ui";
import Home from "./pages/Home";
import Projetos from "./pages/Projetos";
import Projeto from "./pages/Projeto";
import Editor from "./pages/Editor";
import Estilos from "./pages/Estilos";
import Configuracoes from "./pages/Configuracoes";
import { Compass } from "lucide-react";

export default function App() {
  return (
    <ProvedorAvisos>
      <div className="flex h-full">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Home />} />
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
