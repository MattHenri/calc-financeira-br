"""Servidor MCP: só valida entradas e orquestra chamadas ao núcleo em `calculos/`."""

import asyncio
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Annotated, Literal, get_args

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from calc_financeira_br import __version__
from calc_financeira_br.calculos.renda_fixa import (
    NOME_TIPO,
    TITULOS_BANCARIOS,
    EntradaPosCDI,
    EntradaPoupanca,
    EntradaPrefixado,
    EntradaTesouroSelic,
    simular_pos_cdi,
    simular_poupanca,
    simular_prefixado,
    simular_tesouro_selic,
)
from calc_financeira_br.calculos.taxas import (
    Equivalencia,
    Sentido,
    UnidadePeriodo,
    UnidadeTaxa,
    converter_periodo,
    equivalente_isento_tributado,
    nominal_para_real,
    real_para_nominal,
)
from calc_financeira_br.dados.bcb import (
    SERIES,
    ClienteBCB,
    ErroBCB,
    Leitura,
    NomeIndicador,
    agora_brasilia,
)
from calc_financeira_br.formatacao import formatar_decimal, formatar_percentual, quantizar
from calc_financeira_br.modelos import Resposta
from calc_financeira_br.regras.carregar import TipoTitulo, convencoes

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
    - selic_efetiva: Selic efetiva anualizada, base 252 dias úteis (% a.a.)
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

Indexador = Literal["cdi", "prefixado", "selic", "poupanca"]


class ResultadoRendaFixa(BaseModel):
    tipo: TipoTitulo
    indexador: Indexador
    data_aplicacao: date = Field(description="Data de aplicação usada.")
    data_resgate: date = Field(description="Data de resgate usada.")
    dias_corridos: int
    dias_uteis: int
    percentual_cdi: Decimal | None = Field(default=None, description="% do CDI contratado.")
    taxa_prefixada: Decimal | None = Field(default=None, description="% a.a. contratado.")
    cdi_anual: Decimal | None = Field(default=None, description="CDI projetado, % a.a.")
    selic_efetiva_anual: Decimal | None = Field(
        default=None, description="Selic efetiva projetada (Tesouro Selic), % a.a."
    )
    selic_meta_anual: Decimal | None = Field(
        default=None, description="Meta da Selic (regra da poupança), % a.a."
    )
    tr_mensal: Decimal | None = Field(default=None, description="TR projetada, % a.m.")
    valor_aplicado: Decimal
    valor_bruto: Decimal
    rendimento_bruto: Decimal
    aliquota_iof: Decimal = Field(description="% do rendimento.")
    iof: Decimal
    regime_ir: str = Field(description="'regressivo' ou 'isento'.")
    aliquota_ir: Decimal = Field(description="% sobre o rendimento menos o IOF.")
    ir: Decimal
    custodia: Decimal = Field(description="Taxa de custódia da B3 (Tesouro Direto).")
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


IndiceMercado = Literal["cdi", "selic_efetiva", "selic", "tr"]

_ROTULO_INDICE: dict[IndiceMercado, tuple[str, str, str]] = {
    # índice: (nome, unidade, campo da tool para informar o valor)
    "cdi": ("CDI", "a.a.", "cdi_anual"),
    "selic_efetiva": ("Selic efetiva", "a.a.", "selic_efetiva_anual"),
    "selic": ("Selic meta", "a.a.", "selic_meta_anual"),
    "tr": ("TR", "a.m.", "tr_mensal"),
}


class _Mercado:
    """Taxas de mercado de uma chamada: as informadas pelo usuário ou as do BC.

    Cada índice é buscado uma vez por chamada, e a premissa de origem é registrada
    uma única vez, mesmo quando várias simulações usam o mesmo índice.
    """

    def __init__(
        self,
        informados: dict[IndiceMercado, Decimal | None],
        ipca_anual: Decimal | None,
    ) -> None:
        self._valores: dict[str, Decimal | None] = {}
        self._informados = informados
        self._ipca_informado = ipca_anual
        self.premissas: list[str] = []

    async def indice(self, nome: IndiceMercado) -> Decimal:
        if nome in self._valores:
            valor = self._valores[nome]
            assert valor is not None
            return valor
        rotulo, unidade, campo = _ROTULO_INDICE[nome]
        informado = self._informados.get(nome)
        if informado is not None:
            self.premissas.append(
                f"{rotulo} de {formatar_percentual(informado)} {unidade} informado pelo usuário."
            )
            self._valores[nome] = informado
            return informado
        try:
            leitura = await obter_cliente_bcb().ultimo_valor(nome)
        except ErroBCB as erro:
            raise ToolError(
                f"Não foi possível obter {rotulo} no Banco Central ({erro}). Informe {campo}."
            ) from erro
        self.premissas.append(
            f"{rotulo} de {formatar_percentual(leitura.valor)} {unidade}: {_origem(leitura)}."
        )
        self._valores[nome] = leitura.valor
        return leitura.valor

    async def ipca(self) -> Decimal | None:
        if "ipca" in self._valores:
            return self._valores["ipca"]
        valor = self._ipca_informado
        if valor is not None:
            self.premissas.append(
                f"Inflação de {formatar_percentual(valor)} a.a. informada pelo usuário."
            )
        else:
            try:
                leitura = await obter_cliente_bcb().ultimo_valor("ipca_12m")
            except ErroBCB as erro:
                self.premissas.append(
                    f"Rentabilidade real não calculada: IPCA indisponível ({erro})."
                )
            else:
                valor = leitura.valor
                self.premissas.append(
                    f"Inflação de {formatar_percentual(valor)} a.a.: IPCA acumulado em "
                    f"12 meses, {_origem(leitura)}."
                )
        self._valores["ipca"] = valor
        return valor


async def _simular_titulo(  # noqa: PLR0913
    mercado: _Mercado,
    tipo: TipoTitulo,
    valor: Decimal,
    data_aplicacao: date,
    data_resgate: date,
    *,
    percentual_cdi: Decimal | None = None,
    taxa_prefixada: Decimal | None = None,
    estoque_tesouro_selic: Decimal = Decimal(0),
) -> tuple[ResultadoRendaFixa, list[str], list[str]]:
    """Escolhe o cálculo pelo tipo e indexador. Devolve (resultado, memória, premissas)."""
    ipca = await mercado.ipca()
    campos: dict[str, Decimal | None] = {}
    try:
        if tipo in TITULOS_BANCARIOS:
            if (percentual_cdi is None) == (taxa_prefixada is None):
                raise ToolError(
                    f"Para {NOME_TIPO[tipo]}, informe percentual_cdi (pós-fixado) ou "
                    "taxa_prefixada (prefixado), um dos dois."
                )
            if percentual_cdi is not None:
                indexador: Indexador = "cdi"
                cdi = await mercado.indice("cdi")
                campos = {"percentual_cdi": percentual_cdi, "cdi_anual": cdi}
                r = simular_pos_cdi(
                    EntradaPosCDI(
                        tipo, valor, percentual_cdi, cdi, data_aplicacao, data_resgate, ipca
                    )
                )
            else:
                assert taxa_prefixada is not None
                indexador = "prefixado"
                campos = {"taxa_prefixada": taxa_prefixada}
                r = simular_prefixado(
                    EntradaPrefixado(
                        tipo, valor, taxa_prefixada, data_aplicacao, data_resgate, ipca
                    )
                )
        else:
            if percentual_cdi is not None or taxa_prefixada is not None:
                raise ToolError(
                    f"{NOME_TIPO[tipo]} não usa percentual_cdi nem taxa_prefixada: a "
                    "remuneração vem da Selic e da TR."
                )
            if tipo == "tesouro_selic":
                indexador = "selic"
                selic = await mercado.indice("selic_efetiva")
                campos = {"selic_efetiva_anual": selic}
                r = simular_tesouro_selic(
                    EntradaTesouroSelic(
                        valor, selic, data_aplicacao, data_resgate, estoque_tesouro_selic, ipca
                    )
                )
            else:
                indexador = "poupanca"
                meta = await mercado.indice("selic")
                tr = await mercado.indice("tr")
                campos = {"selic_meta_anual": meta, "tr_mensal": tr}
                r = simular_poupanca(
                    EntradaPoupanca(valor, meta, tr, data_aplicacao, data_resgate, ipca)
                )
    except ValueError as erro:
        raise ToolError(str(erro)) from erro

    resultado = ResultadoRendaFixa(
        tipo=tipo,
        indexador=indexador,
        data_aplicacao=r.data_aplicacao,
        data_resgate=r.data_resgate,
        dias_corridos=r.dias_corridos,
        dias_uteis=r.dias_uteis,
        valor_aplicado=r.valor_aplicado,
        valor_bruto=r.valor_bruto,
        rendimento_bruto=r.rendimento_bruto,
        aliquota_iof=r.aliquota_iof,
        iof=r.iof,
        regime_ir=r.regime_ir,
        aliquota_ir=r.aliquota_ir,
        ir=r.ir,
        custodia=r.custodia,
        valor_liquido=r.valor_liquido,
        rendimento_liquido=r.rendimento_liquido,
        rentabilidade_bruta_periodo=r.rentabilidade_bruta_periodo,
        rentabilidade_liquida_periodo=r.rentabilidade_liquida_periodo,
        rentabilidade_liquida_anual=r.rentabilidade_liquida_anual,
        rentabilidade_real_anual=r.rentabilidade_real_anual,
        **campos,
    )
    return resultado, r.memoria, r.premissas


TaxaMercado = Annotated[Decimal | None, Field(ge=0, le=100)]


@mcp.tool()
async def simular_renda_fixa(  # noqa: PLR0913, PLR0917
    tipo: Annotated[
        TipoTitulo,
        Field(description="cdb, lc, lci, lca, tesouro_selic ou poupanca."),
    ],
    valor: Annotated[
        Decimal, Field(gt=0, le=Decimal("1e12"), description="Valor aplicado em reais.")
    ],
    data_resgate: Annotated[date, Field(description="Data do resgate (AAAA-MM-DD).")],
    percentual_cdi: Annotated[
        Decimal | None,
        Field(
            gt=0,
            le=1000,
            description="CDB/LC/LCI/LCA pós-fixado: percentual do CDI (110 = 110%).",
        ),
    ] = None,
    taxa_prefixada: Annotated[
        Decimal | None,
        Field(gt=-100, le=1000, description="CDB/LC/LCI/LCA prefixado: taxa em % a.a."),
    ] = None,
    data_aplicacao: Annotated[
        date | None, Field(description="Data da aplicação (AAAA-MM-DD). Padrão: hoje.")
    ] = None,
    cdi_anual: Annotated[
        TaxaMercado, Field(description="CDI projetado, % a.a. Padrão: CDI atual do BC.")
    ] = None,
    selic_efetiva_anual: Annotated[
        TaxaMercado,
        Field(description="Tesouro Selic: Selic efetiva projetada, % a.a. Padrão: BC."),
    ] = None,
    selic_meta_anual: Annotated[
        TaxaMercado,
        Field(description="Poupança: meta da Selic projetada, % a.a. Padrão: BC."),
    ] = None,
    tr_mensal: Annotated[
        TaxaMercado, Field(description="Poupança: TR projetada, % a.m. Padrão: TR do mês (BC).")
    ] = None,
    estoque_tesouro_selic: Annotated[
        Decimal,
        Field(
            ge=0,
            le=Decimal("1e12"),
            description="Tesouro Selic que você já tem, em reais (isenção de custódia).",
        ),
    ] = Decimal(0),
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
    """Simula renda fixa do aporte ao resgate: CDB, LC, LCI, LCA, Tesouro Selic ou poupança.

    - CDB/LC/LCI/LCA: pós-fixado (percentual_cdi) ou prefixado (taxa_prefixada).
    - Tesouro Selic: Selic efetiva, com IR, IOF e taxa de custódia da B3.
    - Poupança: regra da Selic meta + TR, rendendo só no aniversário mensal.

    Devolve valor bruto, IOF, IR, custódia, valor líquido e rentabilidades líquida e real.
    """
    mercado = _Mercado(
        {
            "cdi": cdi_anual,
            "selic_efetiva": selic_efetiva_anual,
            "selic": selic_meta_anual,
            "tr": tr_mensal,
        },
        ipca_anual,
    )
    resultado, memoria, premissas = await _simular_titulo(
        mercado,
        tipo,
        valor,
        data_aplicacao or agora_brasilia().date(),
        data_resgate,
        percentual_cdi=percentual_cdi,
        taxa_prefixada=taxa_prefixada,
        estoque_tesouro_selic=estoque_tesouro_selic,
    )
    return Resposta(
        resultado=resultado, memoria_calculo=memoria, premissas=mercado.premissas + premissas
    )


# ---------------------------------------------------------------- taxa_equivalente

Conversao = Literal[
    "periodo",
    "nominal_para_real",
    "real_para_nominal",
    "isento_para_tributado",
    "tributado_para_isento",
]


class ResultadoTaxaEquivalente(BaseModel):
    conversao: Conversao
    taxa_origem: Decimal
    unidade_origem: UnidadeTaxa
    taxa_equivalente: Decimal = Field(description="Em pontos percentuais (1 = 1%).")
    unidade_destino: UnidadeTaxa
    inflacao: Decimal | None = Field(
        default=None, description="Inflação usada, na unidade da taxa (nominal × real)."
    )
    aliquota_ir: Decimal | None = Field(
        default=None, description="Alíquota de IR do prazo (isento × tributado)."
    )
    dias_corridos: int | None = None
    dias_uteis: int | None = None


async def _cdi_padrao(premissas: list[str]) -> Decimal:
    try:
        leitura = await obter_cliente_bcb().ultimo_valor("cdi")
    except ErroBCB as erro:
        raise ToolError(
            f"Não foi possível obter o CDI no Banco Central ({erro}). Informe cdi_anual."
        ) from erro
    premissas.append(f"CDI de {formatar_percentual(leitura.valor)} a.a.: {_origem(leitura)}.")
    return leitura.valor


async def _inflacao_padrao(unidade: UnidadePeriodo, premissas: list[str]) -> Decimal:
    try:
        leitura = await obter_cliente_bcb().ultimo_valor("ipca_12m")
    except ErroBCB as erro:
        raise ToolError(
            f"Não foi possível obter o IPCA no Banco Central ({erro}). Informe a inflação."
        ) from erro
    premissas.append(
        f"Inflação: IPCA acumulado em 12 meses de {formatar_percentual(leitura.valor)}, "
        f"{_origem(leitura)}."
    )
    if unidade == "a.a.":
        return leitura.valor
    convertida = converter_periodo(leitura.valor, "a.a.", unidade)
    premissas.append(f"IPCA convertido para {unidade}: {formatar_percentual(convertida.taxa, 6)}.")
    return convertida.taxa


@mcp.tool()
async def taxa_equivalente(  # noqa: PLR0913, PLR0917
    conversao: Annotated[
        Conversao,
        Field(
            description="periodo (ex.: a.m. → a.a.), nominal_para_real, real_para_nominal, "
            "isento_para_tributado ou tributado_para_isento."
        ),
    ],
    taxa: Annotated[
        Decimal,
        Field(gt=-100, le=10000, description="Taxa em %: 1 = 1%. Em %cdi, 90 = 90% do CDI."),
    ],
    unidade: Annotated[
        UnidadeTaxa,
        Field(description="Unidade da taxa: a.a., a.s., a.t., a.m., a.d.u. (dia útil) ou %cdi."),
    ] = "a.a.",
    unidade_destino: Annotated[
        UnidadePeriodo | None,
        Field(description="Unidade desejada (obrigatória em 'periodo')."),
    ] = None,
    inflacao: Annotated[
        Decimal | None,
        Field(
            gt=-100,
            le=1000,
            description="Inflação em %, na mesma unidade da taxa. Padrão: IPCA 12 meses do BC.",
        ),
    ] = None,
    prazo_dias: Annotated[
        int | None,
        Field(ge=1, le=10950, description="Prazo em dias corridos (isento × tributado)."),
    ] = None,
    cdi_anual: Annotated[
        Decimal | None,
        Field(ge=0, le=100, description="CDI em % a.a. para taxas em %cdi. Padrão: CDI do BC."),
    ] = None,
) -> Resposta[ResultadoTaxaEquivalente]:
    """Converte taxas: entre períodos, nominal × real e isento × tributado.

    Exemplos: 1% a.m. em % a.a.; 12% a.a. nominal com IPCA → real; quanto um CDB
    precisa pagar (% do CDI) para empatar com uma LCI a 90% do CDI em 2 anos.
    A equivalência isento × tributado é exata no prazo (IR sobre o rendimento total).
    """
    premissas: list[str] = []
    casas = convencoes().valores.casas_taxas
    resultado = ResultadoTaxaEquivalente(
        conversao=conversao,
        taxa_origem=taxa,
        unidade_origem=unidade,
        taxa_equivalente=Decimal(0),
        unidade_destino=unidade,
    )
    try:
        if conversao == "periodo":
            if unidade == "%cdi" or unidade_destino is None:
                raise ToolError(
                    "Em 'periodo', informe unidade_destino e use uma unidade de tempo "
                    "(a.a., a.s., a.t., a.m. ou a.d.u.), não %cdi."
                )
            calculo: Equivalencia = converter_periodo(taxa, unidade, unidade_destino)
            resultado.unidade_destino = unidade_destino
        elif conversao in ("nominal_para_real", "real_para_nominal"):
            if unidade == "%cdi":
                raise ToolError("Nominal × real exige uma taxa em unidade de tempo, não %cdi.")
            if inflacao is None:
                inflacao = await _inflacao_padrao(unidade, premissas)
            else:
                premissas.append(
                    f"Inflação de {formatar_percentual(inflacao)} {unidade} informada pelo usuário."
                )
            funcao = nominal_para_real if conversao == "nominal_para_real" else real_para_nominal
            calculo = funcao(taxa, inflacao)
            resultado.inflacao = inflacao
        else:
            if prazo_dias is None:
                raise ToolError(
                    "Isento × tributado precisa do prazo em dias corridos (prazo_dias)."
                )
            if unidade == "%cdi":
                if cdi_anual is None:
                    cdi_anual = await _cdi_padrao(premissas)
                else:
                    premissas.append(
                        f"CDI de {formatar_percentual(cdi_anual)} a.a. informado pelo usuário."
                    )
            sentido: Sentido = (
                "isento_para_tributado"
                if conversao == "isento_para_tributado"
                else "tributado_para_isento"
            )
            tributaria = equivalente_isento_tributado(
                taxa, unidade, prazo_dias, agora_brasilia().date(), sentido, cdi_anual
            )
            calculo = tributaria
            resultado.aliquota_ir = tributaria.aliquota_ir
            resultado.dias_corridos = tributaria.dias_corridos
            resultado.dias_uteis = tributaria.dias_uteis
    except ValueError as erro:
        raise ToolError(str(erro)) from erro

    resultado.taxa_equivalente = quantizar(
        calculo.taxa, casas, convencoes().valores.arredondamento_reais
    )
    return Resposta(
        resultado=resultado,
        memoria_calculo=calculo.memoria,
        premissas=premissas + calculo.premissas + [f"Resultado com {casas} casas decimais."],
    )


def main() -> None:
    """Ponto de entrada do comando `calc-financeira-br` (transporte stdio)."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
