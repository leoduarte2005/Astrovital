# Membro 5 (Santiago / Leonardo) — Edge AI & Adaptação Individual por Astronauta

**Pasta sob responsabilidade exclusiva:** `edge-ai/` (`models/`, `training/`, `src/edgespace_ai/{dsp,inference,adaptation,correlation}`)

---

## 1. Missão

Worker Python local (`onnxruntime`, CPU ARM64) que recebe janelas CSI/I2C da Central via TCP `127.0.0.1:5006`, extrai sinais vitais/postura, detecta anomalias contra baseline individual (`crew_id`) e executa o motor de correlação causal com a base clínica NASA HRP/CSA.

---

## 2. Escopo Técnico

### 2.1 DSP RuView (`dsp/`)
- Adaptar `phase_sanitizer` e `csi_processor` do RuView para **1 antena por nó** (sem diferença de fase entre antenas):
  - unwrap de fase por subportadora
  - remoção de offset linear (CFO/SFO) por regressão sobre índice de subportadora
  - descarte de subportadoras nulas/piloto, filtro Hampel para outliers
  - normalização de amplitude por enlace
- Extração por janela: FFT/Welch banda respiratória $0.1\text{–}0.5\text{ Hz}$, banda cardíaca $0.8\text{–}2.5\text{ Hz}$, energia de movimento, variância Doppler para postura/exercício.
- Fusão dos 20 enlaces (ou 12/6 em failover) com peso por qualidade de sinal.
- Somente NumPy/SciPy. Sem PyTorch em runtime.

### 2.2 Inferência (`inference/`)
- Modelos `.onnx` em `models/`: `posture_cls.onnx`, `exercise_cadence.onnx`, `vitals_reg.onnx`.
- Sessões criadas uma vez no boot (`InferenceSession`, `intra_op_num_threads=2`).
- Saídas: postura, cadência, FR, FC estimada, confiança.

### 2.3 Adaptação por `crew_id` (`adaptation/`)
- Autoencoder basal por astronauta: `models/baselines/baseline_ae_<crew_id>.onnx` + `baseline_<crew_id>.json` (média/desvio de features, limiar de erro de reconstrução).
- `SET_ACTIVE_CREW`: carrega (ou usa cache LRU de sessões) e troca ponteiro atômico; responde ACK.
- Sem baseline: usa `baseline_ae_default.onnx` e marca `calibration_required=true`.
- Calibração via chatbot: acumula janelas limpas, atualiza estatísticas (EMA) e limiares; re-treino completo do AE só em `training/` (solo ou estação), nunca no loop de inferência.
- Isolation Forest (scikit-learn exportado via `skl2onnx`) como detector secundário.

### 2.4 Correlação causal (`correlation/`)
- Entrada `CHAT_CORRELATE_REQ`: texto do sintoma, `crew_id`, snapshot de sensores, histórico resumido.
- Etapas:
  1. Extração de sintomas (dicionário clínico local + regras; sem LLM em nuvem).
  2. Busca híbrida: FTS5 BM25 na tabela `clinical_reports_fts` (SQLite `mode=ro`) + reranqueamento por compatibilidade das assinaturas de sensores.
  3. Grafo causal leve (YAML em `knowledge-base/`): hipótese → evidências esperadas → peso. Pontuação bayesiana simples por evidência presente/ausente.
  4. Escolhe pergunta de desambiguação de maior ganho de informação (ex.: Amsler para separar SANS de CO2).
  5. Saída `CHAT_CORRELATE_RESP` com diferencial, evidências, contramedida, escalonamento e IDs de fonte.
- Validação com golden cases do Membro 1 (cefaleia/CO2, SANS, sono/desidratação, radiação).

### 2.5 Treino em solo (`training/`)
- Scripts de treino Teacher-Student (modelo grande offline destilado para ONNX pequeno) e autoencoders por astronauta. Executados fora do loop de missão; artefatos `.onnx` copiados para `models/`.

---

## 3. Entradas, Saídas, Aceite

- **Consome:**
  - IPC de Leonardo/M4: `CSI_WINDOW`, `PERIPHERAL_SNAPSHOT`, `SET_ACTIVE_CREW`, `CHAT_CORRELATE_REQ`
  - SQLite somente leitura (schema Selliny/M1)
  - Datasets de Selliny/M1 em `knowledge-base/datasets/`
  - Modelos base em `edge-ai/models/`
- **Produz:** IPC para Leonardo/M4: `AI_INFERENCE` (vitais, postura, anomaly score), `CREW_ACK`, `CHAT_CORRELATE_RESP`, `CALIBRATION_FEEDBACK`.
- **Proibido:** escrever no SQLite; acessar rede além de loopback; baixar modelos em runtime.
- **Aceite:** latência janela→inferência `< 50 ms`; hot-swap `< 300 ms`; RAM `< 400 MB`; 100% golden cases com hipótese correta no top-2.
