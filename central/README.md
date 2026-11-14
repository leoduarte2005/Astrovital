# central/ — Orquestrador Central em Go (Orange Pi 4 Pro)

**Responsável:** Leonardo (M4 — Integrador). Guia: [`docs/members/MEMBER-04-CENTRAL-GO.md`](../docs/members/MEMBER-04-CENTRAL-GO.md)

## Propósito
Binário estático Go (`CGO_ENABLED=0`, `linux/arm64`) que integra o cluster ESP32-S3 (Nicolas/M2), o worker Edge AI (Santiago/Leonardo/M5), o SQLite WAL (schema Selliny/M1) e o painel web (Rafael/M3).

## Estrutura
| Pasta | Função |
| :--- | :--- |
| [`cmd/edgespace-central/`](cmd/edgespace-central/README.md) | Ponto de entrada CLI, flags (`--mock-cluster`, `--db`, `--scenario`), shutdown gracioso |
| [`internal/`](internal/README.md) | Pacotes internos (contratos, UDP, cluster, pipeline, sessão, IPC, store, sim, httpws) |

## Fluxo de Dados
- **UDP `:5005` ↔ Nicolas (M2):** recebe CSI e periféricos dos 5× ESP32-S3.
- **TCP `127.0.0.1:5006` ↔ Santiago/Leonardo (M5):** envia CSI/contexto clínico, recebe inferências.
- **HTTP/WS `:8000` ↔ Rafael (M3):** serve UI compilada e WebSocket.
- **Escritor único no SQLite:** schema definido por Selliny (M1).

## Regras
- `CGO_ENABLED=0` obrigatório (SQLite em Go puro).
- Escritor único no SQLite (`internal/store`).
- Loop crítico UDP nunca bloqueia por I/O de disco ou IPC.
- `make central-build` e `make central-run-mock`.
