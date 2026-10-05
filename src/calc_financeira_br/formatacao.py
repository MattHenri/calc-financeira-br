"""Formatação de números no padrão brasileiro, para a memória de cálculo."""

from decimal import ROUND_HALF_UP, Decimal


def formatar_decimal(valor: Decimal) -> str:
    """1234.5 -> '1.234,5'."""
    return f"{valor:,f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatar_reais(valor: Decimal) -> str:
    """1234.5 -> 'R$ 1.234,50'."""
    return f"R$ {formatar_decimal(valor.quantize(Decimal('0.01'), ROUND_HALF_UP))}"


def formatar_percentual(valor: Decimal, casas: int = 4) -> str:
    """Percentual já em pontos (13.65 -> '13,65%'), sem zeros à direita desnecessários."""
    arredondado = valor.quantize(Decimal(1).scaleb(-casas), ROUND_HALF_UP).normalize()
    if arredondado == arredondado.to_integral():
        arredondado = arredondado.quantize(Decimal(1))
    return f"{formatar_decimal(arredondado)}%"
