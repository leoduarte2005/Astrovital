# knowledge-base/nasa_hrp_reports/

**Responsável:** Selliny (M1).

## Propósito
Um arquivo YAML por risco/perigo, estruturado para virar linha em `clinical_reports` + índice FTS5 e nó do grafo causal.

## Campos esperados por arquivo
| Campo | Descrição |
| :--- | :--- |
| `id` | Ex.: `HRP-RISK-SANS` |
| `hazard` | Um dos 5 Perigos (microgravidade, radiação, ambiente fechado hostil, isolamento/confinamento, distância da Terra) |
| `category` | `PHYSIOLOGICAL` (11) ou `BEHAVIORAL_BIOCHEMICAL` (8) |
| `subsystems` | Enum `subsystem` afetado |
| `problem` | Descrição do problema |
| `symptoms` | Lista de sintomas (sinônimos PT/EN para FTS5) |
| `sensor_signatures` | Sensor, métrica, limiar/direção, peso causal |
| `detection` | Método (CSI, I2C, autoexame) |
| `countermeasures` | Ação exata, ordem, protocolo vinculado |
| `escalation` | Regras `LOCAL` / `CREW` / `STORE_AND_FORWARD` |
| `source` | Documento e seção NASA HRP/CSA |

## Cobertura mínima obrigatória
SANS/VIIP (Thigh Cuffs, Complexo B), CANS/ROS (Vitaminas C e E, abrigo), hipercapnia, cortisol/CRP/vírus latentes, volume plasmático/anemia (Nutrition SMO), sono/circadiano/HRV, perda óssea/muscular, autonomia médica.

## Saída
Arquivos YAML validados; contagem 5 + 11 + 8 conferida pelo seed.
