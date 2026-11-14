#!/usr/bin/env python3
"""Inspect the imported research database offline, using a read-only connection."""

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / "space_health_sqlite/space_health.db"
INVENTORY_SQL = """
SELECT d.accession, s.name AS source, d.data_kind, d.status,
       (SELECT COUNT(*) FROM environmental_measurements x WHERE x.dataset_id=d.dataset_id) AS environmental_rows,
       (SELECT COUNT(*) FROM radiation_measurements x WHERE x.dataset_id=d.dataset_id) AS radiation_rows,
       (SELECT COUNT(*) FROM biomedical_samples x WHERE x.dataset_id=d.dataset_id) AS sample_rows,
       (SELECT COUNT(*) FROM gene_expression_measurements x WHERE x.dataset_id=d.dataset_id) AS gene_expression_rows,
       (SELECT COUNT(*) FROM differential_expression_results x WHERE x.dataset_id=d.dataset_id) AS differential_rows,
       (SELECT COUNT(*) FROM synthetic_checkins x WHERE x.dataset_id=d.dataset_id) AS synthetic_rows,
       (SELECT COUNT(*) FROM iss_physiology_study_catalog x WHERE x.dataset_id=d.dataset_id) AS study_catalog_rows
FROM datasets d JOIN data_sources s USING(source_id)
ORDER BY d.dataset_id
"""


def statements(text):
    pending = ""
    for character in text:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if pending.strip():
        yield pending


def physiology_summary(connection):
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"physiology_publications", "published_physiology_aggregates"} <= tables:
        return {"available": False}
    return {
        "available": True,
        "publications": connection.execute("SELECT COUNT(*) FROM physiology_publications").fetchone()[0],
        "publications_with_aggregates": connection.execute(
            "SELECT COUNT(DISTINCT publication_id) FROM published_physiology_aggregates"
        ).fetchone()[0],
        "publications_without_transcribed_values": connection.execute(
            "SELECT COUNT(*) FROM physiology_publications WHERE public_data_status!='AGGREGATES_IMPORTED'"
        ).fetchone()[0],
        "aggregate_rows": connection.execute("SELECT COUNT(*) FROM published_physiology_aggregates").fetchone()[0],
        "by_domain": [dict(row) for row in connection.execute(
            "SELECT domain,COUNT(*) AS aggregate_rows FROM published_physiology_aggregates GROUP BY domain ORDER BY domain"
        )],
        "negative_standard_deviations": connection.execute(
            "SELECT COUNT(*) FROM published_physiology_aggregates WHERE dispersion_type='SD' AND dispersion_value<0"
        ).fetchone()[0],
    }


def missingness_summary(connection):
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "field_quality_events" not in tables:
        return {"available": False}
    return {
        "available": True,
        "missing_cells": connection.execute("SELECT COUNT(*) FROM field_quality_events WHERE quality_status='MISSING'").fetchone()[0],
        "by_reason": [dict(row) for row in connection.execute(
            "SELECT missing_reason,COUNT(*) AS cells FROM field_quality_events WHERE quality_status='MISSING' GROUP BY missing_reason ORDER BY missing_reason"
        )],
        "completeness_summaries": connection.execute("SELECT COUNT(*) FROM dataset_field_completeness").fetchone()[0],
        "temporal_series": connection.execute("SELECT COUNT(*) FROM temporal_coverage_summary").fetchone()[0],
        "imputed_events": connection.execute("SELECT COUNT(*) FROM field_quality_events WHERE quality_status='IMPUTED'").fetchone()[0],
        "all_empty_environmental_rows": connection.execute(
            "SELECT COUNT(*) FROM environmental_measurements WHERE temperature_c IS NULL AND relative_humidity_percent IS NULL AND carbon_dioxide_ppm IS NULL"
        ).fetchone()[0],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--queries", type=Path, help="SQL examples to execute instead of the inventory.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum displayed rows per query (default: 25).")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    try:
        sql = args.queries.read_text(encoding="utf-8") if args.queries else INVENTORY_SQL
        connection = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            for index, statement in enumerate(statements(sql), 1):
                cursor = connection.execute(statement)
                if cursor.description is None:
                    continue
                rows = cursor.fetchmany(args.limit + 1)
                result = {"query": index, "rows": [dict(row) for row in rows[:args.limit]],
                          "display_limit": args.limit, "more_rows": len(rows) > args.limit}
                if args.queries is None:
                    result["published_physiology"] = physiology_summary(connection)
                    result["missingness"] = missingness_summary(connection)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Research database: {error}\n")


if __name__ == "__main__":
    main()
