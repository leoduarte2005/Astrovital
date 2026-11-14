# central/cmd/edgespace-central/

**Responsável:** Leonardo (M4).

## Propósito
Ponto de entrada do binário `edgespace-central`. Sem lógica de domínio: apenas lê configuração/flags, abre `store`, inicia pacotes internos em ordem e trata `SIGINT`/`SIGTERM` (para UDP, drena canais, faz checkpoint WAL).

## Flags esperadas
| Flag | Padrão | Descrição |
| :--- | :--- | :--- |
| `--db` | `./var/edgespace.db` | Caminho do SQLite WAL |
| `--udp-addr` | `:5005` | Porta UDP do cluster |
| `--ipc-addr` | `127.0.0.1:5006` | Endereço do worker Edge AI |
| `--http-addr` | `:8000` | Porta HTTP/WebSocket da UI |
| `--mock-cluster` | `false` | Ativa `internal/sim` no lugar de nós físicos |
| `--scenario` | `""` | Cenário inicial (`hypercapnia`, `sans`, `solar_storm`, `dehydration_sleep`, `node_loss`) |
