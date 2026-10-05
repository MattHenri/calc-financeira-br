from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from calc_financeira_br.dados.bcb import ErroBCB
from tests.bcb_falso import BCBFalso, resposta_padrao

pytestmark = pytest.mark.anyio


async def test_pega_ultimo_valor_ate_hoje_ignorando_datas_futuras() -> None:
    leitura = await BCBFalso().cliente().ultimo_valor("selic")
    assert leitura.data_referencia == date(2026, 10, 5)
    assert leitura.valor == Decimal("13.75")
    assert leitura.serie.codigo == 432


async def test_resposta_fora_de_ordem() -> None:
    leitura = await BCBFalso().cliente().ultimo_valor("cdi")
    assert leitura.data_referencia == date(2026, 10, 1)


async def test_valor_e_decimal_exato_inclusive_negativo() -> None:
    leitura = await BCBFalso().cliente().ultimo_valor("ipca")
    assert isinstance(leitura.valor, Decimal)
    assert leitura.valor == Decimal("-0.32")
    assert str(leitura.valor) == "-0.32"


async def test_consulta_por_intervalo_de_datas() -> None:
    bcb = BCBFalso()
    await bcb.cliente().ultimo_valor("tr")
    (requisicao,) = bcb.requisicoes
    assert requisicao.url.path == "/dados/serie/bcdata.sgs.7811/dados"
    assert requisicao.url.params["formato"] == "json"
    assert requisicao.url.params["dataInicial"] == "07/06/2026"  # 120 dias antes
    assert requisicao.url.params["dataFinal"] == "05/10/2026"


async def test_cache_evita_nova_consulta_dentro_do_ttl() -> None:
    bcb = BCBFalso()
    cliente = bcb.cliente()
    primeira = await cliente.ultimo_valor("selic")
    bcb.agora += timedelta(minutes=59)
    segunda = await cliente.ultimo_valor("selic")
    assert len(bcb.requisicoes) == 1
    assert not primeira.do_cache
    assert segunda.do_cache
    assert segunda.valor == primeira.valor


async def test_cache_expira_depois_do_ttl() -> None:
    bcb = BCBFalso()
    cliente = bcb.cliente()
    await cliente.ultimo_valor("selic")
    bcb.agora += timedelta(hours=1)
    leitura = await cliente.ultimo_valor("selic")
    assert len(bcb.requisicoes) == 2
    assert not leitura.do_cache


async def test_cache_e_separado_por_serie() -> None:
    bcb = BCBFalso()
    cliente = bcb.cliente()
    await cliente.ultimo_valor("selic")
    await cliente.ultimo_valor("cdi")
    assert len(bcb.requisicoes) == 2


async def test_retry_em_erro_do_servidor() -> None:
    falhas = iter([503, 502])

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        status = next(falhas, None)
        return httpx.Response(status) if status else resposta_padrao(requisicao)

    bcb = BCBFalso(manipulador)
    leitura = await bcb.cliente().ultimo_valor("selic")
    assert leitura.valor == Decimal("13.75")
    assert len(bcb.requisicoes) == 3
    assert bcb.esperas == [0.5, 1.0]  # backoff exponencial


async def test_retry_em_timeout() -> None:
    chamadas = 0

    def manipulador(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise httpx.ReadTimeout("demorou", request=requisicao)
        return resposta_padrao(requisicao)

    leitura = await BCBFalso(manipulador).cliente().ultimo_valor("cdi")
    assert leitura.valor == Decimal("13.65")
    assert chamadas == 2


async def test_desiste_depois_das_tentativas() -> None:
    bcb = BCBFalso(lambda _: httpx.Response(503))
    with pytest.raises(ErroBCB, match="indisponível após 3 tentativas"):
        await bcb.cliente().ultimo_valor("selic")
    assert len(bcb.requisicoes) == 3


async def test_404_sem_valores_nao_repete() -> None:
    corpo = {"erro": {"statusCode": 404, "detail": "Value(s) not found"}}
    bcb = BCBFalso(lambda _: httpx.Response(404, json=corpo))
    with pytest.raises(ErroBCB, match="sem valores"):
        await bcb.cliente().ultimo_valor("ipca")
    assert len(bcb.requisicoes) == 1


async def test_pagina_html_com_status_200_e_erro() -> None:
    # A API devolve uma página HTML com status 200 para séries inválidas.
    html = "<html><title>Requisição inválida!</title></html>"
    bcb = BCBFalso(lambda _: httpx.Response(200, text=html))
    with pytest.raises(ErroBCB, match="formato inesperado"):
        await bcb.cliente().ultimo_valor("selic")


async def test_valor_invalido_e_erro() -> None:
    bcb = BCBFalso(lambda _: httpx.Response(200, json=[{"data": "01/10/2026", "valor": "abc"}]))
    with pytest.raises(ErroBCB, match="inválido"):
        await bcb.cliente().ultimo_valor("selic")


async def test_so_datas_futuras_e_erro() -> None:
    bcb = BCBFalso(lambda _: httpx.Response(200, json=[{"data": "04/11/2026", "valor": "13.75"}]))
    with pytest.raises(ErroBCB, match="até a data de hoje"):
        await bcb.cliente().ultimo_valor("selic")


async def test_usa_cache_vencido_quando_api_falha() -> None:
    bcb = BCBFalso()
    cliente = bcb.cliente()
    original = await cliente.ultimo_valor("selic")
    bcb.agora += timedelta(hours=3)
    bcb.manipulador = lambda _: httpx.Response(503)
    leitura = await cliente.ultimo_valor("selic")
    assert leitura.valor == original.valor
    assert leitura.desatualizado
    assert leitura.do_cache
    assert leitura.obtido_em == original.obtido_em
