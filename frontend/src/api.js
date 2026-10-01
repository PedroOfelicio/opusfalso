// Cliente da API local (FastAPI). Em dev o Vite faz proxy de /api para a porta 8000.

async function req(caminho, opcoes = {}) {
  const resp = await fetch(caminho, opcoes);
  if (!resp.ok) {
    let msg = `Erro ${resp.status}`;
    try {
      const dados = await resp.json();
      msg = typeof dados.detail === "string" ? dados.detail : JSON.stringify(dados.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(msg);
  }
  return resp.status === 204 ? null : resp.json();
}

const json = (metodo, corpo) => ({
  method: metodo,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(corpo),
});

export const api = {
  sistema: () => req("/api/sistema"),
  config: () => req("/api/config"),
  salvarConfig: (dados) => req("/api/config", json("PUT", dados)),
  custos: () => req("/api/custos"),
  zerarCustos: () => req("/api/custos", { method: "DELETE" }),

  estilos: () => req("/api/estilos"),
  templates: () => req("/api/templates"),
  salvarTemplate: (nome, template) => req(`/api/templates/${nome}`, json("PUT", template)),
  excluirTemplate: (nome) => req(`/api/templates/${nome}`, { method: "DELETE" }),
  salvarEstilo: (nome, estilo) => req(`/api/estilos/${nome}`, json("PUT", estilo)),
  excluirEstilo: (nome) => req(`/api/estilos/${nome}`, { method: "DELETE" }),
  fontes: () => req("/api/fontes"),
  audio: () => req("/api/audio"),
  abrirPastaAudio: () => req("/api/audio/abrir-pasta", { method: "POST" }),
  baixarPacoteMusicas: () => req("/api/audio/pacote", { method: "POST" }),
  excluirAudio: (caminho) => req(`/api/audio/arquivo?caminho=${encodeURIComponent(caminho)}`, { method: "DELETE" }),
  urlAudio: (caminho) => `/api/audio/arquivo?caminho=${encodeURIComponent(caminho)}`,

  projetos: () => req("/api/projetos"),
  projeto: (id) => req(`/api/projetos/${id}`),
  excluirProjeto: (id, apagarSaida = false) => req(`/api/projetos/${id}?apagar_saida=${apagarSaida}`, { method: "DELETE" }),
  cancelar: (id) => req(`/api/projetos/${id}/cancelar`, { method: "POST" }),
  reprocessar: (id, doZero = false) => req(`/api/projetos/${id}/reprocessar${doZero ? "?do_zero=true" : ""}`, { method: "POST" }),
  abrirPasta: (id) => req(`/api/projetos/${id}/abrir-pasta`, { method: "POST" }),
  refazerArquivos: (id) => req(`/api/projetos/${id}/refazer-arquivos`, { method: "POST" }),
  palavras: (id, inicio, fim, cid) => req(`/api/projetos/${id}/palavras?inicio=${inicio}&fim=${fim}&cid=${cid}`),

  editarClip: (id, cid, dados) => req(`/api/projetos/${id}/clips/${cid}`, json("PATCH", dados)),
  renderizar: (id, cid) => req(`/api/projetos/${id}/clips/${cid}/renderizar`, { method: "POST" }),
  regenerar: (id, cid) => req(`/api/projetos/${id}/clips/${cid}/regenerar`, { method: "POST" }),
  excluirClip: (id, cid) => req(`/api/projetos/${id}/clips/${cid}`, { method: "DELETE" }),
  ajustar: (id, pedido, clips) => req(`/api/projetos/${id}/ajustar`, json("POST", { pedido, clips })),
  urlZip: (id, clips = []) => `/api/projetos/${id}/zip?clips=${clips.join(",")}`,

  armazenamento: () => req("/api/armazenamento"),
  limparTemporarios: () => req("/api/armazenamento/limpar", { method: "POST" }),
  juntarRepetidos: () => req("/api/armazenamento/juntar", { method: "POST" }),

  revisarLongo: (id, dados) => req(`/api/projetos/${id}/edicao`, json("PUT", dados)),
  urlPrevia: (id, inicio, fim) => `/api/projetos/${id}/previa?inicio=${inicio.toFixed(2)}&fim=${fim.toFixed(2)}`,
  urlQuadro: (id, t) => `/api/projetos/${id}/quadro?t=${t.toFixed(1)}`,
};

export const criarLongo = (dados, aoProgresso) => criarProjeto(dados, aoProgresso, "/api/longos");

// Climas da biblioteca de música (pastas DADOS/audio/musica/<clima>)
export const CLIMAS = { energetica: "Energética", tensa: "Tensa", calma: "Calma", engracada: "Engraçada", epica: "Épica" };

// Criação com upload: usa XMLHttpRequest para ter o progresso do envio
export function criarProjeto({ arquivo, caminho, instrucao, modo, opcoes }, aoProgresso, rota = "/api/projetos") {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("instrucao", instrucao);
    form.append("modo", modo);
    form.append("opcoes", JSON.stringify(opcoes));
    if (arquivo) form.append("arquivo", arquivo);
    else form.append("caminho", caminho);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", rota);
    xhr.upload.onprogress = (e) => e.lengthComputable && aoProgresso?.(e.loaded / e.total);
    xhr.onload = () => {
      let dados = null;
      try {
        dados = JSON.parse(xhr.responseText);
      } catch {
        /* ignora */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(dados);
      else reject(new Error(dados?.detail || `Erro ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Sem conexão com o servidor local (uvicorn está rodando?)"));
    xhr.send(form);
  });
}

// ---------- formatação
export const formatarDuracao = (s) => {
  if (s == null || isNaN(s)) return "--:--";
  const m = Math.floor(s / 60);
  const seg = Math.floor(s % 60);
  return `${m}:${String(seg).padStart(2, "0")}`;
};

export const formatarTempoPreciso = (s) => {
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toFixed(1).padStart(4, "0")}`;
};

export const formatarRestante = (s) => {
  if (s == null) return "calculando…";
  if (s < 60) return `~${Math.max(1, Math.round(s))}s restantes`;
  const m = Math.floor(s / 60);
  return `~${m}min ${Math.round(s % 60)}s restantes`;
};

export const formatarData = (ts) =>
  new Date(ts * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export const formatarBytes = (b) =>
  b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} KB`;
