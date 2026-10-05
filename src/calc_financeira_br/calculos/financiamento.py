"""Financiamento pelos sistemas SAC e Price, com amortizações extras e CET.

CET pela Resolução CMN 4.881/2020, art. 4º:
    Σ FCj / (1 + CET)^((dj − d0) / 365) − FC0 = 0
"""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from calc_financeira_br.formatacao import formatar_decimal, formatar_percentual, formatar_reais

Sistema = Literal["sac", "price"]
UnidadeJuros = Literal["a.m.", "a.a.", "a.a.nominal"]
EfeitoAmortizacao = Literal["prazo", "parcela"]

UM = Decimal(1)
CEM = Decimal(100)
ZERO = Decimal(0)
CENTAVO = Decimal("0.01")
PRECISAO = 50
FONTE_CET = "Resolução CMN 4.881/2020, art. 4º"


def _reais(valor: Decimal) -> Decimal:
    with localcontext(prec=PRECISAO):
        return valor.quantize(CENTAVO, ROUND_HALF_UP)


@dataclass(frozen=True)
class AmortizacaoExtra:
    mes: int
    """Número da parcela junto com a qual o valor extra é pago."""
    valor: Decimal
    efeito: EfeitoAmortizacao
    """'prazo' mantém a prestação e encurta o prazo; 'parcela' reduz a prestação."""


@dataclass(frozen=True)
class EntradaFinanciamento:
    valor_financiado: Decimal
    taxa_juros: Decimal
    unidade_taxa: UnidadeJuros
    prazo_meses: int
    sistema: Sistema
    data_contratacao: date
    data_primeira_parcela: date | None = None
    tarifas_iniciais: Decimal = ZERO
    """Pagas na contratação (saem do valor liberado no CET)."""
    tributos_iniciais: Decimal = ZERO
    """Ex.: IOF informado pelo usuário, pago na contratação."""
    tarifa_mensal: Decimal = ZERO
    seguro_mensal: Decimal = ZERO
    """Seguro fixo por parcela, em reais."""
    seguro_percentual_saldo: Decimal = ZERO
    """Seguro mensal em % do saldo devedor no início do mês (ex.: MIP)."""
    amortizacoes_extras: tuple[AmortizacaoExtra, ...] = ()


@dataclass(frozen=True)
class Parcela:
    numero: int
    data: date
    saldo_inicial: Decimal
    juros: Decimal
    amortizacao: Decimal
    prestacao: Decimal
    """Juros + amortização."""
    seguro: Decimal
    tarifa: Decimal
    amortizacao_extra: Decimal
    pagamento_total: Decimal
    """Prestação + seguro + tarifa + amortização extra."""
    saldo_final: Decimal


@dataclass(frozen=True)
class EfeitoAmortizacaoExtra:
    mes: int
    valor_pago: Decimal
    efeito: EfeitoAmortizacao
    juros_economizados: Decimal
    meses_a_menos: int
    prestacao_antes: Decimal
    """Prestação do mês seguinte sem esta amortização."""
    prestacao_depois: Decimal
    """Prestação do mês seguinte com esta amortização (zero se quitou)."""


@dataclass(frozen=True)
class ResultadoFinanciamento:
    taxa_mensal: Decimal
    parcelas: list[Parcela]
    prazo_efetivo_meses: int
    total_juros: Decimal
    total_amortizado: Decimal
    total_seguros: Decimal
    total_tarifas: Decimal
    total_pago: Decimal
    """Tudo o que sai do bolso: parcelas, extras, tarifas e tributos iniciais."""
    cet_anual: Decimal
    cet_mensal: Decimal
    juros_sem_extras: Decimal
    efeitos: list[EfeitoAmortizacaoExtra] = field(default_factory=list)
    memoria: list[str] = field(default_factory=list)
    premissas: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------ utilidades


def somar_meses(dia: date, meses: int) -> date:
    """Mesmo dia `meses` depois; se o mês não tiver o dia, o último dia do mês."""
    total = dia.month - 1 + meses
    ano, mes = dia.year + total // 12, total % 12 + 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def taxa_mensal(taxa: Decimal, unidade: UnidadeJuros) -> tuple[Decimal, str]:
    """Taxa mensal em fração (0.01 = 1%) e a explicação da conversão."""
    with localcontext(prec=PRECISAO):
        if unidade == "a.m.":
            return taxa / CEM, f"Taxa de {formatar_percentual(taxa)} a.m."
        if unidade == "a.a.nominal":
            mensal = taxa / CEM / 12
            return mensal, (
                f"Taxa nominal de {formatar_percentual(taxa)} a.a. com capitalização mensal: "
                f"{formatar_percentual(taxa)} / 12 = {formatar_percentual(mensal * CEM, 6)} a.m."
            )
        mensal = (UM + taxa / CEM) ** (UM / 12) - UM
        return mensal, (
            f"Taxa efetiva de {formatar_percentual(taxa)} a.a.: (1 + {formatar_percentual(taxa)})"
            f"^(1/12) − 1 = {formatar_percentual(mensal * CEM, 6)} a.m."
        )


def prestacao_price(saldo: Decimal, taxa: Decimal, meses: int) -> Decimal:
    """PMT = saldo × i / (1 − (1 + i)^−n), em centavos."""
    with localcontext(prec=PRECISAO):
        if taxa == 0:
            return _reais(saldo / meses)
        return _reais(saldo * taxa / (UM - (UM + taxa) ** -meses))


def _validar(entrada: EntradaFinanciamento) -> None:
    if entrada.valor_financiado <= 0:
        raise ValueError("o valor financiado deve ser positivo")
    if entrada.taxa_juros < 0:
        raise ValueError("a taxa de juros não pode ser negativa")
    if entrada.prazo_meses < 1:
        raise ValueError("o prazo deve ter pelo menos 1 mês")
    for nome in ("tarifas_iniciais", "tributos_iniciais", "tarifa_mensal", "seguro_mensal"):
        if getattr(entrada, nome) < 0:
            raise ValueError(f"{nome} não pode ser negativo")
    if entrada.seguro_percentual_saldo < 0:
        raise ValueError("o seguro sobre o saldo não pode ser negativo")
    primeira = entrada.data_primeira_parcela
    if primeira is not None and primeira <= entrada.data_contratacao:
        raise ValueError("a primeira parcela deve vencer depois da contratação")
    meses = [extra.mes for extra in entrada.amortizacoes_extras]
    if len(meses) != len(set(meses)):
        raise ValueError("informe no máximo uma amortização extra por mês")
    for extra in entrada.amortizacoes_extras:
        if not 1 <= extra.mes <= entrada.prazo_meses:
            raise ValueError(f"amortização extra no mês {extra.mes}: fora do prazo")
        if extra.valor <= 0:
            raise ValueError(f"amortização extra no mês {extra.mes}: valor deve ser positivo")


# ------------------------------------------------------------------------- tabela


def _meses_para_quitar(
    saldo: Decimal, taxa: Decimal, sistema: Sistema, pmt: Decimal, amortizacao_sac: Decimal
) -> int:
    """Quantas parcelas faltam mantendo a prestação (Price) ou a amortização (SAC)."""
    meses = 0
    while saldo > 0:
        meses += 1
        amortizacao = pmt - _reais(saldo * taxa) if sistema == "price" else amortizacao_sac
        if amortizacao <= 0:
            raise ValueError("a prestação não cobre os juros do saldo")
        saldo -= min(amortizacao, saldo)
    return meses


def gerar_tabela(entrada: EntradaFinanciamento, taxa: Decimal) -> list[Parcela]:
    """Tabela de parcelas. Juros e prestações arredondados em centavos a cada mês."""
    extras = {extra.mes: extra for extra in entrada.amortizacoes_extras}
    # Vencimentos contados a partir da âncora para não perder o dia (31/01 → 28/02 → 31/03).
    if entrada.data_primeira_parcela is not None:
        ancora, deslocamento = entrada.data_primeira_parcela, -1
    else:
        ancora, deslocamento = entrada.data_contratacao, 0
    n = entrada.prazo_meses
    saldo = entrada.valor_financiado
    pmt = prestacao_price(saldo, taxa, n)
    amortizacao_sac = _reais(saldo / n)
    parcelas: list[Parcela] = []
    numero = 0
    fim = n  # última parcela planejada; amortizações que reduzem o prazo a antecipam
    while saldo > 0:
        numero += 1
        if numero > n:  # salvaguarda: extras só encurtam o prazo
            raise AssertionError("o saldo não zerou no prazo contratado")
        juros = _reais(saldo * taxa)
        amortizacao = pmt - juros if entrada.sistema == "price" else amortizacao_sac
        if numero == fim or amortizacao >= saldo:
            amortizacao = saldo  # última parcela absorve os centavos de arredondamento
        restante = saldo - amortizacao
        extra = extras.get(numero)
        valor_extra = min(extra.valor, restante) if extra else ZERO
        saldo_final = restante - valor_extra
        seguro = entrada.seguro_mensal + _reais(saldo * entrada.seguro_percentual_saldo / CEM)
        prestacao = juros + amortizacao
        parcelas.append(
            Parcela(
                numero=numero,
                data=somar_meses(ancora, numero + deslocamento),
                saldo_inicial=saldo,
                juros=juros,
                amortizacao=amortizacao,
                prestacao=prestacao,
                seguro=seguro,
                tarifa=entrada.tarifa_mensal,
                amortizacao_extra=valor_extra,
                pagamento_total=prestacao + seguro + entrada.tarifa_mensal + valor_extra,
                saldo_final=saldo_final,
            )
        )
        if extra and saldo_final > 0:
            if extra.efeito == "parcela":
                restantes = fim - numero
                pmt = prestacao_price(saldo_final, taxa, restantes)
                amortizacao_sac = _reais(saldo_final / restantes)
            else:
                fim = numero + _meses_para_quitar(
                    saldo_final, taxa, entrada.sistema, pmt, amortizacao_sac
                )
        saldo = saldo_final
    return parcelas


# ---------------------------------------------------------------------------- CET


def calcular_cet(
    valor_liberado: Decimal, fluxos: Sequence[tuple[date, Decimal]], data_liberacao: date
) -> Decimal:
    """Taxa anual (fração) que zera Σ FCj / (1 + CET)^((dj − d0)/365) − FC0.

    Newton com salvaguarda de bisseção no intervalo [−99%, 100.000%] a.a.
    """
    if valor_liberado <= 0:
        raise ValueError("o valor liberado (crédito menos tarifas e tributos iniciais) é nulo")
    with localcontext(prec=PRECISAO):
        prazos = [(Decimal((d - data_liberacao).days) / 365, fc) for d, fc in fluxos]

        def f(r: Decimal) -> Decimal:
            return sum((fc / (UM + r) ** t for t, fc in prazos), ZERO) - valor_liberado

        def derivada(r: Decimal) -> Decimal:
            return sum((-t * fc / (UM + r) ** (t + 1) for t, fc in prazos), ZERO)

        baixo, alto = Decimal("-0.99"), Decimal(1000)
        if f(baixo) < 0 or f(alto) > 0:
            raise ValueError("não foi possível calcular o CET com esse fluxo de pagamentos")
        r = Decimal("0.1")
        for _ in range(200):
            valor = f(r)
            if abs(valor) < Decimal("1e-20"):
                break
            if valor > 0:
                baixo = r
            else:
                alto = r
            d = derivada(r)
            proximo = r - valor / d if d != 0 else (baixo + alto) / 2
            if not baixo < proximo < alto:
                proximo = (baixo + alto) / 2
            if abs(proximo - r) < Decimal("1e-24"):
                r = proximo
                break
            r = proximo
    return r


# ------------------------------------------------------------------------ simulação


def _sem_extras(entrada: EntradaFinanciamento) -> EntradaFinanciamento:
    return replace(entrada, amortizacoes_extras=())


def simular_financiamento(entrada: EntradaFinanciamento) -> ResultadoFinanciamento:
    _validar(entrada)
    taxa, passo_taxa = taxa_mensal(entrada.taxa_juros, entrada.unidade_taxa)
    parcelas = gerar_tabela(entrada, taxa)
    contratadas = gerar_tabela(_sem_extras(entrada), taxa)

    total_juros = sum((p.juros for p in parcelas), ZERO)
    total_amortizado = sum((p.amortizacao + p.amortizacao_extra for p in parcelas), ZERO)
    total_seguros = sum((p.seguro for p in parcelas), ZERO)
    total_tarifas = sum((p.tarifa for p in parcelas), ZERO)
    iniciais = entrada.tarifas_iniciais + entrada.tributos_iniciais
    total_pago = sum((p.pagamento_total for p in parcelas), ZERO) + iniciais
    juros_sem_extras = sum((p.juros for p in contratadas), ZERO)

    liberado = entrada.valor_financiado - iniciais
    cet = calcular_cet(
        liberado, [(p.data, p.pagamento_total) for p in contratadas], entrada.data_contratacao
    )
    with localcontext(prec=PRECISAO):
        cet_anual = (cet * CEM).quantize(CENTAVO, ROUND_HALF_EVEN)
        cet_mensal = (((UM + cet) ** (UM / 12) - UM) * CEM).quantize(
            Decimal("0.0001"), ROUND_HALF_EVEN
        )

    sistema = "SAC" if entrada.sistema == "sac" else "Price"
    primeira, ultima = parcelas[0], parcelas[-1]
    memoria = [passo_taxa]
    if entrada.sistema == "price":
        memoria.append(
            f"Price: prestação = {formatar_reais(entrada.valor_financiado)} × i / (1 − (1 + i)"
            f"^−{entrada.prazo_meses}) = {formatar_reais(contratadas[0].prestacao)}, constante; "
            "os juros caem e a amortização cresce a cada mês."
        )
    else:
        memoria.append(
            f"SAC: amortização constante de {formatar_reais(entrada.valor_financiado)} / "
            f"{entrada.prazo_meses} = {formatar_reais(contratadas[0].amortizacao)}; os juros "
            "incidem sobre o saldo e a prestação cai a cada mês."
        )
    memoria += [
        f"1ª prestação ({primeira.data:%d/%m/%Y}): juros {formatar_reais(primeira.juros)} + "
        f"amortização {formatar_reais(primeira.amortizacao)} = "
        f"{formatar_reais(primeira.prestacao)}.",
        f"Última prestação (nº {ultima.numero}, {ultima.data:%d/%m/%Y}): "
        f"{formatar_reais(ultima.prestacao)}; saldo final {formatar_reais(ultima.saldo_final)}.",
        f"Totais: juros {formatar_reais(total_juros)}, amortizado "
        f"{formatar_reais(total_amortizado)}, seguros {formatar_reais(total_seguros)}, tarifas "
        f"mensais {formatar_reais(total_tarifas)}; total pago {formatar_reais(total_pago)} "
        f"(inclui {formatar_reais(iniciais)} de tarifas e tributos iniciais).",
        f"CET: valor liberado {formatar_reais(entrada.valor_financiado)} − "
        f"{formatar_reais(iniciais)} = {formatar_reais(liberado)}; taxa que iguala esse valor "
        f"aos {len(contratadas)} pagamentos descontados por (1 + CET)^(dias/365) = "
        f"{formatar_decimal(cet_anual)}% a.a. ({formatar_decimal(cet_mensal)}% a.m.).",
    ]

    efeitos = _efeitos(entrada, taxa, contratadas)
    if efeitos:
        memoria.append(
            f"Com as amortizações extras: juros de {formatar_reais(total_juros)} em vez de "
            f"{formatar_reais(juros_sem_extras)} ({formatar_reais(juros_sem_extras - total_juros)} "
            f"a menos), quitação em {len(parcelas)} meses em vez de {len(contratadas)}."
        )
        for e in efeitos:
            mudanca = (
                f"{e.meses_a_menos} meses a menos"
                if e.efeito == "prazo"
                else f"prestação seguinte de {formatar_reais(e.prestacao_antes)} para "
                f"{formatar_reais(e.prestacao_depois)}"
            )
            memoria.append(
                f"Extra no mês {e.mes} ({formatar_reais(e.valor_pago)}, reduzindo {e.efeito}): "
                f"{formatar_reais(e.juros_economizados)} de juros a menos; {mudanca}."
            )

    premissas = [
        f"Sistema {sistema}; juros e prestações arredondados em centavos (ROUND_HALF_UP) a "
        "cada mês; a última parcela absorve a diferença de arredondamento.",
        "Parcelas mensais, a primeira um mês após a contratação (salvo data informada); "
        "em meses sem o dia do vencimento, vale o último dia do mês.",
        "Sem correção monetária do saldo (ex.: TR): taxa de juros fixa durante todo o prazo.",
        f"CET: {FONTE_CET}; dias corridos / 365; % a.a. com 2 casas pela NBR 5891 "
        "(ROUND_HALF_EVEN). Calculado sobre o fluxo contratado, sem as amortizações extras, "
        "que são opcionais.",
        "Tarifas e tributos iniciais pagos na contratação (saem do valor liberado no CET); "
        "IOF de crédito não é calculado, só entra se informado.",
    ]
    if entrada.seguro_percentual_saldo:
        premissas.append(
            f"Seguro de {formatar_percentual(entrada.seguro_percentual_saldo, 6)} a.m. sobre o "
            "saldo devedor no início de cada mês."
        )
    if entrada.amortizacoes_extras:
        premissas.append(
            "Amortização extra paga junto com a parcela do mês, depois da amortização normal; "
            "'prazo' mantém a prestação (ou a amortização, no SAC) e encurta o prazo; "
            "'parcela' mantém o prazo e recalcula a prestação."
        )

    return ResultadoFinanciamento(
        taxa_mensal=taxa,
        parcelas=parcelas,
        prazo_efetivo_meses=len(parcelas),
        total_juros=total_juros,
        total_amortizado=total_amortizado,
        total_seguros=total_seguros,
        total_tarifas=total_tarifas,
        total_pago=total_pago,
        cet_anual=cet_anual,
        cet_mensal=cet_mensal,
        juros_sem_extras=juros_sem_extras,
        efeitos=efeitos,
        memoria=memoria,
        premissas=premissas,
    )


def _efeitos(
    entrada: EntradaFinanciamento, taxa: Decimal, contratadas: list[Parcela]
) -> list[EfeitoAmortizacaoExtra]:
    """Efeito marginal de cada amortização extra, na ordem dos meses."""
    extras = sorted(entrada.amortizacoes_extras, key=lambda e: e.mes)
    efeitos = []
    anterior = contratadas
    for i, extra in enumerate(extras):
        atual = gerar_tabela(replace(entrada, amortizacoes_extras=tuple(extras[: i + 1])), taxa)
        if extra.mes > len(anterior):
            break  # o financiamento já foi quitado por extras anteriores
        pago = atual[extra.mes - 1].amortizacao_extra

        def seguinte(tabela: list[Parcela], mes: int = extra.mes) -> Decimal:
            return tabela[mes].prestacao if len(tabela) > mes else ZERO

        efeitos.append(
            EfeitoAmortizacaoExtra(
                mes=extra.mes,
                valor_pago=pago,
                efeito=extra.efeito,
                juros_economizados=sum((p.juros for p in anterior), ZERO)
                - sum((p.juros for p in atual), ZERO),
                meses_a_menos=len(anterior) - len(atual),
                prestacao_antes=seguinte(anterior),
                prestacao_depois=seguinte(atual),
            )
        )
        anterior = atual
    return efeitos
