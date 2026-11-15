-- Upgrade of the published operational 0001/0002; run once in the migration transaction.
CREATE TABLE clinical_sources (
    source_id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL,
    url TEXT NOT NULL, section TEXT NOT NULL, reviewed_on TEXT NOT NULL
);
CREATE TABLE clinical_hazards (hazard_id TEXT PRIMARY KEY, name TEXT NOT NULL);

CREATE TABLE crew_baselines (crew_id TEXT PRIMARY KEY REFERENCES crew_profiles(crew_id),baseline_path TEXT,updated_at_us INTEGER NOT NULL DEFAULT 0);
CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY,crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),started_us INTEGER NOT NULL,ended_us INTEGER);
ALTER TABLE crew_profiles ADD COLUMN data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC'));
ALTER TABLE telemetry_timeseries ADD COLUMN data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC','DERIVED'));
ALTER TABLE protocols ADD COLUMN source_id TEXT REFERENCES clinical_sources(source_id);
DROP TRIGGER clinical_reports_ai;
DROP TRIGGER clinical_reports_ad;
DROP TRIGGER clinical_reports_au;
DROP TABLE clinical_reports_fts;
ALTER TABLE clinical_reports RENAME TO clinical_reports_legacy;
CREATE TABLE clinical_reports (
    report_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES clinical_sources(source_id),
    hazard_id TEXT NOT NULL REFERENCES clinical_hazards(hazard_id),
    category TEXT NOT NULL CHECK(category IN ('PHYSIOLOGICAL','BEHAVIORAL_BIOCHEMICAL','HAZARD')),
    title TEXT NOT NULL, problem TEXT NOT NULL, content_text TEXT NOT NULL,
    symptoms_text TEXT NOT NULL DEFAULT '', countermeasures_text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);

INSERT INTO clinical_sources(source_id,title,publisher,url,section,reviewed_on)
SELECT DISTINCT source_id,source_id,'NASA (legacy attribution)','https://www.nasa.gov/hrp/risks/','Legacy reference; details preserved in payload_json','2026-11-14' FROM clinical_reports_legacy;
INSERT INTO clinical_hazards VALUES
('GRAVITY_FIELDS','Campos de gravidade'),('SPACE_RADIATION','Radiação espacial'),
('ISOLATION_CONFINEMENT','Isolamento e confinamento'),('HOSTILE_CLOSED_ENVIRONMENT','Ambiente fechado e hostil'),('DISTANCE_FROM_EARTH','Distância da Terra');
INSERT INTO clinical_reports(report_id,source_id,hazard_id,category,title,problem,content_text,symptoms_text,countermeasures_text,payload_json)
SELECT id,source_id,CASE WHEN lower(hazard) LIKE '%radiation%' THEN 'SPACE_RADIATION'
 WHEN lower(hazard) LIKE '%isolation%' THEN 'ISOLATION_CONFINEMENT'
 WHEN lower(hazard) LIKE '%distance%' THEN 'DISTANCE_FROM_EARTH'
 WHEN lower(hazard) LIKE '%gravity%' THEN 'GRAVITY_FIELDS' ELSE 'HOSTILE_CLOSED_ENVIRONMENT' END,
 CASE WHEN category IN ('BEHAVIORAL','BIOCHEMICAL') THEN 'BEHAVIORAL_BIOCHEMICAL' ELSE category END,
 title,description,content,symptoms_text,countermeasures_text,
 json_object('legacy_id',id,'legacy_hazard',hazard,'legacy_subsystem',subsystem,'legacy_escalation',escalation)
FROM clinical_reports_legacy;
DROP TABLE clinical_reports_legacy;
-- Rebuild to allow NULL sensor values and attach explicit provenance/crew references.
ALTER TABLE peripheral_readings RENAME TO peripheral_readings_legacy;
CREATE TABLE peripheral_readings(reading_id INTEGER PRIMARY KEY,ts_us INTEGER NOT NULL,node_id INTEGER,
 sensor_type TEXT NOT NULL,value REAL,unit TEXT,crew_id TEXT REFERENCES crew_profiles(crew_id),
 data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC')));
INSERT INTO peripheral_readings(ts_us,node_id,sensor_type,value,unit)
 SELECT ts_us,node_id,sensor_type,value,unit FROM peripheral_readings_legacy;
DROP TABLE peripheral_readings_legacy;
CREATE INDEX idx_peripheral_type_ts ON peripheral_readings(sensor_type,ts_us);
-- Applied once by the migration ledger; no BEGIN/COMMIT (Go owns its transaction).
ALTER TABLE crew_profiles ADD COLUMN biological_sex TEXT NOT NULL DEFAULT 'M' CHECK(biological_sex IN ('M','F'));
ALTER TABLE crew_profiles ADD COLUMN height_cm REAL CHECK(height_cm > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_weight_kg REAL CHECK(preflight_weight_kg > 0);
ALTER TABLE crew_profiles ADD COLUMN vo2max_baseline REAL CHECK(vo2max_baseline > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_hr_bpm REAL CHECK(preflight_hr_bpm > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_hrv_ms REAL CHECK(preflight_hrv_ms >= 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_spo2_pct REAL CHECK(preflight_spo2_pct BETWEEN 0 AND 100);
ALTER TABLE crew_profiles ADD COLUMN preflight_sbp_mmhg REAL CHECK(preflight_sbp_mmhg > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_dbp_mmhg REAL CHECK(preflight_dbp_mmhg > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_ferritin_ug_l REAL CHECK(preflight_ferritin_ug_l >= 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_hemoglobin_g_dl REAL CHECK(preflight_hemoglobin_g_dl > 0);
ALTER TABLE crew_profiles ADD COLUMN preflight_onsd_mm REAL CHECK(preflight_onsd_mm > 0);
ALTER TABLE crew_profiles ADD COLUMN sans_susceptibility TEXT NOT NULL DEFAULT 'MODERATE' CHECK(sans_susceptibility IN ('LOW','MODERATE','HIGH'));
ALTER TABLE crew_profiles ADD COLUMN sas_susceptibility TEXT NOT NULL DEFAULT 'MODERATE' CHECK(sas_susceptibility IN ('LOW','MODERATE','HIGH'));
ALTER TABLE crew_profiles ADD COLUMN co2_sensitivity TEXT NOT NULL DEFAULT 'NORMAL' CHECK(co2_sensitivity IN ('NORMAL','HIGH'));
ALTER TABLE crew_profiles ADD COLUMN mission_start_us INTEGER;
CREATE INDEX idx_peripheral_crew_sensor_ts ON peripheral_readings(crew_id,sensor_type,ts_us);
ALTER TABLE self_exams ADD COLUMN protocol_id TEXT REFERENCES protocols(protocol_id);
ALTER TABLE self_exams ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json));
ALTER TABLE self_exams ADD COLUMN abnormal_flag INTEGER NOT NULL DEFAULT 0 CHECK(abnormal_flag IN (0,1));
CREATE INDEX idx_self_exams_crew_protocol_ts ON self_exams(crew_id,protocol_id,ts_us DESC);
ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json));
ALTER TABLE protocols ADD COLUMN duration_s INTEGER CHECK(duration_s >= 0);
ALTER TABLE protocols ADD COLUMN materials_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(materials_json));
ALTER TABLE protocols ADD COLUMN rich_steps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(rich_steps_json));
ALTER TABLE protocols ADD COLUMN result_schema_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_schema_json));
ALTER TABLE protocols ADD COLUMN linked_risks_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(linked_risks_json));
CREATE VIRTUAL TABLE protocols_fts USING fts5(
    protocol_id UNINDEXED,name,description,steps_json,rich_steps_json,
    content='protocols',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER protocols_ai AFTER INSERT ON protocols BEGIN
    INSERT INTO protocols_fts(rowid,protocol_id,name,description,steps_json,rich_steps_json)
    VALUES(new.rowid,new.protocol_id,new.name,new.description,new.steps_json,new.rich_steps_json);
END;
CREATE TRIGGER protocols_ad AFTER DELETE ON protocols BEGIN
    INSERT INTO protocols_fts(protocols_fts,rowid,protocol_id,name,description,steps_json,rich_steps_json)
    VALUES('delete',old.rowid,old.protocol_id,old.name,old.description,old.steps_json,old.rich_steps_json);
END;
CREATE TRIGGER protocols_au AFTER UPDATE ON protocols BEGIN
    INSERT INTO protocols_fts(protocols_fts,rowid,protocol_id,name,description,steps_json,rich_steps_json)
    VALUES('delete',old.rowid,old.protocol_id,old.name,old.description,old.steps_json,old.rich_steps_json);
    INSERT INTO protocols_fts(rowid,protocol_id,name,description,steps_json,rich_steps_json)
    VALUES(new.rowid,new.protocol_id,new.name,new.description,new.steps_json,new.rich_steps_json);
END;
INSERT INTO protocols_fts(protocols_fts) VALUES('rebuild');
CREATE VIRTUAL TABLE clinical_reports_fts USING fts5(
    report_id UNINDEXED,title,problem,content_text,symptoms_text,countermeasures_text,
    content='clinical_reports',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER clinical_reports_ai AFTER INSERT ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(rowid,report_id,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES(new.rowid,new.report_id,new.title,new.problem,new.content_text,new.symptoms_text,new.countermeasures_text);
END;
CREATE TRIGGER clinical_reports_ad AFTER DELETE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES('delete',old.rowid,old.report_id,old.title,old.problem,old.content_text,old.symptoms_text,old.countermeasures_text);
END;
CREATE TRIGGER clinical_reports_au AFTER UPDATE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES('delete',old.rowid,old.report_id,old.title,old.problem,old.content_text,old.symptoms_text,old.countermeasures_text);
    INSERT INTO clinical_reports_fts(rowid,report_id,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES(new.rowid,new.report_id,new.title,new.problem,new.content_text,new.symptoms_text,new.countermeasures_text);
END;
INSERT INTO clinical_reports_fts(clinical_reports_fts) VALUES('rebuild');
CREATE INDEX idx_telemetry_crew_mode_ts ON telemetry_timeseries(crew_id,mission_mode,ts_us);
CREATE INDEX idx_alerts_crew_ts ON alerts_audit(crew_id,ts_us DESC);
CREATE TABLE audit_log (
    audit_id INTEGER PRIMARY KEY, ts_us INTEGER NOT NULL,
    crew_id TEXT REFERENCES crew_profiles(crew_id), event_type TEXT NOT NULL, details TEXT NOT NULL
);
CREATE INDEX idx_audit_crew_ts ON audit_log(crew_id,ts_us DESC);
CREATE TABLE csi_blobs (
    blob_id INTEGER PRIMARY KEY, ts_us INTEGER NOT NULL,
    crew_id TEXT REFERENCES crew_profiles(crew_id), reason TEXT NOT NULL,
    byte_len INTEGER NOT NULL CHECK(byte_len >= 0), blob BLOB NOT NULL,
    CHECK(byte_len = length(blob))
);
CREATE TABLE individual_baselines (
    baseline_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    version INTEGER NOT NULL CHECK(version > 0), onnx_model_path TEXT,
    feature_dim INTEGER NOT NULL DEFAULT 64 CHECK(feature_dim > 0),
    feature_schema_id TEXT NOT NULL DEFAULT 'EDGESPACE_DSP64_V1',
    mean_json TEXT NOT NULL CHECK(json_valid(mean_json) AND json_type(mean_json)='array' AND json_array_length(mean_json)=feature_dim),
    std_json TEXT NOT NULL CHECK(json_valid(std_json) AND json_type(std_json)='array' AND json_array_length(std_json)=feature_dim),
    anomaly_threshold REAL NOT NULL CHECK(anomaly_threshold > 0),
    sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
    clean_window_ratio REAL NOT NULL CHECK(clean_window_ratio BETWEEN 0 AND 1),
    covered_postures_json TEXT NOT NULL CHECK(json_valid(covered_postures_json)),
    calibration_status TEXT NOT NULL CHECK(calibration_status IN ('REQUIRES_CALIBRATION','CALIBRATING','READY','STALE','FAILED','SYNTHETIC_SEED')),
    drift_score REAL NOT NULL DEFAULT 0 CHECK(drift_score >= 0),
    is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    updated_at_us INTEGER NOT NULL, data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC')),
    UNIQUE(crew_id,version)
);
CREATE UNIQUE INDEX idx_baseline_one_active ON individual_baselines(crew_id) WHERE is_active=1;
CREATE TRIGGER baseline_vectors_insert BEFORE INSERT ON individual_baselines BEGIN
    SELECT CASE WHEN EXISTS(SELECT 1 FROM json_each(new.mean_json) WHERE type NOT IN ('real','integer'))
        OR EXISTS(SELECT 1 FROM json_each(new.std_json) WHERE type NOT IN ('real','integer') OR value <= 0)
        THEN RAISE(ABORT,'baseline vectors must be numeric with positive std') END;
END;
CREATE TRIGGER baseline_vectors_update BEFORE UPDATE OF mean_json,std_json ON individual_baselines BEGIN
    SELECT CASE WHEN EXISTS(SELECT 1 FROM json_each(new.mean_json) WHERE type NOT IN ('real','integer'))
        OR EXISTS(SELECT 1 FROM json_each(new.std_json) WHERE type NOT IN ('real','integer') OR value <= 0)
        THEN RAISE(ABORT,'baseline vectors must be numeric with positive std') END;
END;
CREATE TABLE calibration_sessions (
    session_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    baseline_id TEXT REFERENCES individual_baselines(baseline_id),
    started_us INTEGER NOT NULL, ended_us INTEGER, status TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0 CHECK(sample_count >= 0),
    clean_window_ratio REAL CHECK(clean_window_ratio BETWEEN 0 AND 1),
    covered_postures_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(covered_postures_json)),
    notes TEXT NOT NULL DEFAULT '', CHECK(ended_us IS NULL OR ended_us >= started_us)
);
CREATE TABLE crew_clinical_memory (
    memory_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    fact_type TEXT NOT NULL CHECK(fact_type IN ('ALLERGY','MEDICATION','CONDITION_HISTORY','SENSITIVITY','SLEEP_NOTE','PREFERENCE','ANSWERED_TOPIC')),
    fact_key TEXT NOT NULL, fact_value TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1), source_role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_us INTEGER NOT NULL, updated_us INTEGER NOT NULL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC')),
    UNIQUE(crew_id,fact_type,fact_key), CHECK(updated_us >= created_us)
);
CREATE TABLE telemetry_daily_rollups (
    crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id), day_utc TEXT NOT NULL CHECK(date(day_utc)=day_utc),
    mission_day INTEGER NOT NULL, sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
    hr_mean REAL, hr_min REAL, hr_max REAL, hrv_mean REAL, hrv_p10 REAL, resp_mean REAL,
    spo2_mean REAL, spo2_min REAL, co2_mean REAL, co2_max REAL, temp_mean REAL,
    sleep_duration_h REAL, deep_sleep_h REAL, exercise_minutes REAL, radiation_dose_msv REAL,
    data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC','DERIVED')),
    PRIMARY KEY(crew_id,day_utc), CHECK(hr_min <= hr_mean AND hr_mean <= hr_max),
    CHECK(spo2_min <= spo2_mean), CHECK(deep_sleep_h <= sleep_duration_h)
);
CREATE TABLE mission_context_events (
    event_id TEXT PRIMARY KEY, crew_id TEXT REFERENCES crew_profiles(crew_id),
    event_type TEXT NOT NULL CHECK(event_type IN ('EVA','EXERCISE_ARED','EXERCISE_AEROBIC','RADIATION_SPE_ALERT','SLEEP_WINDOW')),
    ts_us INTEGER NOT NULL, end_us INTEGER, details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC')), CHECK(end_us IS NULL OR end_us >= ts_us)
);
CREATE INDEX idx_mission_events_crew_type_ts ON mission_context_events(crew_id,event_type,ts_us DESC);
CREATE TABLE crew_circadian_schedule (
    schedule_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id), day_utc TEXT NOT NULL,
    sleep_start_us INTEGER NOT NULL, sleep_end_us INTEGER NOT NULL,
    light_start_us INTEGER, light_end_us INTEGER, light_lux REAL,
    data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC')),
    UNIQUE(crew_id,day_utc), CHECK(sleep_end_us > sleep_start_us)
);
CREATE TABLE nutrition_hydration_logs (
    log_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id), ts_us INTEGER NOT NULL,
    water_ml REAL CHECK(water_ml >= 0), energy_kcal REAL CHECK(energy_kcal >= 0),
    protein_g REAL CHECK(protein_g >= 0), calcium_mg REAL CHECK(calcium_mg >= 0),
    iron_mg REAL CHECK(iron_mg >= 0), vitamin_d_ug REAL CHECK(vitamin_d_ug >= 0),
    potassium_citrate_mg REAL CHECK(potassium_citrate_mg >= 0), body_mass_kg REAL CHECK(body_mass_kg > 0),
    source_note TEXT NOT NULL, data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC'))
);
CREATE INDEX idx_nutrition_crew_ts ON nutrition_hydration_logs(crew_id,ts_us);
CREATE TABLE causal_conditions (
    condition_id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES clinical_reports(report_id),
    name TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES clinical_sources(source_id), subsystem TEXT NOT NULL,
    prior REAL NOT NULL CHECK(prior > 0 AND prior < 1),
    default_escalation TEXT NOT NULL CHECK(default_escalation IN ('LOCAL','CREW','STORE_AND_FORWARD')),
    recommended_mission_mode TEXT NOT NULL CHECK(recommended_mission_mode IN ('MODE_CABIN_TOMOGRAPHY','MODE_REST_VITALS','MODE_COUNTERMEASURE_EXERCISE','MODE_RADIATION_ALERT')),
    symptoms_json TEXT NOT NULL CHECK(json_valid(symptoms_json)),
    countermeasures_json TEXT NOT NULL CHECK(json_valid(countermeasures_json)),
    actions_json TEXT NOT NULL CHECK(json_valid(actions_json)),
    linked_protocols_json TEXT NOT NULL CHECK(json_valid(linked_protocols_json)),
    match_policy TEXT NOT NULL DEFAULT 'ALL' CHECK(match_policy IN ('ALL','ANY')),
    model_status TEXT NOT NULL DEFAULT 'ENGINEERING_TEST_ONLY' CHECK(model_status IN ('ENGINEERING_TEST_ONLY','CLINICALLY_VALIDATED'))
);
CREATE TABLE causal_sensor_rules (
    rule_id TEXT PRIMARY KEY, condition_id TEXT NOT NULL REFERENCES causal_conditions(condition_id) ON DELETE CASCADE,
    source_sensor TEXT NOT NULL, metric TEXT NOT NULL,
    op TEXT NOT NULL CHECK(op IN ('GT','GE','LT','LE','EQ','IN','DELTA_GT','DELTA_LT')),
    threshold_value REAL, values_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(values_json)),
    likelihood_ratio REAL NOT NULL CHECK(likelihood_ratio > 0),
    severity_tier TEXT NOT NULL CHECK(severity_tier IN ('INFO','YELLOW','RED')),
    weight_basis TEXT NOT NULL, description TEXT NOT NULL
);
CREATE INDEX idx_causal_rules_condition ON causal_sensor_rules(condition_id);
CREATE TABLE causal_disambiguation_questions (
    question_id TEXT PRIMARY KEY, condition_id TEXT NOT NULL REFERENCES causal_conditions(condition_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL, positive_concepts_json TEXT NOT NULL CHECK(json_valid(positive_concepts_json)),
    yes_likelihood REAL NOT NULL CHECK(yes_likelihood > 0), no_likelihood REAL NOT NULL CHECK(no_likelihood > 0),
    linked_protocol_id TEXT REFERENCES protocols(protocol_id)
);
CREATE TABLE causal_contraindications (
    contra_id TEXT PRIMARY KEY, condition_id TEXT NOT NULL REFERENCES causal_conditions(condition_id) ON DELETE CASCADE,
    blocked_action TEXT NOT NULL, guard_metric TEXT NOT NULL,
    guard_op TEXT NOT NULL CHECK(guard_op IN ('GT','GE','LT','LE','EQ')),
    guard_value REAL NOT NULL, rationale TEXT NOT NULL
);
