# edge-ai/src/edgespace_ai/correlation/

**Responsável:** Santiago/Leonardo (M5). Base clínica + golden cases: Selliny (M1).

## Propósito
Motor de correlação causal que cruza sintomas relatados no Chatbot com telemetria dos ESP32-S3, histórico individual do `crew_id` e a base clínica NASA HRP/CSA.

## Pipeline (`CHAT_CORRELATE_REQ` → `CHAT_CORRELATE_RESP`)
1. Extração de sintomas e duração a partir do texto do astronauta (vocabulário clínico local PT/EN).
2. Avaliação das evidências físicas em tempo real:
   - Ambiente: `SCD40` ($\text{CO}_2$), `BME280` (T/UR/pressão).
   - Fisiologia/SANS: PA, SpO2/FC (`MAX30102`), FR/HRV/sono (CSI), `anomaly_score` individual, autoexames recentes (Grade de Amsler, ultrassom ONSD, sangue capilar).
3. Busca híbrida no SQLite (`mode=ro`): `MATCH` BM25 em `clinical_reports_fts` + pontuação pelas arestas causais (`causal_edges`).
4. Seleção de:
   - diferencial ranqueado com confiança e evidências citadas (sensor, valor, ID da fonte NASA HRP/CSA)
   - pergunta de desambiguação de maior ganho de informação
   - contramedida exata e nível de escalonamento (`LOCAL` / `CREW` / `STORE_AND_FORWARD`).

## Regras
- Nunca abrir SQLite com permissão de escrita.
- Saída é sempre recomendação fundamentada, nunca diagnóstico definitivo.
