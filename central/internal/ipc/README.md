# central/internal/ipc/

**Responsável:** Leonardo (M4). Conecta a Santiago/Leonardo (M5) em `127.0.0.1:5006`.

## Propósito
Cliente TCP para `127.0.0.1:5006` conectando a Central ao worker Python `edge-ai`.

## Protocolo
- Frames com prefixo de 4 bytes big-endian (tamanho uint32) + JSON conforme `contracts/jsonschema/ipc/`.
- Reconexão automática com backoff se o worker Python reiniciar.

## Mensagens
- Envia: `CSI_WINDOW`, `PERIPHERAL_SNAPSHOT`, `SET_ACTIVE_CREW`, `CHAT_CORRELATE_REQ`, `CALIBRATION_STEP`.
- Recebe: `AI_INFERENCE`, `CREW_ACK`, `CHAT_CORRELATE_RESP`, `CALIBRATION_FEEDBACK`.

## Regras
- Prioridade de fila: `SET_ACTIVE_CREW` e `CHAT_CORRELATE_REQ` furam fila de `CSI_WINDOW`.
- Se IPC cair, `session/` marca `ai_ready=false` e telemetria I2C + UI continuam operando.
