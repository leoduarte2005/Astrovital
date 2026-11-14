# frontend/src/scene/

**Responsável:** Rafael (M3). Subsistemas vêm dos dados agregados de Leonardo (M4) e Santiago/Leonardo (M5).

## Propósito
Digital Twin 3D (Three.js) do astronauta ativo.

## Subsistemas (cores Verde/Amarelo/Vermelho)
| Enum `subsystem` | Região no modelo |
| :--- | :--- |
| `CARDIOVASCULAR_FLUIDS` | Coração, vasos, pernas (fluid shift) |
| `RESPIRATORY_ATMOSPHERE` | Pulmões |
| `NEURO_OCULAR_SANS` | Cabeça/olhos |
| `MUSCULOSKELETAL_POSTURE` | Esqueleto/músculos |
| `IMMUNE_HEMATO_NUTRITION` | Abdômen/sangue |
| `NEUROBEHAVIORAL_RADIATION` | Cérebro + aura de radiação |

## Entradas / Saídas
- Entrada: `TELEMETRY_FRAME.subsystems[]`, `ALERT_EVENT`, postura de `AI_INFERENCE` (via Central).
- Saída: seleção de subsistema (abre detalhes).

## Regras
- Render sob demanda (sem loop contínuo quando nada muda) para poupar bateria do tablet.
- Fallback 2D se WebGL indisponível.
