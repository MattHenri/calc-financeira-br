"""Prefixado, Tesouro Selic e poupança."""

from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from calc_financeira_br.calculos.renda_fixa import (
    EntradaPoupanca,
    EntradaPrefixado,
    EntradaTesouroSelic,
    fator_cdi,
    simular_poupanca,
    simular_prefixado,
    simular_tesouro_selic,
    taxa_mensal_poupanca,
)
from calc_financeira_br.regras.carregar import TipoTitulo, convencoes, regras_poupanca

SEGUNDA = date(2026, 10, 5)
UM_ANO = date(2027, 10, 5)  # 365 dias corridos, 250 dias úteis


# ---------------------------------------------------------------------- prefixado


def test_prefixado_fator_e_tributos() -> None:
    r = simular_prefixado(EntradaPrefixado("cdb", Decimal(10000), Decimal(12), SEGUNDA, UM_ANO))
    with localcontext(prec=50):
        esperado = (Decimal("1.12") ** (Decimal(250) / 252)).quantize(Decimal("1e-16"), ROUND_DOWN)
    assert r.dias_uteis == 250
    assert r.fator_acumulado == esperado == Decimal("1.1189930868022511")
    assert r.valor_bruto == Decimal("11189.93")
    assert r.aliquota_ir == Decimal("17.5")
    assert r.ir == Decimal("208.24")  # 1.189,93 × 17,5% = 208,2378
    assert r.valor_liquido == Decimal("10981.69")


def test_lci_prefixada_isenta() -> None:
    r = simular_prefixado(EntradaPrefixado("lci", Decimal(10000), Decimal(11), SEGUNDA, UM_ANO))
    assert r.ir == 0
    assert r.valor_liquido == r.valor_bruto


def test_prefixado_curto_paga_iof() -> None:
    r = simular_prefixado(
        EntradaPrefixado("cdb", Decimal(10000), Decimal(12), SEGUNDA, date(2026, 10, 15))
    )
    assert r.aliquota_iof == 66


@pytest.mark.parametrize("tipo", ["tesouro_selic", "poupanca"])
def test_prefixado_so_para_titulos_bancarios(tipo: TipoTitulo) -> None:
    with pytest.raises(ValueError, match="CDB, LC, LCI e LCA"):
        simular_prefixado(EntradaPrefixado(tipo, Decimal(1000), Decimal(10), SEGUNDA, UM_ANO))


# ------------------------------------------------------------------ Tesouro Selic


def tesouro(valor: str, estoque: str = "0", resgate: date = UM_ANO) -> EntradaTesouroSelic:
    return EntradaTesouroSelic(
        Decimal(valor), Decimal("13.65"), SEGUNDA, resgate, estoque_tesouro_selic=Decimal(estoque)
    )


def test_tesouro_selic_rende_100_por_cento_da_selic() -> None:
    r = simular_tesouro_selic(tesouro("5000"))
    _, _, fator = fator_cdi(Decimal(100), Decimal("13.65"), 250, convencoes())
    assert r.fator_acumulado == fator


def test_tesouro_selic_ate_10_mil_nao_paga_custodia() -> None:
    r = simular_tesouro_selic(tesouro("5000"))
    assert r.custodia == 0
    assert r.valor_liquido == r.valor_bruto - r.iof - r.ir


def test_custodia_so_sobre_o_excedente() -> None:
    r = simular_tesouro_selic(tesouro("20000"))
    taxa_ano = Decimal("0.002") * 365 / 365
    # Entre o excedente inicial e o excedente final, pro rata de um ano.
    assert (20000 - 10000) * taxa_ano < r.custodia < (r.valor_bruto - 10000) * taxa_ano
    assert r.custodia == Decimal("22.64")


def test_estoque_existente_reduz_a_isencao() -> None:
    sem_estoque = simular_tesouro_selic(tesouro("5000"))
    com_estoque = simular_tesouro_selic(tesouro("5000", estoque="8000"))
    assert sem_estoque.custodia == 0
    # A parte que passa de R$ 10 mil vai de 3.000 a ~3.677 no ano.
    assert Decimal(6) < com_estoque.custodia < Decimal("7.36")
    estoque_cheio = simular_tesouro_selic(tesouro("5000", estoque="10000"))
    assert (
        5000 * Decimal("0.002")
        < estoque_cheio.custodia
        < estoque_cheio.valor_bruto * Decimal("0.002")
    )


def test_custodia_nao_sai_da_base_do_ir() -> None:
    r = simular_tesouro_selic(tesouro("50000"))
    assert r.custodia > 0
    assert r.base_ir == r.rendimento_bruto - r.iof
    assert r.valor_liquido == r.valor_bruto - r.iof - r.ir - r.custodia


def test_tesouro_selic_curto_paga_iof() -> None:
    r = simular_tesouro_selic(tesouro("5000", resgate=date(2026, 10, 15)))
    assert r.aliquota_iof == 66
    assert r.aliquota_ir == Decimal("22.5")


def test_custodia_na_memoria() -> None:
    r = simular_tesouro_selic(tesouro("20000"))
    assert any("Custódia B3" in passo for passo in r.memoria)
    assert any("Ofício Circular B3 014/2024-VPC" in p for p in r.premissas)


# ----------------------------------------------------------------------- poupança


def poupanca(
    aplicacao: date = SEGUNDA, resgate: date = UM_ANO, selic: str = "13.75", tr: str = "0.1616"
) -> EntradaPoupanca:
    return EntradaPoupanca(Decimal(10000), Decimal(selic), Decimal(tr), aplicacao, resgate)


@pytest.mark.parametrize(
    ("selic", "tr", "esperado"),
    [
        ("13.75", "0", "0.5"),
        ("8.51", "0", "0.5"),
        # Selic exatamente em 8,5%: vale a regra dos 70% (≤ 8,5%).
        ("8.5", "0", "0.4828"),  # (1 + 70% × 8,5%)^(1/12) − 1 = 0,48280%
        ("6", "0", "0.3434"),  # (1 + 4,2%)^(1/12) − 1 = 0,34344%
    ],
)
def test_regra_da_selic_na_borda(selic: str, tr: str, esperado: str) -> None:
    taxa, _ = taxa_mensal_poupanca(Decimal(selic), Decimal(tr), regras_poupanca())
    assert taxa == Decimal(esperado)


def test_poupanca_um_ano_completo() -> None:
    r = simular_poupanca(poupanca(resgate=UM_ANO))
    saldo = Decimal(10000)
    for _ in range(12):  # 12 aniversários, saldo em centavos a cada crédito
        saldo = (saldo * Decimal("1.006624")).quantize(Decimal("0.01"))
    assert r.valor_bruto == saldo
    assert r.iof == 0
    assert r.ir == 0
    assert r.custodia == 0
    assert r.valor_liquido == r.valor_bruto


def test_resgate_um_dia_antes_do_aniversario_perde_o_mes() -> None:
    antes = simular_poupanca(poupanca(resgate=date(2027, 10, 4)))
    no_dia = simular_poupanca(poupanca(resgate=UM_ANO))
    assert antes.valor_bruto < no_dia.valor_bruto
    assert any("não rendem" in passo for passo in antes.memoria)


def test_menos_de_um_mes_nao_rende() -> None:
    r = simular_poupanca(poupanca(resgate=date(2026, 11, 4)))
    assert r.valor_bruto == Decimal(10000)


@pytest.mark.parametrize("dia", [29, 30, 31])
def test_deposito_nos_dias_29_30_31_faz_aniversario_no_dia_1(dia: int) -> None:
    aplicacao = date(2026, 1, dia)
    em_marco = simular_poupanca(poupanca(aplicacao, resgate=date(2026, 3, 1)))
    fim_de_fevereiro = simular_poupanca(poupanca(aplicacao, resgate=date(2026, 2, 28)))
    assert em_marco.valor_bruto > Decimal(10000)  # 1º/02 → 1º/03: um crédito
    assert fim_de_fevereiro.valor_bruto == Decimal(10000)
    assert "dia 1º" in em_marco.memoria[0]


def test_datas_da_poupanca_nao_vao_para_dia_util() -> None:
    sabado = date(2026, 10, 10)
    r = simular_poupanca(poupanca(aplicacao=sabado, resgate=date(2026, 11, 10)))
    assert r.data_aplicacao == sabado
    assert r.data_resgate == date(2026, 11, 10)
    assert r.valor_bruto > Decimal(10000)


def test_regra_vale_a_partir_de_maio_de_2012() -> None:
    with pytest.raises(ValueError, match="04/05/2012"):
        simular_poupanca(poupanca(aplicacao=date(2012, 5, 3), resgate=date(2026, 1, 5)))
