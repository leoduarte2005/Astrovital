# EdgeSpace — Guia Rápido de Demonstração (Jurados NASA Space Apps)

Sistema **100% offline** de monitoramento biomédico orbital por tomografia Wi-Fi CSI, sensores fisiológicos/ambientais e IA embarcada (ONNX + Grafo Causal SQLite + SLM local).

---

## Escolha Sua Trilha

| Trilha | Quando usar | Hardware necessário | Comando único |
| :--- | :--- | :--- | :--- |
| **A — Dados Mockados** | Avaliação imediata em qualquer notebook ou Orange Pi | Nenhum (5× ESP32-S3 simulados em memória) | `make demo-mock` |
| **B — Hardware Real** | Demonstração ao vivo com placas físicas + sensores | 5× ESP32-S3 + `MAX30102`, `BME280`, `SCD40` + Wi-Fi 2.4 GHz | `make demo-real` |

> **Observação:** Na Trilha A, **apenas os rádios ESP32-S3 são simulados**. Frontend React/Three.js, Central Go, Edge AI (ONNX + SLM) e banco SQLite são 100% reais.

---

## Trilha A — Demonstração Completa com Dados Mockados (1 Comando)

### 1. Iniciar o Ecossistema

Escolha o comando conforme seu sistema operacional:

- **Linux / Orange Pi 4 Pro / WSL / Git Bash:**
  ```bash
  make demo-mock
  # ou diretamente:
  ./scripts/demo.sh --mock
  ```
- **Windows PowerShell:**
  ```powershell
  .\scripts\demo.ps1 -Mode mock
  ```

**Opções úteis:**
- `-NoSlm` / `--no-slm`: desativa o modelo SLM (~1.1 GB) em máquinas com pouca RAM, mantendo ONNX + Grafo Causal SQLite.
- `-NoOpen` / `--no-open`: não abre o navegador automaticamente (ideal para acesso via SSH).
- `-Scenario <nome>` / `--scenario <nome>`: inicia direto em um evento clínico (`nominal`, `hypercapnia`, `sans`, `solar_storm`, `dehydration_sleep`, `node_loss`).

Aguarde o painel no terminal confirmar `Painel Web: http://localhost:5173/#/crew`. O navegador abrirá automaticamente na tela de seleção de tripulante.

---

### 2. Roteiro Interativo em 5 Passos na Tela

#### Passo 1 — Telemetria dos 20 Enlaces TDM e Sinais Vitais
- No painel principal, confirme o status **`CLUSTER ACTIVE (5/5 NODES • 20 LINKS)`**.
- Observe os 20 enlaces ponto-a-ponto (matriz $5 \times 4$ direcional) e os sinais vitais em tempo real:
  - **Frequência Cardíaca (FC)**, **SpO₂**, **Frequência Respiratória (FR)**, **CO₂ (ppm)**, **Temperatura** e **Postura / Cadência de Exercício** inferidas via Wi-Fi CSI + modelos `.onnx`.

#### Passo 2 — Troca de Astronauta e Adaptação de Baseline
- No seletor de tripulante no topo da tela, alterne entre **`crew_001`** e **`crew_002`**.
- Observe que os limiares fisiológicos e o desvio de anomalia (Autoencoder / Isolation Forest) se recalculam automaticamente para o baseline individual armazenado no SQLite.

#### Passo 3 — Cenários Clínicos e Failover $N+1$
- No painel de cenários (ou via API de simulação), dispare sequencialmente:
  1. **`hypercapnia`**: elevação progressiva de $\text{CO}_2$, aumento de FR/FC e geração de alerta clínico causal.
  2. **`sans`** (*Spaceflight-Associated Neuro-ocular Syndrome*): alteração neuro-ocular correlacionada com pressão intracraniana/edema.
  3. **`node_loss`**: simula perda física de um nó ESP32-S3; valide a transição para failover $N+1$ (de 20 para 12 enlaces ativos) mantendo monitoramento contínuo sem queda da Central.

#### Passo 4 — Chatbot Clínico Offline + Grafo Causal
- Abra o **Assistente Clínico** no painel lateral.
- Envie sintomas reais em português, como:
  - *"Estou com dor de cabeça forte e visão turva"*
  - *"Estou com dor de barriga e náusea"*
- Verifique que o assistente **não responde texto genérico**: ele cruza o sintoma relatado com os sensores ao vivo (ex.: $\text{CO}_2$, $\text{SpO}_2$, FC, radiação/hidratação) e com o grafo causal médico embarcado no SQLite (`FTS5`).

#### Passo 5 — Protocolo de Autoexame (Grade de Amsler)
- No módulo de **Autoexame**, inicie o protocolo **Grade de Amsler** (rastreio rápido de SANS).
- Marque eventuais distorções visuais ou resposta normal e conclua o exame; o resultado é persistido na linha do tempo clínica do astronauta ativo.

Para encerrar tudo sem deixar processos órfãos, pressione **`Ctrl+C`** no terminal.

---

## Trilha B — Demonstração com Cluster Físico 5× ESP32-S3 + Sensores I2C

### 1. Pré-requisitos de Hardware e Rede

- **5× placas ESP32-S3** (com PSRAM / Wi-Fi 2.4 GHz).
- **Barramento I2C nos nós sensores** (pinagem padrão do firmware):
  - `SDA = GPIO8`
  - `SCL = GPIO9`
  - Sensores compatíveis: **`MAX30102`** (oximetria/FC), **`BME280`** (temperatura/umidade/pressão) e **`SCD40`** ($\text{CO}_2$ real).
- **Rede Wi-Fi dedicada:** **2.4 GHz, Canal 6, largura HT20** (ex.: Hotspot da Orange Pi 4 Pro ou roteador isolado de bancada com a Central na mesma sub-rede).

### 2. Gravar o Firmware Único Homogêneo nos 5 ESP32-S3

O firmware do EdgeSpace é **homogêneo** (o mesmo binário vai para todos os 5 nós; a identidade e os slots TDM são negociados pela Central via `CLUSTER_SYNC`).

1. Conecte os ESP32-S3 via USB ao computador (um por vez ou todos em hub USB com driver serial).
2. Execute:
   - **Linux / Orange Pi:** `make flash-esp` (ou `./scripts/demo.sh --flash-only`)
   - **Windows PowerShell:** `.\scripts\demo.ps1 -FlashOnly`
   - Para especificar uma porta manualmente: `make flash-esp PORT=/dev/ttyUSB0` ou `.\scripts\demo.ps1 -FlashOnly -Port COM5`.

> **Atalho tudo-em-um:** `.\scripts\demo.ps1 -Mode real -Flash` (ou `./scripts/demo.sh --real --flash`) compila, grava os ESP32 conectados e já sobe a Central logo em seguida.

### 3. Subir a Central em Modo Hardware Real

1. Desconecte os cabos USB de gravação (ou apenas alimente os 5 ESP32-S3 próximos à área de teste).
2. Inicie o receptor UDP `:5005`:
   - **Linux / Orange Pi:** `make demo-real` (ou `./scripts/demo.sh --real --no-open` em modo headless)
   - **Windows PowerShell:** `.\scripts\demo.ps1 -Mode real`

### 4. Validação Ao Vivo no Painel (`http://localhost:5173/#/crew`)

Confirme os 3 indicadores de operação real:
1. **5/5 Nós em `ACTIVE`:** todos os nós físicos aparecem online após o handshake `CLUSTER_SYNC`.
2. **20 Enlaces TDM formados:** matriz de enlaces CSI mostra pacotes contínuos sem perda crítica.
3. **Leitura Óptica & Ambiental Real:** aproxime o dedo do **`MAX30102`** para ver onda PPG/FC/SpO₂ responder ao vivo e respire próximo ao **`SCD40`** para ver o $\text{CO}_2$ subir em tempo real no gráfico e acionar o diagnóstico causal da IA.
