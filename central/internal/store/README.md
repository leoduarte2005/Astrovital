# central/internal/store/

**Responsável (runtime):** Leonardo (M4) — escritor único. **Schema:** Selliny (M1) em `database/migrations/`.

## Propósito
**Escritor único** do SQLite `WAL + FTS5` (`edgespace.db`).

## Responsabilidades
- Abrir SQLite com driver Go puro (`CGO_ENABLED=0`) e aplicar PRAGMAs (`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`).
- Goroutine única escritora recebendo comandos de inserção por canal, com batching curto (ex.: a cada 250 ms ou N registros).
- Leituras concorrentes seguras para REST (`GET /api/crew/{id}/timeseries` com decimação por bucket, `/api/protocols/{id}`, histórico de chat e alertas).
- Gerenciamento da fila `store_and_forward_outbox` para alertas vermelhos/pacotes para cirurgiões de voo.

## Regras
- Nenhum outro pacote Go abre o arquivo SQLite diretamente.
- Checkpoint WAL periódico e no shutdown gracioso.
