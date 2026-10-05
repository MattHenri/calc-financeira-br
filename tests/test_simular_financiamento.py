from collections.abc import AsyncIterator
from typing import Any

import pytest
from mcp import Client

from calc_financeira_br import server
from calc_financeira_br.modelos import AVISO_SIMULACAO
from tests.bcb_falso import AGORA

pytestmark = pytest.mark.anyio

PRICE = {
    "valor_financiado": "100000",
    "taxa_juros": "1",
    "unidade_taxa": "a.m.",
    "prazo_meses": 12,
    "sistema": "price",
    "data_contratacao": "2026-10-05",
}


@pytest.fixture
async def cliente_mcp(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Client]:
    monkeypatch.setattr(server, "agora_brasilia", lambda: AGORA)
    async with Client(server.mcp) as cliente:
        yield cliente


async def _chamar(cliente: Client, argumentos: dict[str, Any]) -> dict[str, Any]:
    resultado = await cliente.call_tool("simular_financiamento", argumentos)
    assert not resultado.is_error, resultado.content
    saida: dict[str, Any] | None = resultado.structured_content
    assert saida is not None
    return saida


async def _erro(cliente: Client, argumentos: dict[str, Any]) -> str:
    resultado = await cliente.call_tool("simular_financiamento", argumentos)
    assert resultado.is_error
    return " ".join(getattr(c, "text", "") for c in resultado.content)


async def test_price_basico(cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, PRICE)
    r = saida["resultado"]
    assert r["primeira_prestacao"] == "8884.88"
    assert r["taxa_mensal"] == "1.000000"
    assert r["total_amortizado"] == "100000.00"
    assert r["cet_anual"] == "12.68"
    assert len(r["parcelas"]) == 12
    assert r["parcelas"][0]["data"] == "2026-11-05"
    assert r["efeitos_amortizacoes"] == []
    assert any("Resolução CMN 4.881/2020" in p for p in saida["premissas"])
    assert saida["aviso"] == AVISO_SIMULACAO


async def test_sem_tabela(cliente_mcp: Client) -> None:
    saida = await _chamar(cliente_mcp, {**PRICE, "incluir_tabela": False})
    assert saida["resultado"]["parcelas"] is None


async def test_contratacao_padrao_e_hoje(cliente_mcp: Client) -> None:
    argumentos = {k: v for k, v in PRICE.items() if k != "data_contratacao"}
    saida = await _chamar(cliente_mcp, argumentos)
    assert saida["resultado"]["parcelas"][0]["data"] == "2026-11-05"


async def test_imobiliario_sac_com_extras(cliente_mcp: Client) -> None:
    argumentos = {
        "valor_financiado": "400000",
        "taxa_juros": "11.5",
        "unidade_taxa": "a.a.",
        "prazo_meses": 420,
        "sistema": "sac",
        "data_contratacao": "2026-10-05",
        "tarifas_iniciais": "3000",
        "seguro_percentual_saldo": "0.03",
        "tarifa_mensal": "25",
        "amortizacoes_extras": [
            {"mes": 12, "valor": "20000", "efeito": "prazo"},
            {"mes": 24, "valor": "20000", "efeito": "parcela"},
        ],
        "incluir_tabela": False,
    }
    saida = await _chamar(cliente_mcp, argumentos)
    r = saida["resultado"]
    assert r["prazo_efetivo_meses"] == 400
    assert r["cet_anual"] == "12.12"
    assert [e["mes"] for e in r["efeitos_amortizacoes"]] == [12, 24]
    assert r["efeitos_amortizacoes"][0]["meses_a_menos"] == 20
    assert r["juros_economizados"] == "105264.94"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("sistema", "americano"),
        ("unidade_taxa", "a.d."),
        ("prazo_meses", 0),
        ("prazo_meses", 601),
        ("valor_financiado", "0"),
    ],
)
async def test_entradas_invalidas(cliente_mcp: Client, campo: str, valor: object) -> None:
    await _erro(cliente_mcp, {**PRICE, campo: valor})


async def test_unidade_obrigatoria(cliente_mcp: Client) -> None:
    argumentos = {k: v for k, v in PRICE.items() if k != "unidade_taxa"}
    await _erro(cliente_mcp, argumentos)


async def test_erro_de_regra_vira_mensagem(cliente_mcp: Client) -> None:
    mensagem = await _erro(
        cliente_mcp,
        {**PRICE, "amortizacoes_extras": [{"mes": 13, "valor": "100"}]},
    )
    assert "fora do prazo" in mensagem
