"""Servidor MCP: só valida entradas e orquestra chamadas ao núcleo em `calculos/`."""

import asyncio
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Annotated, get_args

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from calc_financeira_br import __version__
from calc_financeira_br.dados.bcb import SERIES, ClienteBCB, ErroBCB, Leitura, NomeIndicador
from calc_financeira_br.modelos import Resposta, formatar_decimal

mcp = MCPServer(
    "calc-financeira-br",
    version=__version__,
    instructions=(
        "Cálculos financeiros brasileiros determinísticos, com memória de cálculo. "
        "Os resultados são simulações, não recomendação de investimento."
    ),
)


@cache
def obter_cliente_bcb() -> ClienteBCB:
    return ClienteBCB()


class Indicador(BaseModel):
    indicador: NomeIndicador
    nome: str
    valor: Decimal
    unidade: str
    data_referencia: date
    serie_sgs: int = Field(description="Código da série no SGS do Banco Central.")
    fonte: str = Field(description="URL consultada no Banco Central.")
    desatualizado: bool = Field(
        description="True se o Banco Central falhou e foi usado um valor antigo em cache."
    )


class IndicadorIndisponivel(BaseModel):
    indicador: NomeIndicador
    motivo: str


class ResultadoIndicadores(BaseModel):
    indicadores: list[Indicador]
    indisponiveis: list[IndicadorIndisponivel]


def _descrever(leitura: Leitura) -> str:
    serie = leitura.serie
    origem = "cache" if leitura.do_cache else "consulta"
    texto = (
        f"{serie.nome}: série SGS {serie.codigo} ({origem} de "
        f"{leitura.obtido_em:%d/%m/%Y %H:%M}); último valor com data até hoje: "
        f"{formatar_decimal(leitura.valor)} {serie.unidade} em {leitura.data_referencia:%d/%m/%Y}."
    )
    if leitura.desatualizado:
        texto += " Banco Central indisponível agora; valor antigo do cache."
    return texto


@mcp.tool()
async def obter_indicadores(
    indicadores: Annotated[
        list[NomeIndicador] | None,
        Field(
            min_length=1,
            description="Indicadores a consultar. Se omitido, consulta todos.",
        ),
    ] = None,
) -> Resposta[ResultadoIndicadores]:
    """Consulta no Banco Central o valor atual de Selic, CDI, IPCA e TR.

    - selic: meta da Selic definida pelo Copom (% a.a.)
    - cdi: taxa DI anualizada, base 252 dias úteis (% a.a.)
    - ipca: variação mensal do IPCA (% a.m.)
    - ipca_12m: IPCA acumulado em 12 meses (%)
    - tr: Taxa Referencial do mês (% a.m.)
    """
    pedidos = list(dict.fromkeys(indicadores or get_args(NomeIndicador)))
    cliente = obter_cliente_bcb()
    leituras = await asyncio.gather(
        *(cliente.ultimo_valor(nome) for nome in pedidos), return_exceptions=True
    )

    obtidos: list[Indicador] = []
    falhas: list[IndicadorIndisponivel] = []
    memoria: list[str] = []
    for nome, leitura in zip(pedidos, leituras, strict=True):
        if isinstance(leitura, ErroBCB):
            falhas.append(IndicadorIndisponivel(indicador=nome, motivo=str(leitura)))
            memoria.append(f"{SERIES[nome].nome}: indisponível ({leitura}).")
            continue
        if isinstance(leitura, BaseException):
            raise leitura
        obtidos.append(
            Indicador(
                indicador=nome,
                nome=leitura.serie.nome,
                valor=leitura.valor,
                unidade=leitura.serie.unidade,
                data_referencia=leitura.data_referencia,
                serie_sgs=leitura.serie.codigo,
                fonte=leitura.url,
                desatualizado=leitura.desatualizado,
            )
        )
        memoria.append(_descrever(leitura))

    horas_cache = int(cliente.ttl.total_seconds() // 3600)
    premissas = [
        "Fonte: Sistema Gerenciador de Séries Temporais (SGS) do Banco Central.",
        *(f"{SERIES[n].nome}: {SERIES[n].descricao} (série {SERIES[n].codigo})." for n in pedidos),
        "Valores com data futura publicados pelo Banco Central (como a Selic meta vigente "
        "até a próxima reunião do Copom) são ignorados.",
        f"Valores ficam em cache por até {horas_cache} hora(s).",
    ]
    return Resposta(
        resultado=ResultadoIndicadores(indicadores=obtidos, indisponiveis=falhas),
        memoria_calculo=memoria,
        premissas=premissas,
    )


def main() -> None:
    """Ponto de entrada do comando `calc-financeira-br` (transporte stdio)."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
