# central/internal/session/

**Responsável:** Leonardo (M4). Gerencia `crew_id` ativo (hot-swap).

## Propósito
Gerenciador da sessão ativa multi-astronauta (`crew_id`), modo de missão e estado de calibração.

## Fluxo de Hot-Swap (`SET_CREW`)
1. Recebe pedido `SET_CREW` de `httpws/`.
2. Solicita flush de pendências do astronauta anterior ao `store/`.
3. Carrega `crew_profiles`, limiares individuais e resumo histórico do novo `crew_id`.
4. Envia `SET_ACTIVE_CREW` via `ipc/` e aguarda `CREW_ACK` (timeout 2 s).
5. Publica `CREW_STATE` em `httpws/` (com `ai_ready=true/false`).

## Outras funções
- Orquestra troca de modo de missão (`MODE_*`), notificando `cluster/`/`udp/` e UI.
- Anexa contexto clínico e últimas leituras de sensores ao `CHAT_CORRELATE_REQ` antes de enviar ao Edge AI.
