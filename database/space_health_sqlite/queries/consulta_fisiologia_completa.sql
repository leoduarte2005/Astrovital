-- Consulta somente leitura: todos os campos dos agregados e das publicacoes.
-- publication_id aparece uma unica vez, pois e a chave de relacionamento.
-- Cada linha representa um resultado agregado publicado, com seu contexto.
-- As ausencias ficam em JSON para manter uma linha por agregado.

WITH ausencias AS (
    SELECT record_pk,
           COUNT(*) AS campos_ausentes_documentados,
           json_group_array(json_object(
               'campo', field_name,
               'motivo', missing_reason,
               'origem', data_origin,
               'qualidade', quality_status,
               'fonte_id', source_id,
               'processo', process_id,
               'registrado_em', transformed_at,
               'observacao', notes
           )) AS detalhes_ausencias
    FROM field_quality_events
    WHERE table_name = 'published_physiology_aggregates'
      AND quality_status = 'MISSING'
    GROUP BY record_pk
)

SELECT
    a.aggregate_id AS id_registro,
    a.publication_id AS id_publicacao,
    a.domain AS codigo_dominio,
    CASE a.domain
        WHEN 'BLOOD_PRESSURE' THEN 'Pressão arterial'
        WHEN 'HEART_RATE' THEN 'Frequência cardíaca'
        WHEN 'CARDIOVASCULAR_RESPONSE' THEN 'Resposta cardiovascular'
        WHEN 'ORTHOSTATIC_INTOLERANCE' THEN 'Intolerância ortostática'
        WHEN 'BONE_HEALTH' THEN 'Saúde óssea'
    END AS dominio,
    COUNT(*) OVER (PARTITION BY a.domain) AS registros_no_dominio,
    COUNT(*) OVER () AS total_registros,

    a.metric_code AS codigo_metrica,
    a.metric_label AS descricao_metrica,
    a.value AS valor,
    a.unit AS unidade,
    a.statistic AS tipo_estatistica,
    a.dispersion_type AS tipo_dispersao,
    a.dispersion_value AS valor_dispersao,
    a.dispersion_low AS limite_inferior,
    a.dispersion_high AS limite_superior,
    a.p_value AS p_valor,

    a.sample_size AS tamanho_amostra,
    a.cohort AS grupo_estudado,
    a.phase AS fase_da_missao,
    a.posture AS postura_ou_condicao,
    a.intervention AS intervencao,
    a.source_locator AS local_no_artigo,
    a.interpretation_note AS nota_interpretacao,
    a.source_id AS id_fonte_resultado,
    a.data_origin AS origem_dado,
    a.quality_status AS qualidade_dado,
    fonte.name AS nome_fonte_resultado,
    fonte.url AS link_fonte_resultado,

    p.citation AS publicacao,
    p.doi,
    p.article_url AS link_artigo,
    p.subject AS tema_publicacao,
    p.public_data_status AS status_dados_publicados,
    p.extraction_note AS nota_extracao,
    p.accessed_at AS consulta_fonte_em,
    p.source_id AS id_fonte_publicacao,

    COALESCE(q.campos_ausentes_documentados, 0) AS campos_ausentes_documentados,
    COALESCE(q.detalhes_ausencias, '[]') AS detalhes_ausencias_json,

    CASE
        WHEN a.dispersion_type = 'SD' AND a.dispersion_value < 0
            THEN 'REVISAR_DESVIO_PADRAO_NEGATIVO'
        WHEN a.statistic = 'RANGE'
            THEN 'CONSULTAR_INTERVALO_E_NOTA'
        ELSE NULL
    END AS observacao_qualidade

FROM published_physiology_aggregates a
JOIN physiology_publications p
    ON p.publication_id = a.publication_id
LEFT JOIN data_sources fonte ON fonte.source_id = a.source_id
LEFT JOIN ausencias q ON q.record_pk = a.aggregate_id
WHERE a.domain IN (
    'BLOOD_PRESSURE',
    'HEART_RATE',
    'CARDIOVASCULAR_RESPONSE',
    'ORTHOSTATIC_INTOLERANCE',
    'BONE_HEALTH'
)
ORDER BY
    CASE a.domain
        WHEN 'BLOOD_PRESSURE' THEN 1
        WHEN 'HEART_RATE' THEN 2
        WHEN 'CARDIOVASCULAR_RESPONSE' THEN 3
        WHEN 'ORTHOSTATIC_INTOLERANCE' THEN 4
        WHEN 'BONE_HEALTH' THEN 5
    END,
    p.citation,
    a.metric_code,
    a.phase,
    a.posture,
    a.aggregate_id;
