"""Taxas equivalentes: entre períodos, nominal × real e isento × tributado.

Todas as taxas estão em pontos percentuais (1 = 1%).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from typing import Literal

from calc_financeira_br.calculos.calendario import dias_uteis_entre, proximo_dia_util
from calc_financeira_br.calculos.tributos import aliquota_ir
from calc_financeira_br.formatacao import formatar_decimal, formatar_percentual, quantizar

UM = Decimal(1)
CEM = Decimal(100)
PRECISAO = 50

UnidadePeriodo = Literal["a.a.", "a.s.", "a.t.", "a.m.", "a.d.u."]
UnidadeTaxa = UnidadePeriodo | Literal["%cdi"]
Sentido = Literal["isento_para_tributado", "tributado_para_isento"]

# Fração do ano de cada unidade. Dia útil na base 252, como o CDI.
FRACAO_DO_ANO: dict[UnidadePeriodo, Fraction] = {
    "a.a.": Fraction(1),
    "a.s.": Fraction(1, 2),
    "a.t.": Fraction(1, 4),
    "a.m.": Fraction(1, 12),
    "a.d.u.": Fraction(1, 252),
}

NOME_UNIDADE: dict[UnidadePeriodo, str] = {
    "a.a.": "ao ano",
    "a.s.": "ao semestre",
    "a.t.": "ao trimestre",
    "a.m.": "ao mês",
    "a.d.u.": "ao dia útil",
}


@dataclass(frozen=True)
class Equivalencia:
    taxa: Decimal
    memoria: list[str] = field(default_factory=list)
    premissas: list[str] = field(default_factory=list)


def _pct(valor: Decimal) -> str:
    return formatar_percentual(valor, casas=6)


def _expoente(fracao: Fraction) -> Decimal:
    return Decimal(fracao.numerator) / Decimal(fracao.denominator)


def converter_periodo(taxa: Decimal, de: UnidadePeriodo, para: UnidadePeriodo) -> Equivalencia:
    """Juros compostos: (1 + i)^(n_destino / n_origem) − 1."""
    if taxa <= -CEM:
        raise ValueError("a taxa deve ser maior que -100%")
    razao = FRACAO_DO_ANO[para] / FRACAO_DO_ANO[de]
    with localcontext(prec=PRECISAO):
        resultado = ((UM + taxa / CEM) ** _expoente(razao) - UM) * CEM
    expoente = f"{razao.numerator}/{razao.denominator}" if razao.denominator != 1 else str(razao)
    return Equivalencia(
        resultado,
        [f"(1 + {_pct(taxa)})^({expoente}) − 1 = {_pct(resultado)} {para} ({NOME_UNIDADE[para]})."],
        [
            "Juros compostos.",
            "Ano com 12 meses e 252 dias úteis (21 dias úteis por mês).",
        ],
    )


def nominal_para_real(taxa_nominal: Decimal, inflacao: Decimal) -> Equivalencia:
    """Equação de Fisher: (1 + nominal) / (1 + inflação) − 1."""
    _validar_inflacao(inflacao)
    with localcontext(prec=PRECISAO):
        real = ((UM + taxa_nominal / CEM) / (UM + inflacao / CEM) - UM) * CEM
    return Equivalencia(
        real,
        [f"(1 + {_pct(taxa_nominal)}) / (1 + {_pct(inflacao)}) − 1 = {_pct(real)} (taxa real)."],
        ["Equação de Fisher; taxa e inflação no mesmo período."],
    )


def real_para_nominal(taxa_real: Decimal, inflacao: Decimal) -> Equivalencia:
    """Equação de Fisher: (1 + real) × (1 + inflação) − 1."""
    _validar_inflacao(inflacao)
    with localcontext(prec=PRECISAO):
        nominal = ((UM + taxa_real / CEM) * (UM + inflacao / CEM) - UM) * CEM
    return Equivalencia(
        nominal,
        [f"(1 + {_pct(taxa_real)}) × (1 + {_pct(inflacao)}) − 1 = {_pct(nominal)} (nominal)."],
        ["Equação de Fisher; taxa e inflação no mesmo período."],
    )


def _validar_inflacao(inflacao: Decimal) -> None:
    if inflacao <= -CEM:
        raise ValueError("a inflação deve ser maior que -100%")


def _validar_aliquota(aliquota_ir: Decimal) -> None:
    if not 0 <= aliquota_ir < CEM:
        raise ValueError("a alíquota de IR deve estar entre 0% e 100%")


def isento_tributado_anual(
    taxa: Decimal,
    aliquota_ir: Decimal,
    dias_uteis: int,
    sentido: Sentido,
) -> Equivalencia:
    """Taxa anual (base 252) que dá o mesmo rendimento líquido no prazo.

    Exato no prazo: o IR incide sobre o rendimento total, não sobre a taxa,
    então a conta não é só dividir por (1 − alíquota).
    """
    _validar_aliquota(aliquota_ir)
    if dias_uteis < 1:
        raise ValueError("o prazo precisa ter pelo menos 1 dia útil")
    liquido = UM - aliquota_ir / CEM
    with localcontext(prec=PRECISAO):
        anos = Decimal(dias_uteis) / 252
        rendimento = (UM + taxa / CEM) ** anos - UM
        alvo = rendimento / liquido if sentido == "isento_para_tributado" else rendimento * liquido
        resultado = ((UM + alvo) ** (UM / anos) - UM) * CEM
    origem, destino = _nomes(sentido)
    return Equivalencia(
        resultado,
        [
            f"Rendimento {origem} em {dias_uteis} dias úteis: (1 + {_pct(taxa)})^({dias_uteis}/252)"
            f" − 1 = {formatar_decimal(_q(rendimento * CEM))}%.",
            _passo_ir(sentido, aliquota_ir, alvo),
            f"Taxa equivalente no título {destino}: (1 + {formatar_decimal(_q(alvo * CEM))}%)^(252/"
            f"{dias_uteis}) − 1 = {_pct(resultado)} a.a.",
        ],
        ["Taxas anuais na base 252 dias úteis; IR sobre o rendimento total do prazo."],
    )


def isento_tributado_cdi(
    percentual_cdi: Decimal,
    aliquota_ir: Decimal,
    dias_uteis: int,
    cdi_anual: Decimal,
    sentido: Sentido,
) -> Equivalencia:
    """Percentual do CDI que dá o mesmo rendimento líquido no prazo.

    Usa o fator diário 1 + p × TDI acumulado em `dias_uteis` dias.
    Despreza os truncamentos diários (efeito abaixo de 10⁻¹⁰ no fator).
    """
    _validar_aliquota(aliquota_ir)
    if dias_uteis < 1:
        raise ValueError("o prazo precisa ter pelo menos 1 dia útil")
    liquido = UM - aliquota_ir / CEM
    with localcontext(prec=PRECISAO):
        tdi = (UM + cdi_anual / CEM) ** (UM / 252) - UM
        if tdi <= 0:
            raise ValueError("com CDI zero não há rendimento para comparar")
        rendimento = (UM + percentual_cdi / CEM * tdi) ** dias_uteis - UM
        alvo = rendimento / liquido if sentido == "isento_para_tributado" else rendimento * liquido
        resultado = ((UM + alvo) ** (UM / dias_uteis) - UM) / tdi * CEM
    origem, destino = _nomes(sentido)
    return Equivalencia(
        resultado,
        [
            f"Taxa diária do CDI a {formatar_percentual(cdi_anual)} a.a.: "
            f"{formatar_decimal(_q(tdi, 10))}.",
            f"Rendimento {origem} a {formatar_percentual(percentual_cdi)} do CDI em {dias_uteis} "
            f"dias úteis: (1 + {formatar_percentual(percentual_cdi)} × taxa diária)^{dias_uteis} "
            f"− 1 = {formatar_decimal(_q(rendimento * CEM))}%.",
            _passo_ir(sentido, aliquota_ir, alvo),
            f"Percentual do CDI equivalente no título {destino}: "
            f"((1 + rendimento)^(1/{dias_uteis}) − 1) "
            f"/ taxa diária = {formatar_percentual(resultado)} do CDI.",
        ],
        [
            f"CDI constante em {formatar_percentual(cdi_anual)} a.a. no prazo; IR sobre o "
            "rendimento total do prazo.",
            "Truncamentos diários do fator desprezados (efeito abaixo de 10⁻¹⁰).",
        ],
    )


def _nomes(sentido: str) -> tuple[str, str]:
    """(rendimento de origem, título de destino)."""
    if sentido == "isento_para_tributado":
        return "isento", "tributado"
    return "bruto tributado", "isento"


def _passo_ir(sentido: str, aliquota_ir: Decimal, alvo: Decimal) -> str:
    aliquota = formatar_percentual(aliquota_ir)
    alvo_pct = formatar_decimal(_q(alvo * CEM))
    if sentido == "isento_para_tributado":
        return (
            f"Rendimento bruto necessário para sobrar o mesmo líquido com IR de {aliquota}: "
            f"rendimento / (1 − {aliquota}) = {alvo_pct}%."
        )
    return (
        f"Rendimento líquido depois do IR de {aliquota}: "
        f"rendimento × (1 − {aliquota}) = {alvo_pct}%."
    )


def _q(valor: Decimal, casas: int = 6) -> Decimal:
    """Arredondamento só para exibir na memória de cálculo."""
    return quantizar(valor, casas, ROUND_HALF_UP)


@dataclass(frozen=True)
class EquivalenciaTributaria(Equivalencia):
    aliquota_ir: Decimal = Decimal(0)
    dias_corridos: int = 0
    dias_uteis: int = 0


def equivalente_isento_tributado(  # noqa: PLR0913, PLR0917
    taxa: Decimal,
    unidade: UnidadeTaxa,
    prazo_dias: int,
    data_inicio: date,
    sentido: Sentido,
    cdi_anual: Decimal | None = None,
) -> EquivalenciaTributaria:
    """Equivalência isento × tributado num prazo, com a alíquota de IR do prazo.

    Taxas fora de `a.a.` são levadas a `a.a.`, comparadas e trazidas de volta.
    """
    if prazo_dias < 1:
        raise ValueError("o prazo deve ter pelo menos 1 dia corrido")
    inicio = proximo_dia_util(data_inicio)
    fim = proximo_dia_util(inicio + timedelta(days=prazo_dias))
    dias_corridos = (fim - inicio).days
    dias_uteis = dias_uteis_entre(inicio, fim)
    ir = aliquota_ir("cdb", dias_corridos, inicio)
    memoria = [
        f"Prazo de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}: {dias_corridos} dias corridos e "
        f"{dias_uteis} dias úteis; IR regressivo de {formatar_percentual(ir.aliquota)}.",
    ]
    premissas = [
        "Compara só o IR; o IOF (resgates com menos de 30 dias) não entra na equivalência.",
        "Prazo contado a partir do próximo dia útil; resgate em dia não útil vai para o "
        "dia útil seguinte.",
    ]

    if unidade == "%cdi":
        if cdi_anual is None:
            raise ValueError("informe o CDI para comparar taxas em % do CDI")
        base = isento_tributado_cdi(taxa, ir.aliquota, dias_uteis, cdi_anual, sentido)
        return EquivalenciaTributaria(
            base.taxa,
            memoria + base.memoria,
            premissas + base.premissas,
            ir.aliquota,
            dias_corridos,
            dias_uteis,
        )

    anual = taxa
    if unidade != "a.a.":
        conversao = converter_periodo(taxa, unidade, "a.a.")
        anual = conversao.taxa
        memoria += conversao.memoria
        premissas += conversao.premissas
    base = isento_tributado_anual(anual, ir.aliquota, dias_uteis, sentido)
    memoria += base.memoria
    premissas += base.premissas
    resultado = base.taxa
    if unidade != "a.a.":
        volta = converter_periodo(resultado, "a.a.", unidade)
        resultado = volta.taxa
        memoria += volta.memoria
    return EquivalenciaTributaria(
        resultado,
        memoria,
        list(dict.fromkeys(premissas)),
        ir.aliquota,
        dias_corridos,
        dias_uteis,
    )
