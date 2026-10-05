"""Modelos de saída comuns a todas as tools."""

from decimal import Decimal

from pydantic import BaseModel, Field

AVISO_SIMULACAO = (
    "Simulação com finalidade informativa. Não é recomendação de investimento; "
    "confira as condições com a instituição antes de decidir."
)


class Resposta[T: BaseModel](BaseModel):
    """Envelope de toda tool: resultado, memória de cálculo, premissas e aviso."""

    resultado: T
    memoria_calculo: list[str] = Field(description="Passo a passo de como o resultado foi obtido.")
    premissas: list[str] = Field(description="Premissas e fontes usadas no cálculo.")
    aviso: str = Field(default=AVISO_SIMULACAO)


def formatar_decimal(valor: Decimal) -> str:
    """Formata no padrão brasileiro: 1234.5 -> '1.234,5'."""
    return f"{valor:,f}".replace(",", "_").replace(".", ",").replace("_", ".")
