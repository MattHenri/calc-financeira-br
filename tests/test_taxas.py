from datetime import date, timedelta
from decimal import Decimal

import pytest

from calc_financeira_br.calculos.renda_fixa import EntradaPosCDI, simular_pos_cdi
from calc_financeira_br.calculos.taxas import (
    converter_periodo,
    equivalente_isento_tributado,
    isento_tributado_anual,
    nominal_para_real,
    real_para_nominal,
)

INICIO = date(2026, 10, 5)
CENTAVOS = Decimal("0.01")


def q6(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.000001"))


@pytest.mark.parametrize(
    ("taxa", "de", "para", "esperado"),
    [
        ("1", "a.m.", "a.a.", "12.682503"),  # (1,01)^12 − 1
        ("12", "a.a.", "a.m.", "0.948879"),  # 1,12^(1/12) − 1
        ("13.65", "a.a.", "a.d.u.", "0.050788"),  # CDI diário publicado pelo BC (série 12)
        ("10", "a.s.", "a.a.", "21"),  # 1,1² − 1
        ("3", "a.t.", "a.s.", "6.09"),  # 1,03² − 1
        ("7", "a.a.", "a.a.", "7"),
    ],
)
def test_converter_periodo(taxa: str, de: str, para: str, esperado: str) -> None:
    resultado = converter_periodo(Decimal(taxa), de, para)  # type: ignore[arg-type]
    assert q6(resultado.taxa) == Decimal(esperado)


def test_ida_e_volta_entre_periodos() -> None:
    mensal = converter_periodo(Decimal("13.65"), "a.a.", "a.m.").taxa
    assert q6(converter_periodo(mensal, "a.m.", "a.a.").taxa) == Decimal("13.65")


def test_taxa_negativa_ate_menos_cem() -> None:
    assert converter_periodo(Decimal(-5), "a.a.", "a.m.").taxa < 0
    with pytest.raises(ValueError, match="-100%"):
        converter_periodo(Decimal(-100), "a.a.", "a.m.")


def test_nominal_e_real() -> None:
    real = nominal_para_real(Decimal(10), Decimal(4)).taxa
    assert q6(real) == Decimal("5.769231")  # 1,10 / 1,04 − 1
    assert q6(real_para_nominal(real, Decimal(4)).taxa) == Decimal(10)
    assert q6(nominal_para_real(Decimal(3), Decimal(5)).taxa) == Decimal("-1.904762")


def test_inflacao_invalida() -> None:
    with pytest.raises(ValueError, match="inflação"):
        nominal_para_real(Decimal(10), Decimal(-100))


def test_isento_tributado_anual_nao_e_divisao_simples() -> None:
    # 12% a.a. isento por 2 anos, IR de 15%: a regra de bolso daria 12 / 0,85 = 14,1176%.
    resultado = isento_tributado_anual(Decimal(12), Decimal(15), 504, "isento_para_tributado")
    # Conta independente: sqrt(1 + (1,12² − 1) / 0,85) − 1 = 13,986583%.
    assert q6(resultado.taxa) == Decimal("13.986583")
    volta = isento_tributado_anual(resultado.taxa, Decimal(15), 504, "tributado_para_isento")
    assert q6(volta.taxa) == Decimal(12)


def test_isento_tributado_aliquota_zero_e_identidade() -> None:
    assert (
        q6(isento_tributado_anual(Decimal(9), Decimal(0), 100, "isento_para_tributado").taxa) == 9
    )


@pytest.mark.parametrize(
    ("prazo", "aliquota"), [(90, "22.5"), (200, "20"), (365, "17.5"), (800, "15")]
)
def test_aliquota_do_prazo(prazo: int, aliquota: str) -> None:
    r = equivalente_isento_tributado(
        Decimal(90), "%cdi", prazo, INICIO, "isento_para_tributado", Decimal("13.65")
    )
    assert r.aliquota_ir == Decimal(aliquota)


@pytest.mark.parametrize("prazo", [91, 365, 730, 1100])
@pytest.mark.parametrize("percentual", ["85", "90", "100"])
def test_lci_e_cdb_equivalente_rendem_o_mesmo_liquido(prazo: int, percentual: str) -> None:
    """Prova com o simulador: LCI a p% e CDB no % equivalente dão o mesmo líquido."""
    cdi = Decimal("13.65")
    equivalente = equivalente_isento_tributado(
        Decimal(percentual), "%cdi", prazo, INICIO, "isento_para_tributado", cdi
    )
    resgate = INICIO + timedelta(days=prazo)
    lci = simular_pos_cdi(
        EntradaPosCDI("lci", Decimal(100_000), Decimal(percentual), cdi, INICIO, resgate)
    )
    cdb = simular_pos_cdi(
        EntradaPosCDI("cdb", Decimal(100_000), equivalente.taxa, cdi, INICIO, resgate)
    )
    assert cdb.dias_corridos == equivalente.dias_corridos
    assert abs(cdb.valor_liquido - lci.valor_liquido) <= 2 * CENTAVOS


def test_cdb_para_lci_equivalente() -> None:
    cdi = Decimal("13.65")
    r = equivalente_isento_tributado(
        Decimal(110), "%cdi", 730, INICIO, "tributado_para_isento", cdi
    )
    resgate = INICIO + timedelta(days=730)
    cdb = simular_pos_cdi(
        EntradaPosCDI("cdb", Decimal(100_000), Decimal(110), cdi, INICIO, resgate)
    )
    lca = simular_pos_cdi(EntradaPosCDI("lca", Decimal(100_000), r.taxa, cdi, INICIO, resgate))
    assert abs(cdb.valor_liquido - lca.valor_liquido) <= 2 * CENTAVOS


def test_isento_tributado_em_taxa_mensal_volta_para_mensal() -> None:
    r = equivalente_isento_tributado(Decimal(1), "a.m.", 730, INICIO, "isento_para_tributado")
    anual = equivalente_isento_tributado(
        converter_periodo(Decimal(1), "a.m.", "a.a.").taxa,
        "a.a.",
        730,
        INICIO,
        "isento_para_tributado",
    )
    assert q6(converter_periodo(r.taxa, "a.m.", "a.a.").taxa) == q6(anual.taxa)
    assert "a.m." in r.memoria[-1]


def test_cdi_obrigatorio_para_percentual_do_cdi() -> None:
    with pytest.raises(ValueError, match="CDI"):
        equivalente_isento_tributado(Decimal(90), "%cdi", 365, INICIO, "isento_para_tributado")


def test_prazo_invalido() -> None:
    with pytest.raises(ValueError, match="1 dia"):
        equivalente_isento_tributado(Decimal(9), "a.a.", 0, INICIO, "isento_para_tributado")
