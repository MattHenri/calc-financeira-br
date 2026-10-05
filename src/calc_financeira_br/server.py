"""Servidor MCP: só valida entradas e orquestra chamadas ao núcleo em `calculos/`."""

import asyncio
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Annotated, get_args

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from calc_financeira_br import __version__
from calc_financeira_br.calculos.renda_fixa import EntradaPosCDI, simular_pos_cdi
from calc_financeira_br.dados.bcb import (
    SERIES,
    ClienteBCB,
    ErroBCB,
    Leitura,
    NomeIndicador,
    agora_brasilia,
)
from calc_financeira_br.formatacao import formatar_decimal, formatar_percentual
from calc_financeira_br.modelos import Resposta
from calc_financeira_br.regras.carregar import TipoTitulo

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


# ---------------------------------------------------------------- obter_indicadores


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


# --------------------------------------------------------------- simular_renda_fixa


class ResultadoRendaFixa(BaseModel):
    tipo: TipoTitulo
    data_aplicacao: date = Field(description="Data de aplicação usada (dia útil).")
    data_resgate: date = Field(description="Data de resgate usada (dia útil).")
    dias_corridos: int
    dias_uteis: int
    percentual_cdi: Decimal
    cdi_anual: Decimal = Field(description="CDI usado na projeção, % a.a.")
    valor_aplicado: Decimal
    valor_bruto: Decimal
    rendimento_bruto: Decimal
    aliquota_iof: Decimal = Field(description="% do rendimento.")
    iof: Decimal
    regime_ir: str = Field(description="'regressivo' ou 'isento'.")
    aliquota_ir: Decimal = Field(description="% sobre o rendimento menos o IOF.")
    ir: Decimal
    valor_liquido: Decimal
    rendimento_liquido: Decimal
    rentabilidade_bruta_periodo: Decimal = Field(description="% no período.")
    rentabilidade_liquida_periodo: Decimal = Field(description="% no período.")
    rentabilidade_liquida_anual: Decimal = Field(description="% a.a., base 252 dias úteis.")
    rentabilidade_real_anual: Decimal | None = Field(
        description="% a.a. acima da inflação; vazio se a inflação não estiver disponível."
    )


def _origem(leitura: Leitura) -> str:
    texto = f"série SGS {leitura.serie.codigo} do Banco Central, dado de "
    texto += f"{leitura.data_referencia:%d/%m/%Y}"
    return texto + (" (valor antigo do cache)" if leitura.desatualizado else "")


@mcp.tool()
async def simular_renda_fixa(  # noqa: PLR0913, PLR0917
    tipo: Annotated[
        TipoTitulo,
        Field(description="Título pós-fixado em % do CDI: cdb, lc, lci ou lca."),
    ],
    valor: Annotated[
        Decimal, Field(gt=0, le=Decimal("1e12"), description="Valor aplicado em reais.")
    ],
    percentual_cdi: Annotated[
        Decimal, Field(gt=0, le=1000, description="Percentual do CDI: 110 = 110% do CDI.")
    ],
    data_resgate: Annotated[date, Field(description="Data do resgate (AAAA-MM-DD).")],
    data_aplicacao: Annotated[
        date | None, Field(description="Data da aplicação (AAAA-MM-DD). Padrão: hoje.")
    ] = None,
    cdi_anual: Annotated[
        Decimal | None,
        Field(ge=0, le=100, description="CDI projetado, % a.a. Padrão: CDI atual do BC."),
    ] = None,
    ipca_anual: Annotated[
        Decimal | None,
        Field(
            gt=-100,
            le=1000,
            description="Inflação anual para a rentabilidade real, % a.a. "
            "Padrão: IPCA acumulado em 12 meses do BC.",
        ),
    ] = None,
) -> Resposta[ResultadoRendaFixa]:
    """Simula um CDB, LC, LCI ou LCA pós-fixado (% do CDI) do aporte ao resgate.

    Calcula valor bruto, IOF, IR, valor líquido e rentabilidades líquida e real,
    com o CDI em base 252 dias úteis e o calendário de feriados nacionais.
    """
    premissas: list[str] = []
    cliente = obter_cliente_bcb()
    if cdi_anual is None:
        try:
            leitura_cdi = await cliente.ultimo_valor("cdi")
        except ErroBCB as erro:
            raise ToolError(
                f"Não foi possível obter o CDI no Banco Central ({erro}). "
                "Informe o CDI projetado em cdi_anual."
            ) from erro
        cdi_anual = leitura_cdi.valor
        premissas.append(f"CDI de {formatar_percentual(cdi_anual)} a.a.: {_origem(leitura_cdi)}.")
    else:
        premissas.append(f"CDI de {formatar_percentual(cdi_anual)} a.a. informado pelo usuário.")

    if ipca_anual is None:
        try:
            leitura_ipca = await cliente.ultimo_valor("ipca_12m")
        except ErroBCB as erro:
            premissas.append(f"Rentabilidade real não calculada: IPCA indisponível ({erro}).")
        else:
            ipca_anual = leitura_ipca.valor
            premissas.append(
                f"Inflação de {formatar_percentual(ipca_anual)} a.a.: IPCA acumulado em "
                f"12 meses, {_origem(leitura_ipca)}."
            )
    else:
        premissas.append(
            f"Inflação de {formatar_percentual(ipca_anual)} a.a. informada pelo usuário."
        )

    entrada = EntradaPosCDI(
        tipo=tipo,
        valor=valor,
        percentual_cdi=percentual_cdi,
        cdi_anual=cdi_anual,
        data_aplicacao=data_aplicacao or agora_brasilia().date(),
        data_resgate=data_resgate,
        ipca_anual=ipca_anual,
    )
    try:
        r = simular_pos_cdi(entrada)
    except ValueError as erro:
        raise ToolError(str(erro)) from erro

    resultado = ResultadoRendaFixa(
        tipo=tipo,
        data_aplicacao=r.data_aplicacao,
        data_resgate=r.data_resgate,
        dias_corridos=r.dias_corridos,
        dias_uteis=r.dias_uteis,
        percentual_cdi=percentual_cdi,
        cdi_anual=cdi_anual,
        valor_aplicado=r.valor_aplicado,
        valor_bruto=r.valor_bruto,
        rendimento_bruto=r.rendimento_bruto,
        aliquota_iof=r.aliquota_iof,
        iof=r.iof,
        regime_ir=r.regime_ir,
        aliquota_ir=r.aliquota_ir,
        ir=r.ir,
        valor_liquido=r.valor_liquido,
        rendimento_liquido=r.rendimento_liquido,
        rentabilidade_bruta_periodo=r.rentabilidade_bruta_periodo,
        rentabilidade_liquida_periodo=r.rentabilidade_liquida_periodo,
        rentabilidade_liquida_anual=r.rentabilidade_liquida_anual,
        rentabilidade_real_anual=r.rentabilidade_real_anual,
    )
    return Resposta(
        resultado=resultado, memoria_calculo=r.memoria, premissas=premissas + r.premissas
    )


def main() -> None:
    """Ponto de entrada do comando `calc-financeira-br` (transporte stdio)."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
