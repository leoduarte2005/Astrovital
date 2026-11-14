# Membro 2 (Nicolas) — Firmware Cluster 5× ESP32-S3

**Pasta sob responsabilidade exclusiva:**
- `firmware/` (`firmware/main/`)

---

## 1. Missão do Membro 2

Desenvolver uma **imagem única e homogênea de firmware** em **ESP-IDF v5.x** para os **5 microcontroladores ESP32-S3**, garantindo sincronização TDM de 100 ms sem colisão RF, extração de Wi-Fi CSI em 2.4 GHz ch 6 HT20, pré-processamento dual-core e auto-discovery de sensores I2C/GPIO.

---

## 2. Escopo Técnico Detalhado

### 2.1 Imagem Única e Identidade Dinâmica
- Proibido compilar binários diferentes por nó (`node_0.bin`, `node_1.bin` etc.).
- O nó deriva sua identidade do MAC de fábrica (`esp_read_mac`) e negocia seu `node_id` lógico ($0..4$) e `slot_id` com a Central via `NODE_HELLO` e `CLUSTER_SYNC` na porta UDP `:5005`.

### 2.2 Rádio Wi-Fi e `esp-csi` (Regras Críticas)
- Banda e canal fixos: **2.4 GHz, Canal 6, largura HT20** (52 subportadoras LLTF / 64 HT-LTF conforme configuração RuView).
- **Power Save estritamente desativado:** `esp_wifi_set_ps(WIFI_PS_NONE)` obrigatório no boot. Qualquer economia de energia destrói o determinismo do slot TDM de 20 ms e corrompe a fase CSI.
- Antena única por nó (`1T1R`), fornecendo CSI bruto (pares `I/Q` int8 por subportadora + RSSI + noise floor + timestamp em microssegundos `esp_timer_get_time()`).

### 2.3 Sincronização TDM Multi-Estática (20 Enlaces)
- Ciclo nominal: **100 ms** dividido em **5 slots de 20 ms** (ou $K$ slots dinâmicos se a Central sinalizar failover $N+1$ no `CLUSTER_SYNC`).
- Quando `current_slot == my_slot_id`: o nó entra em papel **TX** e dispara burst de frames de sondagem CSI.
- Quando `current_slot != my_slot_id`: o nó permanece em **RX**, captura o callback `wifi_csi_cb_t` dos outros 4 nós transmissores, etiqueta o par `(tx_node_id, rx_node_id)` e enfileira para o Core 1.
- Resultado na cabine: $5 \times 4 = 20$ enlaces direcionais completos a cada 100 ms (10 Hz).

### 2.4 Arquitetura Dual-Core (ESP32-S3 Xtensa LX7)
- **Core 0 (PRO_CPU — RF & Rede):** stack Wi-Fi, callback ISR-safe de `esp-csi` (copia apenas para ring buffer estático em SRAM), receptor de `CLUSTER_SYNC` e transmissor UDP `:5005`. Zero alocação dinâmica (`malloc`) dentro do callback CSI.
- **Core 1 (APP_CPU — DSP Embarcado & I2C):**
  - Filtragem inicial de outliers/pacotes truncados, desempacotamento `I/Q` e adaptação da taxa de envio conforme o modo de missão (`MODE_CABIN_TOMOGRAPHY`, `MODE_REST_VITALS`, `MODE_COUNTERMEASURE_EXERCISE`, `MODE_RADIATION_ALERT`).
  - Barramento I2C com **auto-discovery** periódico:
    - `MAX30102` (`0x57`): oximetria óptica ($\text{SpO}_2$) e fotopletismografia (FC/PPG) quando o astronauta apoia o dedo.
    - `BME280` (`0x76` / `0x77`): temperatura, umidade relativa e pressão barométrica da cabine.
    - `SCD40` (`0x62`): concentração de $\text{CO}_2$ em ppm (crítico para diferenciar cefaleia por hipercapnia vs. SANS).
  - Atuadores locais (LED RGB / buzzer de abrigo em `MODE_RADIATION_ALERT`).

---

## 3. Entradas, Saídas e Critérios de Aceite

- **Consome (UDP `:5005` de Leonardo/M4):** `CLUSTER_SYNC` (mapa de slots ativos, época de sincronismo, `mission_mode` atual).
- **Produz (UDP `:5005` para Leonardo/M4):** `NODE_HELLO`, `HEARTBEAT`, `CSI_FRAME` (compacto) e `PERIPHERAL_DATA` (1 Hz com bitmap de sensores descobertos).
- **Critérios de aceite:**
  1. Mesmo `.bin` gravado nos 5 ESP32-S3 converge para 20 enlaces em `< 1 s` após receber `CLUSTER_SYNC`.
  2. Jitter de slot TDM `< 1.5 ms` com `WIFI_PS_NONE`.
  3. Desligar 1 ESP32-S3 da tomada não trava os outros 4 (reconfiguração suave para 12 enlaces $4 \times 3$ comandada pela Central).
  4. Plugar/desplugar `MAX30102`, `BME280` ou `SCD40` é refletido automaticamente no campo `peripherals` sem reboot.
