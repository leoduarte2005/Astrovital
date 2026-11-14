# central/internal/sim/

**Responsável:** Leonardo (M4). Simula os nós de Nicolas (M2) quando `--mock-cluster` ativo.

## Propósito
Modo `--mock-cluster` (desenvolvimento sem ESP32-S3 físico) e simulador de cenários espaciais para testes e demonstração.

## Cenários obrigatórios
| Cenário | Efeito sintético |
| :--- | :--- |
| `hypercapnia` | Sobe `SCD40` CO2 gradualmente acima do limiar |
| `sans` | Eleva PA + injeta resultado alterado na Grade de Amsler |
| `solar_storm` | Dispara evento SPE e comuta para `MODE_RADIATION_ALERT` |
| `dehydration_sleep` | Injeta sono curto, HRV reduzido e baixa hidratação |
| `node_loss` | Derruba 1 nó simulado para testar failover $N+1$ (20 → 12 enlaces) |

## Entradas / Saídas
- Injeta `NODE_HELLO`, `HEARTBEAT`, `CSI_FRAME` e `PERIPHERAL_DATA` nos mesmos canais de `udp/`, mantendo o resto do pipeline idêntico ao hardware real.
- Acionável por flag `--scenario` ou endpoint REST de desenvolvimento.
