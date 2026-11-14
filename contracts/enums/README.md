# contracts/enums/

**Responsável:** guardião Leonardo (M4); conteúdo clínico revisado por Selliny (M1).

## Propósito
Enumerações compartilhadas por todos os módulos (um arquivo JSON por enum).

## Enums esperados
| Enum | Valores (mínimo) |
| :--- | :--- |
| `mission_mode` | `MODE_CABIN_TOMOGRAPHY`, `MODE_REST_VITALS`, `MODE_COUNTERMEASURE_EXERCISE`, `MODE_RADIATION_ALERT` |
| `subsystem` | `CARDIOVASCULAR_FLUIDS`, `RESPIRATORY_ATMOSPHERE`, `NEURO_OCULAR_SANS`, `MUSCULOSKELETAL_POSTURE`, `IMMUNE_HEMATO_NUTRITION`, `NEUROBEHAVIORAL_RADIATION` |
| `severity` | `GREEN`, `YELLOW`, `RED` |
| `escalation` | `LOCAL`, `CREW`, `STORE_AND_FORWARD` |
| `udp_msg_type` | `CLUSTER_SYNC`, `MODE_CMD`, `NODE_HELLO`, `HEARTBEAT`, `CSI_FRAME`, `PERIPHERAL_DATA` |
| `ipc_msg_type` | `CSI_WINDOW`, `PERIPHERAL_SNAPSHOT`, `SET_ACTIVE_CREW`, `CREW_ACK`, `AI_INFERENCE`, `CHAT_CORRELATE_REQ`, `CHAT_CORRELATE_RESP`, `CALIBRATION_FEEDBACK` |
| `ws_msg_type` | `TELEMETRY_FRAME`, `ALERT_EVENT`, `CREW_STATE`, `CLUSTER_STATUS`, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`, `SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP` |
| `peripheral` | `MAX30102`, `BME280`, `SCD40` |
| `node_state` | `DISCOVERED`, `SYNCING`, `ACTIVE`, `SUSPECT`, `LOST` |

## Regras
- Só adicionar valores; nunca renomear/remover em `v1`.
- Nomes em `UPPER_SNAKE_CASE`.
