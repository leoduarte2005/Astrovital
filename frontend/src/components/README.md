# frontend/src/components/

**Responsável:** Rafael (M3).

## Propósito
Componentes de UI gerais.

## Componentes esperados
| Componente | Função |
| :--- | :--- |
| Layout tático | Grade principal (Twin, gráficos, chat, alertas) otimizada para toque |
| Seletor de astronauta | Lista `GET /api/crew`; envia `SET_CREW`; bloqueia UI até `CREW_STATE` |
| Barra de status | `crew_id` ativo, modo de missão, nós ativos, enlaces (20/12/6), `ai_ready` |
| Painel de alertas | Lista `ALERT_EVENT` por severidade e escalonamento |
| Tutoriais | Wizard passo a passo dos protocolos (capilar, Amsler interativo, ultrassom, PA, temperatura); envia `SELF_EXAM` |
| Overlay de radiação | Tela cheia em `MODE_RADIATION_ALERT` com instrução de abrigo |

## Entradas / Saídas
Estado do `store/`; ações disparadas via `store/`.
