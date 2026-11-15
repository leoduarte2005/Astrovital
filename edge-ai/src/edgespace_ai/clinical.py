"""Read-only SQLite clinical data access, reusable by the Python Edge AI.

Runtime reads SQLite only. YAML files are build-time authoring inputs.
The optional rule evaluator is an engineering acceptance harness, not a diagnosis.
"""
from datetime import date, timedelta, datetime, timezone
import json
import math
from pathlib import Path
import sqlite3


class ClinicalRepository:
    def __init__(self, path):
        self.connection = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("PRAGMA foreign_keys=ON")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    @staticmethod
    def decode(row):
        result=dict(row)
        for key,value in list(result.items()):
            if key.endswith('_json') and value is not None:
                result[key[:-5]]=json.loads(value)
        return result

    def crew(self, crew_id):
        row=self.connection.execute('SELECT * FROM crew_profiles WHERE crew_id=?',(crew_id,)).fetchone()
        if row is None:
            raise KeyError(crew_id)
        return self.decode(row)

    def baseline(self, crew_id):
        row=self.connection.execute('SELECT * FROM individual_baselines WHERE crew_id=? AND is_active=1',(crew_id,)).fetchone()
        if row is None:
            raise KeyError('No active baseline: '+crew_id)
        return self.decode(row)

    def protocol(self, protocol_id):
        row=self.connection.execute('SELECT * FROM protocols WHERE protocol_id=?',(protocol_id,)).fetchone()
        if row is None:
            raise KeyError(protocol_id)
        return self.decode(row)

    def memory(self, crew_id):
        self.crew(crew_id)
        return [dict(r) for r in self.connection.execute('SELECT * FROM crew_clinical_memory WHERE crew_id=? AND active=1 ORDER BY fact_type,fact_key',(crew_id,))]

    def rollups(self, crew_id, days=7, as_of=None):
        if days not in (3,7,30):
            raise ValueError('Supported windows: 3, 7, 30 days')
        self.crew(crew_id)
        if as_of is None:
            as_of=self.connection.execute('SELECT MAX(day_utc) FROM telemetry_daily_rollups WHERE crew_id=?',(crew_id,)).fetchone()[0]
            if as_of is None:
                return []
        end=date.fromisoformat(as_of)
        start=end-timedelta(days=days-1)
        return [dict(r) for r in self.connection.execute('SELECT * FROM telemetry_daily_rollups WHERE crew_id=? AND day_utc BETWEEN ? AND ? ORDER BY day_utc',(crew_id,str(start),str(end)))]

    def context_metrics(self, crew_id):
        """Only recorded context is evidence; absent measurements stay unknown."""
        c=self.connection
        metrics={}
        memory=self.memory(crew_id)
        for fact in memory:
            if fact['fact_type'] in ('SENSITIVITY','CONDITION_HISTORY'):
                try: metrics[fact['fact_key']]=float(fact['fact_value'])
                except ValueError: pass
        latest=c.execute('SELECT MAX(ts_us) FROM telemetry_timeseries WHERE crew_id=?',(crew_id,)).fetchone()[0]
        if latest is not None:
            row=c.execute('SELECT heart_rate_bpm,hrv_ms,resp_rate_bpm,spo2_pct,co2_ppm FROM telemetry_timeseries WHERE crew_id=? AND ts_us=?',(crew_id,latest)).fetchone()
            if row: metrics.update({k:v for k,v in dict(row).items() if v is not None})
        allowed={r[0] for r in c.execute('SELECT DISTINCT metric FROM causal_sensor_rules')}|{r[0] for r in c.execute('SELECT DISTINCT guard_metric FROM causal_contraindications')}
        for row in c.execute('SELECT result FROM self_exams WHERE crew_id=? ORDER BY ts_us DESC LIMIT 20',(crew_id,)):
            try: values=json.loads(row['result'])
            except (json.JSONDecodeError,TypeError): continue
            if isinstance(values,dict):
                for key,value in values.items():
                    if key in allowed and isinstance(value,(int,float)):
                        metrics.setdefault(key,value)
        now=int(datetime.now(timezone.utc).timestamp()*1_000_000)
        types=[r[0] for r in c.execute('SELECT event_type FROM mission_context_events WHERE (crew_id=? OR crew_id IS NULL) AND ts_us<=? AND COALESCE(end_us,ts_us)>=?',(crew_id,now,now-2*3600_000_000))]
        if any(t.startswith('EXERCISE_') for t in types):metrics['exercise_recent']=1
        if 'EVA' in types:metrics['eva_recent']=1
        if 'RADIATION_SPE_ALERT' in types:metrics['spe_alert']=1
        rows=c.execute("SELECT date(ts_us/1000000,'unixepoch') AS day,SUM(water_ml) AS water,SUM(energy_kcal) AS energy FROM nutrition_hydration_logs WHERE crew_id=? AND ts_us BETWEEN ? AND ? GROUP BY day",(crew_id,now-7*86400_000_000,now)).fetchall()
        metrics.setdefault('nutrition_days_observed',len(rows))
        water=[r['water'] for r in rows if r['water'] is not None];energy=[r['energy'] for r in rows if r['energy'] is not None]
        if water:metrics.setdefault('water_7d_mean_ml',sum(water)/len(water))
        if energy:metrics.setdefault('energy_7d_mean_kcal',sum(energy)/len(energy))
        rollups=self.rollups(crew_id,7,datetime.now(timezone.utc).date().isoformat())
        sleeps=[r['sleep_duration_h'] for r in rollups if r['sleep_duration_h'] is not None]
        if sleeps:metrics.setdefault('sleep_duration_h',sum(sleeps)/len(sleeps))
        return metrics

    def search_reports(self, query, limit=20):
        if not 1 <= limit <= 100:
            raise ValueError('Limit must be 1..100')
        return [dict(r) for r in self.connection.execute('SELECT report_id,title,rank FROM clinical_reports_fts WHERE clinical_reports_fts MATCH ? ORDER BY rank,report_id LIMIT ?',(query,limit))]

    def conditions(self):
        result=[]
        for row in self.connection.execute('SELECT * FROM causal_conditions ORDER BY condition_id'):
            condition=self.decode(row)
            for key,table in [('rules','causal_sensor_rules'),('questions','causal_disambiguation_questions'),('contraindications','causal_contraindications')]:
                condition[key]=[self.decode(r) for r in self.connection.execute(f'SELECT * FROM {table} WHERE condition_id=? ORDER BY rowid',(condition['condition_id'],))]
            result.append(condition)
        return result

    @staticmethod
    def compare(value, op, threshold, values=None, profile=None):
        if value is None:
            return None
        if isinstance(value,(float,int)) and not math.isfinite(value):
            return None
        if op=='IN':
            return value in (values or {}).get('values',[])
        if op.startswith('DELTA_'):
            baseline=(profile or {}).get((values or {}).get('baseline_field'))
            if baseline is None:
                return None
            value=value-baseline
            op=op[6:]
        if threshold is None:
            return None
        operations={'GT':lambda a,b:a>b,'GE':lambda a,b:a>=b,'LT':lambda a,b:a<b,'LE':lambda a,b:a<=b,'EQ':lambda a,b:a==b}
        return operations[op](value,threshold)

    def assess_fixture(self, crew_id, metrics, *, allow_engineering=False, answers=None):
        if not allow_engineering:
            raise ValueError('Synthetic model: explicitly enable engineering acceptance mode')
        profile=self.crew(crew_id)
        answered={m['fact_key'] for m in self.memory(crew_id) if m['fact_type']=='ANSWERED_TOPIC'}
        answers=answers or {}
        matches=[]
        unknown=[]
        for condition in self.conditions():
            states=[self.compare(metrics.get(r['metric']),r['op'],r['threshold_value'],r['values'],profile) for r in condition['rules']]
            if any(s is None for s in states):
                unknown.append(condition['condition_id'])
            matched=bool(states) and (all(s is True for s in states) if condition['match_policy']=='ALL' else any(s is True for s in states))
            if not matched:
                continue
            odds=condition['prior']/(1-condition['prior'])
            for rule in condition['rules']:
                if self.compare(metrics.get(rule['metric']),rule['op'],rule['threshold_value'],rule['values'],profile):
                    odds*=rule['likelihood_ratio']
            questions=[]
            for question in condition['questions']:
                qid=question['question_id']
                if qid in answers:
                    if not isinstance(answers[qid],bool):
                        raise ValueError('Question answers must be boolean')
                    odds*=question['yes_likelihood'] if answers[qid] else question['no_likelihood']
                elif qid not in answered:
                    questions.append(question)
            blocked=[]
            review=[]
            for contra in condition['contraindications']:
                state=self.compare(metrics.get(contra['guard_metric']),contra['guard_op'],contra['guard_value'])
                if state is True:
                    blocked.append(contra['blocked_action'])
                elif state is None:
                    review.append(contra['blocked_action'])
            order={'INFO':0,'YELLOW':1,'RED':2}
            tier=max((r['severity_tier'] for r in condition['rules']),key=order.get)
            matches.append(dict(condition_id=condition['condition_id'],engineering_score=odds/(1+odds),
                severity='GREEN' if tier=='INFO' else tier,source_id=condition['source_id'],
                recommended_mission_mode=condition['recommended_mission_mode'],
                escalation=condition['default_escalation'],blocked_actions=sorted(set(blocked)),
                requires_review_actions=sorted(set(review)),questions=questions))
        matches.sort(key=lambda r:(-r['engineering_score'],r['condition_id']))
        severity=max((m['severity'] for m in matches),key={'GREEN':0,'YELLOW':1,'RED':2}.get,default='GREEN')
        return dict(model_status='ENGINEERING_TEST_ONLY',matches=matches,max_severity=severity,
                    unknown_conditions=sorted(unknown),blocked_actions=sorted({a for m in matches for a in m['blocked_actions']}))
