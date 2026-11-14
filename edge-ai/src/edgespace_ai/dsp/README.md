# edge-ai/src/edgespace_ai/dsp/

**Responsável:** Santiago/Leonardo (M5). Processa CSI de Nicolas (M2) via Leonardo (M4).

## Propósito
Adaptação do pipeline RuView (`phase_sanitizer` + `csi_processor`) para **1 antena por nó ESP32-S3** e malha de até 20 enlaces.

## Pipeline por janela (`CSI_WINDOW`)
1. Descarte de subportadoras nulas/guarda e filtro Hampel contra spikes.
2. Unwrap de fase por subportadora e remoção de inclinação/offset linear (CFO/SFO) por regressão sobre o índice da subportadora.
3. Ponderação dos enlaces ativos (20 nominal; 12 ou 6 em failover) por SNR/RSSI.
4. FFT/Welch:
   - banda respiratória $0.1\text{–}0.5\text{ Hz}$ (FR)
   - banda cardíaca $0.8\text{–}2.5\text{ Hz}$ (FC/HRV em repouso)
   - energia Doppler/variância para movimento e cadência.

## Entradas / Saídas
- Entrada: `CSI_WINDOW` bruto dos enlaces ativos.
- Saída: vetor de features limpo para `inference/` e `adaptation/` + métrica de qualidade de sinal (`CALIBRATION_FEEDBACK`).
