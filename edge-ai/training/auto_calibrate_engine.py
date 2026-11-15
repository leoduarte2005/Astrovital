"""Layer 3: Auto-calibrate clinical_synonyms.json & Bayesian constants via scipy.optimize."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
_TRAIN_DIR = Path(__file__).resolve().parent
if str(_TRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_TRAIN_DIR))

from edgespace_ai.correlation import causal_graph as cg_mod
from edgespace_ai.correlation.clinical_store import load_yaml_file
from edgespace_ai.correlation.correlator import ClinicalCorrelator
from edgespace_ai.correlation.symptom_extractor import (
    SYMPTOM_LEXICON,
    SymptomExtractor,
    _normalize_text,
)
from edgespace_ai.ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    CrewProfile,
    Peripheral,
    PeripheralReading,
    now_us,
)
from eval_clinical import apply_real_migrations, eval_golden_cases

_NON_CLINICAL_PROBES = (
    "ola",
    "bom dia",
    "estou com dor",
    "preciso de ajuda",
    "nao estou me sentindo muito bem",
    "tudo bem por aqui",
)


def mine_synonyms(existing_path: Path, nlu_train_path: Path | None) -> dict[str, Any]:
    """Audit and expand clinical_synonyms.json from NASA reports + nlu_train without collisions."""
    synonyms: dict[str, list[str]] = {}
    if existing_path.is_file():
        raw = json.loads(existing_path.read_text(encoding="utf-8"))
        for k, v in (raw.get("synonyms") or {}).items():
            synonyms[str(k)] = list(dict.fromkeys(_normalize_text(str(x)) for x in v if str(x).strip()))

    # Pull clean report symptom phrases whose concept is uniquely identifiable
    base_phrases = {c: set(p) for c, p in SYMPTOM_LEXICON.items()}
    ext = SymptomExtractor()
    rejected: list[dict[str, str]] = []

    def _try_add(concept: str, raw_phrase: str) -> None:
        norm = _normalize_text(raw_phrase)
        if not norm or len(norm) < 4 or concept not in SYMPTOM_LEXICON:
            return
        if norm in base_phrases[concept] or norm in synonyms.get(concept, []):
            return
        # Reject if phrase fires a non-clinical probe or maps to a conflicting concept
        for probe in _NON_CLINICAL_PROBES:
            if norm == probe or norm in probe:
                rejected.append({"concept": concept, "phrase": norm, "reason": "non_clinical_probe"})
                return
        existing_hits = ext.extract(norm).concepts
        if existing_hits and any(h != concept and not ({h, concept} <= {"blurred_vision", "visual_disturbance"}) for h in existing_hits):
            rejected.append({"concept": concept, "phrase": norm, "reason": f"collides:{existing_hits}"})
            return
        synonyms.setdefault(concept, []).append(norm)

    # Also mine missed concepts from nlu_train.jsonl if present
    if nlu_train_path is not None and nlu_train_path.is_file():
        for line in nlu_train_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            exp = row.get("expected_concepts") or []
            if len(exp) == 1:
                got = set(ext.extract(row["text"]).concepts)
                if exp[0] not in got:
                    # Extract stripped phrase candidate after common leads
                    cleaned = _normalize_text(row["text"])
                    for lead in ("estou com ", "estou sentindo ", "tenho ", "sinto ", "i have ", "i feel "):
                        if lead in cleaned:
                            cand = cleaned.split(lead, 1)[1].split(",")[0].split(".")[0].strip()
                            _try_add(exp[0], cand)

    # Curated NASA HRP/CSA synonyms not yet in SYMPTOM_LEXICON
    nasa_additions = {
        "headache": ("pressao intracraniana", "frontal headache", "throbbing head"),
        "photophobia": ("sensibilidade ocular a luz", "bright light discomfort"),
        "dizziness": ("vertigem postural", "sensacao de desmaio"),
        "dyspnea": ("fome de ar", "air hunger", "labored breathing"),
        "nausea": ("enjoo vestibular", "nausea persistente"),
        "insomnia": ("sono fragmentado", "fragmented sleep"),
        "flank_pain": ("dor lombar lateral", "renal colic pain"),
        "joint_pain": ("dor articular pos eva", "decompression joint pain"),
        "orthostatic_intolerance": ("pre sincope ortostatica", "intolerancia ao ortostatismo"),
        "eye_pressure": ("tensao ocular", "retro orbital pain"),
    }
    for concept, phrases in nasa_additions.items():
        for ph in phrases:
            _try_add(concept, ph)

    out_dict = {k: sorted(dict.fromkeys(v)) for k, v in sorted(synonyms.items()) if v}
    return {
        "schema_version": 1,
        "generated_by": "auto_calibrate_engine.py",
        "total_phrases": sum(len(v) for v in out_dict.values()),
        "rejected_collisions": rejected,
        "synonyms": out_dict,
    }


_PARAM_NAMES = ("SYMPTOM_GAIN", "UNMATCHED_SYMPTOM_PENALTY", "NEGATIVE_EVIDENCE_FLOOR", "OVERLAP_YES_LIKELIHOOD")


def _set_params(x: np.ndarray) -> None:
    for name, val in zip(_PARAM_NAMES, x):
        setattr(cg_mod, name, float(val))


def _probe_metrics(db_file: Path) -> tuple[float, float]:
    from eval_clinical import eval_nlu_and_ranking

    res = eval_nlu_and_ranking(db_file)
    return float(res["top1_accuracy"]), float(res["top3_accuracy"])


def calibrate_bayes(db_file: Path, max_fev: int) -> dict[str, Any]:
    """Bounded (0.5x..2x), L2-regularised search; golden cases are a hard regression guard."""
    x0 = np.array([getattr(cg_mod, n) for n in _PARAM_NAMES], dtype=np.float64)
    lo = np.array([x0[0] * 0.5, x0[1] * 0.5, x0[2] * 0.8, x0[3] * 0.5])
    hi = np.array([x0[0] * 2.0, min(x0[1] * 1.5, 0.99), 0.99, min(x0[3] * 1.5, 0.9)])
    golden_dir = _REPO_ROOT / "knowledge-base" / "datasets" / "golden_cases" / "golden_cases.yaml"

    base_top1, base_top3 = _probe_metrics(db_file)
    base_golden = eval_golden_cases(db_file, golden_dir)

    def cost(x: np.ndarray) -> float:
        _set_params(x)
        t1, t3 = _probe_metrics(db_file)
        reg = 0.05 * float(np.sum(np.square(np.log(np.clip(x, 1e-6, None) / x0))))
        return -(t1 + 0.5 * t3) + reg

    res = minimize(cost, x0, method="Powell", bounds=list(zip(lo, hi)), options={"maxfev": max_fev, "xtol": 1e-2, "ftol": 1e-3})
    x_best = np.clip(res.x, lo, hi)
    _set_params(x_best)
    new_top1, new_top3 = _probe_metrics(db_file)
    new_golden = eval_golden_cases(db_file, golden_dir)
    _set_params(x0)  # never leave module state mutated

    improved = (new_top1 + 0.5 * new_top3) > (base_top1 + 0.5 * base_top3) + 1e-9
    golden_ok = new_golden["cases_passed"] == new_golden["cases_total"] == base_golden["cases_passed"]
    return {
        "params_before": dict(zip(_PARAM_NAMES, map(float, x0))),
        "params_proposed": dict(zip(_PARAM_NAMES, map(float, x_best))),
        "probe_before": {"top1": base_top1, "top3": base_top3},
        "probe_after": {"top1": new_top1, "top3": new_top3},
        "golden_before": f"{base_golden['cases_passed']}/{base_golden['cases_total']}",
        "golden_after": f"{new_golden['cases_passed']}/{new_golden['cases_total']}",
        "evaluations": int(res.nfev),
        "recommend_apply": bool(improved and golden_ok),
        "applied": False,
        "note": "Probe set is small and engineering-synthetic; proposal requires human review.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-calibrate synonyms and Bayesian constants.")
    parser.add_argument("--models-dir", type=Path, default=_TRAIN_DIR.parent / "models")
    parser.add_argument("--nlu-train", type=Path, default=_TRAIN_DIR / "data" / "nlu_train.jsonl")
    parser.add_argument("--max-fev", type=int, default=40)
    parser.add_argument("--skip-bayes", action="store_true")
    parser.add_argument("--write-synonyms", action="store_true")
    parser.add_argument("--out", type=Path, default=_TRAIN_DIR / "reports" / "calibration_proposal.json")
    args = parser.parse_args()

    syn_path = args.models_dir / "clinical_synonyms.json"
    syn = mine_synonyms(syn_path, args.nlu_train)
    report: dict[str, Any] = {
        "synonyms_total": syn["total_phrases"],
        "synonyms_rejected": len(syn["rejected_collisions"]),
    }
    if args.write_synonyms:
        syn_path.write_text(json.dumps(syn, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["synonyms_written"] = str(syn_path)

    if not args.skip_bayes:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_file = Path(tmp) / "calib.db"
            apply_real_migrations(db_file)
            report["bayes"] = calibrate_bayes(db_file, args.max_fev)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
