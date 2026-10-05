from collections.abc import AsyncIterator
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
import pytest
from mcp import Client

from calc_financeira_br import server
from calc_financeira_br.calculos.comparacao import Candidato, ranquear
from calc_financeira_br.modelos import AVISO_SIMULACAO
from tests.bcb_falso import AGORA, BCBFalso, codigo_da_url, resposta_padrao

pytestmark = pytest.mark.anyio

BASE = {"valor": "10000", "data_aplicacao": "2026-10-05", "data_resgate": "2027-10-05"}


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
    resultado = await cliente.call_tool("comparar_investimentos", argumentos)
    assert not resultado.is_error, resultado.content
    saida: dict[str, Any] | None = resultado.structured_content
    assert saida is not None
    return saida


async def _erro(cliente: Client, argumentos: dict[str, Any]) -> str:
    resultado = await cliente.call_tool("comparar_investimentos", argumentos)
    assert resultado.is_error
    return " ".join(getattr(c, "text", "") for c in resultado.content)


# ------------------------------------------------------------------ ranking (puro)


def test_ranking_ordena_e_calcula_diferencas() -> None:
    posicoes, memoria = ranquear(
        [
            Candidato("A", Decimal("11000.00"), Decimal(10)),
            Candidato("B", Decimal("11500.00"), Decimal(15)),
            Candidato("C", Decimal("10800.00"), Decimal(8)),
        ]
    )
    assert [p.indice for p in posicoes] == [1, 0, 2]
    assert [p.posicao for p in posicoes] == [1, 2, 3]
    assert [p.diferenca_para_o_primeiro for p in posicoes] == [0, 500, 700]
    assert [p.diferenca_anual_pp for p in posicoes] == [0, 5, 7]
    assert "R$ 500,00 a menos que B" in memoria[2]


def test_empate_divide_a_posicao() -> None:
    posicoes, memoria = ranquear(
        [
            Candidato("A", Decimal(100), Decimal(1)),
            Candidato("B", Decimal(100), Decimal(1)),
            Candidato("C", Decimal(90), Decimal(0)),
        ]
    )
    assert [p.posicao for p in posicoes] == [1, 1, 3]
    assert "empatado com A" in memoria[2]


def test_ranking_vazio_e_erro() -> None:
    with pytest.raises(ValueError, match="pelo menos uma"):
        ranquear([])


# ------------------------------------------------------------------------ tool MCP


async def test_compara_lci_cdb_tesouro_e_poupanca(bcb: BCBFalso, cliente_mcp: Client) -> None:
    opcoes = [
        {"tipo": "poupanca"},
        {"tipo": "cdb", "percentual_cdi": "100"},
        {"tipo": "lci", "percentual_cdi": "90"},
        {"tipo": "tesouro_selic"},
    ]
    saida = await _chamar(cliente_mcp, {**BASE, "opcoes": opcoes})
    ranking = saida["resultado"]["ranking"]
    nomes = [item["nome"] for item in ranking]
    # LCI a 90% isenta bate o CDB a 100% com IR de 17,5% em 1 ano (equivale a ~107,8%).
    assert nomes == ["LCI 90% do CDI", "CDB 100% do CDI", "Tesouro Selic", "Poupança"]
    assert saida["resultado"]["melhor"] == "LCI 90% do CDI"
    assert ranking[0]["diferenca_para_o_primeiro"] == "0.00"
    for anterior, atual in pairwise(ranking):
        assert Decimal(atual["simulacao"]["valor_liquido"]) <= Decimal(
            anterior["simulacao"]["valor_liquido"]
        )
        assert Decimal(atual["diferenca_para_o_primeiro"]) == Decimal(
            ranking[0]["simulacao"]["valor_liquido"]
        ) - Decimal(atual["simulacao"]["valor_liquido"])
    assert saida["aviso"] == AVISO_SIMULACAO


async def test_cada_indice_e_buscado_uma_vez(bcb: BCBFalso, cliente_mcp: Client) -> None:
    opcoes = [
        {"tipo": "cdb", "percentual_cdi": "100"},
        {"tipo": "cdb", "percentual_cdi": "110"},
        {"tipo": "lca", "percentual_cdi": "95"},
    ]
    saida = await _chamar(cliente_mcp, {**BASE, "opcoes": opcoes})
    codigos = [codigo_da_url(req.url) for req in bcb.requisicoes]
    assert sorted(codigos) == [4389, 13522]
    premissas = saida["premissas"]
    assert sum("série SGS 4389" in p for p in premissas) == 1


async def test_memoria_tem_resumo_de_cada_opcao_e_o_ranking(
    bcb: BCBFalso, cliente_mcp: Client
) -> None:
    opcoes = [
        {"tipo": "cdb", "percentual_cdi": "100", "nome": "Banco X"},
        {"tipo": "cdb", "taxa_prefixada": "12", "nome": "Banco Y"},
    ]
    saida = await _chamar(cliente_mcp, {**BASE, "opcoes": opcoes})
    memoria = saida["memoria_calculo"]
    assert memoria[0].startswith("Banco X: bruto R$ 11.353,46")
    assert memoria[1].startswith("Banco Y: bruto R$ 11.189,93")
    assert memoria[2].startswith("Ranking")
    assert memoria[3].startswith("1º Banco X")


async def test_datas_efetivas_diferentes_viram_premissa(bcb: BCBFalso, cliente_mcp: Client) -> None:
    argumentos = {**BASE, "data_resgate": "2027-11-20"}  # sábado
    opcoes = [{"tipo": "poupanca"}, {"tipo": "cdb", "percentual_cdi": "100"}]
    saida = await _chamar(cliente_mcp, {**argumentos, "opcoes": opcoes})
    assert any("datas de resgate efetivas diferem" in p for p in saida["premissas"])


async def test_erro_indica_a_opcao(bcb: BCBFalso, cliente_mcp: Client) -> None:
    opcoes = [{"tipo": "cdb", "percentual_cdi": "100"}, {"tipo": "lci"}]
    mensagem = await _erro(cliente_mcp, {**BASE, "opcoes": opcoes})
    assert "Opção 2 (LCI)" in mensagem


async def test_cdi_indisponivel(bcb: BCBFalso, cliente_mcp: Client) -> None:
    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        if codigo_da_url(requisicao.url) == 4389:
            return httpx.Response(503)
        return resposta_padrao(requisicao)

    bcb.manipulador = manipulador
    opcoes = [{"tipo": "poupanca"}, {"tipo": "cdb", "percentual_cdi": "100"}]
    mensagem = await _erro(cliente_mcp, {**BASE, "opcoes": opcoes})
    assert "cdi_anual" in mensagem


@pytest.mark.parametrize("quantidade", [1, 11])
async def test_quantidade_de_opcoes(bcb: BCBFalso, cliente_mcp: Client, quantidade: int) -> None:
    opcoes = [{"tipo": "poupanca"}] * quantidade
    await _erro(cliente_mcp, {**BASE, "opcoes": opcoes})
