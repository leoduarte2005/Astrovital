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

## Golden cases mínimos
1. Cefaleia + CO2 alto + Amsler normal: hipercapnia, ventilação.
2. Cefaleia + visão turva + Amsler alterado + CO2 normal: SANS/VIIP, Thigh Cuffs + ultrassom + Complexo B.
3. Cefaleia + sono curto + HRV baixo + hidratação baixa: fadiga/desidratação, Nutrition SMO + ajuste circadiano.
4. Evento SPE + HRV em queda: `MODE_RADIATION_ALERT`, abrigo + Vitaminas C e E.

## Regras
- Arquivos grandes: formato compacto (`.npz`/`.parquet`) e documentados aqui com tamanho.
- Cada dataset com `README` de geração (seed aleatória, parâmetros).
