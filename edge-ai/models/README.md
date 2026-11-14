# edge-ai/models/

**Responsável:** Santiago/Leonardo (M5). Baseline individual: `baseline_ae_<crew_id>.onnx` + `baseline_<crew_id>.json`.

## Propósito
Artefatos `.onnx` e metadados de normalização usados em inferência offline na Orange Pi 4 Pro.

## Arquivos esperados
| Arquivo | Função |
| :--- | :--- |
| `posture_cls.onnx` | Classificação de postura/locomoção (`MODE_CABIN_TOMOGRAPHY`) |
| `exercise_cadence.onnx` | Cadência e amplitude de treino resistivo (`MODE_COUNTERMEASURE_EXERCISE`) |
| `vitals_reg.onnx` | Estimativa refinada de FR/FC (`MODE_REST_VITALS`) |
| `baselines/baseline_ae_default.onnx` | Autoencoder basal genérico (fallback quando astronauta ainda não calibrado) |
| `baselines/baseline_ae_<crew_id>.onnx` | Autoencoder basal individual por astronauta |
| `baselines/baseline_<crew_id>.json` | Média/desvio por feature, limiares de anomalia, timestamp da última calibração |

## Regras
- Opset ONNX compatível com `onnxruntime` ARM64 instalado na estação.
- Cada modelo acompanhado de checksum SHA-256 e shape de entrada/saída documentado.
