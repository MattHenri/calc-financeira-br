from datetime import date

import pytest

from calc_financeira_br.calculos.calendario import (
    ErroCalendario,
    dias_uteis_entre,
    eh_dia_util,
    proximo_dia_util,
)


@pytest.mark.parametrize(
    ("dia", "util"),
    [
        (date(2026, 10, 5), True),  # segunda comum
        (date(2026, 10, 10), False),  # sábado
        (date(2026, 10, 11), False),  # domingo
        (date(2026, 10, 12), False),  # Nossa Senhora Aparecida
        (date(2026, 2, 16), False),  # Carnaval (segunda)
        (date(2026, 2, 17), False),  # Carnaval (terça)
        (date(2026, 2, 18), True),  # quarta de cinzas é dia útil
        (date(2026, 6, 4), False),  # Corpus Christi
        (date(2026, 11, 20), False),  # Consciência Negra
        (date(2026, 4, 2), True),  # quinta da Semana Santa é dia útil
    ],
)
def test_eh_dia_util(dia: date, util: bool) -> None:
    assert eh_dia_util(dia) is util


@pytest.mark.parametrize(
    ("dia", "esperado"),
    [
        (date(2026, 10, 5), date(2026, 10, 5)),  # já é útil
        (date(2026, 11, 20), date(2026, 11, 23)),  # feriado na sexta → segunda
        (date(2026, 10, 10), date(2026, 10, 13)),  # sábado → pula domingo e feriado
        (date(2026, 12, 25), date(2026, 12, 28)),  # Natal na sexta
        (date(2026, 12, 31), date(2026, 12, 31)),  # último dia do ano é útil na ANBIMA
    ],
)
def test_proximo_dia_util(dia: date, esperado: date) -> None:
    assert proximo_dia_util(dia) == esperado


def test_dias_uteis_de_um_mes() -> None:
    # Outubro/2026: 22 dias de semana, menos o feriado de 12/10.
    assert dias_uteis_entre(date(2026, 10, 1), date(2026, 11, 1)) == 21
    # Janeiro/2026: 22 dias de semana, menos 1º de janeiro.
    assert dias_uteis_entre(date(2026, 1, 1), date(2026, 2, 1)) == 21


def test_contagem_inclui_inicio_e_exclui_fim() -> None:
    segunda, terca = date(2026, 10, 5), date(2026, 10, 6)
    assert dias_uteis_entre(segunda, terca) == 1
    assert dias_uteis_entre(segunda, segunda) == 0
    # Sexta → segunda: só a sexta conta.
    assert dias_uteis_entre(date(2026, 10, 2), date(2026, 10, 5)) == 1


def test_fim_antes_do_inicio_e_erro() -> None:
    with pytest.raises(ValueError, match="anterior"):
        dias_uteis_entre(date(2026, 10, 6), date(2026, 10, 5))


@pytest.mark.parametrize("dia", [date(2023, 12, 29), date(2031, 1, 2)])
def test_fora_da_cobertura_de_feriados_e_erro(dia: date) -> None:
    with pytest.raises(ErroCalendario, match="2024 a 2030"):
        eh_dia_util(dia)
