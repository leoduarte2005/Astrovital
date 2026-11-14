# edge-ai/training/

**Responsável:** Santiago/Leonardo (M5). Dados de entrada: `knowledge-base/datasets/` (Selliny/M1).

## Propósito
Scripts executados **fora do loop de tempo real** (em solo ou janela de manutenção) para treinar e exportar modelos `.onnx` para `edge-ai/models/`.

## Pipelines esperados
1. **Teacher-Student:** destila modelos maiores de postura/exercício/vitais em redes leves exportadas para ONNX.
2. **Autoencoder Basal (`baseline_ae_<crew_id>.onnx`):** treina sobre janelas nominais de um astronauta e grava o `.onnx` + `.json` de normalização.
3. **Isolation Forest (`skl2onnx`):** detector complementar de anomalias multivariadas.
4. **Avaliador de Golden Cases:** roda os casos de `knowledge-base/datasets/golden_cases/` contra `correlation/` e gera relatório de acurácia.

## Regras
- Nenhum módulo de `src/edgespace_ai/` importa `training/`.
- Fixar seeds aleatórias para reprodutibilidade.
