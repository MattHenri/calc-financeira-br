import socket

import pytest
from mcp import Client

from calc_financeira_br import __version__
from calc_financeira_br.server import mcp
from tests.conftest import RedeBloqueadaError


@pytest.mark.anyio
async def test_servidor_responde_e_lista_tools() -> None:
    async with Client(mcp, raise_exceptions=True) as cliente:
        resultado = await cliente.list_tools()
    assert {tool.name for tool in resultado.tools} == {
        "obter_indicadores",
        "simular_renda_fixa",
        "taxa_equivalente",
        "comparar_investimentos",
        "simular_financiamento",
    }


def test_versao_definida() -> None:
    assert __version__ == "0.1.0"


def test_rede_bloqueada_nos_testes() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s,
        pytest.raises(RedeBloqueadaError),
    ):
        s.connect(("203.0.113.1", 443))  # TEST-NET-3, nunca alcançável
