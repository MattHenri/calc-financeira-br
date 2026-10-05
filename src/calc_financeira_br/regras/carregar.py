"""Leitura e validação dos arquivos de regras (`*.toml`)."""

import tomllib
from datetime import date
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TipoTitulo = Literal["cdb", "lc", "lci", "lca", "tesouro_selic", "poupanca"]
ModoArredondamento = Literal[
    "ROUND_DOWN", "ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_CEILING", "ROUND_FLOOR", "ROUND_UP"
]


class FaixaIR(BaseModel):
    ate_dias: int | None = None
    aliquota: Decimal


class RegraIR(BaseModel):
    tipos: list[TipoTitulo]
    regime: Literal["regressivo", "isento"]
    aplicacao_desde: date | None = None
    aplicacao_ate: date | None = None

    def vale_para(self, tipo: TipoTitulo, data_aplicacao: date) -> bool:
        if tipo not in self.tipos:
            return False
        if self.aplicacao_desde is not None and data_aplicacao < self.aplicacao_desde:
            return False
        return self.aplicacao_ate is None or data_aplicacao <= self.aplicacao_ate


class RegrasIR(BaseModel):
    fonte: str
    faixas: list[FaixaIR] = Field(min_length=1)
    regras: list[RegraIR] = Field(min_length=1)

    @field_validator("faixas")
    @classmethod
    def _faixas_em_ordem(cls, faixas: list[FaixaIR]) -> list[FaixaIR]:
        limites = [f.ate_dias for f in faixas[:-1] if f.ate_dias is not None]
        if len(limites) != len(faixas) - 1 or faixas[-1].ate_dias is not None:
            raise ValueError("só a última faixa de IR pode (e deve) ficar sem limite")
        if limites != sorted(limites):
            raise ValueError("as faixas de IR devem estar em ordem crescente de prazo")
        return faixas


class RegrasIOF(BaseModel):
    fonte: str
    tipos: list[TipoTitulo]
    tabela: list[Decimal] = Field(min_length=30, max_length=30)


class RegrasTributacao(BaseModel):
    ir: RegrasIR
    iof: RegrasIOF


class ConvencoesCDI(BaseModel):
    base_dias_uteis: int = Field(gt=0)
    casas_taxa_diaria: int = Field(gt=0)
    arredondamento_taxa_diaria: ModoArredondamento
    casas_fator_acumulado: int = Field(gt=0)
    arredondamento_fator: ModoArredondamento


class ConvencoesValores(BaseModel):
    casas_reais: int = Field(ge=0)
    arredondamento_reais: ModoArredondamento
    casas_percentuais: int = Field(ge=0)
    casas_taxas: int = Field(ge=0)


class Convencoes(BaseModel):
    cdi: ConvencoesCDI
    valores: ConvencoesValores


class CustodiaTesouro(BaseModel):
    fonte: str
    taxa_anual: Decimal = Field(ge=0)
    base_dias: int = Field(gt=0)
    isencao_tesouro_selic: Decimal = Field(ge=0)


class Tarifas(BaseModel):
    custodia_tesouro: CustodiaTesouro


class RegrasPoupanca(BaseModel):
    fonte: str
    vigente_desde: date
    limite_selic: Decimal
    adicional_mensal: Decimal
    percentual_selic: Decimal
    casas_taxa_mensal: int = Field(ge=0)
    arredondamento_taxa_mensal: ModoArredondamento
    dias_aniversario_no_dia_1: list[int]


def _ler_toml(nome: str) -> dict[str, Any]:
    return tomllib.loads(files("calc_financeira_br.regras").joinpath(nome).read_text("utf-8"))


@cache
def regras_tributacao() -> RegrasTributacao:
    return RegrasTributacao.model_validate(_ler_toml("tributacao.toml"))


@cache
def convencoes() -> Convencoes:
    return Convencoes.model_validate(_ler_toml("convencoes.toml"))


@cache
def tarifas() -> Tarifas:
    return Tarifas.model_validate(_ler_toml("tarifas.toml"))


@cache
def regras_poupanca() -> RegrasPoupanca:
    return RegrasPoupanca.model_validate(_ler_toml("poupanca.toml"))
