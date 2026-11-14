"""Regression checks for the imported publication corpus and transaction boundary."""

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
IMPORTER = PACKAGE / "scripts/import_published_physiology.py"
SPEC = importlib.util.spec_from_file_location("published_physiology", IMPORTER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EXPECTED = json.loads((PACKAGE / "reports/supplied/validation_report.json").read_text(encoding="utf-8"))["counts"]


class PublishedPhysiologyImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edgespace-physiology-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / "research.db"

    def state(self):
        connection = sqlite3.connect(self.database)
        try:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("physiology_publications", "published_physiology_aggregates")
            }
        finally:
            connection.close()

    def test_module_import_has_no_database_side_effects(self):
        spec = importlib.util.spec_from_file_location("publication_import_check", IMPORTER)
        module = importlib.util.module_from_spec(spec)
        with mock.patch("sqlite3.connect", side_effect=AssertionError("Unexpected database access")):
            spec.loader.exec_module(module)

    def test_fresh_database_uses_shared_schema_and_retains_supplied_values(self):
        summary = MODULE.import_database(self.database)
        self.assertEqual(summary["total_publications"], EXPECTED["physiology_publications"])
        self.assertEqual(summary["total_aggregate_rows"], EXPECTED["published_physiology_aggregates"])
        connection = sqlite3.connect(self.database)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(published_physiology_aggregates)")}
            self.assertIn("dispersion_value", columns)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute(
                "SELECT dispersion_value FROM published_physiology_aggregates WHERE metric_code='SVR_CHANGE_PCT'"
            ).fetchone()[0], -4.0)
        finally:
            connection.close()

    def test_repeated_import_preserves_unrelated_publications_and_values(self):
        MODULE.import_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            publication = connection.execute(
                "INSERT INTO physiology_publications(citation,article_url,subject,public_data_status,extraction_note,accessed_at) "
                "VALUES('Local regression fixture','https://example.invalid/test','Test','AGGREGATES_IMPORTED','Fixture','2026-01-01')"
            ).lastrowid
            connection.execute(
                "INSERT INTO published_physiology_aggregates(publication_id,domain,metric_code,metric_label,value,unit,statistic,source_locator) "
                "VALUES(?,'HEART_RATE','LOCAL_TEST','Local fixture',77,'bpm','MEAN','Fixture')", (publication,)
            )
            connection.commit()
        finally:
            connection.close()
        for _ in range(2):
            summary = MODULE.import_database(self.database)
            self.assertEqual(summary["total_publications"], EXPECTED["physiology_publications"] + 1)
            self.assertEqual(summary["total_aggregate_rows"], EXPECTED["published_physiology_aggregates"] + 1)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute(
                "SELECT value FROM published_physiology_aggregates WHERE metric_code='LOCAL_TEST'"
            ).fetchall(), [(77.0,)])
        finally:
            connection.close()

    def test_failed_import_rolls_back_publications_and_aggregate_replacement(self):
        MODULE.import_database(self.database)
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                "CREATE TRIGGER reject_fixture BEFORE INSERT ON published_physiology_aggregates "
                "WHEN NEW.metric_code='HR_BPM' BEGIN SELECT RAISE(ABORT,'forced rollback'); END;"
            )
        finally:
            connection.close()
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError):
            MODULE.import_database(self.database)
        self.assertEqual(self.state(), before)

    def test_legacy_table_missing_dispersion_value_is_upgraded(self):
        connection = sqlite3.connect(self.database)
        try:
            schema = (PACKAGE / "schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema.replace("    dispersion_value REAL,\n", "", 1))
        finally:
            connection.close()
        summary = MODULE.import_database(self.database)
        self.assertEqual(summary["total_aggregate_rows"], EXPECTED["published_physiology_aggregates"])

    def test_cli_supports_named_and_legacy_paths_from_another_directory(self):
        for arguments in (["--db", str(self.database)], [str(self.database)]):
            result = subprocess.run(
                [sys.executable, str(IMPORTER), *arguments], cwd=self.directory,
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["total_aggregate_rows"], EXPECTED["published_physiology_aggregates"])


if __name__ == "__main__":
    unittest.main()
