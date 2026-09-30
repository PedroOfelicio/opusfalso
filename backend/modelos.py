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
    num_clips: int = Field(3, ge=1, le=20)
    duracao_min: float = Field(30, ge=5, le=180)
    duracao_max: float = Field(60, ge=5, le=180)
    formato: Literal["9:16", "16:9", "1:1"] = "9:16"
    legenda: Legenda = Field(default_factory=Legenda)
    zoom_em_enfase: bool = False
    remover_silencios: bool = False
    musica_fundo: bool = False
    musica_caminho: str | None = None
    normalizar_audio: bool = True
    titulo_gancho: bool = True
    # Partes do pedido que não existem na lista de ações (mostradas ao usuário)
    nao_atendido: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordem(self):
        if self.duracao_min > self.duracao_max:
            self.duracao_min, self.duracao_max = self.duracao_max, self.duracao_min
        if self.musica_fundo and not self.musica_caminho:
            # Sem arquivo não dá para colocar música: desliga e avisa
            self.musica_fundo = False
            self.nao_atendido.append("música de fundo (nenhum arquivo de música informado)")
        return self


class Emoji(BaseModel):
    palavra: str
    emoji: str


class Corte(BaseModel):
    """Um trecho escolhido pelo Claude."""
    inicio: float = Field(ge=0)
    fim: float = Field(gt=0)
    titulo: str = ""
    nota: int = Field(50, ge=0, le=100)
    justificativa: str = ""
    palavras_enfase: list[str] = Field(default_factory=list)
    emojis: list[Emoji] = Field(default_factory=list)
    pico: float | None = None  # só no gameplay: instante do pico de energia (preenchido pelo código)

    @field_validator("nota", mode="before")
    @classmethod
    def _nota(cls, v):
        return nota_valida(v)

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

    @field_validator("nota", mode="before")
    @classmethod
    def _nota(cls, v):
        return nota_valida(v)


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
    formato: Literal["9:16", "16:9", "1:1"] | None = None
    nao_atendido: list[str] = Field(default_factory=list)

    @field_validator("cor_legenda", mode="before")
    @classmethod
    def _cor(cls, v):
        return normalizar_cor(v) if v else None


class ConfirmacaoFrames(BaseModel):
    """Resposta do refino por imagem (etapa 11)."""
    bom_momento: bool
    nota: int = Field(50, ge=0, le=100)
    titulo: str = ""
    justificativa: str = ""
