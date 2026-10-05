from datetime import date
from decimal import Decimal

import pytest

from calc_financeira_br.calculos.tributos import aliquota_iof, aliquota_ir
from calc_financeira_br.regras.carregar import RegraIR, regras_tributacao
from calc_financeira_br.regras.feriados import ANOS_COBERTOS, FERIADOS_NACIONAIS

APLICACAO = date(2026, 10, 5)

# Anexo do Decreto 6.306/2007 (texto compilado do Planalto), dias 1 a 30.
TABELA_DECRETO = [
    96, 93, 90, 86, 83, 80, 76, 73, 70, 66, 63, 60, 56, 53, 50,
    46, 43, 40, 36, 33, 30, 26, 23, 20, 16, 13, 10, 6, 3, 0,
]  # fmt: skip


def test_tabela_iof_igual_ao_decreto() -> None:
    assert regras_tributacao().iof.tabela == [Decimal(x) for x in TABELA_DECRETO]


@pytest.mark.parametrize(
    ("dias", "aliquota"),
    [(1, "96"), (2, "93"), (10, "66"), (29, "3"), (30, "0"), (31, "0"), (365, "0")],
)
@pytest.mark.parametrize("tipo", ["cdb", "lc", "lci"])
def test_iof_regressivo(tipo: str, dias: int, aliquota: str) -> None:
    assert aliquota_iof(tipo, dias) == Decimal(aliquota)  # type: ignore[arg-type]


@pytest.mark.parametrize("dias", [1, 15, 29])
def test_lca_tem_aliquota_zero_de_iof(dias: int) -> None:
    assert aliquota_iof("lca", dias) == 0


@pytest.mark.parametrize(
    ("dias", "aliquota"),
    [
        (1, "22.5"),
        (180, "22.5"),
        (181, "20"),
        (360, "20"),
        (361, "17.5"),
        (720, "17.5"),
        (721, "15"),
        (3650, "15"),
    ],
)
@pytest.mark.parametrize("tipo", ["cdb", "lc"])
def test_ir_regressivo_nas_bordas(tipo: str, dias: int, aliquota: str) -> None:
    resultado = aliquota_ir(tipo, dias, APLICACAO)  # type: ignore[arg-type]
    assert resultado.regime == "regressivo"
    assert resultado.aliquota == Decimal(aliquota)


@pytest.mark.parametrize("tipo", ["lci", "lca"])
@pytest.mark.parametrize("dias", [1, 181, 721])
def test_lci_lca_isentas_de_ir(tipo: str, dias: int) -> None:
    resultado = aliquota_ir(tipo, dias, APLICACAO)  # type: ignore[arg-type]
    assert resultado.regime == "isento"
    assert resultado.aliquota == 0


def test_regra_de_ir_por_data_de_aplicacao() -> None:
    # Simula uma lei que passasse a tributar LCI/LCA aplicadas a partir de 2027.
    atual = regras_tributacao()
    nova = RegraIR(tipos=["lci", "lca"], regime="regressivo", aplicacao_desde=date(2027, 1, 1))
    regras = atual.model_copy(
        update={"ir": atual.ir.model_copy(update={"regras": [nova, *atual.ir.regras]})}
    )
    assert aliquota_ir("lci", 100, date(2026, 12, 31), regras).regime == "isento"
    depois = aliquota_ir("lci", 100, date(2027, 1, 1), regras)
    assert depois.regime == "regressivo"
    assert depois.aliquota == Decimal("22.5")


def test_prazo_zero_e_erro() -> None:
    with pytest.raises(ValueError, match="1 dia"):
        aliquota_iof("cdb", 0)
    with pytest.raises(ValueError, match="1 dia"):
        aliquota_ir("cdb", 0, APLICACAO)


def test_feriados_cobrem_todos_os_anos_declarados() -> None:
    anos = {dia.year for dia in FERIADOS_NACIONAIS}
    assert anos == set(ANOS_COBERTOS)
    # Feriados fixos presentes em todos os anos.
    for ano in ANOS_COBERTOS:
        for mes, dia in [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20)]:
            assert date(ano, mes, dia) in FERIADOS_NACIONAIS
        assert date(ano, 12, 25) in FERIADOS_NACIONAIS
