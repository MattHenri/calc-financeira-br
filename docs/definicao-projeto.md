# MCP Calculadora Financeira BR — Definição do Projeto

> Outubro de 2026. Fonte da verdade do projeto.

## Visão geral

Um servidor MCP open source, em Python, que dá ao Claude (e a qualquer cliente MCP) cálculos financeiros brasileiros exatos e explicados: renda fixa, comparação de investimentos, taxas equivalentes e financiamentos.

LLMs erram contas com juros compostos, dias úteis e faixas de imposto. O MCP faz a conta de forma determinística e devolve a memória de cálculo; o Claude cuida da conversa e da explicação.

**Objetivo da v1:** cinco tools confiáveis, testadas contra calculadoras oficiais e publicadas no PyPI, para qualquer pessoa instalar com um comando.

## Público e diferencial

O diferencial é rigor e transparência em poucas áreas, não cobertura ampla. O concorrente mais próximo, o FalaZuki Finance BR, já oferece 25 tools genéricas, incluindo simulação de renda fixa.

**Público:** pessoas físicas que comparam investimentos ou financiamentos conversando com IA, e devs brasileiros que querem cálculos confiáveis em seus agentes.

| Diferencial | Na prática |
|---|---|
| Precisão de mercado | CDI em base 252 dias úteis com calendário de feriados, IOF dia a dia, `Decimal` em vez de `float` |
| Memória de cálculo | Toda tool devolve o passo a passo: taxa diária, IOF, base do IR, alíquota aplicada |
| Ferramentas de decisão | Ponto de equilíbrio isento × tributado, amortizar prazo × parcela |
| Validação pública | Testes que comparam resultados com calculadoras oficiais |

## Escopo da v1

A v1 tem cinco tools. Todas recebem entradas validadas e devolvem resultado, memória de cálculo, premissas usadas e um aviso de que é simulação, não recomendação de investimento.

| Tool | Entradas principais | Saída |
|---|---|---|
| `obter_indicadores` | Lista de indicadores (Selic, CDI, IPCA, TR) | Valor atual, data de referência e fonte (Banco Central) |
| `simular_renda_fixa` | Tipo (CDB/LC, LCI/LCA, Tesouro Selic, prefixado, poupança), valor, taxa (% do CDI ou % a.a.), datas de aplicação e resgate | Bruto, IOF, IR, líquido, rentabilidade líquida e real |
| `comparar_investimentos` | Lista de opções da tool anterior, mesmo valor e prazo | Ranking pelo valor líquido e diferença entre as opções |
| `taxa_equivalente` | Taxa de origem, tipo de conversão, prazo e inflação opcional | Taxa equivalente: isento × tributado, mensal × anual, nominal × real |
| `simular_financiamento` | Valor, taxa, prazo, sistema (SAC ou Price), tarifas e seguros, amortizações extras | Tabela de parcelas, juros totais, CET e efeito de cada amortização |

Os indicadores atuais entram como padrão quando o usuário não informa uma taxa, mas qualquer premissa pode ser sobrescrita.

## Regras de domínio

As regras abaixo valem em outubro de 2026 e ficam num arquivo de configuração versionado, não espalhadas no código. Assim, uma mudança na lei vira uma edição de configuração e um teste novo.

| Regra | Como funciona | Aplica-se a |
|---|---|---|
| IR regressivo | 22,5% até 180 dias, 20% de 181 a 360, 17,5% de 361 a 720, 15% acima de 720; incide só sobre o rendimento | CDB, LC, Tesouro Direto, debêntures comuns |
| Isenção de IR (pessoa física) | Rendimento sem IR | LCI, LCA, CRI, CRA, debêntures incentivadas, poupança |
| IOF | Sobre o rendimento de resgates nos primeiros 30 dias: 96% no dia 1, caindo até zerar no dia 30 (Decreto 6.306/2007, Tabela III); calculado antes do IR | CDB, LC, Tesouro Direto |
| Poupança | Selic acima de 8,5% a.a.: 0,5% a.m. + TR; Selic até 8,5%: 70% da Selic + TR; rende apenas no aniversário mensal | Depósitos a partir de 4/5/2012 |
| CDI | Taxa anual convertida em fator diário na base de 252 dias úteis | Todos os pós-fixados atrelados ao CDI |

Para um título a p% do CDI, o fator de cada dia útil é:

$$f_{dia} = 1 + p \cdot \left[(1 + CDI_{a.a.})^{1/252} - 1\right]$$

Dois pontos de atenção:

- **Isenção de LCI/LCA em discussão:** a MP 1.303/2025, que propunha tributar esses títulos, perdeu a validade em outubro de 2025, mas a equipe econômica voltou a defender a tributação em setembro de 2026, sem projeto aprovado. A configuração deve permitir regras por data de aplicação.
- **Calendário:** feriados nacionais definem os dias úteis; a lista precisa ser atualizada todo ano.

## Stack e arquitetura

O servidor só traduz chamadas MCP em funções do núcleo. A conta fica em `calculos/`, sem rede e sem depender do MCP, o que facilita os testes e permite reaproveitar o código em outros projetos.

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.12+ | SDK de MCP mais maduro e com mais exemplos |
| MCP | SDK oficial (`mcp`, com FastMCP) | Tools declaradas com decorators e tipos |
| Validação | Pydantic v2 | Entradas e saídas tipadas; o schema chega ao cliente |
| Números | `decimal.Decimal` | Sem erros de arredondamento de float |
| HTTP | httpx | Timeout e retry nas chamadas ao Banco Central |
| Projeto | uv | Dependências, ambiente e publicação no PyPI |
| Testes | pytest + hypothesis | Casos de referência e testes de propriedade |

Estrutura de pastas proposta:

```
calc-financeira-br/
├── pyproject.toml
├── README.md
├── src/calc_financeira_br/
│   ├── server.py
│   ├── calculos/
│   │   ├── renda_fixa.py
│   │   ├── taxas.py
│   │   └── financiamento.py
│   ├── regras/
│   │   ├── tributacao.toml
│   │   └── feriados.py
│   └── dados/
│       └── bcb.py
└── tests/
    ├── referencia/
    └── propriedades/
```

## Qualidade e testes

O projeto só cumpre a promessa de rigor se cada cálculo tiver um teste que o compare com uma referência externa.

- **Testes de referência:** casos com valores conferidos na Calculadora do Cidadão do Banco Central e em simuladores de bancos, salvos como fixtures.
- **Testes de borda:** dia 30 do IOF, dias 180/181 e 720/721 do IR, Selic exatamente em 8,5%, resgate em feriado.
- **Testes de propriedade:** líquido nunca maior que bruto; IR nunca negativo; SAC e Price com o mesmo total amortizado.
- **Sem rede nos testes:** a API do Banco Central é simulada; um teste separado e opcional checa a API real.
- **Qualidade de código:** ruff para lint e formatação, mypy para tipos e CI no GitHub Actions rodando tudo a cada push.
- **Teste manual:** MCP Inspector para chamar cada tool e conferir as respostas antes de cada versão.

## Distribuição

O objetivo é que qualquer pessoa instale com um comando, sem clonar o repositório.

- Repositório público no GitHub, licença MIT.
- Pacote no PyPI, executável com `uvx <nome-do-pacote>`.
- Instruções no README para Claude Desktop, Claude Code (`claude mcp add`) e Cursor.
- Registro no MCP Registry oficial e em diretórios como Smithery e Glama.
- README em português e inglês, com exemplos de perguntas e respostas reais.
- Transporte da v1: stdio (local). HTTP para hospedagem remota fica para depois.

## Fora da v1 e próximas versões

A v1 não dá recomendação de investimento, não cobre renda variável e não acessa contas bancárias. Candidatos para a v2, em ordem de prioridade:

1. Tesouro IPCA+ e prefixado com preços e taxas reais do Tesouro Direto (marcação a mercado).
2. Calendário com feriados estaduais e municipais.
3. Independência financeira: quanto acumular e em quanto tempo.
4. Dívidas: rotativo do cartão, parcelamento e portabilidade de crédito.
5. Transporte HTTP para uso como conector remoto.

## Decisões em aberto e próximos passos

Decisões tomadas:

- [x] Nome do projeto e do pacote → `calc-financeira-br` (módulo `calc_financeira_br`).
- [x] Idioma dos nomes das tools → português. As descrições ficam em português.
- [x] Fonte do calendário de feriados → lista própria versionada no projeto (`regras/`).

Próximos passos:

1. Criar o repositório e o esqueleto do projeto.
2. Implementar `obter_indicadores` e `simular_renda_fixa` primeiro, com testes.

## Fontes

- FalaZuki Finance BR no Smithery
- Mycapital: o que muda no IR dos investimentos em 2026
- Patrimo: tabela do IR regressivo e IOF
- Blog Santander: rendimento da poupança em 2026
