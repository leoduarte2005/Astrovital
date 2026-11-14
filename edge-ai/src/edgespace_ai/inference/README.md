# edge-ai/src/edgespace_ai/inference/

**Responsável:** Santiago/Leonardo (M5).

## Propósito
Wrappers de sessão `onnxruntime.InferenceSession` para os modelos de postura, exercício e sinais vitais.

## Entradas / Saídas
- Entrada: vetor de features vindo de `dsp/` + `mission_mode` atual.
- Saída: postura estimada, cadência/amplitude de exercício, FR/FC estimadas e intervalo de confiança.

## Regras
- Sessões ONNX inicializadas no boot (`CPUExecutionProvider`, `intra_op_num_threads=2`).
- Pré-alocar arrays NumPy `float32` de entrada para evitar alocações por frame.
