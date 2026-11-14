#!/usr/bin/env python3
"""Run requested integrity/content checks and write a factual validation report."""
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=ROOT/'space_health.db'); p.add_argument('--out',type=Path,default=ROOT.parents[1]/'var/research/validation_report.json'); p.add_argument('--quiet',action='store_true',help='Print check summaries, quality finding counts and report paths.'); a=p.parse_args()
    c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA query_only=ON')
    integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
    fk=[dict(r) for r in c.execute('PRAGMA foreign_key_check')]
    tables=['data_sources','datasets','dataset_fields','import_batches','missions','scientific_references','risk_catalog','environmental_measurements','radiation_measurements','biomedical_samples','gene_expression_measurements','differential_expression_results','synthetic_subjects','synthetic_checkins','reference_parameters','source_snapshots','iss_physiology_study_catalog','physiology_publications','published_physiology_aggregates','missing_reason_codes','field_quality_events','dataset_field_completeness','source_row_exclusions','field_availability_registry','temporal_coverage_summary','field_transformation_registry']
    counts={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}
    by_dataset=[dict(r) for r in c.execute('''SELECT d.accession,d.title,d.data_kind,d.status,
      COALESCE((SELECT COUNT(*) FROM environmental_measurements x WHERE x.dataset_id=d.dataset_id),0) env_rows,
      COALESCE((SELECT COUNT(*) FROM radiation_measurements x WHERE x.dataset_id=d.dataset_id),0) radiation_rows,
      COALESCE((SELECT COUNT(*) FROM gene_expression_measurements x WHERE x.dataset_id=d.dataset_id),0) gene_expression_rows,
      COALESCE((SELECT COUNT(*) FROM differential_expression_results x WHERE x.dataset_id=d.dataset_id),0) differential_rows,
      COALESCE((SELECT COUNT(*) FROM synthetic_checkins x WHERE x.dataset_id=d.dataset_id),0) synthetic_rows
      FROM datasets d ORDER BY d.dataset_id''')]
    batch_rows=[dict(r) for r in c.execute('SELECT batch_id,d.dataset_id,d.accession,d.title,b.status,b.source_records,b.inserted_records,b.skipped_records,b.sha256,b.details FROM import_batches b JOIN datasets d USING(dataset_id) ORDER BY batch_id')]
    env_stats=dict(c.execute('''SELECT COUNT(*) AS rows,COUNT(DISTINCT mission_id) AS missions,MIN(timestamp_raw) AS first_source_timestamp,MAX(timestamp_raw) AS last_source_timestamp,
      SUM(temperature_c IS NOT NULL) AS temp_values,SUM(relative_humidity_percent IS NOT NULL) AS rh_values,SUM(carbon_dioxide_ppm IS NOT NULL) AS co2_values,
      SUM(quality_flags LIKE '%OUTSIDE_0_100%') AS flagged_rh_values FROM environmental_measurements''').fetchone())
    for key in ('temp_values','rh_values','co2_values','flagged_rh_values'):
        env_stats[key]=env_stats[key] or 0
    env_by_mission=[dict(r) for r in c.execute('''SELECT m.mission_code,COUNT(*) AS rows,MIN(e.timestamp_raw) AS first_source_timestamp,MAX(e.timestamp_raw) AS last_source_timestamp,
      SUM(e.temperature_c IS NOT NULL) AS temp_values,SUM(e.relative_humidity_percent IS NOT NULL) AS rh_values,SUM(e.carbon_dioxide_ppm IS NOT NULL) AS co2_values
      FROM environmental_measurements e JOIN missions m USING(mission_id) GROUP BY m.mission_code ORDER BY m.mission_code''')]
    env_by_zone=[dict(r) for r in c.execute('SELECT zone,COUNT(*) AS rows FROM environmental_measurements GROUP BY zone ORDER BY zone')]
    rad_stats=[dict(r) for r in c.execute('''SELECT d.accession,radiation_metric,unit,COUNT(*) AS rows,MIN(timestamp_raw) AS first_source_timestamp,MAX(timestamp_raw) AS last_source_timestamp,MIN(value) AS min_value,MAX(value) AS max_value FROM radiation_measurements r JOIN datasets d USING(dataset_id) GROUP BY d.accession,radiation_metric,unit ORDER BY d.accession,radiation_metric''')]
    radlab_metadata=dict(c.execute("SELECT COUNT(DISTINCT timestamp_raw) AS timestamps, SUM(magnetic_b_nt IS NOT NULL) AS b_values, SUM(magnetic_l IS NOT NULL) AS l_values, SUM(latitude_deg IS NOT NULL) AS latitude_values, SUM(longitude_deg IS NOT NULL) AS longitude_values, SUM(altitude_km IS NOT NULL) AS altitude_values FROM radiation_measurements WHERE dataset_id=(SELECT dataset_id FROM datasets WHERE accession='RADLAB-DOSTEL-2022-04-01') AND radiation_metric='ABSORBED_DOSE_RATE'").fetchone())
    # Guard against category bleed, duplicates, invalid scales, broken provenance.
    duplicate_refs=c.execute('SELECT COUNT(*) FROM (SELECT source_record_ref FROM environmental_measurements GROUP BY source_record_ref HAVING COUNT(*)>1)').fetchone()[0]
    duplicate_radiation_refs=c.execute('SELECT COUNT(*) FROM (SELECT dataset_id,source_record_ref,radiation_metric FROM radiation_measurements GROUP BY dataset_id,source_record_ref,radiation_metric HAVING COUNT(*)>1)').fetchone()[0]
    bad_synth=c.execute("SELECT COUNT(*) FROM synthetic_checkins WHERE data_class!='SYNTHETIC' OR sleep_quality_1_5 NOT BETWEEN 1 AND 5 OR fatigue_1_5 NOT BETWEEN 1 AND 5 OR mood_1_5 NOT BETWEEN 1 AND 5 OR pain_0_10 NOT BETWEEN 0 AND 10").fetchone()[0]
    physiology_catalog_rows=c.execute('SELECT COUNT(*) FROM iss_physiology_study_catalog').fetchone()[0]
    physiology_catalog_invalid=c.execute("SELECT COUNT(*) FROM iss_physiology_study_catalog c JOIN datasets d USING(dataset_id) WHERE c.observation_access_status!='METADATA_ONLY' OR d.status!='METADATA_ONLY' OR d.data_kind!='CATALOG'").fetchone()[0]
    missing_provenance=c.execute('SELECT COUNT(*) FROM environmental_measurements WHERE dataset_id IS NULL OR batch_id IS NULL OR source_record_ref IS NULL').fetchone()[0]+c.execute('SELECT COUNT(*) FROM radiation_measurements WHERE dataset_id IS NULL OR batch_id IS NULL OR source_record_ref IS NULL').fetchone()[0]
    missing_provenance+=c.execute('SELECT COUNT(*) FROM gene_expression_measurements WHERE dataset_id IS NULL OR batch_id IS NULL OR source_record_ref IS NULL').fetchone()[0]+c.execute('SELECT COUNT(*) FROM differential_expression_results WHERE dataset_id IS NULL OR batch_id IS NULL OR source_record_ref IS NULL').fetchone()[0]
    agg_orphans=c.execute('SELECT COUNT(*) FROM published_physiology_aggregates a LEFT JOIN physiology_publications p USING(publication_id) WHERE p.publication_id IS NULL').fetchone()[0]
    physiology_domains=[dict(r) for r in c.execute('SELECT domain,COUNT(*) AS rows FROM published_physiology_aggregates GROUP BY domain ORDER BY domain')]
    quality_reason_orphans=c.execute("SELECT COUNT(*) FROM field_quality_events q LEFT JOIN missing_reason_codes r ON r.reason_code=q.missing_reason WHERE q.quality_status='MISSING' AND (r.reason_code IS NULL OR r.is_missing!=1 OR q.source_id IS NULL)").fetchone()[0]
    completeness_bad=c.execute("""SELECT COUNT(*) FROM dataset_field_completeness
      WHERE expected_count IS NOT NULL AND (
        expected_count<0 OR observed_count<0 OR missing_count<0
        OR observed_count+missing_count!=expected_count
        OR completeness_class IS NULL
        OR (expected_count=0 AND (completeness_pct IS NOT NULL OR completeness_class!='NOT_ASSESSABLE'))
        OR (expected_count>0 AND (
          completeness_pct IS NULL
          OR ABS(completeness_pct-100.0*observed_count/expected_count)>0.000001
          OR (completeness_pct>=95 AND completeness_class!='HIGH')
          OR (completeness_pct>=80 AND completeness_pct<95 AND completeness_class!='MODERATE')
          OR (completeness_pct>=50 AND completeness_pct<80 AND completeness_class!='LOW')
          OR (completeness_pct<50 AND completeness_class!='CRITICAL')
        )))""").fetchone()[0]
    temporal_frequency_bad=c.execute("SELECT COUNT(*) FROM temporal_coverage_summary WHERE expected_count IS NOT NULL AND expected_frequency_seconds IS NULL").fetchone()[0]
    imputed_rows=c.execute("SELECT (SELECT COUNT(*) FROM field_quality_events WHERE quality_status='IMPUTED') + (SELECT COUNT(*) FROM published_physiology_aggregates WHERE data_origin='IMPUTED' OR quality_status='IMPUTED')").fetchone()[0]
    synthetic_label_bad=c.execute("SELECT COUNT(*) FROM synthetic_checkins WHERE data_class!='SYNTHETIC'").fetchone()[0]
    missing_source_record_bad=c.execute("SELECT COUNT(*) FROM field_quality_events WHERE quality_status='MISSING' AND missing_reason IS NULL").fetchone()[0]
    null_event_mismatch=0
    null_tables={'environmental_measurements':'measurement_id','radiation_measurements':'radiation_id','gene_expression_measurements':'expression_id','differential_expression_results':'result_id','published_physiology_aggregates':'aggregate_id'}
    event_groups=c.execute("SELECT table_name,field_name,COUNT(*) AS n FROM field_quality_events WHERE quality_status='MISSING' GROUP BY table_name,field_name").fetchall()
    for event in event_groups:
        table=event['table_name']; field=event['field_name']; key=null_tables.get(table)
        if key is None:
            null_event_mismatch+=event['n']; continue
        columns={row[1] for row in c.execute('PRAGMA table_info("'+table+'")')}
        if field not in columns:
            null_event_mismatch+=event['n']; continue
        quoted_field='"'+field.replace('"','""')+'"'
        sql=(f'SELECT COUNT(*) FROM field_quality_events q LEFT JOIN "{table}" t ON t."{key}"=q.record_pk '
             f"WHERE q.quality_status='MISSING' AND q.table_name=? AND q.field_name=? "
             f'AND (t."{key}" IS NULL OR t.{quoted_field} IS NOT NULL)')
        null_event_mismatch+=c.execute(sql,(table,field)).fetchone()[0]
    publications_without_values=c.execute("SELECT COUNT(*) FROM physiology_publications WHERE public_data_status!='AGGREGATES_IMPORTED'").fetchone()[0]
    quality_findings=[dict(r) for r in c.execute("SELECT a.aggregate_id,a.publication_id,p.doi,a.metric_code,a.dispersion_value,'NEGATIVE_STANDARD_DEVIATION' AS issue FROM published_physiology_aggregates a JOIN physiology_publications p USING(publication_id) WHERE a.dispersion_type='SD' AND a.dispersion_value<0 ORDER BY a.aggregate_id")]
    checks={'missingness_reasons_and_provenance':'PASS' if quality_reason_orphans==0 and missing_source_record_bad==0 and null_event_mismatch==0 else 'FAIL','completeness_thresholds_and_denominators':'PASS' if completeness_bad==0 else 'FAIL','temporal_expected_counts_require_frequency':'PASS' if temporal_frequency_bad==0 else 'FAIL','no_unlabeled_imputation':'PASS' if imputed_rows==0 else 'FAIL','synthetic_origin_labeled':'PASS' if synthetic_label_bad==0 else 'FAIL','published_physiology_sources_and_aggregates':'PASS' if agg_orphans==0 else 'FAIL','sqlite_integrity_check':'PASS' if integrity=='ok' else 'FAIL','foreign_key_check':'PASS' if not fk else 'FAIL','environmental_provenance_duplicates':'PASS' if duplicate_refs==0 else 'FAIL','radiation_provenance_duplicates':'PASS' if duplicate_radiation_refs==0 else 'FAIL','synthetic_label_and_scale':'PASS' if bad_synth==0 else 'FAIL','real_measurement_provenance':'PASS' if missing_provenance==0 else 'FAIL','physiology_catalog_separated_from_observations':'PASS' if physiology_catalog_invalid==0 else 'FAIL'}
    result={'generated_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'database':a.db.name,'database_bytes':a.db.stat().st_size,'integrity_check':integrity,'foreign_key_violations':fk,'counts':counts,'datasets':by_dataset,'import_batches':batch_rows,'environmental_summary':env_stats,'environmental_by_zone':env_by_zone,'environmental_by_mission':env_by_mission,'radiation_summary':rad_stats,'radlab_context_fields':radlab_metadata,'published_physiology_by_domain':physiology_domains,'published_physiology_orphan_rows':agg_orphans,'publications_without_transcribed_values':publications_without_values,'published_physiology_quality_findings':quality_findings,'missing_quality_events':counts['field_quality_events'],'missing_quality_provenance_errors':quality_reason_orphans,'missing_event_nonnull_or_unresolved':null_event_mismatch,'completeness_summary_rows':counts['dataset_field_completeness'],'temporal_coverage_series':counts['temporal_coverage_summary'],'documented_source_row_exclusions':counts['source_row_exclusions'],'imputed_value_count':imputed_rows,'iss_physiology_catalog_rows':physiology_catalog_rows,'iss_physiology_catalog_invalid_rows':physiology_catalog_invalid,'additional_checks':checks,'limitations':['NASA EDA environmental rows are experiment hardware/cage and ground-control telemetry; they are not astronaut clinical or personal data.','NASA RadLab readings are instrument measurements, not individual dosimeter records or clinical outcomes.','Missing numeric values are stored as NULL and classified in field_quality_events; no automatic statistical imputation has been applied. Completeness percentages for source tables use returned rows plus documented all-empty excluded rows; they do not imply time-series schedule coverage. Temporal gaps are summarized, but expected sample counts remain NULL because no validated sampling schedule was established. Sensor-failure and below-detection-limit codes are available but are not assigned without source evidence.',f'Physiology article values are public study/group aggregates, not astronaut-level records. {publications_without_values} catalogued public articles did not have their numeric tables transcribed in this pass; this publication inventory is a research snapshot and not a claim of exhaustive discovery worldwide. OSD-53 is molecular gene-expression research data. ESA HREDA entries in iss_physiology_study_catalog are discovery metadata. Synthetic check-ins are fictional fixtures, not validated scales.','The NASA EDA page labels time Controller_Time_GMT; source timestamps are retained and normalized to UTC form. Other source timestamps remain as returned.','Dataset-specific reuse terms must be rechecked before redistribution or operational use.']}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    md=['# SQLite build validation report','',f"Generated (UTC): {result['generated_at_utc']}",f"Database: `{a.db.name}` ({result['database_bytes']:,} bytes)",'', '## Integrity checks','',f"- SQLite integrity: **{integrity}**",f"- Foreign key violations: **{len(fk)}**",f"- Environmental source-reference duplicates: **{duplicate_refs}**",f"- Radiation source-reference duplicates: **{duplicate_radiation_refs}**",f"- Invalid or mislabeled synthetic check-ins: **{bad_synth}**",f"- Real measurements missing provenance fields: **{missing_provenance}**",'', '## Row counts','']
    for t,n in counts.items(): md.append(f'- `{t}`: {n:,}')
    md += ['', '## Imported datasets','', '| Accession | Category | Status | Environmental rows | Radiation rows | Gene-expression rows | Differential-expression rows | Synthetic rows |','|---|---:|---|---:|---:|---:|---:|---:|']
    for r in by_dataset: md.append(f"| {r['accession']} | {r['data_kind']} | {r['status']} | {r['env_rows']:,} | {r['radiation_rows']:,} | {r['gene_expression_rows']:,} | {r['differential_rows']:,} | {r['synthetic_rows']:,} |")
    md += ['', '## ISS physiology study catalog','',f"- ESA HREDA discovery records: {physiology_catalog_rows}; invalid metadata/measurement classification rows: {physiology_catalog_invalid}.",f"- Article inventory: {counts['physiology_publications']} publications; numeric aggregate records: {counts['published_physiology_aggregates']}; orphan aggregate rows: {agg_orphans}.",'', '| Domain | Aggregate records |','|---|---:|']
    for r in physiology_domains: md.append(f"| {r['domain']} | {r['rows']:,} |")
    md += ['', '## Missingness, completeness and temporal coverage','',f"- Field-level missing-value events: {counts['field_quality_events']:,}; documented omitted source rows: {sum((r['exclusion_count'] or 0) for r in c.execute('SELECT exclusion_count FROM source_row_exclusions')):,} in {counts['source_row_exclusions']} exclusion group(s).",f"- Dataset-variable completeness summaries: {counts['dataset_field_completeness']}; temporal series audited: {counts['temporal_coverage_summary']}. No expected sample count is inferred without documented sampling frequency.",f"- Imputed values: {imputed_rows}; values remain REAL, DERIVED or SYNTHETIC as sourced/labeled.",'', '## Environmental coverage','',f"- Rows: {env_stats['rows']:,}; missions: {env_stats['missions']}; source timestamp span: {env_stats['first_source_timestamp']} to {env_stats['last_source_timestamp']}.",f"- Non-null temperature values: {env_stats['temp_values']:,}; relative humidity values: {env_stats['rh_values']:,}; CO₂ values: {env_stats['co2_values']:,}.",f"- Relative-humidity values outside 0–100% preserved and flagged: {env_stats['flagged_rh_values'] or 0:,}.",'','| Zone | Rows |','|---|---:|']
    for r in env_by_zone: md.append(f"| {r['zone']} | {r['rows']:,} |")
    md += ['', '## Environmental rows by mission','', '| Mission | Rows | First source timestamp | Last source timestamp | Temp values | RH values | CO₂ values |','|---|---:|---|---|---:|---:|---:|']
    for r in env_by_mission: md.append(f"| {r['mission_code']} | {r['rows']:,} | {r['first_source_timestamp']} | {r['last_source_timestamp']} | {r['temp_values']:,} | {r['rh_values']:,} | {r['co2_values']:,} |")
    md += ['', '## Import batches','', '| Batch | Dataset | Status | Source rows/values | Inserted | Skipped |','|---:|---|---|---:|---:|---:|']
    for r in batch_rows: md.append(f"| {r['batch_id']} | {r['accession']} | {r['status']} | {r['source_records']:,} | {r['inserted_records']:,} | {r['skipped_records']:,} |")
    md += ['', '## Interpretation limits','']+[f'- {x}' for x in result['limitations']]
    md += ['', '## Publication transcription quality', '', f'- Publications without transcribed values: {publications_without_values}.', f'- Source quality findings: {len(quality_findings)}; source values preserved.']
    for finding in quality_findings:
        md.append(f"- {finding['issue']}: aggregate {finding['aggregate_id']}, metric {finding['metric_code']}, SD={finding['dispersion_value']}, DOI {finding['doi']}.")
    markdown_out=a.out.parent/'VALIDATION_REPORT.md'
    markdown_out.write_text('\n'.join(md)+'\n',encoding='utf-8')
    if a.quiet:
        print('Checks: '+', '.join(f'{name}={status}' for name,status in checks.items()))
        print(f'Data quality findings: {len(quality_findings)} (source values preserved)')
        print(f'JSON: {a.out}\nMarkdown: {markdown_out}')
    else:
        print(json.dumps(result,indent=2,ensure_ascii=False))
    c.close()
    if any(status!='PASS' for status in checks.values()):
        raise SystemExit(1)

if __name__=='__main__': main()
