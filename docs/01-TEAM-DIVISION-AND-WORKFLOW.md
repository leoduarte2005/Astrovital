# EdgeSpace — Divisão da Equipe e Fluxo Paralelo (01)

> Objetivo: permitir que os **5 desenvolvedores** trabalhem em paralelo desde o Dia 1 sem bloqueios cruzados, usando `contracts/` e mocks determinísticos como fronteira.

---

## 1. Matriz de Responsabilidades (5 Membros)

| Membro | Responsável | Domínio Principal | Pastas Exclusivas | Interfaces que Produz | Interfaces que Consome |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Membro 1** | **Selliny** | Base Clínica NASA & Banco de Dados | `knowledge-base/`, `database/` | Schemas SQL (`WAL + FTS5`), seeds, JSONs/YAMLs NASA HRP/CSA, protocolos de autoexame, datasets sintéticos | `contracts/enums/` (IDs de modos, subsistemas, sensores, severidades) |
| **Membro 2** | **Nicolas** | Firmware Cluster 5× ESP32-S3 | `firmware/` | Pacotes UDP `:5005` (`NODE_HELLO`, `CSI_FRAME`, `PERIPHERAL_DATA`, `HEARTBEAT`) | `CLUSTER_SYNC` e `MODE_CMD` UDP `:5005` |
| **Membro 3** | **Rafael** | Frontend Tablet/Monitor, Gráficos & Chatbot | `frontend/` | UI compilada (`dist/`), eventos WebSocket cliente (`SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP`) | Stream WS `:8000` (`TELEMETRY_FRAME`, `ALERT_EVENT`, `CHAT_REPLY`, `CREW_STATE`) e REST `/api/*` |
| **Membro 4** | **Leonardo** (Integrador) | Orquestrador Central Go (Orange Pi 4 Pro) & Integração | `central/`, `tools/`, `deploy/`, guardião de `contracts/` | UDP `:5005` (`CLUSTER_SYNC`), IPC `:5006` (`AI_REQUEST`), HTTP/WS `:8000`, `--mock-cluster` | UDP dos ESP32-S3, IPC respostas da Edge AI, schemas/migrations de Selliny |
| **Membro 5** | **Santiago / Leonardo** | Edge AI, Adaptação por `crew_id` & Correlação Causal | `edge-ai/` | Respostas IPC `:5006` (`VITALS_OUT`, `ANOMALY_OUT`, `CORRELATION_OUT`), `baseline_ae_<crew_id>.onnx` | Frames CSI/I2C do IPC `:5006`, base SQLite (somente leitura) + datasets de Selliny |

---

## 2. Regras de Ouro Anti-Conflito

1. **Propriedade de Diretório:** cada membro abre PRs alterando apenas suas pastas exclusivas. Alterar pasta de outro membro exige revisão do dono da pasta.
2. **Mudança em `contracts/`:** qualquer alteração em enum, JSON Schema ou fixture exige aprovação de Leonardo (M4) + 1 membro afetado, com atualização imediata de `tools/validate_contracts.py` e dos structs Go/TS/Python.
3. **Escritor Único do SQLite:** Selliny (M1) define o schema em `database/migrations/`, mas em runtime **somente `central/internal/store` (Leonardo/M4)** executa `INSERT/UPDATE/DELETE`. Santiago/Leonardo (M5, `edge-ai/`) lê apenas em `file:edgespace.db?mode=ro`.
4. **Mocks Primeiro:**
   - Rafael (M3) desenvolve todo o Frontend contra o mock server / `--mock-cluster` de Leonardo (M4) (não precisa de ESP32 nem Python rodando).
   - Santiago/Leonardo (M5) desenvolve e testa DSP/ONNX/Correlação offline usando `knowledge-base/datasets/` de Selliny (M1) e fixtures em `contracts/fixtures/`.
   - Nicolas (M2) valida firmware contra um script/receptor UDP `:5005` simples antes de plugar na Orange Pi.

---

## 3. Contratos entre Fronteiras

| Fronteira | Transporte | Contrato Canônico | Frequência |
| :--- | :--- | :--- | :--- |
| `central` ↔ `firmware` | UDP `:5005` | `CLUSTER_SYNC` (Central→Nós, 10 Hz); `CSI_FRAME` + `PERIPHERAL_DATA` (Nós→Central) | 100 ms ciclo TDM (5×20 ms); I2C 1 Hz |
| `central` ↔ `edge-ai` | TCP `127.0.0.1:5006` | Frames length-prefixed JSON: `CSI_WINDOW`, `SET_ACTIVE_CREW`, `CHAT_CORRELATE_REQ` ↔ `AI_INFERENCE`, `CHAT_CORRELATE_RESP` | 1–10 Hz (janelas deslizantes) + sob demanda (chat) |
| `central` ↔ `frontend` | WS + REST `:8000` | Envelope `{"v":1,"type":...,"ts_us":...,"crew_id":...,"payload":...}` | Push 2–10 Hz para UI; REST para histórico/seeds |
| `central` ↔ `database` | SQLite local (`WAL`) | `database/migrations/*.sql` + queries FTS5 | Contínuo (batch/tx curtas) |

---

## 4. Sequência de Integração por Sprints

| Sprint | Marco Coletivo | Entregável de Cada Membro |
| :--- | :--- | :--- |
| **Sprint 0 (Pré-req)** | Contratos travados | Restaurar `contracts/` e `tools/` no repo; validar schemas v1 |
| **Sprint 1 (Vertical Slice Mock)** | UI 3D recebe telemetria mock e troca `crew_id` | Selliny: migrations + 3 perfis + 5 Perigos; Nicolas: TDM TX/RX 2 nós; Rafael: shell React + seletor astronauta + Twin 3D; Leonardo: UDP + `--mock-cluster` + WS `:8000`; Santiago/Leonardo: `phase_sanitizer` + FFT em fixtures |
| **Sprint 2 (Cluster 5× + IA Basal)** | 5 ESP32-S3 reais → Central → ONNX → UI | Selliny: 11 riscos + 8 riscos + datasets; Nicolas: 5 nós TDM + `MAX30102/BME280/SCD40`; Rafael: gráficos longitudinais + tutoriais; Leonardo: failover $N+1$ + SQLite writer; Santiago/Leonardo: ONNX postura/vitais + `baseline_ae_<crew_id>.onnx` |
| **Sprint 3 (Chatbot Causal + Orange Pi)** | Queixa no Chatbot cruza ESP32 + NASA HRP + histórico | Selliny: golden cases cefaleia/SANS/CO2/radiação; Nicolas: stress 24h RF; Rafael: fluxo completo Chatbot + calibração; Leonardo: deploy ARM64 + hostapd + outbox Store-and-Forward; Santiago/Leonardo: motor causal + FTS5 RAG |
| **Sprint 4 (Ensaio de Missão / Demo)** | Cenários de crise ao vivo | Simulador dispara hipercapnia, SANS, tempestade solar e queda de 1 nó com failover $N+1$ |

---

## 5. Guias Individuais

- Selliny (M1): [`members/MEMBER-01-DATABASE-KNOWLEDGE.md`](members/MEMBER-01-DATABASE-KNOWLEDGE.md)
- Nicolas (M2): [`members/MEMBER-02-ESP32-CLUSTER.md`](members/MEMBER-02-ESP32-CLUSTER.md)
- Rafael (M3): [`members/MEMBER-03-FRONTEND-CHATBOT.md`](members/MEMBER-03-FRONTEND-CHATBOT.md)
- Leonardo (M4): [`members/MEMBER-04-CENTRAL-GO.md`](members/MEMBER-04-CENTRAL-GO.md)
- Santiago / Leonardo (M5): [`members/MEMBER-05-EDGE-AI-ADAPTIVE.md`](members/MEMBER-05-EDGE-AI-ADAPTIVE.md)
