# knowledge-base/datasets/

**Responsável:** Selliny (M1). Consumidor principal: Santiago/Leonardo (M5).

## Propósito
Dados sintéticos de treino/validação e golden cases causais. Nenhum dado real identificável.

## Conteúdo esperado
| Item | Descrição |
| :--- | :--- |
| `synthetic_csi/` | Janelas CSI sintéticas por `crew_id` (nominal, respiração, postura, exercício, anomalia) |
| `synthetic_peripherals/` | Séries `MAX30102`, `BME280`, `SCD40` |
| `golden_cases/` | Casos rotulados: sintoma + snapshot de sensores + histórico + resposta esperada (hipótese top-1, contramedida, escalonamento) |
| [`Space Health SQLite`](../../database/space_health_sqlite/docs/INTEGRATION.md) | Base de pesquisa disponível: 1.269.126 linhas ambientais (128.175 totalmente ausentes), 6.342 medições de radiação, 13 amostras, 3.159 valores de expressão gênica, 243 resultados moleculares agregados, 90 check-ins fictícios, 5 estudos ESA/HREDA em metadados e 161 agregados fisiológicos associados a 18 publicações |

## Base de pesquisa disponível

O pacote completo fica em `database/space_health_sqlite/`, com schema, scripts Python, consultas, inventário de fontes, snapshots comprimidos dentro do banco, política de ausências e relatórios. O snapshot tem cerca de 474 MiB e é referenciado nesta pasta, sem duplicação.

`make db-research-inventory` mostra os 13 datasets e distingue dados importados, referências, fixtures e registros do catálogo ESA/HREDA. O bloco `published_physiology` informa separadamente o corpus de artigos: 18 publicações, das quais 13 têm 161 agregados numéricos e cinco não têm valores transcritos. A view `v_dataset_inventory` é limitada aos conjuntos que possuem `dataset_id`; as publicações não são somadas artificialmente a esses datasets.

`make db-research-validate` valida o snapshot local sem baixar dados. Os relatórios apresentam as 13 verificações estruturais e as pendências de qualidade da transcrição, incluindo a SD negativa preservada para revisão. `make db-research-test` verifica importação e política de ausências, repetição, rollback, preservação de dados externos e recuperação de linhas vazias a partir do snapshot.

O bloco `missingness` do inventário informa 781.198 eventos de ausência, 124 resumos de completude e 44 séries temporais examinadas. As medidas numéricas não foram imputadas; zero e `NULL` permanecem distintos. A completude representa disponibilidade de células em linhas conhecidas, não a cobertura de um calendário de amostragem. Veja [MISSING_DATA_POLICY.md](../../database/space_health_sqlite/docs/MISSING_DATA_POLICY.md).

As séries ambientais descrevem experimentos e controles em solo; os dados moleculares são valores processados de pesquisa com aliases públicos. Não há correspondência automática com tripulantes operacionais. Os 90 check-ins são sintéticos e permanecem em tabelas separadas.

Os 161 resultados fisiológicos são estatísticas publicadas de estudos/grupos, com médias, medianas, contagens, intervalos ou efeitos combinados. Unidades, fases, posturas, intervenções e tipos de estatística devem ser considerados ao comparar resultados. Alguns valores `RANGE` usam pontos médios para ordenação, conforme a nota da origem; os limites publicados permanecem disponíveis. As tabelas não representam séries individuais de astronautas.

## Golden cases mínimos
1. Cefaleia + CO2 alto + Amsler normal: hipercapnia, ventilação.
2. Cefaleia + visão turva + Amsler alterado + CO2 normal: SANS/VIIP, Thigh Cuffs + ultrassom + Complexo B.
3. Cefaleia + sono curto + HRV baixo + hidratação baixa: fadiga/desidratação, Nutrition SMO + ajuste circadiano.
4. Evento SPE + HRV em queda: `MODE_RADIATION_ALERT`, abrigo + Vitaminas C e E.

## Regras
- Arquivos grandes: formato compacto (`.npz`/`.parquet`) e documentados aqui com tamanho.
- Cada dataset com `README` de geração (seed aleatória, parâmetros).
