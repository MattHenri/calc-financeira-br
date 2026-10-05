from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from calc_financeira_br.calculos.calendario import ErroCalendario
from calc_financeira_br.calculos.renda_fixa import EntradaPosCDI, fator_cdi, simular_pos_cdi
from calc_financeira_br.regras.carregar import TipoTitulo, convencoes

QUARTA = date(2026, 10, 7)
SEGUNDA = date(2026, 10, 5)


def entrada(
    tipo: TipoTitulo = "cdb",
    dias: int = 365,
    aplicacao: date = SEGUNDA,
    percentual: str = "100",
    **kwargs: object,
) -> EntradaPosCDI:
    base = EntradaPosCDI(
        tipo=tipo,
        valor=Decimal(10000),
        percentual_cdi=Decimal(percentual),
        cdi_anual=Decimal("13.65"),
        data_aplicacao=aplicacao,
        data_resgate=aplicacao + timedelta(days=dias),
    )
    return replace(base, **kwargs)  # type: ignore[arg-type]


def test_taxa_diaria_bate_com_o_cdi_diario_do_banco_central() -> None:
    # Série SGS 12 (CDI diário) publicou 0,050788% a.d. quando a 4389 marcava 13,65% a.a.
    taxa, fator_dia, _ = fator_cdi(Decimal(100), Decimal("13.65"), 0, convencoes())
    assert taxa == Decimal("0.00050788")
    assert fator_dia == Decimal("1.00050788")


def test_fator_de_um_dia_e_o_fator_diario() -> None:
    _, fator_dia, acumulado = fator_cdi(Decimal(110), Decimal("13.65"), 1, convencoes())
    assert fator_dia == Decimal("1.000558668")
    assert acumulado == fator_dia


def test_fator_truncado_em_16_casas() -> None:
    _, _, acumulado = fator_cdi(Decimal(100), Decimal("13.65"), 250, convencoes())
    assert acumulado.as_tuple().exponent == -16
    # 252 dias úteis a 100% do CDI devolvem o CDI anual (salvo o arredondamento da taxa diária).
    _, _, ano = fator_cdi(Decimal(100), Decimal("13.65"), 252, convencoes())
    assert abs(ano - Decimal("1.1365")) < Decimal("0.000001")


def test_cdb_um_ano() -> None:
    r = simular_pos_cdi(entrada(ipca_anual=Decimal("4.22")))
    assert (r.dias_corridos, r.dias_uteis) == (365, 250)
    assert r.fator_acumulado == Decimal("1.1353463608796627")
    assert r.valor_bruto == Decimal("11353.46")
    assert r.rendimento_bruto == Decimal("1353.46")
    assert r.iof == 0
    assert r.aliquota_ir == Decimal("17.5")
    assert r.ir == Decimal("236.86")  # 1353,46 × 17,5% = 236,8555 → 236,86
    assert r.valor_liquido == Decimal("11116.60")
    assert r.rentabilidade_liquida_periodo == Decimal("11.1660")
    assert r.rentabilidade_real_anual is not None


def test_iof_antes_do_ir() -> None:
    r = simular_pos_cdi(entrada(dias=10))
    assert r.aliquota_iof == 66
    assert r.iof == (r.rendimento_bruto * Decimal("0.66")).quantize(Decimal("0.01"))
    assert r.base_ir == r.rendimento_bruto - r.iof
    assert r.ir == (r.base_ir * Decimal("0.225")).quantize(Decimal("0.01"))
    assert r.valor_liquido == r.valor_bruto - r.iof - r.ir


@pytest.mark.parametrize(
    ("aplicacao", "dias", "iof"),
    [(QUARTA, 1, "96"), (QUARTA, 29, "3"), (QUARTA, 30, "0"), (SEGUNDA, 31, "0")],
)
def test_bordas_do_iof(aplicacao: date, dias: int, iof: str) -> None:
    r = simular_pos_cdi(entrada(dias=dias, aplicacao=aplicacao))
    assert r.dias_corridos == dias
    assert r.aliquota_iof == Decimal(iof)


@pytest.mark.parametrize(
    ("aplicacao", "dias", "ir"),
    [
        (QUARTA, 180, "22.5"),
        (QUARTA, 181, "20"),
        (SEGUNDA, 360, "20"),
        (SEGUNDA, 361, "17.5"),
        (QUARTA, 720, "17.5"),
        (QUARTA, 721, "15"),
    ],
)
def test_bordas_do_ir(aplicacao: date, dias: int, ir: str) -> None:
    r = simular_pos_cdi(entrada(dias=dias, aplicacao=aplicacao))
    assert r.dias_corridos == dias
    assert r.aliquota_ir == Decimal(ir)


def test_lci_curta_paga_iof_mas_nao_ir() -> None:
    r = simular_pos_cdi(entrada("lci", dias=10, percentual="90"))
    assert r.aliquota_iof == 66
    assert r.iof > 0
    assert r.regime_ir == "isento"
    assert r.ir == 0
    assert r.valor_liquido == r.valor_bruto - r.iof


def test_lca_curta_nao_paga_iof_nem_ir() -> None:
    r = simular_pos_cdi(entrada("lca", dias=10, percentual="90"))
    assert r.iof == 0
    assert r.ir == 0
    assert r.valor_liquido == r.valor_bruto
    assert any("alíquota zero de IOF" in passo for passo in r.memoria)


def test_resgate_em_feriado_vai_para_o_proximo_dia_util() -> None:
    feriado = date(2026, 11, 20)  # sexta, Consciência Negra
    no_feriado = simular_pos_cdi(entrada(data_resgate=feriado))
    na_segunda = simular_pos_cdi(entrada(data_resgate=date(2026, 11, 23)))
    assert no_feriado.data_resgate == date(2026, 11, 23)
    assert no_feriado.valor_liquido == na_segunda.valor_liquido
    assert no_feriado.dias_corridos == na_segunda.dias_corridos == 49
    assert "20/11/2026 (dia não útil)" in no_feriado.memoria[0]


def test_aplicacao_no_fim_de_semana_vai_para_o_proximo_dia_util() -> None:
    r = simular_pos_cdi(entrada(data_aplicacao=date(2026, 10, 10), data_resgate=date(2027, 1, 4)))
    assert r.data_aplicacao == date(2026, 10, 13)  # sábado → pula domingo e feriado de 12/10


def test_prazo_nulo_depois_do_ajuste_e_erro() -> None:
    with pytest.raises(ValueError, match="prazo ficou nulo"):
        simular_pos_cdi(entrada(data_aplicacao=date(2026, 10, 10), data_resgate=date(2026, 10, 12)))


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("valor", Decimal(0), "valor aplicado"),
        ("percentual_cdi", Decimal(0), "percentual"),
        ("cdi_anual", Decimal(-1), "negativo"),
        ("data_resgate", SEGUNDA, "posterior"),
        ("ipca_anual", Decimal(-100), "inflação"),
    ],
)
def test_entradas_invalidas(campo: str, valor: Any, mensagem: str) -> None:
    with pytest.raises(ValueError, match=mensagem):
        simular_pos_cdi(replace(entrada(), **{campo: valor}))


def test_data_fora_do_calendario_e_erro() -> None:
    with pytest.raises(ErroCalendario):
        simular_pos_cdi(entrada(data_resgate=date(2031, 3, 3)))


def test_rentabilidade_real() -> None:
    r = simular_pos_cdi(entrada(ipca_anual=Decimal("4.22")))
    anual, real = r.rentabilidade_liquida_anual, r.rentabilidade_real_anual
    assert real is not None
    esperado = ((1 + anual / 100) / Decimal("1.0422") - 1) * 100
    assert abs(real - esperado) < Decimal("0.0001")
    assert simular_pos_cdi(entrada()).rentabilidade_real_anual is None


def test_memoria_tem_cada_etapa() -> None:
    r = simular_pos_cdi(entrada(ipca_anual=Decimal("4.22")))
    texto = "\n".join(r.memoria)
    for trecho in (
        "365 dias corridos e 250 dias úteis",
        "0,00050788",
        "1,1353463608796627",
        "R$ 11.353,46",
        "IOF:",
        "17,5%",
        "R$ 11.116,60",
        "Rentabilidade real",
    ):
        assert trecho in texto
