# firmware/ — Firmware Único 5× ESP32-S3

**Responsável:** Nicolas (M2). Guia: [`docs/members/MEMBER-02-ESP32-CLUSTER.md`](../docs/members/MEMBER-02-ESP32-CLUSTER.md)

## Propósito
Projeto ESP-IDF v5.x (`IDF_TARGET=esp32s3`) gerando **um único binário** gravado nos 5 nós. Identidade derivada do MAC; `node_id`/`slot_id` atribuídos pela Central.

## Configuração de rádio obrigatória
- 2.4 GHz, canal 6, HT20.
- `esp_wifi_set_ps(WIFI_PS_NONE)` no boot.
- CSI habilitado (`esp-csi`), 1 antena.

## Estrutura esperada
| Item | Conteúdo |
| :--- | :--- |
| `CMakeLists.txt`, `sdkconfig.defaults`, `partitions.csv` | Projeto ESP-IDF (criados na Sprint 1) |
| [`main/`](main/README.md) | Módulos TDM, Wi-Fi CSI, DSP dual-core, I2C auto-discovery |

## Entradas / Saídas
- **Entrada (UDP `:5005`):** `CLUSTER_SYNC`, `MODE_CMD` de Leonardo (M4).
- **Saída (UDP `:5005`):** `NODE_HELLO`, `HEARTBEAT`, `CSI_FRAME`, `PERIPHERAL_DATA` para Leonardo (M4).
- Formato: `contracts/jsonschema/udp/`.

## Comandos
`make firmware-build`, `make firmware-flash PORT=COM5` (ou `/dev/ttyUSB0`).

## Aceite
20 enlaces em `< 1 s` após sync; jitter de slot `< 1.5 ms`; failover sem travar nós restantes; hot-plug I2C refletido em `peripherals`.
