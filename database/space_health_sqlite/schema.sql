PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_sources (
    source_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    organization TEXT NOT NULL,
    url TEXT NOT NULL,
    accessed_at TEXT,
    access_mode TEXT NOT NULL,
    license_note TEXT,
    scope_note TEXT
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(source_id),
    accession TEXT,
    title TEXT NOT NULL,
    data_kind TEXT NOT NULL CHECK(data_kind IN ('REAL','REFERENCE','SYNTHETIC','CATALOG')),
    scope_note TEXT,
    format_note TEXT,
    status TEXT NOT NULL CHECK(status IN ('IMPORTED','METADATA_ONLY','GENERATED','NOT_IMPORTED')),
    license_note TEXT,
    sha256 TEXT,
    UNIQUE(source_id, accession, title)
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUCCESS','PARTIAL','FAILED')),
    source_records INTEGER NOT NULL DEFAULT 0,
    inserted_records INTEGER NOT NULL DEFAULT 0,
    skipped_records INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER REFERENCES import_batches(batch_id),
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    media_type TEXT,
    sha256 TEXT NOT NULL,
    content_gzip BLOB NOT NULL,
    byte_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS missions (
    mission_id INTEGER PRIMARY KEY,
    mission_code TEXT NOT NULL UNIQUE,
    mission_name TEXT,
    program TEXT,
    context_note TEXT
);

CREATE TABLE IF NOT EXISTS scientific_references (
    reference_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(source_id),
    citation TEXT NOT NULL,
    url TEXT NOT NULL,
    published_or_updated TEXT,
    accessed_at TEXT,
    evidence_scope TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS dataset_fields (
    field_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    source_field TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    value_type TEXT NOT NULL,
    unit TEXT,
    measurement_context TEXT NOT NULL,
    specification_status TEXT NOT NULL,
    notes TEXT,
    UNIQUE(dataset_id, source_field)
);

CREATE TABLE IF NOT EXISTS risk_catalog (
    risk_id INTEGER PRIMARY KEY,
    hazard TEXT NOT NULL,
    risk_name TEXT NOT NULL,
    description TEXT NOT NULL,
    scope_note TEXT NOT NULL,
    monitoring_relevance TEXT,
    limitation TEXT NOT NULL,
    reference_id INTEGER NOT NULL REFERENCES scientific_references(reference_id),
    UNIQUE(hazard, risk_name)
);

CREATE TABLE IF NOT EXISTS environmental_measurements (
    measurement_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id),
    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
    timestamp_raw TEXT NOT NULL,
    timestamp_utc TEXT,
    zone TEXT NOT NULL CHECK(zone IN ('ISS_HARDWARE','GROUND_CONTROL')),
    temperature_c REAL,
    relative_humidity_percent REAL,
    carbon_dioxide_ppm REAL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class='REAL'),
    source_record_ref TEXT NOT NULL,
    quality_flags TEXT,
    UNIQUE(dataset_id, source_record_ref)
);

CREATE TABLE IF NOT EXISTS radiation_measurements (
    radiation_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id),
    mission_id INTEGER REFERENCES missions(mission_id),
    timestamp_raw TEXT NOT NULL,
    timestamp_utc TEXT,
    instrument_id TEXT,
    spacecraft TEXT,
    radiation_metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    module TEXT,
    latitude_deg REAL,
    longitude_deg REAL,
    altitude_km REAL,
    magnetic_b_nt REAL,
    magnetic_l REAL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class='REAL'),
    source_record_ref TEXT NOT NULL,
    quality_flags TEXT
);

CREATE TABLE IF NOT EXISTS synthetic_subjects (
    synthetic_subject_id INTEGER PRIMARY KEY,
    subject_code TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id)
);

CREATE TABLE IF NOT EXISTS biomedical_samples (
    sample_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    sample_accession TEXT NOT NULL,
    subject_label TEXT,
    organism TEXT,
    tissue TEXT,
    study_factor TEXT,
    source_record_ref TEXT NOT NULL,
    UNIQUE(dataset_id, sample_accession)
);

CREATE TABLE IF NOT EXISTS gene_expression_measurements (
    expression_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id),
    sample_id INTEGER NOT NULL REFERENCES biomedical_samples(sample_id),
    feature_id TEXT NOT NULL,
    reported_value REAL,
    value_scale TEXT NOT NULL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class='REAL'),
    source_record_ref TEXT NOT NULL,
    UNIQUE(dataset_id, sample_id, feature_id)
);

CREATE TABLE IF NOT EXISTS differential_expression_results (
    result_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id),
    feature_id TEXT NOT NULL,
    annotation_accession TEXT,
    mean_preflight REAL,
    mean_postflight REAL,
    fold_change_ratio REAL,
    log2_ratio REAL,
    f_test REAL,
    p_value REAL,
    adjusted_p_value REAL,
    comparison TEXT NOT NULL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class='REAL'),
    source_record_ref TEXT NOT NULL,
    UNIQUE(dataset_id, feature_id, comparison)
);

CREATE TABLE IF NOT EXISTS synthetic_checkins (
    checkin_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id),
    synthetic_subject_id INTEGER NOT NULL REFERENCES synthetic_subjects(synthetic_subject_id),
    timestamp_utc TEXT NOT NULL,
    sleep_quality_1_5 INTEGER NOT NULL CHECK(sleep_quality_1_5 BETWEEN 1 AND 5),
    fatigue_1_5 INTEGER NOT NULL CHECK(fatigue_1_5 BETWEEN 1 AND 5),
    mood_1_5 INTEGER NOT NULL CHECK(mood_1_5 BETWEEN 1 AND 5),
    pain_0_10 INTEGER NOT NULL CHECK(pain_0_10 BETWEEN 0 AND 10),
    scenario TEXT NOT NULL,
    data_class TEXT NOT NULL DEFAULT 'SYNTHETIC' CHECK(data_class='SYNTHETIC'),
    generation_seed INTEGER NOT NULL,
    limitation TEXT NOT NULL,
    UNIQUE(synthetic_subject_id, timestamp_utc)
);

CREATE TABLE IF NOT EXISTS reference_parameters (
    parameter_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id),
    reference_id INTEGER NOT NULL REFERENCES scientific_references(reference_id),
    parameter_name TEXT NOT NULL,
    value_text TEXT,
    unit TEXT,
    population_or_context TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    limitation TEXT NOT NULL
);

-- Study-level catalog for public ISS physiology datasets whose source pages
-- expose discovery metadata but not reusable subject-level observation files.
-- This deliberately keeps catalog records separate from measurements.
CREATE TABLE IF NOT EXISTS iss_physiology_study_catalog (
    catalog_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL UNIQUE REFERENCES datasets(dataset_id),
    platform TEXT NOT NULL,
    contributing_agency TEXT NOT NULL,
    investigation_code TEXT NOT NULL,
    modalities TEXT NOT NULL,
    temporal_coverage TEXT,
    doi TEXT,
    source_url TEXT NOT NULL,
    observation_access_status TEXT NOT NULL CHECK(observation_access_status IN ('PUBLIC_VALUES_IMPORTED','METADATA_ONLY','ACCESS_RESTRICTED','UNVERIFIED')),
    access_note TEXT NOT NULL,
    subject_nationality_status TEXT NOT NULL DEFAULT 'NOT_REPORTED_IN_SOURCE'
        CHECK(subject_nationality_status IN ('REPORTED','NOT_REPORTED_IN_SOURCE','NOT_APPLICABLE'))
);

-- Public numeric results transcribed from scientific articles. These are study/group aggregates,
-- never synthetic data and never invented subject-level records.
CREATE TABLE IF NOT EXISTS physiology_publications (
    publication_id INTEGER PRIMARY KEY,
    citation TEXT NOT NULL UNIQUE,
    doi TEXT,
    article_url TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    public_data_status TEXT NOT NULL CHECK(public_data_status IN ('AGGREGATES_IMPORTED','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','METADATA_ONLY')),
    extraction_note TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    source_id INTEGER REFERENCES data_sources(source_id)
);
CREATE TABLE IF NOT EXISTS published_physiology_aggregates (
    aggregate_id INTEGER PRIMARY KEY,
    publication_id INTEGER NOT NULL REFERENCES physiology_publications(publication_id),
    domain TEXT NOT NULL CHECK(domain IN ('BLOOD_PRESSURE','HEART_RATE','CARDIOVASCULAR_RESPONSE','ORTHOSTATIC_INTOLERANCE','BONE_HEALTH')),
    metric_code TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    statistic TEXT NOT NULL,
    dispersion_type TEXT,
    dispersion_value REAL,
    dispersion_low REAL,
    dispersion_high REAL,
    sample_size INTEGER,
    cohort TEXT,
    phase TEXT,
    posture TEXT,
    intervention TEXT,
    source_locator TEXT NOT NULL,
    p_value TEXT,
    interpretation_note TEXT,
    source_id INTEGER REFERENCES data_sources(source_id),
    data_origin TEXT NOT NULL DEFAULT 'REAL' CHECK(data_origin IN ('REAL','IMPUTED','DERIVED','SYNTHETIC')),
    quality_status TEXT NOT NULL DEFAULT 'OBSERVED' CHECK(quality_status IN ('OBSERVED','MISSING','IMPUTED','DERIVED','SYNTHETIC','BELOW_DETECTION_LIMIT','REJECTED')),
    UNIQUE(publication_id, metric_code, phase, posture, intervention, source_locator)
);
CREATE INDEX IF NOT EXISTS idx_pubphys_domain_metric ON published_physiology_aggregates(domain, metric_code);
CREATE INDEX IF NOT EXISTS idx_pubphys_publication ON published_physiology_aggregates(publication_id);


CREATE TABLE IF NOT EXISTS missing_reason_codes (
    reason_code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    is_missing INTEGER NOT NULL CHECK(is_missing IN (0,1)),
    handling_rule TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_quality_events (
    event_id INTEGER PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_pk INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    data_origin TEXT NOT NULL CHECK(data_origin IN ('REAL','IMPUTED','DERIVED','SYNTHETIC')),
    quality_status TEXT NOT NULL CHECK(quality_status IN ('OBSERVED','MISSING','IMPUTED','DERIVED','SYNTHETIC','BELOW_DETECTION_LIMIT','REJECTED')),
    missing_reason TEXT REFERENCES missing_reason_codes(reason_code),
    original_value_text TEXT,
    imputation_method TEXT,
    source_id INTEGER REFERENCES data_sources(source_id),
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    reference_id INTEGER REFERENCES scientific_references(reference_id),
    transformed_at TEXT,
    process_id TEXT,
    notes TEXT,
    UNIQUE(table_name,record_pk,field_name),
    CHECK((quality_status='MISSING' AND missing_reason IS NOT NULL) OR quality_status!='MISSING'),
    CHECK(quality_status!='IMPUTED' OR imputation_method IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS dataset_field_completeness (
    summary_id INTEGER PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    source_id INTEGER REFERENCES data_sources(source_id),
    table_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    study_key TEXT,
    period_start TEXT,
    period_end TEXT,
    expected_count INTEGER,
    observed_count INTEGER NOT NULL,
    missing_count INTEGER NOT NULL,
    completeness_pct REAL,
    completeness_class TEXT CHECK(completeness_class IN ('HIGH','MODERATE','LOW','CRITICAL','NOT_ASSESSABLE')),
    denominator_basis TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    UNIQUE(dataset_id,table_name,field_name,study_key,period_start,period_end)
);
CREATE TABLE IF NOT EXISTS source_row_exclusions (
    exclusion_id INTEGER PRIMARY KEY,
    batch_id INTEGER REFERENCES import_batches(batch_id),
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    source_id INTEGER REFERENCES data_sources(source_id),
    exclusion_count INTEGER NOT NULL,
    reason_code TEXT NOT NULL REFERENCES missing_reason_codes(reason_code),
    record_level_detail_available INTEGER NOT NULL CHECK(record_level_detail_available IN (0,1)),
    recorded_at TEXT NOT NULL,
    notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_availability_registry (
    availability_id INTEGER PRIMARY KEY,
    domain TEXT NOT NULL,
    field_name TEXT NOT NULL,
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    source_id INTEGER REFERENCES data_sources(source_id),
    availability_status TEXT NOT NULL REFERENCES missing_reason_codes(reason_code),
    assessed_at TEXT NOT NULL,
    evidence_note TEXT NOT NULL,
    UNIQUE(domain,field_name,dataset_id)
);
CREATE TABLE IF NOT EXISTS temporal_coverage_summary (
    temporal_id INTEGER PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    source_id INTEGER REFERENCES data_sources(source_id),
    table_name TEXT NOT NULL,
    series_key TEXT NOT NULL,
    time_field TEXT NOT NULL,
    first_observed_at TEXT,
    last_observed_at TEXT,
    row_count INTEGER NOT NULL,
    distinct_timestamp_count INTEGER NOT NULL,
    duplicate_timestamp_rows INTEGER NOT NULL,
    max_observed_gap_seconds REAL,
    gaps_over_1day INTEGER NOT NULL,
    expected_frequency_seconds REAL,
    expected_count INTEGER,
    completeness_pct REAL,
    completeness_class TEXT NOT NULL CHECK(completeness_class IN ('HIGH','MODERATE','LOW','CRITICAL','NOT_ASSESSABLE')),
    assessment_note TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    UNIQUE(dataset_id,table_name,series_key)
);
CREATE TABLE IF NOT EXISTS field_transformation_registry (
    transformation_id INTEGER PRIMARY KEY,
    table_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    data_origin TEXT NOT NULL CHECK(data_origin='DERIVED'),
    source_field_name TEXT NOT NULL,
    method_description TEXT NOT NULL,
    records_affected INTEGER NOT NULL,
    source_id INTEGER REFERENCES data_sources(source_id),
    dataset_id INTEGER REFERENCES datasets(dataset_id),
    transformed_at TEXT NOT NULL,
    process_id TEXT NOT NULL,
    original_preserved INTEGER NOT NULL CHECK(original_preserved IN (0,1)),
    notes TEXT NOT NULL,
    UNIQUE(dataset_id,table_name,field_name)
);
CREATE INDEX IF NOT EXISTS idx_quality_event_field ON field_quality_events(table_name,field_name,missing_reason);
CREATE INDEX IF NOT EXISTS idx_completeness_dataset_field ON dataset_field_completeness(dataset_id,field_name,study_key,period_start);

CREATE INDEX IF NOT EXISTS idx_env_mission_time ON environmental_measurements(mission_id, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_env_co2 ON environmental_measurements(carbon_dioxide_ppm);
CREATE INDEX IF NOT EXISTS idx_rad_time_metric ON radiation_measurements(timestamp_utc, radiation_metric);
CREATE INDEX IF NOT EXISTS idx_rad_instrument ON radiation_measurements(instrument_id, timestamp_utc);
CREATE UNIQUE INDEX IF NOT EXISTS uq_radiation_source_record
  ON radiation_measurements(dataset_id, source_record_ref, radiation_metric);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scientific_reference_citation_url
  ON scientific_references(citation, url);
CREATE INDEX IF NOT EXISTS idx_risk_hazard ON risk_catalog(hazard);
CREATE INDEX IF NOT EXISTS idx_checkin_subject_time ON synthetic_checkins(synthetic_subject_id, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_gene_sample_feature ON gene_expression_measurements(sample_id, feature_id);
CREATE INDEX IF NOT EXISTS idx_diff_expr_pvalue ON differential_expression_results(adjusted_p_value);
CREATE INDEX IF NOT EXISTS idx_iss_phys_platform_modality ON iss_physiology_study_catalog(platform, contributing_agency, investigation_code);

DROP VIEW IF EXISTS v_dataset_inventory;
CREATE VIEW v_dataset_inventory AS
SELECT d.dataset_id, s.name AS source, d.accession, d.title, d.data_kind, d.status,
       COALESCE((SELECT COUNT(*) FROM environmental_measurements e WHERE e.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM radiation_measurements r WHERE r.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM synthetic_checkins c WHERE c.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM biomedical_samples b WHERE b.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM gene_expression_measurements g WHERE g.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM differential_expression_results q WHERE q.dataset_id=d.dataset_id),0)
       + COALESCE((SELECT COUNT(*) FROM iss_physiology_study_catalog p WHERE p.dataset_id=d.dataset_id),0)
       AS stored_rows
FROM datasets d JOIN data_sources s USING(source_id);

