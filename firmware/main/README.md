# firmware/main/

**Responsável:** Nicolas (M2).

## Propósito
Componente principal do firmware. Módulos separados por responsabilidade e núcleo.

## Módulos esperados
| Módulo | Núcleo | Função |
| :--- | :--- | :--- |
| `app_main` | — | Boot, NVS, Wi-Fi STA no AP da Orange Pi, `WIFI_PS_NONE`, criação de tasks com afinidade |
| `tdm_sync` | Core 0 | Recebe `CLUSTER_SYNC`, alinha época, calcula slot atual, alterna TX/RX |
| `csi_capture` | Core 0 | Callback `esp-csi`: copia I/Q + RSSI + `timestamp_us` para ring buffer estático (sem `malloc`) |
| `csi_tx_probe` | Core 0 | Burst de frames de sondagem no slot próprio |
| `udp_link` | Core 0 | Socket UDP `:5005`, `NODE_HELLO`, `HEARTBEAT`, envio de frames |
| `dsp_pre` | Core 1 | Validação, descarte de pacotes truncados, empacotamento por enlace `(tx,rx)`, taxa por modo de missão |
| `i2c_discovery` | Core 1 | Varredura periódica: `MAX30102` `0x57`, `BME280` `0x76/0x77`, `SCD40` `0x62`; bitmap `peripherals` |
| `periph_drivers` | Core 1 | Leitura dos sensores descobertos (1 Hz) |
| `actuators` | Core 1 | LED/buzzer (alerta de abrigo em `MODE_RADIATION_ALERT`) |

## Regras
- Comunicação entre núcleos só via filas/ring buffers pré-alocados.
- Nenhum `node_id` hardcoded.
- Constantes de protocolo espelham `contracts/enums/`.
