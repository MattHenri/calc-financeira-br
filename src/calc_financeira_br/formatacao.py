"""Formatação de números no padrão brasileiro, para a memória de cálculo."""

from decimal import ROUND_HALF_UP, Decimal, localcontext


def quantizar(valor: Decimal, casas: int, modo: str = ROUND_HALF_UP) -> Decimal:
    """Arredonda em `casas` decimais com precisão suficiente para qualquer magnitude."""
    digitos = max(valor.adjusted(), 0) + casas + 5
    with localcontext(prec=max(28, digitos)):
        return valor.quantize(Decimal(1).scaleb(-casas), modo)


def formatar_decimal(valor: Decimal) -> str:
    """1234.5 -> '1.234,5'."""
    return f"{valor:,f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatar_reais(valor: Decimal) -> str:
    """1234.5 -> 'R$ 1.234,50'."""
    return f"R$ {formatar_decimal(quantizar(valor, 2))}"


def formatar_percentual(valor: Decimal, casas: int = 4) -> str:
    """Percentual já em pontos (13.65 -> '13,65%'), sem zeros à direita desnecessários."""
    arredondado = quantizar(valor, casas)
    if arredondado == arredondado.to_integral_value():
        arredondado = arredondado.quantize(Decimal(1))
    else:
        arredondado = Decimal(str(arredondado).rstrip("0"))
    return f"{formatar_decimal(arredondado)}%"
