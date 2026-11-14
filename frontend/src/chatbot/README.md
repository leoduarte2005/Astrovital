# frontend/src/chatbot/

**Responsável UI:** Rafael (M3). Lógica clínica: Santiago/Leonardo (M5) via Leonardo (M4) em `:8000`.

## Propósito
Interface conversacional com dois modos.

### Modo Calibração
- Script de passos (`CALIBRATION_STEP`): repouso sentado, respiração lenta, postura em pé, exercício leve.
- Mostra timer, instrução e qualidade de sinal (`CALIBRATION_FEEDBACK`).

### Modo Consulta Clínica
- Relato livre (`CHAT_MSG`); resposta `CHAT_REPLY` com:
  - diferencial ranqueado e confiança
  - evidências (sensor, valor, horário) e fonte NASA HRP/CSA
  - pergunta de desambiguação com botão de ação (abrir Amsler, medir PA)
  - contramedida e selo `LOCAL` / `CREW` / `STORE_AND_FORWARD`

## Regras
- Nenhuma inferência no navegador; toda lógica vem da Central/Edge AI.
- Histórico por `crew_id`; troca de astronauta limpa a sessão visível.
- Aviso fixo: apoio à decisão, não diagnóstico.
