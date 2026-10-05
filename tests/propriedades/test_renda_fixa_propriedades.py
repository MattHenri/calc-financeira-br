from datetime import date, timedelta
from decimal import Decimal
from typing import get_args

from hypothesis import given, settings
from hypothesis import strategies as st

from calc_financeira_br.calculos.renda_fixa import EntradaPosCDI, ResultadoPosCDI, simular_pos_cdi
from calc_financeira_br.regras.carregar import TipoTitulo

tipos = st.sampled_from(get_args(TipoTitulo))
valores = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(10_000_000), places=2)
percentuais = st.decimals(min_value=Decimal(1), max_value=Decimal(200), places=2)
cdis = st.decimals(min_value=Decimal(0), max_value=Decimal(30), places=2)
aplicacoes = st.dates(min_value=date(2024, 1, 1), max_value=date(2027, 12, 31))
prazos = st.integers(min_value=1, max_value=1000)


@st.composite
def entradas(draw: st.DrawFn) -> EntradaPosCDI:
    aplicacao = draw(aplicacoes)
    return EntradaPosCDI(
        tipo=draw(tipos),
        valor=draw(valores),
        percentual_cdi=draw(percentuais),
        cdi_anual=draw(cdis),
        data_aplicacao=aplicacao,
        data_resgate=aplicacao + timedelta(days=draw(prazos)),
    )


def _simular(entrada: EntradaPosCDI) -> ResultadoPosCDI | None:
    try:
        return simular_pos_cdi(entrada)
    except ValueError:
        return None  # prazo nulo depois do ajuste para dias úteis


@settings(max_examples=200, deadline=None)
@given(entradas())
def test_liquido_entre_aplicado_e_bruto(entrada: EntradaPosCDI) -> None:
    r = _simular(entrada)
    if r is None:
        return
    assert r.iof >= 0
    assert r.ir >= 0
    assert r.valor_liquido <= r.valor_bruto
    assert r.valor_liquido >= entrada.valor
    assert r.valor_liquido == r.valor_bruto - r.iof - r.ir


@settings(max_examples=100, deadline=None)
@given(entradas(), st.decimals(min_value=Decimal("0.01"), max_value=Decimal(50), places=2))
def test_mais_cdi_nunca_rende_menos(entrada: EntradaPosCDI, extra: Decimal) -> None:
    menor = _simular(entrada)
    if menor is None:
        return
    maior = simular_pos_cdi(
        EntradaPosCDI(
            tipo=entrada.tipo,
            valor=entrada.valor,
            percentual_cdi=entrada.percentual_cdi + extra,
            cdi_anual=entrada.cdi_anual,
            data_aplicacao=entrada.data_aplicacao,
            data_resgate=entrada.data_resgate,
        )
    )
    assert maior.valor_liquido >= menor.valor_liquido
