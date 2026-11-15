-- Clinical intelligence v2 schema upgrade; run once inside the migration ledger transaction.
-- No PRAGMA and no BEGIN/COMMIT: the Go/Python runner owns the transaction.

-- 1. crew_profiles clinical, nutrition and radiation attributes (NULL = not measured)
ALTER TABLE crew_profiles ADD COLUMN blood_type TEXT CHECK(blood_type IN ('A+','A-','B+','B-','AB+','AB-','O+','O-'));
ALTER TABLE crew_profiles ADD COLUMN motion_sickness_history TEXT CHECK(motion_sickness_history IN ('NONE','LOW','MODERATE','HIGH'));
ALTER TABLE crew_profiles ADD COLUMN preflight_bmd_zscore REAL CHECK(preflight_bmd_zscore BETWEEN -6 AND 6);
ALTER TABLE crew_profiles ADD COLUMN preflight_sleep_h REAL CHECK(preflight_sleep_h > 0 AND preflight_sleep_h <= 24);
ALTER TABLE crew_profiles ADD COLUMN preflight_deep_sleep_h REAL CHECK(preflight_deep_sleep_h >= 0 AND preflight_deep_sleep_h <= 24);
ALTER TABLE crew_profiles ADD COLUMN target_kcal_day REAL CHECK(target_kcal_day > 0 AND target_kcal_day <= 10000);
ALTER TABLE crew_profiles ADD COLUMN target_water_ml_day REAL CHECK(target_water_ml_day > 0 AND target_water_ml_day <= 15000);
ALTER TABLE crew_profiles ADD COLUMN target_protein_g_day REAL CHECK(target_protein_g_day > 0 AND target_protein_g_day <= 500);
ALTER TABLE crew_profiles ADD COLUMN radiation_career_limit_msv REAL CHECK(radiation_career_limit_msv > 0 AND radiation_career_limit_msv <= 5000);

-- 2. individual_baselines posture statistics and resting calibration metadata
ALTER TABLE individual_baselines ADD COLUMN per_posture_stats_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(per_posture_stats_json));
ALTER TABLE individual_baselines ADD COLUMN resting_hr_mean REAL CHECK(resting_hr_mean > 0);
ALTER TABLE individual_baselines ADD COLUMN resting_hrv_mean REAL CHECK(resting_hrv_mean >= 0);
ALTER TABLE individual_baselines ADD COLUMN calib_window_start_us INTEGER CHECK(calib_window_start_us >= 0);
ALTER TABLE individual_baselines ADD COLUMN calib_window_end_us INTEGER CHECK(calib_window_end_us >= 0);

-- 3. Dead crew_baselines table replaced by a view over the active baseline
DROP TABLE crew_baselines;
CREATE VIEW v_active_crew_baselines AS
SELECT cp.crew_id, cp.name, cp.role, cp.mission_day, cp.data_class AS crew_data_class,
       ib.baseline_id, ib.version, COALESCE(ib.onnx_model_path, cp.baseline_path) AS model_path,
       ib.feature_dim, ib.feature_schema_id, ib.mean_json, ib.std_json, ib.anomaly_threshold,
       ib.sample_count, ib.clean_window_ratio, ib.covered_postures_json, ib.per_posture_stats_json,
       ib.resting_hr_mean, ib.resting_hrv_mean, ib.calib_window_start_us, ib.calib_window_end_us,
       ib.calibration_status, ib.drift_score, ib.updated_at_us
FROM crew_profiles cp
LEFT JOIN individual_baselines ib ON ib.crew_id = cp.crew_id AND ib.is_active = 1;

-- 4. Chat session link and memory provenance/expiry/verification
ALTER TABLE chat_messages ADD COLUMN session_id TEXT REFERENCES chat_sessions(session_id);
ALTER TABLE crew_clinical_memory ADD COLUMN source_message_ts_us INTEGER;
ALTER TABLE crew_clinical_memory ADD COLUMN expires_us INTEGER;
ALTER TABLE crew_clinical_memory ADD COLUMN clinical_verified INTEGER NOT NULL DEFAULT 0 CHECK(clinical_verified IN (0,1));

-- 5. Causal engine extensions
ALTER TABLE causal_conditions ADD COLUMN symptom_weights_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(symptom_weights_json));
ALTER TABLE causal_conditions ADD COLUMN differential_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(differential_ids_json));
ALTER TABLE causal_conditions ADD COLUMN expected_biomarkers_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(expected_biomarkers_json));
ALTER TABLE causal_conditions ADD COLUMN severity_thresholds_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(severity_thresholds_json));
ALTER TABLE causal_sensor_rules ADD COLUMN rule_scope TEXT NOT NULL DEFAULT 'INSTANT' CHECK(rule_scope IN ('INSTANT','ROLLUP_3D','ROLLUP_7D','ROLLUP_30D','CONTEXT_WINDOW'));
ALTER TABLE causal_sensor_rules ADD COLUMN window_hours REAL CHECK(window_hours > 0);
ALTER TABLE causal_sensor_rules ADD COLUMN baseline_field TEXT;
ALTER TABLE causal_disambiguation_questions ADD COLUMN target_differential_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(target_differential_ids_json));

-- 6. clinical_reports.subsystem backfill from causal_conditions, then FTS rebuild
ALTER TABLE clinical_reports ADD COLUMN subsystem TEXT;
UPDATE clinical_reports SET subsystem=(SELECT MIN(c.subsystem) FROM causal_conditions c WHERE c.report_id=clinical_reports.report_id);
UPDATE clinical_reports SET subsystem=json_extract(payload_json,'$.legacy_subsystem') WHERE subsystem IS NULL;
DROP TRIGGER clinical_reports_ai;
DROP TRIGGER clinical_reports_ad;
DROP TRIGGER clinical_reports_au;
DROP TABLE clinical_reports_fts;
CREATE VIRTUAL TABLE clinical_reports_fts USING fts5(
    report_id UNINDEXED,source_id UNINDEXED,hazard_id,category,subsystem,title,problem,content_text,symptoms_text,countermeasures_text,
    content='clinical_reports',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER clinical_reports_ai AFTER INSERT ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(rowid,report_id,source_id,hazard_id,category,subsystem,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES(new.rowid,new.report_id,new.source_id,new.hazard_id,new.category,new.subsystem,new.title,new.problem,new.content_text,new.symptoms_text,new.countermeasures_text);
END;
CREATE TRIGGER clinical_reports_ad AFTER DELETE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,source_id,hazard_id,category,subsystem,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES('delete',old.rowid,old.report_id,old.source_id,old.hazard_id,old.category,old.subsystem,old.title,old.problem,old.content_text,old.symptoms_text,old.countermeasures_text);
END;
CREATE TRIGGER clinical_reports_au AFTER UPDATE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,source_id,hazard_id,category,subsystem,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES('delete',old.rowid,old.report_id,old.source_id,old.hazard_id,old.category,old.subsystem,old.title,old.problem,old.content_text,old.symptoms_text,old.countermeasures_text);
    INSERT INTO clinical_reports_fts(rowid,report_id,source_id,hazard_id,category,subsystem,title,problem,content_text,symptoms_text,countermeasures_text)
    VALUES(new.rowid,new.report_id,new.source_id,new.hazard_id,new.category,new.subsystem,new.title,new.problem,new.content_text,new.symptoms_text,new.countermeasures_text);
END;
INSERT INTO clinical_reports_fts(clinical_reports_fts) VALUES('rebuild');

-- 7. mission_context_events rebuild: new event types, lookback_hours, severity
ALTER TABLE mission_context_events RENAME TO mission_context_events_legacy;
DROP INDEX idx_mission_events_crew_type_ts;
CREATE TABLE mission_context_events (
    event_id TEXT PRIMARY KEY, crew_id TEXT REFERENCES crew_profiles(crew_id),
    event_type TEXT NOT NULL CHECK(event_type IN ('EVA','EXERCISE_ARED','EXERCISE_AEROBIC','RADIATION_SPE_ALERT','SLEEP_WINDOW',
        'CABIN_DEPRESSURIZATION','CO2_SCRUBBER_FAULT','THERMAL_EXCURSION','MEDICATION_DOSE','LIGHT_THERAPY','FLIGHT_SURGEON_CONSULT')),
    ts_us INTEGER NOT NULL, end_us INTEGER,
    lookback_hours REAL NOT NULL DEFAULT 2 CHECK(lookback_hours > 0),
    severity TEXT NOT NULL DEFAULT 'INFO' CHECK(severity IN ('INFO','YELLOW','RED')),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC')), CHECK(end_us IS NULL OR end_us >= ts_us)
);
INSERT INTO mission_context_events(event_id,crew_id,event_type,ts_us,end_us,lookback_hours,severity,details_json,data_class)
SELECT event_id,crew_id,event_type,ts_us,end_us,
    CASE WHEN event_type IN ('EVA','RADIATION_SPE_ALERT') THEN 72 ELSE 2 END,'INFO',details_json,data_class
FROM mission_context_events_legacy;
DROP TABLE mission_context_events_legacy;
CREATE INDEX idx_mission_events_crew_type_ts ON mission_context_events(crew_id,event_type,ts_us DESC);
CREATE INDEX idx_mission_events_ts ON mission_context_events(ts_us DESC);


-- 8. Nutrition and circadian extensions
ALTER TABLE nutrition_hydration_logs ADD COLUMN sodium_mg REAL CHECK(sodium_mg >= 0);
ALTER TABLE crew_circadian_schedule ADD COLUMN actual_sleep_start_us INTEGER;
ALTER TABLE crew_circadian_schedule ADD COLUMN actual_sleep_end_us INTEGER;
ALTER TABLE crew_circadian_schedule ADD COLUMN sleep_quality_score REAL CHECK(sleep_quality_score BETWEEN 0 AND 100);

-- 9. telemetry_daily_rollups extensions
ALTER TABLE telemetry_daily_rollups ADD COLUMN body_mass_kg REAL CHECK(body_mass_kg > 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN energy_kcal_total REAL CHECK(energy_kcal_total >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN water_ml_total REAL CHECK(water_ml_total >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN eva_minutes REAL CHECK(eva_minutes >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN anomaly_score_mean REAL CHECK(anomaly_score_mean >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN anomaly_score_p95 REAL CHECK(anomaly_score_p95 >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN alerts_yellow_count INTEGER CHECK(alerts_yellow_count >= 0);
ALTER TABLE telemetry_daily_rollups ADD COLUMN alerts_red_count INTEGER CHECK(alerts_red_count >= 0);

-- 10. Shift-level rollups
CREATE TABLE telemetry_shift_rollups (
    crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    shift_start_us INTEGER NOT NULL, shift_end_us INTEGER NOT NULL,
    shift_label TEXT NOT NULL CHECK(shift_label IN ('SLEEP','WORK_AM','WORK_PM')),
    day_utc TEXT NOT NULL CHECK(date(day_utc)=day_utc),
    sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
    hr_mean REAL, hrv_mean REAL, resp_mean REAL, spo2_mean REAL, co2_mean REAL, temp_mean REAL,
    anomaly_score_mean REAL CHECK(anomaly_score_mean >= 0), anomaly_score_p95 REAL CHECK(anomaly_score_p95 >= 0),
    data_class TEXT NOT NULL CHECK(data_class IN ('REAL','SYNTHETIC','DERIVED')),
    PRIMARY KEY(crew_id,shift_start_us), CHECK(shift_end_us > shift_start_us)
);
CREATE INDEX idx_shift_rollups_crew_day ON telemetry_shift_rollups(crew_id,day_utc DESC);

-- 11. New indexes
CREATE INDEX idx_peripheral_crew_ts ON peripheral_readings(crew_id,ts_us DESC);
CREATE INDEX idx_memory_crew_active_type ON crew_clinical_memory(crew_id,active,fact_type);

-- 12. Longitudinal rolling windows view (ROW_NUMBER per crew_id)
CREATE VIEW v_crew_longitudinal_windows AS
WITH ranked AS (
    SELECT crew_id, day_utc, mission_day, deep_sleep_h, hrv_mean, radiation_dose_msv,
           energy_kcal_total, water_ml_total, body_mass_kg,
           ROW_NUMBER() OVER (PARTITION BY crew_id ORDER BY day_utc DESC) AS rn
    FROM telemetry_daily_rollups
),
windowed AS (
    SELECT crew_id, day_utc, mission_day, rn, body_mass_kg,
           AVG(CASE WHEN rn <= 3 THEN deep_sleep_h END) OVER (PARTITION BY crew_id) AS deep_sleep_3d_avg_h,
           AVG(CASE WHEN rn <= 7 THEN deep_sleep_h END) OVER (PARTITION BY crew_id) AS deep_sleep_7d_avg_h,
           AVG(CASE WHEN rn <= 30 THEN deep_sleep_h END) OVER (PARTITION BY crew_id) AS deep_sleep_30d_avg_h,
           AVG(CASE WHEN rn <= 7 THEN hrv_mean END) OVER (PARTITION BY crew_id) AS hrv_7d_avg_ms,
           AVG(CASE WHEN rn <= 30 THEN hrv_mean END) OVER (PARTITION BY crew_id) AS hrv_30d_avg_ms,
           SUM(CASE WHEN rn <= 30 THEN radiation_dose_msv END) OVER (PARTITION BY crew_id) AS radiation_30d_sum_msv,
           AVG(CASE WHEN rn <= 7 THEN energy_kcal_total END) OVER (PARTITION BY crew_id) AS energy_7d_avg_kcal,
           AVG(CASE WHEN rn <= 7 THEN water_ml_total END) OVER (PARTITION BY crew_id) AS water_7d_avg_ml,
           MIN(CASE WHEN rn <= 30 AND body_mass_kg IS NOT NULL THEN rn END) OVER (PARTITION BY crew_id) AS mass_newest_rn_30d,
           MAX(CASE WHEN rn <= 30 AND body_mass_kg IS NOT NULL THEN rn END) OVER (PARTITION BY crew_id) AS mass_oldest_rn_30d
    FROM ranked
),
mass_30d AS (
    SELECT crew_id,
           MAX(CASE WHEN rn = mass_newest_rn_30d THEN body_mass_kg END) AS mass_newest_30d,
           MAX(CASE WHEN rn = mass_oldest_rn_30d THEN body_mass_kg END) AS mass_oldest_30d
    FROM windowed
    GROUP BY crew_id
)
SELECT cp.crew_id, w.day_utc AS latest_day_utc, w.mission_day AS latest_mission_day,
       w.deep_sleep_3d_avg_h, w.deep_sleep_7d_avg_h, w.deep_sleep_30d_avg_h,
       w.hrv_7d_avg_ms, w.hrv_30d_avg_ms,
       CASE WHEN w.hrv_7d_avg_ms IS NOT NULL AND w.hrv_30d_avg_ms IS NOT NULL
            THEN w.hrv_7d_avg_ms - w.hrv_30d_avg_ms END AS hrv_delta_7d_vs_30d_ms,
       COALESCE(w.radiation_30d_sum_msv, 0.0) AS radiation_30d_sum_msv,
       w.energy_7d_avg_kcal, w.water_7d_avg_ml,
       CASE WHEN m.mass_newest_30d IS NOT NULL AND m.mass_oldest_30d IS NOT NULL
            THEN m.mass_newest_30d - m.mass_oldest_30d END AS body_mass_30d_delta_kg
FROM crew_profiles cp
LEFT JOIN windowed w ON w.crew_id = cp.crew_id AND w.rn = 1
LEFT JOIN mass_30d m ON m.crew_id = cp.crew_id;

