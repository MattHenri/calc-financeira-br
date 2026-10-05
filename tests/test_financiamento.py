from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext

import pytest

from calc_financeira_br.calculos.financiamento import (
    AmortizacaoExtra,
    EntradaFinanciamento,
    calcular_cet,
    prestacao_price,
    simular_financiamento,
    somar_meses,
    taxa_mensal,
)

CONTRATO = date(2026, 10, 5)


def price(**kwargs: object) -> EntradaFinanciamento:
    base = EntradaFinanciamento(Decimal(100000), Decimal(1), "a.m.", 12, "price", CONTRATO)
    return replace(base, **kwargs)  # type: ignore[arg-type]


def sac(**kwargs: object) -> EntradaFinanciamento:
    base = EntradaFinanciamento(Decimal(120000), Decimal(1), "a.m.", 12, "sac", CONTRATO)
    return replace(base, **kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------------- tabela


def test_price_prestacao_classica() -> None:
    # 100.000 a 1% a.m. em 12 meses: PMT = 8.884,88 (fórmula da Tabela Price).
    r = simular_financiamento(price())
    assert prestacao_price(Decimal(100000), Decimal("0.01"), 12) == Decimal("8884.88")
    assert [p.prestacao for p in r.parcelas[:-1]] == [Decimal("8884.88")] * 11
    assert r.parcelas[-1].prestacao == Decimal("8884.85")  # absorve o arredondamento
    assert r.parcelas[0].juros == Decimal("1000.00")
    assert r.total_amortizado == Decimal(100000)
    assert r.parcelas[-1].saldo_final == 0
    assert r.total_juros == sum(p.prestacao for p in r.parcelas) - 100000


def test_sac_conta_fechada() -> None:
    # 120.000 a 1% a.m. em 12 meses: amortização 10.000; juros = 1% × 10.000 × (12 + ... + 1).
    r = simular_financiamento(sac())
    assert {p.amortizacao for p in r.parcelas} == {Decimal(10000)}
    assert r.parcelas[0].prestacao == Decimal(11200)
    assert r.parcelas[-1].prestacao == Decimal(10100)
    assert r.total_juros == Decimal(7800)


def test_sac_paga_menos_juros_que_price() -> None:
    valor = Decimal(100000)
    r_sac = simular_financiamento(price(sistema="sac", valor_financiado=valor))
    r_price = simular_financiamento(price(valor_financiado=valor))
    assert r_sac.total_amortizado == r_price.total_amortizado == valor
    assert r_sac.total_juros < r_price.total_juros


def test_juros_zero() -> None:
    r = simular_financiamento(price(taxa_juros=Decimal(0)))
    assert r.total_juros == 0
    assert r.parcelas[0].prestacao == Decimal("8333.33")
    assert r.total_amortizado == Decimal(100000)


@pytest.mark.parametrize(
    ("taxa", "unidade", "mensal"),
    [
        ("1", "a.m.", "0.01"),
        ("12", "a.a.nominal", "0.01"),
        ("12.682503013196972066120100", "a.a.", "0.01"),
    ],
)
def test_unidades_de_taxa(taxa: str, unidade: str, mensal: str) -> None:
    resultado, _ = taxa_mensal(Decimal(taxa), unidade)  # type: ignore[arg-type]
    assert abs(resultado - Decimal(mensal)) < Decimal("1e-20")


def test_datas_das_parcelas() -> None:
    r = simular_financiamento(price(data_contratacao=date(2026, 1, 31)))
    assert r.parcelas[0].data == date(2026, 2, 28)  # fevereiro não tem dia 31
    assert r.parcelas[1].data == date(2026, 3, 31)
    assert somar_meses(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert somar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_primeira_parcela_informada() -> None:
    r = simular_financiamento(price(data_primeira_parcela=date(2027, 1, 10)))
    assert [p.data for p in r.parcelas[:2]] == [date(2027, 1, 10), date(2027, 2, 10)]


def test_seguros_e_tarifas() -> None:
    r = simular_financiamento(
        sac(
            seguro_mensal=Decimal(20),
            seguro_percentual_saldo=Decimal("0.05"),
            tarifa_mensal=Decimal(25),
        )
    )
    primeira = r.parcelas[0]
    assert primeira.seguro == Decimal(20) + Decimal(60)  # 0,05% de 120.000
    assert primeira.pagamento_total == primeira.prestacao + primeira.seguro + Decimal(25)
    assert r.total_tarifas == Decimal(300)


# ------------------------------------------------------------- amortizações extras


def test_extra_reduzindo_prazo_mantem_a_prestacao() -> None:
    r = simular_financiamento(
        price(amortizacoes_extras=(AmortizacaoExtra(3, Decimal(20000), "prazo"),))
    )
    assert r.parcelas[3].prestacao == Decimal("8884.88")
    assert r.prazo_efetivo_meses < 12
    assert r.total_amortizado == Decimal(100000)
    (efeito,) = r.efeitos
    assert efeito.meses_a_menos == 12 - r.prazo_efetivo_meses
    assert efeito.juros_economizados == r.juros_sem_extras - r.total_juros > 0


def test_extra_reduzindo_parcela_mantem_o_prazo() -> None:
    r = simular_financiamento(
        price(amortizacoes_extras=(AmortizacaoExtra(3, Decimal(20000), "parcela"),))
    )
    assert r.prazo_efetivo_meses == 12
    assert r.parcelas[3].prestacao < Decimal("8884.88")
    (efeito,) = r.efeitos
    assert efeito.prestacao_antes == Decimal("8884.88")
    assert efeito.prestacao_depois == r.parcelas[3].prestacao


def test_extra_parcela_depois_de_extra_prazo_respeita_o_novo_prazo() -> None:
    extras = (
        AmortizacaoExtra(2, Decimal(20000), "prazo"),
        AmortizacaoExtra(4, Decimal(5000), "parcela"),
    )
    so_prazo = simular_financiamento(price(amortizacoes_extras=extras[:1]))
    r = simular_financiamento(price(amortizacoes_extras=extras))
    # A segunda redução de parcela não devolve os meses ganhos com a primeira.
    assert r.prazo_efetivo_meses == so_prazo.prazo_efetivo_meses


def test_extra_maior_que_o_saldo_quita() -> None:
    r = simular_financiamento(
        sac(amortizacoes_extras=(AmortizacaoExtra(2, Decimal(10**6), "prazo"),))
    )
    assert r.prazo_efetivo_meses == 2
    assert r.parcelas[-1].amortizacao_extra == Decimal(100000)  # só o saldo restante
    assert r.parcelas[-1].saldo_final == 0


@pytest.mark.parametrize("sistema", ["sac", "price"])
def test_extras_sempre_amortizam_o_valor_exato(sistema: str) -> None:
    extras = (
        AmortizacaoExtra(1, Decimal("1234.56"), "parcela"),
        AmortizacaoExtra(5, Decimal(7000), "prazo"),
    )
    r = simular_financiamento(price(sistema=sistema, amortizacoes_extras=extras))
    assert r.total_amortizado == Decimal(100000)
    assert r.parcelas[-1].saldo_final == 0


# ---------------------------------------------------------------------------- CET


def test_cet_sem_custos_extras_e_a_taxa_efetiva() -> None:
    r = simular_financiamento(price())
    # 1% a.m. ≈ 12,68% a.a.; as datas em dias corridos mudam pouco o resultado.
    assert r.cet_anual == Decimal("12.68")


def test_cet_com_tarifas_e_seguros_fica_acima_da_taxa() -> None:
    r = simular_financiamento(price(tarifas_iniciais=Decimal(1500), seguro_mensal=Decimal(30)))
    assert r.cet_anual > Decimal("12.68")


def test_cet_zera_a_equacao_da_resolucao() -> None:
    r = simular_financiamento(price(tarifas_iniciais=Decimal(1500), tarifa_mensal=Decimal(15)))
    fluxos = [(p.data, p.pagamento_total) for p in r.parcelas]
    cet = calcular_cet(Decimal(98500), fluxos, CONTRATO)
    with localcontext(prec=50):
        residuo = sum(
            fc / (1 + cet) ** (Decimal((d - CONTRATO).days) / 365) for d, fc in fluxos
        ) - Decimal(98500)
    assert abs(residuo) < Decimal("1e-15")
    assert (cet * 100).quantize(Decimal("0.01")) == r.cet_anual


def test_cet_ignora_amortizacoes_extras() -> None:
    sem = simular_financiamento(price(tarifas_iniciais=Decimal(1500)))
    com = simular_financiamento(
        price(
            tarifas_iniciais=Decimal(1500),
            amortizacoes_extras=(AmortizacaoExtra(3, Decimal(20000), "prazo"),),
        )
    )
    assert com.cet_anual == sem.cet_anual


def test_cet_arredonda_pela_nbr_5891() -> None:
    # NBR 5891: com 5 exato seguido de zeros, arredonda para o par.
    assert Decimal("12.345").quantize(Decimal("0.01"), "ROUND_HALF_EVEN") == Decimal("12.34")
    assert Decimal("12.355").quantize(Decimal("0.01"), "ROUND_HALF_EVEN") == Decimal("12.36")


def test_tarifas_maiores_que_o_credito() -> None:
    with pytest.raises(ValueError, match="valor liberado"):
        simular_financiamento(price(tarifas_iniciais=Decimal(100000)))


# ------------------------------------------------------------------------ validação


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("valor_financiado", Decimal(0), "valor financiado"),
        ("taxa_juros", Decimal(-1), "negativa"),
        ("prazo_meses", 0, "1 mês"),
        ("tarifa_mensal", Decimal(-1), "tarifa_mensal"),
        ("data_primeira_parcela", CONTRATO, "depois da contratação"),
        (
            "amortizacoes_extras",
            (AmortizacaoExtra(13, Decimal(1), "prazo"),),
            "fora do prazo",
        ),
        (
            "amortizacoes_extras",
            (AmortizacaoExtra(2, Decimal(1), "prazo"), AmortizacaoExtra(2, Decimal(1), "prazo")),
            "uma amortização extra por mês",
        ),
    ],
)
def test_entradas_invalidas(campo: str, valor: object, mensagem: str) -> None:
    with pytest.raises(ValueError, match=mensagem):
        simular_financiamento(price(**{campo: valor}))
