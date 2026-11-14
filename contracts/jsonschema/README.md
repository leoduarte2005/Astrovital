# contracts/jsonschema/

**Responsável:** guardião Leonardo (M4); cada canal revisado pelos membros nas pontas.

## Propósito
JSON Schemas (draft 2020-12) de todas as mensagens.

## Organização esperada
| Subpasta | Canal | Pontas |
| :--- | :--- | :--- |
| `udp/` | UDP `:5005` | Nicolas/M2 (firmware) ↔ Leonardo/M4 (Central) |
| `ipc/` | TCP `127.0.0.1:5006`, frame = 4 bytes big-endian de tamanho + JSON | Leonardo/M4 ↔ Santiago/Leonardo/M5 (Edge AI) |
| `ws/` | WebSocket `:8000/ws` | Leonardo/M4 ↔ Rafael/M3 (painel) |
| `rest/` | HTTP `:8000/api/*` | Leonardo/M4 ↔ Rafael/M3 |

## Envelope comum (WS e IPC)
`{"v":1, "type":"<enum>", "ts_us":<int64>, "crew_id":"<string|null>", "payload":{...}}`

## Envelope UDP
Cabeçalho JSON compacto (`v`, `type`, `node_id`, `slot_id`, `mode`, `timestamp_us`, `peripherals`) e `csi_payload` (I/Q int8 em base64 ou bloco binário após o cabeçalho, conforme documentado no schema `udp/csi_frame`).

## Regras
- `additionalProperties: false` em payloads críticos.
- Unidades no nome do campo (`_us`, `_ppm`, `_bpm`, `_hpa`, `_pct`).
