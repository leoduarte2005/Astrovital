# database/ — SQLite WAL + FTS5

**Responsável (schema):** Selliny (M1). **Escritor em runtime:** somente Leonardo (M4) em `central/internal/store`. **Leitor somente-leitura:** Santiago/Leonardo (M5).

## Propósito
Modelagem do banco local `edgespace.db`: perfis multi-astronauta, séries temporais, base clínica NASA com busca FTS5, auditoria e fila Store-and-Forward.

## Estrutura
| Pasta | Conteúdo |
| :--- | :--- |
| [`migrations/`](migrations/README.md) | SQL versionado e idempotente |
| [`seeds/`](seeds/README.md) | Carga inicial (astronautas, base NASA, protocolos) |

## PRAGMAs obrigatórios (aplicados pela Central ao abrir)
`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`.

## Comandos
- `make db-migrate` e `make db-seed` (banco padrão `./var/edgespace.db`).
