# frontend/src/store/

**Responsável:** Rafael (M3). Conecta ao WebSocket `/ws` de Leonardo (M4).

## Propósito
Estado global reativo e cliente WebSocket.

## Responsabilidades
- Conexão WS `/ws` relativa à origem (sem host fixo), reconexão com backoff exponencial.
- Validação do envelope (`v`, `type`, `ts_us`, `crew_id`, `payload`); descarta mensagens de `crew_id` diferente do ativo.
- Fila de saída durante desconexão (`CHAT_MSG`, `SELF_EXAM`).
- Fatias de estado: `crew`, `cluster`, `telemetry`, `alerts`, `chat`, `calibration`.
- Modo mock: carrega `contracts/fixtures/ws/` quando backend ausente.

## Regras
- Tipos espelham `contracts/jsonschema/ws/`.
- Sem lógica clínica.
