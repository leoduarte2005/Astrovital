-- EdgeSpace / Space Health: consultas somente leitura para o DBeaver.
-- Conexao: EdgeSpace - Pesquisa.
-- As series ambientais descrevem experimentos e controles em solo.
-- Os check-ins SIM-CREW sao ficticios. Os dados moleculares sao de pesquisa.
-- Os resultados fisiologicos publicados sao agregados por estudo/grupo.
-- NULL indica ausencia registrada; zero continua sendo um valor observado.

-- 1. Listar todas as tabelas do banco.
SELECT name AS tabela
FROM sqlite_master
WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
ORDER BY name;

-- 2. Conferir a quantidade de registros dos principais conjuntos.
SELECT 'Ambiente' AS conjunto, COUNT(*) AS registros FROM environmental_measurements
UNION ALL SELECT 'Radiacao', COUNT(*) FROM radiation_measurements
UNION ALL SELECT 'Amostras biologicas', COUNT(*) FROM biomedical_samples
UNION ALL SELECT 'Expressao genica', COUNT(*) FROM gene_expression_measurements
UNION ALL SELECT 'Resultados pre/pos-voo', COUNT(*) FROM differential_expression_results
UNION ALL SELECT 'Check-ins ficticios', COUNT(*) FROM synthetic_checkins
UNION ALL SELECT 'Catalogo de riscos', COUNT(*) FROM risk_catalog
UNION ALL SELECT 'Estudos ISS (metadados)', COUNT(*) FROM iss_physiology_study_catalog
UNION ALL SELECT 'Publicacoes de fisiologia', COUNT(*) FROM physiology_publications
UNION ALL SELECT 'Agregados fisiologicos publicados', COUNT(*) FROM published_physiology_aggregates
UNION ALL SELECT 'Eventos de qualidade por campo', COUNT(*) FROM field_quality_events;

-- 3. Fontes, classificacao e disponibilidade de cada dataset.
SELECT d.accession AS dataset, s.name AS fonte,
       d.data_kind AS classificacao, d.status,
       d.scope_note AS contexto
FROM datasets d
JOIN data_sources s ON s.source_id = d.source_id
ORDER BY d.dataset_id;

-- 4. Leituras ambientais do hardware da missao RR-1.
-- Troque o codigo da missao ou remova o LIMIT para ampliar a consulta.
SELECT m.mission_code AS missao, e.timestamp_utc AS data_utc,
       e.zone AS zona, e.temperature_c AS temperatura_c,
       e.relative_humidity_percent AS umidade_percentual,
       e.carbon_dioxide_ppm AS co2_ppm, e.quality_flags
FROM environmental_measurements e
JOIN missions m ON m.mission_id = e.mission_id
WHERE m.mission_code = 'RR-1' AND e.zone = 'ISS_HARDWARE'
ORDER BY e.timestamp_utc, e.measurement_id
LIMIT 100;

-- 5. Serie diaria de CO2: dados adequados para comparar as duas zonas em grafico.
-- AVG ignora NULL; leituras_co2 mostra quantos valores entram na media.
SELECT date(e.timestamp_utc) AS dia, e.zone AS zona,
       COUNT(e.carbon_dioxide_ppm) AS leituras_co2,
       ROUND(AVG(e.carbon_dioxide_ppm), 2) AS co2_medio_ppm,
       MAX(e.carbon_dioxide_ppm) AS co2_maximo_ppm
FROM environmental_measurements e
JOIN missions m ON m.mission_id = e.mission_id
WHERE m.mission_code = 'RR-1'
GROUP BY date(e.timestamp_utc), e.zone
ORDER BY dia, zona;

-- 6. Taxa de dose absorvida do RadLab; unidade preservada da fonte.
SELECT r.timestamp_utc AS data_utc, r.instrument_id AS instrumento,
       r.value AS taxa_dose_absorvida, r.unit AS unidade
FROM radiation_measurements r
JOIN datasets d ON d.dataset_id = r.dataset_id
WHERE d.accession = 'RADLAB-DOSTEL-2022-04-01'
  AND r.radiation_metric = 'ABSORBED_DOSE_RATE'
ORDER BY r.timestamp_utc, r.instrument_id, r.radiation_id
LIMIT 100;

-- 7. Cobertura da radiacao por dataset, metrica e unidade.
-- Nao combina dose, taxa de dose e fluxo de particulas.
SELECT d.accession AS dataset, r.radiation_metric AS metrica,
       r.unit AS unidade, COUNT(*) AS registros,
       MIN(r.timestamp_utc) AS inicio_utc,
       MAX(r.timestamp_utc) AS fim_utc
FROM radiation_measurements r
JOIN datasets d ON d.dataset_id = r.dataset_id
GROUP BY d.dataset_id, d.accession, r.radiation_metric, r.unit
ORDER BY dataset, metrica;

-- 8. Todos os 90 check-ins dos perfis ficticios.
SELECT s.subject_code AS perfil_ficticio, c.timestamp_utc AS data_utc,
       c.sleep_quality_1_5 AS sono_1_a_5,
       c.fatigue_1_5 AS fadiga_1_a_5,
       c.mood_1_5 AS humor_1_a_5,
       c.pain_0_10 AS dor_0_a_10, c.scenario AS cenario
FROM synthetic_checkins c
JOIN synthetic_subjects s ON s.synthetic_subject_id = c.synthetic_subject_id
WHERE c.data_class = 'SYNTHETIC'
ORDER BY perfil_ficticio, data_utc;

-- 9. Valores processados de expressao genica por amostra OSD-53.
-- Os valores permanecem na escala publicada; nao representam sinais vitais.
SELECT s.sample_accession AS amostra, s.subject_label AS alias_publico,
       s.study_factor AS grupo, g.feature_id,
       g.reported_value AS valor_publicado, g.value_scale AS escala
FROM gene_expression_measurements g
JOIN biomedical_samples s ON s.sample_id = g.sample_id
JOIN datasets d ON d.dataset_id = g.dataset_id
WHERE d.accession = 'OSD-53'
ORDER BY amostra, g.feature_id
LIMIT 100;

-- 10. Todos os 243 resultados agregados pre/pos-voo de OSD-53.
-- Estatisticas publicadas pela fonte, sem aplicar limiar clinico.
SELECT q.feature_id, q.mean_preflight AS media_pre_voo,
       q.mean_postflight AS media_pos_voo, q.fold_change_ratio,
       q.log2_ratio, q.p_value, q.adjusted_p_value
FROM differential_expression_results q
JOIN datasets d ON d.dataset_id = q.dataset_id
WHERE d.accession = 'OSD-53'
ORDER BY q.adjusted_p_value IS NULL, q.adjusted_p_value, q.feature_id;

-- 11. Catalogo de riscos com referencia e limites de interpretacao.
SELECT r.hazard AS perigo, r.risk_name AS risco,
       r.description AS descricao, r.limitation AS limitacao,
       s.url AS referencia
FROM risk_catalog r
JOIN scientific_references s ON s.reference_id = r.reference_id
ORDER BY perigo, risco;

-- 12. Dicionario de variaveis, unidades e contexto de medicao.
SELECT d.accession AS dataset, f.canonical_name AS variavel,
       f.unit AS unidade, f.measurement_context AS contexto,
       f.specification_status AS especificacao, f.notes AS observacoes
FROM dataset_fields f
JOIN datasets d ON d.dataset_id = f.dataset_id
ORDER BY dataset, f.field_id;

-- 13. Estudos de fisiologia da ISS no catalogo ESA/HREDA.
-- Sao metadados de estudos; observation_access_status explicita o acesso aos valores.
SELECT d.accession AS dataset, c.investigation_code AS estudo,
       c.contributing_agency AS agencia, c.platform AS plataforma,
       c.modalities AS modalidades, c.temporal_coverage AS periodo,
       c.doi, c.source_url AS fonte,
       c.observation_access_status AS acesso_as_observacoes,
       c.subject_nationality_status AS nacionalidade_na_fonte,
       c.access_note AS observacoes
FROM iss_physiology_study_catalog c
JOIN datasets d ON d.dataset_id = c.dataset_id
WHERE c.platform = 'ISS'
ORDER BY agencia, estudo;

-- 14. Publicacoes e quantidade de resultados transcritos por artigo.
SELECT p.citation AS publicacao, p.doi, p.article_url AS fonte,
       p.subject AS tema, p.public_data_status AS status,
       COUNT(a.aggregate_id) AS agregados, p.extraction_note AS nota_extracao
FROM physiology_publications p
LEFT JOIN published_physiology_aggregates a ON a.publication_id = p.publication_id
GROUP BY p.publication_id
ORDER BY publicacao;

-- 15. Todos os resultados fisiologicos publicados, com estatistica e contexto.
-- RANGE preserva os extremos; consulte a nota antes de interpretar value.
SELECT p.citation AS publicacao, p.doi,
       a.domain AS dominio, a.metric_code AS metrica,
       a.metric_label AS descricao, a.value AS valor,
       a.unit AS unidade, a.statistic AS estatistica,
       a.dispersion_type AS tipo_dispersao,
       a.dispersion_value AS dispersao,
       a.dispersion_low AS limite_inferior,
       a.dispersion_high AS limite_superior,
       a.sample_size AS tamanho_amostra, a.cohort AS grupo,
       a.phase AS fase, a.posture AS postura, a.intervention AS intervencao,
       a.source_locator AS local_no_artigo, a.p_value,
       CASE WHEN a.dispersion_type = 'SD' AND a.dispersion_value < 0
            THEN 'REVISAR_SD_NEGATIVO'
            WHEN a.statistic = 'RANGE' THEN 'CONSULTAR_INTERVALO_E_NOTA'
            ELSE 'SEM_ALERTA_ESTRUTURAL' END AS revisao,
       a.interpretation_note AS nota_interpretacao,
       a.data_origin AS origem_dado, a.quality_status AS qualidade_dado,
       a.source_id AS id_fonte,
       p.article_url AS fonte
FROM published_physiology_aggregates a
JOIN physiology_publications p ON p.publication_id = a.publication_id
ORDER BY dominio, metrica, publicacao, fase, postura;

-- 16. Cobertura do corpus, mantendo separadas metricas, unidades e estatisticas.
SELECT domain AS dominio, metric_code AS metrica, unit AS unidade,
       statistic AS estatistica, COUNT(*) AS agregados,
       COUNT(DISTINCT publication_id) AS publicacoes
FROM published_physiology_aggregates
GROUP BY domain, metric_code, unit, statistic
ORDER BY dominio, metrica, unidade, estatistica;

-- 17. Dispersoes negativas na transcricao: valores preservados para revisao.
SELECT a.aggregate_id, p.citation AS publicacao, p.doi,
       a.metric_code AS metrica, a.value AS valor,
       a.dispersion_value AS desvio_padrao, a.unit AS unidade,
       a.source_locator AS local_no_artigo
FROM published_physiology_aggregates a
JOIN physiology_publications p ON p.publication_id = a.publication_id
WHERE a.dispersion_type = 'SD' AND a.dispersion_value < 0
ORDER BY a.aggregate_id;

-- 18. Motivos de ausencia e regras de tratamento.
SELECT reason_code AS motivo, description AS descricao,
       is_missing AS representa_ausencia, handling_rule AS tratamento
FROM missing_reason_codes
ORDER BY reason_code;

-- 19. Quantidade de ausencias por tabela, campo e motivo.
SELECT table_name AS tabela, field_name AS campo,
       missing_reason AS motivo, COUNT(*) AS celulas,
       COUNT(DISTINCT record_pk) AS registros
FROM field_quality_events
WHERE quality_status = 'MISSING'
GROUP BY table_name, field_name, missing_reason
ORDER BY tabela, campo, motivo;

-- 20. Completude das celulas; o denominador nao representa cobertura temporal.
SELECT d.accession AS dataset, f.table_name AS tabela,
       f.field_name AS campo, f.study_key AS estudo,
       f.period_start AS inicio, f.period_end AS fim,
       f.expected_count AS denominador,
       f.observed_count AS disponiveis, f.missing_count AS ausentes,
       f.completeness_pct AS completude_percentual,
       f.completeness_class AS classe,
       f.denominator_basis AS base_denominador
FROM dataset_field_completeness f
LEFT JOIN datasets d ON d.dataset_id = f.dataset_id
ORDER BY dataset, campo, estudo, inicio;

-- 21. Cobertura e intervalos observados, sem inferir amostras nao observadas.
SELECT d.accession AS dataset, t.series_key AS serie,
       t.first_observed_at AS primeiro_timestamp,
       t.last_observed_at AS ultimo_timestamp,
       t.row_count AS linhas, t.distinct_timestamp_count AS timestamps_distintos,
       t.duplicate_timestamp_rows AS linhas_com_timestamp_repetido,
       t.max_observed_gap_seconds AS maior_intervalo_segundos,
       t.gaps_over_1day AS intervalos_acima_de_um_dia,
       t.expected_frequency_seconds AS frequencia_esperada_segundos,
       t.expected_count AS quantidade_esperada,
       t.completeness_pct AS completude_temporal,
       t.completeness_class AS classe, t.assessment_note AS observacao
FROM temporal_coverage_summary t
LEFT JOIN datasets d ON d.dataset_id = t.dataset_id
ORDER BY dataset, serie;

-- 22. Linhas ambientais preservadas com todos os valores numericos ausentes.
SELECT m.mission_code AS missao, e.timestamp_raw AS data_original,
       e.timestamp_utc AS data_utc, e.zone AS zona,
       e.temperature_c AS temperatura_c,
       e.relative_humidity_percent AS umidade,
       e.carbon_dioxide_ppm AS co2_ppm,
       e.source_record_ref AS referencia_registro, e.quality_flags
FROM environmental_measurements e
JOIN missions m ON m.mission_id = e.mission_id
WHERE e.temperature_c IS NULL
  AND e.relative_humidity_percent IS NULL
  AND e.carbon_dioxide_ppm IS NULL
ORDER BY e.measurement_id
LIMIT 100;

-- 23. Categorias cuja disponibilidade ainda nao foi verificada.
SELECT domain AS dominio, field_name AS campo,
       availability_status AS disponibilidade,
       assessed_at AS avaliado_em, evidence_note AS evidencia
FROM field_availability_registry
ORDER BY dominio, campo;

-- 24. Transformacoes derivadas com o texto original preservado.
SELECT table_name AS tabela, field_name AS campo,
       source_field_name AS campo_original,
       method_description AS metodo, records_affected AS registros,
       data_origin AS origem, original_preserved AS original_preservado,
       transformed_at AS registrado_em, process_id AS processo
FROM field_transformation_registry
ORDER BY tabela, campo;
