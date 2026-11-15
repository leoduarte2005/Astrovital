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
    CausalGraph,
    DisambiguationQuestion,
    HypothesisPosterior,
    question_p_yes,
)
from edgespace_ai.correlation.correlator import (
    ClinicalCorrelator,
    classify_intent,
    derive_prior_multipliers,
    extract_permanent_facts,
)
from edgespace_ai.correlation.disambiguator import Disambiguator, shannon_entropy
from edgespace_ai.correlation.symptom_extractor import (
    ExtractedSymptoms,
    SymptomExtractor,
    detect_followup_polarity,
    load_clinical_synonyms,
)
from edgespace_ai.correlation.synthesizer import LocalSLMSynthesizer
from edgespace_ai.dsp.feature_extractor import FEATURE_DIM
from edgespace_ai.ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    ChatMessage,
    CrewProfile,
    Escalation,
    Peripheral,
    PeripheralReading,
    Threshold,
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
    assert "headache" in ext.extract("throbbing head").concepts
    assert "dyspnea" in ext.extract("hard to catch my breath after workout").concepts
    assert "blurred_vision" in ext.extract("my vision feels blurry").concepts


def test_negated_symptoms_are_not_extracted() -> None:
    ext = SymptomExtractor()
    assert "headache" not in ext.extract("no headache, just saying good morning").concepts
    res = ext.extract("no shortness of breath and no dizziness, just poor sleep")
    assert "dyspnea" not in res.concepts and "dizziness" not in res.concepts
    assert "insomnia" in res.concepts
    assert "headache" in ext.extract("i have a headache and no dizziness").concepts


def test_fuzzy_typo_matches_but_non_clinical_does_not() -> None:
    ext = SymptomExtractor()
    assert "headache" in ext.extract("bad headahce today").concepts
    assert ext.extract("i need help").concepts == ()
    assert ext.extract("hello how are you").concepts == ()


def test_followup_polarity_uncertainty_is_not_yes_or_no() -> None:
    assert detect_followup_polarity("yes") == "yes"
    assert detect_followup_polarity("no") == "no"
    for txt in ("maybe", "not sure", "a little", "i don't know", "not sure if it improves"):
        assert detect_followup_polarity(txt) == "unsure", txt


def test_negated_allergy_is_not_stored_and_positive_is() -> None:
    assert not [f for f in extract_permanent_facts("i am not allergic to penicillin") if f["fact_type"] == "ALLERGY"]
    facts = extract_permanent_facts("i am allergic to sulfa, i am not allergic to penicillin")
    keys = {f["fact_key"] for f in facts if f["fact_type"] == "ALLERGY"}
    assert any(k.startswith("sulfa") for k in keys)
    assert not any("penicillin" in k for k in keys)


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
    first = "hello, I have headaches when looking at the light"
    t1 = corr.correlate(
        ChatCorrelateReqPayload(text=first, crew_id="crew_003", profile=prof), peripherals=_periph(), inference=_inf()
    )
    assert t1.disambiguation_question
    hist = [
        ChatMessage(sent_at_us=now_us() - 2000, role="user", content=first),
        ChatMessage(sent_at_us=now_us() - 1000, role="assistant", content=t1.disambiguation_question),
    ]
    r_unsure = corr.correlate(
        ChatCorrelateReqPayload(text="maybe", crew_id="crew_003", profile=prof, recent_history=hist),
        peripherals=_periph(), inference=_inf(),
    )
    assert not any(u.get("fact_type") == "ANSWERED_TOPIC" for u in (r_unsure.memory_updates or []))
    r_yes = corr.correlate(
        ChatCorrelateReqPayload(text="yes", crew_id="crew_003", profile=prof, recent_history=hist),
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


_FORBIDDEN_PT_TOKENS = ("Entendido", "Hipótese", "Sintomas", "Apoio à decisão", "Olá")


def _assert_no_portuguese_leak(resp) -> None:
    chunks = [
        resp.text or "",
        resp.disclaimer or "",
        resp.disambiguation_question or "",
        *(resp.differentials or []),
        *(resp.evidence or []),
        *(resp.countermeasures or []),
    ]
    blob = "\n".join(chunks)
    for tok in _FORBIDDEN_PT_TOKENS:
        assert tok not in blob, f"Portuguese token {tok!r} leaked into CHAT_CORRELATE_RESP: {blob}"


def test_health_checkup_with_yellow_co2_places_hypercapnia_top1_without_entendido(tmp_path: Path) -> None:
    db = _db(tmp_path)
    prof = CrewProfile(crew_id="crew_001", name="Cmdr. Silva", mission_day=12)
    inf_prone = AIInferencePayload(
        cycle_seq_first=1, posture="prone", respiration_hz=0.25, heart_rate_bpm=74.0,
        hrv_ms=48.0, anomaly_score=0.3, confidence=0.9,
    )
    thresholds = {"co2_ppm": Threshold(metric_name="co2_ppm", yellow_high=2500.0, red_high=5000.0)}
    periph = _periph(co2=3242.4)

    cg_yaml = CausalGraph(allow_yaml_for_tests=True)
    assess = cg_yaml.evaluate(
        symptoms=ExtractedSymptoms(
            concepts=(), matched_terms=(), eva_context=False, radiation_context=False, answered_topics=(),
        ),
        peripherals=periph,
        inference=inf_prone,
        thresholds=thresholds,
        profile=prof,
    )
    assert assess.hypotheses[0].condition.id == "hypercapnia_co2"

    for corr in (ClinicalCorrelator(db_path=db), ClinicalCorrelator(allow_yaml_for_tests=True)):
        resp = corr.correlate(
            ChatCorrelateReqPayload(text="how is my health today?", crew_id="crew_001", profile=prof),
            peripherals=periph,
            inference=inf_prone,
            thresholds=thresholds,
        )
        _assert_no_portuguese_leak(resp)
        assert resp.differentials
        top_diff = resp.differentials[0].lower()
        assert "hypercapnia" in top_diff
        assert "radiation" not in top_diff
        assert not resp.text.lstrip().startswith(("Understood", "Entendido"))

        slm = LocalSLMSynthesizer(disabled=True, auto_load=False)
        out = slm.synthesize_response(resp, [], {"co2_ppm": 3242.4, "spo2_pct": 98.0})
        assert not out.lstrip().startswith(("Understood", "Entendido"))
        assert "briefing" in out.lower() or "vital signs" in out.lower()


def test_greeting_with_elevated_co2_returns_natural_greeting_and_short_warning(tmp_path: Path) -> None:
    db = _db(tmp_path)
    prof = CrewProfile(crew_id="crew_001", name="Cmdr. Silva", mission_day=12)
    thresholds = {"co2_ppm": Threshold(metric_name="co2_ppm", yellow_high=2500.0, red_high=5000.0)}
    periph = _periph(co2=3458.0)

    corr = ClinicalCorrelator(db_path=db)
    for greet_msg in ("hello", "hi there"):
        greet_resp = corr.correlate(
            ChatCorrelateReqPayload(text=greet_msg, crew_id="crew_001", profile=prof),
            peripherals=periph,
            inference=_inf(),
            thresholds=thresholds,
        )
        _assert_no_portuguese_leak(greet_resp)
        assert greet_resp.text.startswith("Hello, Cmdr. Silva")
        assert "3458" in greet_resp.text
        assert "co2" in greet_resp.text.lower()
        assert "primary hypothesis" not in greet_resp.text.lower()
        assert "briefing" not in greet_resp.text.lower()

        slm = LocalSLMSynthesizer(disabled=True, auto_load=False)
        msgs = slm.build_messages(greet_resp, [], {"co2_ppm": 3458.0})
        assert "GREETING" in msgs[1]["content"]
        assert slm.synthesize_response(greet_resp, [], {"co2_ppm": 3458.0}) == greet_resp.text

    checkup_resp = corr.correlate(
        ChatCorrelateReqPayload(text="how is my health today?", crew_id="crew_001", profile=prof),
        peripherals=periph,
        inference=_inf(),
        thresholds=thresholds,
    )
    assert greet_resp.text != checkup_resp.text


def test_symptom_reports_english_and_zero_portuguese_leak(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM mission_context_events")
        c.execute("DELETE FROM telemetry_daily_rollups")
        c.commit()
    corr = ClinicalCorrelator(db_path=db)
    prof = CrewProfile(crew_id="crew_003", name="Eng. Sato", mission_day=12)

    resp_sans = corr.correlate(
        ChatCorrelateReqPayload(
            text="hello, I have headaches when looking at the light",
            crew_id="crew_003",
            profile=prof,
        ),
        peripherals=_periph(co2=600.0),
        inference=_inf(),
    )
    _assert_no_portuguese_leak(resp_sans)
    assert resp_sans.differentials and "SANS" in resp_sans.differentials[0]
    assert "headache" in resp_sans.text.lower()

    resp_gi = corr.correlate(
        ChatCorrelateReqPayload(
            text="I have a stomach ache",
            crew_id="crew_003",
            profile=prof,
        ),
        peripherals=_periph(co2=600.0),
        inference=_inf(),
    )
    _assert_no_portuguese_leak(resp_gi)
    assert resp_gi.differentials and "GI" in resp_gi.differentials[0]
    assert "abdominal pain" in resp_gi.text.lower()


def test_intent_routing_and_hypoxia_sensor_dominance(tmp_path: Path) -> None:
    ext = SymptomExtractor()
    assert classify_intent("hello", ext.extract("hello")) == "GREETING"
    assert classify_intent("hi there", ext.extract("hi there")) == "GREETING"
    assert classify_intent("good morning", ext.extract("good morning")) == "GREETING"
    assert classify_intent("how is my health today?", ext.extract("how is my health today?")) == "HEALTH_CHECKUP"
    assert classify_intent("vital signs status", ext.extract("vital signs status")) == "HEALTH_CHECKUP"
    assert classify_intent("am i okay?", ext.extract("am i okay?")) == "HEALTH_CHECKUP"
    assert classify_intent("I have a stomach ache", ext.extract("I have a stomach ache")) == "SYMPTOM_OR_FOLLOWUP"

    # SpO2 <= 94% without symptoms places hypoxia Top-1
    ts = now_us()
    low_spo2 = [
        PeripheralReading(type=Peripheral.SCD40, value=650.0, unit="ppm", timestamp_us=ts),
        PeripheralReading(type=Peripheral.MAX30102, value=93.0, unit="%", timestamp_us=ts),
    ]
    thresholds = {"spo2_pct": Threshold(metric_name="spo2_pct", yellow_high=0.0, red_high=0.0, yellow_low=94.0, red_low=90.0)}
    cg_yaml = CausalGraph(allow_yaml_for_tests=True)
    hyp_assess = cg_yaml.evaluate(
        symptoms=ExtractedSymptoms(
            concepts=(), matched_terms=(), eva_context=False, radiation_context=False, answered_topics=(),
        ),
        peripherals=low_spo2,
        inference=_inf(),
        thresholds=thresholds,
        profile=CrewProfile(crew_id="crew_003", name="Eng. Sato", mission_day=15),
    )
    assert hyp_assess.hypotheses[0].condition.id == "hypoxia"

    # Nominal check-up with mission_day >= 7 and posture == prone must not emit pathology differentials
    db = _db(tmp_path)
    corr = ClinicalCorrelator(db_path=db)
    nominal_inf = AIInferencePayload(
        cycle_seq_first=1, posture="prone", respiration_hz=0.22, heart_rate_bpm=68.0,
        hrv_ms=52.0, anomaly_score=0.2, confidence=0.9,
    )
    nom_resp = corr.correlate(
        ChatCorrelateReqPayload(
            text="how is my health today?",
            crew_id="crew_003",
            profile=CrewProfile(crew_id="crew_003", name="Eng. Sato", mission_day=15),
        ),
        peripherals=_periph(co2=600.0),
        inference=nominal_inf,
    )
    _assert_no_portuguese_leak(nom_resp)
    assert nom_resp.differentials is None
    assert "briefing" in nom_resp.text.lower()


