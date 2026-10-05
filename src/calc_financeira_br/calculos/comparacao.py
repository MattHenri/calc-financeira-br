"""Ranking de investimentos pelo valor líquido."""

from dataclasses import dataclass
from decimal import Decimal

from calc_financeira_br.formatacao import formatar_percentual, formatar_reais


@dataclass(frozen=True)
class Candidato:
    nome: str
    valor_liquido: Decimal
    rentabilidade_liquida_anual: Decimal


@dataclass(frozen=True)
class Posicao:
    posicao: int
    indice: int
    """Posição da opção na lista de entrada (0, 1, ...)."""
    diferenca_para_o_primeiro: Decimal
    """Quanto rende a menos que a primeira colocada, em reais (zero para ela)."""
    diferenca_anual_pp: Decimal
    """Diferença de rentabilidade líquida anual para a primeira, em pontos percentuais."""


def ranquear(candidatos: list[Candidato]) -> tuple[list[Posicao], list[str]]:
    """Ordena do maior para o menor valor líquido. Empates ficam com a mesma posição."""
    if not candidatos:
        raise ValueError("informe pelo menos uma opção")
    ordem = sorted(range(len(candidatos)), key=lambda i: -candidatos[i].valor_liquido)
    primeiro = candidatos[ordem[0]]
    posicoes: list[Posicao] = []
    memoria = ["Ranking pelo valor líquido no resgate (maior primeiro):"]
    for colocacao, indice in enumerate(ordem, start=1):
        c = candidatos[indice]
        empatado = posicoes and candidatos[posicoes[-1].indice].valor_liquido == c.valor_liquido
        posicao = posicoes[-1].posicao if empatado else colocacao
        diferenca = primeiro.valor_liquido - c.valor_liquido
        pp = primeiro.rentabilidade_liquida_anual - c.rentabilidade_liquida_anual
        posicoes.append(Posicao(posicao, indice, diferenca, pp))
        linha = f"{posicao}º {c.nome}: {formatar_reais(c.valor_liquido)} líquidos"
        if diferenca > 0:
            linha += (
                f", {formatar_reais(diferenca)} a menos que {primeiro.nome} "
                f"({formatar_percentual(pp).removesuffix('%')} p.p. a.a. a menos)"
            )
        elif indice != ordem[0]:
            linha += f", empatado com {primeiro.nome}"
        memoria.append(linha + ".")
    return posicoes, memoria
