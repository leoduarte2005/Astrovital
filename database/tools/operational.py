#!/usr/bin/env python3
"""Apply and validate operational migrations, sharing Go's schema_version ledger."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

if __package__:
    from .clinical_repository import ClinicalRepository
else:
    from clinical_repository import ClinicalRepository

ROOT=Path(__file__).resolve().parents[2]
MIGRATIONS=ROOT/'database/migrations'
RESEARCH=ROOT/'database/space_health_sqlite/space_health.db'


def statements(text):
    pending=''
    for line in text.splitlines(keepends=True):
        pending+=line
        if sqlite3.complete_statement(pending):
            yield pending
            pending=''
    if any(line.strip() and not line.lstrip().startswith('--') for line in pending.splitlines()):
        raise ValueError('Incomplete SQL statement')


def migrate(path, migrations=MIGRATIONS):
    path=Path(path).resolve()
    if path==RESEARCH.resolve() or (path.exists() and RESEARCH.exists() and path.samefile(RESEARCH)):
        raise ValueError('Operational migrations cannot target the research snapshot')
    files=sorted(Path(migrations).glob('*.sql'))
    if not files:
        raise ValueError('No SQL migrations found')
    path.parent.mkdir(parents=True,exist_ok=True)
    applied=[]
    with closing(sqlite3.connect(path)) as c:
        names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'datasets','import_batches'} <= names:
            raise ValueError('Research schema detected; refusing operational migration')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        c.execute('PRAGMA busy_timeout=5000')
        c.execute('CREATE TABLE IF NOT EXISTS schema_version(filename TEXT PRIMARY KEY,applied_at_us INTEGER NOT NULL)')
        c.commit()
        for file in files:
            # Check the ledger under the writer lock, so concurrent starts cannot replay DDL.
            c.execute('BEGIN IMMEDIATE')
            try:
                if c.execute('SELECT 1 FROM schema_version WHERE filename=?',(file.name,)).fetchone():
                    c.rollback()
                    continue
                for sql in statements(file.read_text(encoding='utf-8')):
                    c.execute(sql)
                violations=c.execute('PRAGMA foreign_key_check').fetchall()
                if violations:
                    raise ValueError(f'Foreign key violations in {file.name}: {violations}')
                c.execute('INSERT INTO schema_version VALUES (?,?)',(file.name,int(datetime.now(timezone.utc).timestamp()*1_000_000)))
                c.commit()
                applied.append(file.name)
            except BaseException:
                c.rollback()
                raise
    return applied


LONGITUDINAL_AGGREGATES=('mean','sum','delta','count','last')


def longitudinal_metrics(repo, crew_id, specs):
    """Derive named metrics from telemetry_daily_rollups; a missing series stays None (unknown)."""
    values={}
    for name,spec in specs.items():
        if spec['agg'] not in LONGITUDINAL_AGGREGATES:
            raise ValueError(f"Unsupported longitudinal aggregate: {spec['agg']}")
        series=[r[spec['field']] for r in repo.rollups(crew_id,spec['days']) if r[spec['field']] is not None]
        if spec['agg']=='count':
            values[name]=len(series)
        elif not series:
            values[name]=None
        elif spec['agg']=='mean':
            values[name]=sum(series)/len(series)
        elif spec['agg']=='sum':
            values[name]=sum(series)
        elif spec['agg']=='delta':
            values[name]=series[-1]-series[0]
        else:
            values[name]=series[-1]
    return values


def check_case(repo, case_id, crew_id, metrics, expected, longitudinal=None):
    """Return a failure record, or None when the engineering assessment meets the expectation."""
    derived=longitudinal_metrics(repo,crew_id,longitudinal) if longitudinal else {}
    result=repo.assess_fixture(crew_id,{**metrics,**derived},allow_engineering=True)
    actual={m['condition_id'] for m in result['matches']}
    problems=[]
    if actual!=set(expected['expected_conditions']):
        problems.append('conditions')
    if result['max_severity']!=expected['expected_max_severity']:
        problems.append('severity')
    if not set(expected['expected_blocked_actions']) <= set(result['blocked_actions']):
        problems.append('blocked_actions')
    if set(expected.get('forbidden_blocked_actions',[])) & set(result['blocked_actions']):
        problems.append('unexpected_blocked_actions')
    for name,bound in expected.get('expected_longitudinal',{}).items():
        value=derived.get(name)
        if value is None or ('lt' in bound and not value<bound['lt']) or ('gt' in bound and not value>bound['gt']):
            problems.append(f'longitudinal:{name}')
    if problems:
        return {'case_id':case_id,'crew_id':crew_id,'problems':problems,'expected':expected['expected_conditions'],
                'actual':sorted(actual),'longitudinal':derived,'result':result}
    return None


def golden(path):
    suite=json.loads((ROOT/'knowledge-base/datasets/golden_cases/golden_cases.yaml').read_text(encoding='utf-8'))
    failures=[]
    crew_cases=suite.get('crew_cases',[])
    with ClinicalRepository(path) as repo:
        for case in suite['cases']:
            failure=check_case(repo,case['case_id'],case['crew_id'],case['metrics'],case,case.get('longitudinal'))
            if failure:
                failures.append(failure)
        for case in crew_cases:
            outcomes=set()
            for crew_id,expected in case['crews'].items():
                failure=check_case(repo,case['case_id'],crew_id,case.get('metrics',{}),expected,case.get('longitudinal'))
                if failure:
                    failures.append(failure)
                outcomes.add(tuple(sorted(expected['expected_conditions'])))
            if case.get('require_distinct_outputs') and len(outcomes)!=len(case['crews']):
                failures.append({'case_id':case['case_id'],'problems':['outputs_not_distinct'],'outcomes':sorted(outcomes)})
    total=len(suite['cases'])+len(crew_cases)
    failed_ids={f['case_id'] for f in failures}
    return {'cases':total,'passed':total-len(failed_ids),'failures':failures,
            'crew_cases':len(crew_cases),'format_version':suite.get('schema_version',1)}


def validate(path):
    with ClinicalRepository(path) as repo:
        c=repo.connection
        checks={}
        checks['sqlite_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        checks['foreign_keys']=not c.execute('PRAGMA foreign_key_check').fetchall()
        tables=['crew_profiles','clinical_sources','clinical_hazards','clinical_reports','protocols','individual_baselines',
                'calibration_sessions','crew_clinical_memory','telemetry_daily_rollups','mission_context_events',
                'crew_circadian_schedule','nutrition_hydration_logs','causal_conditions','causal_sensor_rules',
                'causal_disambiguation_questions','causal_contraindications']
        counts={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}
        checks['risk_coverage']=counts['clinical_reports']>=19 and counts['clinical_hazards']==5 and counts['causal_conditions']>=19
        categories=dict(c.execute('SELECT category,count(*) FROM clinical_reports GROUP BY category'))
        checks['category_coverage']=categories.get('PHYSIOLOGICAL',0)>=11 and categories.get('BEHAVIORAL_BIOCHEMICAL',0)>=8
        active=c.execute('SELECT crew_id FROM individual_baselines WHERE is_active=1 ORDER BY crew_id').fetchall()
        checks['three_active_baselines']=[r[0] for r in active]==['crew_001','crew_002','crew_003']
        checks['baseline_vectors']=all(b['feature_dim']==64 and len(b['mean'])==64 and len(b['std'])==64 and all(v>0 for v in b['std']) for b in (repo.baseline(f'crew_{i:03d}') for i in range(1,4)))
        checks['conditions_complete']=not c.execute('''SELECT c.condition_id FROM causal_conditions c WHERE
            NOT EXISTS(SELECT 1 FROM causal_sensor_rules r WHERE r.condition_id=c.condition_id) OR
            NOT EXISTS(SELECT 1 FROM causal_disambiguation_questions q WHERE q.condition_id=c.condition_id) OR
            NOT EXISTS(SELECT 1 FROM causal_contraindications x WHERE x.condition_id=c.condition_id)''').fetchall()
        checks['linked_protocols']=not c.execute('''SELECT c.condition_id FROM causal_conditions c,json_each(c.linked_protocols_json) j
            LEFT JOIN protocols p ON p.protocol_id=j.value WHERE p.protocol_id IS NULL''').fetchall()
        checks['ranked_fts']=bool(repo.search_reports('cefaleia OR SANS OR CO2'))
        checks['protocol_fts']=bool(c.execute("SELECT protocol_id FROM protocols_fts WHERE protocols_fts MATCH 'Amsler'").fetchall())
        checks['seven_days_per_crew']=all(len(repo.rollups(f'crew_{i:03d}',7))==7 for i in range(1,4))
        checks['thirty_days_per_crew']=all(len(repo.rollups(f'crew_{i:03d}',30))==30 for i in range(1,4))
        checks['enriched_protocols']=not c.execute("SELECT protocol_id FROM protocols WHERE json_array_length(rich_steps_json)=0 OR json_array_length(materials_json)=0 OR result_schema_json='{}'").fetchall()
    suite=golden(path)
    checks['golden_cases']=suite['cases']>=33 and not suite['failures']
    return {'database':str(Path(path).resolve()),'checks':checks,'passed':all(checks.values()),'counts':counts,'golden_cases':suite,
            'model_status':'ENGINEERING_TEST_ONLY','fixture_data_class':'SYNTHETIC'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['migrate','validate','golden'])
    p.add_argument('--db',type=Path,default=ROOT/'var/edgespace.db')
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        if a.command=='migrate':
            result={'database':str(a.db.resolve()),'applied':migrate(a.db)}
        elif a.command=='validate':
            result=validate(a.db)
        else:
            result=golden(a.db)
        if a.out:
            a.out.parent.mkdir(parents=True,exist_ok=True)
            a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('passed') is False or result.get('failures'):
            return 1
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        p.exit(1,f'Operational database: {error}\n')
    return 0


if __name__=='__main__':
    sys.exit(main())
