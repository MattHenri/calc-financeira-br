from decimal import Decimal
from typing import get_args

from hypothesis import given
from hypothesis import strategies as st

from calc_financeira_br.calculos.taxas import (
    UnidadePeriodo,
    converter_periodo,
    isento_tributado_anual,
    nominal_para_real,
    real_para_nominal,
)

unidades = st.sampled_from(get_args(UnidadePeriodo))
# Faixa realista em qualquer unidade: de -20% a 50% (até ao dia útil, que vira ~10^44% a.a.).
taxas = st.decimals(min_value=Decimal(-20), max_value=Decimal(50), places=4)
aliquotas = st.sampled_from([Decimal("22.5"), Decimal(20), Decimal("17.5"), Decimal(15)])
TOLERANCIA = Decimal("1e-15")  # pontos percentuais


@given(taxas, unidades, unidades)
def test_ida_e_volta_entre_periodos(
    taxa: Decimal, de: UnidadePeriodo, para: UnidadePeriodo
) -> None:
    ida = converter_periodo(taxa, de, para).taxa
    volta = converter_periodo(ida, para, de).taxa
    assert abs(volta - taxa) < TOLERANCIA


@given(taxas, st.decimals(min_value=Decimal(-20), max_value=Decimal(100), places=4))
def test_fisher_ida_e_volta(taxa: Decimal, inflacao: Decimal) -> None:
    real = nominal_para_real(taxa, inflacao).taxa
    assert abs(real_para_nominal(real, inflacao).taxa - taxa) < TOLERANCIA


@given(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal(50), places=4),
    aliquotas,
    st.integers(min_value=1, max_value=2520),
)
def test_tributado_sempre_maior_que_isento(taxa: Decimal, aliquota: Decimal, dias: int) -> None:
    tributado = isento_tributado_anual(taxa, aliquota, dias, "isento_para_tributado").taxa
    assert tributado > taxa
    volta = isento_tributado_anual(tributado, aliquota, dias, "tributado_para_isento").taxa
    assert abs(volta - taxa) < TOLERANCIA
