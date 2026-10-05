"""Casos de referência de financiamento.

A prestação Price e os juros do SAC são conferidos por conta fechada. O CET segue a
fórmula da Resolução CMN 4.881/2020 (os testes provam que ele zera a equação), mas os
valores ainda não foram conferidos num simulador de banco.
"""

from datetime import date
from decimal import Decimal

import pytest

from calc_financeira_br.calculos.financiamento import (
    AmortizacaoExtra,
    EntradaFinanciamento,
    simular_financiamento,
)

CONTRATO = date(2026, 10, 5)


def test_conferido_price_e_sac_por_conta_fechada() -> None:
    price = simular_financiamento(
        EntradaFinanciamento(Decimal(100000), Decimal(1), "a.m.", 12, "price", CONTRATO)
    )
    # 100.000 × 0,01 / (1 − 1,01^−12) = 8.884,8788…
    assert price.parcelas[0].prestacao == Decimal("8884.88")
    sac = simular_financiamento(
        EntradaFinanciamento(Decimal(120000), Decimal(1), "a.m.", 12, "sac", CONTRATO)
    )
    # Juros = 1% × 10.000 × (12 + 11 + … + 1) = 7.800.
    assert sac.total_juros == Decimal(7800)


CASOS_CET = [
    # (descrição, entrada, CET % a.a.)
    (
        "pessoal Price 24x 2,5% a.m., tarifa 500, seguro 15/mês",
        EntradaFinanciamento(
            Decimal(20000),
            Decimal("2.5"),
            "a.m.",
            24,
            "price",
            CONTRATO,
            tarifas_iniciais=Decimal(500),
            seguro_mensal=Decimal(15),
        ),
        # TIR com meses iguais dá 40,15%; com dias corridos / 365 (resolução), 40,12%.
        "40.12",
    ),
    (
        "imobiliário SAC 420x 11,5% a.a., tarifa 3.000, MIP 0,03%, taxa 25/mês",
        EntradaFinanciamento(
            Decimal(400000),
            Decimal("11.5"),
            "a.a.",
            420,
            "sac",
            CONTRATO,
            tarifas_iniciais=Decimal(3000),
            tarifa_mensal=Decimal(25),
            seguro_percentual_saldo=Decimal("0.03"),
            amortizacoes_extras=(AmortizacaoExtra(12, Decimal(20000), "prazo"),),
        ),
        "12.12",
    ),
]


@pytest.mark.pendente_validacao
@pytest.mark.parametrize(("descricao", "entrada", "cet"), CASOS_CET)
def test_pendente_cet(descricao: str, entrada: EntradaFinanciamento, cet: str) -> None:
    assert simular_financiamento(entrada).cet_anual == Decimal(cet), descricao
