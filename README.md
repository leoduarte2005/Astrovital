# EdgeSpace — Monitoramento Autônomo de Saúde para Astronautas

> NASA Space Apps Challenge — *Create Health Monitoring Software for Astronauts on Space Missions*
> **Equipe:** Selliny (M1), Nicolas (M2), Rafael (M3), Leonardo (M4 — Integrador), Santiago/Leonardo (M5)

EdgeSpace é uma estação de saúde **100% local (Offline-First / Zero Cloud)** para missões de longa duração (Artemis / Marte, atraso de comunicação de até 22 min). Combina:

- **Sensoriamento passivo por Wi-Fi CSI** (base RuView) em malha TDM multi-estática de **5× ESP32-S3** (20 enlaces, 2.4 GHz ch 6 HT20, failover N+1).
- **Periféricos I2C auto-descobertos** (`MAX30102` SpO2/FC, `BME280` T/UR/pressão, `SCD40` CO2).
- **Orquestrador Central em Go** na **Orange Pi 4 Pro (`linux/arm64`)**, SQLite `WAL + FTS5`.
- **Edge AI em Python + `onnxruntime`** com baseline individual por astronauta (`baseline_ae_<crew_id>.onnx`).
- **Base clínica NASA HRP/CSA** (5 Perigos, 11 Riscos Fisiológicos, 8 Riscos Comportamentais/Bioquímicos) + **motor de correlação causal**.
- **Painel tablet/monitor offline** (React + Vite + Three.js) com Digital Twin 3D, gráficos longitudinais e **Chatbot de Calibração/Consulta Clínica**.

**Proibido:** qualquer serviço de nuvem, CDN, API externa ou download em tempo de execução.

---

## Mapa do Monorepo

| Pasta | Dono | Conteúdo |
| :--- | :--- | :--- |
| [`contracts/`](contracts/README.md) | Todos (guardião: Leonardo/M4) | Fonte única de verdade: enums, JSON Schemas, fixtures |
| [`tools/`](tools/README.md) | Leonardo/M4 | Validador de contratos e utilitários de CI local |
| [`docs/`](docs/README.md) | Todos | Plano mestre, divisão da equipe, guias por membro |
| [`knowledge-base/`](knowledge-base/README.md) | Selliny/M1 | Relatórios NASA HRP/CSA estruturados, protocolos, datasets |
| [`database/`](database/README.md) | Selliny/M1 | Base Space Health SQLite, schema, scripts, consultas e testes |
| [`firmware/`](firmware/README.md) | Nicolas/M2 | Firmware único ESP-IDF v5.x para os 5× ESP32-S3 |
| [`frontend/`](frontend/README.md) | Rafael/M3 | Painel offline, Digital Twin, gráficos, chatbot |
| [`central/`](central/README.md) | Leonardo/M4 | Orquestrador Go (UDP :5005, IPC :5006, HTTP/WS :8000) |
| [`edge-ai/`](edge-ai/README.md) | Santiago/Leonardo/M5 | DSP RuView, modelos ONNX, adaptação por `crew_id`, correlação |
| [`deploy/`](deploy/README.md) | Leonardo/M4 (+ todos) | hostapd, systemd, nftables da Orange Pi 4 Pro |

## Portas e Contratos (resumo)

| Canal | Endpoint | Formato | Contrato |
| :--- | :--- | :--- | :--- |
| Cluster ↔ Central | UDP `:5005` (broadcast + unicast) | Envelope JSON compacto + payload CSI binário | `contracts/jsonschema/udp/` |
| Central ↔ Edge AI | TCP `127.0.0.1:5006` | Frames JSON com prefixo de tamanho (4 bytes big-endian) | `contracts/jsonschema/ipc/` |
| Central ↔ Painel | HTTP + WebSocket `:8000` (`/api/*`, `/ws`) | JSON tipado (envelope `v/type/ts_us/crew_id/payload`) | `contracts/jsonschema/ws/`, `contracts/jsonschema/rest/` |
| Persistência planejada | Arquivo `edgespace.db` | SQLite `journal_mode=WAL`, FTS5; escritor único = Central | [Escopo operacional](database/README.md#base-operacional-planejada) |
| Pesquisa local | Arquivo `database/space_health_sqlite/space_health.db` | SQLite de referência, consultas somente leitura | `database/space_health_sqlite/docs/INTEGRATION.md` |

## Começo Rápido

1. Leia [`docs/00-PROJECT-MASTER-PLAN.md`](docs/00-PROJECT-MASTER-PLAN.md).
2. Leia [`docs/01-TEAM-DIVISION-AND-WORKFLOW.md`](docs/01-TEAM-DIVISION-AND-WORKFLOW.md).
3. Abra seu guia em [`docs/members/`](docs/members/README.md).
4. `make help` lista os alvos de build disponíveis.
5. `make db-research-inventory` explora a base de pesquisa, os 161 agregados fisiológicos e a auditoria de ausências; `make db-research-validate` verifica integridade e proveniência offline, e `make db-research-test` verifica importação e política de ausências. Veja o [guia do pacote](database/space_health_sqlite/docs/INTEGRATION.md).
6. Para abrir o banco e executar SQL pela interface, siga o [passo a passo de uso local e DBeaver](database/COMO_RODAR_LOCAL_E_DBEAVER.md).

## Estado Atual

- Etapa: estruturação da aplicação; base Space Health SQLite, scripts de construção/validação, consultas e documentação de pesquisa incorporados. A Central, o worker e o painel ainda não possuem implementação de aplicação neste workspace.
- Pendência: artefatos da Sprint 0 (`contracts/`, `tools/`) não estavam presentes neste workspace. Ver [`contracts/README.md`](contracts/README.md) para restaurá-los antes da Sprint 1.
