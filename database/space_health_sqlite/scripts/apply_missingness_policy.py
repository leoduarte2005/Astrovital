#!/usr/bin/env python3
"""Apply the supplied missingness policy offline, preserving original measurements."""

import argparse
import gzip
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parents[1] / "var" / "space_health_demo.db"


def apply_values(c):
    """Rebuild managed audit summaries; missing numeric values remain NULL."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reasons=[
    ('NOT_PROVIDED_BY_SOURCE','Source record or publication did not provide a value for this field.',1,'Persist NULL and attach this reason; never replace with zero.'),
    ('NOT_MEASURED','The variable was not measured or collected in the study/record.',1,'Persist NULL and retain explicit study/collection note.'),
    ('NOT_APPLICABLE','The field does not apply to this record or source type.',1,'Persist NULL; do not count as a failed measurement.'),
    ('SENSOR_FAILURE','Source documents a failed, disconnected, or unusable sensor measurement.',1,'Persist NULL and record the failure evidence; do not interpolate critical signals.'),
    ('REJECTED_INCONSISTENCY','Source value was rejected for a documented inconsistency or QC reason.',1,'Preserve original source text if available; record QC rule and exclusion reason.'),
    ('AVAILABILITY_UNVERIFIED','Availability was not verified across relevant public repositories/sources.',1,'Persist no value and do not describe it as unavailable; mark search status unverified.'),
    ('BELOW_DETECTION_LIMIT','Measurement is reported below an assay detection/quantification limit.',0,'This is a censored result, not ordinary missingness; preserve qualifier and limit separately.'),
    ]
    c.executemany('INSERT INTO missing_reason_codes VALUES(?,?,?,?) ON CONFLICT(reason_code) DO UPDATE SET description=excluded.description,is_missing=excluded.is_missing,handling_rule=excluded.handling_rule',reasons)
    # Add a public-literature data source once, and link the article inventory to it.
    c.execute("INSERT OR IGNORE INTO data_sources(name,organization,url,accessed_at,access_mode,license_note,scope_note) VALUES(?,?,?,?,?,?,?)",('Public scientific literature: astronaut physiology and bone health','Multiple publishers / NASA-hosted manuscripts','https://pubmed.ncbi.nlm.nih.gov/','2026-11-14','PUBLIC_ARTICLE_AGGREGATE_TRANSCRIPTION','Article-specific reuse terms vary; citations/links retained.','Peer-reviewed and public ISS/spaceflight articles. Only published group/study aggregates are stored; no individual readings inferred.'))
    source_id=c.execute("select source_id from data_sources where name='Public scientific literature: astronaut physiology and bone health'").fetchone()[0]
    # Establish source lineage for article-derived aggregate values.
    if 'source_id' not in [r[1] for r in c.execute('pragma table_info(physiology_publications)')]: c.execute('ALTER TABLE physiology_publications ADD COLUMN source_id INTEGER REFERENCES data_sources(source_id)')
    c.execute('UPDATE physiology_publications SET source_id=? WHERE source_id IS NULL',(source_id,))
    if 'source_id' not in [r[1] for r in c.execute('pragma table_info(published_physiology_aggregates)')]: c.execute('ALTER TABLE published_physiology_aggregates ADD COLUMN source_id INTEGER REFERENCES data_sources(source_id)')
    if 'data_origin' not in [r[1] for r in c.execute('pragma table_info(published_physiology_aggregates)')]: c.execute("ALTER TABLE published_physiology_aggregates ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'REAL' CHECK(data_origin IN ('REAL','IMPUTED','DERIVED','SYNTHETIC'))")
    if 'quality_status' not in [r[1] for r in c.execute('pragma table_info(published_physiology_aggregates)')]: c.execute("ALTER TABLE published_physiology_aggregates ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'OBSERVED' CHECK(quality_status IN ('OBSERVED','MISSING','IMPUTED','DERIVED','SYNTHETIC','BELOW_DETECTION_LIMIT','REJECTED'))")
    c.execute('UPDATE published_physiology_aggregates SET source_id=? WHERE source_id IS NULL',(source_id,))
    # Restore all-empty EDA source rows from the compressed original source snapshot as explicit NULL records.
    # This preserves exact timestamps/zones and allows field-level missingness to remain queryable.
    eda=c.execute("SELECT dataset_id,source_id FROM datasets WHERE accession='EDA-TELEMETRY'").fetchone()
    if eda:
        snap=c.execute('SELECT content_gzip FROM source_snapshots WHERE dataset_id=? ORDER BY snapshot_id LIMIT 1',(eda[0],)).fetchone()
        if snap:
            raw=gzip.decompress(snap[0]).decode('utf-8')
            match=re.search(r'<script id="data" type="application/json">(.*?)</script>',raw,re.S)
            if not match: raise RuntimeError('EDA source snapshot could not be parsed; no omitted rows restored')
            wrapper=json.loads(match.group(1)); telemetry=json.loads(wrapper['telemetry_data'])
            batch_id=c.execute('SELECT batch_id FROM import_batches WHERE dataset_id=? ORDER BY batch_id LIMIT 1',(eda[0],)).fetchone()[0]
            mission_lookup={r[0]:r[1] for r in c.execute('SELECT mission_code,mission_id FROM missions')}
            restored=0
            for key,timestamps in telemetry.items():
                if not key.startswith('time_'): continue
                mission=key[5:]; mid=mission_lookup.get(mission)
                if mid is None: continue
                arrays={field:telemetry.get(f'{field}_{mission}',[]) for field in ('temperature_ground','temperature_iss','rh_ground','rh_iss','co2_ground','co2_iss')}
                for i,raw_ts in enumerate(timestamps):
                    for zone,suffix in [('GROUND_CONTROL','ground'),('ISS_HARDWARE','iss')]:
                        vals=[]
                        for field in (f'temperature_{suffix}',f'rh_{suffix}',f'co2_{suffix}'):
                            x=arrays[field][i] if i<len(arrays[field]) else None
                            try:
                                v=float(x) if x is not None else None
                                vals.append(v if v is not None and math.isfinite(v) else None)
                            except (TypeError,ValueError): vals.append(None)
                        if any(v is not None for v in vals): continue
                        ts=str(raw_ts); ts_utc=ts.replace(' ','T')+('Z' if not ts.endswith('Z') else '')
                        cur=c.execute('''INSERT OR IGNORE INTO environmental_measurements(dataset_id,batch_id,mission_id,timestamp_raw,timestamp_utc,zone,temperature_c,relative_humidity_percent,carbon_dioxide_ppm,data_class,source_record_ref,quality_flags) VALUES(?,?,?,?,?,?,NULL,NULL,NULL,'REAL',?,'SOURCE_ALL_NUMERIC_VALUES_MISSING')''',(eda[0],batch_id,mid,ts,ts_utc,zone,f'{mission}:{i}:{suffix}'))
                        restored+=cur.rowcount
            if restored:
                batch=c.execute('SELECT skipped_records,inserted_records FROM import_batches WHERE batch_id=?',(batch_id,)).fetchone()
                c.execute("UPDATE import_batches SET inserted_records=inserted_records+?,skipped_records=MAX(0,skipped_records-?),details=COALESCE(details,'') || ? WHERE batch_id=?",(restored,restored,f' Restored {restored} all-empty source rows from snapshot as timestamped REAL records with NULL measures.',batch_id))
                # A consistency guard: all source-empty rows recorded as skipped must now be preserved.
                if batch and batch[0]!=restored: raise RuntimeError(f'Expected {batch[0]} all-empty rows from import batch, restored {restored}.')
    # Materialize null cell reasons for source-imported measurements and published aggregates.
    # Existing data_class is kept unchanged; this adds a normalized, queryable reason per NULL cell.
    c.execute("DELETE FROM field_quality_events WHERE process_id='missingness-audit-v1'")
    def missing_rows(table,pk,field,reason,source_expr,dataset_expr,where=''):
        sql=f'''INSERT OR IGNORE INTO field_quality_events(table_name,record_pk,field_name,data_origin,quality_status,missing_reason,source_id,dataset_id,transformed_at,process_id,notes)
          SELECT ?,t.{pk},?,COALESCE(t.data_class,'REAL'),'MISSING',?,{source_expr},{dataset_expr},?,?,? FROM {table} t {where}'''
        c.execute(sql,(table,field,reason,now,'missingness-audit-v1','NULL field in imported source row; value was not modified.'))
    # Dataset/source ids via datasets; for imported row tables.
    join_env='JOIN datasets d ON d.dataset_id=t.dataset_id'
    for f in ['temperature_c','relative_humidity_percent','carbon_dioxide_ppm']:
        missing_rows('environmental_measurements','measurement_id',f,'NOT_PROVIDED_BY_SOURCE','d.source_id','t.dataset_id',join_env+f' WHERE t.{f} IS NULL')
    # Distinguish EDA-only instrument/location fields (not applicable to its daily series) from unprovided RadLab metadata.
    for f in ['instrument_id','module','latitude_deg','longitude_deg','altitude_km','magnetic_b_nt','magnetic_l']:
        missing_rows('radiation_measurements','radiation_id',f,'NOT_APPLICABLE','d.source_id','t.dataset_id',join_env+f" WHERE t.{f} IS NULL AND t.dataset_id=(SELECT dataset_id FROM datasets WHERE accession='EDA-RADIATION')")
    for f in ['instrument_id','module','latitude_deg','longitude_deg','altitude_km','magnetic_b_nt','magnetic_l','mission_id']:
        missing_rows('radiation_measurements','radiation_id',f,'NOT_PROVIDED_BY_SOURCE','d.source_id','t.dataset_id',join_env+f" WHERE t.{f} IS NULL AND t.dataset_id=(SELECT dataset_id FROM datasets WHERE accession LIKE 'RADLAB-%')")
    missing_rows('gene_expression_measurements','expression_id','reported_value','NOT_PROVIDED_BY_SOURCE','d.source_id','t.dataset_id',join_env+' WHERE t.reported_value IS NULL')
    for f in ['fold_change_ratio','log2_ratio','f_test','p_value','adjusted_p_value']:
        missing_rows('differential_expression_results','result_id',f,'NOT_PROVIDED_BY_SOURCE','d.source_id','t.dataset_id',join_env+f' WHERE t.{f} IS NULL')
    # Optional aggregate descriptors absent from the article are explicitly source-unreported.
    article_fields=['dispersion_type','dispersion_value','dispersion_low','dispersion_high','sample_size','cohort','phase','posture','intervention','p_value','interpretation_note']
    for f in article_fields:
        c.execute(f'''INSERT OR IGNORE INTO field_quality_events(table_name,record_pk,field_name,data_origin,quality_status,missing_reason,source_id,transformed_at,process_id,notes)
           SELECT 'published_physiology_aggregates',a.aggregate_id,?,'REAL','MISSING','NOT_PROVIDED_BY_SOURCE',a.source_id,?,'missingness-audit-v1','Article did not report this optional aggregate descriptor for this result.' FROM published_physiology_aggregates a WHERE a.{f} IS NULL''',(f,now))
    # Dataset-variable completeness, conditional on rows returned by the source. This is not temporal coverage.
    c.execute("DELETE FROM dataset_field_completeness WHERE dataset_id IN (SELECT dataset_id FROM datasets WHERE accession IN ('EDA-TELEMETRY','EDA-RADIATION','RADLAB-DOSTEL-2022-04-01','OSD-53'))")
    def add_summary(dataset_accession,table,pk,field,source_sql,where=''):
        ds=c.execute('SELECT dataset_id,source_id FROM datasets WHERE accession=?',(dataset_accession,)).fetchone()
        if not ds:return
        q=f'SELECT COUNT(*) AS n, SUM({field} IS NOT NULL) AS obs FROM {table} {where}'
        q += ' AND dataset_id=?' if where.strip() else ' WHERE dataset_id=?'
        n,obs=c.execute(q,(ds[0],)).fetchone(); n=int(n or 0);obs=int(obs or 0); miss=n-obs
        pct=(100*obs/n) if n else None
        cls=('NOT_ASSESSABLE' if pct is None else 'HIGH' if pct>=95 else 'MODERATE' if pct>=80 else 'LOW' if pct>=50 else 'CRITICAL')
        c.execute('''INSERT INTO dataset_field_completeness(dataset_id,source_id,table_name,field_name,expected_count,observed_count,missing_count,completeness_pct,completeness_class,denominator_basis,calculated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(ds[0],ds[1],table,field,n,obs,miss,pct,cls,'RETURNED_SOURCE_ROWS; describes cell availability among imported rows only; does not estimate unobserved time points',now))
    for f in ['temperature_c','relative_humidity_percent','carbon_dioxide_ppm']:
        add_summary('EDA-TELEMETRY','environmental_measurements','measurement_id',f,'source-row count')
    for acc in ['EDA-RADIATION','RADLAB-DOSTEL-2022-04-01']:
        add_summary(acc,'radiation_measurements','radiation_id','value','source-row count',f"WHERE dataset_id=(SELECT dataset_id FROM datasets WHERE accession='{acc}')")
    add_summary('OSD-53','gene_expression_measurements','expression_id','reported_value','source-row count')
    for f in ['mean_preflight','mean_postflight','fold_change_ratio','log2_ratio','f_test','p_value','adjusted_p_value']:
        add_summary('OSD-53','differential_expression_results','result_id',f,'source-row count')
    # Per-study/per-period completeness for source rows with timestamps. These denominators count
    # values expected at timestamps actually listed by the source; they do not estimate omitted times.
    def insert_group_summary(accession,table,field,study_key,pstart,pend,n,obs,note):
        ds=c.execute('SELECT dataset_id,source_id FROM datasets WHERE accession=?',(accession,)).fetchone()
        if not ds:return
        n=int(n or 0);obs=int(obs or 0);miss=n-obs;pct=100*obs/n if n else None
        cls='NOT_ASSESSABLE' if pct is None else 'HIGH' if pct>=95 else 'MODERATE' if pct>=80 else 'LOW' if pct>=50 else 'CRITICAL'
        c.execute('''INSERT INTO dataset_field_completeness(dataset_id,source_id,table_name,field_name,study_key,period_start,period_end,expected_count,observed_count,missing_count,completeness_pct,completeness_class,denominator_basis,calculated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(ds[0],ds[1],table,field,study_key,pstart,pend,n,obs,miss,pct,cls,note,now))
    for field in ['temperature_c','relative_humidity_percent','carbon_dioxide_ppm']:
        grouped=c.execute(f'''SELECT m.mission_code,substr(e.timestamp_utc,1,4) yr,MIN(e.timestamp_utc),MAX(e.timestamp_utc),COUNT(*),SUM(e.{field} IS NOT NULL)
           FROM environmental_measurements e JOIN missions m USING(mission_id) WHERE e.dataset_id=(SELECT dataset_id FROM datasets WHERE accession='EDA-TELEMETRY') GROUP BY m.mission_code,yr ORDER BY m.mission_code,yr''').fetchall()
        for mission,yr,first,last,n,obs in grouped:
            insert_group_summary('EDA-TELEMETRY','environmental_measurements',field,mission,first,last,n,obs,'Rows and missing numeric values reported by NASA EDA timestamps within this mission-label period; no unobserved timepoints inferred.')
    for accession in ['EDA-RADIATION','RADLAB-DOSTEL-2022-04-01']:
        groups=c.execute('''SELECT radiation_metric,substr(timestamp_utc,1,4),MIN(timestamp_utc),MAX(timestamp_utc),COUNT(*),SUM(value IS NOT NULL)
          FROM radiation_measurements WHERE dataset_id=(SELECT dataset_id FROM datasets WHERE accession=?) GROUP BY radiation_metric,substr(timestamp_utc,1,4) ORDER BY radiation_metric,substr(timestamp_utc,1,4)''',(accession,)).fetchall()
        for metric,yr,first,last,n,obs in groups:
            insert_group_summary(accession,'radiation_measurements','value',metric,first,last,n,obs,'Values among source timestamps in this metric/year; this does not estimate missing timestamps or instrument cadence.')
    # These are source rows intentionally omitted because all numeric telemetry cells were blank; batch count is preserved.
    c.execute("DELETE FROM source_row_exclusions WHERE dataset_id IN (SELECT dataset_id FROM datasets WHERE accession='EDA-TELEMETRY') AND reason_code='NOT_PROVIDED_BY_SOURCE'")
    c.execute('''INSERT INTO source_row_exclusions(batch_id,dataset_id,source_id,exclusion_count,reason_code,record_level_detail_available,recorded_at,notes)
     SELECT b.batch_id,b.dataset_id,d.source_id,b.skipped_records,'NOT_PROVIDED_BY_SOURCE',0,?,
     'All-empty environmental source rows/zones were excluded from measurement fact table; exclusion count preserved from import batch; row-level missing cells were not retained.'
     FROM import_batches b JOIN datasets d USING(dataset_id) WHERE d.accession='EDA-TELEMETRY' AND b.skipped_records>0''',(now,))
    # Explicitly record categories not established by the current imported sources as unverified rather than unavailable.
    c.execute('DELETE FROM field_availability_registry WHERE dataset_id IS NULL AND source_id=?',(source_id,))
    for domain,field,note in [
     ('PHYSIOLOGY','HRV','No continuous ISS HRV measurements imported in this build; source availability has not been exhaustively verified.'),
     ('PHYSIOLOGY','SPO2','No SpO2 observations imported; public-source availability remains unverified.'),
     ('PHYSIOLOGY','RESPIRATION','No respiratory-rate measurements imported; public-source availability remains unverified.'),
     ('PHYSIOLOGY','BODY_TEMPERATURE','No crew body-temperature measurements imported; environmental temperature is not a substitute; availability unverified.'),
     ('PHYSIOLOGY','ECG','No ECG waveform/individual observations imported; public-source availability remains unverified.'),
     ('PHYSIOLOGY','SLEEP','No crew sleep observations imported; public-source availability remains unverified.'),
     ('PHYSIOLOGY','ACTIVITY','No individual crew activity observations imported; public-source availability remains unverified.'),
     ('BIOMEDICAL','LABORATORY_BIOMARKERS','No general clinical laboratory/biomarker panel imported; source availability not exhaustively verified.'),
     ('SENSOR_SPECIFICATION','ACCURACY_RESOLUTION_CALIBRATION','Imported source interfaces do not fully specify all sensor accuracy, resolution or calibration values; retain NULL/unverified.'),
     ('MISSION','CREW_MISSION_CHARACTERISTICS','EDA labels refer to experiments and are not a complete crew mission catalog; availability remains unverified.')]:
        c.execute('INSERT OR REPLACE INTO field_availability_registry(domain,field_name,dataset_id,source_id,availability_status,assessed_at,evidence_note) VALUES(?,?,NULL,? ,"AVAILABILITY_UNVERIFIED",?,?)',(domain,field,source_id,now,note))
    # Summarize observed timestamp spans and large observed gaps without inventing expected cadence.
    c.execute("DELETE FROM temporal_coverage_summary WHERE dataset_id IN (SELECT dataset_id FROM datasets WHERE accession IN ('EDA-TELEMETRY','EDA-RADIATION','RADLAB-DOSTEL-2022-04-01'))")

    def parse_ts(x):
        if not x:return None
        try:return datetime.fromisoformat(x.replace('Z','+00:00'))
        except ValueError:
            for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%Y-%m-%d'):
                try:return datetime.strptime(x,fmt)
                except ValueError: pass
        return None

    def temporal_insert(accession,table,key_sql,timecol,filter_sql=''):
        ds=c.execute('SELECT dataset_id,source_id FROM datasets WHERE accession=?',(accession,)).fetchone()
        if not ds:return
        query=f'SELECT {key_sql} AS sk,{timecol} AS ts,COUNT(*) AS n FROM {table} {filter_sql} GROUP BY sk,ts ORDER BY sk,ts'
        from collections import defaultdict
        groups=defaultdict(list); counts=defaultdict(int)
        for row in c.execute(query):
            key=row[0]; ts=parse_ts(row[1]); n=row[2]
            if ts is not None: groups[key].append(ts); counts[(key,ts)]+=n
        for key,times in groups.items():
            gaps=[(b-a).total_seconds() for a,b in zip(times,times[1:]) if b>=a]
            total_rows=sum(counts[(key,t)] for t in times)
            dup=total_rows-len(times)
            c.execute('''INSERT INTO temporal_coverage_summary(dataset_id,source_id,table_name,series_key,time_field,first_observed_at,last_observed_at,row_count,distinct_timestamp_count,duplicate_timestamp_rows,max_observed_gap_seconds,gaps_over_1day,expected_frequency_seconds,expected_count,completeness_pct,completeness_class,assessment_note,calculated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,'NOT_ASSESSABLE',?,?)''',(ds[0],ds[1],table,str(key),timecol,times[0].isoformat(),times[-1].isoformat(),total_rows,len(times),dup,max(gaps) if gaps else 0,sum(g>86400 for g in gaps),'Sampling frequency/expected schedule not established from source metadata; >1-day gaps are descriptive spans, not inferred missing sample counts.',now))
    # Environmental per mission and zone; radiation per dataset metric.
    temporal_insert('EDA-TELEMETRY','environmental_measurements',"m.mission_code || '|' || e.zone",'e.timestamp_utc',"e JOIN missions m USING(mission_id) WHERE e.dataset_id=(SELECT dataset_id FROM datasets WHERE accession='EDA-TELEMETRY')")
    temporal_insert('EDA-RADIATION','radiation_measurements','radiation_metric','timestamp_utc',"WHERE dataset_id=(SELECT dataset_id FROM datasets WHERE accession='EDA-RADIATION')")
    temporal_insert('RADLAB-DOSTEL-2022-04-01','radiation_measurements','radiation_metric','timestamp_utc',"WHERE dataset_id=(SELECT dataset_id FROM datasets WHERE accession='RADLAB-DOSTEL-2022-04-01')")
    # UTC-normalized timestamps are derived representations; raw source text remains available beside them.
    c.execute("DELETE FROM field_transformation_registry WHERE process_id='missingness-audit-v1'")
    for acc,table,field,src,description in [('EDA-TELEMETRY','environmental_measurements','timestamp_utc','timestamp_raw','Normalized source Controller_Time_GMT text to UTC timestamp according to importer parser.'),('EDA-RADIATION','radiation_measurements','timestamp_utc','timestamp_raw','Normalized source date/timestamp to UTC representation according to importer parser.'),('RADLAB-DOSTEL-2022-04-01','radiation_measurements','timestamp_utc','timestamp_raw','Normalized RadLab timestamp to UTC representation; original timestamp_raw is retained.')]:
     ds=c.execute('SELECT dataset_id,source_id FROM datasets WHERE accession=?',(acc,)).fetchone()
     if ds:
      n=c.execute(f'SELECT COUNT(*) FROM {table} WHERE dataset_id=? AND {field} IS NOT NULL',(ds[0],)).fetchone()[0]
      c.execute("INSERT OR REPLACE INTO field_transformation_registry(table_name,field_name,data_origin,source_field_name,method_description,records_affected,source_id,dataset_id,transformed_at,process_id,original_preserved,notes) VALUES(?,?,'DERIVED',?,?,?,?,?,?,?,1,?)",(table,field,src,description,n,ds[1],ds[0],now,'missingness-audit-v1','Source value is preserved in the raw timestamp column; no numeric measurement imputation was performed.'))
    return {
        "missing_cells": c.execute("SELECT COUNT(*) FROM field_quality_events WHERE quality_status='MISSING'").fetchone()[0],
        "missing_reasons": dict(c.execute("SELECT missing_reason,COUNT(*) FROM field_quality_events WHERE quality_status='MISSING' GROUP BY missing_reason")),
        "completeness_rows": c.execute("SELECT COUNT(*) FROM dataset_field_completeness").fetchone()[0],
        "temporal_series": c.execute("SELECT COUNT(*) FROM temporal_coverage_summary").fetchone()[0],
        "imputed_values": c.execute("SELECT COUNT(*) FROM field_quality_events WHERE quality_status='IMPUTED'").fetchone()[0],
    }


def apply_database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, isolation_level=None)
    try:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=5000")
        columns = {row[1] for row in c.execute("PRAGMA table_info(dataset_field_completeness)")}
        migration = ""
        if columns and "study_key" not in columns:
            migration = "ALTER TABLE dataset_field_completeness ADD COLUMN study_key TEXT;\n"
        c.executescript("BEGIN IMMEDIATE;\n" + migration + (ROOT / "schema.sql").read_text(encoding="utf-8"))
        summary = apply_values(c)
        if c.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("Missingness policy produced invalid foreign keys")
        c.execute("COMMIT")
        return summary
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", type=Path, help="Legacy positional database path.")
    parser.add_argument("--db", type=Path, help="Target database; defaults to var/space_health_demo.db.")
    args = parser.parse_args()
    if args.database is not None and args.db is not None:
        parser.error("Use either --db or the positional database path.")
    path = args.db or args.database or DEFAULT_DB
    try:
        summary = apply_database(path)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        parser.exit(1, f"Missingness policy failed: {error}\n")
    print(json.dumps({"database": str(path), **summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
