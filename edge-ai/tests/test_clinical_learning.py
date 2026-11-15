"""Tests for lexicon expansion, multi-turn Bayes, prior memory, and online baseline adaptation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from edgespace_ai.adaptation import BaselineRegistry, CalibrationEngine
from edgespace_ai.adaptation.calibration_engine import (
    ONLINE_MAX_ANCHOR_DRIFT,
    ONLINE_MIN_INTERVAL_S,
    canonical_posture,
)
from edgespace_ai.correlation.causal_graph import (
    CausalCondition,
    DisambiguationQuestion,
    HypothesisPosterior,
    question_p_yes,
)
from edgespace_ai.correlation.correlator import (
    ClinicalCorrelator,
    derive_prior_multipliers,
    extract_permanent_facts,
)
from edgespace_ai.correlation.disambiguator import Disambiguator, shannon_entropy
from edgespace_ai.correlation.symptom_extractor import (
    SymptomExtractor,
    detect_followup_polarity,
    load_clinical_synonyms,
)
from edgespace_ai.dsp.feature_extractor import FEATURE_DIM
from edgespace_ai.ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    ChatMessage,
    CrewProfile,
    Escalation,
    Peripheral,
    PeripheralReading,
    now_us,
)


def _db(tmp_path: Path) -> Path:
    db_file = tmp_path / "learn.db"
    repo_root = Path(__file__).resolve().parents[2]
    conn = sqlite3.connect(db_file)
    try:
        for sql in sorted((repo_root / "database" / "migrations").glob("*.sql")):
            conn.executescript(sql.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_file


def _inf(anom: float = 0.3) -> AIInferencePayload:
    return AIInferencePayload(
        cycle_seq_first=1, posture="supine", respiration_hz=0.23, heart_rate_bpm=70.0,
        hrv_ms=50.0, anomaly_score=anom, confidence=0.85,
    )


def _periph(co2: float = 600.0) -> list[PeripheralReading]:
    ts = now_us()
    return [
        PeripheralReading(type=Peripheral.SCD40, value=co2, unit="ppm", timestamp_us=ts),
        PeripheralReading(type=Peripheral.MAX30102, value=98.0, unit="%", timestamp_us=ts),
    ]


def _top_p(resp) -> float:
    return float(resp.differentials[0].rsplit("P=", 1)[1].rstrip(")"))


def test_synonym_file_loaded_and_colloquial_terms_match() -> None:
    assert load_clinical_synonyms()
    ext = SymptomExtractor()
    assert "headache" in ext.extract("cabeca latejando").concepts
    assert "dyspnea" in ext.extract("respiracao curta depois do treino").concepts
    assert "blurred_vision" in ext.extract("my vision feels blurry").concepts


def test_negated_symptoms_are_not_extracted() -> None:
    ext = SymptomExtractor()
    assert "headache" not in ext.extract("nao estou com dor de cabeca, so passei para dar bom dia").concepts
    res = ext.extract("sem falta de ar e sem tontura, apenas dormi pouco")
    assert "dyspnea" not in res.concepts and "dizziness" not in res.concepts
    assert "insomnia" in res.concepts
    assert "headache" in ext.extract("estou com dor de cabeca e sem tontura").concepts


def test_fuzzy_typo_matches_but_non_clinical_does_not() -> None:
    ext = SymptomExtractor()
    assert "headache" in ext.extract("estou com cefaleai forte").concepts
    assert ext.extract("preciso de ajuda").concepts == ()
    assert ext.extract("ola tudo bem").concepts == ()


def test_followup_polarity_uncertainty_is_not_yes_or_no() -> None:
    assert detect_followup_polarity("sim") == "yes"
    assert detect_followup_polarity("nao") == "no"
    for txt in ("talvez", "nao sei", "not sure", "nao tenho certeza se melhora"):
        assert detect_followup_polarity(txt) == "unsure", txt


def test_negated_allergy_is_not_stored_and_positive_is() -> None:
    assert not [f for f in extract_permanent_facts("nao sou alergico a dipirona") if f["fact_type"] == "ALLERGY"]
    facts = extract_permanent_facts("sou alergico a sulfa, nao sou alergico a dipirona")
    keys = {f["fact_key"] for f in facts if f["fact_type"] == "ALLERGY"}
    assert any(k.startswith("sulfa") for k in keys)
    assert not any("dipirona" in k for k in keys)


def test_prior_multipliers_from_memory_and_profile_are_bounded() -> None:
    mult = derive_prior_multipliers(
        [{"fact_type": "SENSITIVITY", "fact_key": "co2_sensitivity"}],
        {"sans_susceptibility": "HIGH"},
    )
    assert mult["HYPERCAPNIA"] == pytest.approx(1.5)
    assert mult["SANS"] == pytest.approx(1.4)
    assert all(0.5 <= v <= 2.0 for v in mult.values())
    assert derive_prior_multipliers([], {"co2_sensitivity": "NORMAL"}) == {}


def test_unsure_answer_does_not_change_posterior_but_yes_does(tmp_path: Path) -> None:
    db = _db(tmp_path)
    corr = ClinicalCorrelator(db_path=db)
    prof = CrewProfile(crew_id="crew_003", name="Eng. Sato", mission_day=12)
    first = "ola, estou com dores de cabeça ao olhar para a luz"
    t1 = corr.correlate(
        ChatCorrelateReqPayload(text=first, crew_id="crew_003", profile=prof), peripherals=_periph(), inference=_inf()
    )
    assert t1.disambiguation_question
    hist = [
        ChatMessage(sent_at_us=now_us() - 2000, role="user", content=first),
        ChatMessage(sent_at_us=now_us() - 1000, role="assistant", content=t1.disambiguation_question),
    ]
    r_unsure = corr.correlate(
        ChatCorrelateReqPayload(text="talvez", crew_id="crew_003", profile=prof, recent_history=hist),
        peripherals=_periph(), inference=_inf(),
    )
    assert not any(u.get("fact_type") == "ANSWERED_TOPIC" for u in (r_unsure.memory_updates or []))
    r_yes = corr.correlate(
        ChatCorrelateReqPayload(text="sim", crew_id="crew_003", profile=prof, recent_history=hist),
        peripherals=_periph(), inference=_inf(),
    )
    assert any(u.get("fact_type") == "ANSWERED_TOPIC" and u["fact_value"] == "yes" for u in r_yes.memory_updates)
    assert _top_p(r_yes) != _top_p(r_unsure)


def test_disambiguator_ig_uses_shared_likelihood_table() -> None:
    def _cond(cid: str, symptoms: dict[str, float]) -> CausalCondition:
        return CausalCondition(
            id=cid, name=cid, source_id="S", subsystem="X", prior=0.1, default_escalation=Escalation.LOCAL,
            symptoms=symptoms, sensor_rules=(), countermeasures=(), actions=(), disambiguation_questions=(),
        )

    q = DisambiguationQuestion(id="Q", prompt="?", positive_concepts=("headache",), yes_likelihood=0.9,
                               no_likelihood=0.1, owner_condition_id="A")
    a, b, c = _cond("A", {"headache": 0.9}), _cond("B", {"headache": 0.5}), _cond("C", {"nausea": 0.5})
    assert question_p_yes(q, a) == pytest.approx(0.9)
    assert question_p_yes(q, b) == pytest.approx(0.5)
    assert question_p_yes(q, c) == pytest.approx(0.1)

    hyps = [HypothesisPosterior(a, 0.4, (), ()), HypothesisPosterior(b, 0.4, (), ()), HypothesisPosterior(c, 0.2, (), ())]
    probs = [0.4, 0.4, 0.2]
    ig = Disambiguator._information_gain(q, hyps, probs, shannon_entropy(probs))
    py = [question_p_yes(q, x) for x in (a, b, c)]
    p_yes = sum(p * y for p, y in zip(probs, py))
    post_yes = [p * y / p_yes for p, y in zip(probs, py)]
    post_no = [p * (1 - y) / (1 - p_yes) for p, y in zip(probs, py)]
    expected = shannon_entropy(probs) - (p_yes * shannon_entropy(post_yes) + (1 - p_yes) * shannon_entropy(post_no))
    assert ig == pytest.approx(expected)


def test_online_clean_baseline_gates_and_anchor_freeze(tmp_path: Path) -> None:
    db = _db(tmp_path)
    reg = BaselineRegistry(models_dir=tmp_path, db_path=db)
    reg.set_active_crew("crew_001")
    cal = CalibrationEngine(reg)
    base0 = reg.get("crew_001")
    assert base0 is not None
    vec = base0.mean.copy() + 0.1

    # Blocked by high anomaly, symptom present, bad link quality, unknown posture
    assert cal.apply_clean_sample("crew_001", vec, anomaly_score=0.9 * base0.threshold, posture="supine", now_s=100.0) is None
    assert cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, posture="supine", symptomatic=True, now_s=100.0) is None
    assert cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, link_quality=0.4, posture="supine", now_s=100.0) is None
    assert cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, posture="unknown", now_s=100.0) is None
    # Uncalibrated crew is also rejected
    reg.set_active_crew("crew_003")
    assert cal.apply_clean_sample("crew_003", vec, anomaly_score=0.1, posture="supine", now_s=100.0) is None

    # Clean sample accepted; threshold stays frozen; posture alias maps exercising -> exercise
    reg.set_active_crew("crew_001")
    u1 = cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, posture="exercising", now_s=100.0)
    assert u1 is not None
    assert u1.threshold == pytest.approx(base0.threshold)
    assert canonical_posture("exercising") == "exercise"
    assert "exercise" in u1.per_posture_stats

    # Rate limit blocks immediate repeat, accepts after ONLINE_MIN_INTERVAL_S
    assert cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, posture="supine", now_s=110.0) is None
    u2 = cal.apply_clean_sample("crew_001", vec, anomaly_score=0.1, posture="supine", now_s=100.0 + ONLINE_MIN_INTERVAL_S)
    assert u2 is not None and cal.anchor_drift("crew_001") is not None

    # Gradual large drift past ONLINE_MAX_ANCHOR_DRIFT stops updating (pathology cannot erase anchor)
    far = base0.mean + 50.0 * base0.std
    t = 500.0
    for _ in range(40):
        t += ONLINE_MIN_INTERVAL_S + 1.0
        cal.apply_clean_sample("crew_001", far, anomaly_score=0.1, posture="supine", now_s=t)
    drift = cal.anchor_drift("crew_001")
    assert drift is not None and drift > ONLINE_MAX_ANCHOR_DRIFT
    assert cal.apply_clean_sample("crew_001", far, anomaly_score=0.1, posture="supine", now_s=t + 120.0) is None

