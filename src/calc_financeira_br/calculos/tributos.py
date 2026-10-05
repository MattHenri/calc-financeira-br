"""Alíquotas de IR e IOF de renda fixa, lidas das regras em `regras/tributacao.toml`."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from calc_financeira_br.regras.carregar import RegrasTributacao, TipoTitulo, regras_tributacao

ZERO = Decimal(0)
DIAS_IOF = 30


@dataclass(frozen=True)
class AliquotaIR:
    regime: str
    aliquota: Decimal
    """Percentual (22.5 = 22,5%). Zero quando isento."""


def aliquota_iof(
    tipo: TipoTitulo, dias_corridos: int, regras: RegrasTributacao | None = None
) -> Decimal:
    """Percentual do rendimento devido de IOF (96 = 96%)."""
    if dias_corridos < 1:
        raise ValueError("o prazo deve ter pelo menos 1 dia corrido")
    regras = regras or regras_tributacao()
    if tipo not in regras.iof.tipos or dias_corridos >= DIAS_IOF:
        return ZERO
    return regras.iof.tabela[dias_corridos - 1]


def aliquota_ir(
    tipo: TipoTitulo,
    dias_corridos: int,
    data_aplicacao: date,
    regras: RegrasTributacao | None = None,
) -> AliquotaIR:
    if dias_corridos < 1:
        raise ValueError("o prazo deve ter pelo menos 1 dia corrido")
    regras = regras or regras_tributacao()
    regra = next((r for r in regras.ir.regras if r.vale_para(tipo, data_aplicacao)), None)
    if regra is None:
        raise ValueError(
            f"nenhuma regra de IR para {tipo.upper()} aplicado em {data_aplicacao:%d/%m/%Y}"
        )
    if regra.regime == "isento":
        return AliquotaIR("isento", ZERO)
    for faixa in regras.ir.faixas:
        if faixa.ate_dias is None or dias_corridos <= faixa.ate_dias:
            return AliquotaIR("regressivo", faixa.aliquota)
    raise AssertionError("a última faixa de IR não tem limite")  # garantido pela validação
