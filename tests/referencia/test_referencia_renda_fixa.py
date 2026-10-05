"""Casos de referência de renda fixa.

Casos `conferido` batem com uma fonte externa. Casos marcados com
`pendente_validacao` foram calculados por este projeto e ainda precisam ser
conferidos numa calculadora externa; enquanto isso, servem de teste de regressão.
"""

from datetime import date
from decimal import Decimal

import pytest

from calc_financeira_br.calculos.renda_fixa import EntradaPosCDI, fator_cdi, simular_pos_cdi
from calc_financeira_br.regras.carregar import TipoTitulo, convencoes


@pytest.mark.parametrize(
    ("cdi_anual", "cdi_diario_bcb"),
    [
        # Série SGS 4389 (CDI % a.a.) x série SGS 12 (CDI % a.d.), mesma data.
        ("13.65", "0.050788"),  # 01/10/2026
    ],
)
def test_conferido_taxa_diaria_igual_a_serie_12_do_bcb(cdi_anual: str, cdi_diario_bcb: str) -> None:
    taxa, _, _ = fator_cdi(Decimal(100), Decimal(cdi_anual), 0, convencoes())
    assert taxa * 100 == Decimal(cdi_diario_bcb)


CASOS_PENDENTES = [
    # (tipo, valor, %CDI, CDI a.a., aplicação, resgate, bruto, IOF, IR, líquido)
    ("cdb", "10000", "100", "13.65", date(2026, 10, 5), date(2027, 10, 5),
     "11353.46", "0.00", "236.86", "11116.60"),
    ("cdb", "10000", "110", "13.65", date(2026, 10, 5), date(2028, 10, 5),
     "13236.23", "0.00", "485.43", "12750.80"),
    ("cdb", "5000", "100", "13.65", date(2026, 10, 7), date(2026, 10, 21),
     "5022.90", "12.14", "2.42", "5008.34"),
    ("lci", "10000", "90", "13.65", date(2026, 10, 5), date(2027, 4, 5),
     "10573.36", "0.00", "0.00", "10573.36"),
    ("lca", "10000", "95", "13.65", date(2026, 10, 5), date(2027, 10, 5),
     "11281.65", "0.00", "0.00", "11281.65"),
]  # fmt: skip


@pytest.mark.pendente_validacao
@pytest.mark.parametrize(
    ("tipo", "valor", "percentual", "cdi", "aplicacao", "resgate", "bruto", "iof", "ir", "liquido"),
    CASOS_PENDENTES,
)
def test_pendente_valores_finais(  # noqa: PLR0917
    tipo: TipoTitulo,
    valor: str,
    percentual: str,
    cdi: str,
    aplicacao: date,
    resgate: date,
    bruto: str,
    iof: str,
    ir: str,
    liquido: str,
) -> None:
    r = simular_pos_cdi(
        EntradaPosCDI(tipo, Decimal(valor), Decimal(percentual), Decimal(cdi), aplicacao, resgate)
    )
    assert (r.valor_bruto, r.iof, r.ir, r.valor_liquido) == (
        Decimal(bruto),
        Decimal(iof),
        Decimal(ir),
        Decimal(liquido),
    )
