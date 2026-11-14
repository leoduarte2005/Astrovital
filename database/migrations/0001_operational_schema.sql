-- Operational database only. Connection must enable foreign_keys and WAL.
CREATE TABLE clinical_sources (
    source_id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL,
    url TEXT NOT NULL, section TEXT NOT NULL, reviewed_on TEXT NOT NULL
);
CREATE TABLE clinical_hazards (hazard_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE crew_profiles (
    crew_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',
    mission_day INTEGER NOT NULL DEFAULT 0 CHECK(mission_day >= 0), age INTEGER CHECK(age >= 18),
    baseline_path TEXT NOT NULL DEFAULT '',
    thresholds_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(thresholds_json)),
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC'))
);
CREATE TABLE crew_baselines (
    crew_id TEXT PRIMARY KEY REFERENCES crew_profiles(crew_id),
    baseline_path TEXT, updated_at_us INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE cluster_nodes (
    mac TEXT PRIMARY KEY, node_id INTEGER NOT NULL UNIQUE CHECK(node_id BETWEEN 0 AND 4),
    first_seen_us INTEGER NOT NULL, last_seen_us INTEGER NOT NULL
);
CREATE TABLE telemetry_timeseries (
    reading_id INTEGER PRIMARY KEY, ts_us INTEGER NOT NULL,
    crew_id TEXT REFERENCES crew_profiles(crew_id),
    mission_mode TEXT NOT NULL CHECK(mission_mode IN ('MODE_CABIN_TOMOGRAPHY','MODE_REST_VITALS','MODE_COUNTERMEASURE_EXERCISE','MODE_RADIATION_ALERT')),
    heart_rate_bpm REAL, hrv_ms REAL, resp_rate_bpm REAL, spo2_pct REAL,
    posture TEXT, confidence REAL CHECK(confidence BETWEEN 0 AND 1),
    co2_ppm REAL, temp_c REAL, humidity_pct REAL, pressure_hpa REAL,
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC','DERIVED'))
);
CREATE INDEX idx_telemetry_crew_ts ON telemetry_timeseries(crew_id,ts_us);
CREATE TABLE peripheral_readings (
    reading_id INTEGER PRIMARY KEY, ts_us INTEGER NOT NULL, node_id INTEGER NOT NULL,
    sensor_type TEXT NOT NULL, value REAL, unit TEXT NOT NULL DEFAULT '',
    data_class TEXT NOT NULL DEFAULT 'REAL' CHECK(data_class IN ('REAL','SYNTHETIC'))
);
CREATE TABLE self_exams (
    exam_id INTEGER PRIMARY KEY, ts_us INTEGER NOT NULL,
    crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    exam_type TEXT NOT NULL, result TEXT NOT NULL, observations TEXT NOT NULL DEFAULT ''
);
CREATE TABLE chat_sessions (
    session_id TEXT PRIMARY KEY, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    started_us INTEGER NOT NULL, ended_us INTEGER
);
CREATE TABLE chat_messages (
    message_id INTEGER PRIMARY KEY, session_id TEXT REFERENCES chat_sessions(session_id),
    ts_us INTEGER NOT NULL, crew_id TEXT NOT NULL REFERENCES crew_profiles(crew_id),
    role TEXT NOT NULL CHECK(role IN ('user','assistant','clinician','system')),
    content TEXT NOT NULL
);
CREATE INDEX idx_chat_crew_ts ON chat_messages(crew_id,ts_us DESC,message_id DESC);
CREATE TABLE protocols (
    protocol_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
    subsystems_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(subsystems_json)),
    steps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(steps_json)),
    source_id TEXT REFERENCES clinical_sources(source_id)
);
CREATE TABLE clinical_reports (
    report_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES clinical_sources(source_id),
    hazard_id TEXT NOT NULL REFERENCES clinical_hazards(hazard_id),
    category TEXT NOT NULL CHECK(category IN ('PHYSIOLOGICAL','BEHAVIORAL_BIOCHEMICAL')),
    title TEXT NOT NULL, problem TEXT NOT NULL, content_text TEXT NOT NULL,
    symptoms_text TEXT NOT NULL DEFAULT '', countermeasures_text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE VIRTUAL TABLE clinical_reports_fts USING fts5(
    report_id UNINDEXED,title,problem,content_text,
    content='clinical_reports',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER clinical_reports_ai AFTER INSERT ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(rowid,report_id,title,problem,content_text)
    VALUES(new.rowid,new.report_id,new.title,new.problem,new.content_text);
END;
CREATE TRIGGER clinical_reports_ad AFTER DELETE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,title,problem,content_text)
    VALUES('delete',old.rowid,old.report_id,old.title,old.problem,old.content_text);
END;
CREATE TRIGGER clinical_reports_au AFTER UPDATE ON clinical_reports BEGIN
    INSERT INTO clinical_reports_fts(clinical_reports_fts,rowid,report_id,title,problem,content_text)
    VALUES('delete',old.rowid,old.report_id,old.title,old.problem,old.content_text);
    INSERT INTO clinical_reports_fts(rowid,report_id,title,problem,content_text)
    VALUES(new.rowid,new.report_id,new.title,new.problem,new.content_text);
END;
CREATE TABLE alerts_audit (
    alert_id TEXT PRIMARY KEY, ts_us INTEGER NOT NULL,
    crew_id TEXT REFERENCES crew_profiles(crew_id), subsystem TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('GREEN','YELLOW','RED')),
    message TEXT NOT NULL, countermeasure TEXT NOT NULL DEFAULT '',
    escalation TEXT NOT NULL DEFAULT 'LOCAL' CHECK(escalation IN ('LOCAL','CREW','STORE_AND_FORWARD')),
    handled INTEGER NOT NULL DEFAULT 0 CHECK(handled IN (0,1))
);
CREATE TABLE store_and_forward_outbox (
    outbox_id TEXT PRIMARY KEY, ts_us INTEGER NOT NULL, subsystem TEXT NOT NULL,
    severity TEXT NOT NULL, message TEXT NOT NULL, destination TEXT NOT NULL DEFAULT 'ground_control',
    sent INTEGER NOT NULL DEFAULT 0 CHECK(sent IN (0,1))
);
