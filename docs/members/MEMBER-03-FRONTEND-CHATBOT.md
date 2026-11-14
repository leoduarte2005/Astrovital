# Membro 3 (Rafael) — Frontend Tablet/Monitor, Gráficos & Chatbot

**Pasta sob responsabilidade exclusiva:** `frontend/` (`public/`, `src/components/`, `src/scene/`, `src/chatbot/`, `src/charts/`, `src/store/`)

---

## 1. Missão

Painel tático **100% offline** (React + Vite + Three.js) servido pela Central em `:8000`, operado em tablet/monitor na cabine. Exibe estado do astronauta ativo, permite trocar tripulante, guia autoexames e conduz o **Chatbot de Calibração e Consulta Clínica**.

---

## 2. Escopo Técnico

### 2.1 Regras offline
- Zero CDN: fontes, ícones, `.glb`, decoder Draco (`public/draco/`) e libs empacotadas localmente.
- Build Vite com `base: './'`; saída copiada para `central/internal/httpws/ui/` (`make frontend-build`) e embutida via `embed` no binário Go.
- Dependências instaladas com cache npm local (`npm ci --offline`).
- Orçamento: bundle JS inicial `< 1.5 MB` gzip; 30 fps mínimo no tablet; modelo 3D `< 3 MB`.

### 2.2 Seletor de astronauta (`src/components/`)
- Lista via `GET /api/crew`. Seleção envia WS `SET_CREW {crew_id}`.
- UI só troca contexto após `CREW_STATE` de confirmação (evita mostrar dados do tripulante errado).
- Indicador permanente do `crew_id` ativo + estado do cluster (nós ativos, enlaces 20/12/6).

### 2.3 Digital Twin 3D (`src/scene/`)
- Corpo humano com 6 subsistemas coloridos Verde/Amarelo/Vermelho:
  1. Cardiovascular & Fluidos 2. Respiratório & Atmosfera 3. Neuro-Ocular (SANS) 4. Musculoesquelético & Postura 5. Imune, Hematológico & Nutricional 6. Neurocomportamental & Radiação
- Estado vindo de `TELEMETRY_FRAME.subsystems[]` e `ALERT_EVENT`. Frontend **não** calcula severidade; apenas renderiza.
- Toque no subsistema abre painel com valores atuais, tendência e recomendação.
- `MODE_RADIATION_ALERT`: overlay de abrigo em tela cheia.

### 2.4 Gráficos longitudinais (`src/charts/`)
- Séries por `crew_id` via `GET /api/crew/{crew_id}/timeseries?metric=&from=&to=&bucket=`.
- Métricas: FC, HRV, FR, SpO2, PA, CO2 cabine, sono, resultados Amsler/ultrassom/capilar.
- Eixo de missão (dia de missão, não só data) + faixa basal individual sombreada.
- Live append via WS; decimação no backend (bucket) para não travar o tablet.

### 2.5 Tutoriais passo a passo
- Conteúdo de `knowledge-base/protocols/` (Membro 1), servido via `GET /api/protocols/{id}`.
- Fluxos: coleta capilar (glicemia/sangue ponta do dedo), Grade de Amsler (teste interativo na tela, registro de áreas distorcidas), ultrassom point-of-care, PA, temperatura.
- Resultado enviado via WS `SELF_EXAM`.

### 2.6 Chatbot (`src/chatbot/`)
- **Modo Calibração:** script de passos (`CALIBRATION_STEP`) com timer, instrução e feedback de qualidade de sinal vindo da Central.
- **Modo Consulta:** texto livre `CHAT_MSG`; resposta `CHAT_REPLY` renderiza:
  - diferencial ranqueado com barra de confiança
  - evidências (sensor, valor, horário) e fonte NASA HRP/CSA
  - botões de ação rápida (abrir tutorial Amsler, iniciar PA, aceitar contramedida)
  - selo de escalonamento: LOCAL / CREW / STORE_AND_FORWARD
- Aviso fixo: recomendação de apoio, não diagnóstico.

### 2.7 Estado (`src/store/`)
- Store único reativo + cliente WS com reconexão exponencial, fila de saída durante desconexão, validação de `v` do envelope.
- Tipos TS gerados/espelhados de `contracts/jsonschema/ws/`.

---

## 3. Entradas, Saídas, Aceite

- **Consome:** WS `TELEMETRY_FRAME`, `ALERT_EVENT`, `CREW_STATE`, `CHAT_REPLY`, `CALIBRATION_FEEDBACK`, `CLUSTER_STATUS`; REST `/api/crew`, `/api/crew/{id}/timeseries`, `/api/protocols/{id}` de Leonardo (M4).
- **Produz:** WS `SET_CREW`, `CHAT_MSG`, `SELF_EXAM`, `CALIBRATION_STEP` para Leonardo (M4).
- **Desenvolve contra:** `make central-run-mock` (Leonardo/M4) e `contracts/fixtures/`.
- **Aceite:** funciona com cabo de rede desconectado da internet (DevTools sem requests externos); troca de astronauta `< 500 ms`; Twin reflete alerta `< 1 s` após evento.
