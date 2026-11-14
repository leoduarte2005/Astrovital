"""Behavior checks for NULL preservation, snapshot restoration and atomic audit refresh."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1] / "space_health_sqlite"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = load("missingness_policy", "apply_missingness_policy.py")
BUILDER = load("missingness_fixture_builder", "build_db.py")


class MissingnessPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edgespace-missingness-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / "research.db"

    def prepare_snapshot(self):
        connection = BUILDER.connect(self.database)
        try:
            BUILDER.seed_catalog(connection)
            BUILDER.generate_checkins(connection)
            dataset = connection.execute("SELECT dataset_id FROM datasets WHERE accession='EDA-TELEMETRY'").fetchone()[0]
            mission = BUILDER.mission_row(connection, "TEST")
            batch = connection.execute(
                "INSERT INTO import_batches(dataset_id,started_at,completed_at,status,source_records,inserted_records,skipped_records) "
                "VALUES(?,'2026-01-01','2026-01-01','SUCCESS',4,2,2)", (dataset,)
            ).lastrowid
            for zone, suffix in [("GROUND_CONTROL", "ground"), ("ISS_HARDWARE", "iss")]:
                connection.execute(
                    "INSERT INTO environmental_measurements(dataset_id,batch_id,mission_id,timestamp_raw,timestamp_utc,zone,temperature_c,relative_humidity_percent,carbon_dioxide_ppm,source_record_ref) "
                    "VALUES(?,?,?,'2026-11-01 00:00','2026-11-01T00:00Z',?,0,0,0,?)",
                    (dataset, batch, mission, zone, f"TEST:0:{suffix}"),
                )
            telemetry = {"time_TEST": ["2026-11-01 00:00", "2026-11-02 00:00"]}
            for field in ["temperature_ground", "temperature_iss", "rh_ground", "rh_iss", "co2_ground", "co2_iss"]:
                telemetry[field] = [0, None]
            wrapper = json.dumps({"telemetry_data": json.dumps(telemetry)})
            raw = ('<script id="data" type="application/json">' + wrapper + "</script>").encode()
            connection.execute(
                "INSERT INTO source_snapshots(dataset_id,batch_id,source_url,retrieved_at,sha256,content_gzip,byte_count) "
                "VALUES(?,?,'https://example.invalid/fixture','2026-01-01',?,?,?)",
                (dataset, batch, hashlib.sha256(raw).hexdigest(), gzip.compress(raw, mtime=0), len(raw)),
            )
            connection.commit()
            return dataset, batch, mission
        finally:
            connection.close()

    def state(self):
        connection = sqlite3.connect(self.database)
        try:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ["environmental_measurements", "import_batches", "field_quality_events", "missing_reason_codes"]
            }
        finally:
            connection.close()

    def test_importing_module_does_not_open_a_database(self):
        with mock.patch("sqlite3.connect", side_effect=AssertionError("Unexpected database access")):
            load("missingness_import_check", "apply_missingness_policy.py")

    def test_fresh_database_uses_shared_schema(self):
        summary = POLICY.apply_database(self.database)
        self.assertEqual(summary["missing_cells"], 0)
        connection = sqlite3.connect(self.database)
        try:
            self.assertIn("study_key", {r[1] for r in connection.execute("PRAGMA table_info(dataset_field_completeness)")})
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM missing_reason_codes").fetchone()[0], 7)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_restore_empty_source_rows_keep_zero_values_and_reapply_without_duplicates(self):
        dataset, batch, _ = self.prepare_snapshot()
        for _ in range(2):
            summary = POLICY.apply_database(self.database)
            self.assertEqual(summary["missing_cells"], 6)
            self.assertEqual(summary["imputed_values"], 0)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM environmental_measurements").fetchone()[0], 4)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM environmental_measurements WHERE temperature_c=0 AND relative_humidity_percent=0 AND carbon_dioxide_ppm=0"
            ).fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT inserted_records,skipped_records FROM import_batches WHERE batch_id=?", (batch,)).fetchone(), (4, 0))
            self.assertEqual(connection.execute(
                "SELECT expected_count,observed_count,missing_count,completeness_pct FROM dataset_field_completeness "
                "WHERE dataset_id=? AND field_name='carbon_dioxide_ppm' AND study_key IS NULL", (dataset,)
            ).fetchone(), (4, 2, 2, 50.0))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM temporal_coverage_summary WHERE expected_count IS NOT NULL").fetchone()[0], 0)
        finally:
            connection.close()

    def test_preserve_external_audit_and_scope_completeness_to_its_dataset(self):
        dataset, _, mission = self.prepare_snapshot()
        POLICY.apply_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            source = connection.execute("SELECT source_id FROM datasets WHERE dataset_id=?", (dataset,)).fetchone()[0]
            external = connection.execute(
                "INSERT INTO datasets(source_id,accession,title,data_kind,status) VALUES(?,'LOCAL-TEST','External test','REAL','IMPORTED')", (source,)
            ).lastrowid
            batch = connection.execute(
                "INSERT INTO import_batches(dataset_id,started_at,completed_at,status) VALUES(?,'2026-01-01','2026-01-01','SUCCESS')", (external,)
            ).lastrowid
            connection.execute(
                "INSERT INTO environmental_measurements(dataset_id,batch_id,mission_id,timestamp_raw,timestamp_utc,zone,temperature_c,relative_humidity_percent,carbon_dioxide_ppm,source_record_ref) "
                "VALUES(?,?,?,'2026-11-01','2026-11-01T00:00Z','ISS_HARDWARE',25,50,500,'LOCAL:0')", (external, batch, mission)
            )
            connection.execute(
                "INSERT INTO field_quality_events(table_name,record_pk,field_name,data_origin,quality_status,process_id) "
                "VALUES('synthetic_checkins',1,'scenario','SYNTHETIC','SYNTHETIC','external-review')"
            )
            connection.commit()
        finally:
            connection.close()
        POLICY.apply_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM field_quality_events WHERE process_id='external-review'").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT expected_count FROM dataset_field_completeness WHERE dataset_id=? AND field_name='temperature_c' AND study_key IS NULL", (dataset,)
            ).fetchone()[0], 4)
        finally:
            connection.close()

    def test_failed_refresh_rolls_back_the_previous_audit(self):
        self.prepare_snapshot()
        POLICY.apply_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                "CREATE TRIGGER reject_audit BEFORE INSERT ON field_quality_events "
                "WHEN NEW.field_name='carbon_dioxide_ppm' BEGIN SELECT RAISE(ABORT,'forced failure'); END;"
            )
        finally:
            connection.close()
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError):
            POLICY.apply_database(self.database)
        self.assertEqual(self.state(), before)

    def test_legacy_completeness_table_keeps_data_and_gains_study_key(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "CREATE TABLE dataset_field_completeness(summary_id INTEGER PRIMARY KEY,dataset_id INTEGER,source_id INTEGER,"
                "table_name TEXT NOT NULL,field_name TEXT NOT NULL,period_start TEXT,period_end TEXT,expected_count INTEGER,"
                "observed_count INTEGER NOT NULL,missing_count INTEGER NOT NULL,completeness_pct REAL,completeness_class TEXT,"
                "denominator_basis TEXT NOT NULL,calculated_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO dataset_field_completeness(table_name,field_name,observed_count,missing_count,completeness_class,denominator_basis,calculated_at) "
                "VALUES('external','field',0,0,'NOT_ASSESSABLE','External fixture','2026-01-01')"
            )
            connection.commit()
        finally:
            connection.close()
        POLICY.apply_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM dataset_field_completeness WHERE table_name='external'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_cli_accepts_named_and_positional_database_paths(self):
        script = PACKAGE / "scripts/apply_missingness_policy.py"
        for arguments in (["--db", str(self.database)], [str(self.database)]):
            result = subprocess.run([sys.executable, str(script), *arguments], cwd=self.directory, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["imputed_values"], 0)


if __name__ == "__main__":
    unittest.main()
