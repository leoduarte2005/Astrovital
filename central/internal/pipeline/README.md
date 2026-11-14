# central/internal/pipeline/

**Responsável:** Leonardo (M4). Envia CSI/I2C para Santiago/Leonardo (M5) via `:5006`.

## Propósito
Ring buffers pré-alocados dos **20 enlaces CSI** `(tx_node_id, rx_node_id)` e agregação das leituras I2C (`MAX30102`, `BME280`, `SCD40`).

## Entradas / Saídas
- Consome: `CSI_FRAME` e `PERIPHERAL_DATA` vindos de `udp/` (ou `sim/`).
- Monta janelas deslizantes sincronizadas (com máscara de enlaces ativos em caso de failover 12 ou 6 enlaces) e envia `CSI_WINDOW` + `PERIPHERAL_SNAPSHOT` para `ipc/`.
- Envia snapshot ambiental e séries brutas decimadas para `store/` e `httpws/`.

## Regras
- Pré-alocar ring buffers por enlace na inicialização; evitar GC pressure.
- Anexar `crew_id` ativo (consultando `session/`) apenas no envelope de saída para inferência biométrica; dados ambientais (`SCD40`, `BME280`) permanecem associados à cabine.
