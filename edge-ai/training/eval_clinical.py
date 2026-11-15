"""Clinical evaluation harness for EdgeSpace (Golden Cases, NLU, Multi-turn, Latency)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from edgespace_ai.correlation.correlator import ClinicalCorrelator
from edgespace_ai.correlation.symptom_extractor import detect_followup_polarity
from edgespace_ai.ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    CrewProfile,
    Peripheral,
    PeripheralReading,
    now_us,
)


def apply_real_migrations(db_file: Path, repo_root: Path = _REPO_ROOT) -> None:
    mig_dir = repo_root / "database" / "migrations"
    conn = sqlite3.connect(db_file)
    try:
        for sql_path in sorted(mig_dir.glob("*.sql")):
            conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def eval_golden_cases(db_file: Path, golden_path: Path) -> dict[str, Any]:
    suite = json.loads(golden_path.read_text(encoding="utf-8"))
    correlator = ClinicalCorrelator(db_path=db_file)
    passed = 0
    total = 0
    failures: list[dict[str, Any]] = []

    with sqlite3.connect(db_file) as c:
        c.execute("DELETE FROM mission_context_events")
        c.execute("DELETE FROM telemetry_daily_rollups")
        c.execute("DELETE FROM nutrition_hydration_logs")
        c.commit()

        for case in suite.get("cases", []):
            total += 1
            c.execute("DELETE FROM self_exams")
            c.execute(
                "INSERT INTO self_exams(ts_us,crew_id,exam_type,result,observations) VALUES (?,?,?,?,?)",
                (now_us(), case["crew_id"], "structured_fixture", json.dumps(case["metrics"]), "SYNTHETIC"),
            )
            c.commit()
            res = correlator.correlate(
                ChatCorrelateReqPayload(text="Revisar registros estruturados", crew_id=case["crew_id"])
            )
            got_conds = set(res.matched_condition_ids or [])
            exp_conds = set(case.get("expected_conditions") or [])
            got_sev = res.max_severity
            exp_sev = case.get("expected_max_severity")
            got_blk = set(res.blocked_actions or [])
            exp_blk = set(case.get("expected_blocked_actions") or [])
            forb_blk = set(case.get("forbidden_blocked_actions") or [])

            ok = (
                got_conds == exp_conds
                and got_sev == exp_sev
                and exp_blk.issubset(got_blk)
                and not (forb_blk & got_blk)
            )
            if ok:
                passed += 1
            else:
                failures.append(
                    {
                        "case_id": case["case_id"],
                        "got_conds": sorted(got_conds),
                        "exp_conds": sorted(exp_conds),
                        "got_sev": got_sev,
                        "exp_sev": exp_sev,
                    }
                )

    crew_cases = suite.get("crew_cases", [])
    crew_units = sum(len(cc.get("crews") or {}) for cc in crew_cases)
    return {
        "cases_passed": passed,
        "cases_total": total,
        "cases_pass_rate": round(passed / max(1, total), 4),
        "crew_cases_count": len(crew_cases),
        "crew_cases_expectation_units": crew_units,
        "failures": failures,
    }



def _built_in_nlu_probe() -> list[dict[str, Any]]:
    """Probe set covering colloquial PT/EN phrasing, negation, uncertainty, and greetings."""
    return [
        {
            "id": "NLU01",
            "text": "ola, estou com dores de cabeca ao olhar para a luz",
            "expected_concepts": ["headache", "photophobia"],
            "forbidden_concepts": [],
            "expected_top1": "SANS",
            "peripherals": {"co2_ppm": 620.0, "spo2_pct": 98.0},
            "posture": "supine",
            "mission_day": 12,
        },
        {
            "id": "NLU02",
            "text": "cabeca latejando e tontura no modulo",
            "expected_concepts": ["headache", "dizziness"],
            "forbidden_concepts": [],
            "expected_top1": "HYPERCAPNIA",
            "peripherals": {"co2_ppm": 3800.0, "spo2_pct": 97.0},
            "posture": "sitting",
            "mission_day": 14,
        },
        {
            "id": "NLU03",
            "text": "estou enxergando tudo embacado desde que acordei",
            "expected_concepts": ["blurred_vision", "visual_disturbance"],
            "forbidden_concepts": [],
            "expected_top1": "SANS",
            "peripherals": {"co2_ppm": 580.0, "spo2_pct": 98.5},
            "posture": "supine",
            "mission_day": 20,
        },
        {
            "id": "NLU04",
            "text": "muita falta de ar e respiracao curta apos o exercicio",
            "expected_concepts": ["dyspnea"],
            "forbidden_concepts": [],
            "expected_top1": "HYPOXIA",
            "peripherals": {"co2_ppm": 700.0, "spo2_pct": 88.0},
            "posture": "sitting",
            "mission_day": 10,
        },
        {
            "id": "NLU05",
            "text": "sinto o estomago embrulhado e vontade de vomitar",
            "expected_concepts": ["nausea"],
            "forbidden_concepts": ["headache"],
            "expected_top1": "SPACE_MOTION_SICKNESS",
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 98.5},
            "posture": "sitting",
            "mission_day": 2,
        },
        {
            "id": "NLU06",
            "text": "dor forte nas costas do lado direito perto do rim",
            "expected_concepts": ["flank_pain"],
            "forbidden_concepts": ["headache"],
            "expected_top1": "RENAL_STONES",
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 98.5},
            "posture": "sitting",
            "mission_day": 30,
        },
        {
            "id": "NLU07",
            "text": "nao estou com dor de cabeca, so passei para dar bom dia",
            "expected_concepts": [],
            "forbidden_concepts": ["headache"],
            "expected_top1": None,
            "peripherals": {"co2_ppm": 580.0, "spo2_pct": 98.5},
            "posture": "sitting",
            "mission_day": 10,
        },
        {
            "id": "NLU08",
            "text": "sem falta de ar e sem tontura, apenas dormi pouco",
            "expected_concepts": ["insomnia"],
            "forbidden_concepts": ["dyspnea", "dizziness"],
            "expected_top1": "SLEEP_CIRCADIAN",
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 98.5},
            "posture": "sitting",
            "mission_day": 15,
        },
        {
            "id": "NLU09",
            "text": "my vision feels blurry and eyes hurt behind sockets",
            "expected_concepts": ["blurred_vision", "eye_pressure"],
            "forbidden_concepts": [],
            "expected_top1": "SANS",
            "peripherals": {"co2_ppm": 590.0, "spo2_pct": 98.0},
            "posture": "supine",
            "mission_day": 18,
        },
        {
            "id": "NLU10",
            "text": "joint ache in shoulder right after EVA depressurization",
            "expected_concepts": ["joint_pain"],
            "forbidden_concepts": [],
            "expected_top1": "DECOMPRESSION_SICKNESS",
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 96.0},
            "posture": "sitting",
            "mission_day": 16,
        },
        {
            "id": "NLU11",
            "text": "a vista escurece e fico tonto quando fico de pe",
            "expected_concepts": ["orthostatic_intolerance", "dizziness"],
            "forbidden_concepts": [],
            "expected_top1": "ORTHOSTATIC_INTOLERANCE",
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 98.0},
            "posture": "standing",
            "mission_day": 45,
        },
        {
            "id": "NLU12",
            "text": "nao estou me sentindo muito bem",
            "expected_concepts": [],
            "forbidden_concepts": ["headache", "nausea"],
            "expected_top1": None,
            "peripherals": {"co2_ppm": 600.0, "spo2_pct": 98.5},
            "posture": "supine",
            "mission_day": 14,
        },
    ]



def _readings_from(per: dict[str, Any]) -> list[PeripheralReading]:
    ts = now_us()
    out: list[PeripheralReading] = []
    if "co2_ppm" in per:
        out.append(PeripheralReading(type=Peripheral.SCD40, value=float(per["co2_ppm"]), unit="ppm", timestamp_us=ts))
    if "spo2_pct" in per:
        out.append(PeripheralReading(type=Peripheral.MAX30102, value=float(per["spo2_pct"]), unit="%", timestamp_us=ts))
    return out


def eval_nlu_and_ranking(db_file: Path, nlu_file: Path | None = None) -> dict[str, Any]:
    if nlu_file is not None and nlu_file.is_file():
        samples = [json.loads(ln) for ln in nlu_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    else:
        samples = _built_in_nlu_probe()

    correlator = ClinicalCorrelator(db_path=db_file)
    ext = correlator.symptom_extractor
    cond_by_name = {c.name: c.id for c in correlator.causal_graph.conditions}

    tp = fp = fn = neg_fp = 0
    top1_hits = top3_hits = scored = 0
    latencies_ms: list[float] = []
    details: list[dict[str, Any]] = []

    for s in samples:
        got_c = set(ext.extract(s["text"]).concepts)
        exp_c = set(s.get("expected_concepts") or [])
        forb_c = set(s.get("forbidden_concepts") or [])
        tp += len(got_c & exp_c)
        fp += len(got_c - exp_c)
        fn += len(exp_c - got_c)
        neg_fp += len(got_c & forb_c)

        inf = AIInferencePayload(
            cycle_seq_first=1,
            posture=s.get("posture", "sitting"),
            respiration_hz=0.24,
            heart_rate_bpm=74.0,
            hrv_ms=48.0,
            anomaly_score=0.30,
            confidence=0.85,
        )
        profile = CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=int(s.get("mission_day", 14)))
        t0 = time.perf_counter()
        resp = correlator.correlate(
            ChatCorrelateReqPayload(text=s["text"], crew_id="crew_001", profile=profile),
            peripherals=_readings_from(s.get("peripherals") or {}),
            inference=inf,
        )
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        ranked_ids = [cond_by_name.get(d.rsplit(" (P=", 1)[0], d) for d in (resp.differentials or [])]
        if "expected_top1" in s:
            exp_top1 = s.get("expected_top1")
            scored += 1
            if exp_top1 is None:
                if not resp.differentials:
                    top1_hits += 1
                    top3_hits += 1
            else:
                top1_hits += int(bool(ranked_ids) and ranked_ids[0] == exp_top1)
                top3_hits += int(exp_top1 in ranked_ids[:3])
        else:
            exp_top1 = None

        details.append(
            {
                "id": s.get("id", ""),
                "got_concepts": sorted(got_c),
                "exp_concepts": sorted(exp_c),
                "forbidden_hits": sorted(got_c & forb_c),
                "got_top3": ranked_ids[:3],
                "exp_top1": exp_top1,
            }
        )

    lat = sorted(latencies_ms)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0.0
    # "unsure" = uncertain reply, must NOT move the posterior; "um pouco" is a mild affirmative.
    polarity_cases = [
        ("sim", "yes"),
        ("nao", "no"),
        ("talvez", "unsure"),
        ("um pouco", "yes"),
        ("nao sei", "unsure"),
        ("not sure", "unsure"),
    ]
    pol_ok = sum(1 for txt, exp in polarity_cases if detect_followup_polarity(txt) == exp)

    return {
        "samples": len(samples),
        "concept_recall": round(tp / max(1, tp + fn), 4),
        "concept_precision": round(tp / max(1, tp + fp), 4),
        "forbidden_false_positives": neg_fp,
        "top1_accuracy": round(top1_hits / max(1, scored), 4),
        "top3_accuracy": round(top3_hits / max(1, scored), 4),
        "polarity_uncertainty_accuracy": round(pol_ok / len(polarity_cases), 4),
        "correlate_p95_ms": round(p95, 2),
        "details": details,
    }


def run_eval(nlu_file: Path | None = None, out_path: Path | None = None) -> dict[str, Any]:
    golden_path = _REPO_ROOT / "knowledge-base" / "datasets" / "golden_cases" / "golden_cases.yaml"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_file = Path(tmp) / "eval.db"
        apply_real_migrations(db_file)
        golden = eval_golden_cases(db_file, golden_path)
        nlu = eval_nlu_and_ranking(db_file, nlu_file=nlu_file)
    report = {"golden": golden, "nlu_and_ranking": nlu}
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate EdgeSpace clinical correlation and NLU.")
    parser.add_argument("--nlu-file", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = run_eval(nlu_file=args.nlu_file, out_path=args.out)
    summary = {
        "golden": {k: v for k, v in report["golden"].items() if k != "failures"},
        "golden_failures": report["golden"]["failures"],
        "nlu_and_ranking": {k: v for k, v in report["nlu_and_ranking"].items() if k != "details"},
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

