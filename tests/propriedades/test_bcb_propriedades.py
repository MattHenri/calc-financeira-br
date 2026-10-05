from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from calc_financeira_br.dados.bcb import ErroBCB, ultimo_ponto_ate

datas = st.dates(min_value=date(2000, 1, 1), max_value=date(2040, 12, 31))
valores = st.decimals(min_value=-100, max_value=100, places=4, allow_nan=False)
pontos = st.lists(st.tuples(datas, valores), max_size=50)


@given(pontos, datas)
def test_ultimo_ponto_e_o_mais_recente_ate_hoje(
    lista: list[tuple[date, Decimal]], hoje: date
) -> None:
    validos = [p for p in lista if p[0] <= hoje]
    if not validos:
        with pytest.raises(ErroBCB):
            ultimo_ponto_ate(lista, hoje)
        return
    data_escolhida, valor = ultimo_ponto_ate(lista, hoje)
    assert data_escolhida <= hoje
    assert data_escolhida == max(p[0] for p in validos)
    assert (data_escolhida, valor) in lista
