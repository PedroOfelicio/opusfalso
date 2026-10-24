"""
Modelos pydantic: o "contrato" entre o Claude e o código.

O Claude só pode pedir o que está aqui (lista FECHADA de ações). Qualquer campo
ausente assume o valor padrão; valores fora do intervalo são corrigidos.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Nomes de cor comuns em português -> hex (o Claude às vezes responde por nome)
CORES_NOMEADAS = {
    "amarelo": "#FFE600", "amarela": "#FFE600", "verde": "#22FF6B", "azul": "#3B82F6",
    "vermelho": "#FF3B30", "vermelha": "#FF3B30", "branco": "#FFFFFF", "branca": "#FFFFFF",
    "rosa": "#FF4FD8", "roxo": "#A855F7", "roxa": "#A855F7", "laranja": "#FF8A00",
    "ciano": "#22D3EE", "preto": "#000000", "preta": "#000000",
}


def normalizar_cor(valor: str | None, padrao: str = "#FFE600") -> str:
    if not valor:
        return padrao
    v = str(valor).strip().lower()
    if v in CORES_NOMEADAS:
        return CORES_NOMEADAS[v]
    if re.fullmatch(r"#?[0-9a-f]{6}", v):
        return "#" + v.lstrip("#").upper()
    if re.fullmatch(r"#?[0-9a-f]{3}", v):
        v = v.lstrip("#")
        return "#" + "".join(c * 2 for c in v).upper()
    return padrao


# Climas de música da biblioteca local (pastas DADOS/audio/musica/<clima>)
CLIMAS = {
    "energetica": "animada, batida forte (gameplay, conquistas, ritmo rápido)",
    "tensa": "suspense, clutch, momento decisivo",
    "calma": "lo-fi, fundo discreto para conselho ou história",
    "engracada": "cômica, para falhas e risadas",
    "epica": "orquestral/cinemática, vitória, revelação",
}


def clima_valido(v) -> str | None:
    """Aceita "Energética", "épica"... e devolve a chave do clima (ou None)."""
    if not v:
        return None
    s = re.sub(r"[^a-z]", "", str(v).lower().translate(str.maketrans("áâãàéêíóôõúç", "aaaaeeiooouc")))
    return next((c for c in CLIMAS if s.startswith(c[:5])), None)


def hashtags_validas(v) -> list[str]:
    """Aceita "#a #b", ["a", "#b"]... e devolve até 6 hashtags únicas, sempre com #."""
    if isinstance(v, str):
        v = re.split(r"[\s,]+", v)
    saida: list[str] = []
    for h in v or []:
        h = re.sub(r"\W", "", str(h))
        if h and h.lower() not in (s[1:].lower() for s in saida):
            saida.append("#" + h)
    return saida[:6]


def texto_post_valido(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:300]


def nota_valida(v) -> int:
    """Aceita "87", 87.4, None... e devolve inteiro entre 0 e 100."""
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 50


class Legenda(BaseModel):
    ativa: bool = True
    estilo: Literal["simples", "animada"] = "simples"
    preset: str = "opus"
    cor: str | None = None  # None = cor de destaque do próprio preset

    @field_validator("cor", mode="before")
    @classmethod
    def _cor(cls, v):
        return normalizar_cor(v) if v else None


class PlanoEdicao(BaseModel):
    """Plano de edição gerado a partir da instrução em linguagem natural."""
    num_clips: int = Field(3, ge=1, le=100)
    duracao_min: float = Field(30, ge=5, le=180)
    duracao_max: float = Field(60, ge=5, le=180)
    formato: Literal["9:16", "16:9", "1:1"] = "9:16"
    legenda: Legenda = Field(default_factory=Legenda)
    zoom_em_enfase: bool = False
    remover_silencios: bool = False
    musica_fundo: bool = False
    musica_caminho: str | None = None   # None = sorteia da biblioteca local
    musica_clima: str | None = None     # None = o Claude escolhe por clipe
    efeitos_sonoros: bool = False
    normalizar_audio: bool = True
    titulo_gancho: bool = True
    barra_progresso: bool | None = None  # None = o preset decide
    abertura_climax: bool = True        # teaser de 1-2 s do melhor momento antes do clipe
    limpar_voz: bool | None = None      # ruído, zumbido, EQ e compressão; None = ligado na fala, desligado no gameplay
    # Partes do pedido que não existem na lista de ações (mostradas ao usuário)
    nao_atendido: list[str] = Field(default_factory=list)

    @field_validator("musica_clima", mode="before")
    @classmethod
    def _clima(cls, v):
        return clima_valido(v)

    @model_validator(mode="after")
    def _ordem(self):
        if self.duracao_min > self.duracao_max:
            self.duracao_min, self.duracao_max = self.duracao_max, self.duracao_min
        return self


class BRoll(BaseModel):
    """Vídeo de apoio: cobre a tela de inicio a fim (s do vídeo original), buscado no banco com `busca`."""
    inicio: float
    fim: float
    busca: str = Field(min_length=2)

    @model_validator(mode="after")
    def _duracao(self):
        if self.fim - self.inicio < 1.0:
            raise ValueError("b-roll curto demais")
        self.fim = min(self.fim, self.inicio + 4.0)  # mais que 4 s some com quem está falando
        return self


class Reacao(BaseModel):
    """Texto de reação que pula na tela num instante (s do vídeo original): "ESPERA...", "KKKKK"."""
    t: float = Field(ge=0)
    texto: str = Field(min_length=1, max_length=18)


class Emoji(BaseModel):
    palavra: str
    emoji: str


def lista_tolerante(modelo: type[BaseModel], v) -> list:
    """Itens de lista vindos do Claude: aceita nomes alternativos de campo ("word" em vez de
    "palavra") e descarta só o item inválido, em vez de invalidar a resposta inteira
    (o que custaria outra chamada, com imagens e tudo)."""
    apelidos = {"word": "palavra", "text": "palavra", "from": "de", "to": "para"}
    saida = []
    for item in v or []:
        if isinstance(item, dict):
            item = {apelidos.get(k, k): x for k, x in item.items()}
        try:
            saida.append(modelo.model_validate(item))
        except ValueError:
            continue
    return saida


class Correcao(BaseModel):
    """Erro de transcrição que o Claude corrigiu pelo contexto ("meu jeep" -> "meu Deus")."""
    de: str = Field(min_length=1)
    para: str


def intervalos_validos(v) -> list[tuple[float, float]]:
    """Aceita [[a, b], ...] ou [{"inicio": a, "fim": b}, ...]; descarta o que não fizer sentido."""
    saida = []
    for item in v or []:
        try:
            a, b = (item["inicio"], item["fim"]) if isinstance(item, dict) else item
            a, b = float(a), float(b)
        except (TypeError, ValueError, KeyError):
            continue
        if b - a >= 0.3:
            saida.append((round(a, 2), round(b, 2)))
    return saida


class Corte(BaseModel):
    """Um trecho escolhido pelo Claude."""
    inicio: float = Field(ge=0)
    fim: float = Field(gt=0)
    titulo: str = ""
    nota: int = Field(50, ge=0, le=100)
    justificativa: str = ""
    palavras_enfase: list[str] = Field(default_factory=list)
    emojis: list[Emoji] = Field(default_factory=list)
    clima: str | None = None   # clima da música de fundo escolhido para este trecho
    remover: list[tuple[float, float]] = Field(default_factory=list)  # tempo morto/enrolação (s do vídeo)
    correcoes: list[Correcao] = Field(default_factory=list)
    gancho: tuple[float, float] | None = None  # frase mais forte (falado): vira a abertura do clipe
    pico: float | None = None  # só no gameplay: instante do pico de energia (preenchido pelo código)
    legenda_post: str = ""     # texto para a descrição do post (TikTok/Reels/Shorts)
    hashtags: list[str] = Field(default_factory=list)
    direcao: dict = Field(default_factory=dict)  # direção de arte do clipe (validada em direcao.valida)
    broll: list[BRoll] = Field(default_factory=list)  # vídeos de apoio (só fala)
    reacoes: list[Reacao] = Field(default_factory=list)  # textos de reação no pico ("ESPERA...")

    @field_validator("reacoes", mode="before")
    @classmethod
    def _reacoes(cls, v):
        return lista_tolerante(Reacao, v)[:2]

    @field_validator("direcao", mode="before")
    @classmethod
    def _direcao(cls, v):
        return v if isinstance(v, dict) else {}

    @field_validator("broll", mode="before")
    @classmethod
    def _broll(cls, v):
        return lista_tolerante(BRoll, v)[:3]

    @field_validator("legenda_post", mode="before")
    @classmethod
    def _legenda_post(cls, v):
        return texto_post_valido(v)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _hashtags(cls, v):
        return hashtags_validas(v)

    @field_validator("nota", mode="before")
    @classmethod
    def _nota(cls, v):
        return nota_valida(v)

    @field_validator("emojis", mode="before")
    @classmethod
    def _emojis(cls, v):
        return lista_tolerante(Emoji, v)

    @field_validator("correcoes", mode="before")
    @classmethod
    def _correcoes(cls, v):
        return lista_tolerante(Correcao, v)

    @field_validator("clima", mode="before")
    @classmethod
    def _clima(cls, v):
        return clima_valido(v)

    @field_validator("remover", mode="before")
    @classmethod
    def _remover(cls, v):
        return intervalos_validos(v)

    @field_validator("gancho", mode="before")
    @classmethod
    def _gancho(cls, v):
        validos = intervalos_validos([v]) if v else []
        return validos[0] if validos else None

    @model_validator(mode="after")
    def _intervalo(self):
        if self.fim <= self.inicio:
            raise ValueError(f"fim ({self.fim}) deve ser maior que início ({self.inicio})")
        return self


class RespostaCortes(BaseModel):
    cortes: list[Corte]


class EscolhaGameplay(BaseModel):
    """O Claude escolhe entre candidatos pré-selecionados pelos picos de áudio."""
    id: int
    titulo: str = ""
    nota: int = Field(50, ge=0, le=100)
    justificativa: str = ""
    palavras_enfase: list[str] = Field(default_factory=list)
    emojis: list[Emoji] = Field(default_factory=list)
    clima: str | None = None
    inicio: float | None = None
    fim: float | None = None
    remover: list[tuple[float, float]] = Field(default_factory=list)
    correcoes: list[Correcao] = Field(default_factory=list)
    legenda_post: str = ""
    hashtags: list[str] = Field(default_factory=list)
    direcao: dict = Field(default_factory=dict)  # direção de arte do clipe (validada em direcao.valida)
    reacoes: list[Reacao] = Field(default_factory=list)  # textos de reação no pico ("ESPERA...")

    @field_validator("reacoes", mode="before")
    @classmethod
    def _reacoes(cls, v):
        return lista_tolerante(Reacao, v)[:2]

    @field_validator("direcao", mode="before")
    @classmethod
    def _direcao(cls, v):
        return v if isinstance(v, dict) else {}

    @field_validator("remover", mode="before")
    @classmethod
    def _remover(cls, v):
        return intervalos_validos(v)

    @field_validator("legenda_post", mode="before")
    @classmethod
    def _legenda_post(cls, v):
        return texto_post_valido(v)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _hashtags(cls, v):
        return hashtags_validas(v)

    @field_validator("nota", mode="before")
    @classmethod
    def _nota(cls, v):
        return nota_valida(v)

    @field_validator("emojis", mode="before")
    @classmethod
    def _emojis(cls, v):
        return lista_tolerante(Emoji, v)

    @field_validator("correcoes", mode="before")
    @classmethod
    def _correcoes(cls, v):
        return lista_tolerante(Correcao, v)

    @field_validator("clima", mode="before")
    @classmethod
    def _clima(cls, v):
        return clima_valido(v)


TIPOS_QUADRO = ("acao", "reacao", "morto", "menu")


class RevisaoClipe(BaseModel):
    """Revisão fina de um clipe de gameplay: um rótulo por quadro, na ordem da folha.
    O código calcula início, fim e buracos a partir dos rótulos."""
    quadros: list[str] = Field(default_factory=list)

    @field_validator("quadros", mode="before")
    @classmethod
    def _quadros(cls, v):
        saida = []
        for x in v or []:
            x = str(x.get("tipo") if isinstance(x, dict) else x).lower().strip()
            x = x.replace("ç", "c").replace("ã", "a")
            saida.append(x if x in TIPOS_QUADRO else "morto")
        return saida


class RespostaGameplay(BaseModel):
    escolhas: list[EscolhaGameplay]


class AjusteClips(BaseModel):
    """Ajustes pedidos em linguagem natural na tela de Resultados (lista fechada)."""
    duracao_alvo: float | None = Field(None, ge=5, le=180)   # "deixa mais curto" -> segundos
    cor_legenda: str | None = None
    preset: str | None = None
    estilo_legenda: Literal["simples", "animada"] | None = None
    legenda_ativa: bool | None = None
    titulo_ativo: bool | None = None
    novo_titulo: str | None = None
    zoom_em_enfase: bool | None = None
    remover_silencios: bool | None = None
    normalizar_audio: bool | None = None
    efeitos_sonoros: bool | None = None
    limpar_voz: bool | None = None
    formato: Literal["9:16", "16:9", "1:1"] | None = None
    nao_atendido: list[str] = Field(default_factory=list)

    @field_validator("cor_legenda", mode="before")
    @classmethod
    def _cor(cls, v):
        return normalizar_cor(v) if v else None


class Template(BaseModel):
    """Template visual escolhido na criação: preenche as opções do projeto de uma vez."""
    nome: str = Field(min_length=1, max_length=40)
    descricao: str = ""
    modo: Literal["falado", "gameplay"] | None = None  # None = serve para os dois
    preset: str
    cor: str | None = None
    animada: bool = False
    formato: Literal["9:16", "16:9", "1:1"] = "9:16"
    layout: Literal["auto", "rosto", "dupla", "centro", "inteiro", "split", "jogo"] = "auto"
    duracao: tuple[float, float] = (30, 60)
    titulo: bool = True
    barra: bool | None = None
    zoom: bool = False
    remover_silencios: bool = False
    musica: str = ""  # "" | "auto" | clima
    efeitos: bool = False
    abertura: bool = True

    @field_validator("cor", mode="before")
    @classmethod
    def _cor(cls, v):
        return normalizar_cor(v) if v else None

    @field_validator("musica", mode="before")
    @classmethod
    def _musica(cls, v):
        return "auto" if v == "auto" else (clima_valido(v) or "")


# ================================================================ vídeos longos

class Capitulo(BaseModel):
    inicio: float = Field(ge=0)
    titulo: str = Field(min_length=1, max_length=80)


class MomentoLongo(BaseModel):
    """Trecho de uma compilação de melhores momentos (tempos do vídeo original)."""
    inicio: float = Field(ge=0)
    fim: float = Field(gt=0)
    titulo: str = ""

    @model_validator(mode="after")
    def _intervalo(self):
        if self.fim <= self.inicio:
            raise ValueError("fim deve ser maior que início")
        return self


class Remocao(BaseModel):
    """Trecho que o Claude tirou de um vídeo longo, com o motivo (aparece na revisão)."""
    inicio: float = Field(ge=0)
    fim: float = Field(gt=0)
    motivo: str = ""

    @model_validator(mode="after")
    def _intervalo(self):
        if self.fim - self.inicio < 0.3:
            raise ValueError("trecho curto demais")
        return self


def remocoes_tolerantes(v) -> list:
    """Aceita [[a, b], ...] ou [{"inicio": a, "fim": b, "motivo": "..."}, ...]."""
    itens = []
    for item in v or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            item = {"inicio": item[0], "fim": item[1], "motivo": item[2] if len(item) > 2 else ""}
        itens.append(item)
    return lista_tolerante(Remocao, itens)


class EdicaoLonga(BaseModel):
    """Decisões do Claude para um vídeo longo (uma chamada só, com a transcrição inteira)."""
    remover: list[Remocao] = Field(default_factory=list)                # erros de gravação, desvios
    capitulos: list[Capitulo] = Field(default_factory=list)
    momentos: list[MomentoLongo] = Field(default_factory=list)        # só no modo "melhores"
    abertura: tuple[float, float] | None = None                        # teaser no começo
    titulos: list[str] = Field(default_factory=list)
    descricao: str = ""
    tags: list[str] = Field(default_factory=list)
    texto_thumb: str = ""                                               # 2-4 palavras para a thumbnail
    correcoes: list[Correcao] = Field(default_factory=list)            # erros da transcrição automática
    nao_atendido: list[str] = Field(default_factory=list)
    look: str = ""                                                      # cor do vídeo inteiro (direcao.LOOKS)
    broll: list[BRoll] = Field(default_factory=list)                   # vídeos de apoio

    @field_validator("broll", mode="before")
    @classmethod
    def _broll(cls, v):
        return lista_tolerante(BRoll, v)[:30]

    @field_validator("remover", mode="before")
    @classmethod
    def _remover(cls, v):
        return remocoes_tolerantes(v)

    @field_validator("correcoes", mode="before")
    @classmethod
    def _correcoes(cls, v):
        return lista_tolerante(Correcao, v)

    @field_validator("abertura", mode="before")
    @classmethod
    def _abertura(cls, v):
        validos = intervalos_validos([v]) if v else []
        return validos[0] if validos else None

    @field_validator("capitulos", mode="before")
    @classmethod
    def _capitulos(cls, v):
        return lista_tolerante(Capitulo, v)

    @field_validator("momentos", mode="before")
    @classmethod
    def _momentos(cls, v):
        return lista_tolerante(MomentoLongo, v)

    @field_validator("titulos", "tags", "nao_atendido", mode="before")
    @classmethod
    def _textos(cls, v):
        return [str(x).strip() for x in (v or []) if str(x).strip()]


class TitulosCapitulos(BaseModel):
    """Gameplay longo: títulos dos capítulos (por índice) e metadados do YouTube."""
    capitulos: list[str] = Field(default_factory=list)
    titulos: list[str] = Field(default_factory=list)
    descricao: str = ""
    tags: list[str] = Field(default_factory=list)
    texto_thumb: str = ""

    @field_validator("capitulos", "titulos", "tags", mode="before")
    @classmethod
    def _textos(cls, v):
        return [str(x.get("titulo", "") if isinstance(x, dict) else x).strip() for x in (v or [])]


class Correcoes(BaseModel):
    """Só as correções da transcrição (gameplay longo: a narração tem muito erro por causa do som do jogo)."""
    correcoes: list[Correcao] = Field(default_factory=list)

    @field_validator("correcoes", mode="before")
    @classmethod
    def _correcoes(cls, v):
        return lista_tolerante(Correcao, v)
