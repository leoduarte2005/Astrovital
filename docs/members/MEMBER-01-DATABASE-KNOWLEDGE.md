# Membro 1 (Selliny) — Base Clínica NASA & Banco de Dados

**Pastas sob responsabilidade exclusiva:**
- `knowledge-base/` (`nasa_hrp_reports/`, `protocols/`, `datasets/`)
- `database/` (`space_health_sqlite/`, `tools/`, `tests/`)

---

## 1. Missão do Membro 1

Estruturar todo o conhecimento médico aeroespacial oficial da **NASA HRP (Human Research Program)** e **CSA**, modelar o banco local **SQLite (`WAL + FTS5`)** e fornecer os datasets de treino e *golden cases* usados pelo Membro 5 (Edge AI) e Membro 4 (Central Go).

---

## 2. Escopo Técnico Detalhado

### 2.1 Levantamento Clínico (`knowledge-base/nasa_hrp_reports/`)
Documentar em arquivos JSON/YAML validáveis os **5 Perigos Espaciais**, **11 Riscos Fisiológicos** e **8 Riscos Comportamentais/Bioquímicos**:

1. **Microgravidade & Fluid Shift:**
   - **SANS / VIIP** (edema de disco óptico, dobras coroidais, hipermetropia) $\rightarrow$ detecção via Grade de Amsler, ultrassom ocular (diâmetro da bainha do nervo óptico — ONSD) e PA; contramedidas: **Thigh Cuffs**, ajuste de CO2 cabinário e suplementação de **Complexo B** (folato/B12/B6 para via de 1-carbono).
   - Atrofia muscular e perda óssea $\rightarrow$ monitoramento em `MODE_COUNTERMEASURE_EXERCISE`.
2. **Radiação Espacial (GCR & SPE):**
   - Efeitos agudos e **CANS / CSA** com formação de **espécies reativas de oxigênio (ROS)** e estresse oxidativo $\rightarrow$ acionamento de `MODE_RADIATION_ALERT`, protocolo de **abrigo blindado** e suplementação antioxidante (**Vitaminas C e E**).
3. **Ambiente Fechado Hostil & Imunidade:**
   - Hipercapnia por acúmulo de $\text{CO}_2$ (`SCD40`), variações térmicas/barométricas (`BME280`).
   - Degradação do sono $\rightarrow$ aumento de **cortisol** e proteína C-reativa (**CRP**), favorecendo reativação de **vírus latentes** (EBV, VZV, CMV).
   - Contração do **volume plasmático** $\rightarrow$ hemoconcentração inicial / sobrecarga de ferro sérico e **anemia espacial** hemolítica; integração com o protocolo **Nutrition SMO**.
4. **Isolamento e Confinamento:**
   - Arquitetura do sono, **HRV**, humor e testes cognitivos curtos (PVT/gamificados) $\rightarrow$ protocolo de luz e ajuste de **ritmo circadiano**.
5. **Distância da Terra (Autonomia Médica):**
   - Protocolos guiados passo a passo (`knowledge-base/protocols/`): **coleta de sangue capilar / glicemia na ponta do dedo**, **Grade de Amsler**, **ultrassom point-of-care**, **pressão arterial** e **temperatura**.
   - Regras de escalonamento: **1) Autônomo local**, **2) Acionar outro tripulante**, **3) Store-and-Forward** (pacote assíncrono em fila para cirurgiões de voo na Terra).

### 2.2 Modelagem SQLite (`database/`)

A base de pesquisa disponível usa `database/space_health_sqlite/schema.sql`, com scripts em `scripts/`, consultas em `queries/` e testes em `database/tests/`. O [guia de integração](../../database/space_health_sqlite/docs/INTEGRATION.md) descreve construção, importação, auditoria e validação.

Os requisitos abaixo são para a futura base operacional `var/edgespace.db`, cujo schema e carga inicial ainda não foram implementados:

- Configurar obrigatoriamente na conexão operacional:
  - `PRAGMA journal_mode = WAL;`
  - `PRAGMA synchronous = NORMAL;`
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA busy_timeout = 5000;`
- Grupos de tabelas obrigatórios:
  1. `crew_profiles` e `crew_baselines` (dados antropométricos, particularidades clínicas, caminho para `baseline_ae_<crew_id>.onnx`, limiares individuais).
  2. `telemetry_timeseries` e `peripheral_readings` (séries compactas indexadas por `(crew_id, ts_us)`).
  3. `self_exams` e `chat_sessions` / `chat_messages` (histórico de autoexames e diálogos de consulta/calibração).
  4. `clinical_reports` + tabela virtual **`clinical_reports_fts` (`USING fts5`)** com triggers de sincronização para busca híbrida pelo Membro 5.
  5. `alerts_audit` e `store_and_forward_outbox` (pacotes clínicos pendentes de janela de comunicação com a Terra).

### 2.3 Datasets e Golden Cases (`knowledge-base/datasets/`)
- Séries sintéticas de CSI/vitais por `crew_id` (basal nominal vs. desvios).
- **Golden cases causais** para validar o motor do Membro 5:
  - Caso 1: Cefaleia + $\text{CO}_2 > 3500\text{ ppm}$ (`SCD40`) + Amsler normal $\rightarrow$ Hipercapnia ambiental.
  - Caso 2: Cefaleia + turvação visual + Amsler com metamorfopsia + $\text{CO}_2$ normal $\rightarrow$ Suspeita de **SANS/VIIP** (*Thigh Cuffs* + ultrassom ONSD + Complexo B).
  - Caso 3: Cefaleia + sono $< 5\text{ h}$ + HRV deprimido + baixa hidratação $\rightarrow$ Fadiga/desidratação + ajuste circadiano/Nutrition SMO.
  - Caso 4: Alerta solar + queda de HRV $\rightarrow$ `MODE_RADIATION_ALERT` + abrigo + Vitaminas C e E.

---

## 3. Entradas, Saídas e Critérios de Aceite

- **Consome:** `contracts/enums/` (códigos de subsistemas, modos de missão, níveis de severidade).
- **Entrega disponível para Leonardo (M4):** snapshot de pesquisa, schema e scripts em `database/space_health_sqlite/`; inventário com `make db-research-inventory`, validação com `make db-research-validate` e testes com `make db-research-test`. `make db-research-demo` cria uma demonstração offline separada, sem reconstruir as medições NASA do snapshot completo.
- **Entrega operacional pendente para Leonardo (M4):** schema e carga inicial idempotentes para `var/edgespace.db`.
- **Entrega para Rafael (M3):** textos e passos estruturados dos tutoriais (`knowledge-base/protocols/`).
- **Entrega para Santiago/Leonardo (M5):** base FTS5 populada + datasets + *golden cases* rotulados.
- **Critério de aceite operacional planejado:** banco sobe do zero em `< 2 s`, consulta `MATCH` no FTS5 retorna em `< 5 ms` na Orange Pi 4 Pro e cobre 100% dos 5 Perigos, 11 Riscos Fisiológicos e 8 Riscos Comportamentais/Bioquímicos. Esses critérios ainda não foram medidos na base operacional.
