"""Dias úteis do mercado financeiro (fins de semana e feriados nacionais da ANBIMA)."""

from collections.abc import Mapping
from datetime import date, timedelta

from calc_financeira_br.regras.feriados import ANOS_COBERTOS, FERIADOS_NACIONAIS

SABADO = 5


class ErroCalendario(ValueError):
    """Data fora dos anos cobertos pela lista de feriados."""


def _verificar_cobertura(dia: date, anos: range) -> None:
    if dia.year not in anos:
        raise ErroCalendario(
            f"a lista de feriados cobre de {anos.start} a {anos.stop - 1}; "
            f"a data {dia:%d/%m/%Y} está fora desse período"
        )


def eh_dia_util(
    dia: date,
    feriados: Mapping[date, str] = FERIADOS_NACIONAIS,
    anos: range = ANOS_COBERTOS,
) -> bool:
    _verificar_cobertura(dia, anos)
    return dia.weekday() < SABADO and dia not in feriados


def proximo_dia_util(
    dia: date,
    feriados: Mapping[date, str] = FERIADOS_NACIONAIS,
    anos: range = ANOS_COBERTOS,
) -> date:
    """O próprio dia, se for útil; senão, o primeiro dia útil seguinte."""
    while not eh_dia_util(dia, feriados, anos):
        dia += timedelta(days=1)
    return dia


def dias_uteis_entre(
    inicio: date,
    fim: date,
    feriados: Mapping[date, str] = FERIADOS_NACIONAIS,
    anos: range = ANOS_COBERTOS,
) -> int:
    """Dias úteis no intervalo [inicio, fim): conta o início e não conta o fim.

    É a contagem usada para o CDI: cada dia útil desde a aplicação até a véspera
    do resgate rende a taxa daquele dia.
    """
    if fim < inicio:
        raise ValueError("a data final é anterior à inicial")
    _verificar_cobertura(inicio, anos)
    _verificar_cobertura(fim, anos)
    total = 0
    dia = inicio
    while dia < fim:
        if eh_dia_util(dia, feriados, anos):
            total += 1
        dia += timedelta(days=1)
    return total
