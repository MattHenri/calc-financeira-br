# calc-financeira-br

[![CI](https://github.com/MattHenri/calc-financeira-br/actions/workflows/ci.yml/badge.svg)](https://github.com/MattHenri/calc-financeira-br/actions/workflows/ci.yml)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)

> 🇧🇷 Português · [🇺🇸 English](#english)

Servidor [MCP](https://modelcontextprotocol.io) open source que dá ao Claude (e a qualquer cliente MCP) **cálculos financeiros brasileiros exatos e explicados**: renda fixa, comparação de investimentos, taxas equivalentes e financiamentos.

LLMs erram contas com juros compostos, dias úteis e faixas de imposto. Este servidor faz a conta de forma determinística e devolve a **memória de cálculo** passo a passo; o modelo cuida da conversa.

> ⚠️ **Em desenvolvimento (pré-alfa).** Ainda não publicado no PyPI.

## Diferenciais

- **Precisão de mercado:** CDI na base 252 dias úteis com calendário de feriados (ANBIMA), IOF dia a dia e `Decimal` em vez de `float`.
- **Memória de cálculo:** cada resultado mostra taxa diária, IOF, base do IR e a alíquota aplicada.
- **Regras versionadas:** alíquotas e tabelas ficam em arquivos de configuração, com a fonte oficial citada.
- **Validação pública:** testes comparados com calculadoras de referência.

## Tools

| Tool | Status |
|---|---|
| `obter_indicadores` | ✅ Selic, CDI, IPCA (mês e 12 meses) e TR do Banco Central |
| `simular_renda_fixa` | 🟡 CDB, LC, LCI e LCA pós-fixados (% do CDI), com IR, IOF e dias úteis; Tesouro Selic, prefixado e poupança em breve |
| `comparar_investimentos` | 🚧 planejada |
| `taxa_equivalente` | 🚧 planejada |
| `simular_financiamento` | 🚧 planejada |

Todas as respostas são **simulações, não recomendação de investimento**.

## Desenvolvimento

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12+.

```bash
uv sync                      # instala dependências
uv run pytest                # testes (sem rede)
uv run pytest --rede         # inclui testes que acessam APIs reais
uv run ruff check .          # lint
uv run ruff format .         # formatação
uv run mypy                  # tipos
uv run calc-financeira-br    # sobe o servidor (stdio)
npx @modelcontextprotocol/inspector uv run calc-financeira-br   # MCP Inspector
```

## Licença

[MIT](LICENSE)

---

## English

Open source [MCP](https://modelcontextprotocol.io) server that gives Claude (and any MCP client) **exact, explained Brazilian financial calculations**: fixed income (CDB, LCI/LCA, Tesouro, savings), investment comparison, equivalent rates and loans (SAC/Price).

Every result includes a step-by-step calculation trail and the assumptions used. Results are simulations, not investment advice.

> ⚠️ **Work in progress (pre-alpha).** Not yet published on PyPI. Tool names and descriptions are in Portuguese.
