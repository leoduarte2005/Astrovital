# EdgeSpace — Auditoria Técnica Integral e Plano de Ação

> **Escopo:** Auditoria ponta a ponta (somente leitura) de todas as camadas do projeto **EdgeSpace** (NASA Space Apps Challenge — Orange Pi 4 Pro `linux/arm64`, 100% Offline).
> **Data da Auditoria:** 2026-11-15
> **Base:** Inspeção direta do código-fonte, schemas SQLite, modelos ONNX/GGUF, scripts e testes executados no workspace.

---

## Seção 1 — Mapa Completo da Arquitetura e Fluxos Ponta a Ponta

### 1.1 Diagrama Arquitetural Real (Estado Atual no Código)

```text
+======================================================================================+
| CAMADA DE CAMPO: 5x ESP32-S3 (firmware/main/app_main.c) — ESTADO: STUB / QUEBRADO    |
|  [ESP32-S3] --(example_connect SSID="server8874", all-ch scan)--> Gateway IP:5005    |
|  - Envia APENAS string ASCII "%.2f" da amplitude media do BSSID do AP                |
|  - NAO recebe CLUSTER_SYNC/MODE_CMD | NAO roda TDM 5x20ms | NAO le MAX30102/BME/SCD |
+==========================================|===========================================+
                                           X  (INCOMPATIVEL com udp.Receiver :5005)
                                           |
     [SIMULACAO FUNCIONAL]                 |  [HARDWARE REAL ESPERADO]
     central/internal/sim/                 v  UDP :5005 (JSON+'\n'+10B LE+I/Q int16*1000)
+======================================================================================+
| ESTACAO CENTRAL GO (central/ | CGO_ENABLED=0 | Porta HTTP/WS :8000 | UDP :5005)     |
|                                                                                      |
|  udp.Receiver (:5005) ----+--> cluster.Manager (FSM DISCOVERED->ACTIVE->SUSPECT->LOST|
|  udp.Transmitter (10 Hz) -+    Failover N+1, SlotMap 20/12/6, registry MAC->node_id) |
|         |                                     |                                      |
|         v (DataCh 512)                        | (ActiveLinkMask)                     |
|  pipeline.Pipeline (zero-GC ring [20][300], 4 cycleBuckets, grace 30ms)              |
|    |-- 2 Hz CSI_WINDOW (5 ciclos) ----------> ipc.Client (TCP 127.0.0.1:5006)        |
|    |-- 1 Hz PERIPHERAL_SNAPSHOT ------------>   - HiPri (cap 16) / LoPri (cap 8)     |
|    |-- 1 Hz Telemetry/Peripherals ---------->   - uint32 BE + JSON v=1               |
|    |-- Alertas RED + 30s CSI blob ----------> store.Store (modernc.org/sqlite WAL)   |
|    '-- Latest (atomic.Pointer) ------------->   - Single-writer batch 250ms          |
|                                                 - Reader pool 4 conns (mode=ro)      |
|  session.Manager (single-writer goroutine) <--->  - Rollup horario (shift/daily)     |
|    - SwapSeq, hot-swap crew_id, Chat/SelfExam/Calib                                  |
|                                                                                      |
|  httpws.Server (:8000)                                                               |
|    |-- REST: /healthz, /api/metrics, /api/crew*, /api/protocols/{id}, /api/alerts,   |
|    |         /api/outbox, /api/dev/*                                                 |
|    |-- WS /ws: Push TELEMETRY_FRAME (2-10 Hz), CLUSTER_STATUS (1 Hz), ALERT_EVENT,   |
|    |           CREW_STATE, CHAT_REPLY, CALIBRATION_FEEDBACK, ERROR                   |
|    '-- embed ui/* -> CONTEM APENAS PLACEHOLDER (index.html/app.js/style.css 3.7 KB)  |
+=========================|===================================|========================+
                          | TCP 127.0.0.1:5006                | HTTP/WS :8000
                          v                                   X (QUEBRADO NO FRONTEND)
+===============================================+   +==================================+
| EDGE AI WORKER (edge-ai/ | Python 3.11+       |   | FRONTEND (frontend/ | Vite/TS)  |
|  ipc.IPCServer (:5006)                        |   | - IMPORTS QUEBRADOS:             |
|   |-- dsp/: CSIProcessor (1-antena),          |   |   @/lib/data/* NAO EXISTE        |
|   |   LinkFusion, WindowBuffer, FeatureExt(64)|   | - ASSETS 3D AUSENTES:            |
|   |-- inference/: ONNXRuntime (2 threads):    |   |   data/models/*.glb NAO EXISTE   |
|   |   posture_cls, exercise_cadence,          |   | - TOOLS AUSENTES: tools/*        |
|   |   vitals_reg (Regra P4 <=0.65),           |   | - TELAS PLACEHOLDER: Charts,     |
|   |   anomaly_scorer (AE+IForest)             |   |   Diagnosis, Encyclopedia, Prof. |
|   |-- adaptation/: BaselineRegistry (SQLite   |   | - CSP Go bloqueia Draco WASM,    |
|   |   mode=ro + bug codigo morto JSON),       |   |   Blob Worker e ws:// em Chrome90|
|   |   CalibrationEngine (EMA 64-dim)          |   +==================================+
|   |-- correlation/: SymptomExtractor (PT/EN), |
|   |   ClinicalStore (SQLite FTS5 BM25),       |   +==================================+
|   |   CausalGraph + ClinicalRepository,       |   | BANCO DE DADOS (database/)       |
|   |   Disambiguator (IG Shannon),             |   | - Operacional: var/edgespace.db  |
|   |   LocalSLMSynthesizer (Qwen2.5-1.5B GGUF) |   |   Migrations 0001..0006 aplicadas|
|   '-------------------------------------------'   |   WAL + FTS5 + 26 condicoes      |
|                                                   | - Pesquisa (separado, RO):       |
|   [DEPLOY ARM64: deploy/ e tools/ e contracts/    |   database/space_health_sqlite/  |
|    CONTEUDO AUSENTE — APENAS READMEs]             +==================================+
+======================================================================================+
```

### 1.2 Inventário Completo dos Módulos

| Módulo | Caminho | Stack | Status Real | Dependências / Observações |
| :--- | :--- | :--- | :--- | :--- |
| Contratos SSOT | `contracts/` | JSON Schema / Fixtures | **QUEBRADO** | Só `README.md`/`.owner`. Zero `.json` em `enums/`, `jsonschema/`, `fixtures/`. |
| Utilitários CI | `tools/` | Python | **QUEBRADO** | Só `README.md`/`.owner`. `validate_contracts.py` ausente. |
| Deploy ARM64 | `deploy/` | systemd/hostapd/nftables | **QUEBRADO** | Só `README.md`/`.owner`. Sem configs de SO/rede/systemd. |
| Firmware Cluster | `firmware/` | C / ESP-IDF v5 (`esp32s3`) | **STUB/EXEMPLO** | `app_main.c` é protótipo AP-only; `csi_processor.py` órfão porta `5556`; falta `partitions.csv`, TDM, I2C, UDP `:5005`. |
| Central Entrypoint | `central/cmd/edgespace-central/` | Go 1.27 (`CGO_ENABLED=0`) | **PRONTO*** | Bugs em `wiring.go` (`HandleChatMsg` omite pressão/umidade/HR MAX30102) e `main.go` (`SetCrew` inicial sem espera fora `--mock-ai`). |
| Central Contracts | `central/internal/contracts/` | Go | **PRONTO** | Stdlib. Espelha v1 + P1–P6; sem validação cruzada contra `contracts/`. |
| Central UDP | `central/internal/udp/` | Go | **PRONTO*** | `DecodeCSIBinary(csiPayload, nil)` aloca slice/pacote; `peripherals` vs `supported_peripherals`. |
| Central Cluster | `central/internal/cluster/` | Go | **PRONTO** | FSM 5 estados, `SlotMap` 20/12/6, failover `< 500 ms`. |
| Central Pipeline | `central/internal/pipeline/` | Go | **PRONTO*** | Ring `[20][300]` zero-GC; bug no override de FC em `MODE_COUNTERMEASURE_EXERCISE`. |
| Central Session | `central/internal/session/` | Go | **PRONTO*** | `DefaultChatTimeout=0` (ilimitado); `SaveBaseline` não grava `per_posture_stats_json`. |
| Central IPC | `central/internal/ipc/` | Go | **PRONTO** | `uint32 BE + JSON`, HiPri/LoPri, watchdog 3s, backoff exponencial. |
| Central Store | `central/internal/store/` | Go (`modernc.org/sqlite`) | **PRONTO*** | `QueryTimeseries` ignora `metric` e usa `COALESCE(...,0)`; omite `data_class` em inserts. |
| Central Sim | `central/internal/sim/` | Go | **PRONTO** | 5 cenários (`hypercapnia`, `sans`, `solar_storm`, `dehydration_sleep`, `node_loss`) + `MockAI`. |
| Central HTTP/WS | `central/internal/httpws/` | Go (`coder/websocket`) | **PARCIAL** | CSP bloqueia Draco WASM/Worker/`ws://` Chrome 90; `ui/` tem placeholder. |
| Edge AI Main/Cfg | `edge-ai/src/edgespace_ai/` | Python 3.11+ (`pydantic`) | **PRONTO*** | `slm_auto_download=True` viola regra 100% offline se GGUF faltar. |
| Edge AI IPC | `edge-ai/src/edgespace_ai/ipc/` | Python (`asyncio`) | **PRONTO** | HiPri/LoPri, descarte `1000ms`, `CHAT_CORRELATE_REQ` assíncrono em task. |
| Edge AI DSP | `edge-ai/src/edgespace_ai/dsp/` | Python (`numpy`, `scipy`) | **PRONTO** | Unwrap, remoção linear STO/CFO, Hampel, fusão SNR, 64 features. |
| Edge AI Inferência | `edge-ai/src/edgespace_ai/inference/` | Python (`onnxruntime`) | **PRONTO** | 5 `.onnx` no boot (`intra_op=2`). Falta `baseline_ae_<crew_id>.onnx` (usa default). |
| Edge AI Adaptação | `edge-ai/src/edgespace_ai/adaptation/` | Python (`numpy`, `sqlite3`) | **PARCIAL** | Código morto em `baseline_registry.py:190-238`; ignora `SYNTHETIC_SEED`; não persiste JSON. |
| Edge AI Correlação | `edge-ai/src/edgespace_ai/correlation/` | Python (`sqlite3`, `llama-cpp`) | **PARCIAL** | FTS5 BM25 + grafo causal + IG + Qwen2.5-1.5B (1.1 GB). Duplo motor pode divergir. |
| Edge AI Treino | `edge-ai/training/` | Python (`sklearn`, `skl2onnx`) | **PRONTO** | Gera os 5 `.onnx` + `baseline_default.json`. |
| Banco Operacional | `database/migrations/`, `tools/` | SQLite WAL + FTS5 / Py | **PRONTO** | Migrations `0001..0006` + 36 golden cases (`operational.py validate` 14/14 OK). |
| Banco Pesquisa | `database/space_health_sqlite/` | SQLite / Python | **PRONTO** | Base pesquisa RO; 25/25 testes unitários em `database/tests/` OK. |
| Knowledge Base | `knowledge-base/` | YAML / JSON | **PRONTO** | 23 relatórios + 5 perigos + 14 protocolos + 36 golden cases + datasets. |
| Frontend | `frontend/` | React 19 + Vite 8 + Three | **QUEBRADO** | Sem `node_modules/`, `dist/`, `src/lib/data/`, `data/models/*.glb`, `tools/`; telas placeholder. |
| Scripts & Make | `scripts/`, `Makefile` | PowerShell / Bash / Make | **PARCIAL** | `run_stack.ps1` omite `migrate`; `Makefile` usa `npm ci` (repo é `pnpm`) e cita `wheels/` inexistente. |

> **Evidência de validação executada na auditoria:** `operational.py validate` PASSOU (14/14, 36/36 golden cases); `database/tests` PASSOU (25/25); `edge-ai` `pytest` iniciou com 15/15 iniciais; `go test ./...` PASSOU em 9/10 pacotes (`internal/contracts` bloqueado apenas pelo Smart App Control do Windows ao rodar `contracts.test.exe`).

---

## Seção 2 — Matriz de Verificação de Lógica e Contratos (Cruzamento Entre Camadas)

### 2.1 Cluster ESP32-S3 (`firmware/`) ↔ Central Go (`central/internal/udp/` + `cluster/`)

| Requisito / Campo | Contrato / Esperado | `firmware/main/app_main.c` + `sdkconfig` | `central/internal/udp/` + `contracts/udp.go` + `cluster/` | Status |
| :--- | :--- | :--- | :--- | :--- |
| Wi-Fi Canal / PS | 2.4 GHz, Canal 6, HT20, `WIFI_PS_NONE` | `esp_wifi_set_ps(WIFI_PS_NONE)` (L117), **mas** `example_connect()` usa SSID `"server8874"` + `ALL_CHANNEL` scan (`sdkconfig:579-583`) | Espera AP em `10.42.0.1` ch 6 HT20 (`deploy/hostapd/` ausente) | **DIVERGE** |
| TDM `CLUSTER_SYNC` | 100 ms (10 Hz), 5×20 ms (`cycle_seq`, `slot_ms`, `active_node_mask`, `slots[]`) | **Não implementado** (não escuta UDP `:5005`) | `transmitter.go:155-186` envia JSON 10 Hz para `10.42.0.255:5005` com `cycle_seq` | **DIVERGE** |
| `MODE_CMD` | Broadcast imediato na troca de `mission_mode` | **Não implementado** | `transmitter.go:189-213` envia `MODE_CMD` (`mode`, `timestamp_us`, `cycle_seq`) | **DIVERGE** |
| Captura CSI 20 enlaces | Capturar CSI dos outros 4 nós transmissores no slot TDM | `wifi_csi_rx_cb` (L82+107) filtra `memcmp(info->mac, s_ap_info.bssid, 6)` (**só AP, ignora pares**) | `pipeline.go:313-390` indexa `(tx_node_id, rx_node_id)` em `0..19` via `LinkIndex` | **DIVERGE** |
| Formato `CSI_FRAME` | `JSON + '\n' + 10B LE [tx:1][rx:1][rssi:i16][noise:f32][count:u16] + I/Q int16 LE × 1000` | Envia ASCII `"%.2f"` da amplitude média (`app_main.c:71-72`) | `contracts/udp.go:122-203` decodifica `JSON + '\n' + 10B LE + N*4B int16 LE / 1000.0` (`MaxSubcarriers=64`) | **DIVERGE** |
| `NODE_HELLO` & `HEARTBEAT` | Auto-registro MAC (`esp_read_mac`), `node_id`, `peripherals[]` | **Não implementado** | `receiver.go:175-205, 248-286` trata ambos; `UDPHeader` usa `supported_peripherals`, enquanto payloads usam `peripherals` | **PARCIAL** |
| I2C `PERIPHERAL_DATA` | Auto-discovery `MAX30102` (`0x57`), `BME280` (`0x76/77`), `SCD40` (`0x62`) a 1 Hz | **Não implementado** (zero I2C) | `receiver.go:225-241` aceita `peripherals: [{type, value, unit, timestamp_us}]` | **DIVERGE** |
| Failover $N+1$ | `SUSPECT` 200ms, `LOST` 300ms → recalcula `SlotMap` (20→12→6) | **Não implementado** | `cluster/manager.go:384-434` e `slotmap.go:51-96` prontos e testados | **OK (Central)** |

### 2.2 Central Go (`central/internal/ipc/` + `session/`) ↔ Edge AI (`edge-ai/`)

| Item / Mensagem | Central Go (`ipc/` + `session/` + `contracts/`) | Edge AI (`edge-ai/src/edgespace_ai/ipc/`) | Status |
| :--- | :--- | :--- | :--- |
| Framing TCP `:5006` | `uint32 BE + JSON`, `MaxFrameBytes = 1 MiB` (`contracts/frame.go:11-61`) | `struct.Struct(">I")`, `MAX_FRAME_BYTES = 1 << 20` (`protocol.py:18-19, 321-352`) | **ALINHADO** |
| Envelope `v=1` | `v`, `type`, `ts_us`, `crew_id` (`*string`), `req_id` (`*uint64`), `payload` | `v=1`, `type`, `ts_us`, `crew_id` (`""->None`), `req_id`, `payload` (`protocol.py:233-268`) | **ALINHADO** |
| Filas & Backpressure | `HiPriCap=16`, `LoPriCap=8`, descarta `CSI_WINDOW` > `1s` (`ipc.go:18-29`, `send.go:30-51`) | `hi_pri_cap=64`, `lo_pri_cap=8`, oldest-drop e idade `1000ms` (`server.py:63-93, 299-305`) | **ALINHADO** |
| Timeouts | `CrewAck=2s` (doc `<=300ms`), `Calib=2s`, `Chat=0` (ilimitado! `send.go:75` cita `5s`), `Watchdog=3s` | `CHAT_CORRELATE_REQ` em `create_task` separado (`server.py:314`); `synthesizer.py:23` `DEFAULT_TIMEOUT_S=None` | **DIVERGE** *(chat sem teto)* |
| `CSI_WINDOW` | `cycle_seq_first`, `active_link_mask`, `mode`, `links[]`, `quality_per_link[]` | `CSIWindowPayload` espelha todos os campos (`protocol.py:79-108`) | **ALINHADO** |
| `PERIPHERAL_SNAPSHOT` | `readings[]`, `timestamp_us`, `crew_id=nil` (`pipeline.go:689-698`) | Atualiza `latest_peripherals` + `latest_peripheral_ts_us` (`handlers.py:342-351`) | **ALINHADO** |
| `SET_ACTIVE_CREW` / `CREW_ACK` | Envia `crew_id`, `profile`, `baseline_path`, `thresholds` (`session.go:383-388`) | `baseline_registry.py:264` exige `calibration_status=="READY"`, retornando `baseline_found=False` p/ `SYNTHETIC_SEED` | **DIVERGE** |
| `CALIBRATION_STEP` / `FEEDBACK` | Intercepta `fb.BaselineUpdate` → `SaveBaselineUpdate` (`session.go:693-702`) | Envia `EDGESPACE_DSP64_V1` (`mean`, `std`, `threshold`, `sample_count`, `covered_postures`) (`handlers.py:259`) | **PARCIAL** *(`per_posture_stats` ignorado no Go)* |
| `CHAT_CORRELATE_REQ` / `RESP` | `wiring.go:280-289` envia só `CO2`, `TempC`, `SpO2` (omite umidade, pressão e HR MAX30102) | `handlers.py:192-196` faz merge com `latest_peripherals` (atenua omissão se snapshot prévio existir) | **PARCIAL** |

### 2.3 Central Go (`store/`) + Edge AI ↔ Banco de Dados (`database/` + `knowledge-base/`)

| Tabela / Artefato | Migrations (`0001`..`0006`) | Central Go (`store/`) | Edge AI (`clinical.py`, `clinical_store.py`, `adaptation/`) | Divergência / Fallback |
| :--- | :--- | :--- | :--- | :--- |
| `crew_profiles` & `v_active_crew_baselines` | `0002` seeda `crew_001/002` com `baseline_path` e `crew_003` com `''`; `0004/0006` seedam `SYNTHETIC_SEED` (`sample_count=164`) para os 3 | `reader.go:50`: `READY \|\| SYNTHETIC_SEED` → `crew_003` aparece calibrado no `/api/crew`, mas `wiring.go:84` usa `BaselinePath == ""` | `baseline_registry.py:264`: exige `READY` → retorna `baseline_found=False` para todos; zera `sample_count` (`L271`) | **DIVERGE** (3 regras conflitantes entre REST, Perfil e WS) |
| `individual_baselines` | `0005` adiciona `per_posture_stats_json`, `resting_hr_mean`, `resting_hrv_mean`, `calib_window_*` | `intelligence.go:105` insere só colunas da `0003`, descartando `per_posture_stats_json` | `baseline_registry.py:274` lê `per_posture_stats`, mas `CalibrationEngine` nunca persiste isso no DB | **PARCIAL** |
| `self_exams` | `0003` adiciona `protocol_id`, `payload_json`, `abnormal_flag` | `clinical.go:662-672` busca `protocol_id = exam.ExamType` (`"AMSLER"` ≠ `"amsler_grid"`) e faz `json.Unmarshal` em `exam.Result` (string `"metamorphopsia"` vira `abnormal_flag=0`) | `clinical.py:88-94` faz `json.loads(row['result'])` e ignora silenciosamente resultados string | **DIVERGE** |
| `telemetry_timeseries` & `peripheral_readings` | `0003` adiciona `data_class IN ('REAL','SYNTHETIC','DERIVED')` | `clinical.go:500,538` omite `data_class` (`--mock-cluster` grava como `'REAL'`). `QueryTimeseries` ignora `metric` e usa `COALESCE(...,0)` | `clinical.py:85` lê última linha por `crew_id` | **DIVERGE** |
| `clinical_reports_fts` | `0005` recria FTS5 (`report_id`, `source_id`, `title`, `subsystem`, `content_text`, etc.) | N/A | `clinical_store.py:229-278` usa `PRAGMA table_info` + `bm25()`, filtra `HAZARD` | **ALINHADO** |
| **Fallbacks Ativos** | — | `store/clinical.go:91` `fallbackStore` em RAM (ativo sem `--migrations`); `httpws/ui/` placeholder | `baseline_registry.py:190-238` código morto `_load_from_disk` (`models/profiles/*.json`); `baseline_ae_default.onnx`; `posture_cls.py:78`; `vitals_reg.py:97`; `synthesizer.py:295` | **MAPA ATIVO** |

### 2.4 Central Go (`central/internal/httpws/`) ↔ Frontend (`frontend/`)

| Item / Canal | Central Go (`httpws/`) | Frontend (`frontend/`) | Status |
| :--- | :--- | :--- | :--- |
| WS Server → Client | `TELEMETRY_FRAME`, `ALERT_EVENT`, `CREW_STATE`, `CLUSTER_STATUS`, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`, `ERROR` | `src/lib/model/live.ts` tipa parcialmente; **`src/lib/data/` não existe** (App não compila) | **QUEBRADO** |
| WS Client → Server | `SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP` (`wsclient.go:207-260`) | Sem store/cliente WS; sem UI para `SELF_EXAM`, `CALIBRATION_STEP` ou campos ricos de `CHAT_REPLY` | **QUEBRADO** |
| REST `/api/*` | `/healthz`, `/api/metrics`, `/api/crew*`, `/api/protocols/{id}`, `/api/alerts`, `/api/outbox`, `/api/dev/*` | Nenhum fetch implementado; `vite.config.ts:58` proxy aponta hardcoded para `10.37.51.130:8000` | **QUEBRADO** |
| Política CSP | `server.go:29`: `"default-src 'self'; connect-src 'self'"` | Bloqueia `draco_decoder.wasm` (falta `'wasm-unsafe-eval'`), Worker `Blob:` (`worker-src 'self' blob:`) e `ws://` em Chrome 90 (`connect-src 'self' ws: wss:`) | **INCOMPATÍVEL** |
| Assets 3D & Offline | `server.go:19` embute só `ui/*` (sem rota `/models/`) | `renderer.ts:26-32` carrega `./models/anatomy/*.glb` e `./models/reduced/*.glb`, mas `frontend/data/models/` **não existe** | **QUEBRADO** |

### 2.5 Regras Clínicas & Inteligência de IA

| Regra Clínica | Implementação Atual | Verificação |
| :--- | :--- | :--- |
| **Regra P4 (`confidence <= 0.65` sem `MAX30102`)** | `vitals_reg.py:31-63, 114-121` limita `confidence <= 0.65` se não houver `MAX30102` válido nos últimos `10s` | **ALINHADO** |
| **Personalização por `crew_id`** | `anomaly_scorer.py:39` normaliza por `CrewBaseline`, mas `baseline_ae_<crew_id>.onnx` inexiste em `models/` | **PARCIAL** *(usa `baseline_ae_default.onnx`)* |
| **Extração PT/EN** | `symptom_extractor.py:19-415`: léxico bilíngue (24+ conceitos), normalização NFKD, contexto EVA/radiação | **ALINHADO** |
| **Desambiguação Bayesiana Multi-Turno** | `disambiguator.py` (IG Shannon) + `correlator.py:163-166` grava `ANSWERED_TOPIC`, **mas não aplica** `yes_likelihood`/`no_likelihood` ao posterior no turno seguinte | **PARCIAL** |
| **Contraindicações (ferritina > 500)** | `correlator.py:288-356`: `preflight_ferritin_ug_l` não é mapeado para `ferritin_ug_l`; alergias/meds funcionam por stem; `requires_review_actions` é descartado | **PARCIAL / LACUNA** |
| **SLM Local (`synthesizer.py`)** | `Qwen2.5-1.5B Q4_K_M` (1.1 GB) com fallback determinístico; `slm_auto_download=True` tenta HTTPS no boot se ausente | **PARCIAL** *(risco RAM/offline)* |

---

## Seção 3 — Catálogo Detalhado de Problemas, Bugs e Lacunas

### Severidade CRÍTICO / BLOQUEADOR

- **CRIT-01 — Firmware ESP32-S3 é apenas protótipo Wi-Fi incompatível com Central `:5005`**
  - **Arquivos:** `firmware/main/app_main.c:33-123`, `firmware/sdkconfig:579-583`, `firmware/main/csi_processor.py:1-108`
  - **Hoje vs. Esperado:** Conecta via `example_connect()` ao SSID `"server8874"` (scan todos os canais), filtra `wifi_csi_rx_cb` apenas pelo BSSID do AP (`L82, L107`), envia string ASCII `"%.2f"` para `ip_info.gw.addr:5005`, e ignora I2C (`MAX30102`, `BME280`, `SCD40`), `NODE_HELLO`, `HEARTBEAT`, `CLUSTER_SYNC` e TDM 5×20ms. Deveria fixar canal 6 HT20 + `WIFI_PS_NONE`, sincronizar via `CLUSTER_SYNC`, capturar CSI dos 4 pares TX no TDM, ler I2C 1 Hz e emitir `JSON + '\n' + header 10B LE + I/Q int16 LE × 1000`.
  - **Impacto:** Hardware real 5× ESP32-S3 não se registra no cluster e todos pacotes são descartados como `ErrInvalidUDPDatagram` (`central/internal/udp/receiver.go:158`).

- **CRIT-02 — Frontend não compila, não possui camada de dados nem assets 3D, e `httpws/ui` é placeholder**
  - **Arquivos:** `frontend/src/app/App.tsx:4-5`, `frontend/src/pages/crew/CrewPage.tsx:4-5`, `frontend/src/pages/home/HomePage.tsx:6-7`, `frontend/src/features/chat/ChatDrawer.tsx:2`, `frontend/src/features/twin3d/renderer.ts:26-32`, `frontend/package.json:16-17`, `central/internal/httpws/ui/{index.html,app.js,style.css}`
  - **Hoje vs. Esperado:** Código importa `@/lib/data*`, carrega `./models/{anatomy,reduced}/*.glb` e referencia `tools/check-*.ts`, mas `frontend/src/lib/data/`, `frontend/data/models/`, `frontend/tools/`, `node_modules/` e `dist/` **não existem**. Telas de gráficos, diagnóstico, enciclopédia, perfil, calibração e autoexame são placeholders; `central/internal/httpws/ui/` ainda tem o HTML/JS mínimo de teste.
  - **Impacto:** Impossível compilar ou operar o painel React/Three.js offline contra a Central `:8000`.

- **CRIT-03 — CSP da Central bloqueia Draco WASM, Web Worker Blob e WebSocket em Chrome 90**
  - **Arquivos:** `central/internal/httpws/server.go:29, 250`, `frontend/src/features/twin3d/renderer.ts:35-43`, `frontend/vite.config.ts:76`
  - **Hoje vs. Esperado:** `cspPolicy = "default-src 'self'; connect-src 'self'"`. Deveria incluir `'wasm-unsafe-eval'` em `script-src`, `worker-src 'self' blob:`, `connect-src 'self' ws: wss:`, `img-src 'self' data: blob:` e `style-src 'self' 'unsafe-inline'` (se CSS inline).
  - **Impacto:** Mesmo após build do frontend, o navegador bloqueia `draco_decoder.wasm`, o Worker Blob do `DRACOLoader` e o handshake `ws://` em tablets com WebView/Chrome 90.

- **CRIT-04 — `contracts/`, `tools/` e `deploy/` contêm apenas READMEs (zero schemas, validador ou deploy ARM64)**
  - **Arquivos:** `contracts/{enums,jsonschema,fixtures}/README.md`, `tools/README.md`, `deploy/README.md`, `Makefile:52-54`
  - **Hoje vs. Esperado:** Não há JSON Schemas, fixtures compartilhadas, `tools/validate_contracts.py`, nem arquivos `hostapd`/`dnsmasq`/`nftables`/`systemd`.
  - **Impacto:** Sem validação automatizada de contrato entre Go/Python/TS/C e sem isolamento offline da Orange Pi 4 Pro.

- **CRIT-05 — Conflito de status `SYNTHETIC_SEED` vs `READY` e código morto em `BaselineRegistry`**
  - **Arquivos:** `edge-ai/src/edgespace_ai/adaptation/baseline_registry.py:173-238, 264, 271`, `central/internal/store/reader.go:50`, `central/cmd/edgespace-central/wiring.go:84`, `database/migrations/0004_intelligence_seeds.sql`
  - **Hoje vs. Esperado:** `set_active_crew` retorna na L189 deixando L190-238 inalcançáveis; L264 aceita apenas `calibration_status == "READY"` e L271 zera `sample_count` para `SYNTHETIC_SEED`. Enquanto isso `reader.go:50` aceita `READY || SYNTHETIC_SEED` e `wiring.go:84` verifica `BaselinePath == ""`.
  - **Impacto:** `GET /api/crew` diz `calibration_required=false` para `crew_001/002/003`, `GET /api/crew/crew_003/profile` diz `true`, e `CREW_STATE` via WS (após `CREW_ACK`) diz `calibration_required=true` para todos.

### Severidade ALTO

- **HIGH-01 — `self_exams` incompatível entre `sim`/UI/Central e `edge-ai/clinical.py`**
  - **Arquivos:** `central/internal/store/clinical.go:656-673`, `central/internal/sim/scenarios.go:115-120`, `central/internal/pipeline/thresholds.go:167-202`, `edge-ai/src/edgespace_ai/clinical.py:88-94`
  - **Hoje vs. Esperado:** `SaveSelfExam` busca `protocol_id` igual a `exam.ExamType` (`"AMSLER"` ≠ `"amsler_grid"` → grava `NULL`) e espera `exam.Result` em JSON (`{"abnormal_flag": true}`), enquanto `sim` e `thresholds.go` usam strings (`"metamorphopsia"`, `"red"`). `clinical.py:89` também faz `json.loads(row['result'])` e descarta silenciosamente strings.
  - **Impacto:** `self_exams.abnormal_flag` fica sempre `0` e o motor causal não enxerga autoexames alterados gravados no SQLite.

- **HIGH-02 — `run_stack.ps1` não executa `operational.py migrate` antes de subir o worker `edge-ai`**
  - **Arquivos:** `scripts/run_stack.ps1:237-252` vs `scripts/run_stack.sh:210`, `edge-ai/src/edgespace_ai/correlation/causal_graph.py:126-127`
  - **Hoje vs. Esperado:** Em Windows sem `var/edgespace.db` prévio, `edge-ai` inicia antes da Central Go e aborta com `FileNotFoundError` ao abrir o SQLite `mode=ro`.
  - **Impacto:** Falha de boot em instalação limpa no Windows.

- **HIGH-03 — `slm_auto_download=True` e `pip install` em runtime violam regra 100% offline**
  - **Arquivos:** `edge-ai/src/edgespace_ai/utils/config.py:29-32`, `edge-ai/src/edgespace_ai/ipc/handlers.py:118`, `scripts/run_stack.ps1:186-200`, `scripts/run_stack.sh:184-194`
  - **Hoje vs. Esperado:** Sem `--disable-slm` / `-NoSlm`, se GGUF ou `llama_cpp` faltarem, scripts e worker tentam baixar de Hugging Face / GitHub Pages em runtime. Deveria bloquear rede por padrão em produção e exigir pré-instalação offline.
  - **Impacto:** Viola requisito zero-internet; bloqueia boot por timeout TCP quando sem WAN.

- **HIGH-04 — Orçamento de RAM `< 400 MB` estourado pelo SLM no mesmo processo + `ChatTimeout=0`**
  - **Arquivos:** `edge-ai/models/slm/qwen2.5-1.5b-instruct-q4_k_m.gguf` (1.117 GB), `edge-ai/src/edgespace_ai/correlation/synthesizer.py:19, 23, 222-231`, `central/internal/session/types.go:21`, `central/internal/ipc/ipc.go:22`, `central/internal/httpws/wsclient.go:200`
  - **Hoje vs. Esperado:** GGUF 1.1 GB (`n_ctx=2048`) é mapeado no mesmo processo Python de `onnxruntime`, e todos os timeouts de chat (`Go IPC`, `Session`, `WS`, `SLM`) são infinitos (`0`/`None`). Deveria ter teto configurável (ex.: 15–30s para SLM ou `<= 5s` em fallback) e isolamento/controle rigoroso de memória em ARM64.
  - **Impacto:** Pressão de RAM / OOM killer na Orange Pi 4 Pro e goroutines/chamadas WS presas indefinidamente.

- **HIGH-05 — Duplo motor causal (`CausalGraph` vs `assess_fixture`) + contradição ferritina > 500 e multi-turno incompleto**
  - **Arquivos:** `edge-ai/src/edgespace_ai/correlation/correlator.py:163-166, 173-180, 307-331`, `edge-ai/src/edgespace_ai/clinical.py:182-229`
  - **Hoje vs. Esperado:** `correlator.py` usa `CausalGraph` para `text`/`differentials`/`escalation`, mas `assess_fixture` para `matched_condition_ids`/`max_severity`/`blocked_actions`; não mapeia `preflight_ferritin_ug_l` para `ferritin_ug_l` (nem lê `requires_review_actions`), e não injeta `yes_likelihood`/`no_likelihood` ao responder pergunta de desambiguação no turno seguinte.
  - **Impacto:** Diferenciais e severidade podem divergir entre campos da mesma resposta; bloqueio `SUPPLEMENT_IRON` não dispara sem `self_exam` JSON prévio.

- **HIGH-06 — `QueryTimeseries` ignora `metric` e converte `NULL` em `0.0`; `HandleChatMsg` omite sensores**
  - **Arquivos:** `central/internal/store/clinical.go:974-1020`, `central/internal/httpws/handlers.go:108`, `central/cmd/edgespace-central/wiring.go:280-289`
  - **Hoje vs. Esperado:** `QueryTimeseries` ignora parâmetro `metric` e aplica `COALESCE(AVG(...), 0)` (transformando sensor ausente em `0.0`); `HandleChatMsg` monta `LastPeripherals` com apenas `CO2`, `TempC` e `SpO2`, omitindo umidade (`%RH`), pressão (`hPa`) e FC do `MAX30102`.
  - **Impacto:** Gráficos confundem ausência de sensor com leitura zero; correlação causal recebe snapshot incompleto se `PERIPHERAL_SNAPSHOT` ainda não chegou.

- **HIGH-07 — Override de FC para `MODE_COUNTERMEASURE_EXERCISE` nunca ativa em tripulantes do seed**
  - **Arquivos:** `central/internal/pipeline/thresholds.go:239`, `database/migrations/0002_operational_seeds.sql:25-39`
  - **Hoje vs. Esperado:** `thresholds.go:239` só eleva `YellowHigh=165 / RedHigh=185` se `view.Thresholds["heart_rate_bpm"].MetricName == ""`, porém o seed preenche `metric_name: "heart_rate_bpm"` com `110/140`.
  - **Impacto:** Falsos alertas YELLOW/RED durante exercício resistivo/aeróbico normal.

### Severidade MÉDIO

- **MED-01 — `DecodeCSIBinary(csiPayload, nil)` aloca slice no hot path UDP; divergência `peripherals` vs `supported_peripherals`**
  - **Arquivos:** `central/internal/udp/receiver.go:186, 202, 207, 248-286`, `central/internal/contracts/types.go:72-73`
  - **Hoje vs. Esperado:** Passar `nil` aloca `[]IQSample` ~200×/s em vez de reutilizar buffer; `UDPHeader` exige `supported_peripherals` enquanto `NODE_HELLO`/`HEARTBEAT` enviam `peripherals`.
- **MED-02 — `SaveBaselineUpdate` não grava `per_posture_stats_json` nem metadados da migration `0005`; `CalibrationEngine` não salva JSON**
  - **Arquivos:** `central/internal/store/intelligence.go:61-111`, `edge-ai/src/edgespace_ai/adaptation/calibration_engine.py:66, 125`
  - **Hoje vs. Esperado:** Campos `per_posture_stats`, `resting_hr_mean`, `resting_hrv_mean` e `calib_window_*` adicionados na `0005` ficam sempre padrão/NULL após calibração via IPC.
- **MED-03 — `SaveTelemetry1Hz` / `SavePeripheral1Hz` gravam dados simulados como `data_class='REAL'`**
  - **Arquivos:** `central/internal/store/clinical.go:500, 538`, `central/cmd/edgespace-central/wiring.go:217-240`
  - **Hoje vs. Esperado:** Sem flag `data_class='SYNTHETIC'` no modo `--mock-cluster`, dados de teste poluem rollups históricos de voo.
- **MED-04 — `Makefile` e `main.go` têm alvos e defaults desalinhados**
  - **Arquivos:** `Makefile:30, 104, 121`, `central/cmd/edgespace-central/main.go:203-214, 346`
  - **Hoje vs. Esperado:** `Makefile:104` usa `npm ci --offline` em repo `pnpm` (`pnpm-lock.yaml`); `Makefile:121` aponta `./wheels` inexistente; `main.go:203` só aguarda IPC no boot se `--mock-ai`; default `--migrations` (`../database/migrations`) quebra se rodado da raiz.

### Severidade BAIXO

- **LOW-01 — Documentação desatualizada (`README.md`, `contracts/enums`, `firmware/README copy.md`)**
  - **Arquivos:** `README.md:54-56`, `contracts/enums/README.md:16`, `edge-ai/src/edgespace_ai/ipc/send.go:75` (comentário `5s` vs `0`), `firmware/README copy.md` (cópia duplicada/ruído).
- **LOW-02 — Ausência de `baseline_ae_<crew_id>.onnx` gerados e artefatos residuais em `var/` / `central/tmp/`**
  - **Arquivos:** `edge-ai/models/`, `central/tmp/qa_space.db-{shm,wal}`.

---

## Seção 4 — Oportunidades de Melhoria Técnica e Inteligência

*(Respeitando orçamento ARM64 da Orange Pi 4 Pro: `< 400 MB` RAM para ONNX/DSP, latência `< 50 ms`, 100% offline).*

### 4.1 Modelos ONNX & DSP 1-Antena (`edge-ai/dsp/`, `inference/`, `training/`)
1. **Janela Deslizante Vetorizada + Cache de FFT:** Em `csi_processor.py` e `feature_extractor.py`, pré-alocar coeficientes Butterworth SOS (`signal.butter`) uma única vez no `__init__` em vez de recalcular a cada janela 2 Hz; usar `rfft` sobre os últimos 100 ciclos (10 s) reutilizando buffers NumPy para manter DSP + ONNX bem abaixo de `15 ms` em ARM64.
2. **Estimação Cardíaca/HRV mais Robusta para 1-Antena:** O `resample`/interpolação parabólica atual em `_estimate_hrv_proxies` (`feature_extractor.py:377`) opera sobre `fs=10 Hz` (resolução Nyquist 5 Hz, 100 ms/amostra). Aplicar interpolação cúbica `4×` (`40 Hz`) apenas no sinal cardíaco `0.8–2.5 Hz` melhora detecção de picos R-R proxy e reduz erro de RMSSD sem custo perceptível de CPU.
3. **Treino de Autoencoders Leves por Tripulante (`baseline_ae_<crew_id>.onnx`):** Manter MLP AE `(64->32->16->32->64)` float32 (~22 KB por arquivo) com `intra_op_num_threads=2`; exportar `baseline_ae_crew_001.onnx` e `crew_002.onnx` no `training/` para validar hot-swap real de arquivo `.onnx` (não apenas troca de vetor `mean/std`).
4. **Calibração por Postura Persistida:** Propagar `per_posture_stats_json`, `resting_hr_mean` e `resting_hrv_mean` via `CalibrationFeedbackPayload` para o SQLite, permitindo normalização específica (`CrewBaseline.normalize_vital`) quando o astronauta estiver sentado vs em exercício vs supino.

### 4.2 Inteligência do Chatbot, Memória Clínica & SLM Local (`edge-ai/correlation/`)
1. **Unificar Motor Causal (`CausalGraph` + `ClinicalRepository.assess_fixture`):** Fundir o score determinístico de `assess_fixture` (regras objetivas `ROLLUP_*`, `DELTA_*`, `CONTEXT_WINDOW`, `match_policy`) com a ponderação Bayesiana de sintomas de `CausalGraph`, garantindo que `differentials`, `matched_condition_ids`, `max_severity` e `blocked_actions` nunca se contradigam.
2. **Atualização Bayesiana Multi-Turno Real:** Quando `ANSWERED_TOPIC` for registrado (`sim`/`não` à pergunta de desambiguação `last_question_id`), multiplicar efetivamente `yes_likelihood`/`no_likelihood` nas condições-alvo na avaliação do turno seguinte (fechando o loop da Seção 4.2 do Plano Mestre).
3. **Mapeamento Completo de Contraindicações & Alerta de Revisão:** Mapear `preflight_ferritin_ug_l` → `ferritin_ug_l` apenas como fallback quando não houver dosagem recente, filtrar contraindicações relevantes às condições no top-3 (em vez de varrer todas as 26 indistintamente) e expor `requires_review_actions` no `ChatCorrelateRespPayload` quando o guardião for `None`.
4. **Controle Estrito de RAM e Latência do SLM na Orange Pi:** Manter ONNX/DSP em processo dedicado (`< 400 MB` RSS garantidos) e isolar o SLM `llama-cpp-python` (ou limitar `n_ctx=1024`, `n_threads=4` em Cortex-A72/A55, `timeout_s=12.0` + `slm_auto_download=False` default) para nunca causar OOM no pipeline de telemetria em tempo real nem pendurar requisições WS.
5. **Busca Híbrida FTS5 + Sinônimos Clínicos Bilíngues:** Expandir `_CONCEPT_SEARCH_EXPANSIONS` em `clinical_store.py:321` para todos os 24+ conceitos de `SYMPTOM_LEXICON` (hoje cobre apenas 7 conceitos de MSK/GI), melhorando recall do BM25 em PT/EN sem precisar de modelo de embeddings externo.

### 4.3 Resiliência Operacional, Failover $N+1$ & Scripts (`central/`, `firmware/`, `deploy/`)
1. **Buffer Reutilizável no UDP Receiver:** Reutilizar slice pré-alocado no loop de `udp.Receiver.Run` ao chamar `DecodeCSIBinary` (cópia apenas quando `TrySendData` for aceito no canal), eliminando ~200 alocações/s no hot path.
2. **Failover $N+1$ Coordenado com TDM Real:** No firmware ESP32-S3, derivar `my_slot_id` dinamicamente de `CLUSTER_SYNC.slots[]` em cada ciclo (não fixar slot por ID), recalculando janela de guarda (`>= 1.5 ms`) para suportar transição suave 5→4→3 nós (`20→12→6` enlaces) em `< 500 ms`.
3. **Separação Estrita `REAL` vs `SYNTHETIC` no SQLite:** Propagar `data_class` de `main.go` (`--mock-cluster` ≠ `false` → `'SYNTHETIC'`) até `store/clinical.go` para impedir que simulações contaminem rollups reais de missão.
4. **Higiene de Boot e Offline-First:** Garantir `operational.py migrate` também no `run_stack.ps1`, usar `pnpm install --offline` no `Makefile`, vendoring de `edge-ai/wheels/` ARM64/x86 e `deploy/` completo (`hostapd` ch 6 HT20 + `nftables` bloqueando WAN).

---

## Seção 5 — Plano de Ação Priorizado (Roadmap de Execução)

### Onda 1 — Contratos SSOT, Alinhamento de Banco/Adaptação e Segurança Offline
*(Objetivo: eliminar divergências de contrato entre Go, Python e SQLite antes de tocar em UI e Firmware).*

1. **T1.1 — Restaurar `contracts/` e `tools/` (`Leonardo/M4`):**
   - **Arquivos:** `contracts/enums/*.json`, `contracts/jsonschema/{udp,ipc,ws,rest}/*.json`, `contracts/fixtures/{udp,ipc,ws,rest}/*.json`, `tools/validate_contracts.py`
   - **Especificação:** Materializar schemas draft 2020-12 espelhando `central/internal/contracts/` e `edge-ai/src/edgespace_ai/ipc/protocol.py`, incluindo `ERROR` (P4), `cycle_seq` (P1), `req_id` (P3) e formato híbrido UDP (P6); criar validador Python offline.
   - **Critério de aceite:** `make contracts-validate` retorna exit 0 com 100% das fixtures válidas/inválidas verificadas.

2. **T1.2 — Corrigir `BaselineRegistry`, `CalibrationEngine` e Status `SYNTHETIC_SEED` (`Santiago+Leonardo/M5` + `M4`):**
   - **Arquivos:** `edge-ai/src/edgespace_ai/adaptation/baseline_registry.py`, `edge-ai/src/edgespace_ai/adaptation/calibration_engine.py`, `central/internal/store/reader.go`, `central/internal/store/intelligence.go`, `central/cmd/edgespace-central/wiring.go`
   - **Especificação:** Remover código morto L190–238 em `baseline_registry.py`; alinhar regra única (`crew_001/002` calibrados via `SYNTHETIC_SEED` + `baseline_path`, `crew_003` pendente de calibração); preservar `sample_count`; persistir `per_posture_stats_json` em `SaveBaselineUpdate` e JSON em `models/profiles/` se aplicável.
   - **Critério de aceite:** `pytest` + `go test ./internal/store ./internal/session` passam; `GET /api/crew`, `GET /api/crew/{id}/profile` e WS `CREW_STATE` reportam exatamente o mesmo `calibration_required`.

3. **T1.3 — Corrigir `self_exams`, `QueryTimeseries`, `data_class` e `HandleChatMsg` (`Leonardo/M4` + `M1`/`M5`):**
   - **Arquivos:** `central/internal/store/clinical.go`, `central/cmd/edgespace-central/wiring.go`, `central/internal/pipeline/thresholds.go`, `edge-ai/src/edgespace_ai/clinical.py`
   - **Especificação:** Normalizar mapeamento `ExamType -> protocol_id` e flag `abnormal_flag` para strings e JSON em `SaveSelfExam` e `clinical.py`; respeitar `metric` e preservar `NULL` em `QueryTimeseries`; propagar `data_class='SYNTHETIC'` em simulação; corrigir `thresholds.go:239` em `MODE_COUNTERMEASURE_EXERCISE`; enviar todos os periféricos em `HandleChatMsg`.
   - **Critério de aceite:** `go test ./internal/store ./internal/pipeline ./cmd/edgespace-central` + `operational.py validate` passam sem regressão.

4. **T1.4 — Corrigir Boot Offline, Timeouts e `run_stack.ps1` (`Leonardo/M4` + `M5`):**
   - **Arquivos:** `edge-ai/src/edgespace_ai/utils/config.py`, `edge-ai/src/edgespace_ai/correlation/synthesizer.py`, `central/internal/session/types.go`, `central/internal/ipc/ipc.go`, `scripts/run_stack.ps1`, `scripts/run_stack.sh`, `Makefile`
   - **Especificação:** Mudar `slm_auto_download` default para `False`; definir timeout explícito de SLM/Chat (`15s` com degradação determinística) e `n_ctx=1024`; rodar `operational.py migrate` em `run_stack.ps1` antes do worker; trocar `npm ci` por `pnpm install --offline` no `Makefile`.
   - **Critério de aceite:** `powershell -File scripts/run_stack.ps1 -NoSlm -SmokeSeconds 5` e `./scripts/run_stack.sh --no-slm --smoke-seconds 5` sobem de `var/` limpo com `ai_ready=true`.

### Onda 2 — Unificação do Motor Causal & Inteligência Clínica (`edge-ai/`)
*(Objetivo: eliminar divergência entre `CausalGraph` e `assess_fixture` e garantir desambiguação multi-turno + contramedidas).*

5. **T2.1 — Unificar Score Causal + Contraindicações + Multi-Turno (`Santiago+Leonardo/M5` + `Selliny/M1`):**
   - **Arquivos:** `edge-ai/src/edgespace_ai/correlation/{correlator.py,causal_graph.py,clinical_store.py}`, `edge-ai/src/edgespace_ai/clinical.py`
   - **Especificação:** Integrar `assess_fixture` dentro do ranking do `CausalGraph`; aplicar `yes_likelihood`/`no_likelihood` no turno seguinte após `ANSWERED_TOPIC`; mapear `preflight_ferritin_ug_l` → `ferritin_ug_l` (fallback) e filtrar contraindicações relevantes; expandir `_CONCEPT_SEARCH_EXPANSIONS` em `clinical_store.py` para os 24+ conceitos.
   - **Critério de aceite:** `pytest tests/` passa 100% (multi-turno + ferritina > 500 + 36 golden cases).

6. **T2.2 — Otimização DSP + ONNX por Tripulante (`Santiago+Leonardo/M5`):**
   - **Arquivos:** `edge-ai/src/edgespace_ai/dsp/feature_extractor.py`, `edge-ai/training/build_all_models.py`
   - **Especificação:** Pré-computar filtros SOS no `__init__`, aplicar interpolação `4×` na banda cardíaca para HRV proxy e gerar `baseline_ae_crew_001.onnx` / `baseline_ae_crew_002.onnx`.
   - **Critério de aceite:** Benchmark mostra `< 50 ms`/janela e RSS ONNX/DSP `< 400 MB` (`test_edge_ai.py` + `e2e_central_integration.py`).

### Onda 3 — Frontend Offline Completo + CSP da Central (`frontend/` + `central/internal/httpws/`)
*(Objetivo: fazer o painel compilar, renderizar Digital Twin 3D com Draco, gráficos, tutoriais e Chatbot clínico).*

7. **T3.1 — Atualizar CSP + Servir Modelos 3D na Central (`Leonardo/M4`):**
   - **Arquivos:** `central/internal/httpws/server.go`, `central/internal/httpws/handlers.go`, `central/internal/httpws/httpws_test.go`
   - **Especificação:** Atualizar `cspPolicy` para `"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss:"`. Garantir que `models/` copiado para `central/internal/httpws/ui/models/` sirva `.glb` com `model/gltf-binary`.
   - **Critério de aceite:** `go test ./internal/httpws` passa verificando headers CSP + MIME `.wasm` e `.glb`.

8. **T3.2 — Implementar `frontend/src/lib/data/*`, Assets 3D e `tools/` (`Rafael/M3`):**
   - **Arquivos:** `frontend/src/lib/data/{index,ws,rest,session,crewState,telemetry,cluster,chat}.ts`, `frontend/data/models/**`, `frontend/tools/{check-offline,check-size}.ts`
   - **Especificação:** Implementar cliente WS `/ws` com reconexão exponencial + envelope `v=1`; lojas Zustand para `CREW_STATE`, `TELEMETRY_FRAME`, `ALERT_EVENT`, `CLUSTER_STATUS`, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`; clientes REST `/api/crew*`, `/api/crew/{id}/timeseries`, `/api/protocols/{id}`, `/api/alerts`; disponibilizar GLBs `< 3 MB` e remover proxy hardcoded `10.37.51.130` em favor de `localhost:8000` / env.
   - **Critério de aceite:** `pnpm run typecheck && pnpm run build && pnpm run check:offline && pnpm run check:size` passam sem requests externos.

9. **T3.3 — Completar Telas & Chatbot Rico + Embed em `httpws/ui/` (`Rafael/M3` + `M4`):**
   - **Arquivos:** `frontend/src/features/chat/ChatDrawer.tsx`, `frontend/src/pages/{charts,diagnosis,encyclopedia,profile}/*`, `frontend/src/features/twin3d/TwinCanvas.tsx`, `central/internal/httpws/ui/*`
   - **Especificação:** Renderizar `differentials`, `evidence`, `countermeasures`, `source_ids`, `escalation`, `disambiguation_question`, `actions` e `disclaimer` no `ChatDrawer`; colorir os 6 subsistemas no Digital Twin conforme `TELEMETRY_FRAME.subsystems`; implementar wizard de `CALIBRATION_STEP` e fluxo `SELF_EXAM` (Grade de Amsler + protocolos); copiar `dist/` para `central/internal/httpws/ui/`.
   - **Critério de aceite:** `go build ./cmd/edgespace-central` embute UI completa; DevTools Network mostra zero requisições externas em `http://127.0.0.1:8000`.

### Onda 4 — Firmware Cluster 5× ESP32-S3 Real (`firmware/` + `central/internal/udp/`)
*(Objetivo: substituir o protótipo `app_main.c` pelo firmware TDM multi-estático + I2C compatível com `:5005`).*

10. **T4.1 — Otimizar `udp.Receiver` e Alinhar Campo `peripherals` (`Leonardo/M4`):**
    - **Arquivos:** `central/internal/udp/receiver.go`, `central/internal/contracts/{types,udp}.go`
    - **Especificação:** Reutilizar buffer `[]IQSample` no loop de leitura UDP antes da cópia para `DataMsg`; unificar `peripherals` vs `supported_peripherals`.
    - **Critério de aceite:** `go test -bench . ./internal/udp` mostra redução de alocações no hot path.

11. **T4.2 — Implementar Firmware Único ESP-IDF v5.x (`Nicolas/M2`):**
    - **Arquivos:** `firmware/main/{app_main.c,tdm_sync.c,csi_capture.c,i2c_sensors.c,udp_transport.c}`, `firmware/partitions.csv`, `firmware/sdkconfig.defaults` (remover `firmware/main/csi_processor.py` e `firmware/README copy.md`)
    - **Especificação:** Configurar Wi-Fi STA fixo no AP Orange Pi canal 6 HT20 + `WIFI_PS_NONE`; Core 0 gerencia UDP `:5005` (`NODE_HELLO`, `HEARTBEAT`, RX `CLUSTER_SYNC`/`MODE_CMD`), slot timer TDM (`esp_timer`) e callback `wifi_csi_rx_cb` sem `malloc` capturando MACs dos outros nós; Core 1 empacota `JSON + '\n' + 10B LE + I/Q int16 LE * 1000` e realiza auto-discovery I2C (`MAX30102` `0x57`, `BME280` `0x76/77`, `SCD40` `0x62`) emitindo `PERIPHERAL_DATA` a 1 Hz.
    - **Critério de aceite:** `idf.py set-target esp32s3 build` compila sem erros; 5 placas convergem para 20 enlaces em `< 1 s`, jitter `< 1.5 ms`, failover 4 nós (12 enlaces) sem reboot.

### Onda 5 — Deploy Orange Pi 4 Pro ARM64 e Ensaio E2E Offline (`deploy/`)
*(Objetivo: empacotar operação 100% isolada na Orange Pi 4 Pro com `systemd` + AP + firewall).*

12. **T5.1 — Criar Artefatos `deploy/` ARM64 (`Leonardo/M4`):**
    - **Arquivos:** `deploy/hostapd/hostapd-24g.conf`, `deploy/dnsmasq/edgespace.conf`, `deploy/nftables/edgespace.nft`, `deploy/systemd/{edgespace-ai.service,edgespace-central.service}`, `deploy/install.sh`
    - **Especificação:** AP 2.4 GHz canal 6 HT20 (`10.42.0.1`), DHCP estático para 5 ESP32 + tablet sem DNS upstream, firewall bloqueando WAN e liberando `:5005/udp` + `:8000/tcp` na LAN (`:5006` só loopback), units `systemd` com `MemoryMax=400M` (ONNX/DSP) e `200M` (Central).
    - **Critério de aceite:** `GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build` + `run_stack.sh --real-cluster --smoke-seconds 10` e `python edge-ai/tests/e2e_central_integration.py` passam ponta a ponta.

---

## Seção 6 — Prompts Prontos para Execução por Fase

### Fase 1 — Contratos SSOT, Banco/Adaptação, Scripts e Segurança Offline (Onda 1)
```text
Execute a Onda 1 (T1.1 a T1.4) de docs/FULL-SYSTEM-AUDIT-AND-PLAN.md:
1. Crie contracts/enums/*.json, contracts/jsonschema/{udp,ipc,ws,rest}/*.json, contracts/fixtures/ e tools/validate_contracts.py espelhando central/internal/contracts/ e edge-ai/src/edgespace_ai/ipc/protocol.py.
2. Em edge-ai/src/edgespace_ai/adaptation/baseline_registry.py, remova o código morto (L190-238), alinhe SYNTHETIC_SEED com central/internal/store/reader.go e central/cmd/edgespace-central/wiring.go, e persista per_posture_stats_json em store/intelligence.go.
3. Corrija SaveSelfExam/clinical.py (protocol_id + abnormal_flag string/JSON), QueryTimeseries (filtrar metric e preservar NULL), data_class='SYNTHETIC' em simulação, thresholds.go:239 em MODE_COUNTERMEASURE_EXERCISE e wiring.go:280-289 (todos periféricos).
4. Desative slm_auto_download por padrão (config.py), defina timeout explícito de chat/SLM (15s com fallback), adicione operational.py migrate em scripts/run_stack.ps1 e ajuste Makefile (pnpm --offline).
Valide com: make contracts-validate, go test ./..., pytest e operational.py validate.
```

### Fase 2 — Motor Causal Unificado, DSP 1-Antena & ONNX por Tripulante (Onda 2)
```text
Execute a Onda 2 (T2.1 e T2.2) de docs/FULL-SYSTEM-AUDIT-AND-PLAN.md:
1. Unifique CausalGraph e ClinicalRepository.assess_fixture em edge-ai/src/edgespace_ai/correlation/correlator.py para não haver divergência entre differentials e matched_condition_ids/blocked_actions.
2. Aplique yes_likelihood/no_likelihood no turno seguinte quando ANSWERED_TOPIC for respondido; mapeie preflight_ferritin_ug_l -> ferritin_ug_l (fallback) para contraindicação ferritina > 500; exponha requires_review_actions; expanda _CONCEPT_SEARCH_EXPANSIONS em clinical_store.py para todos os conceitos de symptom_extractor.py.
3. Pré-calcule filtros Butterworth SOS no FeatureExtractor, aplique interpolação 4x na banda cardíaca e gere baseline_ae_crew_001.onnx / baseline_ae_crew_002.onnx via training/build_all_models.py.
Valide com: pytest e python edge-ai/tests/e2e_central_integration.py (verificando < 50ms e RAM ONNX/DSP < 400 MB).
```

### Fase 3 — CSP Central + Frontend Offline 3D + Chatbot Rico (Onda 3)
```text
Execute a Onda 3 (T3.1 a T3.3) de docs/FULL-SYSTEM-AUDIT-AND-PLAN.md:
1. Atualize cspPolicy em central/internal/httpws/server.go para liberar 'wasm-unsafe-eval', worker-src 'self' blob:, connect-src 'self' ws: wss:, style-src 'self' 'unsafe-inline' e img-src 'self' data: blob:; garanta que ./models/*.glb seja servido offline.
2. Implemente frontend/src/lib/data/{index,ws,rest,session,crewState,telemetry,cluster,chat}.ts, adicione frontend/tools/check-{offline,size}.ts e os GLBs em frontend/data/models/ (< 3 MB).
3. Atualize ChatDrawer.tsx (differentials, evidence, countermeasures, source_ids, escalation, disambiguation_question, actions, disclaimer), conecte os 6 subsistemas ao TwinCanvas e implemente telas /charts, /diagnosis, /encyclopedia, /profile, SELF_EXAM e CALIBRATION_STEP.
4. Gere dist/ e copie para central/internal/httpws/ui/.
Valide com: pnpm run typecheck && pnpm run build && pnpm run check:offline, depois go test ./internal/httpws e make central-run-mock.
```

### Fase 4 — Firmware TDM 5× ESP32-S3 + Otimização UDP Zero-Alloc (Onda 4)
```text
Execute a Onda 4 (T4.1 e T4.2) de docs/FULL-SYSTEM-AUDIT-AND-PLAN.md:
1. Em central/internal/udp/receiver.go, reutilize buffer []IQSample no DecodeCSIBinary e alinhe peripherals vs supported_peripherals.
2. Substitua o protótipo firmware/main/app_main.c por firmware único ESP-IDF v5.x (esp32s3) com: Wi-Fi ch 6 HT20 + WIFI_PS_NONE, registro NODE_HELLO/HEARTBEAT por MAC, recepção de CLUSTER_SYNC/MODE_CMD na porta :5005, TDM 5x20ms sem malloc em wifi_csi_rx_cb capturando todos os pares TX, payload híbrido JSON+'\n'+10B LE+I/Q int16 LE*1000 e auto-discovery I2C (MAX30102 0x57, BME280 0x76/0x77, SCD40 0x62) enviando PERIPHERAL_DATA 1 Hz. Remova firmware/main/csi_processor.py e adicione partitions.csv.
Valide com: go test -bench . ./internal/udp e idf.py set-target esp32s3 build.
```

### Fase 5 — Deploy ARM64 Orange Pi 4 Pro & Ensaio E2E Offline (Onda 5)
```text
Execute a Onda 5 (T5.1) de docs/FULL-SYSTEM-AUDIT-AND-PLAN.md:
Crie os arquivos em deploy/ (hostapd ch 6 HT20 em 10.42.0.1, dnsmasq sem upstream DNS, nftables bloqueando WAN e isolando :5006 em loopback, systemd edgespace-ai.service + edgespace-central.service com limites de memória e install.sh idempotente).
Valide com: GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build ./cmd/edgespace-central e teste completo com ./scripts/run_stack.sh --smoke-seconds 10.
```