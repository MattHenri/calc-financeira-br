"""API do Banco Central simulada para os testes (sem rede)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from calc_financeira_br.dados.bcb import FUSO_BRASIL, ClienteBCB

AGORA = datetime(2026, 10, 5, 14, 30, tzinfo=FUSO_BRASIL)

# Recortes reais da API em 05/10/2026, fora de ordem e com datas futuras como ela devolve.
RESPOSTAS: dict[int, list[dict[str, str]]] = {
    432: [
        {"data": "04/11/2026", "valor": "13.75"},
        {"data": "02/10/2026", "valor": "13.75"},
        {"data": "05/10/2026", "valor": "13.75"},
    ],
    4389: [
        {"data": "01/10/2026", "valor": "13.65"},
        {"data": "30/09/2026", "valor": "13.65"},
    ],
    433: [
        {"data": "01/07/2026", "valor": "0.07"},
        {"data": "01/08/2026", "valor": "-0.32"},
    ],
    13522: [
        {"data": "01/07/2026", "valor": "4.44"},
        {"data": "01/08/2026", "valor": "4.22"},
    ],
    7811: [
        {"data": "01/09/2026", "valor": "0.1690"},
        {"data": "01/10/2026", "valor": "0.1616"},
    ],
}


def codigo_da_url(url: httpx.URL) -> int:
    return int(url.path.split("bcdata.sgs.")[1].split("/")[0])


def resposta_padrao(requisicao: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=RESPOSTAS[codigo_da_url(requisicao.url)])


@dataclass
class BCBFalso:
    """Transporte httpx que registra as requisições e responde com `manipulador`."""

    manipulador: Callable[[httpx.Request], httpx.Response] = resposta_padrao
    requisicoes: list[httpx.Request] = field(default_factory=list)
    agora: datetime = AGORA
    esperas: list[float] = field(default_factory=list)

    def _responder(self, requisicao: httpx.Request) -> httpx.Response:
        self.requisicoes.append(requisicao)
        return self.manipulador(requisicao)

    async def _dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)

    def cliente(self, **kwargs: object) -> ClienteBCB:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self._responder))
        return ClienteBCB(
            http,
            relogio=lambda: self.agora,
            dormir=self._dormir,
            **kwargs,  # type: ignore[arg-type]
        )
