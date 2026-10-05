"""Feriados nacionais que não são dias úteis no mercado financeiro.

Fonte: calendário de feriados nacionais da ANBIMA
(https://www.anbima.com.br/feriados/arqs/feriados_nacionais.xls), baixado em 2026-10-01.
Inclui Carnaval e Corpus Christi, que a ANBIMA considera dias sem movimentação
das reservas bancárias. Não inclui feriados estaduais e municipais.

Atualize todo ano: acrescente o ano novo e amplie `ANOS_COBERTOS`.
"""

from datetime import date

FONTE = "Calendário de feriados nacionais da ANBIMA"

ANOS_COBERTOS = range(2024, 2031)

FERIADOS_NACIONAIS: dict[date, str] = {
    # 2024
    date(2024, 1, 1): "Confraternização Universal",
    date(2024, 2, 12): "Carnaval",
    date(2024, 2, 13): "Carnaval",
    date(2024, 3, 29): "Paixão de Cristo",
    date(2024, 4, 21): "Tiradentes",
    date(2024, 5, 1): "Dia do Trabalho",
    date(2024, 5, 30): "Corpus Christi",
    date(2024, 9, 7): "Independência do Brasil",
    date(2024, 10, 12): "Nossa Senhora Aparecida",
    date(2024, 11, 2): "Finados",
    date(2024, 11, 15): "Proclamação da República",
    date(2024, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2024, 12, 25): "Natal",
    # 2025
    date(2025, 1, 1): "Confraternização Universal",
    date(2025, 3, 3): "Carnaval",
    date(2025, 3, 4): "Carnaval",
    date(2025, 4, 18): "Paixão de Cristo",
    date(2025, 4, 21): "Tiradentes",
    date(2025, 5, 1): "Dia do Trabalho",
    date(2025, 6, 19): "Corpus Christi",
    date(2025, 9, 7): "Independência do Brasil",
    date(2025, 10, 12): "Nossa Senhora Aparecida",
    date(2025, 11, 2): "Finados",
    date(2025, 11, 15): "Proclamação da República",
    date(2025, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2025, 12, 25): "Natal",
    # 2026
    date(2026, 1, 1): "Confraternização Universal",
    date(2026, 2, 16): "Carnaval",
    date(2026, 2, 17): "Carnaval",
    date(2026, 4, 3): "Paixão de Cristo",
    date(2026, 4, 21): "Tiradentes",
    date(2026, 5, 1): "Dia do Trabalho",
    date(2026, 6, 4): "Corpus Christi",
    date(2026, 9, 7): "Independência do Brasil",
    date(2026, 10, 12): "Nossa Senhora Aparecida",
    date(2026, 11, 2): "Finados",
    date(2026, 11, 15): "Proclamação da República",
    date(2026, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2026, 12, 25): "Natal",
    # 2027
    date(2027, 1, 1): "Confraternização Universal",
    date(2027, 2, 8): "Carnaval",
    date(2027, 2, 9): "Carnaval",
    date(2027, 3, 26): "Paixão de Cristo",
    date(2027, 4, 21): "Tiradentes",
    date(2027, 5, 1): "Dia do Trabalho",
    date(2027, 5, 27): "Corpus Christi",
    date(2027, 9, 7): "Independência do Brasil",
    date(2027, 10, 12): "Nossa Senhora Aparecida",
    date(2027, 11, 2): "Finados",
    date(2027, 11, 15): "Proclamação da República",
    date(2027, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2027, 12, 25): "Natal",
    # 2028
    date(2028, 1, 1): "Confraternização Universal",
    date(2028, 2, 28): "Carnaval",
    date(2028, 2, 29): "Carnaval",
    date(2028, 4, 14): "Paixão de Cristo",
    date(2028, 4, 21): "Tiradentes",
    date(2028, 5, 1): "Dia do Trabalho",
    date(2028, 6, 15): "Corpus Christi",
    date(2028, 9, 7): "Independência do Brasil",
    date(2028, 10, 12): "Nossa Senhora Aparecida",
    date(2028, 11, 2): "Finados",
    date(2028, 11, 15): "Proclamação da República",
    date(2028, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2028, 12, 25): "Natal",
    # 2029
    date(2029, 1, 1): "Confraternização Universal",
    date(2029, 2, 12): "Carnaval",
    date(2029, 2, 13): "Carnaval",
    date(2029, 3, 30): "Paixão de Cristo",
    date(2029, 4, 21): "Tiradentes",
    date(2029, 5, 1): "Dia do Trabalho",
    date(2029, 5, 31): "Corpus Christi",
    date(2029, 9, 7): "Independência do Brasil",
    date(2029, 10, 12): "Nossa Senhora Aparecida",
    date(2029, 11, 2): "Finados",
    date(2029, 11, 15): "Proclamação da República",
    date(2029, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2029, 12, 25): "Natal",
    # 2030
    date(2030, 1, 1): "Confraternização Universal",
    date(2030, 3, 4): "Carnaval",
    date(2030, 3, 5): "Carnaval",
    date(2030, 4, 19): "Paixão de Cristo",
    date(2030, 4, 21): "Tiradentes",
    date(2030, 5, 1): "Dia do Trabalho",
    date(2030, 6, 20): "Corpus Christi",
    date(2030, 9, 7): "Independência do Brasil",
    date(2030, 10, 12): "Nossa Senhora Aparecida",
    date(2030, 11, 2): "Finados",
    date(2030, 11, 15): "Proclamação da República",
    date(2030, 11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    date(2030, 12, 25): "Natal",
}
