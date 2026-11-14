# edge-ai/src/edgespace_ai/adaptation/

**Responsável:** Santiago/Leonardo (M5). Hot-swap de `baseline_ae_<crew_id>.onnx` por tripulante.

## Propósito
Adaptação individual por astronauta (`crew_id`): hot-swap de baseline ONNX, cálculo de desvio basal e atualização de calibração.

## Responsabilidades
- Manter cache das sessões `baseline_ae_<crew_id>.onnx` + parâmetros `baseline_<crew_id>.json`.
- Ao receber `SET_ACTIVE_CREW`: ativar baseline do `crew_id` em `< 300 ms` (ou `baseline_ae_default.onnx` com `calibration_required=true`) e responder `CREW_ACK`.
- Calcular `anomaly_score` (erro de reconstrução normalizado + z-score das features em relação ao basal individual).
- Durante o **Chatbot de Calibração** (`CALIBRATION_STEP`): validar se a janela está limpa e atualizar estatísticas individuais (EMA) devolvendo `CALIBRATION_FEEDBACK`.
