#!/usr/bin/env python3
"""Compile authoring JSON/YAML into offline SQLite seeds and synthetic fixtures.

The .yaml sources use the JSON subset of YAML 1.2 so no PyYAML is required.
Nothing in this module writes files on import. All clinical weights are test data.
"""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "knowledge-base"
SEED = 20261114
AS_OF = date(2026, 11, 14)
START_US = int(datetime(2026, 10, 4, tzinfo=timezone.utc).timestamp() * 1_000_000)
NOW_US = int(datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp() * 1_000_000)
POSTURES = ("sitting", "standing", "supine", "deep_breathing", "exercise", "apnea_desat")
SQL_PATH = Path("database/migrations/0004_intelligence_seeds.sql")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite seed value")
        return str(value)
    if isinstance(value, (list, dict)):
        value = compact(value)
    return "'" + str(value).replace("'", "''") + "'"


def upsert(table, row, key):
    keys = (key,) if isinstance(key, str) else tuple(key)
    columns = list(row)
    updates = ",".join(f"{c}=excluded.{c}" for c in columns if c not in keys)
    return (f"INSERT INTO {table}({','.join(columns)}) VALUES "
            f"({','.join(literal(row[c]) for c in columns)}) "
            f"ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates};\n")


def profiles():
    rows = []
    for i, (sex, hr, hrv, weight, height) in enumerate([
        ("M", 64.0, 52.0, 78.0, 178.0),
        ("F", 78.0, 43.0, 62.0, 166.0),
        ("M", 58.0, 61.0, 72.0, 174.0),
    ], 1):
        rows.append(dict(crew_id=f"crew_{i:03d}", biological_sex=sex, height_cm=height,
                         preflight_weight_kg=weight, vo2max_baseline=42.0+i,
                         preflight_hr_bpm=hr, preflight_hrv_ms=hrv, preflight_spo2_pct=98.0,
                         preflight_sbp_mmhg=112.0+2*i, preflight_dbp_mmhg=72.0+i,
                         preflight_ferritin_ug_l=90.0+20*i, preflight_hemoglobin_g_dl=13.5+0.3*i,
                         preflight_onsd_mm=4.6+0.05*i, sans_susceptibility="HIGH" if i==1 else "MODERATE",
                         sas_susceptibility="MODERATE", co2_sensitivity="HIGH" if i==1 else "NORMAL",
                         mission_start_us=START_US, data_class="SYNTHETIC"))
    return rows


def synthetic_data():
    import sys
    sys.path.insert(0,str(ROOT/'edge-ai/src'))
    import numpy as np
    from edgespace_ai.dsp.csi_processor import CSIProcessor
    from edgespace_ai.dsp.feature_extractor import FeatureExtractor
    from edgespace_ai.dsp.link_fusion import FusedCSI
    extractor,processor=FeatureExtractor(),CSIProcessor()
    csi_rows, peripheral_rows, baselines = [], [], []
    rng = random.Random(SEED)
    for crew_index, profile in enumerate(profiles()):
        clean, candidates = [], 0
        for pose_index, posture in enumerate(POSTURES):
            window=[]
            for j in range(60):
                ts = NOW_US + (pose_index*60+j)*100_000
                drop = j == 17
                t = j/10
                factor = 2.0 if posture == "exercise" else 1.0
                if posture == "deep_breathing":
                    factor = 1.7
                if posture == "apnea_desat" and j >= 30:
                    factor = 0.0  # no respiratory modulation; missing samples remain None
                i_values = [round((1+crew_index*0.03)*math.cos(k*0.13 + factor*0.03*math.sin(t*1.57)) + rng.gauss(0,0.005),6) for k in range(32)]
                q_values = [round(math.sin(k*0.13 + factor*0.03*math.sin(t*1.57)) + rng.gauss(0,0.005),6) for k in range(32)]
                features=None
                if not drop:
                    window.append(np.asarray(i_values)+1j*np.asarray(q_values));window=window[-40:]
                    if len(window)>=19:
                        processed=processor.process_complex_frames(np.asarray(window),rssi_dbm=-49,noise_floor=-92,apply_hampel=True)
                        fused=FusedCSI(processed.amplitude,processed.phase,{(0,1):1.0},1,43.0,0.0,0.05,np.asarray([float(np.var(np.diff(processed.amplitude,axis=0)))]),1.0,10.0)
                        features=[round(float(v),8) for v in extractor.extract(fused).vector]
                csi_rows.append(dict(crew_id=profile['crew_id'],ts_us=ts,posture=posture,
                                     tx_node_id=0,rx_node_id=1,iq_i=None if drop else i_values,
                                     iq_q=None if drop else q_values,features=None if drop else features,
                                     data_class="SYNTHETIC",missing_reason="SYNTHETIC_DROPOUT" if drop else "INSUFFICIENT_WINDOW" if features is None else None))
                if pose_index < 4:
                    candidates += 1
                    if features is not None:
                        clean.append(features)
                hr = profile['preflight_hr_bpm'] + (65 if posture == "exercise" else 8 if posture == "standing" else -3 if posture == "supine" else 0) + rng.gauss(0,1)
                spo2 = 86.0 + rng.random() if posture == "apnea_desat" and j >= 30 else 98.0+rng.uniform(-0.4,0.4)
                peripheral_rows.append(dict(crew_id=profile['crew_id'],ts_us=ts,posture=posture,
                    heart_rate_bpm=round(hr,3),hrv_ms=round(profile['preflight_hrv_ms']/(1.6 if posture=='exercise' else 1),3),
                    resp_rate_bpm=6.0 if posture=='deep_breathing' else 27.0 if posture=='exercise' else None if posture=='apnea_desat' else 14.0,
                    spo2_pct=None if drop else round(spo2,3),co2_ppm=round(600+rng.uniform(-20,20),3),
                    temp_c=22.0,humidity_pct=45.0,pressure_hpa=1013.0,
                    data_class="SYNTHETIC",missing_reason="SYNTHETIC_DROPOUT" if drop or posture=='apnea_desat' else None))
        mean = [round(statistics.mean(v[k] for v in clean),8) for k in range(64)]
        std = [round(max(statistics.pstdev(v[k] for v in clean),0.000001),8) for k in range(64)]
        baselines.append(dict(baseline_id=f"seed-{profile['crew_id']}-v1",crew_id=profile['crew_id'],version=1,
            onnx_model_path=None,feature_dim=64,feature_schema_id="EDGESPACE_DSP64_V1",mean_json=mean,std_json=std,anomaly_threshold=0.75,
            sample_count=len(clean),clean_window_ratio=len(clean)/candidates,
            covered_postures_json=list(POSTURES[:4]),calibration_status="SYNTHETIC_SEED",drift_score=0.0,
            is_active=1,updated_at_us=NOW_US,data_class="SYNTHETIC"))
    return csi_rows, peripheral_rows, baselines


def build_outputs():
    catalog = load(KB / "sources.json")
    reports = [load(KB/p) for p in load(KB/'catalog.json')['reports']]
    protocols = [load(p) for p in sorted((KB / "protocols").glob("*.yaml"))]
    if len(reports) < 19 or len({r['report_id'] for r in reports}) != len(reports):
        raise ValueError("Expected 19 unique project reports")
    if sum(r['category']=='PHYSIOLOGICAL' for r in reports)<11:
        raise ValueError("Expected 11 physiological and eight behavioral/biochemical reports")
    csi, peripherals, baselines = synthetic_data()
    sql = ["-- Generated by database/tools/generate_intelligence_seeds.py; do not edit.\n",
           "-- Profiles, baselines, longitudinal history and numerical causal weights are SYNTHETIC.\n",
           "-- Clinical narratives cite public sources; ENGINEERING_TEST_ONLY is not diagnostic validation.\n"]
    for source in catalog['sources']:
        sql.append(upsert('clinical_sources',source,'source_id'))
    for hazard in catalog['hazards']:
        sql.append(upsert('clinical_hazards',hazard,'hazard_id'))
    for profile in profiles():
        crew_id = profile['crew_id']
        sql.append("UPDATE crew_profiles SET " + ','.join(f"{k}={literal(v)}" for k,v in profile.items() if k!='crew_id') + f" WHERE crew_id={literal(crew_id)};\n")
    for protocol in protocols:
        row = {k:protocol[k] for k in ('protocol_id','name','description','duration_s','source_id')}
        for key in ('subsystems','steps','materials','rich_steps','result_schema','linked_risks'):
            row[key+'_json'] = protocol[key]
        sql.append(upsert('protocols',row,'protocol_id'))
    for report in reports:
        measures = list(dict.fromkeys(m for c in report['conditions'] for m in c['countermeasures']))
        sql.append(upsert('clinical_reports',dict(report_id=report['report_id'],source_id=report['source_id'],
            hazard_id=report['hazard_id'],category=report['category'],title=report['title'],problem=report['problem'],
            content_text=report['scientific_scope']+' '+' '.join(report['detection'])+' '+' '.join(report.get('search_aliases',[])),
            symptoms_text=' '.join(report['primary_symptoms']+report['secondary_symptoms']),
            countermeasures_text=' '.join(measures),payload_json=report),'report_id'))
        for condition in report['conditions']:
            row = {k:condition[k] for k in ('condition_id','name','source_id','subsystem','prior','default_escalation','recommended_mission_mode','match_policy','model_status')}
            row['report_id'] = report['report_id']
            for key in ('symptoms','countermeasures','actions','linked_protocols'):
                row[key+'_json'] = condition[key]
            sql.append(upsert('causal_conditions',row,'condition_id'))
            for i, rule in enumerate(condition['sensor_rules'],1):
                sql.append(upsert('causal_sensor_rules',dict(rule_id=f"{condition['condition_id']}-R{i}",condition_id=condition['condition_id'],**rule),'rule_id'))
            for i, question in enumerate(condition['questions'],1):
                row = dict(question)
                row['positive_concepts_json'] = row.pop('positive_concepts')
                sql.append(upsert('causal_disambiguation_questions',dict(question_id=f"{condition['condition_id']}-Q{i}",condition_id=condition['condition_id'],**row),'question_id'))
            for i, contra in enumerate(condition['contraindications'],1):
                sql.append(upsert('causal_contraindications',dict(contra_id=f"{condition['condition_id']}-C{i}",condition_id=condition['condition_id'],**contra),'contra_id'))
    for b in baselines:
        sql.append(upsert('individual_baselines',b,'baseline_id'))
        sql.append(upsert('calibration_sessions',dict(session_id='session-'+b['baseline_id'],crew_id=b['crew_id'],baseline_id=b['baseline_id'],
            started_us=NOW_US,ended_us=NOW_US+24_000_000,status='SYNTHETIC_SEED',sample_count=b['sample_count'],
            clean_window_ratio=b['clean_window_ratio'],covered_postures_json=b['covered_postures_json'],
            notes='Fixtures sintéticas; nenhum modelo ONNX treinado foi fornecido.'),'session_id'))
    for index, profile in enumerate(profiles()):
        crew_id=profile['crew_id']
        for fact_type,key,value in [('PREFERENCE','preferred_language','pt-BR'),('SLEEP_NOTE','sleep_window','22:00–06:00 UTC (fixture)'),('ANSWERED_TOPIC','baseline_context','Linha de base fictícia explicada ao usuário de teste.')]:
            sql.append(upsert('crew_clinical_memory',dict(memory_id=f'seed-{crew_id}-{key}',crew_id=crew_id,fact_type=fact_type,
                fact_key=key,fact_value=value,confidence=1.0,source_role='SEED',active=1,created_us=NOW_US,updated_us=NOW_US,data_class='SYNTHETIC'),'memory_id'))
        for offset in range(7):
            day=AS_OF-timedelta(days=6-offset)
            ts=int(datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1_000_000)
            hr=profile['preflight_hr_bpm']+offset*0.3
            sql.append(upsert('telemetry_daily_rollups',dict(crew_id=crew_id,day_utc=str(day),mission_day=36+offset,sample_count=86400,
                hr_mean=hr,hr_min=hr-8,hr_max=hr+60,hrv_mean=profile['preflight_hrv_ms']-offset*0.2,hrv_p10=profile['preflight_hrv_ms']-8,
                resp_mean=14.0,spo2_mean=98.0,spo2_min=96.0,co2_mean=600.0,co2_max=850.0,temp_mean=22.0,
                sleep_duration_h=7.5,deep_sleep_h=1.3,exercise_minutes=90.0,radiation_dose_msv=0.15,data_class='SYNTHETIC'),('crew_id','day_utc')))
            sql.append(upsert('nutrition_hydration_logs',dict(log_id=f'seed-{crew_id}-{day}',crew_id=crew_id,ts_us=ts+12*3600_000_000,
                water_ml=2300.0,energy_kcal=2400.0+100*index,protein_g=90.0,calcium_mg=1000.0,iron_mg=8.0,vitamin_d_ug=20.0,
                potassium_citrate_mg=None,body_mass_kg=profile['preflight_weight_kg'],
                source_note='Diário fictício com as oito categorias do roteiro; valores não são metas prescritas. Citrato não administrado/não informado.',data_class='SYNTHETIC'),'log_id'))
            sql.append(upsert('crew_circadian_schedule',dict(schedule_id=f'seed-{crew_id}-{day}',crew_id=crew_id,day_utc=str(day),
                sleep_start_us=ts+22*3600_000_000,sleep_end_us=ts+30*3600_000_000,
                light_start_us=ts+6*3600_000_000,light_end_us=ts+21*3600_000_000,light_lux=300.0,data_class='SYNTHETIC'),'schedule_id'))
            for etype,hour in [('EXERCISE_ARED',10),('EXERCISE_AEROBIC',16),('SLEEP_WINDOW',22)]:
                sql.append(upsert('mission_context_events',dict(event_id=f'seed-{crew_id}-{day}-{etype}',crew_id=crew_id,event_type=etype,
                    ts_us=ts+hour*3600_000_000,end_us=ts+(hour+(8 if etype=='SLEEP_WINDOW' else 1))*3600_000_000,
                    details_json={'fixture':True},data_class='SYNTHETIC'),'event_id'))
        for etype,hour in [('EVA',8),('RADIATION_SPE_ALERT',18)]:
            sql.append(upsert('mission_context_events',dict(event_id=f'seed-{crew_id}-{etype}',crew_id=crew_id,event_type=etype,
                ts_us=NOW_US+hour*3600_000_000,end_us=NOW_US+(hour+1)*3600_000_000,details_json={'fixture':True},data_class='SYNTHETIC'),'event_id'))
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=list(peripherals[0]),lineterminator='\n')
    writer.writeheader()
    writer.writerows(peripherals)  # None serializes as an empty cell, never 0.0.
    outputs={SQL_PATH:''.join(sql),Path('knowledge-base/datasets/synthetic_csi/samples.jsonl'):''.join(compact(row)+'\n' for row in csi),
             Path('knowledge-base/datasets/synthetic_peripherals/samples.csv'):buffer.getvalue(),
             Path('knowledge-base/datasets/synthetic_profiles.json'):json.dumps({'data_class':'SYNTHETIC','seed':SEED,'profiles':profiles()},ensure_ascii=False,indent=2)+'\n'}
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Check reproducibility without writing files.')
    args=parser.parse_args()
    outputs=build_outputs()
    bad=[]
    for path,content in outputs.items():
        destination=ROOT/path
        if args.check:
            if not destination.is_file() or destination.read_bytes()!=content.encode('utf-8'):
                bad.append(str(path))
        else:
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(content,encoding='utf-8',newline='')
    if bad:
        parser.exit(1,'Generated files need regeneration: '+', '.join(bad)+'\n')
    print(('Verified' if args.check else 'Generated')+f' {len(outputs)} deterministic artifacts; seed={SEED}.')


if __name__=='__main__':
    main()
