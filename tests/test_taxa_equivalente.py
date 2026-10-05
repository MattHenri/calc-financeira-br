from collections.abc import AsyncIterator
from decimal import Decimal, localcontext
from typing import Any

import httpx
import pytest
from mcp import Client

from calc_financeira_br import server
from calc_financeira_br.formatacao import quantizar
from calc_financeira_br.modelos import AVISO_SIMULACAO
from tests.bcb_falso import AGORA, BCBFalso, codigo_da_url

pytestmark = pytest.mark.anyio


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
    resultado = await cliente.call_tool("taxa_equivalente", argumentos)
    assert not resultado.is_error, resultado.content
    saida: dict[str, Any] | None = resultado.structured_content
    assert saida is not None
    return saida


async def _erro(cliente: Client, argumentos: dict[str, Any]) -> str:
    resultado = await cliente.call_tool("taxa_equivalente", argumentos)
    assert resultado.is_error
    return " ".join(getattr(c, "text", "") for c in resultado.content)


async def test_mensal_para_anual(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(
        cliente_mcp,
        {"conversao": "periodo", "taxa": "1", "unidade": "a.m.", "unidade_destino": "a.a."},
    )
    r = saida["resultado"]
    assert r["taxa_equivalente"] == "12.682503"
    assert r["unidade_destino"] == "a.a."
    assert "12,682503% a.a." in saida["memoria_calculo"][0]
    assert saida["aviso"] == AVISO_SIMULACAO
    assert bcb.requisicoes == []


async def test_periodo_exige_destino(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(cliente_mcp, {"conversao": "periodo", "taxa": "1"})
    assert "unidade_destino" in mensagem


async def test_nominal_para_real_com_ipca_do_bc(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {"conversao": "nominal_para_real", "taxa": "13.65"})
    r = saida["resultado"]
    assert r["inflacao"] == "4.22"
    # 1,1365 / 1,0422 − 1 = 9,0481672...%
    assert r["taxa_equivalente"] == "9.048167"
    assert "série SGS 13522" in " ".join(saida["premissas"])


async def test_real_para_nominal_mensal_converte_o_ipca(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(
        cliente_mcp, {"conversao": "real_para_nominal", "taxa": "0.5", "unidade": "a.m."}
    )
    assert "IPCA convertido para a.m." in " ".join(saida["premissas"])
    assert saida["resultado"]["unidade_destino"] == "a.m."


async def test_inflacao_informada_nao_consulta_bc(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(
        cliente_mcp, {"conversao": "nominal_para_real", "taxa": "10", "inflacao": "4"}
    )
    assert saida["resultado"]["taxa_equivalente"] == "5.769231"
    assert bcb.requisicoes == []


async def test_lci_para_cdb_em_percentual_do_cdi(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(
        cliente_mcp,
        {
            "conversao": "isento_para_tributado",
            "taxa": "90",
            "unidade": "%cdi",
            "prazo_dias": 365,
        },
    )
    r = saida["resultado"]
    assert r["aliquota_ir"] == "17.5"
    assert (r["dias_corridos"], r["dias_uteis"]) == (365, 250)
    assert r["taxa_equivalente"] == "107.842149"
    assert {codigo_da_url(req.url) for req in bcb.requisicoes} == {4389}
    premissas = " ".join(saida["premissas"])
    assert "IOF" in premissas
    assert "série SGS 4389" in premissas


async def test_isento_tributado_exige_prazo(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(
        cliente_mcp, {"conversao": "isento_para_tributado", "taxa": "90", "unidade": "%cdi"}
    )
    assert "prazo_dias" in mensagem


async def test_cdi_indisponivel_pede_para_informar(bcb: BCBFalso, cliente_mcp: Client) -> None:
    bcb.manipulador = lambda _: httpx.Response(503)
    mensagem = await _erro(
        cliente_mcp,
        {"conversao": "isento_para_tributado", "taxa": "90", "unidade": "%cdi", "prazo_dias": 90},
    )
    assert "cdi_anual" in mensagem


async def test_nominal_real_rejeita_percentual_do_cdi(bcb: BCBFalso, cliente_mcp: Client) -> None:
    mensagem = await _erro(
        cliente_mcp, {"conversao": "nominal_para_real", "taxa": "100", "unidade": "%cdi"}
    )
    assert "%cdi" in mensagem


async def test_taxa_diaria_alta_nao_quebra(bcb: BCBFalso, cliente_mcp: Client) -> None:
    saida = await _chamar(
        cliente_mcp,
        {"conversao": "periodo", "taxa": "20", "unidade": "a.d.u.", "unidade_destino": "a.a."},
    )
    with localcontext(prec=80):  # 1,2^252 ≈ 9 × 10^19: precisa de mais de 28 dígitos
        esperado = (Decimal("1.2") ** 252 - 1) * 100
    assert Decimal(saida["resultado"]["taxa_equivalente"]) == quantizar(esperado, 6)
