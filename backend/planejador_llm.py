"""
Interface com o Claude.

O Claude NUNCA executa nada: ele só devolve JSON dentro de uma lista fechada de
ações (ver modelos.py). O código valida com pydantic e executa.

Funções:
- interpretar_instrucao(): linguagem natural -> PlanoEdicao
- escolher_cortes_falado(): transcrição -> lista de Cortes
- escolher_cortes_gameplay(): candidatos (picos de áudio) -> escolhas
- interpretar_ajuste(): "deixa mais curto" -> AjusteClips
- confirmar_frames(): refino por imagem (etapa 11)
"""
import base64
import json
import logging
import re

import anthropic
from pydantic import BaseModel, ValidationError

import config
import custos
from modelos import (AjusteClips, ConfirmacaoFrames, Corte, PlanoEdicao,
                     RespostaCortes, RespostaGameplay)

log = logging.getLogger("claude")


class ErroClaude(RuntimeError):
    pass


# Última falha da API (mostrada na interface); some quando uma chamada funciona
estado = {"ultimo_erro": None}


def _cliente() -> anthropic.Anthropic:
    chave = config.api_key()
    if not chave:
        raise ErroClaude("Chave da API não configurada. Defina ANTHROPIC_API_KEY ou salve em Configurações.")
    return anthropic.Anthropic(api_key=chave, max_retries=3)


def _extrair_json(texto: str) -> str:
    """Tira cercas ```json e pega do primeiro { ao último }."""
    texto = re.sub(r"```(?:json)?", "", texto).strip()
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("resposta sem objeto JSON")
    return texto[ini:fim + 1]


def _chamar_json(sistema: str, conteudo, modelo_resposta: type[BaseModel], projeto_id=None,
                 motivo: str = "", max_tokens: int = 8000) -> BaseModel:
    """Chama o Claude pedindo APENAS JSON, valida com pydantic e tenta de novo 1x se vier inválido."""
    try:
        resultado = _chamar_json_sem_estado(sistema, conteudo, modelo_resposta, projeto_id, motivo, max_tokens)
        estado["ultimo_erro"] = None
        return resultado
    except ErroClaude as e:
        estado["ultimo_erro"] = str(e)
        raise


def _chamar_json_sem_estado(sistema, conteudo, modelo_resposta, projeto_id, motivo, max_tokens):
    cliente = _cliente()
    modelo = config.carregar()["modelo"]
    mensagens = [{"role": "user", "content": conteudo}]

    for tentativa in (1, 2):
        try:
            resposta = cliente.messages.create(
                model=modelo, max_tokens=max_tokens, system=sistema, messages=mensagens,
            )
        except anthropic.AuthenticationError:
            raise ErroClaude("Chave da API inválida (401). Confira em Configurações.")
        except anthropic.NotFoundError:
            raise ErroClaude(f"Modelo '{modelo}' não encontrado. Troque em Configurações.")
        except anthropic.RateLimitError:
            raise ErroClaude("Limite de requisições da API atingido. Tente de novo em alguns minutos.")
        except anthropic.APIConnectionError:
            raise ErroClaude("Sem conexão com a API da Anthropic.")
        except anthropic.APIStatusError as e:
            if "credit balance" in str(e.message):
                raise ErroClaude("Conta da API Anthropic sem créditos (Plans & Billing no console).")
            raise ErroClaude(f"Erro da API ({e.status_code}): {e.message}")

        custo = custos.registrar(modelo, resposta.usage, projeto_id, motivo)
        log.info("%s: %d tokens entrada, %d saída (US$ %.4f)", motivo or "chamada",
                 resposta.usage.input_tokens, resposta.usage.output_tokens, custo)

        if resposta.stop_reason == "refusal":
            raise ErroClaude("O modelo recusou o pedido.")
        texto = "".join(b.text for b in resposta.content if b.type == "text")
        try:
            if resposta.stop_reason == "max_tokens":
                raise ValueError("resposta cortada por limite de tokens")
            return modelo_resposta.model_validate(json.loads(_extrair_json(texto)))
        except (ValueError, ValidationError) as e:
            log.warning("JSON inválido na tentativa %d: %s", tentativa, str(e)[:300])
            if tentativa == 2:
                raise ErroClaude(f"O Claude devolveu JSON inválido duas vezes: {str(e)[:300]}")
            mensagens += [
                {"role": "assistant", "content": texto or "(vazio)"},
                {"role": "user", "content": f"Seu JSON está inválido: {str(e)[:500]}\n"
                                            "Responda de novo APENAS com o objeto JSON corrigido, sem texto extra."},
            ]


# ================================================================ 1. instrução -> plano

def presets_disponiveis() -> dict:
    return config.ler_json(config.ARQ_ESTILOS, {})


SISTEMA_PLANO = """Você converte pedidos de edição de vídeo em um PLANO DE EDIÇÃO em JSON.
Responda APENAS com um objeto JSON válido, sem markdown e sem comentários.

Lista FECHADA de campos (não invente outros):
- num_clips: inteiro 1-20 (quantos clipes gerar)
- duracao_min, duracao_max: segundos (5-180)
- formato: "9:16" | "16:9" | "1:1"  (vertical = 9:16, horizontal = 16:9, quadrado = 1:1)
- legenda: {{"ativa": bool, "estilo": "simples"|"animada", "preset": um de {presets}, "cor": "#RRGGBB" ou null (cor da palavra falada; null = cor do preset)}}
- zoom_em_enfase: bool (zoom sutil nas palavras de ênfase / momentos intensos, ex.: "zoom nas kills")
- remover_silencios: bool (corta pausas longas e vícios como "hum", "é", "tipo")
- musica_fundo: bool
- musica_caminho: string com caminho de arquivo de música, ou null
- normalizar_audio: bool
- titulo_gancho: bool (título chamativo nos primeiros segundos)
- nao_atendido: lista de strings curtas descrevendo CADA parte do pedido que não cabe nos campos acima
  (ex.: "adicionar memes", "trocar o fundo", "efeito de transição"). Lista vazia se tudo foi atendido.

Regras:
- Parta das OPÇÕES BASE; mude só o que a instrução pedir explicitamente.
- "sem música" => musica_fundo=false. "sem legenda" => legenda.ativa=false.
- "animada", "dinâmica", "estilo tiktok/opus" => estilo "animada". Se não for mencionado, mantenha o da base.
- Só preencha legenda.cor se o usuário pedir uma cor. Cores por nome viram hex (amarelo #FFE600, verde #22FF6B, azul #3B82F6, vermelho #FF3B30, rosa #FF4FD8, branco #FFFFFF, laranja #FF8A00, roxo #A855F7).
- Uma faixa como "15-30s" define duracao_min=15 e duracao_max=30.
- Se o pedido pedir música mas não houver caminho, deixe musica_fundo=false e coloque em nao_atendido."""


def interpretar_instrucao(instrucao: str, modo: str, base: PlanoEdicao, projeto_id=None) -> PlanoEdicao:
    """Converte a instrução em plano. Sem instrução, usa só as opções da interface (sem custo)."""
    if not instrucao.strip():
        return base
    presets = list(presets_disponiveis().keys()) or ["opus"]
    sistema = SISTEMA_PLANO.format(presets=" | ".join(f'"{p}"' for p in presets))
    base_json = base.model_dump(exclude={"nao_atendido"})
    conteudo = (f"MODO DO VÍDEO: {modo}\n"
                f"OPÇÕES BASE (escolhidas na interface):\n{json.dumps(base_json, ensure_ascii=False)}\n\n"
                f"INSTRUÇÃO DO USUÁRIO:\n{instrucao.strip()}")
    plano = _chamar_json(sistema, conteudo, PlanoEdicao, projeto_id, "plano de edição", max_tokens=1500)
    if plano.legenda.preset not in presets:
        plano.nao_atendido.append(f"preset de legenda '{plano.legenda.preset}' não existe (usando '{base.legenda.preset}')")
        plano.legenda.preset = base.legenda.preset
    return plano


# ================================================================ 2. escolha de cortes (falado)

SISTEMA_CORTES = """Você é um editor de vídeos curtos virais (TikTok, Reels, Shorts).
Recebe a transcrição com tempos de um vídeo e escolhe os MELHORES trechos para virar clipes.
Responda APENAS com JSON válido, sem markdown, no formato:
{"cortes": [{"inicio": 12.3, "fim": 47.8, "titulo": "...", "nota": 87, "justificativa": "...",
             "palavras_enfase": ["..."], "emojis": [{"palavra": "...", "emoji": "🔥"}]}]}

Critérios:
- Cada clipe deve fazer sentido SOZINHO: começa numa frase que prende atenção (gancho) e termina num pensamento completo.
- Respeite a duração pedida. Use os tempos da transcrição (início de uma frase, fim de outra).
- Clipes não podem se sobrepor.
- titulo: gancho curto (máx. 8 palavras) no idioma do vídeo, que gere curiosidade. Sem aspas, sem emoji.
- nota: potencial viral de 0 a 100. Seja criterioso: 85+ só para trechos realmente fortes
  (revelação, número impactante, história com virada, opinião polêmica, conselho prático claro).
- justificativa: 1 frase curta (máx. 20 palavras) explicando a nota.
- palavras_enfase: 2 a 6 palavras DO PRÓPRIO TRECHO (copiadas exatamente como aparecem) que merecem destaque/zoom.
- emojis: 0 a 3 por clipe, só em palavras-chave onde um emoji reforça o sentido.
- Ordene do melhor para o pior."""


def _formatar_transcricao(transcricao: dict) -> str:
    return "\n".join(f"[{s['inicio']:.1f}-{s['fim']:.1f}] {s['texto']}" for s in transcricao["segmentos"])


def escolher_cortes_falado(transcricao: dict, plano: PlanoEdicao, projeto_id=None,
                           excluir: list[tuple[float, float]] | None = None, quantidade: int | None = None) -> list[Corte]:
    quantidade = quantidade or plano.num_clips
    duracao_video = transcricao["duracao"]
    dmin = min(plano.duracao_min, duracao_video)
    dmax = min(plano.duracao_max, duracao_video)
    pedido = (f"Escolha {quantidade} clipe(s) com duração entre {dmin:.0f} e {dmax:.0f} segundos.\n"
              f"Duração total do vídeo: {duracao_video:.0f}s.\n")
    if excluir:
        pedido += ("NÃO use estes intervalos (já viraram clipes): "
                   + ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in excluir) + "\n")
    conteudo = pedido + "\nTRANSCRIÇÃO:\n" + _formatar_transcricao(transcricao)
    resposta = _chamar_json(SISTEMA_CORTES, conteudo, RespostaCortes, projeto_id, "escolha de cortes")

    cortes = []
    for c in resposta.cortes:
        ajustado = ajustar_as_palavras(c, transcricao["palavras"], dmin, dmax, duracao_video)
        if ajustado and not _sobrepoe(ajustado, cortes + [Corte(inicio=a, fim=b) for a, b in (excluir or [])]):
            cortes.append(ajustado)
    cortes.sort(key=lambda c: c.nota, reverse=True)
    return cortes[:quantidade]


def _sobrepoe(c: Corte, outros: list[Corte]) -> bool:
    for o in outros:
        inter = min(c.fim, o.fim) - max(c.inicio, o.inicio)
        if inter > 0.3 * min(c.fim - c.inicio, o.fim - o.inicio):
            return True
    return False


def _fim_de_frase(p: str) -> bool:
    return p.rstrip().endswith((".", "!", "?", "…"))


def ajustar_as_palavras(corte: Corte, palavras: list[dict], dmin: float, dmax: float,
                        duracao_video: float) -> Corte | None:
    """Encaixa início/fim nas bordas das palavras e corrige a duração
    procurando fins de frase (o clipe nunca termina no meio de uma palavra)."""
    if not palavras:
        return corte
    dentro = [w for w in palavras if w["i"] >= corte.inicio - 0.4]
    if not dentro:
        return None
    primeira = dentro[0]
    inicio = max(0.0, primeira["i"] - 0.1)
    candidatas = [w for w in palavras if w["i"] >= primeira["i"]]

    def fim_ideal(limite_min, limite_max):
        # Prefere fim de frase dentro da janela; senão, qualquer palavra
        janela = [w for w in candidatas if limite_min <= w["f"] - inicio <= limite_max]
        frases = [w for w in janela if _fim_de_frase(w["p"])]
        return (frases or janela or [None])[-1]

    ultimas = [w for w in candidatas if w["f"] <= corte.fim + 0.4]
    fim_palavra = ultimas[-1] if ultimas else candidatas[-1]
    duracao = fim_palavra["f"] - inicio
    tol = 0.1  # 10% de tolerância
    if duracao > dmax * (1 + tol) or duracao < dmin * (1 - tol):
        # Tenta o fim de frase mais próximo do fim sugerido, dentro dos limites
        melhor = fim_ideal(dmin * (1 - tol), min(dmax * (1 + tol), max(duracao, dmin)))
        if melhor is None:
            melhor = fim_ideal(dmin * 0.7, dmax * (1 + tol))
        if melhor is not None:
            fim_palavra = melhor
    fim = min(duracao_video, fim_palavra["f"] + 0.25)
    if fim - inicio < 3:
        return None
    return corte.model_copy(update={"inicio": round(inicio, 2), "fim": round(fim, 2)})


# ================================================================ 3. gameplay

SISTEMA_GAMEPLAY = """Você é um editor de clipes de gameplay para TikTok/Shorts.
Recebe CANDIDATOS pré-selecionados por picos de energia no áudio (tiros, explosões, gritos, risadas)
e, quando houver, o que o jogador falou em cada trecho.
Escolha os melhores e responda APENAS com JSON válido, sem markdown:
{"escolhas": [{"id": 3, "titulo": "...", "nota": 82, "justificativa": "...",
               "palavras_enfase": ["..."], "emojis": [{"palavra": "...", "emoji": "💀"}]}]}
- titulo: gancho curto (máx. 7 palavras), estilo gamer, no idioma da fala (português se não houver fala).
- nota 0-100: energia + reação do jogador + clareza do momento. 85+ só para momentos excepcionais.
- justificativa: 1 frase curta.
- palavras_enfase: palavras ditas no trecho que merecem destaque (vazio se não houver fala).
- Ordene do melhor para o pior."""


def escolher_cortes_gameplay(candidatos: list[dict], quantidade: int, projeto_id=None) -> RespostaGameplay:
    linhas = []
    for c in candidatos:
        fala = c.get("fala") or "(sem fala)"
        linhas.append(f"id={c['id']} | {c['inicio']:.1f}-{c['fim']:.1f}s | energia={c['energia']:.0f}/100 | "
                      f"picos={c['picos']} | fala: {fala[:400]}")
    conteudo = f"Escolha até {quantidade} candidatos.\n\nCANDIDATOS:\n" + "\n".join(linhas)
    return _chamar_json(SISTEMA_GAMEPLAY, conteudo, RespostaGameplay, projeto_id, "escolha gameplay", max_tokens=4000)


# ================================================================ 4. ajustes em linguagem natural

SISTEMA_AJUSTE = """Você converte pedidos de ajuste de clipes de vídeo em JSON. Responda APENAS com JSON válido.
Campos possíveis (todos opcionais, use null para o que não foi pedido):
- duracao_alvo: segundos (ex.: "deixa mais curto" => ~70% da duração atual; "mais longo" => ~130%)
- cor_legenda: "#RRGGBB"
- preset: um de {presets}
- estilo_legenda: "simples" | "animada"
- legenda_ativa: bool
- titulo_ativo: bool
- novo_titulo: string (só se pedirem para trocar o título; escreva o novo título)
- zoom_em_enfase: bool
- remover_silencios: bool
- normalizar_audio: bool
- formato: "9:16" | "16:9" | "1:1"
- nao_atendido: lista de partes do pedido que não cabem nesses campos."""


def interpretar_ajuste(pedido: str, clipes: list[dict], projeto_id=None) -> AjusteClips:
    presets = list(presets_disponiveis().keys())
    sistema = SISTEMA_AJUSTE.format(presets=" | ".join(f'"{p}"' for p in presets))
    contexto = [{"titulo": c.get("titulo"), "duracao": round(c.get("fim", 0) - c.get("inicio", 0), 1)} for c in clipes]
    conteudo = f"CLIPES SELECIONADOS: {json.dumps(contexto, ensure_ascii=False)}\n\nPEDIDO: {pedido}"
    return _chamar_json(sistema, conteudo, AjusteClips, projeto_id, "ajuste", max_tokens=1000)


# ================================================================ 5. refino por imagem (etapa 11)

SISTEMA_FRAMES = """Você avalia se um trecho de gameplay é um bom momento para um clipe curto viral.
Recebe alguns frames em ordem cronológica e o contexto do áudio.
Responda APENAS com JSON: {"bom_momento": true, "nota": 0-100, "titulo": "gancho curto", "justificativa": "1 frase"}
Bons momentos: kills, jogadas difíceis, explosões, falhas engraçadas, vitórias, sustos.
Ruins: menus, loading, tela parada, inventário, mapa."""


def confirmar_frames(frames_jpg: list[bytes], contexto: str, projeto_id=None) -> ConfirmacaoFrames:
    conteudo = []
    for i, dados in enumerate(frames_jpg, 1):
        conteudo.append({"type": "text", "text": f"Frame {i}:"})
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.standard_b64encode(dados).decode()}})
    conteudo.append({"type": "text", "text": f"Contexto: {contexto}"})
    return _chamar_json(SISTEMA_FRAMES, conteudo, ConfirmacaoFrames, projeto_id, "refino por frames", max_tokens=600)
