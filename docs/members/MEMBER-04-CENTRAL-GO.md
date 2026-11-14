# Membro 4 (Leonardo — Integrador) — Arquitetura da Central em Go

**Pastas exclusivas:** `central/`, `tools/`, `deploy/`. Guardião de `contracts/`.
**Hub único** entre Nicolas/M2 (cluster ESP32-S3), Rafael/M3 (UI/Chatbot), Selliny/M1 (schema SQLite), Santiago/Leonardo/M5 (Edge AI).
**Status:** especificação arquitetural de referência. A Central já possui implementação em `central/`; os blocos abaixo descrevem o desenho e os critérios previstos, cuja cobertura deve ser conferida no código e nos testes.

---

## 0. Restrições de Projeto

| Item | Valor fixo |
| :--- | :--- |
| Alvo | Orange Pi 4 Pro, `linux/arm64`, binário estático `CGO_ENABLED=0` |
| Portas | UDP `:5005` (cluster LAN), TCP `127.0.0.1:5006` (IPC IA, só loopback), HTTP/WS `:8000` (LAN) |
| Persistência | SQLite `WAL + FTS5`, driver Go puro, **escritor único** (`store/`) |
| Rede | Zero saída WAN. Zero CDN. Dependências Go vendorizadas (`go mod vendor`) |
| Orçamento | RAM `< 150 MB`, CPU `< 25%` de 1 núcleo (5 nós a 10 Hz), failover `< 500 ms` |
| Fonte da verdade | `contracts/` (enums, jsonschema, fixtures). Proibido campo fora do contrato |

### 0.1 Decisões de Dependência (a registrar como ADR antes do código)

| Necessidade | Candidato (Go puro) | Motivo |
| :--- | :--- | :--- |
| SQLite | `modernc.org/sqlite` | Sem CGO, suporta WAL + FTS5 |
| WebSocket | `github.com/coder/websocket` (ou `gorilla/websocket`) | Go puro, context-aware |
| Logs | `log/slog` (stdlib) | Zero dep, JSON estruturado |
| Métricas | `expvar` (stdlib) ou contadores atômicos em `/api/metrics` | Sem Prometheus externo |
| Embed UI | `embed` (stdlib) | `frontend/dist` dentro do binário |

Regra: stdlib primeiro. Toda dep nova exige ADR em `docs/` + vendor.

---

## 1. Arquitetura de Pacotes (`central/internal/`)

```text
central/
├── cmd/edgespace-central/   # main: flags, wiring, ordem de start/stop, sinais
└── internal/
    ├── contracts/  # tipos Go 1:1 com contracts/ (enums, envelopes, payloads)
    ├── udp/        # transporte :5005 (rx decode, tx CLUSTER_SYNC/MODE_CMD)
    ├── cluster/    # registry MAC→node_id, FSM por nó, slot map, failover N+1
    ├── pipeline/   # ring buffers 20 enlaces, montagem de ciclo TDM, agregação I2C, avaliação de limiares
    ├── session/    # crew_id ativo, modo de missão, calibração, contexto de chat
    ├── ipc/        # cliente TCP :5006, framing uint32 BE + JSON, filas de prioridade
    ├── store/      # escritor único SQLite (batch 250 ms), pool read-only, outbox
    ├── sim/        # --mock-cluster (nós virtuais + cenários) e --mock-ai (worker falso)
    └── httpws/     # :8000 UI embutida, REST /api/*, hub WS /ws (2 Hz)
```

### 1.1 Grafo de Dependências (import permitido)

```text
cmd ──> todos
udp, cluster, pipeline, session, ipc, store, sim, httpws ──> contracts
pipeline ──> (lê) session.Snapshot   [interface, não import circular]
sim      ──> udp.Sink (interface)    [injeta nos mesmos canais]
httpws   ──> store.Reader (interface), session.Commands (canal)
```

Regras:
- Pacotes **não** se importam entre si além de `contracts`. Comunicação = canais + interfaces pequenas definidas no consumidor, ligadas em `cmd/`.
- Nenhum estado global. Cada pacote expõe `New(cfg, deps) *X` e `Run(ctx) error`.
- `contracts` não importa nada interno.

### 1.2 Responsabilidades por Subpacote

| Pacote | Faz | Não faz | Entradas | Saídas |
| :--- | :--- | :--- | :--- | :--- |
| `contracts` | Structs/constantes espelhando `contracts/`; encode/decode; testes contra `contracts/fixtures/` | Lógica de negócio | — | Tipos |
| `udp` | Bind `:5005`; goroutine de leitura com buffer reutilizável; decode cabeçalho + `csi_payload`; envio `CLUSTER_SYNC` (10 Hz) e `MODE_CMD` (imediato) em broadcast | Decidir slot, persistir, chamar IPC | Socket, `SlotMap` de `cluster` | `ControlCh` (HELLO/HEARTBEAT), `DataCh` (CSI/PERIPHERAL) |
| `cluster` | Registry MAC→`node_id` 0..4 (estável, persistido); FSM `DISCOVERED→SYNCING→ACTIVE→SUSPECT→LOST`; recálculo de slots K ativos (`100/K` ms); bitmap periféricos por nó | Processar CSI | `ControlCh`, `PERIPHERAL_DATA.peripherals` | `SlotMap` (→`udp`), `CLUSTER_STATUS` (→`httpws`), eventos (→`store`), máscara de enlaces (→`pipeline`) |
| `pipeline` | Ring buffers pré-alocados por enlace `(tx,rx)`; agrupar frames por `cycle_seq`; fechar ciclo; montar `CSI_WINDOW` e `PERIPHERAL_SNAPSHOT`; aplicar limiares do tripulante ativo e gerar severidade por subsistema; mesclar `AI_INFERENCE` | Abrir SQLite, falar WS direto | `DataCh`, máscara do `cluster`, `session.Snapshot`, inferências do `ipc` | `ipc` (lo-pri), `store` (cmds), `httpws` (estado latest-wins), alertas |
| `session` | Dono do `crew_id` ativo e `mission_mode`; hot-swap atômico; calibração; montar contexto de `CHAT_CORRELATE_REQ` | Telemetria contínua | Cmds de `httpws`/`sim`, `CREW_ACK`, respostas de chat | `Snapshot` atômico, `SET_ACTIVE_CREW`, `CREW_STATE`, `MODE_CMD` |
| `ipc` | Conectar/reconectar `127.0.0.1:5006`; framing; fila hi-pri/lo-pri; roteamento de respostas por `type` e `req_id` | Interpretar inferência | Envelopes de `pipeline`/`session` | `InferenceCh`, `CrewAckCh`, `ChatRespCh`, `CalibFbCh` |
| `store` | Goroutine única de escrita; batch 250 ms; PRAGMAs; migrations da pasta configurada por `--migrations`; pool read-only para REST; outbox Store-and-Forward; checkpoint WAL | Regras clínicas | `store.Cmd` canal | Linhas no DB, ACKs de flush |
| `sim` | Nós virtuais (MACs fixos, HELLO/HEARTBEAT/CSI/I2C) e cenários; worker IA falso | Rodar em produção sem flag | Flags, `POST /api/dev/scenario` | Mesmos canais de `udp`; listener IPC falso |
| `httpws` | Servir `embed` UI; REST; hub WS; validar envelope de entrada; decimador 2 Hz | Calcular severidade (só repassa) | Estado latest-wins, eventos, `store.Reader` | Frames WS, cmds para `session` |

---
## 2. Fluxo de Execução Concorrente

### 2.1 Mapa de Goroutines (estado estável, ~10 + 1 par por cliente WS)

| # | Goroutine | Pacote | Gatilho | Bloqueia em |
| :--- | :--- | :--- | :--- | :--- |
| G1 | `udpRx` | `udp` | `ReadFromUDP` contínuo | Socket (só) |
| G2 | `tdmTicker` | `udp` | `time.Ticker` 100 ms (relógio monotônico) | Nada (lê `SlotMap` atômico) |
| G3 | `clusterFSM` | `cluster` | `ControlCh` + varredura 100 ms | Canal |
| G4 | `cycleAssembler` | `pipeline` | `DataCh` + timer de fechamento de ciclo | Canal |
| G5 | `ipcWriter` | `ipc` | Filas hi/lo | Socket TCP |
| G6 | `ipcReader` | `ipc` | `io.ReadFull` frames | Socket TCP |
| G7 | `sessionLoop` | `session` | `CmdCh`, `CrewAckCh`, `ChatRespCh` | Canal |
| G8 | `storeWriter` | `store` | `CmdCh` + ticker 250 ms | Disco (isolado aqui) |
| G9 | `wsBroadcaster` | `httpws` | Ticker 500 ms (2 Hz) + `EventCh` | Nada (send não bloqueante) |
| G10 | `httpServer` | `httpws` | `net/http` (goroutine por request) | Rede |
| Gc | `wsClientWriter/Reader` ×N | `httpws` | 1 par por cliente | Socket do cliente |
| Gs | `simNodes`, `mockAI` | `sim` | Só com flags | — |

Princípio: **cada recurso de I/O tem dono único** (socket UDP: G1/G2; conexão IPC: G5/G6; escrita SQLite: G8; socket WS: Gc).

### 2.2 Canais e Política de Backpressure

| Canal | Produtor → Consumidor | Buffer | Cheio = |
| :--- | :--- | :--- | :--- |
| `udp.ControlCh` | G1 → G3 | 64 | Drop + `dropped_ctrl` (heartbeat seguinte recupera) |
| `udp.DataCh` | G1 → G4 | 512 (≈2,5 ciclos) | Drop do mais novo + `dropped_frames` |
| `cluster.SlotMap` | G3 → G2, G4 | `atomic.Pointer` (latest-wins) | n/a |
| `ipc.LoPri` | G4 → G5 | 8 janelas | Drop janela mais antiga + `ipc_dropped_windows` |
| `ipc.HiPri` | G7 → G5 | 16 | Erro imediato ao chamador (`ai_busy`) |
| `ipc.InferenceCh` | G6 → G4 | 32 | Drop + métrica |
| `ipc.CrewAckCh`, `ChatRespCh`, `CalibFbCh` | G6 → G7 | 8 cada | Bloqueio (baixo volume) |
| `store.CmdCh` | G3/G4/G7/httpws → G8 | 4096 | `select` timeout 50 ms; falha = `store_backlog` + alerta de sistema |
| `httpws.Latest` | G4 → G9 | `atomic.Pointer` | n/a |
| `httpws.EventCh` | G3/G4/G7 → G9 | 128 | Bloqueio curto (eventos raros e críticos) |
| `session.CmdCh` | httpws/sim → G7 | 16 | Responde `busy` |

Regra de ouro: **caminho UDP→pipeline nunca espera disco, IPC nem WS**. Todo send no hot path = `select { case ch <- v: default: contador++ }`.

### 2.3 Ciclo TDM (100 ms) — Central é Mestre de Tempo

```text
G2 tick (t0)                                                        t0+100ms
 │ CLUSTER_SYNC{cycle_seq=n, epoch_us, slot_ms=20, slots[], mode} ─> broadcast :5005
 ├── slot0 TX=N0 ──┼── slot1 TX=N1 ──┼── slot2 ──┼── slot3 ──┼── slot4 ──┤
 │   RX enviam CSI_FRAME{cycle_seq=n, slot_id, tx, rx, iq[]}
 │
G4: buckets[n % 4][link] <- frames por cycle_seq
    fecha ciclo n quando: todos enlaces ativos chegaram OU t0+130ms (grace 30 ms)
    enlaces faltantes = marcados na máscara de qualidade; nunca espera mais
```

- `CLUSTER_SYNC` leva `cycle_seq` (uint32 monotônico); nós ecoam no `CSI_FRAME`. Agrupar por `cycle_seq` elimina dependência do relógio dos ESP32. **(Proposta de contrato P1, §6.)**
- 4 ciclos em voo (`[4][20]`), pré-alocados. `cycle_seq` fora da janela = descarte (`late_frames`).
- Mudança de `SlotMap`/modo: G2 aplica no **próximo** tick, nunca no meio do ciclo.
- `SetReadBuffer(4 MiB)`; datagrama alvo `< 1400 B` (sem fragmentação IP).
- Carga: 5 slots × 4 RX = 20 `CSI_FRAME`/ciclo = **200 pps** + 5 HEARTBEAT/s + 5 PERIPHERAL_DATA/s.

### 2.4 Failover N+1

| Evento | Regra | Tempo |
| :--- | :--- | :--- |
| `ACTIVE → SUSPECT` | 2 ciclos sem pacote do nó | 200 ms |
| `SUSPECT → LOST` | 3º ciclo sem pacote | 300 ms |
| Recalcular `SlotMap` | K ativos, `slot_ms = 100/K` (K=4: 25 ms/12 enlaces; K=3: 33 ms/6 enlaces) | imediato em G3 |
| Propagar | Próximo tick G2 | ≤ 100 ms |
| **Total** | detecção + propagação | **≤ 400 ms (aceite < 500 ms)** |
| Retorno | `LOST → SYNCING`; 3 heartbeats consecutivos para `ACTIVE` (histerese anti-flapping) | ~300 ms |

`node_id` estável por MAC e persistido (**proposta P5 a Selliny/M1**), para enlace `(tx,rx)` manter significado entre reboots e baselines da IA continuarem válidos.

---
### 2.5 Montagem de Janelas e Envio à IA

- Ring buffer por enlace: 20 × 300 posições (30 s @ 10 Hz) de struct fixa (`iq` inline, sem ponteiros) — ~0,8 MB total, zero GC no hot path.
- `CSI_WINDOW` = bloco de `window_cycles` ciclos fechados (padrão 5 = 500 ms → **2 Hz** no IPC), com `cycle_seq_first`, `active_link_mask` (20 bits) e qualidade por enlace. Worker IA mantém histórico longo (FFT respiratória 0,1–0,5 Hz exige ≥ 20 s). **(Proposta P2 com M5, §6.)**
- `PERIPHERAL_SNAPSHOT` 1 Hz: última leitura por sensor (`SCD40`, `BME280`, `MAX30102`), idade e `node_id`.
- `crew_id` anexado **só** a janelas biométricas. Ambiente (`SCD40`/`BME280`) é dado de cabine (`crew_id=null`).

### 2.6 Escrita Single-Writer SQLite (batch 250 ms)

```text
G8 loop:
  select
    cmd := <-CmdCh      -> append em batch[tipo]; se len(batch) >= 512 -> flush
    <-ticker 250ms      -> flush se batch não vazio
    cmd Flush{done}     -> flush imediato; done <- err         (usado no hot-swap)
    <-ctx.Done()        -> drena CmdCh, flush final, wal_checkpoint(TRUNCATE), close
  flush = BEGIN IMMEDIATE; prepared stmts; COMMIT  (1 fsync / 250 ms)
```

- PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `wal_autocheckpoint=1000`.
- Conexões: **1 escrita** (`SetMaxOpenConns(1)`) + pool **read-only** (`mode=ro`, 4 conns) para REST. Edge AI abre seu próprio `mode=ro`.
- **O que persiste (protege cartão SD/eMMC):**

| Dado | Taxa | Tabela (schema M1) |
| :--- | :--- | :--- |
| `AI_INFERENCE` | 1 Hz (decimado) | `telemetry_timeseries` |
| Periféricos I2C | 1 Hz | `peripheral_readings` |
| CSI bruto | **Não** em regime; só calibração e dump 30 s em alerta vermelho | blob em `alerts_audit` |
| Alertas, autoexames, chat, cluster | Por evento | `alerts_audit`, `self_exams`, `chat_*` |
| Alerta vermelho | Por evento, mesma tx | `alerts_audit` + `store_and_forward_outbox` |

Estimativa `< 50 MB/dia`. Migrations SQL da pasta configurada por `--migrations` são aplicadas no boot por `store` (tabela de versão). Essa pasta não é distribuída no repositório atual; a base de pesquisa usa seus próprios scripts de preparação (seção 12).

### 2.7 Broadcast WebSocket (2 Hz)

- G4 atualiza `httpws.Latest` (`atomic.Pointer`) a cada ciclo.
- G9 a cada 500 ms (config `--ws-hz`, 2–10 Hz): lê `Latest`, **serializa uma vez**, envia o mesmo `[]byte` a todos os clientes (canal/cliente buffer 8, `select default` = drop de telemetria).
- Eventos (`ALERT_EVENT`, `CREW_STATE`, `CLUSTER_STATUS` em mudança, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`) saem **imediatamente** por `EventCh`. Cliente que não absorve evento → desconectado (reconecta e recebe snapshot).
- Na conexão: push inicial (`CREW_STATE` + `CLUSTER_STATUS` + último `TELEMETRY_FRAME`). Write deadline 1 s; ping 10 s.

### 2.8 Ordem de Start / Shutdown

```text
Start:    store(migrate) -> session(carrega último crew) -> ipc -> pipeline -> cluster -> udp|sim -> httpws
Shutdown: httpws(para accept, fecha WS 1001) -> udp|sim -> cluster -> pipeline(drain)
          -> ipc(close) -> session -> store(drain + flush + checkpoint TRUNCATE)
```
`signal.NotifyContext(SIGINT, SIGTERM)`; timeout total 5 s (systemd `TimeoutStopSec=10`).

---
## 3. Gerenciamento de Sessão por Astronauta (`crew_id`)

### 3.1 Estado (dono exclusivo: G7 `sessionLoop`)

| Campo | Tipo | Uso |
| :--- | :--- | :--- |
| `active_crew_id` | string | Tripulante ativo |
| `profile` | `contracts.CrewProfile` | Idade, missão, dia de voo, baseline_path |
| `thresholds` | `contracts.Thresholds` | Limiares individuais por subsistema/métrica |
| `mission_mode` | `MissionMode` | `MODE_CABIN_TOMOGRAPHY`, `MODE_REST_VITALS`, `MODE_COUNTERMEASURE_EXERCISE`, `MODE_RADIATION_ALERT` |
| `ai_ready` | bool | `true` só após `CREW_ACK` ok |
| `calibration_required` | bool | `true` se worker usou `baseline_ae_default.onnx` |
| `calib_state` | struct | Idle / passo ativo de calibração |
| `swap_seq` | uint64 | Monotônico; descarta ACKs atrasados de troca anterior |

G4 e G9 leem cópia imutável via `atomic.Pointer[SessionSnapshot]`.

### 3.2 Hot-Swap de `crew_id` (`SET_CREW`)

1. `httpws` valida envelope e envia `CmdSetCrew{crew_id, replyCh}` para `session.CmdCh`.
2. Se `crew_id == active_crew_id` e `ai_ready`: retorna `CREW_STATE` atual.
3. G7 incrementa `swap_seq`; envia `store.Flush{done}` e aguarda — garante que nenhum batch pendente do tripulante anterior vaze para o novo.
4. G7 lê do `store` (read-only): `crew_profiles` + `crew_baselines` + últimos valores relevantes. `crew_id` inexistente → erro REST/WS, **mantém tripulante atual**.
5. G7 atualiza `SessionSnapshot` com o novo `crew_id` e `ai_ready=false` (enquanto troca na IA, `pipeline` continua gravando I2C ambiental sem interrupção e **congela** inferência biométrica até confirmar).
6. G7 envia `SET_ACTIVE_CREW` (com `req_id=swap_seq`) na fila `ipc.HiPri`.
7. Aguarda `CREW_ACK` com timeout **2 s**:
   - **Sucesso:** `ai_ready=true`, `calibration_required = !payload.baseline_found`.
   - **Timeout ou IPC offline:** `ai_ready=false`, log warning; telemetria I2C + autoexames + REST continuam. Quando IPC reconectar, G7 reenvia `SET_ACTIVE_CREW` automaticamente (auto-healing).
8. G7 publica `CREW_STATE` em `httpws.EventCh` e grava evento de auditoria no `store`. UI só troca contexto visual ao receber `CREW_STATE`.

### 3.3 Contexto para Calibração, Autoexames e Chatbot

- **Troca de `mission_mode`:** origem manual (`httpws`) ou automática (`MODE_RADIATION_ALERT` por cenário/evento SPE). G7 atualiza `SessionSnapshot`, envia `MODE_CMD` imediato via `udp` e publica `CREW_STATE`.
- **Calibração:** `CALIBRATION_STEP` vai em `ipc.HiPri` com `crew_id` e `step_id`; `pipeline` marca flag `calibration_tag` nos frames da janela para persistência excepcional do CSI bruto.
- **Chatbot (`CHAT_MSG`):** G7 monta `CHAT_CORRELATE_REQ` anexando `crew_id`, perfil, limiares, últimas leituras I2C (`SCD40`, `BME280`, `MAX30102`), última `AI_INFERENCE`, resumo longitudinal 24 h (sono, HRV, autoexames recentes no `store`) e últimas mensagens do `chat_sessions`. Envia em `ipc.HiPri` (timeout 5 s). Na volta (`CHAT_CORRELATE_RESP`), G7 persiste diálogo + evidências + eventuais alertas em `store` (e `store_and_forward_outbox` se severidade `RED` / escalonamento `STORE_AND_FORWARD`), e emite `CHAT_REPLY` na UI.

---
## 4. Contratos de Interconexão

> Fonte canônica: `contracts/jsonschema/{udp,ipc,ws,rest}/` + `contracts/enums/`. Esta seção define **comportamento do transporte** na Central. Campos marcados *(P#)* são propostas pendentes de PR em `contracts/` (§6).

### 4.1 Central ↔ Edge AI — IPC TCP `127.0.0.1:5006`

**Papéis:** worker Python = servidor (listen); Central = cliente (dial). 1 conexão persistente, full-duplex.

**Framing:**

```text
+-------------------------+-------------------------------+
| len: uint32 big-endian  | JSON UTF-8 (len bytes)        |
+-------------------------+-------------------------------+
```

| Regra | Valor |
| :--- | :--- |
| `len` máximo | 1 MiB. Acima = erro de protocolo, fecha conexão, reconecta |
| `len == 0` | Inválido |
| Leitura | `io.ReadFull` de 4 B, depois `io.ReadFull` de `len` B (buffer reutilizável) |
| Escrita | Header + body em uma `Write` (ou `net.Buffers`) por frame; só G5 escreve |
| Deadlines | Write 1 s; Read sem deadline + watchdog de silêncio |
| Envelope | `{"v":1,"type":"...","ts_us":<int64>,"crew_id":"...|null","req_id":<uint64>?,"payload":{...}}` |
| Correlação | `req_id` *(P3)* em mensagens request/response (`SET_ACTIVE_CREW`↔`CREW_ACK`, `CHAT_CORRELATE_REQ`↔`CHAT_CORRELATE_RESP`, `CALIBRATION_STEP`↔`CALIBRATION_FEEDBACK`) |
| Versão | `v != 1` → descarta frame + métrica `ipc_bad_version` |

**Mensagens:**

| Direção | `type` | Fila | Taxa | Conteúdo-chave |
| :--- | :--- | :--- | :--- | :--- |
| C→IA | `CSI_WINDOW` | lo | 2 Hz (5 ciclos) | `cycle_seq_first`, `mode`, `active_link_mask`, enlaces `(tx,rx)` com I/Q, RSSI, noise floor |
| C→IA | `PERIPHERAL_SNAPSHOT` | lo | 1 Hz | Últimas leituras I2C + idade + `node_id` |
| C→IA | `SET_ACTIVE_CREW` | **hi** | Sob demanda | `crew_id`, `baseline_path`, limiares |
| C→IA | `CHAT_CORRELATE_REQ` | **hi** | Sob demanda | Texto + contexto (§3.3) |
| C→IA | `CALIBRATION_STEP` | **hi** | Sob demanda | `step_id`, ação, duração |
| IA→C | `AI_INFERENCE` | — | ~2 Hz | Postura, cadência, FR, FC, HRV, `anomaly_score`, confiança, `cycle_seq_first` de origem |
| IA→C | `CREW_ACK` | — | 1/troca | `ok`, `baseline_found`, erro |
| IA→C | `CHAT_CORRELATE_RESP` | — | 1/req | Diferencial ranqueado, evidências, contramedida, escalonamento, IDs de fonte NASA HRP/CSA |
| IA→C | `CALIBRATION_FEEDBACK` | — | Por passo | Qualidade de sinal, progresso |

**Política de fila (G5):** `select` prioriza `HiPri`; `LoPri` só quando `HiPri` vazio. Janela CSI obsoleta (> 1 s) descartada antes de enviar.

**Pendências (G7 não bloqueia):** cada request hi-pri vira entrada em `pending[req_id]{deadline, replyCh}`; timer varre a cada 100 ms. Timeouts: `CREW_ACK` 2 s, `CHAT_CORRELATE_RESP` 5 s, `CALIBRATION_FEEDBACK` 2 s. Resposta com `req_id` desconhecido/antigo = descartada (`ipc_stale_resp`).

**Reconexão / saúde:**

| Situação | Ação |
| :--- | :--- |
| Dial falha | Backoff exponencial 250 ms → 5 s (jitter ±20%) |
| Conexão cai | Fecha, limpa `LoPri`, falha `pending` com `ai_unavailable`, `session.ai_ready=false` |
| Reconecta | G7 reenvia `SET_ACTIVE_CREW` do tripulante ativo antes de liberar `LoPri` |
| Silêncio > 3 s (sem `AI_INFERENCE` com `LoPri` ativo) | Considera worker travado → reconecta + `CLUSTER_STATUS.ai_link=degraded` |
| Frame inválido (JSON/tamanho) | Fecha e reconecta; métrica `ipc_protocol_errors` |

### 4.2 Central ↔ Frontend — WebSocket `:8000/ws` + REST `:8000/api/*`

**Envelope único (ambas direções):** `{"v":1,"type":"<ws_msg_type>","ts_us":<int64>,"crew_id":"...|null","payload":{...}}`. Mensagens client→server podem levar `client_msg_id` *(P4)* para ACK/erro correlacionado.

**Server → Client:**

| `type` | Quando | Conteúdo-chave |
| :--- | :--- | :--- |
| `TELEMETRY_FRAME` | 2 Hz | Vitais (FC, HRV, FR, SpO2, postura), ambiente (CO2, T, UR, P), `subsystems[6]` com `GREEN/YELLOW/RED`, `ai_ready` |
| `ALERT_EVENT` | Imediato | `subsystem`, `severity`, mensagem, contramedida, `escalation`, ID fonte NASA HRP/CSA |
| `CREW_STATE` | Conexão + troca crew/modo/calibração | `crew_id`, perfil resumido, `mission_mode`, `ai_ready`, `calibration_required` |
| `CLUSTER_STATUS` | Conexão + mudança + 1 Hz | Nós (`node_state`, slot, periféricos), enlaces ativos 20/12/6, `ai_link`, métricas de drop |
| `CHAT_REPLY` | Resposta | Diferencial, evidências, ações, escalonamento, aviso "apoio, não diagnóstico" |
| `CALIBRATION_FEEDBACK` | Por passo | Qualidade de sinal, progresso |

**Client → Server:**

| `type` | Destino interno | Validação |
| :--- | :--- | :--- |
| `SET_CREW` | `session.CmdCh` | `crew_id` existe em `crew_profiles` |
| `CHAT_MSG` | `session.CmdCh` → IPC hi | Texto ≤ 2000 chars; exige `crew_id` ativo |
| `SELF_EXAM` | `store` + `pipeline` (reavalia subsistemas) | `exam_type` válido; unidades no nome do campo |
| `CALIBRATION_STEP` | `session.CmdCh` → IPC hi | `step_id` válido |

**Regras WS:** schema inválido → resposta de erro (envelope `ERROR` *(P4)*), conexão mantida; mensagem > 64 KB → close 1009; rate limit 20 msg/s por cliente; `Origin` restrita à LAN/`self`.

**REST (leitura via pool read-only):** `GET /api/crew`, `GET /api/crew/{id}/timeseries?metric=&from=&to=&bucket=` (decimação no SQL por bucket), `GET /api/protocols/{id}`, `GET /api/alerts`, `GET /api/outbox`, `GET /api/metrics`, `GET /healthz`. Dev only (com `--mock-cluster`): `POST /api/dev/scenario`, `POST /api/dev/node/{id}/kill`.

Segurança HTTP: CSP `default-src 'self'; connect-src 'self'`; zero referência a CDN; UI via `embed` (`httpws/ui/`).

---
## 5. Estratégia de Mock (`--mock-cluster` e `--mock-ai`)

Princípio: **mock substitui só a borda; o núcleo roda idêntico ao hardware real.** Nenhum `if mock` dentro de `cluster`, `pipeline`, `session`, `store`, `httpws`.

### 5.1 Matriz de Modos

| Flags | Cluster | IA | Uso |
| :--- | :--- | :--- | :--- |
| *(nenhuma)* | ESP32-S3 reais via UDP | Worker Python real | Produção Orange Pi |
| `--mock-cluster` | `sim` virtual | Worker Python real | M5 testa IA sem hardware |
| `--mock-ai` | ESP32-S3 reais | `sim.MockAI` | Bancada com Nicolas/M2 sem Python |
| `--mock-cluster --mock-ai` | `sim` virtual | `sim.MockAI` | Notebook do Leonardo; Rafael/M3 dev da UI (`make central-run-mock`) |

### 5.2 `--mock-cluster` (nós virtuais)

| Aspecto | Desenho |
| :--- | :--- |
| Ponto de injeção | `sim` implementa a mesma interface `udp.Sink` e escreve em `ControlCh`/`DataCh`. `udp` não abre socket de rx. |
| Modo alternativo `--mock-cluster=udp` | `sim` envia datagramas reais para `127.0.0.1:5005` — testa também o decoder `udp` e serve de referência para Nicolas/M2 |
| Nós | 5 MACs fixos (`02:ED:6E:00:00:0X`, bit localmente administrado), mesmo ciclo de vida: `NODE_HELLO` → responde a `CLUSTER_SYNC` → `HEARTBEAT` |
| Relógio | `sim` segue o `CLUSTER_SYNC` lido do `SlotMap` (como firmware real); ecoa `cycle_seq` |
| CSI sintético | Por enlace: amplitude base + modulação respiratória (0,25 Hz) + cardíaca (1,2 Hz) + ruído gaussiano + offset de fase linear (para o `phase_sanitizer` de M5 ter o que limpar). Tabelas senoidais pré-calculadas |
| I2C sintético | `SCD40` ~600 ppm, `BME280` 22 °C/45%/1013 hPa, `MAX30102` SpO2 98% / FC 65 só no nó com "dedo apoiado" |
| Determinismo | `--seed` (padrão fixo) + `--time-scale` (1x, 10x p/ testes). Mesma seed = mesma sequência de frames (teste de regressão) |
| Falhas injetáveis | `--sim-loss=0.02` (perda de pacote), `--sim-jitter-ms=3`, kill/revive de nó |

**Cenários (`--scenario` ou `POST /api/dev/scenario`):**

| Cenário | Linha do tempo sintética | Resposta esperada da Central | Base NASA |
| :--- | :--- | :--- | :--- |
| `hypercapnia` | `SCD40` 600 → 5000 ppm em 120 s | `RESPIRATORY_ATMOSPHERE` YELLOW → RED; `ALERT_EVENT` ventilação | Ambiente fechado hostil |
| `sans` | PA ↑ + `SELF_EXAM` Amsler com metamorfopsia injetado | `NEURO_OCULAR_SANS` YELLOW; Thigh Cuffs + ultrassom ONSD + Complexo B | SANS/VIIP |
| `solar_storm` | Evento SPE em t=10 s | `MODE_RADIATION_ALERT` → `MODE_CMD` nós + overlay UI; abrigo + Vitaminas C e E | CANS/ROS |
| `dehydration_sleep` | Sono 4 h, HRV −30%, FC repouso ↑ | `IMMUNE_HEMATO_NUTRITION` YELLOW; Nutrition SMO + ajuste circadiano | Cortisol/CRP, volume plasmático |
| `node_loss` | Nó 3 silencia em t=15 s, volta em t=45 s | `CLUSTER_STATUS` 20 → 12 → 20 enlaces; failover medido `< 500 ms` | — (N+1) |

### 5.3 `--mock-ai` (worker IA falso)

| Aspecto | Desenho |
| :--- | :--- |
| Transporte | `sim.MockAI` sobe **listener TCP real** em `127.0.0.1:5006` (ou `--mock-ai-addr`) **dentro do processo**. `ipc` faz dial normal — framing, filas, reconexão e timeouts são exercitados de verdade |
| `SET_ACTIVE_CREW` | Responde `CREW_ACK` em 150 ms; `baseline_found=false` para `crew_id` sem baseline (testa `calibration_required`) |
| `CSI_WINDOW` | Responde `AI_INFERENCE` derivado do cenário ativo (ex.: `dehydration_sleep` → HRV baixo) com `cycle_seq_first` ecoado |
| `CHAT_CORRELATE_REQ` | Respostas canned de `contracts/fixtures/ipc/` mapeadas por palavra-chave + estado do cenário (golden cases M1: cefaleia+CO2, cefaleia+Amsler, cefaleia+sono, radiação) |
| `CALIBRATION_STEP` | `CALIBRATION_FEEDBACK` progressivo (0 → 100%) |
| Falhas injetáveis | `--mock-ai-latency-ms`, `--mock-ai-drop-ack` (testa timeout 2 s), `--mock-ai-crash-after=60s` (testa reconexão + reenvio de `SET_ACTIVE_CREW`) |

Fonte das respostas = `contracts/fixtures/` → mock nunca diverge do contrato real de M5.

### 5.4 Roteiro de Validação Local (antes da Orange Pi)

1. `make contracts-validate` — fixtures válidas/ inválidas passam.
2. `make central-run-mock` (`--mock-cluster --mock-ai`) no Windows/Linux dev, sem hardware.
3. Abrir `http://localhost:8000` — UI conecta, recebe `CREW_STATE` + `CLUSTER_STATUS` + `TELEMETRY_FRAME` 2 Hz.
4. Trocar `crew_id` → `CREW_STATE` com `ai_ready=true` em `< 500 ms`.
5. Rodar cada cenário (§5.2) e conferir resposta esperada.
6. `node_loss` → medir failover em `/api/metrics`.
7. `--mock-ai-crash-after` → `ai_ready=false`, I2C continua, recupera sozinho.
8. Teste de carga: `--time-scale=10` por 10 min → `dropped_frames == 0`, heap estável (`/debug/pprof` só em build dev).
9. Cross-compile `GOOS=linux GOARCH=arm64 CGO_ENABLED=0` → binário roda em QEMU/Orange Pi com `--mock-cluster` antes de plugar ESP32.
10. Troca para hardware: tirar `--mock-cluster`; depois tirar `--mock-ai` com worker de M5 rodando.

Testes Go planejados (sem código agora): `contracts` (round-trip fixtures), `ipc` (framing com `net.Pipe`, len inválido, reconexão), `cluster` (tabela de transições FSM + tempos de failover com relógio falso), `pipeline` (fechamento de ciclo com enlaces faltantes), `store` (batch/flush/shutdown em arquivo temporário), `session` (hot-swap com ACK, timeout e ACK atrasado), e2e (`--mock-cluster --mock-ai` + cliente WS de teste).

---
## 6. Propostas de Contrato (PR em `contracts/` antes do código)

`contracts/` v1 ainda ausente no workspace (ver `contracts/README.md`). Itens abaixo entram na restauração da Sprint 0, com aprovação de Leonardo + membro afetado.

| ID | Mudança | Afeta | Motivo |
| :--- | :--- | :--- | :--- |
| P1 | `cycle_seq` (uint32) em `CLUSTER_SYNC` e eco em `CSI_FRAME` | Nicolas/M2 | Agrupar ciclo sem depender de relógio dos ESP32 |
| P2 | `CSI_WINDOW` = 5 ciclos (2 Hz) com `cycle_seq_first` e `active_link_mask`; IA mantém histórico longo | Santiago/M5 | Corta overhead JSON 5×; FFT respiratória precisa ≥ 20 s no worker |
| P3 | `req_id` (uint64) no envelope IPC request/response | Santiago/M5 | Correlação, descarte de ACK atrasado |
| P4 | `client_msg_id` opcional + tipo `ERROR` em `ws_msg_type` | Rafael/M3 | Feedback de validação para a UI |
| P5 | Tabela `cluster_nodes(mac, node_id, first_seen, last_seen)` | Selliny/M1 | `node_id` estável por MAC entre reboots |
| P6 | `csi_payload` binário após cabeçalho JSON (`\n` separador) em vez de base64 | Nicolas/M2 | −33% bytes no UDP; decode sem alocação |

---

## 7. Flags do Binário (`cmd/edgespace-central`)

| Flag | Padrão | Descrição |
| :--- | :--- | :--- |
| `--db` | `./var/edgespace.db` | SQLite WAL |
| `--migrations` | `../database/migrations` | Padrão atual da CLI; diretório não distribuído. Aceita outra pasta de migrations SQL, aplicadas no boot. |
| `--udp-addr` / `--broadcast-addr` | `:5005` / `10.42.0.255:5005` | Rx e destino de `CLUSTER_SYNC` |
| `--ipc-addr` | `127.0.0.1:5006` | Worker Edge AI |
| `--http-addr` | `:8000` | UI/REST/WS |
| `--ws-hz` | `2` | Taxa de `TELEMETRY_FRAME` (2–10) |
| `--mock-cluster` | `false` | `inproc` (padrão) ou `udp` |
| `--mock-ai` | `false` | Worker IA falso em processo |
| `--scenario` | `""` | `hypercapnia`, `sans`, `solar_storm`, `dehydration_sleep`, `node_loss` |
| `--seed`, `--time-scale` | fixo, `1` | Determinismo do `sim` |
| `--log-level` | `info` | `slog` JSON em stdout (journald) |

O alvo `make central-run-mock` passa `--mock-cluster=inproc --mock-ai`, executando os simuladores locais de cluster e IA.

---

## 8. Deploy (`deploy/`)

- `hostapd` (AP local), `dnsmasq` (DHCP local, sem DNS externo), `nftables` (bloqueia saída WAN; libera `:5005/udp` e `:8000/tcp` na LAN; `:5006` só loopback).
- Units `systemd`: `edgespace-ai.service` antes de `edgespace-central.service` (`After=`, mas Central tolera IA ausente). `Restart=on-failure`, `MemoryMax=200M` (Central), `TimeoutStopSec=10`.
- Binário único `build/edgespace-central` com UI embutida; DB em `/var/lib/edgespace/`.

---

## 9. Orçamento e Critérios de Aceite

| Métrica | Alvo | Como medir |
| :--- | :--- | :--- |
| RAM | `< 150 MB` RSS | `/proc/<pid>/status` em 1 h de carga |
| CPU | `< 25%` de 1 núcleo, 5 nós @ 10 Hz | `pidstat 1` |
| Failover N+1 | `< 500 ms` | Timestamp `LOST` → novo `SlotMap` (métrica) |
| Hot-swap `crew_id` | `< 500 ms` com IA ok; `≤ 2 s` pior caso | `SET_CREW` → `CREW_STATE` |
| Alerta → UI | `< 1 s` | `ts_us` evento vs. envio WS |
| Perda no hot path | `dropped_frames == 0` em regime | `/api/metrics` |
| Escrita | ≤ 4 commits/s; `< 50 MB/dia` | Métrica `store_commits`, tamanho DB |
| Isolamento | Zero conexão de saída fora da LAN | `nftables` counters + `ss -tunp` |
| Mock | `--mock-cluster --mock-ai` sobe sem hardware nem Python | Roteiro §5.4 |

---

## 10. Riscos e Mitigação

| Risco | Mitigação |
| :--- | :--- |
| Rajada UDP estoura buffer do kernel | `SetReadBuffer(4 MiB)`, G1 sem trabalho além de decode, métrica de drop |
| GC pause no hot path | Ring buffers sem ponteiros, buffers reutilizados, `GOGC` ajustado após profiling |
| Worker Python trava | Watchdog 3 s + reconexão + `ai_ready=false`; Central nunca depende da IA para I2C/alertas por limiar |
| Desgaste de eMMC/SD | Batch 250 ms, sem CSI bruto em regime, checkpoint controlado |
| ACK de troca atrasado aplica crew errado | `swap_seq`/`req_id`, descarte de resposta obsoleta |
| Contrato diverge entre Go/Python/TS | Fixtures compartilhadas + `make contracts-validate` no merge; mocks alimentados pelas fixtures |

---

## 11. Sequência de Implementação (Sprint 1 → 2)

1. Restaurar `contracts/` v1 + propostas P1–P6 → `make contracts-validate`.
2. `contracts` (tipos Go + testes com fixtures).
3. `store` (migrations, writer único, batch, shutdown).
4. `httpws` mínimo (`/healthz`, WS hub 2 Hz com dado fixo) → **Rafael/M3 desbloqueado**.
5. `sim --mock-cluster` + `cluster` (FSM, `SlotMap`) + `udp` (tx `CLUSTER_SYNC`).
6. `pipeline` (ciclo, janelas, latest-wins) → telemetria real no WS.
7. `ipc` + `sim --mock-ai` → `session` (hot-swap completo).
8. Cenários + `node_loss` + métricas → vertical slice mock da Sprint 1.
9. `udp` rx real com Nicolas/M2 (2 nós → 5 nós) e worker real de Santiago/M5 (Sprint 2).

---

## 12. Integração com a base de pesquisa

A base de pesquisa de Selliny/M1 fica em `database/space_health_sqlite/` e deve ser consultada por conexão separada somente leitura. Ela mantém schema e dados próprios; o banco operacional da Central é `var/edgespace.db`. O [guia de uso local e DBeaver](../../database/space_health_sqlite/docs/COMO_RODAR_LOCAL_E_DBEAVER.md) descreve as consultas e os comandos disponíveis. O escopo da entrega operacional de M1 está em [database/README.md](../../database/README.md#base-operacional-planejada).

---

Documento vivo. Mudança em interface exige atualização deste arquivo + `contracts/`. Guardião: Leonardo (M4).
