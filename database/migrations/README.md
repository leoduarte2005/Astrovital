# database/migrations/

**Responsável:** Selliny (M1). Revisão obrigatória: Leonardo (M4) impacto no writer, Santiago/Leonardo (M5) consultas FTS5.

## Propósito
Arquivos SQL aplicados em ordem lexicográfica: `NNNN_<descricao>.sql` (ex.: `0001_core.sql`).

## Grupos de tabelas esperados
| Grupo | Tabelas |
| :--- | :--- |
| Perfis | `crew_profiles`, `crew_baselines` (limiares, caminho `baseline_ae_<crew_id>.onnx`, versão) |
| Séries temporais | `telemetry_timeseries`, `peripheral_readings` (índice `(crew_id, ts_us)`) |
| Cluster | `nodes`, `cluster_events` (failover, mudanças de modo) |
| Interação | `self_exams`, `chat_sessions`, `chat_messages`, `calibration_runs` |
| Base clínica | `clinical_reports`, `clinical_reports_fts` (`USING fts5`, triggers de sincronização), `countermeasures`, `causal_edges` |
| Auditoria | `alerts_audit` (evidências, fonte, decisão, escalonamento) |
| Comunicação | `store_and_forward_outbox` (status, prioridade, janela de envio) |

## Regras
- Idempotente (`CREATE ... IF NOT EXISTS`); tabela `schema_version`.
- Nunca editar migration já mesclada; criar nova.
- Timestamps em `INTEGER` microssegundos (`ts_us`).
