# Membro 4 (Leonardo — Integrador) — Orquestrador Central em Go

**Pastas sob responsabilidade exclusiva:** `central/`, `tools/`, `deploy/`. Guardião de `contracts/` e integrador do monorepo.
**Hub único** entre: Nicolas/M2 (nós), Rafael/M3 (UI), Selliny/M1 (DB), Santiago/Leonardo/M5 (IA).

---

## 1. Missão

Binário Go estático (`CGO_ENABLED=0`, `GOOS=linux GOARCH=arm64`) rodando na Orange Pi 4 Pro como hub único entre cluster ESP32-S3, worker Edge AI, SQLite e painel.

---

## 2. Módulos (`central/internal/`)

| Pacote | Responsabilidade | Integração |
| :--- | :--- | :--- |
| `contracts/` | Structs Go espelhando `contracts/jsonschema` + enums; testes com `contracts/fixtures/` | Guardião |
| `udp/` | Socket `:5005`: broadcast `CLUSTER_SYNC` a cada 100 ms; recepção de Nicolas/M2 | ← Nicolas/M2 |
| `cluster/` | Registry MAC→`node_id`, FSM por nó, failover $N+1$, mapa de periféricos | Coordena Nicolas/M2 |
| `pipeline/` | Ring buffers dos 20 enlaces CSI, janelas para Edge AI, agregação I2C | → Santiago/Leonardo/M5 |
| `session/` | Hot-swap de astronauta (`crew_id`), perfil, limiares, modo de missão | ↔ Rafael/M3, → Santiago/Leonardo/M5 |
| `ipc/` | Cliente TCP `127.0.0.1:5006` para Santiago/Leonardo/M5 | ↔ Santiago/Leonardo/M5 |
| `store/` | **Escritor único** SQLite WAL (schema Selliny/M1), FTS5, outbox | Lê Selliny/M1 schema |
| `sim/` | `--mock-cluster`: simula nós Nicolas/M2 com cenários | Dev/testes |
| `httpws/` | HTTP `:8000`: UI Rafael/M3 embutida, REST, WebSocket | ↔ Rafael/M3 |

---

## 3. Regras Críticas

- Loop UDP nunca bloqueia: canais com buffer + descarte contado (métrica `dropped_frames`).
- Uma goroutine escreve no SQLite. Demais módulos enviam comandos ao `store` por canal.
- `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; foreign_keys=ON`.
- Troca de `crew_id`: (1) flush de batch pendente do tripulante anterior, (2) carga do novo perfil, (3) `SET_ACTIVE_CREW` ao IPC, (4) aguarda ACK com timeout 2 s, (5) `CREW_STATE` à UI. Falha no IPC: UI recebe estado com `ai_ready=false`.
- Escalonamento clínico vermelho: grava `alerts_audit` + enfileira `store_and_forward_outbox`.
- Shutdown gracioso (SIGTERM do systemd): para UDP, drena canais, checkpoint WAL.

---

## 4. Simulador de Cenários (`sim/`)

| Cenário | Efeito sintético | Resposta esperada |
| :--- | :--- | :--- |
| `hypercapnia` | `SCD40` sobe gradualmente acima do limiar | Subsistema Respiratório amarelo/vermelho, contramedida ventilação |
| `sans` | PA elevada + Amsler alterado injetado | Neuro-Ocular amarelo, sugere Thigh Cuffs + ultrassom |
| `solar_storm` | Evento SPE | `MODE_RADIATION_ALERT` broadcast a nós e UI |
| `dehydration_sleep` | Sono curto, HRV baixo | Imune/Nutricional amarelo |
| `node_loss` | Silencia nó N | Failover para 12 enlaces, UI mostra cluster degradado |

---

## 5. Deploy (`deploy/`)

- `hostapd` (AP local), `dnsmasq` (DHCP local, sem DNS externo), `nftables` (bloqueia saída WAN, libera só `:5005/udp`, `:8000/tcp` na LAN; `:5006` só loopback), units `systemd` para Central e Edge AI.

---

## 6. Entradas, Saídas, Aceite

- **Consome:**
  - UDP dos nós Nicolas/M2
  - Respostas IPC de Santiago/Leonardo/M5
  - Migrations de Selliny/M1 em `database/migrations/`
  - `dist/` compilado de Rafael/M3 em `frontend/`
- **Produz:**
  - `CLUSTER_SYNC` → Nicolas/M2
  - Requests IPC → Santiago/Leonardo/M5
  - Eventos WS + REST `:8000` → Rafael/M3
  - Binário `build/edgespace-central`
- **Aceite:** RAM `< 150 MB`, CPU `< 25%` de um núcleo com 5 nós a 10 Hz; failover `< 500 ms`; `--mock-cluster` sobe sem hardware; nenhuma conexão de saída fora da LAN.
