# central/internal/cluster/

**Responsável:** Leonardo (M4). Gerencia os 5× ESP32-S3 de Nicolas (M2).

## Propósito
Gerenciamento do cluster homogêneo: atribuição dinâmica de `node_id` ($0..4$) e `slot_id` por MAC, máquina de estados por nó e failover $N+1$.

## Máquina de Estados do Nó
`DISCOVERED -> SYNCING -> ACTIVE -> SUSPECT -> LOST`
- Sem heartbeat por > 3 ciclos (300 ms): nó passa a `LOST`, `cluster/` recalcula mapa com $K$ slots ativos ($100/K$ ms) e `udp/` propaga novo `CLUSTER_SYNC`.
- Nó que retorna reentra como `SYNCING` e assume o próximo ciclo completo.

## Entradas / Saídas
- Consome: `NODE_HELLO`, `HEARTBEAT`, `PERIPHERAL_DATA` (bitmap de I2C descobertos).
- Produz: mapa de slots para `udp/`, `CLUSTER_STATUS` para `httpws/`, eventos de cluster para `store/`.
