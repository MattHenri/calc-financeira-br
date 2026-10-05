"""Testes contra a API real do Banco Central. Só rodam com `pytest --rede`."""

from datetime import timedelta
from decimal import Decimal
from typing import get_args

import pytest

from calc_financeira_br.dados.bcb import ClienteBCB, NomeIndicador, agora_brasilia

pytestmark = [pytest.mark.rede, pytest.mark.anyio]

# Faixas largas só para detectar série errada ou formato quebrado, não para validar valores.
FAIXAS: dict[NomeIndicador, tuple[Decimal, Decimal]] = {
    "selic": (Decimal(1), Decimal(40)),
    "cdi": (Decimal(1), Decimal(40)),
    "ipca": (Decimal(-3), Decimal(5)),
    "ipca_12m": (Decimal(-5), Decimal(30)),
    "tr": (Decimal(0), Decimal(2)),
}


@pytest.mark.parametrize("indicador", get_args(NomeIndicador))
async def test_api_real(indicador: NomeIndicador) -> None:
    leitura = await ClienteBCB().ultimo_valor(indicador)
    minimo, maximo = FAIXAS[indicador]
    assert minimo <= leitura.valor <= maximo
    hoje = agora_brasilia().date()
    assert hoje - timedelta(days=100) <= leitura.data_referencia <= hoje
