# edge-ai/src/edgespace_ai/

**Responsável:** Santiago/Leonardo (M5).

## Propósito
Pacote principal do worker IA. Abre servidor TCP em `127.0.0.1:5006`, processa frames da Central e devolve inferências e correlações causais.

## Submódulos
| Pasta | Função |
| :--- | :--- |
| [`dsp/`](dsp/README.md) | Sanitização de fase RuView (1 antena) e extração espectral FFT |
| [`inference/`](inference/README.md) | Execução dos modelos ONNX de postura, exercício e vitais |
| [`adaptation/`](adaptation/README.md) | Hot-swap de `baseline_ae_<crew_id>.onnx`, calibração e score de anomalia |
| [`correlation/`](correlation/README.md) | Motor de correlação causal (sintomas + ESPs + FTS5 NASA HRP/CSA) |

## Entradas / Saídas
Protocolo IPC definido em `contracts/jsonschema/ipc/`.
