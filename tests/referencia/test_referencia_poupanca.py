"""Poupança conferida com o Banco Central.

A série SGS 195 publica o rendimento da poupança (depósitos a partir de 04/05/2012)
para cada data de início de período; a série SGS 226, a TR do mesmo período; a 432,
a meta da Selic. Valores consultados em 05/10/2026.
"""

from decimal import Decimal

import pytest

from calc_financeira_br.calculos.renda_fixa import taxa_mensal_poupanca
from calc_financeira_br.regras.carregar import regras_poupanca


@pytest.mark.parametrize(
    ("inicio", "selic_meta", "tr", "rendimento_bcb"),
    [
        ("01/08/2026", "14.25", "0.1693", "0.6701"),
        ("03/08/2026", "14.25", "0.1729", "0.6738"),
        ("08/08/2026", "14.00", "0.1453", "0.6460"),
        ("04/01/2021", "2.00", "0.0000", "0.1159"),
        ("01/06/2021", "3.50", "0.0000", "0.2019"),
    ],
)
def test_conferido_rendimento_igual_a_serie_195_do_bcb(
    inicio: str, selic_meta: str, tr: str, rendimento_bcb: str
) -> None:
    taxa, _ = taxa_mensal_poupanca(Decimal(selic_meta), Decimal(tr), regras_poupanca())
    assert taxa == Decimal(rendimento_bcb), inicio
