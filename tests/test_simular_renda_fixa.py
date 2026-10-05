from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from mcp import Client

from calc_financeira_br import server
from calc_financeira_br.modelos import AVISO_SIMULACAO
from tests.bcb_falso import AGORA, BCBFalso, codigo_da_url, resposta_padrao

pytestmark = pytest.mark.anyio

CDB_UM_ANO = {
    "tipo": "cdb",
    "valor": "10000",
    "percentual_cdi": "100",
    "data_aplicacao": "2026-10-05",
    "data_resgate": "2027-10-05",
}


@pytest.fixture
def bcb(monkeypatch: pytest.MonkeyPatch) -> BCBFalso:
    falso = BCBFalso()
    cliente = falso.cliente()
    monkeypatch.setattr(server, "obter_cliente_bcb", lambda: cliente)
    monkeypatch.setattr(server, "agora_brasilia", lambda: AGORA)
    return falso


@pytest.fixture
async def cliente_mcp() -> AsyncIterator[Client]:
    async with Client(server.mcp) as cliente:
        yield cliente


async def _chamar(cliente: Client, argumentos: dict[str, Any]) -> dict[str, Any]:
    resultado = await cliente.call_tool("simular_renda_fixa", argumentos)
    assert not resultado.is_error, resultado.content
    saida: dict[str, Any] | None = resultado.structured_content
    assert saida is not None
    return saida


async def _erro(cliente: Client, argumentos: dict[str, Any]) -> str:
    resultado = await cliente.call_tool("simular_renda_fixa", argumentos)
    assert resultado.is_error
    return " ".join(getattr(c, "text", "") for c in resultado.content)


async def test_tool_listada(cliente_mcp: Client) -> None:
    nomes = {tool.name for tool in (await cliente_mcp.list_tools()).tools}
    assert "simular_renda_fixa" in nomes


async def test_usa_cdi_e_ipca_do_banco_central(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, CDB_UM_ANO)
    r = saida["resultado"]
    assert r["cdi_anual"] == "13.65"
    assert r["valor_bruto"] == "11353.46"
    assert r["ir"] == "236.86"
    assert r["valor_liquido"] == "11116.60"
    assert r["rentabilidade_real_anual"] is not None
    premissas = " ".join(saida["premissas"])
    assert "série SGS 4389" in premissas
    assert "série SGS 13522" in premissas
    assert saida["aviso"] == AVISO_SIMULACAO
    assert {codigo_da_url(req.url) for req in bcb.requisicoes} == {4389, 13522}


async def test_cdi_e_ipca_informados_nao_consultam_o_bc(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {**CDB_UM_ANO, "cdi_anual": "10", "ipca_anual": "4"})
    assert saida["resultado"]["cdi_anual"] == "10"
    assert "informado pelo usuário" in " ".join(saida["premissas"])
    assert bcb.requisicoes == []


async def test_aplicacao_padrao_e_hoje(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {k: v for k, v in CDB_UM_ANO.items() if k != "data_aplicacao"}
    saida = await _chamar(cliente_mcp, argumentos)
    assert saida["resultado"]["data_aplicacao"] == "2026-10-05"


async def test_resgate_em_feriado(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {**CDB_UM_ANO, "data_resgate": "2026-11-20"})
    assert saida["resultado"]["data_resgate"] == "2026-11-23"
    assert "dia não útil" in saida["memoria_calculo"][0]


async def test_sem_cdi_no_bc_pede_para_informar(bcb: BCBFalso, cliente_mcp: Client) -> None:
    bcb.manipulador = lambda _: httpx.Response(503)
    mensagem = await _erro(cliente_mcp, CDB_UM_ANO)
    assert "cdi_anual" in mensagem


async def test_sem_ipca_simula_sem_rentabilidade_real(bcb: BCBFalso, cliente_mcp: Client) -> None:
    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        if codigo_da_url(requisicao.url) == 13522:
            return httpx.Response(503)
        return resposta_padrao(requisicao)

    bcb.manipulador = manipulador
    saida = await _chamar(cliente_mcp, CDB_UM_ANO)
    assert saida["resultado"]["rentabilidade_real_anual"] is None
    assert "Rentabilidade real não calculada" in " ".join(saida["premissas"])


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("tipo", "debenture"),
        ("valor", "0"),
        ("valor", "-10"),
        ("percentual_cdi", "0"),
        ("data_resgate", "05/10/2027"),
    ],
)
async def test_entradas_invalidas(
    bcb: BCBFalso, cliente_mcp: Client, campo: str, valor: str
) -> None:
    await _erro(cliente_mcp, {**CDB_UM_ANO, campo: valor})


async def test_resgate_antes_da_aplicacao(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(cliente_mcp, {**CDB_UM_ANO, "data_resgate": "2026-10-01"})
    assert "posterior" in mensagem


async def test_data_fora_do_calendario(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(cliente_mcp, {**CDB_UM_ANO, "data_resgate": "2032-01-05"})
    assert "2024 a 2030" in mensagem


async def test_cdb_prefixado_nao_consulta_cdi(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {k: v for k, v in CDB_UM_ANO.items() if k != "percentual_cdi"}
    saida = await _chamar(cliente_mcp, {**argumentos, "taxa_prefixada": "12"})
    r = saida["resultado"]
    assert r["indexador"] == "prefixado"
    assert r["taxa_prefixada"] == "12"
    assert r["cdi_anual"] is None
    assert r["valor_liquido"] == "10981.69"
    assert {codigo_da_url(req.url) for req in bcb.requisicoes} == {13522}


async def test_percentual_e_prefixado_juntos_e_erro(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(cliente_mcp, {**CDB_UM_ANO, "taxa_prefixada": "12"})
    assert "um dos dois" in mensagem


async def test_cdb_sem_taxa_e_erro(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {k: v for k, v in CDB_UM_ANO.items() if k != "percentual_cdi"}
    mensagem = await _erro(cliente_mcp, argumentos)
    assert "percentual_cdi" in mensagem


async def test_tesouro_selic_usa_selic_efetiva(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {
        "tipo": "tesouro_selic",
        "valor": "20000",
        "data_aplicacao": "2026-10-05",
        "data_resgate": "2027-10-05",
    }
    saida = await _chamar(cliente_mcp, argumentos)
    r = saida["resultado"]
    assert r["indexador"] == "selic"
    assert r["selic_efetiva_anual"] == "13.65"
    assert r["custodia"] == "22.64"
    assert "série SGS 1178" in " ".join(saida["premissas"])
    assert {codigo_da_url(req.url) for req in bcb.requisicoes} == {1178, 13522}


async def test_tesouro_selic_com_estoque(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {
        "tipo": "tesouro_selic",
        "valor": "5000",
        "estoque_tesouro_selic": "8000",
        "data_aplicacao": "2026-10-05",
        "data_resgate": "2027-10-05",
    }
    saida = await _chamar(cliente_mcp, argumentos)
    assert saida["resultado"]["custodia"] == "6.66"


async def test_tesouro_selic_nao_aceita_percentual_cdi(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(cliente_mcp, {**CDB_UM_ANO, "tipo": "tesouro_selic"})
    assert "Tesouro Selic não usa percentual_cdi" in mensagem


async def test_poupanca_usa_selic_meta_e_tr(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {
        "tipo": "poupanca",
        "valor": "10000",
        "data_aplicacao": "2026-10-05",
        "data_resgate": "2027-10-05",
    }
    saida = await _chamar(cliente_mcp, argumentos)
    r = saida["resultado"]
    assert r["indexador"] == "poupanca"
    assert r["selic_meta_anual"] == "13.75"
    assert r["tr_mensal"] == "0.1616"
    assert r["ir"] == "0.00"
    assert r["iof"] == "0.00"
    assert {codigo_da_url(req.url) for req in bcb.requisicoes} == {432, 7811, 13522}


async def test_poupanca_com_taxas_informadas(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {
        "tipo": "poupanca",
        "valor": "10000",
        "data_aplicacao": "2026-10-05",
        "data_resgate": "2027-10-05",
        "selic_meta_anual": "8.5",
        "tr_mensal": "0",
        "ipca_anual": "4",
    }
    saida = await _chamar(cliente_mcp, argumentos)
    assert "0,4828%" in " ".join(saida["memoria_calculo"])
    assert bcb.requisicoes == []
