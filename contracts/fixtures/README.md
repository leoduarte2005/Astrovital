# contracts/fixtures/

**Responsável:** guardião Leonardo (M4); todos podem propor fixtures via PR.

## Propósito
Exemplos concretos de mensagens para testes unitários e mocks em todos os módulos (Go, Python, TS, C host-tests).

## Convenção
- Espelhar estrutura de `jsonschema/`: `udp/`, `ipc/`, `ws/`, `rest/`.
- Nome: `<tipo>.valid.<caso>.json` e `<tipo>.invalid.<caso>.json`.
  - Ex.: `ws/chat_reply.valid.headache_co2.json`, `udp/cluster_sync.valid.failover_k4.json`.
- Cenários clínicos devem casar com golden cases de `knowledge-base/datasets/`.

## Uso
- Membro 3: alimenta store do painel sem backend.
- Membro 4: testes de (de)serialização dos structs Go.
- Membro 5: testes de DSP/correlação sem Central.
- `make contracts-validate` valida tudo contra os schemas.
