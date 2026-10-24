"""
Interface com o Claude.

O Claude NUNCA executa nada: ele só devolve JSON dentro de uma lista fechada de
ações (ver modelos.py). O código valida com pydantic e executa.

Funções:
- interpretar_instrucao(): linguagem natural -> PlanoEdicao
- escolher_cortes_falado(): transcrição -> lista de Cortes
- escolher_cortes_gameplay(): candidatos (picos de áudio) -> escolhas
- interpretar_ajuste(): "deixa mais curto" -> AjusteClips
"""
import base64
import hashlib
import json
import logging
import re
import shutil
import time

import anthropic
from pydantic import BaseModel, ValidationError

import config
import custos
import direcao
from modelos import (CLIMAS, AjusteClips, Correcoes, Corte, EdicaoLonga, PlanoEdicao, TitulosCapitulos,
                     RespostaCortes, RespostaGameplay, RevisaoClipe)

log = logging.getLogger("claude")


class ErroClaude(RuntimeError):
    pass


# Última falha da API (mostrada na interface); some quando uma chamada funciona
estado = {"ultimo_erro": None}


def _cliente() -> anthropic.Anthropic:
    chave = config.api_key()
    if not chave:
        raise ErroClaude("Chave da API não configurada. Defina ANTHROPIC_API_KEY ou salve em Configurações.")
    workspace = config.workspace_id()
    cabecalhos = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(api_key=chave, max_retries=3, default_headers=cabecalhos)


def _extrair_json(texto: str) -> str:
    """Tira cercas ```json e pega o primeiro objeto JSON completo (ignora texto ou JSON repetido depois)."""
    texto = re.sub(r"```(?:json)?", "", texto).strip()
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("resposta sem objeto JSON")
    try:
        _, tamanho = json.JSONDecoder().raw_decode(texto[ini:])
        return texto[ini:ini + tamanho]
    except json.JSONDecodeError:
        pass
    return texto[ini:fim + 1]


def _suporta_esforco(modelo: str) -> bool:
    """`effort` existe no Opus 4.5+, Sonnet 4.6+ e famílias 5; no Haiku 4.5 e no Sonnet 4.5 dá erro."""
    return not re.search(r"haiku|sonnet-4-5|claude-3", modelo)


def _chamar_json(sistema: str, conteudo, modelo_resposta: type[BaseModel], projeto_id=None,
                 motivo: str = "", max_tokens: int = 8000, rapido: bool = False) -> BaseModel:
    """Chama o Claude pedindo APENAS JSON, valida com pydantic e tenta de novo 1x se vier inválido.
    rapido=True usa o modelo da revisão fina (Configurações > modelo_rapido; vazio = o principal)."""
    try:
        resultado = _chamar_json_sem_estado(sistema, conteudo, modelo_resposta, projeto_id, motivo, max_tokens, rapido)
        estado["ultimo_erro"] = None
        return resultado
    except ErroClaude as e:
        estado["ultimo_erro"] = str(e)
        raise


def _pasta_respostas(projeto_id: str):
    return config.PASTA_PROJETOS / projeto_id / "respostas"


def esquecer_respostas(projeto_id: str) -> None:
    """Apaga as respostas guardadas do projeto: a próxima rodada pergunta tudo de novo ao Claude."""
    shutil.rmtree(_pasta_respostas(projeto_id), ignore_errors=True)


def _arquivo_resposta(projeto_id, modelo, sistema, conteudo, max_tokens, extras, modelo_resposta):
    """Cada resposta válida fica guardada no projeto, pela impressão digital do pedido (modelo, prompt,
    transcrição, imagens). Continuar um processamento que parou no meio não paga de novo o que já foi
    respondido; "Refazer" um projeto pronto apaga tudo (esquecer_respostas) para vir uma edição nova."""
    if not projeto_id:
        return None
    pedido = json.dumps([modelo, sistema, conteudo, max_tokens, extras, modelo_resposta.__name__],
                        ensure_ascii=False, sort_keys=True, default=str)
    return _pasta_respostas(projeto_id) / f"{hashlib.sha256(pedido.encode('utf-8')).hexdigest()[:32]}.json"


def _resposta_guardada(arquivo, modelo_resposta, motivo):
    if not arquivo or not arquivo.exists():
        return None
    try:
        texto = json.loads(arquivo.read_text(encoding="utf-8"))["texto"]
        resultado = modelo_resposta.model_validate(json.loads(_extrair_json(texto)))
    except (OSError, KeyError, TypeError, ValueError, ValidationError):
        return None
    log.info("%s: resposta reaproveitada (sem custo)", motivo or "chamada")
    return resultado


def _chamar_json_sem_estado(sistema, conteudo, modelo_resposta, projeto_id, motivo, max_tokens, rapido=False):
    cfg = config.carregar()
    modelo = (cfg.get("modelo_rapido") or cfg["modelo"]) if rapido else cfg["modelo"]
    mensagens = [{"role": "user", "content": conteudo}]
    # Escolher trechos e montar JSON não precisa de raciocínio longo: esforço baixo corta
    # a maior parte dos tokens de saída (o que mais pesa no custo)
    extras = {"output_config": {"effort": "low"}} if _suporta_esforco(modelo) else {}
    arquivo = _arquivo_resposta(projeto_id, modelo, sistema, conteudo, max_tokens, extras, modelo_resposta)
    guardada = _resposta_guardada(arquivo, modelo_resposta, motivo)
    if guardada is not None:
        return guardada
    cliente = _cliente()

    for tentativa in (1, 2):
        try:
            resposta = cliente.messages.create(
                model=modelo, max_tokens=max_tokens, system=sistema, messages=mensagens, **extras,
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
            resultado = modelo_resposta.model_validate(json.loads(_extrair_json(texto)))
            if arquivo:
                try:
                    config.gravar_json(arquivo, {"motivo": motivo, "modelo": modelo, "em": time.time(), "texto": texto})
                except OSError as e:
                    log.warning("Não consegui guardar a resposta: %s", e)
            return resultado
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

CLIMAS_TEXTO = "Um de: " + "; ".join(f'"{c}" ({d})' for c, d in CLIMAS.items()) + "."


def presets_disponiveis() -> dict:
    return config.ler_json(config.ARQ_ESTILOS, {})


SISTEMA_PLANO = """Você converte pedidos de edição de vídeo em um PLANO DE EDIÇÃO em JSON.
Responda APENAS com um objeto JSON válido, sem markdown e sem comentários.

Lista FECHADA de campos (não invente outros):
- num_clips: inteiro 1-100 (quantos clipes gerar)
- duracao_min, duracao_max: segundos (5-180)
- formato: "9:16" | "16:9" | "1:1"  (vertical = 9:16, horizontal = 16:9, quadrado = 1:1)
- legenda: {{"ativa": bool, "estilo": "simples"|"animada", "preset": um de {presets}, "cor": "#RRGGBB" ou null (cor da palavra falada; null = cor do preset)}}
- zoom_em_enfase: bool (zoom sutil nas palavras de ênfase / momentos intensos, ex.: "zoom nas kills")
- remover_silencios: bool (corta pausas longas e vícios como "hum", "é", "tipo")
- musica_fundo: bool (música de fundo; o app sorteia uma faixa da biblioteca local e abaixa quando há voz)
- musica_caminho: string com caminho de arquivo de música (só se o usuário informar um), ou null
- musica_clima: um de {climas}, ou null (null = escolhido por clipe conforme o trecho)
- efeitos_sonoros: bool (whoosh no título, impacto nas kills/picos, pop nos zooms de ênfase)
- normalizar_audio: bool
- titulo_gancho: bool (título chamativo nos primeiros segundos)
- barra_progresso: bool ou null (barra que enche no topo durante o clipe; null = padrão do preset)
- abertura_climax: bool (1-2 s do melhor momento no começo, como teaser, antes do contexto)
- limpar_voz: bool ou null (tira ruído de fundo e zumbido e melhora a voz; null = automático)
- nao_atendido: lista de strings curtas descrevendo CADA parte do pedido que não cabe nos campos acima
  (ex.: "adicionar memes", "trocar o fundo", "efeito de transição"). Lista vazia se tudo foi atendido.

Regras:
- Parta das OPÇÕES BASE; mude só o que a instrução pedir explicitamente.
- "sem música" => musica_fundo=false. "sem legenda" => legenda.ativa=false.
- "animada", "dinâmica", "estilo tiktok/opus" => estilo "animada". Se não for mencionado, mantenha o da base.
- Só preencha legenda.cor se o usuário pedir uma cor. Cores por nome viram hex (amarelo #FFE600, verde #22FF6B, azul #3B82F6, vermelho #FF3B30, rosa #FF4FD8, branco #FFFFFF, laranja #FF8A00, roxo #A855F7).
- Uma faixa como "15-30s" define duracao_min=15 e duracao_max=30.
- "com música" => musica_fundo=true. Clima só se pedido ("música tensa" => musica_clima="tensa").
- "efeitos sonoros", "sfx", "sons", "whoosh" => efeitos_sonoros=true. "sem efeitos" => false."""


def interpretar_instrucao(instrucao: str, modo: str, base: PlanoEdicao, projeto_id=None) -> PlanoEdicao:
    """Converte a instrução em plano. Sem instrução, usa só as opções da interface (sem custo)."""
    if not instrucao.strip():
        return base
    presets = list(presets_disponiveis().keys()) or ["opus"]
    sistema = SISTEMA_PLANO.format(presets=" | ".join(f'"{p}"' for p in presets),
                                   climas=" | ".join(f'"{c}"' for c in CLIMAS))
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
             "palavras_enfase": ["..."], "emojis": [{"palavra": "...", "emoji": "🔥"}], "clima": "calma",
             "remover": [[20.1, 23.4]], "correcoes": [{"de": "palavra errada", "para": "palavra certa"}],
             "gancho": [31.2, 34.0], "legenda_post": "...", "hashtags": ["#..."],
             "direcao": {"preset": "...", "cor": null, "look": "...", "transicao": "...", "zoom": "medio", "impacto": "nenhum"},
             "broll": [{"inicio": 40.2, "fim": 42.8, "busca": "stack of money"}]}]}

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
- clima: música de fundo que combina com o trecho. """ + CLIMAS_TEXTO + """
- remover: trechos DENTRO do clipe que enrolam e derrubam a retenção (frase repetida, começo em falso,
  desvio de assunto, "enfim, onde eu tava"). Use os tempos da transcrição. Vazio se o trecho já é enxuto.
  Nunca remova o gancho nem o fechamento.
- correcoes: erros evidentes de transcrição automática no trecho (palavra que não faz sentido no contexto),
  copiando "de" exatamente como está na transcrição. Vazio se não houver.
- gancho: a frase mais forte do clipe (1,5 a 4 s, frase inteira), que vai ser mostrada também no começo como
  teaser antes do contexto. Deve estar DENTRO do clipe e depois dos 3 primeiros segundos. null se o clipe já
  começa com a frase mais forte.
- legenda_post: texto da descrição do post, no idioma do vídeo (1 ou 2 frases curtas, máx. 150 caracteres):
  complementa o título sem repeti-lo e termina com uma pergunta ou chamada para comentar. Sem hashtags.
- hashtags: 3 a 5 do assunto do clipe (as mais específicas primeiro), sem genéricas como #fyp, #viral, #foryou.
- broll: 1 ou 2 vídeos de apoio de banco de imagens por clipe, nos momentos em que a fala cita algo que dá
  para MOSTRAR: objeto, lugar, ação, profissão, dinheiro, tecnologia ("comprei um carro", "fui pra praia",
  "olhei no espelho", "a empresa cresceu", "fiquei doente"). Quase todo trecho de fala tem pelo menos um;
  vazio só se o trecho for todo abstrato. Cada um fica DENTRO do clipe e cobre a tela de inicio a fim (2 a 3 s, nos tempos da
  transcrição, enquanto a frase é dita), nunca nos 3 primeiros segundos nem no momento mais emocional, em
  que o rosto importa. busca: 2 a 4 palavras em INGLÊS, concretas, do jeito que se busca num banco de vídeos
  ("man looking in mirror", "startup office team", "sports car driving").
- Ordene do melhor para o pior."""


def _com_direcao(sistema: str) -> str:
    """Acrescenta o catálogo da direção de arte (os presets vêm do estilos.json, que o usuário pode editar)."""
    return sistema + "\n" + direcao.texto_catalogo(list(presets_disponiveis()))


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
    resposta = _chamar_json(_com_direcao(SISTEMA_CORTES), conteudo, RespostaCortes, projeto_id, "escolha de cortes")

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

SISTEMA_GAMEPLAY = """Você é um editor de clipes de gameplay para TikTok/Shorts, obcecado por retenção.
Recebe CANDIDATOS pré-selecionados por picos de energia no áudio (tiros, explosões, gritos, risadas),
o que o jogador falou em cada trecho (com o tempo de cada frase) e, quando houver, uma FOLHA DE QUADROS:
8 imagens em ordem, cada uma com o segundo do vídeo escrito no canto (t=123.4).
Escolha os melhores e responda APENAS com JSON válido, sem markdown:
{"escolhas": [{"id": 3, "inicio": 101.5, "fim": 128.0, "titulo": "...", "nota": 82, "justificativa": "...",
               "palavras_enfase": ["..."], "emojis": [{"palavra": "...", "emoji": "💀"}], "clima": "energetica",
               "remover": [[110.0, 114.5]], "correcoes": [{"de": "meu jeep", "para": "meu Deus"}],
               "legenda_post": "...", "hashtags": ["#..."],
               "direcao": {"preset": "...", "cor": null, "look": "...", "transicao": "...", "zoom": "forte", "impacto": "tremor"}}]}
- Use os quadros para ver o que acontece de verdade. DESCARTE (não inclua) candidatos sem ação real:
  menu, loja/fase de compra, loading, mapa, tela parada, espectador, jogador só andando.
- inicio/fim: segundos do vídeo, dentro da janela do candidato, respeitando a duração pedida.
  Comece no máximo ~2 s antes da ação (o gancho é a ação, nada de preparação longa).
  Termine logo após o desfecho e a reação (~1-2 s). Não termine em tela de derrota/morte parada,
  a não ser que ela seja a graça do clipe.
- remover: trechos mortos DENTRO do clipe (andando sem nada, esperando, fase de compra) de 2 s ou mais.
  Vazio se não houver. Nunca remova a ação principal.
- correcoes: erros evidentes da transcrição automática (o áudio do jogo atrapalha), copiando "de" exatamente
  como aparece na fala. Ex.: "meu jeep" gritado numa kill quase certamente é "meu Deus".
- titulo: gancho curto (máx. 7 palavras), estilo gamer, no idioma da fala (português se não houver fala).
  Deve prometer o que o clipe entrega (ex.: "1 contra 3 com a faca"), sem entregar o final.
- nota 0-100: energia + reação do jogador + clareza do momento. 85+ só para momentos excepcionais.
- justificativa: 1 frase curta.
- palavras_enfase: palavras ditas no trecho que merecem destaque (vazio se não houver fala).
- clima: música de fundo que combina com o momento. """ + CLIMAS_TEXTO + """
- legenda_post: descrição do post, estilo gamer, no idioma da fala (1 frase curta, máx. 120 caracteres),
  terminando com uma pergunta ou provocação para comentar. Escreva como quem posta o próprio clipe
  (1ª pessoa ou neutro; nunca "o jogador"). Sem hashtags.
- hashtags: 3 a 5: o jogo (se der para identificar pela tela ou pela fala), o tipo de jogada e o nicho.
  Sem genéricas como #fyp, #viral, #foryou.
- Ordene do melhor para o pior."""


def escolher_cortes_gameplay(candidatos: list[dict], quantidade: int, projeto_id=None,
                             dmin: float = 15, dmax: float = 45) -> RespostaGameplay:
    """Com "folha" (JPEG) nos candidatos, o Claude vê os quadros; sem, decide só pelo áudio e pela fala."""
    cabecalho = (f"Escolha até {quantidade} candidato(s). Duração de cada clipe: entre {dmin:.0f} e {dmax:.0f} s "
                 "(depois de remover os trechos mortos).\n\nCANDIDATOS:")
    conteudo = [{"type": "text", "text": cabecalho}]
    for c in candidatos:
        fala = c.get("fala_tempos") or c.get("fala") or "(sem fala)"
        conteudo.append({"type": "text", "text": (
            f"\nid={c['id']} | janela {c['inicio']:.1f}-{c['fim']:.1f}s | pico de áudio em {c['pico']:.1f}s | "
            f"energia={c['energia']:.0f}/100 | picos={c['picos']}\nfala: {fala[:700]}")})
        if c.get("folha"):
            conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(c["folha"]).decode()}})
    return _chamar_json(_com_direcao(SISTEMA_GAMEPLAY), conteudo, RespostaGameplay, projeto_id, "escolha gameplay",
                        max_tokens=5000)


SISTEMA_REVISAO = """Você classifica quadros de um trecho de gameplay para a edição de um clipe curto.
Recebe uma FOLHA DE QUADROS em ordem (esquerda para direita, de cima para baixo), cada um com o segundo do
vídeo escrito no canto (t=123.4). Dê UM rótulo por quadro, na mesma ordem, e responda APENAS com JSON:
{"quadros": ["menu", "acao", "acao", "reacao", "morto"]}
Rótulos:
- "acao": combate acontecendo: mirando/atirando em inimigo, kill, explosão, perseguição, perigo claro.
- "reacao": segundos logo depois de uma kill/jogada (comemoração, câmera ainda no lance).
- "morto": jogador só andando, esperando, olhando o nada, sem inimigo à vista.
- "menu": tudo que não é jogo rolando: fase de compra/loja, loading, placar, mapa, espectador,
  telas/faixas de fim de round ("VENCEU", "PERDEU", "CLUTCH", "VITÓRIA", "DERROTA"),
  câmera de morte (o próprio jogador morto/caído, kill cam), tela escurecendo/preta, respawn.
Na dúvida entre "acao" e "morto", use "acao" se houver inimigo visível ou tiro."""


def revisar_clipe_gameplay(folha: bytes, n: int, projeto_id=None) -> RevisaoClipe:
    """Rótulo de cada quadro com o modelo rápido (~1.500 tokens de entrada, ~60 de saída)."""
    conteudo = [
        {"type": "text", "text": f"A folha tem {n} quadros. Responda com exatamente {n} rótulos."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(folha).decode()}},
    ]
    return _chamar_json(SISTEMA_REVISAO, conteudo, RevisaoClipe, projeto_id, "revisão do clipe",
                        max_tokens=800, rapido=True)


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
- efeitos_sonoros: bool (whoosh, impacto, pop)
- limpar_voz: bool (tira ruído de fundo e melhora a voz)
- formato: "9:16" | "16:9" | "1:1"
- nao_atendido: lista de partes do pedido que não cabem nesses campos."""


def interpretar_ajuste(pedido: str, clipes: list[dict], projeto_id=None) -> AjusteClips:
    presets = list(presets_disponiveis().keys())
    sistema = SISTEMA_AJUSTE.format(presets=" | ".join(f'"{p}"' for p in presets))
    contexto = [{"titulo": c.get("titulo"), "duracao": round(c.get("fim", 0) - c.get("inicio", 0), 1)} for c in clipes]
    conteudo = f"CLIPES SELECIONADOS: {json.dumps(contexto, ensure_ascii=False)}\n\nPEDIDO: {pedido}"
    return _chamar_json(sistema, conteudo, AjusteClips, projeto_id, "ajuste", max_tokens=1000)


# ================================================================ 6. vídeos longos (YouTube)

SISTEMA_LONGO = """Você edita vídeos longos para o YouTube (podcast, aula, vlog, live comentada).
Recebe a transcrição com tempos (segundos do vídeo original) e devolve as DECISÕES DE EDIÇÃO.
Responda APENAS com JSON válido, sem markdown:
{"remover": [{"inicio": a, "fim": b, "motivo": "take repetido"}], "capitulos": [{"inicio": 0, "titulo": "..."}],
 "momentos": [{"inicio": a, "fim": b, "titulo": "..."}], "abertura": [a, b], "titulos": ["...", "...", "..."],
 "descricao": "...", "tags": ["..."], "texto_thumb": "...", "correcoes": [{"de": "...", "para": "..."}], "nao_atendido": []}

MODO "enxugar" (o vídeo inteiro, mais enxuto):
- remover: erros de gravação e enrolação. Frase repetida ou recomeçada: fica a ÚLTIMA tentativa completa, as
  anteriores saem. Também: começo em falso, "corta isso", "vou falar de novo", teste de microfone, conversa com a
  equipe fora do assunto, e o que o usuário pedir para tirar. NÃO remova conteúdo, piadas nem histórias do vídeo.
  Silêncios e vícios ("hum", "é", "tipo") já saem sozinhos: não liste.
  motivo: um de "take repetido", "começo em falso", "desvio de assunto", "bastidor" (conversa de gravação:
  "corta isso", teste de microfone) ou "pedido do usuário". Use os tempos exatos da transcrição.
- capitulos: 3 a 15, o primeiro em 0, título curto (máx. 6 palavras) em cada mudança de assunto,
  com pelo menos 60 s entre eles.
- momentos: vazio.

MODO "melhores" (compilação dos melhores momentos):
- momentos: trechos autocontidos de 30 s a 4 min que fazem sentido sozinhos (começam com contexto, terminam num
  pensamento completo), em ordem cronológica, somando a duração pedida (±15%). titulo = título do capítulo.
- remover: só erros de gravação DENTRO dos momentos. capitulos: vazio (cada momento vira um capítulo).

NOS DOIS MODOS:
- abertura: 8 a 25 s com a fala mais forte ou intrigante (depois do primeiro minuto), frase inteira, que vai
  abrir o vídeo como teaser. null se nada se destacar.
- titulos: 3 opções de título para o YouTube (máx. 70 caracteres), que gerem curiosidade sem mentir.
- descricao: 2 a 4 frases sobre o vídeo, sem capítulos (entram depois) e sem hashtags.
- tags: 8 a 15 palavras-chave.
- texto_thumb: 2 a 4 palavras de impacto para escrever na thumbnail (sem pontuação final), no idioma do vídeo.
- correcoes: erros evidentes da transcrição automática (nome próprio, termo técnico, palavra sem sentido no
  contexto), copiando "de" exatamente como está na transcrição. Vazio se não houver.
- nao_atendido: partes do pedido do usuário que não dá para fazer só cortando o vídeo."""


def decidir_longo(transcricao: dict, modo: str, instrucao: str = "", alvo_min: float | None = None,
                  projeto_id=None) -> EdicaoLonga:
    """Uma chamada com a transcrição inteira (~20 mil tokens por hora de fala, ~US$ 0,05-0,08 no Sonnet)."""
    pedido = f"MODO: {modo}\nDuração do vídeo original: {transcricao['duracao'] / 60:.1f} min\n"
    if modo == "melhores":
        pedido += f"Duração desejada da compilação: {alvo_min:.0f} min\n"
    if instrucao.strip():
        pedido += f"PEDIDO DO USUÁRIO: {instrucao.strip()}\n"
    conteudo = pedido + "\nTRANSCRIÇÃO:\n" + _formatar_transcricao(transcricao)
    return _chamar_json(SISTEMA_LONGO, conteudo, EdicaoLonga, projeto_id, "edição de vídeo longo", max_tokens=16000)


SISTEMA_TITULOS_GAMEPLAY = """Você dá nome aos capítulos de um vídeo longo de gameplay para o YouTube e escreve os metadados.
Recebe a lista de capítulos (partidas ou lances) com o que o jogador falou em cada um.
Responda APENAS com JSON válido, sem markdown:
{"capitulos": ["título do capítulo 1", "..."], "titulos": ["...", "...", "..."], "descricao": "...", "tags": ["..."]}
- capitulos: exatamente um título curto por capítulo, na mesma ordem (máx. 6 palavras, estilo gamer, sem numeração).
  Sem fala no trecho: use o contexto (ex.: "Clutch no fim do round").
- titulos: 3 opções de título para o YouTube (máx. 70 caracteres).
- descricao: 2 a 4 frases, sem capítulos e sem hashtags.
- tags: 8 a 15 palavras-chave.
- texto_thumb: 2 a 4 palavras de impacto para escrever na thumbnail (sem pontuação final)."""


def titulos_gameplay_longo(capitulos: list[dict], jogo_hint: str = "", projeto_id=None) -> TitulosCapitulos:
    """capitulos: [{"inicio": s, "fim": s, "fala": "...", "titulo_sugerido": "..."}] (tempos do vídeo final)."""
    linhas = []
    for k, c in enumerate(capitulos, 1):
        dica = f" | sugestão: {c['titulo_sugerido']}" if c.get("titulo_sugerido") else ""
        linhas.append(f"{k}. {c['inicio'] / 60:.1f}-{c['fim'] / 60:.1f} min{dica} | fala: {(c.get('fala') or '(sem fala)')[:300]}")
    conteudo = (f"{jogo_hint}\nCAPÍTULOS ({len(capitulos)}):\n" + "\n".join(linhas)).strip()
    return _chamar_json(SISTEMA_TITULOS_GAMEPLAY, conteudo, TitulosCapitulos, projeto_id, "títulos do vídeo longo",
                        max_tokens=3000)


SISTEMA_CORRECOES = """Você revisa a transcrição automática da narração de um vídeo de gameplay (o som do jogo atrapalha o
reconhecimento). Responda APENAS com JSON: {"correcoes": [{"de": "meu jeep", "para": "meu Deus"}]}
- Só erros evidentes: palavra que não faz sentido no contexto, nome de jogo/arma/personagem escrito errado.
- "de" copiado exatamente como aparece na transcrição (1 a 4 palavras). Na dúvida, não corrija.
- Lista vazia se estiver tudo certo."""


def corrigir_transcricao(transcricao: dict, projeto_id=None) -> Correcoes:
    """Correções da narração inteira (gameplay longo). Vai só o texto, sem os tempos: para achar palavra
    errada eles não ajudam e custavam ~1/3 dos tokens."""
    texto = "\n".join(s["texto"].strip() for s in transcricao["segmentos"] if s["texto"].strip())
    return _chamar_json(SISTEMA_CORRECOES, "TRANSCRIÇÃO:\n" + texto, Correcoes, projeto_id,
                        "correções da transcrição", max_tokens=4000)
