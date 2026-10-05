"""Renda fixa pós-fixada atrelada ao CDI (CDB, LC, LCI, LCA).

Para um título a p% do CDI, o fator de cada dia útil é
    f = 1 + p × [(1 + CDI)^(1/252) − 1]
Sobre o rendimento incide o IOF (resgates com menos de 30 dias) e, depois,
o IR sobre o rendimento menos o IOF.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext

from calc_financeira_br.calculos.calendario import dias_uteis_entre, proximo_dia_util
from calc_financeira_br.calculos.tributos import aliquota_iof, aliquota_ir
from calc_financeira_br.formatacao import (
    formatar_decimal,
    formatar_percentual,
    formatar_reais,
)
from calc_financeira_br.regras.carregar import (
    Convencoes,
    RegrasTributacao,
    TipoTitulo,
    convencoes,
    regras_tributacao,
)
from calc_financeira_br.regras.feriados import FONTE as FONTE_FERIADOS

UM = Decimal(1)
CEM = Decimal(100)
PRECISAO = 50  # dígitos significativos das contas intermediárias


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
class ResultadoPosCDI:
    data_aplicacao: date
    data_resgate: date
    dias_corridos: int
    dias_uteis: int
    taxa_diaria_cdi: Decimal
    fator_diario: Decimal
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
    valor_liquido: Decimal
    rendimento_liquido: Decimal
    rentabilidade_bruta_periodo: Decimal
    rentabilidade_liquida_periodo: Decimal
    rentabilidade_liquida_anual: Decimal
    rentabilidade_real_anual: Decimal | None
    memoria: list[str] = field(default_factory=list)
    premissas: list[str] = field(default_factory=list)


def _validar(entrada: EntradaPosCDI) -> None:
    if entrada.valor <= 0:
        raise ValueError("o valor aplicado deve ser positivo")
    if entrada.percentual_cdi <= 0:
        raise ValueError("o percentual do CDI deve ser positivo")
    if entrada.cdi_anual < 0:
        raise ValueError("o CDI não pode ser negativo")
    if entrada.data_resgate <= entrada.data_aplicacao:
        raise ValueError("a data de resgate deve ser posterior à data de aplicação")
    if entrada.ipca_anual is not None and entrada.ipca_anual <= -CEM:
        raise ValueError("a inflação anual deve ser maior que -100%")


def _ajustar_datas(entrada: EntradaPosCDI) -> tuple[date, date, list[str]]:
    aplicacao = proximo_dia_util(entrada.data_aplicacao)
    resgate = proximo_dia_util(entrada.data_resgate)
    passos = []
    if aplicacao != entrada.data_aplicacao:
        passos.append(
            f"Aplicação em {entrada.data_aplicacao:%d/%m/%Y} (dia não útil) passa para "
            f"o próximo dia útil: {aplicacao:%d/%m/%Y}."
        )
    if resgate != entrada.data_resgate:
        passos.append(
            f"Resgate em {entrada.data_resgate:%d/%m/%Y} (dia não útil) passa para "
            f"o próximo dia útil: {resgate:%d/%m/%Y}."
        )
    if resgate <= aplicacao:
        raise ValueError("depois do ajuste para dias úteis, o prazo ficou nulo")
    return aplicacao, resgate, passos


def fator_cdi(
    percentual_cdi: Decimal, cdi_anual: Decimal, dias_uteis: int, conv: Convencoes
) -> tuple[Decimal, Decimal, Decimal]:
    """(taxa diária do CDI, fator diário, fator acumulado) com as convenções da B3.

    A taxa diária é arredondada; o fator diário e o acumulado são truncados a cada dia útil.
    """
    c = conv.cdi
    casas_taxa = UM.scaleb(-c.casas_taxa_diaria)
    casas_fator = UM.scaleb(-c.casas_fator_acumulado)
    with localcontext(prec=PRECISAO):
        taxa_diaria = (UM + cdi_anual / CEM) ** (UM / c.base_dias_uteis) - UM
        taxa_diaria = taxa_diaria.quantize(casas_taxa, c.arredondamento_taxa_diaria)
        fator_diario = (UM + taxa_diaria * percentual_cdi / CEM).quantize(
            casas_fator, c.arredondamento_fator
        )
        acumulado = UM
        for _ in range(dias_uteis):
            acumulado = (acumulado * fator_diario).quantize(casas_fator, c.arredondamento_fator)
    return taxa_diaria, fator_diario, acumulado


def simular_pos_cdi(
    entrada: EntradaPosCDI,
    regras: RegrasTributacao | None = None,
    conv: Convencoes | None = None,
) -> ResultadoPosCDI:
    _validar(entrada)
    regras = regras or regras_tributacao()
    conv = conv or convencoes()
    v = conv.valores
    centavos = UM.scaleb(-v.casas_reais)
    casas_pct = UM.scaleb(-v.casas_percentuais)

    def reais(valor: Decimal) -> Decimal:
        return valor.quantize(centavos, v.arredondamento_reais)

    def pct(valor: Decimal) -> Decimal:
        return valor.quantize(casas_pct, v.arredondamento_reais)

    tipo = entrada.tipo.upper()
    p = entrada.percentual_cdi
    aplicacao, resgate, memoria = _ajustar_datas(entrada)
    dias_corridos = (resgate - aplicacao).days
    dias_uteis = dias_uteis_entre(aplicacao, resgate)
    memoria.append(
        f"Prazo de {aplicacao:%d/%m/%Y} a {resgate:%d/%m/%Y}: {dias_corridos} dias corridos "
        f"e {dias_uteis} dias úteis (conta o dia da aplicação, não conta o do resgate)."
    )

    taxa_diaria, fator_diario, fator = fator_cdi(p, entrada.cdi_anual, dias_uteis, conv)
    base = conv.cdi.base_dias_uteis
    memoria += [
        f"Taxa diária do CDI: (1 + {formatar_percentual(entrada.cdi_anual)})^(1/{base}) − 1 "
        f"= {formatar_decimal(taxa_diaria)} ({conv.cdi.casas_taxa_diaria} casas).",
        f"Fator diário a {formatar_percentual(p)} do CDI: 1 + {formatar_decimal(taxa_diaria)} "
        f"× {formatar_percentual(p)} = {formatar_decimal(fator_diario.normalize())}.",
        f"Fator acumulado em {dias_uteis} dias úteis: {formatar_decimal(fator)} "
        f"(truncado em {conv.cdi.casas_fator_acumulado} casas a cada dia).",
    ]

    bruto = reais(entrada.valor * fator)
    rendimento = bruto - entrada.valor
    memoria.append(
        f"Valor bruto: {formatar_reais(entrada.valor)} × {formatar_decimal(fator)} = "
        f"{formatar_reais(bruto)}; rendimento bruto de {formatar_reais(rendimento)}."
    )

    taxa_iof = aliquota_iof(entrada.tipo, dias_corridos, regras)
    iof = reais(rendimento * taxa_iof / CEM)
    if entrada.tipo not in regras.iof.tipos:
        memoria.append(f"IOF: {tipo} tem alíquota zero de IOF = {formatar_reais(iof)}.")
    else:
        memoria.append(
            f"IOF: resgate com {dias_corridos} dias corridos → {formatar_percentual(taxa_iof)} "
            f"do rendimento = {formatar_reais(iof)}."
        )

    ir_info = aliquota_ir(entrada.tipo, dias_corridos, aplicacao, regras)
    base_ir = rendimento - iof
    ir = reais(base_ir * ir_info.aliquota / CEM)
    if ir_info.regime == "isento":
        memoria.append(f"IR: {tipo} é isento de IR para pessoa física = {formatar_reais(ir)}.")
    else:
        memoria.append(
            f"IR: tabela regressiva, {dias_corridos} dias corridos → "
            f"{formatar_percentual(ir_info.aliquota)} sobre (rendimento − IOF) "
            f"{formatar_reais(base_ir)} = {formatar_reais(ir)}."
        )

    liquido = bruto - iof - ir
    rendimento_liquido = liquido - entrada.valor
    memoria.append(
        f"Valor líquido: {formatar_reais(bruto)} − {formatar_reais(iof)} (IOF) − "
        f"{formatar_reais(ir)} (IR) = {formatar_reais(liquido)}."
    )

    with localcontext(prec=PRECISAO):
        rent_bruta = (bruto / entrada.valor - UM) * CEM
        rent_liquida = (liquido / entrada.valor - UM) * CEM
        rent_anual = ((liquido / entrada.valor) ** (Decimal(base) / dias_uteis) - UM) * CEM
        rent_real = None
        if entrada.ipca_anual is not None:
            rent_real = ((UM + rent_anual / CEM) / (UM + entrada.ipca_anual / CEM) - UM) * CEM
    memoria.append(
        f"Rentabilidade líquida: {formatar_percentual(rent_liquida)} no período, "
        f"{formatar_percentual(rent_anual)} a.a. (base {base} dias úteis)."
    )
    if rent_real is not None and entrada.ipca_anual is not None:
        memoria.append(
            f"Rentabilidade real: (1 + {formatar_percentual(rent_anual)}) / "
            f"(1 + {formatar_percentual(entrada.ipca_anual)}) − 1 = "
            f"{formatar_percentual(rent_real)} a.a."
        )

    premissas = [
        f"CDI constante em {formatar_percentual(entrada.cdi_anual)} a.a. durante todo o prazo.",
        f"Dias úteis: {FONTE_FERIADOS} (só feriados nacionais).",
        "Data de aplicação ou de resgate em dia não útil passa para o próximo dia útil.",
        f"Convenção B3: taxa diária do CDI com {conv.cdi.casas_taxa_diaria} casas "
        f"(arredondada); fatores truncados em {conv.cdi.casas_fator_acumulado} casas.",
        f"Valores em reais com {v.casas_reais} casas ({v.arredondamento_reais}).",
        "IR e IOF contam dias corridos entre aplicação e resgate; o IOF é calculado antes "
        "do IR e sai da base do IR.",
        f"IR: {regras.ir.fonte}.",
        f"IOF: {regras.iof.fonte}.",
        f"Rentabilidade anual na base {base} dias úteis.",
    ]
    if entrada.ipca_anual is not None:
        premissas.append(
            f"Inflação constante em {formatar_percentual(entrada.ipca_anual)} a.a. "
            "para a rentabilidade real."
        )

    return ResultadoPosCDI(
        data_aplicacao=aplicacao,
        data_resgate=resgate,
        dias_corridos=dias_corridos,
        dias_uteis=dias_uteis,
        taxa_diaria_cdi=taxa_diaria,
        fator_diario=fator_diario,
        fator_acumulado=fator,
        valor_aplicado=entrada.valor,
        valor_bruto=bruto,
        rendimento_bruto=rendimento,
        aliquota_iof=taxa_iof,
        iof=iof,
        regime_ir=ir_info.regime,
        aliquota_ir=ir_info.aliquota,
        base_ir=base_ir,
        ir=ir,
        valor_liquido=liquido,
        rendimento_liquido=rendimento_liquido,
        rentabilidade_bruta_periodo=pct(rent_bruta),
        rentabilidade_liquida_periodo=pct(rent_liquida),
        rentabilidade_liquida_anual=pct(rent_anual),
        rentabilidade_real_anual=None if rent_real is None else pct(rent_real),
        memoria=memoria,
        premissas=premissas,
    )
