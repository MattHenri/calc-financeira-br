from datetime import date
from decimal import Decimal
from typing import get_args

from hypothesis import example, given, settings
from hypothesis import strategies as st

from calc_financeira_br.calculos.financiamento import (
    AmortizacaoExtra,
    EntradaFinanciamento,
    Sistema,
    simular_financiamento,
)

valores = st.decimals(min_value=Decimal(1000), max_value=Decimal(2_000_000), places=2)
taxas = st.decimals(min_value=Decimal(0), max_value=Decimal(5), places=4)
prazos = st.integers(min_value=1, max_value=120)


@settings(max_examples=80, deadline=None)
@example(Decimal("1000.00"), Decimal("0.0066"), 66)
@given(valores, taxas, prazos)
def test_sac_e_price_amortizam_o_mesmo_total(valor: Decimal, taxa: Decimal, prazo: int) -> None:
    resultados = {
        sistema: simular_financiamento(
            EntradaFinanciamento(valor, taxa, "a.m.", prazo, sistema, date(2026, 10, 5))
        )
        for sistema in ("sac", "price")
    }
    for r in resultados.values():
        assert r.total_amortizado == valor
        assert r.parcelas[-1].saldo_final == 0
        assert len(r.parcelas) == prazo
        assert all(p.juros >= 0 and p.amortizacao >= 0 for p in r.parcelas)
    # SAC paga menos juros que Price, salvo o arredondamento em centavos de cada mês
    # (com juros de poucos centavos por mês, a ordem pode inverter por 1 centavo).
    tolerancia = Decimal("0.01") * prazo
    assert resultados["sac"].total_juros <= resultados["price"].total_juros + tolerancia


@st.composite
def extras(draw: st.DrawFn, prazo: int) -> tuple[AmortizacaoExtra, ...]:
    meses = draw(st.lists(st.integers(1, prazo), unique=True, max_size=4))
    return tuple(
        AmortizacaoExtra(
            mes,
            draw(st.decimals(min_value=Decimal(1), max_value=Decimal(50_000), places=2)),
            draw(st.sampled_from(["prazo", "parcela"])),
        )
        for mes in meses
    )


@settings(max_examples=80, deadline=None)
@given(valores, taxas, st.integers(min_value=2, max_value=60), st.data())
def test_extras_nunca_aumentam_juros_nem_prazo(
    valor: Decimal, taxa: Decimal, prazo: int, dados: st.DataObject
) -> None:
    sistema: Sistema = dados.draw(st.sampled_from(get_args(Sistema)))
    lista = dados.draw(extras(prazo))
    r = simular_financiamento(
        EntradaFinanciamento(
            valor, taxa, "a.m.", prazo, sistema, date(2026, 10, 5), amortizacoes_extras=lista
        )
    )
    assert r.total_amortizado == valor
    assert r.parcelas[-1].saldo_final == 0
    assert r.prazo_efetivo_meses <= prazo
    assert r.total_juros <= r.juros_sem_extras
