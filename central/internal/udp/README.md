# central/internal/udp/

**Responsável:** Leonardo (M4). Recebe do firmware (Nicolas/M2) em `:5005`.

## Propósito
Transporte UDP na porta `:5005` entre a Orange Pi 4 Pro e os 5× ESP32-S3.

## Entradas / Saídas
- **Broadcast (10 Hz / ciclo 100 ms):** `CLUSTER_SYNC` com mapa de slots ativos e modo de missão; `MODE_CMD` imediato em mudanças de modo.
- **Recepção:** `NODE_HELLO`, `HEARTBEAT`, `CSI_FRAME`, `PERIPHERAL_DATA`.
- Entrega frames decodificados para `cluster/` e `pipeline/` via canais com buffer.

## Regras
- Ticker monotônico para o ciclo de 100 ms.
- Nunca bloqueia esperando `store/` ou `ipc/`; se canal encher, descarta frame antigo e incrementa métrica `dropped_frames`.
