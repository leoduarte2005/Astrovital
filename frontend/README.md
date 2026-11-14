# frontend/ — Painel Tablet/Monitor 100% Offline

**Responsável:** Rafael (M3). Guia: [`docs/members/MEMBER-03-FRONTEND-CHATBOT.md`](../docs/members/MEMBER-03-FRONTEND-CHATBOT.md)

## Propósito
SPA React + Vite + Three.js servida pela Leonardo (M4) em `http://<orange-pi>:8000`. Seletor de astronauta, Digital Twin 3D, gráficos longitudinais, tutoriais e Chatbot de Calibração/Consulta.

## Estrutura
| Pasta | Conteúdo |
| :--- | :--- |
| [`public/`](public/README.md) | Assets locais (`.glb`, Draco, fontes, imagens de tutoriais de Selliny/M1) |
| [`src/components/`](src/components/README.md) | Layout, seletor de astronauta, tutoriais, status do cluster |
| [`src/scene/`](src/scene/README.md) | Digital Twin 3D (6 subsistemas) |
| [`src/chatbot/`](src/chatbot/README.md) | Chatbot de calibração e consulta clínica (motor de Leonardo/M4 + Santiago/Leonardo/M5) |
| [`src/charts/`](src/charts/README.md) | Gráficos longitudinais por astronauta |
| [`src/store/`](src/store/README.md) | Estado reativo + cliente WebSocket para Leonardo (M4) em `:8000` |

## Entradas / Saídas
- Consome WS `/ws` e REST `/api/*` de Leonardo/M4 (`contracts/jsonschema/ws`, `rest`).
- Produz `SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP` para Leonardo/M4.
- Build: `make frontend-build` copia `dist/` para `central/internal/httpws/ui/` de Leonardo/M4.

## Regras
- Zero CDN, zero fonte externa, zero analytics.
- Frontend não calcula severidade clínica; só renderiza o que a Central envia.
- Desenvolvimento contra `make central-run-mock` ou `contracts/fixtures/`.
