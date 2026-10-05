"""Renda fixa: pós-fixado no CDI, prefixado, Tesouro Selic e poupança.

Pós-fixado a p% do CDI: fator de cada dia útil f = 1 + p × [(1 + CDI)^(1/252) − 1].
Prefixado a i% a.a.: fator (1 + i)^(dias úteis / 252).
Tesouro Selic: 100% da Selic efetiva, como o CDI, mais a taxa de custódia da B3.
Poupança: rende no aniversário mensal (ver `simular_poupanca`).

Sobre o rendimento incide o IOF (resgates com menos de 30 dias) e, depois,
o IR sobre o rendimento menos o IOF.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext

from calc_financeira_br.calculos.calendario import (
    dias_uteis_entre,
    eh_dia_util,
    proximo_dia_util,
)
from calc_financeira_br.calculos.tributos import aliquota_iof, aliquota_ir
from calc_financeira_br.formatacao import (
    formatar_decimal,
    formatar_percentual,
    formatar_reais,
)
from calc_financeira_br.regras.carregar import (
    Convencoes,
    RegrasPoupanca,
    RegrasTributacao,
    Tarifas,
    TipoTitulo,
    convencoes,
    regras_poupanca,
    regras_tributacao,
    tarifas,
)
from calc_financeira_br.regras.feriados import FONTE as FONTE_FERIADOS

UM = Decimal(1)
CEM = Decimal(100)
PRECISAO = 50  # dígitos significativos das contas intermediárias

NOME_TIPO: dict[TipoTitulo, str] = {
    "cdb": "CDB",
    "lc": "LC",
    "lci": "LCI",
    "lca": "LCA",
    "tesouro_selic": "Tesouro Selic",
    "poupanca": "Poupança",
}
TITULOS_BANCARIOS: tuple[TipoTitulo, ...] = ("cdb", "lc", "lci", "lca")


def _do(indice: str) -> str:
    """'do CDI', 'da Selic'."""
    return f"da {indice}" if indice == "Selic" else f"do {indice}"


@dataclass(frozen=True)
class EntradaPosCDI:
    tipo: TipoTitulo
    valor: Decimal
    """Valor aplicado em reais."""
    percentual_cdi: Decimal
    """110 = 110% do CDI."""
    cdi_anual: Decimal
    """13.65 = 13,65% a.a."""
    data_aplicacao: date
    data_resgate: date
    ipca_anual: Decimal | None = None
    """Inflação anual para a rentabilidade real (4.22 = 4,22% a.a.)."""


@dataclass(frozen=True)
class EntradaPrefixado:
    tipo: TipoTitulo
    valor: Decimal
    taxa_anual: Decimal
    """12 = 12% a.a., base 252 dias úteis."""
    data_aplicacao: date
    data_resgate: date
    ipca_anual: Decimal | None = None


@dataclass(frozen=True)
class EntradaTesouroSelic:
    valor: Decimal
    selic_anual: Decimal
    """Selic efetiva, % a.a. base 252."""
    data_aplicacao: date
    data_resgate: date
    estoque_tesouro_selic: Decimal = Decimal(0)
    """Tesouro Selic que a pessoa já tem, para a isenção de custódia de R$ 10 mil."""
    ipca_anual: Decimal | None = None


@dataclass(frozen=True)
class EntradaPoupanca:
    valor: Decimal
    selic_meta: Decimal
    """Meta da Selic, % a.a. (define a regra da remuneração adicional)."""
    tr_mensal: Decimal
    """TR do período, % a.m., projetada constante."""
    data_aplicacao: date
    data_resgate: date
    ipca_anual: Decimal | None = None


@dataclass(frozen=True)
class ResultadoRendaFixa:
    data_aplicacao: date
    data_resgate: date
    dias_corridos: int
    dias_uteis: int
    fator_acumulado: Decimal
    valor_aplicado: Decimal
    valor_bruto: Decimal
    rendimento_bruto: Decimal
    aliquota_iof: Decimal
    iof: Decimal
    regime_ir: str
    aliquota_ir: Decimal
    base_ir: Decimal
    ir: Decimal
    custodia: Decimal
    valor_liquido: Decimal
    rendimento_liquido: Decimal
    rentabilidade_bruta_periodo: Decimal
    rentabilidade_liquida_periodo: Decimal
    rentabilidade_liquida_anual: Decimal
    rentabilidade_real_anual: Decimal | None
    taxa_diaria_cdi: Decimal | None = None
    fator_diario: Decimal | None = None
    memoria: list[str] = field(default_factory=list)
    premissas: list[str] = field(default_factory=list)


ResultadoPosCDI = ResultadoRendaFixa  # nome antigo


# ------------------------------------------------------------------ validação e datas


def _validar_comum(
    valor: Decimal, aplicacao: date, resgate: date, ipca_anual: Decimal | None
) -> None:
    if valor <= 0:
        raise ValueError("o valor aplicado deve ser positivo")
    if resgate <= aplicacao:
        raise ValueError("a data de resgate deve ser posterior à data de aplicação")
    if ipca_anual is not None and ipca_anual <= -CEM:
        raise ValueError("a inflação anual deve ser maior que -100%")


def _ajustar_datas(data_aplicacao: date, data_resgate: date) -> tuple[date, date, list[str]]:
    aplicacao = proximo_dia_util(data_aplicacao)
    resgate = proximo_dia_util(data_resgate)
    passos = []
    if aplicacao != data_aplicacao:
        passos.append(
            f"Aplicação em {data_aplicacao:%d/%m/%Y} (dia não útil) passa para "
            f"o próximo dia útil: {aplicacao:%d/%m/%Y}."
        )
    if resgate != data_resgate:
        passos.append(
            f"Resgate em {data_resgate:%d/%m/%Y} (dia não útil) passa para "
            f"o próximo dia útil: {resgate:%d/%m/%Y}."
        )
    if resgate <= aplicacao:
        raise ValueError("depois do ajuste para dias úteis, o prazo ficou nulo")
    passos.append(
        f"Prazo de {aplicacao:%d/%m/%Y} a {resgate:%d/%m/%Y}: {(resgate - aplicacao).days} "
        f"dias corridos e {dias_uteis_entre(aplicacao, resgate)} dias úteis (conta o dia da "
        "aplicação, não conta o do resgate)."
    )
    return aplicacao, resgate, passos


# ---------------------------------------------------------------------------- fatores


def _taxa_diaria(taxa_anual: Decimal, conv: Convencoes) -> Decimal:
    c = conv.cdi
    with localcontext(prec=PRECISAO):
        taxa = (UM + taxa_anual / CEM) ** (UM / c.base_dias_uteis) - UM
    return taxa.quantize(UM.scaleb(-c.casas_taxa_diaria), c.arredondamento_taxa_diaria)


def _fator_diario(taxa_diaria: Decimal, percentual: Decimal, conv: Convencoes) -> Decimal:
    c = conv.cdi
    with localcontext(prec=PRECISAO):
        fator = UM + taxa_diaria * percentual / CEM
    return fator.quantize(UM.scaleb(-c.casas_fator_acumulado), c.arredondamento_fator)


def _acumular(acumulado: Decimal, fator_diario: Decimal, conv: Convencoes) -> Decimal:
    c = conv.cdi
    with localcontext(prec=PRECISAO):
        produto = acumulado * fator_diario
    return produto.quantize(UM.scaleb(-c.casas_fator_acumulado), c.arredondamento_fator)


def fator_cdi(
    percentual_cdi: Decimal, cdi_anual: Decimal, dias_uteis: int, conv: Convencoes
) -> tuple[Decimal, Decimal, Decimal]:
    """(taxa diária do CDI, fator diário, fator acumulado) com as convenções da B3.

    A taxa diária é arredondada; o fator diário e o acumulado são truncados a cada dia útil.
    """
    taxa_diaria = _taxa_diaria(cdi_anual, conv)
    fator_diario = _fator_diario(taxa_diaria, percentual_cdi, conv)
    acumulado = UM
    for _ in range(dias_uteis):
        acumulado = _acumular(acumulado, fator_diario, conv)
    return taxa_diaria, fator_diario, acumulado


def fatores_por_dia_corrido(
    fator_diario: Decimal, aplicacao: date, resgate: date, conv: Convencoes
) -> list[Decimal]:
    """Fator acumulado no fim de cada dia corrido após a aplicação (dia 1 até o resgate).

    Cada dia útil rende ao passar para o dia seguinte, como em `dias_uteis_entre`.
    """
    fatores = []
    acumulado = UM
    dia = aplicacao
    while dia < resgate:
        if eh_dia_util(dia):
            acumulado = _acumular(acumulado, fator_diario, conv)
        fatores.append(acumulado)
        dia += timedelta(days=1)
    return fatores


def _memoria_fator_indexado(  # noqa: PLR0913, PLR0917
    nome_indice: str,
    taxa_anual: Decimal,
    percentual: Decimal,
    taxa_diaria: Decimal,
    fator_diario: Decimal,
    fator: Decimal,
    dias_uteis: int,
    conv: Convencoes,
) -> list[str]:
    base = conv.cdi.base_dias_uteis
    return [
        f"Taxa diária {_do(nome_indice)}: (1 + {formatar_percentual(taxa_anual)})^(1/{base}) − 1 "
        f"= {formatar_decimal(taxa_diaria)} ({conv.cdi.casas_taxa_diaria} casas).",
        f"Fator diário a {formatar_percentual(percentual)} {_do(nome_indice)}: 1 + "
        f"{formatar_decimal(taxa_diaria)} × {formatar_percentual(percentual)} = "
        f"{formatar_decimal(fator_diario.normalize())}.",
        f"Fator acumulado em {dias_uteis} dias úteis: {formatar_decimal(fator)} "
        f"(truncado em {conv.cdi.casas_fator_acumulado} casas a cada dia).",
    ]


def _premissas_convencao_b3(nome_indice: str, conv: Convencoes) -> str:
    return (
        f"Convenção B3: taxa diária {_do(nome_indice)} com {conv.cdi.casas_taxa_diaria} casas "
        f"(arredondada); fatores truncados em {conv.cdi.casas_fator_acumulado} casas."
    )


# -------------------------------------------------------------- tributos e fechamento


@dataclass
class _Contexto:
    tipo: TipoTitulo
    valor: Decimal
    aplicacao: date
    resgate: date
    dias_corridos: int
    dias_uteis: int
    fator: Decimal
    ipca_anual: Decimal | None
    memoria: list[str]
    premissas: list[str]
    regras: RegrasTributacao
    conv: Convencoes
    custodia: Callable[[Decimal], tuple[Decimal, list[str]]] | None = None
    """Recebe o valor bruto e devolve (custódia em reais, passos da memória)."""
    taxa_diaria: Decimal | None = None
    fator_diario: Decimal | None = None
    datas_ajustadas: bool = True


def _fechar(ctx: _Contexto) -> ResultadoRendaFixa:  # noqa: PLR0915
    v = ctx.conv.valores
    centavos = UM.scaleb(-v.casas_reais)
    casas_pct = UM.scaleb(-v.casas_percentuais)

    def reais(valor: Decimal) -> Decimal:
        return valor.quantize(centavos, v.arredondamento_reais)

    def pct(valor: Decimal) -> Decimal:
        return valor.quantize(casas_pct, v.arredondamento_reais)

    nome = NOME_TIPO[ctx.tipo]
    memoria = ctx.memoria
    with localcontext(prec=PRECISAO):
        bruto = reais(ctx.valor * ctx.fator)
    rendimento = bruto - ctx.valor
    memoria.append(
        f"Valor bruto: {formatar_reais(ctx.valor)} × {formatar_decimal(ctx.fator)} = "
        f"{formatar_reais(bruto)}; rendimento bruto de {formatar_reais(rendimento)}."
    )

    taxa_iof = aliquota_iof(ctx.tipo, ctx.dias_corridos, ctx.regras)
    iof = reais(rendimento * taxa_iof / CEM)
    if ctx.tipo not in ctx.regras.iof.tipos:
        memoria.append(f"IOF: {nome} tem alíquota zero de IOF = {formatar_reais(iof)}.")
    else:
        memoria.append(
            f"IOF: resgate com {ctx.dias_corridos} dias corridos → "
            f"{formatar_percentual(taxa_iof)} do rendimento = {formatar_reais(iof)}."
        )

    ir_info = aliquota_ir(ctx.tipo, ctx.dias_corridos, ctx.aplicacao, ctx.regras)
    base_ir = rendimento - iof
    ir = reais(base_ir * ir_info.aliquota / CEM)
    if ir_info.regime == "isento":
        memoria.append(f"IR: {nome} é isento de IR para pessoa física = {formatar_reais(ir)}.")
    else:
        memoria.append(
            f"IR: tabela regressiva, {ctx.dias_corridos} dias corridos → "
            f"{formatar_percentual(ir_info.aliquota)} sobre (rendimento − IOF) "
            f"{formatar_reais(base_ir)} = {formatar_reais(ir)}."
        )

    custodia = Decimal("0.00")
    if ctx.custodia is not None:
        bruta, passos = ctx.custodia(bruto)
        custodia = reais(bruta)
        memoria += passos

    liquido = bruto - iof - ir - custodia
    rendimento_liquido = liquido - ctx.valor
    descontos = f"{formatar_reais(iof)} (IOF) − {formatar_reais(ir)} (IR)"
    if ctx.custodia is not None:
        descontos += f" − {formatar_reais(custodia)} (custódia)"
    memoria.append(
        f"Valor líquido: {formatar_reais(bruto)} − {descontos} = {formatar_reais(liquido)}."
    )

    base = ctx.conv.cdi.base_dias_uteis
    with localcontext(prec=PRECISAO):
        rent_bruta = (bruto / ctx.valor - UM) * CEM
        rent_liquida = (liquido / ctx.valor - UM) * CEM
        if ctx.dias_uteis > 0:
            rent_anual = ((liquido / ctx.valor) ** (Decimal(base) / ctx.dias_uteis) - UM) * CEM
        else:
            rent_anual = Decimal(0)
        rent_real = None
        if ctx.ipca_anual is not None:
            rent_real = ((UM + rent_anual / CEM) / (UM + ctx.ipca_anual / CEM) - UM) * CEM
    memoria.append(
        f"Rentabilidade líquida: {formatar_percentual(rent_liquida)} no período, "
        f"{formatar_percentual(rent_anual)} a.a. (base {base} dias úteis)."
    )
    if rent_real is not None and ctx.ipca_anual is not None:
        memoria.append(
            f"Rentabilidade real: (1 + {formatar_percentual(rent_anual)}) / "
            f"(1 + {formatar_percentual(ctx.ipca_anual)}) − 1 = "
            f"{formatar_percentual(rent_real)} a.a."
        )

    premissas = list(ctx.premissas)
    premissas += [f"Dias úteis: {FONTE_FERIADOS} (só feriados nacionais)."]
    if ctx.datas_ajustadas:
        premissas.append(
            "Data de aplicação ou de resgate em dia não útil passa para o próximo dia útil."
        )
    premissas += [
        f"Valores em reais com {v.casas_reais} casas ({v.arredondamento_reais}).",
        "IR e IOF contam dias corridos entre aplicação e resgate; o IOF é calculado antes "
        "do IR e sai da base do IR.",
        f"IR: {ctx.regras.ir.fonte}.",
        f"IOF: {ctx.regras.iof.fonte}.",
        f"Rentabilidade anual na base {base} dias úteis.",
    ]
    if ctx.ipca_anual is not None:
        premissas.append(
            f"Inflação constante em {formatar_percentual(ctx.ipca_anual)} a.a. "
            "para a rentabilidade real."
        )

    return ResultadoRendaFixa(
        data_aplicacao=ctx.aplicacao,
        data_resgate=ctx.resgate,
        dias_corridos=ctx.dias_corridos,
        dias_uteis=ctx.dias_uteis,
        fator_acumulado=ctx.fator,
        valor_aplicado=ctx.valor,
        valor_bruto=bruto,
        rendimento_bruto=rendimento,
        aliquota_iof=taxa_iof,
        iof=iof,
        regime_ir=ir_info.regime,
        aliquota_ir=ir_info.aliquota,
        base_ir=base_ir,
        ir=ir,
        custodia=custodia,
        valor_liquido=liquido,
        rendimento_liquido=rendimento_liquido,
        rentabilidade_bruta_periodo=pct(rent_bruta),
        rentabilidade_liquida_periodo=pct(rent_liquida),
        rentabilidade_liquida_anual=pct(rent_anual),
        rentabilidade_real_anual=None if rent_real is None else pct(rent_real),
        taxa_diaria_cdi=ctx.taxa_diaria,
        fator_diario=ctx.fator_diario,
        memoria=memoria,
        premissas=premissas,
    )


# ---------------------------------------------------------------- pós-fixado no CDI


def simular_pos_cdi(
    entrada: EntradaPosCDI,
    regras: RegrasTributacao | None = None,
    conv: Convencoes | None = None,
) -> ResultadoRendaFixa:
    _validar_comum(entrada.valor, entrada.data_aplicacao, entrada.data_resgate, entrada.ipca_anual)
    if entrada.tipo not in TITULOS_BANCARIOS:
        raise ValueError("pós-fixado no CDI vale para CDB, LC, LCI e LCA")
    if entrada.percentual_cdi <= 0:
        raise ValueError("o percentual do CDI deve ser positivo")
    if entrada.cdi_anual < 0:
        raise ValueError("o CDI não pode ser negativo")
    conv = conv or convencoes()
    aplicacao, resgate, memoria = _ajustar_datas(entrada.data_aplicacao, entrada.data_resgate)
    dias_uteis = dias_uteis_entre(aplicacao, resgate)
    p = entrada.percentual_cdi
    taxa_diaria, fator_diario, fator = fator_cdi(p, entrada.cdi_anual, dias_uteis, conv)
    memoria += _memoria_fator_indexado(
        "CDI", entrada.cdi_anual, p, taxa_diaria, fator_diario, fator, dias_uteis, conv
    )
    return _fechar(
        _Contexto(
            tipo=entrada.tipo,
            valor=entrada.valor,
            aplicacao=aplicacao,
            resgate=resgate,
            dias_corridos=(resgate - aplicacao).days,
            dias_uteis=dias_uteis,
            fator=fator,
            ipca_anual=entrada.ipca_anual,
            memoria=memoria,
            premissas=[
                f"CDI constante em {formatar_percentual(entrada.cdi_anual)} a.a. durante "
                "todo o prazo.",
                _premissas_convencao_b3("CDI", conv),
            ],
            regras=regras or regras_tributacao(),
            conv=conv,
            taxa_diaria=taxa_diaria,
            fator_diario=fator_diario,
        )
    )


# ------------------------------------------------------------------------- prefixado


def simular_prefixado(
    entrada: EntradaPrefixado,
    regras: RegrasTributacao | None = None,
    conv: Convencoes | None = None,
) -> ResultadoRendaFixa:
    _validar_comum(entrada.valor, entrada.data_aplicacao, entrada.data_resgate, entrada.ipca_anual)
    if entrada.tipo not in TITULOS_BANCARIOS:
        raise ValueError("prefixado vale para CDB, LC, LCI e LCA")
    if entrada.taxa_anual <= -CEM:
        raise ValueError("a taxa prefixada deve ser maior que -100%")
    conv = conv or convencoes()
    c = conv.cdi
    aplicacao, resgate, memoria = _ajustar_datas(entrada.data_aplicacao, entrada.data_resgate)
    dias_uteis = dias_uteis_entre(aplicacao, resgate)
    with localcontext(prec=PRECISAO):
        fator = (UM + entrada.taxa_anual / CEM) ** (Decimal(dias_uteis) / c.base_dias_uteis)
    fator = fator.quantize(UM.scaleb(-c.casas_fator_acumulado), c.arredondamento_fator)
    memoria.append(
        f"Fator prefixado: (1 + {formatar_percentual(entrada.taxa_anual)})^({dias_uteis}/"
        f"{c.base_dias_uteis}) = {formatar_decimal(fator)} (truncado em "
        f"{c.casas_fator_acumulado} casas)."
    )
    return _fechar(
        _Contexto(
            tipo=entrada.tipo,
            valor=entrada.valor,
            aplicacao=aplicacao,
            resgate=resgate,
            dias_corridos=(resgate - aplicacao).days,
            dias_uteis=dias_uteis,
            fator=fator,
            ipca_anual=entrada.ipca_anual,
            memoria=memoria,
            premissas=[
                f"Taxa prefixada de {formatar_percentual(entrada.taxa_anual)} a.a. na base "
                f"{c.base_dias_uteis} dias úteis, mantida até o resgate.",
            ],
            regras=regras or regras_tributacao(),
            conv=conv,
        )
    )


# --------------------------------------------------------------------- Tesouro Selic


def custodia_tesouro_selic(
    valor: Decimal,
    fatores_dia: list[Decimal],
    estoque_existente: Decimal,
    tarifa: Tarifas,
) -> tuple[Decimal, list[str]]:
    """Custódia provisionada por dia corrido sobre o valor do dia que excede a isenção.

    Devolve o valor sem arredondar (o arredondamento em reais é feito no fechamento).
    """
    regra = tarifa.custodia_tesouro
    taxa_dia_texto = f"{formatar_percentual(regra.taxa_anual)} / {regra.base_dias}"
    total = Decimal(0)
    dias_tributados = 0
    with localcontext(prec=PRECISAO):
        taxa_dia = regra.taxa_anual / CEM / regra.base_dias
        for fator in fatores_dia:
            valor_dia = valor * fator
            excedente = estoque_existente + valor_dia - regra.isencao_tesouro_selic
            base = min(max(excedente, Decimal(0)), valor_dia)
            if base > 0:
                dias_tributados += 1
            total += base * taxa_dia
    isencao = formatar_reais(regra.isencao_tesouro_selic)
    passos = [
        f"Custódia B3: {taxa_dia_texto} por dia corrido sobre a parte do valor que passa de "
        f"{isencao} (somando o Tesouro Selic que você já tem, {formatar_reais(estoque_existente)})"
        f"; cobrada em {dias_tributados} de {len(fatores_dia)} dias = {formatar_reais(total)}.",
    ]
    return total, passos


def simular_tesouro_selic(
    entrada: EntradaTesouroSelic,
    regras: RegrasTributacao | None = None,
    conv: Convencoes | None = None,
    tarifa: Tarifas | None = None,
) -> ResultadoRendaFixa:
    _validar_comum(entrada.valor, entrada.data_aplicacao, entrada.data_resgate, entrada.ipca_anual)
    if entrada.selic_anual < 0:
        raise ValueError("a Selic não pode ser negativa")
    if entrada.estoque_tesouro_selic < 0:
        raise ValueError("o estoque de Tesouro Selic não pode ser negativo")
    conv = conv or convencoes()
    tarifa = tarifa or tarifas()
    aplicacao, resgate, memoria = _ajustar_datas(entrada.data_aplicacao, entrada.data_resgate)
    dias_uteis = dias_uteis_entre(aplicacao, resgate)
    taxa_diaria = _taxa_diaria(entrada.selic_anual, conv)
    fator_diario = _fator_diario(taxa_diaria, CEM, conv)
    fatores = fatores_por_dia_corrido(fator_diario, aplicacao, resgate, conv)
    fator = fatores[-1]
    memoria += _memoria_fator_indexado(
        "Selic", entrada.selic_anual, CEM, taxa_diaria, fator_diario, fator, dias_uteis, conv
    )

    def custodia(_bruto: Decimal) -> tuple[Decimal, list[str]]:
        return custodia_tesouro_selic(entrada.valor, fatores, entrada.estoque_tesouro_selic, tarifa)

    regra = tarifa.custodia_tesouro
    return _fechar(
        _Contexto(
            tipo="tesouro_selic",
            valor=entrada.valor,
            aplicacao=aplicacao,
            resgate=resgate,
            dias_corridos=(resgate - aplicacao).days,
            dias_uteis=dias_uteis,
            fator=fator,
            ipca_anual=entrada.ipca_anual,
            memoria=memoria,
            premissas=[
                f"Selic efetiva constante em {formatar_percentual(entrada.selic_anual)} a.a. "
                "durante todo o prazo; ágio ou deságio do preço de mercado ignorados.",
                _premissas_convencao_b3("Selic", conv),
                f"Custódia: {regra.fonte}. {formatar_percentual(regra.taxa_anual)} a.a. pro rata "
                f"por dia corrido (base {regra.base_dias}) sobre o valor bruto do dia; isenção "
                f"até {formatar_reais(regra.isencao_tesouro_selic)} de estoque por CPF.",
                "Custódia não é deduzida da base do IR; taxa do agente de custódia zero.",
            ],
            regras=regras or regras_tributacao(),
            conv=conv,
            custodia=custodia,
            taxa_diaria=taxa_diaria,
            fator_diario=fator_diario,
        )
    )


# --------------------------------------------------------------------------- poupança


def _somar_meses(dia: date, meses: int) -> date:
    """Mesmo dia `meses` depois. Só é chamado com dia ≤ 28, que existe em todo mês."""
    total = dia.month - 1 + meses
    return dia.replace(year=dia.year + total // 12, month=total % 12 + 1)


def taxa_mensal_poupanca(
    selic_meta: Decimal, tr_mensal: Decimal, regras: RegrasPoupanca
) -> tuple[Decimal, list[str]]:
    """Rendimento do período em % (como a série SGS 195) e os passos da conta."""
    with localcontext(prec=PRECISAO):
        if selic_meta > regras.limite_selic:
            adicional = regras.adicional_mensal
            passo = (
                f"Selic meta de {formatar_percentual(selic_meta)} > "
                f"{formatar_percentual(regras.limite_selic)}: adicional de "
                f"{formatar_percentual(adicional)} a.m."
            )
        else:
            anual = regras.percentual_selic / CEM * selic_meta
            adicional = ((UM + anual / CEM) ** (UM / 12) - UM) * CEM
            passo = (
                f"Selic meta de {formatar_percentual(selic_meta)} ≤ "
                f"{formatar_percentual(regras.limite_selic)}: adicional de "
                f"{formatar_percentual(regras.percentual_selic)} da Selic = "
                f"{formatar_percentual(anual)} a.a., mensalizado: (1 + "
                f"{formatar_percentual(anual)})^(1/12) − 1 = {formatar_percentual(adicional, 6)} "
                "a.m."
            )
        taxa = ((UM + tr_mensal / CEM) * (UM + adicional / CEM) - UM) * CEM
    taxa = taxa.quantize(UM.scaleb(-regras.casas_taxa_mensal), regras.arredondamento_taxa_mensal)
    return taxa, [
        passo,
        f"Rendimento mensal: (1 + TR {formatar_percentual(tr_mensal)}) × (1 + "
        f"{formatar_percentual(adicional, 6)}) − 1 = {formatar_percentual(taxa)} "
        f"({regras.casas_taxa_mensal} casas, como o Banco Central publica).",
    ]


def simular_poupanca(
    entrada: EntradaPoupanca,
    regras: RegrasTributacao | None = None,
    conv: Convencoes | None = None,
    regras_poup: RegrasPoupanca | None = None,
) -> ResultadoRendaFixa:
    """Poupança de pessoa física: rende só no aniversário mensal, sem IR e sem IOF."""
    _validar_comum(entrada.valor, entrada.data_aplicacao, entrada.data_resgate, entrada.ipca_anual)
    if entrada.selic_meta < 0:
        raise ValueError("a Selic não pode ser negativa")
    if entrada.tr_mensal < 0:
        raise ValueError("a TR não pode ser negativa")
    conv = conv or convencoes()
    rp = regras_poup or regras_poupanca()
    if entrada.data_aplicacao < rp.vigente_desde:
        raise ValueError(
            f"a regra simulada vale para depósitos a partir de {rp.vigente_desde:%d/%m/%Y}"
        )
    centavos = UM.scaleb(-conv.valores.casas_reais)
    aplicacao, resgate = entrada.data_aplicacao, entrada.data_resgate
    memoria: list[str] = []

    inicio = aplicacao
    if aplicacao.day in rp.dias_aniversario_no_dia_1:
        inicio = _somar_meses(aplicacao.replace(day=1), 1)
        memoria.append(
            f"Depósito no dia {aplicacao.day}: o aniversário passa para o dia 1º, e o primeiro "
            f"período começa em {inicio:%d/%m/%Y}."
        )

    taxa, passos = taxa_mensal_poupanca(entrada.selic_meta, entrada.tr_mensal, rp)
    memoria += passos

    saldo = entrada.valor
    creditos = 0
    while _somar_meses(inicio, creditos + 1) <= resgate:
        with localcontext(prec=PRECISAO):
            saldo = (saldo * (UM + taxa / CEM)).quantize(
                centavos, conv.valores.arredondamento_reais
            )
        creditos += 1
    ultimo = _somar_meses(inicio, creditos)
    proximo = _somar_meses(inicio, creditos + 1)
    memoria.append(
        f"Aniversários creditados até {resgate:%d/%m/%Y}: {creditos} (saldo arredondado em "
        f"centavos a cada crédito)."
    )
    if resgate > max(ultimo, aplicacao):
        memoria.append(
            f"Os {(resgate - max(ultimo, aplicacao)).days} dias desde "
            f"{max(ultimo, aplicacao):%d/%m/%Y} não rendem: o próximo aniversário seria "
            f"{proximo:%d/%m/%Y}."
        )
    with localcontext(prec=PRECISAO):
        fator = (saldo / entrada.valor).quantize(
            UM.scaleb(-conv.cdi.casas_fator_acumulado), conv.cdi.arredondamento_fator
        )

    return _fechar(
        _Contexto(
            tipo="poupanca",
            valor=entrada.valor,
            aplicacao=aplicacao,
            resgate=resgate,
            dias_corridos=(resgate - aplicacao).days,
            dias_uteis=dias_uteis_entre(aplicacao, resgate),
            fator=fator,
            ipca_anual=entrada.ipca_anual,
            memoria=memoria,
            premissas=[
                f"Poupança: {rp.fonte}; depósitos a partir de {rp.vigente_desde:%d/%m/%Y}.",
                f"Selic meta constante em {formatar_percentual(entrada.selic_meta)} a.a. e TR "
                f"constante em {formatar_percentual(entrada.tr_mensal)} a.m. durante todo o "
                "prazo.",
                "Rendimento creditado só no aniversário mensal; resgate antes do aniversário "
                "perde o rendimento do mês em curso.",
                "Datas da poupança não passam para o dia útil seguinte: aniversário e resgate "
                "valem em qualquer dia.",
                "Depósito único, sem saques no período (a remuneração incide sobre o menor "
                "saldo do período).",
            ],
            regras=regras or regras_tributacao(),
            conv=conv,
            datas_ajustadas=False,
        )
    )
