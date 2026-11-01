// Métricas do canal: números públicos da YouTube Data API (inscritos, views, likes, comentários). A API só dá o
// total de agora; o servidor guarda um retrato por dia e a evolução sai da diferença entre retratos.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Check, ExternalLink, KeyRound, RefreshCw } from "lucide-react";
import { api, formatarDuracao } from "../api";
import { Aviso, Botao, Chip, EstadoErro, Esqueleto, Segmentado, useAvisar } from "../components/ui";

// Cor única dos gráficos (uma série por gráfico): slot 1 da paleta validada, 4,5:1 sobre o branco do cartão
const COR = "#2a78d6";
const GRADE = "#e1e0d9";
const BASE = "#c3c2b7";
const MUDO = "#898781";

const PERIODOS = [{ valor: 7, rotulo: "7 dias" }, { valor: 30, rotulo: "30 dias" }, { valor: 90, rotulo: "90 dias" }, { valor: 0, rotulo: "Tudo" }];
const compacto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const inteiro = new Intl.NumberFormat("pt-BR");
const fmt = (n) => (n == null ? "—" : Math.abs(n) >= 10000 ? compacto.format(n) : inteiro.format(n));
const diaCurto = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const hojeIso = () => new Date().toLocaleDateString("sv-SE");
const menosDias = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toLocaleDateString("sv-SE");
};

export default function Metricas() {
  const avisar = useAvisar();
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [atualizando, setAtualizando] = useState(false);
  const [periodo, setPeriodo] = useState(30);
  const [tipo, setTipo] = useState("todos");

  const carregar = useCallback(() => {
    api.metricas().then((d) => {
      setDados(d);
      setErro(null);
    }).catch((e) => setErro(e.message));
  }, []);
  useEffect(carregar, [carregar]);

  const atualizar = async () => {
    setAtualizando(true);
    try {
      setDados(await api.atualizarMetricas());
      avisar("Métricas atualizadas");
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setAtualizando(false);
    }
  };

  const calc = useMemo(() => (dados ? calcular(dados, periodo, tipo) : null), [dados, periodo, tipo]);

  if (erro && !dados) return <div className="max-w-[1400px] mx-auto px-6 py-8"><EstadoErro mensagem={erro} aoTentar={carregar} /></div>;
  if (!dados) {
    return (
      <div className="max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-4">
        <Esqueleto className="h-10 w-64" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0, 1, 2, 3].map((k) => <Esqueleto key={k} className="h-28" />)}</div>
        <Esqueleto className="h-64" />
      </div>
    );
  }
  if (!dados.canal || (!dados.conectado && (!dados.tem_chave || !dados.canal_id))) return <Configurar dados={dados} aoSalvar={setDados} />;

  const { canal } = dados;
  const an = !!dados.analytics;
  return (
    <div className={`max-w-[1400px] mx-auto px-6 lg:px-8 py-8 space-y-6 transition-opacity ${atualizando ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          {canal.thumb && <img src={canal.thumb} alt="" className="size-11 rounded-full" />}
          <div className="min-w-0">
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight truncate">{canal.nome}</h1>
            <p className="text-sm text-suave mt-0.5">
              {fmt(canal.videos)} vídeos · atualizado {dados.atualizado_em ? new Date(dados.atualizado_em * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {dados.conectado ? (
            <span className="rotulo-mono inline-flex items-center gap-2 text-black/55" title="Login com o Google: números do YouTube Analytics">
              <span className="size-2 rounded-full bg-verde" />Google conectado
              <button
                className="underline cursor-pointer normal-case"
                onClick={async () => {
                  setDados(await api.sairGoogle());
                  avisar("Login do Google removido deste PC");
                }}
              >
                sair
              </button>
            </span>
          ) : dados.tem_cliente ? (
            <Botao tamanho="sm" onClick={() => api.entrarGoogle().then(() => avisar("Termine o login no navegador e depois clique em Atualizar")).catch((e) => avisar(e.message, "erro"))}>
              Entrar com o Google (retenção e mais)
            </Botao>
          ) : null}
          <a href={`https://studio.youtube.com/channel/${canal.id}/analytics`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-full bg-white border border-black/10 hover:border-black/25">
            <ExternalLink className="size-4" />Analytics no Studio
          </a>
          <Botao icone={RefreshCw} onClick={atualizar} carregando={atualizando}>Atualizar</Botao>
        </div>
      </div>

      {dados.erro && <Aviso tipo="alerta">Última atualização falhou: {dados.erro}</Aviso>}
      {dados.conectado && dados.aviso_analytics && <Aviso tipo="alerta">Analytics indisponível: {dados.aviso_analytics}</Aviso>}
      {dados.pendentes_no_ar > 0 && (
        <Aviso titulo={`${dados.pendentes_no_ar} corte(s) da aba Prontos já estão no canal`}>
          <span>Eles ainda aparecem como “Para postar”. </span>
          <button
            className="underline font-medium cursor-pointer"
            onClick={async () => {
              const r = await api.marcarPublicados();
              setDados(r);
              avisar(`${r.marcados} marcado(s) como postado`);
            }}
          >
            Marcar como postados
          </button>
        </Aviso>
      )}

      {/* Filtros: valem para tudo abaixo */}
      <div className="flex flex-wrap items-center gap-3">
        <Segmentado tamanho="sm" valor={periodo} aoMudar={setPeriodo} opcoes={PERIODOS} />
        <div className="flex gap-2">
          {[["todos", "Tudo"], ["short", "Shorts"], ["longo", "Longos"]].map(([v, r]) => <Chip key={v} ativo={tipo === v} onClick={() => setTipo(v)}>{r}</Chip>)}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Bloco rotulo="Inscritos" valor={canal.inscritos_ocultos ? "ocultos" : fmt(canal.inscritos)} delta={calc.inscritosDelta} periodo={calc.rotuloPeriodo} />
        <Bloco rotulo={`Views ${calc.rotuloPeriodo}`} valor={calc.viewsPeriodo == null ? "—" : fmt(calc.viewsPeriodo)} nota={calc.viewsPeriodo == null ? "aparece a partir do 2º dia de retratos" : `${fmt(canal.views)} no total do canal`} />
        {an ? (
          <>
            <Bloco rotulo={`Horas assistidas ${calc.rotuloPeriodo}`} valor={fmt(Math.round(calc.horas))} nota={`${calc.publicados.length} vídeo(s) publicados no período`} />
            <Bloco rotulo="Retenção média" valor={calc.retencao == null ? "—" : `${calc.retencao.toFixed(0)}%`} nota={`do vídeo assistido, média ponderada por views${tipo !== "todos" ? ` (${tipo === "short" ? "shorts" : "longos"})` : ""}`} />
          </>
        ) : (
          <>
            <Bloco rotulo={`Publicados ${calc.rotuloPeriodo}`} valor={fmt(calc.publicados.length)} nota={`${calc.publicados.filter((v) => v.tipo === "short").length} shorts · ${calc.publicados.filter((v) => v.tipo === "longo").length} longos`} />
            <Bloco rotulo="Views por vídeo publicado" valor={calc.publicados.length ? fmt(Math.round(calc.mediana)) : "—"} nota="mediana dos publicados no período" />
          </>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Cartao titulo={`Views do canal por dia${tipo !== "todos" ? " (todos os vídeos)" : ""}`} sub={an ? "YouTube Analytics: os últimos 2-3 dias ainda sobem" : "Diferença entre retratos diários do total de views"}>
          {calc.porDia.length ? <Colunas dados={calc.porDia} /> : <Vazio texto="O gráfico começa a encher amanhã: o app guarda um retrato do canal por dia (a cada 3 h com o app aberto)." />}
        </Cartao>
        <Cartao titulo="Inscritos" sub={canal.inscritos_ocultos ? "O canal esconde o número de inscritos" : "Último valor de cada dia"}>
          {calc.inscritos.length > 1 && !canal.inscritos_ocultos ? <Linha dados={calc.inscritos} /> : <Vazio texto="A linha aparece com dois ou mais dias de retratos." />}
        </Cartao>
      </div>

      <Cartao titulo={`Mais vistos ${calc.rotuloPeriodo}`} sub={periodo ? "Views ganhas no período (ou desde a publicação, se for mais recente)" : "Views totais"}>
        {calc.top.length ? <Barras dados={calc.top} /> : <Vazio texto="Nenhum vídeo com views nesse filtro." />}
      </Cartao>

      <Tabela videos={calc.videos} periodo={periodo} rotuloPeriodo={calc.rotuloPeriodo} an={an} />
    </div>
  );
}

// ------------------------------------------------------------------ cálculo (tudo respeita os filtros)

function calcular(dados, periodo, tipo) {
  const inicio = periodo ? menosDias(periodo) : "0000-00-00";
  const rotuloPeriodo = periodo ? `em ${periodo} dias` : "desde o início";
  const serie = dados.serie;
  // retrato de base: o último até o início do período (ou o primeiro que existir)
  const base = [...serie].reverse().find((s) => s.dia <= inicio) || serie[0];
  const ultimo = serie[serie.length - 1];
  const temDelta = base && ultimo && base.dia !== ultimo.dia;

  const an = dados.analytics;
  let porDia = [];
  let inscritos;
  let inscritosDelta = temDelta ? ultimo.inscritos - base.inscritos : null;
  let viewsPeriodo = temDelta ? ultimo.views - base.views : null;
  let horas = 0;
  if (an) {
    // Analytics: números reais de cada dia. Inscritos: o total de hoje menos o saldo dos dias seguintes
    const dias = an.dias.filter((d) => d.day > inicio);
    porDia = dias.map((d) => ({ dia: d.day, desde: d.day, valor: d.views }));
    viewsPeriodo = dias.reduce((s, d) => s + d.views, 0);
    horas = dias.reduce((s, d) => s + d.estimatedMinutesWatched, 0) / 60;
    inscritosDelta = dias.reduce((s, d) => s + d.subscribersGained - d.subscribersLost, 0);
    let total = dados.canal.inscritos;
    inscritos = [];
    for (let k = an.dias.length - 1; k >= 0 && an.dias[k].day > inicio; k--) {
      inscritos.unshift({ dia: an.dias[k].day, valor: total });
      total -= an.dias[k].subscribersGained - an.dias[k].subscribersLost;
    }
  } else {
    for (let k = 1; k < serie.length; k++) {
      if (serie[k].dia <= inicio) continue;
      porDia.push({ dia: serie[k].dia, desde: serie[k - 1].dia, valor: Math.max(0, serie[k].views - serie[k - 1].views) });
    }
    inscritos = serie.filter((s) => s.dia >= inicio || s === base).map((s) => ({ dia: s.dia, valor: s.inscritos }));
  }

  const porVideo = an ? an.videos[String(periodo)] || {} : null;
  const inicioTs = periodo ? Date.now() / 1000 - periodo * 86400 : 0;
  const videos = dados.videos.filter((v) => tipo === "todos" || v.tipo === tipo).map((v) => {
    let ganho = v.views;
    const a = porVideo ? porVideo[v.id] : null;
    const extra = a ? { retencao: a.averageViewPercentage, duracaoMedia: a.averageViewDuration, novosInscritos: a.subscribersGained } : {};
    if (porVideo) {
      ganho = a ? a.views : null; // fora do top 200 do período: poucas views, sem detalhe
    } else if (periodo && v.publicado < inicioTs) {
      const dias = Object.keys(v.historico).sort();
      const antes = [...dias].reverse().find((d) => d <= inicio) ?? dias[0];
      ganho = antes != null && antes !== dias[dias.length - 1] ? v.views - v.historico[antes] : null;
    }
    const idadeDias = Math.max(1, (Date.now() / 1000 - v.publicado) / 86400);
    return { ...v, ...extra, ganho, porDia: v.views / idadeDias, curtidas: v.views ? v.likes / v.views : 0 };
  });
  const comRetencao = videos.filter((v) => v.retencao != null && v.ganho > 0);
  const pesos = comRetencao.reduce((s, v) => s + v.ganho, 0);
  const retencao = pesos ? comRetencao.reduce((s, v) => s + v.retencao * v.ganho, 0) / pesos : null;
  const publicados = videos.filter((v) => v.publicado >= inicioTs);
  const views = publicados.map((v) => v.views).sort((a, b) => a - b);
  const mediana = views.length ? (views.length % 2 ? views[(views.length - 1) / 2] : (views[views.length / 2 - 1] + views[views.length / 2]) / 2) : 0;
  const top = videos.filter((v) => (v.ganho ?? 0) > 0).sort((a, b) => b.ganho - a.ganho).slice(0, 10)
    .map((v) => ({ id: v.id, rotulo: v.titulo, valor: v.ganho, url: v.url, app: !!v.app }));

  return { rotuloPeriodo, porDia, inscritos, videos, publicados, mediana, top, inscritosDelta, viewsPeriodo, horas, retencao };
}

// ------------------------------------------------------------------ peças

function Cartao({ titulo, sub, children }) {
  return (
    <section className="cartao p-5">
      <h2 className="font-semibold">{titulo}</h2>
      {sub && <p className="text-xs text-suave mt-0.5">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Vazio({ texto }) {
  return <div className="h-48 flex items-center justify-center text-center text-sm text-suave px-6 rounded-xl bg-card-2">{texto}</div>;
}

function Bloco({ rotulo, valor, delta, periodo, nota }) {
  return (
    <div className="cartao p-4">
      <div className="text-xs text-suave">{rotulo}</div>
      <div className="text-3xl font-semibold mt-1">{valor}</div>
      {delta != null ? (
        <div className={`text-xs mt-1 inline-flex items-center gap-1 ${delta > 0 ? "text-verde" : delta < 0 ? "text-vermelho" : "text-suave"}`}>
          {delta > 0 ? <ArrowUp className="size-3" /> : delta < 0 ? <ArrowDown className="size-3" /> : null}
          {delta > 0 ? "+" : ""}{fmt(delta)} <span className="text-suave">{periodo}</span>
        </div>
      ) : nota ? <div className="text-xs text-apagado mt-1">{nota}</div> : <div className="text-xs text-apagado mt-1">variação a partir do 2º dia</div>}
    </div>
  );
}

function useLargura() {
  const ref = useRef(null);
  const [largura, setLargura] = useState(600);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setLargura(Math.max(240, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, largura];
}

function escala(max) {
  // eixo y com 3-5 marcas redondas (1, 2 ou 5 × 10^n)
  if (max <= 0) return { topo: 1, marcas: [0, 1] };
  const bruto = max / 4;
  const pot = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 5, 10].map((m) => m * pot).find((p) => p >= bruto);
  const topo = Math.ceil(max / passo) * passo;
  const marcas = [];
  for (let v = 0; v <= topo + 1e-9; v += passo) marcas.push(v);
  return { topo, marcas };
}

function Dica({ x, y, largura, children }) {
  if (x == null) return null;
  const esquerda = Math.min(Math.max(0, x - 70), largura - 140);
  return (
    <div className="pointer-events-none absolute z-10 w-[140px] rounded-lg bg-white px-3 py-2 text-xs shadow-lg ring-1 ring-black/10" style={{ left: esquerda, top: Math.max(0, y - 64) }}>
      {children}
    </div>
  );
}

const ALTO = 200;
const M = { esq: 58, dir: 12, topo: 8, baixo: 24 }; // esquerda cabe "12,9 mil"

function Colunas({ dados }) {
  const [ref, largura] = useLargura();
  const [foco, setFoco] = useState(null);
  const { topo, marcas } = escala(Math.max(...dados.map((d) => d.valor)));
  const w = largura - M.esq - M.dir;
  const banda = w / dados.length;
  const barra = Math.min(24, Math.max(2, banda - 2));
  const y = (v) => M.topo + ALTO - (v / topo) * ALTO;
  const passoRotulo = Math.ceil(dados.length / Math.max(1, Math.floor(w / 56)));
  const ativo = foco != null ? dados[foco] : null;
  return (
    <div ref={ref} className="relative">
      <svg width={largura} height={ALTO + M.topo + M.baixo} role="img" aria-label="Views do canal por dia">
        {marcas.map((m) => (
          <g key={m}>
            <line x1={M.esq} x2={largura - M.dir} y1={y(m)} y2={y(m)} stroke={m === 0 ? BASE : GRADE} strokeWidth="1" />
            <text x={M.esq - 8} y={y(m)} dy="0.32em" textAnchor="end" fontSize="11" fill={MUDO} className="tabular-nums">{fmt(m)}</text>
          </g>
        ))}
        {dados.map((d, k) => {
          const x = M.esq + k * banda + (banda - barra) / 2;
          const alto = Math.max(0, y(0) - y(d.valor));
          const r = Math.min(4, alto, barra / 2);
          return (
            <g key={d.dia}>
              {alto > 0 && (
                <path
                  d={`M${x},${y(0)} V${y(d.valor) + r} Q${x},${y(d.valor)} ${x + r},${y(d.valor)} H${x + barra - r} Q${x + barra},${y(d.valor)} ${x + barra},${y(d.valor) + r} V${y(0)} Z`}
                  fill={COR}
                  opacity={foco == null || foco === k ? 1 : 0.55}
                />
              )}
              {k % passoRotulo === 0 && (
                <text x={M.esq + k * banda + banda / 2} y={ALTO + M.topo + 16} textAnchor="middle" fontSize="11" fill={MUDO}>{diaCurto(d.dia)}</text>
              )}
              <rect
                x={M.esq + k * banda} y={M.topo} width={banda} height={ALTO} fill="transparent" tabIndex={0}
                onPointerEnter={() => setFoco(k)} onPointerLeave={() => setFoco(null)} onFocus={() => setFoco(k)} onBlur={() => setFoco(null)}
                aria-label={`${diaCurto(d.dia)}: ${inteiro.format(d.valor)} views`}
              />
            </g>
          );
        })}
      </svg>
      {ativo && (
        <Dica x={M.esq + foco * banda + banda / 2} y={y(ativo.valor)} largura={largura}>
          <div className="text-sm font-semibold">{inteiro.format(ativo.valor)} views</div>
          <div className="text-suave">{diaCurto(ativo.dia)}{ativo.desde < menosDiasDe(ativo.dia, 1) ? ` (desde ${diaCurto(ativo.desde)})` : ""}</div>
        </Dica>
      )}
    </div>
  );
}

function menosDiasDe(iso, n) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - n);
  return d.toLocaleDateString("sv-SE");
}

function Linha({ dados }) {
  const [ref, largura] = useLargura();
  const [foco, setFoco] = useState(null);
  const valores = dados.map((d) => d.valor);
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  // inscritos variam pouco perto do total: o eixo começa perto do mínimo (sem barras, o zero não é obrigatório)
  const folga = Math.max(1, (max - min) * 0.15);
  const lo = Math.max(0, Math.floor(min - folga));
  const { topo: faixa, marcas: brutas } = escala(max + folga - lo);
  const marcas = brutas.map((m) => m + lo);
  const topo = lo + faixa;
  const w = largura - M.esq - M.dir - 36;
  const x = (k) => M.esq + (dados.length === 1 ? w / 2 : (k / (dados.length - 1)) * w);
  const y = (v) => M.topo + ALTO - ((v - lo) / (topo - lo)) * ALTO;
  const caminho = dados.map((d, k) => `${k ? "L" : "M"}${x(k)},${y(d.valor)}`).join(" ");
  const area = `${caminho} L${x(dados.length - 1)},${y(lo)} L${x(0)},${y(lo)} Z`;
  const passoRotulo = Math.ceil(dados.length / Math.max(1, Math.floor(w / 56)));
  const ultimo = dados[dados.length - 1];
  const mover = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    let melhor = 0;
    dados.forEach((_, k) => { if (Math.abs(x(k) - px) < Math.abs(x(melhor) - px)) melhor = k; });
    setFoco(melhor);
  };
  return (
    <div ref={ref} className="relative">
      <svg width={largura} height={ALTO + M.topo + M.baixo} role="img" aria-label="Inscritos por dia" onPointerMove={mover} onPointerLeave={() => setFoco(null)}>
        {marcas.map((m) => (
          <g key={m}>
            <line x1={M.esq} x2={largura - M.dir} y1={y(m)} y2={y(m)} stroke={GRADE} strokeWidth="1" />
            <text x={M.esq - 8} y={y(m)} dy="0.32em" textAnchor="end" fontSize="11" fill={MUDO} className="tabular-nums">{fmt(m)}</text>
          </g>
        ))}
        <path d={area} fill={COR} opacity="0.1" />
        <path d={caminho} fill="none" stroke={COR} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {dados.map((d, k) => k % passoRotulo === 0 && (
          <text key={d.dia} x={x(k)} y={ALTO + M.topo + 16} textAnchor="middle" fontSize="11" fill={MUDO}>{diaCurto(d.dia)}</text>
        ))}
        {foco != null && <line x1={x(foco)} x2={x(foco)} y1={M.topo} y2={M.topo + ALTO} stroke={BASE} strokeWidth="1" />}
        <circle cx={x(foco ?? dados.length - 1)} cy={y(dados[foco ?? dados.length - 1].valor)} r="4" fill={COR} stroke="#fff" strokeWidth="2" />
        <text x={x(dados.length - 1) + 8} y={y(ultimo.valor)} dy="0.32em" fontSize="12" fontWeight="600" fill="#0a0a0a">{fmt(ultimo.valor)}</text>
      </svg>
      {foco != null && (
        <Dica x={x(foco)} y={y(dados[foco].valor)} largura={largura}>
          <div className="flex items-center gap-2 text-sm font-semibold"><span className="inline-block w-3 h-0.5" style={{ background: COR }} />{inteiro.format(dados[foco].valor)}</div>
          <div className="text-suave">inscritos em {diaCurto(dados[foco].dia)}</div>
        </Dica>
      )}
    </div>
  );
}

function Barras({ dados }) {
  const max = Math.max(...dados.map((d) => d.valor));
  return (
    <div className="space-y-2.5">
      {dados.map((d) => (
        <a key={d.id} href={d.url} target="_blank" rel="noreferrer" className="group grid grid-cols-[minmax(0,14rem)_1fr] sm:grid-cols-[minmax(0,22rem)_1fr] items-center gap-3" title={`${d.rotulo}: ${inteiro.format(d.valor)} views`}>
          <span className="truncate text-sm group-hover:underline">{d.app && <span className="rotulo-mono mr-1.5 rounded border border-black/10 px-1 text-[10px] text-black/55">app</span>}{d.rotulo}</span>
          <span className="flex items-center gap-2 min-w-0">
            <span className="h-3.5 rounded-r-[4px] transition-opacity group-hover:opacity-80" style={{ width: `${Math.max(1, (d.valor / max) * 85)}%`, background: COR }} />
            <span className="text-xs tabular-nums text-suave shrink-0">{fmt(d.valor)}</span>
          </span>
        </a>
      ))}
    </div>
  );
}

const COLUNAS = [
  { id: "publicado", rotulo: "Publicado" },
  { id: "views", rotulo: "Views" },
  { id: "ganho", rotulo: "No período" },
  { id: "retencao", rotulo: "Retenção", an: true },
  { id: "duracaoMedia", rotulo: "Assistido", an: true },
  { id: "novosInscritos", rotulo: "Inscritos +", an: true },
  { id: "porDia", rotulo: "Views/dia" },
  { id: "likes", rotulo: "Likes" },
  { id: "comentarios", rotulo: "Coment." },
  { id: "curtidas", rotulo: "Likes/views" },
];

function Tabela({ videos, periodo, rotuloPeriodo, an }) {
  const [ordem, setOrdem] = useState({ col: "publicado", desc: true });
  const [limite, setLimite] = useState(50);
  const [soApp, setSoApp] = useState(false);
  const lista = useMemo(() => {
    const l = videos.filter((v) => !soApp || v.app);
    const val = (v) => v[ordem.col] ?? -1;
    return [...l].sort((a, b) => (ordem.desc ? val(b) - val(a) : val(a) - val(b)));
  }, [videos, ordem, soApp]);
  // "No período" vale com Analytics (desde a criação = total) ou com retratos e um período escolhido
  const colunas = COLUNAS.filter((c) => (c.id !== "ganho" || periodo || an) && (!c.an || an));
  const celula = (v, id) => {
    if (id === "retencao") return v.retencao == null ? "—" : `${v.retencao.toFixed(0)}%`;
    if (id === "duracaoMedia") return v.duracaoMedia == null ? "—" : formatarDuracao(v.duracaoMedia);
    if (id === "novosInscritos") return v.novosInscritos == null ? "—" : inteiro.format(v.novosInscritos);
    return null;
  };
  return (
    <section className="cartao p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div>
          <h2 className="font-semibold">Todos os vídeos <span className="text-suave font-normal text-sm">({lista.length})</span></h2>
          <p className="text-xs text-suave mt-0.5">“No período” = views ganhas {rotuloPeriodo}. Clique no cabeçalho para ordenar.</p>
        </div>
        <Chip ativo={soApp} onClick={() => setSoApp(!soApp)}>Só os cortes do app</Chip>
      </div>
      <div className="overflow-x-auto -mx-5 px-5">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="text-xs text-suave border-b border-borda">
              <th className="text-left font-medium py-2 pr-3">Vídeo</th>
              {colunas.map((c) => (
                <th key={c.id} className="text-right font-medium py-2 px-2 whitespace-nowrap">
                  <button className="cursor-pointer hover:text-texto inline-flex items-center gap-1" onClick={() => setOrdem({ col: c.id, desc: ordem.col === c.id ? !ordem.desc : true })}>
                    {c.rotulo}{ordem.col === c.id && (ordem.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {lista.slice(0, limite).map((v) => (
              <tr key={v.id} className="border-b border-borda last:border-0">
                <td className="py-2 pr-3">
                  <a href={v.url} target="_blank" rel="noreferrer" className="flex items-center gap-3 min-w-0 group">
                    {v.thumb && <img src={v.thumb} alt="" loading="lazy" className="w-16 aspect-video object-cover rounded-md shrink-0" />}
                    <span className="min-w-0">
                      <span className="block truncate max-w-[28rem] group-hover:underline">{v.titulo}</span>
                      <span className="text-xs text-suave">
                        {v.tipo === "short" ? "Short" : "Longo"} · {formatarDuracao(v.duracao)}
                        {v.app && <> · corte do app{v.app.nota != null ? ` (nota ${v.app.nota})` : ""}</>}
                      </span>
                    </span>
                  </a>
                </td>
                <td className="text-right px-2 text-suave whitespace-nowrap">{new Date(v.publicado * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}</td>
                <td className="text-right px-2 font-medium">{inteiro.format(v.views)}</td>
                {colunas.some((c) => c.id === "ganho") && <td className="text-right px-2">{v.ganho == null ? <span className="text-apagado">—</span> : inteiro.format(v.ganho)}</td>}
                {an && ["retencao", "duracaoMedia", "novosInscritos"].map((id) => <td key={id} className="text-right px-2">{celula(v, id)}</td>)}
                <td className="text-right px-2">{fmt(Math.round(v.porDia))}</td>
                <td className="text-right px-2">{inteiro.format(v.likes)}</td>
                <td className="text-right px-2">{inteiro.format(v.comentarios)}</td>
                <td className="text-right px-2">{(v.curtidas * 100).toFixed(1).replace(".", ",")}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {lista.length > limite && (
        <div className="flex justify-center mt-4"><Botao onClick={() => setLimite(limite + 50)}>Mostrar mais {Math.min(50, lista.length - limite)}</Botao></div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ primeira vez: login do Google ou chave e canal

function LoginGoogle({ dados, aoSalvar }) {
  const avisar = useAvisar();
  const [arquivo, setArquivo] = useState("");
  const [esperando, setEsperando] = useState(false);

  // Depois de abrir o navegador, confere a cada 2 s se o login voltou (o Google redireciona para o servidor local)
  useEffect(() => {
    if (!esperando) return;
    const id = setInterval(async () => {
      try {
        const d = await api.metricas();
        if (d.conectado && d.canal) {
          setEsperando(false);
          aoSalvar(d);
          avisar("Canal conectado com o Google");
        }
      } catch {
        /* tenta de novo no próximo intervalo */
      }
    }, 2000);
    const fim = setTimeout(() => setEsperando(false), 5 * 60 * 1000);
    return () => {
      clearInterval(id);
      clearTimeout(fim);
    };
  }, [esperando, aoSalvar, avisar]);

  const entrar = async () => {
    try {
      await api.entrarGoogle();
      setEsperando(true);
    } catch (e) {
      avisar(e.message, "erro");
    }
  };

  return (
    <div className="cartao p-6 space-y-4">
      <div className="font-semibold">Entrar com o Google (completo)</div>
      {dados.tem_cliente ? (
        <>
          <p className="text-sm text-suave">
            Abre o login no seu navegador: entre com a conta dona do canal e permita o acesso <b>somente leitura</b> ao YouTube e ao
            YouTube Analytics. O app guarda o acesso só neste PC.
          </p>
          <p className="text-xs text-apagado">
            No Google Cloud, ative a <b>YouTube Data API v3</b> e a <b>YouTube Analytics API</b>, e em “Tela de permissão OAuth” adicione o seu
            e-mail como usuário de teste. O Google vai avisar que o app não foi verificado: é o seu próprio app, pode continuar.
          </p>
          <div className="flex items-center justify-end gap-3">
            {esperando && <span className="text-xs text-suave">Esperando você terminar o login no navegador…</span>}
            <Botao variante="primario" onClick={entrar} carregando={esperando}>Entrar com o Google</Botao>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-suave">Cole o caminho do arquivo <span className="font-mono text-[12px]">client_secret_….json</span> do cliente OAuth (tipo “App para computador”) que você baixou do Google Cloud.</p>
          <div className="flex gap-2">
            <input value={arquivo} onChange={(e) => setArquivo(e.target.value)} placeholder="C:\Users\...\Downloads\client_secret_....json" className="campo font-mono text-[13px] flex-1" />
            <Botao
              disabled={!arquivo.trim()}
              onClick={async () => {
                try {
                  aoSalvar(await api.salvarClienteOauth(arquivo));
                  avisar("Cliente OAuth salvo");
                } catch (e) {
                  avisar(e.message, "erro");
                }
              }}
            >
              Usar arquivo
            </Botao>
          </div>
        </>
      )}
    </div>
  );
}

function Configurar({ dados, aoSalvar }) {
  const avisar = useAvisar();
  const [chave, setChave] = useState("");
  const [canal, setCanal] = useState(dados.canal_link || "");
  const [salvando, setSalvando] = useState(false);
  const salvar = async () => {
    setSalvando(true);
    try {
      if (chave.trim()) await api.salvarConfig({ youtube_key: chave.trim() });
      if (canal.trim() !== (dados.canal_link || "")) {
        const r = await api.salvarCanal(canal.trim());
        if (!r.canal.channel_id) throw new Error("Não achei o canal por esse link. Use youtube.com/@seucanal ou youtube.com/channel/UC...");
      }
      aoSalvar(await api.atualizarMetricas());
      avisar("Canal conectado");
    } catch (e) {
      avisar(e.message, "erro");
    } finally {
      setSalvando(false);
    }
  };
  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-5">
      <div>
        <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">Métricas do canal</h1>
        <p className="text-sm text-suave mt-1">Inscritos, views, likes e comentários de cada vídeo, com a evolução dia a dia. Com o login do Google, também retenção, tempo assistido e inscritos ganhos por vídeo.</p>
      </div>
      <LoginGoogle dados={dados} aoSalvar={aoSalvar} />
      <div className="cartao p-6 space-y-4">
        <div className="flex items-center gap-2 font-semibold"><KeyRound className="size-4" />Ou só números públicos: chave grátis da YouTube Data API</div>
        <ol className="text-sm text-suave space-y-1.5 list-decimal pl-5">
          <li>Abra <a className="underline" href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">console.cloud.google.com</a> e crie um projeto (qualquer nome).</li>
          <li>Em <a className="underline" href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">APIs e serviços › Biblioteca</a>, ative a <b>YouTube Data API v3</b>.</li>
          <li>Em <a className="underline" href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">Credenciais</a>: <b>Criar credenciais › Chave de API</b>. Copie e cole abaixo.</li>
        </ol>
        <div>
          <label className="rotulo">Chave da API</label>
          <input value={chave} onChange={(e) => setChave(e.target.value)} placeholder={dados.tem_chave ? "Chave já salva (cole outra para trocar)" : "AIza..."} className="campo mt-2 font-mono text-[13px]" />
        </div>
        <div>
          <label className="rotulo">Link do canal</label>
          <input value={canal} onChange={(e) => setCanal(e.target.value)} placeholder="youtube.com/@seucanal" className="campo mt-2" />
        </div>
        {dados.erro && <Aviso tipo="alerta">{dados.erro}</Aviso>}
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-apagado">Cota grátis: 10.000/dia. Cada atualização gasta ~20.</span>
          <Botao variante="primario" icone={Check} onClick={salvar} carregando={salvando} disabled={!(chave.trim() || dados.tem_chave) || !canal.trim()}>Conectar</Botao>
        </div>
      </div>
      <p className="text-xs text-apagado">O link do canal é o mesmo da aba <Link to="/prontos" className="underline">Prontos</Link>.</p>
    </div>
  );
}
