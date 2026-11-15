-- 0001_operational_schema.sql
-- EdgeSpace Phase 1: operational schema + clinical FTS5 index.
-- Applied by central/internal/store/migrate.go inside tx.Begin()/tx.Commit().
-- No PRAGMA journal_mode here: SQLite forbids changing it inside a transaction;
-- Central already sets PRAGMAs via DSN. No explicit BEGIN/COMMIT: owned by the runner.

-- ---------------------------------------------------------------------------
-- Operational tables (match central/internal/store/clinical.go)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cluster_nodes (
    mac           TEXT PRIMARY KEY,
    node_id       INTEGER NOT NULL,
    first_seen_us INTEGER,
    last_seen_us  INTEGER
);

CREATE TABLE IF NOT EXISTS crew_profiles (
    crew_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT '',
    mission_day     INTEGER NOT NULL DEFAULT 0,
    age             INTEGER NOT NULL DEFAULT 0,
    baseline_path   TEXT NOT NULL DEFAULT '',
    thresholds_json TEXT NOT NULL DEFAULT '{}'
);

-- crew_id nullable, intentionally no FK: unattributed samples must not abort batches.
CREATE TABLE IF NOT EXISTS telemetry_timeseries (
    ts_us         INTEGER NOT NULL,
    crew_id       TEXT,
    mission_mode  TEXT,
    heart_rate_bpm REAL,
    hrv_ms        REAL,
    resp_rate_bpm REAL,
    spo2_pct      REAL,
    posture       TEXT,
    confidence    REAL,
    co2_ppm       REAL,
    temp_c        REAL,
    humidity_pct  REAL,
    pressure_hpa  REAL
);

CREATE TABLE IF NOT EXISTS peripheral_readings (
    ts_us       INTEGER NOT NULL,
    node_id     INTEGER,
    sensor_type TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT
);

-- crew_id nullable, intentionally no FK.
CREATE TABLE IF NOT EXISTS alerts_audit (
    alert_id       TEXT PRIMARY KEY,
    ts_us          INTEGER NOT NULL,
    crew_id        TEXT,
    subsystem      TEXT NOT NULL,
    severity       TEXT NOT NULL,
    message        TEXT NOT NULL,
    countermeasure TEXT,
    escalation     TEXT,
    handled        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS store_and_forward_outbox (
    outbox_id   TEXT PRIMARY KEY,
    ts_us       INTEGER NOT NULL,
    subsystem   TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    destination TEXT,
    sent        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS self_exams (
    ts_us        INTEGER NOT NULL,
    crew_id      TEXT NOT NULL,
    exam_type    TEXT NOT NULL,
    result       TEXT NOT NULL,
    observations TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    ts_us   INTEGER NOT NULL,
    crew_id TEXT NOT NULL,
    role    TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS protocols (
    protocol_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    subsystems_json TEXT NOT NULL DEFAULT '[]',
    description     TEXT NOT NULL DEFAULT '',
    steps_json      TEXT NOT NULL DEFAULT '[]'
);

-- ---------------------------------------------------------------------------
-- Performance indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_telemetry_crew_ts   ON telemetry_timeseries(crew_id, ts_us);
CREATE INDEX IF NOT EXISTS idx_peripheral_type_ts  ON peripheral_readings(sensor_type, ts_us);
CREATE INDEX IF NOT EXISTS idx_alerts_ts           ON alerts_audit(ts_us DESC);
CREATE INDEX IF NOT EXISTS idx_outbox_sent_ts      ON store_and_forward_outbox(sent, ts_us DESC);
CREATE INDEX IF NOT EXISTS idx_self_exams_crew_ts  ON self_exams(crew_id, ts_us DESC);
CREATE INDEX IF NOT EXISTS idx_chat_crew_ts        ON chat_messages(crew_id, ts_us DESC);

-- ---------------------------------------------------------------------------
-- Clinical base table + FTS5 index (consumed by edge-ai clinical_store.py)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS clinical_reports (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    hazard               TEXT NOT NULL,
    category             TEXT NOT NULL,
    subsystem            TEXT NOT NULL,
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    symptoms_text        TEXT NOT NULL,
    countermeasures_text TEXT NOT NULL,
    escalation           TEXT NOT NULL,
    content              TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS clinical_reports_fts USING fts5(
    id, source_id, title, subsystem, description, content,
    tokenize='unicode61 remove_diacritics 2'
);

-- Backfill for pre-existing rows (no-op on fresh DB; skips ids already indexed).
INSERT INTO clinical_reports_fts(id, source_id, title, subsystem, description, content)
SELECT r.id, r.source_id, r.title, r.subsystem, r.description, r.content
FROM clinical_reports r
WHERE NOT EXISTS (SELECT 1 FROM clinical_reports_fts f WHERE f.id = r.id);

CREATE TRIGGER IF NOT EXISTS clinical_reports_ai AFTER INSERT ON clinical_reports
BEGIN
    INSERT INTO clinical_reports_fts(id, source_id, title, subsystem, description, content)
    VALUES (new.id, new.source_id, new.title, new.subsystem, new.description, new.content);
END;

CREATE TRIGGER IF NOT EXISTS clinical_reports_au AFTER UPDATE ON clinical_reports
BEGIN
    DELETE FROM clinical_reports_fts WHERE id = old.id;
    INSERT INTO clinical_reports_fts(id, source_id, title, subsystem, description, content)
    VALUES (new.id, new.source_id, new.title, new.subsystem, new.description, new.content);
END;

CREATE TRIGGER IF NOT EXISTS clinical_reports_ad AFTER DELETE ON clinical_reports
BEGIN
    DELETE FROM clinical_reports_fts WHERE id = old.id;
END;
