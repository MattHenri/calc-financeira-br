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

## Fontes oficiais

- Decreto 6.306/2007 (texto compilado): <https://www.planalto.gov.br/ccivil_03/_ato2007-2010/2007/decreto/d6306.htm>
- Feriados nacionais ANBIMA: <https://www.anbima.com.br/feriados/arqs/feriados_nacionais.xls>

## Pontos a revisar

- **IOF em LCI e LCA:** o art. 32, § 2º, V do Decreto 6.306 zera o IOF para LCA (e CDCA, CRA), mas não cita LCI. O documento de definição lista o IOF só para CDB, LC e Tesouro Direto. Decidir na Fase 3.
