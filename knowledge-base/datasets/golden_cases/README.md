# golden_cases/

**Responsável:** Selliny (M1). Consumidor principal: Santiago/Leonardo (M5).

## Propósito
Casos rotulados sintéticos que validam o motor de correlação causal: sintoma + snapshot de sensores + histórico + resposta esperada (hipótese top-1, contramedida, escalonamento). Nenhum dado real identificável.

## Arquivo
`golden_cases.yaml` (versão 1). Geração: autoria manual, sem semente aleatória; regras de referência em `edge-ai/knowledge-base/nasa_causal_graph.yaml`.

## Esquema de cada caso
| Campo | Descrição |
| :--- | :--- |
| `id` | Identificador `GC-NN-...` |
| `title` | Descrição curta do cenário |
| `input.symptoms` | Conceitos de sintoma do grafo (ex.: `headache`, `blurred_vision`) |
| `input.sensor_snapshot` | Métricas (`co2_ppm`, `hrv_ms`, `radiation_context`, `mission_day`, `posture` etc.) |
| `input.history` | `crew_id`, `mission_day` e tendências |
| `input.self_exam` | Resultados de `SELF_EXAM` (ex.: Amsler) |
| `expected.top1_hypothesis` | `id` da condição no grafo causal |
| `expected.mission_mode` | Modo de missão recomendado |
| `expected.countermeasures` | Lista de contramedidas esperadas |
| `expected.escalation` | `LOCAL`, `CREW` ou `STORE_AND_FORWARD` |
| `expected.actions` | Ações do grafo |
| `expected.linked_protocols` | IDs de `knowledge-base/protocols/` |
| `expected.min_top1_posterior` | Posterior mínima aceitável da hipótese top-1 |

## Casos mínimos obrigatórios
| ID | Cenário | Top-1 | Contramedida | Escalonamento |
| :--- | :--- | :--- | :--- | :--- |
| `GC-01-HYPERCAPNIA` | Cefaleia + CO2 alto + Amsler normal | `hypercapnia_co2` | Ventilação | `CREW` |
| `GC-02-SANS-VIIP` | Cefaleia + visão turva + Amsler alterado + CO2 normal | `sans_viip` | Thigh Cuffs + ultrassom + Complexo B | `CREW` |
| `GC-03-FATIGUE-DEHYDRATION` | Cefaleia + sono curto + HRV baixo + hidratação baixa | `sleep_immune_deprivation` | Nutrition SMO + ajuste circadiano | `LOCAL` |
| `GC-04-SPE-RADIATION-ALERT` | Evento SPE + HRV em queda | `radiation_ros` (`MODE_RADIATION_ALERT`) | Abrigo + Vitaminas C e E | `STORE_AND_FORWARD` |

## Limitações
- `min_top1_posterior` é limiar de aceitação provisório; recalibrar após rodar o motor.
- Casos apoiam decisão e não substituem o cirurgião de voo.
