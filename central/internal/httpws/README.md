# central/internal/httpws/

**Responsável:** Leonardo (M4). Consumidor: Rafael (M3) em `frontend/`.

## Propósito
Servidor HTTP e WebSocket na porta `:8000`.

## Responsabilidades
- Servir assets compilados do `frontend/dist` embutidos via Go `embed` (`httpws/ui/`).
- Endpoints REST `/api/*`: lista de astronautas, séries temporais decimadas, protocolos de autoexame, fila Store-and-Forward, acionamento de cenários em modo dev.
- Hub WebSocket `/ws`: fan-out não bloqueante de `TELEMETRY_FRAME`, `ALERT_EVENT`, `CREW_STATE`, `CLUSTER_STATUS`, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`; recebe `SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP`.

## Regras
- Cliente WS lento nunca trava o hub (drop/disconnect com log).
- Zero headers apontando para CDNs; CSP restrita a `'self'`.
