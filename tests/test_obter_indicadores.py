from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from mcp import Client

from calc_financeira_br import server
from calc_financeira_br.modelos import AVISO_SIMULACAO
from tests.bcb_falso import BCBFalso, codigo_da_url, resposta_padrao

pytestmark = pytest.mark.anyio


@pytest.fixture
def bcb(monkeypatch: pytest.MonkeyPatch) -> BCBFalso:
    falso = BCBFalso()
    cliente = falso.cliente()
    monkeypatch.setattr(server, "obter_cliente_bcb", lambda: cliente)
    return falso


@pytest.fixture
async def cliente_mcp() -> AsyncIterator[Client]:
    async with Client(server.mcp, raise_exceptions=True) as cliente:
        yield cliente


async def _chamar(cliente: Client, argumentos: dict[str, Any]) -> dict[str, Any]:
    resultado = await cliente.call_tool("obter_indicadores", argumentos)
    assert not resultado.is_error, resultado.content
    saida: dict[str, Any] | None = resultado.structured_content
    assert saida is not None
    return saida


async def test_tool_listada_com_enum_de_indicadores(cliente_mcp: Client) -> None:
    tools = {tool.name: tool for tool in (await cliente_mcp.list_tools()).tools}
    assert "obter_indicadores" in tools
    schema = str(tools["obter_indicadores"].input_schema)
    for nome in ("selic", "selic_efetiva", "cdi", "ipca", "ipca_12m", "tr"):
        assert f"'{nome}'" in schema


async def test_consulta_indicadores_pedidos(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {"indicadores": ["selic", "cdi"]})
    indicadores = saida["resultado"]["indicadores"]
    assert [i["indicador"] for i in indicadores] == ["selic", "cdi"]
    selic, cdi = indicadores
    assert selic["valor"] == "13.75"  # Decimal serializado como texto, sem perda
    assert selic["unidade"] == "% a.a."
    assert selic["data_referencia"] == "2026-10-05"
    assert selic["serie_sgs"] == 432
    assert "bcdata.sgs.432" in selic["fonte"]
    assert cdi["valor"] == "13.65"
    assert saida["resultado"]["indisponiveis"] == []
    assert len(bcb.requisicoes) == 2


async def test_sem_argumento_consulta_todos(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {})
    nomes = [i["indicador"] for i in saida["resultado"]["indicadores"]]
    assert nomes == ["selic", "selic_efetiva", "cdi", "ipca", "ipca_12m", "tr"]


async def test_repetidos_consultados_uma_vez(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {"indicadores": ["cdi", "cdi"]})
    assert len(saida["resultado"]["indicadores"]) == 1
    assert len(bcb.requisicoes) == 1


async def test_memoria_premissas_e_aviso(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {"indicadores": ["selic"]})
    (passo,) = saida["memoria_calculo"]
    assert "série SGS 432" in passo
    assert "13,75 % a.a. em 05/10/2026" in passo
    premissas = " ".join(saida["premissas"])
    assert "Banco Central" in premissas
    assert "Meta da taxa Selic" in premissas
    assert "data futura" in premissas
    assert saida["aviso"] == AVISO_SIMULACAO


async def test_falha_parcial_vira_indisponivel(bcb: BCBFalso, cliente_mcp: Client) -> None:
    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        if codigo_da_url(requisicao.url) == 433:
            return httpx.Response(503)
        return resposta_padrao(requisicao)

    bcb.manipulador = manipulador
    saida = await _chamar(cliente_mcp, {"indicadores": ["ipca", "selic"]})
    assert [i["indicador"] for i in saida["resultado"]["indicadores"]] == ["selic"]
    (falha,) = saida["resultado"]["indisponiveis"]
    assert falha["indicador"] == "ipca"
    assert "indisponível" in falha["motivo"]
    assert any("IPCA mensal: indisponível" in passo for passo in saida["memoria_calculo"])


async def test_indicador_invalido_e_rejeitado(bcb: BCBFalso) -> None:
    async with Client(server.mcp) as cliente:
        resultado = await cliente.call_tool("obter_indicadores", {"indicadores": ["dolar"]})
    assert resultado.is_error
    assert bcb.requisicoes == []


async def test_lista_vazia_e_rejeitada(bcb: BCBFalso) -> None:
    async with Client(server.mcp) as cliente:
        resultado = await cliente.call_tool("obter_indicadores", {"indicadores": []})
    assert resultado.is_error
