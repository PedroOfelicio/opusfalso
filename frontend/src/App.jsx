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
import Postar from "./pages/Postar";
import PrimeiroUso from "./components/PrimeiroUso";
import { Compass } from "lucide-react";

export default function App() {
  return (
    <ProvedorAvisos>
      <Fundo />
      <div className="relative z-10 flex h-full flex-col">
        <PrimeiroUso />
        <Cabecalho />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/longos" element={<Navigate to="/projetos" replace />} />
            <Route path="/longos/:id" element={<ProjetoLongo />} />
            <Route path="/projetos" element={<Projetos />} />
            <Route path="/projetos/:id" element={<Projeto />} />
            <Route path="/projetos/:id/clips/:cid" element={<Editor />} />
            <Route path="/postar" element={<Postar />} />
            <Route path="/configuracoes" element={<Configuracoes />} />
            <Route path="*" element={<EstadoVazio icone={Compass} titulo="Página não encontrada" />} />
          </Routes>
        </main>
      </div>
    </ProvedorAvisos>
  );
}
