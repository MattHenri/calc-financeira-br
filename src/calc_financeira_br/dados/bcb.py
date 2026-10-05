"""Cliente da API de séries temporais (SGS) do Banco Central, com retry e cache.

Documentação da API: https://dadosabertos.bcb.gov.br/dataset/sgs
Formato da resposta: [{"data": "dd/mm/aaaa", "valor": "13.75"}, ...]
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

URL_BASE_SGS = "https://api.bcb.gov.br/dados/serie"
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

NomeIndicador = Literal["selic", "cdi", "ipca", "ipca_12m", "tr"]


@dataclass(frozen=True)
class SerieSGS:
    codigo: int
    nome: str
    unidade: str
    descricao: str


SERIES: dict[NomeIndicador, SerieSGS] = {
    "selic": SerieSGS(432, "Selic meta", "% a.a.", "Meta da taxa Selic definida pelo Copom"),
    "cdi": SerieSGS(4389, "CDI", "% a.a.", "Taxa DI anualizada na base 252 dias úteis"),
    "ipca": SerieSGS(433, "IPCA mensal", "% a.m.", "Variação mensal do IPCA"),
    "ipca_12m": SerieSGS(13522, "IPCA 12 meses", "%", "IPCA acumulado nos últimos 12 meses"),
    "tr": SerieSGS(7811, "TR mensal", "% a.m.", "TR do período iniciado no 1º dia do mês"),
}


class ErroBCB(Exception):
    """A API do Banco Central falhou ou devolveu dados inválidos."""


@dataclass(frozen=True)
class Leitura:
    """Último valor de uma série, com a origem do dado."""

    serie: SerieSGS
    data_referencia: date
    valor: Decimal
    obtido_em: datetime
    url: str
    do_cache: bool = False
    desatualizado: bool = False


class _PontoSGS(BaseModel):
    data: str
    valor: str


_LISTA_PONTOS = TypeAdapter(list[_PontoSGS])


def agora_brasilia() -> datetime:
    return datetime.now(FUSO_BRASIL)


def _formatar_data_sgs(dia: date) -> str:
    return dia.strftime("%d/%m/%Y")


def _ler_data_sgs(texto: str) -> date:
    dia, mes, ano = (int(parte) for parte in texto.split("/"))
    return date(ano, mes, dia)


def ultimo_ponto_ate(pontos: list[tuple[date, Decimal]], hoje: date) -> tuple[date, Decimal]:
    """Ponto mais recente com data até `hoje`.

    A API não garante a ordem dos pontos, e algumas séries (como a Selic meta)
    já trazem datas futuras, até a próxima reunião do Copom.
    """
    validos = [ponto for ponto in pontos if ponto[0] <= hoje]
    if not validos:
        raise ErroBCB("a série não tem valores até a data de hoje")
    return max(validos, key=lambda ponto: ponto[0])


def interpretar_resposta(conteudo: bytes) -> list[tuple[date, Decimal]]:
    try:
        pontos = _LISTA_PONTOS.validate_json(conteudo)
    except ValidationError as erro:
        raise ErroBCB("resposta do Banco Central em formato inesperado") from erro
    try:
        return [(_ler_data_sgs(p.data), Decimal(p.valor)) for p in pontos]
    except (ValueError, InvalidOperation) as erro:
        raise ErroBCB("data ou valor inválido na resposta do Banco Central") from erro


class ClienteBCB:
    """Busca o último valor de cada indicador, com retry e cache em memória.

    Se a API falhar e houver um valor em cache, mesmo vencido, ele é devolvido
    marcado como desatualizado.
    """

    def __init__(  # noqa: PLR0913
        self,
        http: httpx.AsyncClient | None = None,
        *,
        ttl: timedelta = timedelta(hours=1),
        tentativas: int = 3,
        espera_base: float = 0.5,
        janela_dias: int = 120,
        relogio: Callable[[], datetime] = agora_brasilia,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self.ttl = ttl
        self._tentativas = tentativas
        self._espera_base = espera_base
        # IPCA sai com cerca de 2 meses de atraso; a janela precisa cobrir isso.
        self._janela = timedelta(days=janela_dias)
        self._relogio = relogio
        self._dormir = dormir
        self._cache: dict[int, Leitura] = {}

    async def ultimo_valor(self, indicador: NomeIndicador) -> Leitura:
        serie = SERIES[indicador]
        agora = self._relogio()
        em_cache = self._cache.get(serie.codigo)
        if em_cache is not None and agora - em_cache.obtido_em < self.ttl:
            return replace(em_cache, do_cache=True)
        try:
            leitura = await self._buscar(serie, agora)
        except ErroBCB:
            if em_cache is None:
                raise
            return replace(em_cache, do_cache=True, desatualizado=True)
        self._cache[serie.codigo] = leitura
        return leitura

    async def _buscar(self, serie: SerieSGS, agora: datetime) -> Leitura:
        hoje = agora.date()
        url = f"{URL_BASE_SGS}/bcdata.sgs.{serie.codigo}/dados"
        parametros = {
            "formato": "json",
            "dataInicial": _formatar_data_sgs(hoje - self._janela),
            "dataFinal": _formatar_data_sgs(hoje),
        }
        resposta = await self._get_com_retry(url, parametros)
        data_referencia, valor = ultimo_ponto_ate(interpretar_resposta(resposta.content), hoje)
        return Leitura(serie, data_referencia, valor, agora, str(resposta.url))

    async def _get_com_retry(self, url: str, parametros: dict[str, str]) -> httpx.Response:
        motivo = ""
        for tentativa in range(self._tentativas):
            if tentativa > 0:
                await self._dormir(self._espera_base * 2 ** (tentativa - 1))
            try:
                resposta = await self._http.get(url, params=parametros)
            except httpx.TransportError as erro:  # inclui timeouts
                motivo = f"falha de conexão ({type(erro).__name__})"
                continue
            if resposta.status_code >= 500:
                motivo = f"erro {resposta.status_code} no servidor"
                continue
            if resposta.status_code == 404:
                raise ErroBCB("série sem valores no período consultado")
            if resposta.status_code != 200:
                raise ErroBCB(f"requisição recusada (HTTP {resposta.status_code})")
            return resposta
        raise ErroBCB(f"Banco Central indisponível após {self._tentativas} tentativas: {motivo}")
