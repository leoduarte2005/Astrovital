-- 1. Inventory: imported vs metadata-only vs synthetic.
SELECT * FROM v_dataset_inventory ORDER BY dataset_id;

-- 2. NASA EDA environmental coverage by mission and zone.
SELECT m.mission_code, e.zone, COUNT(*) AS rows,
       MIN(e.timestamp_utc) AS first_utc, MAX(e.timestamp_utc) AS last_utc,
       AVG(e.carbon_dioxide_ppm) AS mean_co2_ppm,
       MAX(e.carbon_dioxide_ppm) AS max_co2_ppm
FROM environmental_measurements e JOIN missions m USING(mission_id)
GROUP BY m.mission_code, e.zone ORDER BY m.mission_code, e.zone;

-- 3. Retrieve a reproducible environmental window (source values unchanged).
SELECT m.mission_code, timestamp_raw, zone, temperature_c,
       relative_humidity_percent, carbon_dioxide_ppm, quality_flags, source_record_ref
FROM environmental_measurements e JOIN missions m USING(mission_id)
WHERE m.mission_code='RR-1' AND zone='ISS_HARDWARE'
ORDER BY timestamp_raw LIMIT 25;

-- 4. NASA RadLab radiation dose-rate readings for the imported day.
SELECT timestamp_raw, instrument_id, value AS absorbed_dose_rate, unit,
       latitude_deg, longitude_deg, altitude_km, magnetic_b_nt, magnetic_l, source_record_ref
FROM radiation_measurements r JOIN datasets d USING(dataset_id)
WHERE d.accession='RADLAB-DOSTEL-2022-04-01'
  AND radiation_metric='ABSORBED_DOSE_RATE'
ORDER BY timestamp_raw LIMIT 100;

-- 5. Compare NASA EDA radiation daily series across mission labels.
SELECT m.mission_code, timestamp_raw, radiation_metric, value, unit
FROM radiation_measurements r JOIN missions m USING(mission_id)
JOIN datasets d USING(dataset_id)
WHERE d.accession='EDA-RADIATION'
ORDER BY m.mission_code, timestamp_raw, radiation_metric;

-- 6. Fictional check-ins only. The data_class predicate prevents source mixing.
SELECT s.subject_code, c.timestamp_utc, c.sleep_quality_1_5,
       c.fatigue_1_5, c.mood_1_5, c.pain_0_10, c.scenario
FROM synthetic_checkins c JOIN synthetic_subjects s USING(synthetic_subject_id)
WHERE c.data_class='SYNTHETIC'
ORDER BY s.subject_code, c.timestamp_utc;

-- 7. Officially described risks and their evidence/limits.
SELECT hazard, risk_name, description, monitoring_relevance, limitation
FROM risk_catalog ORDER BY hazard, risk_name;

-- 8. Validate that each raw record can be traced to source and import batch.
SELECT d.accession, b.batch_id, b.status, b.source_records,
       b.inserted_records, b.skipped_records, b.sha256, b.details
FROM import_batches b JOIN datasets d USING(dataset_id)
ORDER BY b.batch_id;

-- 9. Inspect units and limitations for every imported source field.
SELECT d.accession, f.source_field, f.canonical_name, f.unit,
       f.measurement_context, f.specification_status, f.notes
FROM dataset_fields f JOIN datasets d USING(dataset_id)
ORDER BY d.dataset_id, f.field_id;

-- 10. Public OSD-53 sample-level processed microarray values.
SELECT s.sample_accession, s.subject_label, s.organism, s.tissue,
       s.study_factor, g.feature_id, g.reported_value, g.value_scale
FROM gene_expression_measurements g
JOIN biomedical_samples s USING(sample_id)
JOIN datasets d USING(dataset_id)
WHERE d.accession='OSD-53'
ORDER BY s.sample_accession, g.feature_id LIMIT 100;

-- 11. Source-published OSD-53 preflight/postflight aggregate statistics.
SELECT feature_id, annotation_accession, mean_preflight, mean_postflight,
       fold_change_ratio, log2_ratio, f_test, p_value, adjusted_p_value
FROM differential_expression_results q JOIN datasets d USING(dataset_id)
WHERE d.accession='OSD-53'
ORDER BY adjusted_p_value LIMIT 100;

-- 12. ESA ISS physiology studies available in the public discovery catalog.
-- Metadata-only entries are not physiological observation values.
SELECT d.accession, c.contributing_agency, c.investigation_code,
       c.modalities, c.temporal_coverage, c.doi,
       c.observation_access_status, c.subject_nationality_status, c.access_note
FROM iss_physiology_study_catalog c JOIN datasets d USING(dataset_id)
WHERE c.platform='ISS'
ORDER BY c.contributing_agency, c.investigation_code;


-- 13. Article-level numeric aggregate values across the five requested domains.
SELECT p.citation, p.doi, p.article_url, a.domain, a.metric_code, a.metric_label,
       a.value, a.unit, a.statistic, a.dispersion_type, a.dispersion_value,
       a.dispersion_low, a.dispersion_high, a.sample_size, a.phase,
       a.posture, a.intervention, a.source_locator, a.p_value,
       a.interpretation_note
FROM published_physiology_aggregates a
JOIN physiology_publications p USING(publication_id)
ORDER BY a.domain, p.citation, a.metric_code, a.phase;

-- 14. Publication inventory and whether numeric values were transcribed.
SELECT citation, doi, article_url, subject, public_data_status, extraction_note
FROM physiology_publications ORDER BY citation;


-- 15. All missing cells with a standardized reason and source provenance.
SELECT table_name, record_pk, field_name, data_origin, quality_status,
       missing_reason, source_id, dataset_id, transformed_at, process_id, notes
FROM field_quality_events
WHERE quality_status='MISSING'
ORDER BY table_name, field_name, record_pk LIMIT 500;

-- 16. Completeness for returned source rows; temporal schedule completeness is separate.
SELECT d.accession, f.table_name, f.field_name, f.study_key, f.period_start, f.period_end, f.expected_count,
       f.observed_count, f.missing_count, f.completeness_pct,
       f.completeness_class, f.denominator_basis
FROM dataset_field_completeness f LEFT JOIN datasets d USING(dataset_id)
ORDER BY d.accession, f.field_name;

-- 17. Time spans and observed gaps. Expected counts are intentionally NULL
-- unless frequency and observation schedule are established by source metadata.
SELECT d.accession, t.series_key, t.first_observed_at, t.last_observed_at,
       t.row_count, t.distinct_timestamp_count, t.duplicate_timestamp_rows,
       t.max_observed_gap_seconds, t.gaps_over_1day,
       t.expected_frequency_seconds, t.expected_count, t.completeness_class,
       t.assessment_note
FROM temporal_coverage_summary t LEFT JOIN datasets d USING(dataset_id)
ORDER BY d.accession, t.series_key;

-- 18. Availability not yet verified is not the same as proven unavailable.
SELECT domain, field_name, availability_status, assessed_at, evidence_note
FROM field_availability_registry
ORDER BY domain, field_name;

-- 19. Excluded source rows and audit trail for derived fields.
SELECT d.accession, x.exclusion_count, x.reason_code, x.record_level_detail_available, x.notes
FROM source_row_exclusions x JOIN datasets d USING(dataset_id);
SELECT table_name, field_name, source_field_name, method_description,
       records_affected, source_id, dataset_id, transformed_at, process_id,
       original_preserved, notes FROM field_transformation_registry;
