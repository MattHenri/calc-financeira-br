# Decisões de implementação

Complementa [definicao-projeto.md](definicao-projeto.md) com o que foi decidido depois dele.

| Data | Decisão | Origem |
|---|---|---|
| 2026-10-01 | Pacote `calc-financeira-br` (módulo `calc_financeira_br`), tools em português, licença MIT, transporte stdio | Definição do projeto |
| 2026-10-01 | Feriados: lista própria versionada em `regras/`, copiada do calendário de feriados nacionais da ANBIMA (inclui Carnaval e Corpus Christi; considera os dias sem movimentação das reservas bancárias). Cobertura inicial: 2024–2030 | Definição do projeto |
| 2026-10-01 | Tabela do IOF regressivo: Anexo do Decreto 6.306/2007 (art. 32), conferida no texto compilado do Planalto em 2026-10-01. Os decretos de 2025 (12.466, 12.467, 12.499) não alteraram o art. 32 nem o Anexo | Fonte oficial |
| 2026-10-01 | Arredondamento do CDI na convenção da B3: fator diário com 8 casas (arredondado), fator acumulado com 16 casas (truncado), valores em reais com 2 casas | Decisão de projeto |
| 2026-10-01 | Resgate em feriado ou fim de semana: passa para o próximo dia útil (informado nas premissas) | Decisão de projeto |
| 2026-10-01 | SDK `mcp` 2.x: `FastMCP` virou `mcp.server.MCPServer`; usamos a API nova | Documentação do SDK |
| 2026-10-01 | Prazo para IR e IOF em dias corridos entre aplicação e resgate | Premissa (convenção de mercado) |
| 2026-10-01 | Simulação projeta o CDI como constante (atual ou informado pelo usuário) | Premissa |
| 2026-10-05 | Séries do SGS em `obter_indicadores`: Selic meta (432, % a.a.), CDI anualizado base 252 (4389, % a.a.), IPCA mensal (433), IPCA 12 meses (13522) e TR mensal (7811) | API do Banco Central |
| 2026-10-05 | Consulta por intervalo de datas (últimos 120 dias até hoje), não por "últimos N": a série 432 traz datas futuras até a próxima reunião do Copom, e o IPCA sai com cerca de 2 meses de atraso | API do Banco Central |
| 2026-10-05 | Cache em memória de 1 hora por série; se a API falhar, devolve o último valor em cache marcado como desatualizado. Falha de um indicador não derruba os outros | Decisão de projeto |
| 2026-10-05 | IOF da LCI: segue a tabela regressiva do decreto nos primeiros 30 dias e zera depois (como CDB/LC). LCA: alíquota zero de IOF (art. 32, § 2º, V do Decreto 6.306/2007) | Decisão de projeto + fonte oficial |
| 2026-10-05 | Data de aplicação em dia não útil também passa para o próximo dia útil | Decisão de projeto |
| 2026-10-05 | Dias úteis contados no intervalo [aplicação, resgate): conta o dia da aplicação, não conta o do resgate | Convenção de mercado |
| 2026-10-05 | Arredondamento: taxa diária do CDI com 8 casas (ROUND_HALF_UP); fator diário e acumulado truncados em 16 casas (ROUND_DOWN) a cada dia; reais com 2 casas (ROUND_HALF_UP). Tudo em `regras/convencoes.toml` | Convenção B3 + decisão de projeto |
| 2026-10-05 | Rentabilidade anualizada na base 252 dias úteis; rentabilidade real pela fórmula de Fisher com o IPCA de 12 meses (ou inflação informada) | Decisão de projeto |
| 2026-10-05 | Calendário cobre 2024–2030; datas fora disso são recusadas em vez de assumir que não há feriados | Decisão de projeto |
| 2026-10-05 | Custódia do Tesouro Direto: 0,20% a.a. provisionada diariamente e cobrada pro rata no resgate, no vencimento ou nos juros; Tesouro Selic isento até R$ 10.000 de estoque por CPF, cobrando só o excedente | Ofício Circular B3 014/2024-VPC + página de tarifas da B3 |
| 2026-10-05 | Custódia pro rata em dias corridos/365 sobre o valor bruto atualizado de cada dia (a fonte não define a base) | Decisão de projeto |
| 2026-10-05 | Custódia não é deduzida da base do IR (opção conservadora; nenhuma fonte oficial encontrada) | Decisão de projeto |
| 2026-10-05 | Isenção de R$ 10 mil: a aplicação simulada é todo o estoque de Tesouro Selic do CPF, com campo opcional para o estoque que a pessoa já tem | Decisão de projeto |
| 2026-10-05 | Tesouro Selic rende a Selic efetiva (série SGS 1178), não a meta; ágio/deságio do preço ignorados; taxa do agente de custódia zero por padrão | Decisão de projeto |
| 2026-10-05 | CET pela Resolução CMN 4.881/2020 (a 3.517/2007 foi revogada em 01/02/2021): Σ FCj/(1+CET)^((dj−d0)/365) − FC0 = 0, dias corridos, % a.a. com 2 casas pela NBR 5891 (ROUND_HALF_EVEN); taxas flutuantes e índices (ex.: TR) ficam fora do CET | Resolução CMN 4.881/2020, art. 4º e 5º |
| 2026-10-05 | IOF de operações de crédito não é calculado; tributos do financiamento entram como valor informado | Decisão de projeto |
| 2026-10-05 | `taxa_equivalente`: conversão entre períodos por juros compostos com ano de 12 meses e 252 dias úteis; nominal × real pela equação de Fisher | Decisão de projeto |
| 2026-10-05 | Isento × tributado exato no prazo: iguala o rendimento líquido total (o IR incide sobre o rendimento, não sobre a taxa), em vez da regra de bolso taxa / (1 − alíquota). Alíquota de IR pelo prazo; IOF fora da comparação. Em % do CDI usa o fator diário 1 + p × TDI, desprezando os truncamentos (efeito < 10⁻¹⁰) | Decisão de projeto |
| 2026-10-05 | Taxas equivalentes com 6 casas decimais (`casas_taxas` em `convencoes.toml`) | Decisão de projeto |

## Validação

- Taxa diária do CDI conferida com a série SGS 12 do Banco Central (CDI diário): 13,65% a.a. → 0,050788% a.d.
- Lista de feriados conferida item a item com o arquivo da ANBIMA (91 datas, 2024–2030).
- Tabela do IOF conferida com o Anexo do Decreto 6.306/2007.
- Valores finais de renda fixa (`tests/referencia`) ainda **pendentes de validação** numa calculadora externa.

## Fontes oficiais

- Decreto 6.306/2007 (texto compilado): <https://www.planalto.gov.br/ccivil_03/_ato2007-2010/2007/decreto/d6306.htm>
- Feriados nacionais ANBIMA: <https://www.anbima.com.br/feriados/arqs/feriados_nacionais.xls>
- Ofício Circular B3 014/2024-VPC (tarifação do Tesouro Direto): <https://www.b3.com.br/data/files/CC/A7/6E/11/CC543910B371F339AC094EA8/OC%20014-2024-VPC%20Pol%C3%ADtica%20de%20tarifa%C3%A7%C3%A3o%20do%20Tesouro%20Direto_cobranca_semestral.pdf>
- Tarifas de Tesouro Direto (B3): <https://www.b3.com.br/pt_br/produtos-e-servicos/tarifas/tarifas-de-tesouro-direto/>
- Resolução CMN 4.881/2020 (CET): <https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20CMN&numero=4881>
