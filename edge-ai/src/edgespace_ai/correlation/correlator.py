"""Clinical causal correlator assembling CHAT_CORRELATE_RESP payloads."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Sequence

from ..adaptation.baseline_registry import CrewBaseline
from ..ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    ChatCorrelateRespPayload,
    Escalation,
    PeripheralReading,
    Threshold,
    CrewProfile,
    now_us,
)
from .causal_graph import CausalGraph
from .clinical_store import ClinicalStore
from .disambiguator import Disambiguator
from .symptom_extractor import (
    SymptomExtractor,
    _normalize_text,
    detect_followup_polarity,
    is_pure_greeting,
)
from ..clinical import ClinicalRepository

CLINICAL_DISCLAIMER = (
    "Onboard clinical decision support; does not replace Flight Surgeon evaluation."
)

_STOP_WORDS_FACT = frozenset({"and", "but", "because", "with", "that", "water", "care", "e", "mas", "porque", "com", "que", "agua", "banho", "cuidado"})


def _slug_fact_key(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", _normalize_text(text)).strip("_")
    return cleaned[:48] or "unspecified"


def _trim_entity(raw: str) -> str:
    head = re.split(r"[,.;!?\n]|(?:\s+(?:and|but|because|with|e|mas|porque|com)\s+)", raw.strip(), maxsplit=1)[0]
    words = [w for w in head.strip().split() if w]
    return " ".join(words[:4]).strip()


_NEGATED_FACT_RE = re.compile(
    r"\b(?:not|never|no|don'?t|do\s+not|nao|nunca|sem)\s+(?:allergic|taking|take|have|had|am|i'm|im|sou|tenho|estou|uso|tomo)\b|"
    r"\b(?:i\s+am|i'm|im)\s+not\s+(?:allergic|taking|on)\b"
)


def _drop_negated_fact_clauses(norm: str) -> str:
    """Remove clauses like 'nao sou alergico a X' so negated facts are never stored."""
    clauses = re.split(r"[,.;!?]+|\s+(?:mas|but)\s+", norm)
    return ", ".join(c.strip() for c in clauses if c.strip() and not _NEGATED_FACT_RE.search(c))


# (fact_type, fact_key substring) -> {condition_id: prior multiplier}; bounded by CausalGraph.
_MEMORY_PRIOR_RULES: tuple[tuple[str, str, dict[str, float]], ...] = (
    ("SENSITIVITY", "co2", {"HYPERCAPNIA": 1.5}),
    ("CONDITION_HISTORY", "space_motion_sickness", {"SPACE_MOTION_SICKNESS": 1.6}),
    ("CONDITION_HISTORY", "sans", {"SANS": 1.5}),
    ("CONDITION_HISTORY", "viip", {"SANS": 1.5}),
    ("SLEEP_NOTE", "poor_sleep", {"SLEEP_CIRCADIAN": 1.3}),
)
_PROFILE_PRIOR_RULES: tuple[tuple[str, str, dict[str, float]], ...] = (
    ("co2_sensitivity", "HIGH", {"HYPERCAPNIA": 1.4}),
    ("sans_susceptibility", "HIGH", {"SANS": 1.4}),
    ("sas_susceptibility", "HIGH", {"SPACE_MOTION_SICKNESS": 1.4}),
    ("motion_sickness_history", "HIGH", {"SPACE_MOTION_SICKNESS": 1.4}),
)


def derive_prior_multipliers(
    facts: Sequence[dict[str, Any]],
    crew_row: Optional[dict[str, Any]] = None,
) -> dict[str, float]:
    """Turn permanent crew facts + profile susceptibilities into bounded per-condition prior multipliers."""
    out: dict[str, float] = {}
    for fact in facts:
        ftype = str(fact.get("fact_type") or "")
        fkey = _normalize_text(str(fact.get("fact_key") or ""))
        for rule_type, needle, effects in _MEMORY_PRIOR_RULES:
            if ftype == rule_type and needle in fkey:
                for cid, m in effects.items():
                    out[cid] = max(out.get(cid, 1.0), m)
    if crew_row:
        for column, level, effects in _PROFILE_PRIOR_RULES:
            if str(crew_row.get(column) or "").upper() == level:
                for cid, m in effects.items():
                    out[cid] = max(out.get(cid, 1.0), m)
    return out


def extract_permanent_facts(text: str) -> list[dict[str, Any]]:
    """Deterministically extract English (and legacy PT) permanent clinical facts for crew_clinical_memory."""
    norm = _drop_negated_fact_clauses(_normalize_text(text))
    if not norm:
        return []
    updates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(fact_type: str, fact_key: str, fact_value: str, confidence: float) -> None:
        sig = (fact_type, fact_key)
        if not fact_key or sig in seen:
            return
        seen.add(sig)
        updates.append({
            "fact_type": fact_type,
            "fact_key": fact_key,
            "fact_value": fact_value,
            "confidence": confidence,
            "source_role": "user",
        })

    # ALLERGY (EN primary, PT fallback)
    for pat in (
        r"\b(?:i\s+am|i'm|im)\s+allergic\s+to\s+([a-z0-9\- ]{2,45})",
        r"\ballerg(?:y|ic)\s+to\s+([a-z0-9\- ]{2,45})",
        r"\b(?:sou|tenho|estou)\s+alergic[oa]\s+a(?:o|s)?\s+([a-z0-9\- ]{2,45})",
        r"\balergia\s+a(?:o|s)?\s+([a-z0-9\- ]{2,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            if ent and _slug_fact_key(ent) not in _STOP_WORDS_FACT:
                _add("ALLERGY", _slug_fact_key(ent), ent, 0.95)

    # MEDICATION (EN primary, PT fallback)
    for pat in (
        r"\b(?:i\s+take|i\s+am\s+taking|i'm\s+taking|currently\s+taking|on\s+medication)\s+([a-z0-9\- ]{2,45})",
        r"\b(?:tomo|estou\s+tomando|uso\s+continuo\s+de|faco\s+uso\s+de|uso)\s+([a-z0-9\- ]{2,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug not in _STOP_WORDS_FACT and not slug.startswith(("water", "care", "a_look", "a_breath", "agua", "banho", "cuidado")):
                _add("MEDICATION", slug, ent, 0.90)

    # CONDITION_HISTORY (EN primary, PT fallback)
    if any(p in norm for p in ("space motion sickness", "motion sickness", "enjoo espacial")):
        if any(c in norm for c in ("history", "previously", "had ", "ja tive", "historico")):
            _add("CONDITION_HISTORY", "space_motion_sickness", "1", 0.85)
    for pat in (
        r"\b(?:i\s+have\s+a\s+history\s+of|history\s+of|previously\s+had|i've\s+had)\s+([a-z0-9\- ]{3,45})",
        r"\b(?:ja\s+tive|tenho\s+historico\s+de|historico\s+previo\s+de)\s+([a-z0-9\- ]{3,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug not in _STOP_WORDS_FACT and "motion_sickness" not in slug and "enjoo_espacial" not in slug:
                _add("CONDITION_HISTORY", slug, "1", 0.85)

    # SENSITIVITY (EN primary, PT fallback)
    if re.search(r"\bco2\b.*(?:headache|headaches|sensitive|sensitivity|sick|unwell|dor\s+de\s+cabeca|sensivel|sensibilidade|mal)", norm) or any(
        p in norm for p in ("sensitive to co2", "co2 sensitivity", "sensivel a co2", "sensibilidade a co2")
    ):
        _add("SENSITIVITY", "co2_sensitivity", "1", 0.85)
    for pat in (
        r"\b(?:sensitive\s+to|sensitivity\s+to|sensivel\s+a|sensibilidade\s+a)\s+([a-z0-9\- ]{2,35})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug != "co2":
                _add("SENSITIVITY", f"{slug}_sensitivity", "1", 0.85)

    # SLEEP_NOTE (EN primary, PT fallback)
    if any(p in norm for p in ("slept poorly", "bad sleep", "poor sleep", "insomnia", "didn't sleep", "didnt sleep", "barely slept", "dormi mal", "nao dormi", "pouco sono", "acordei varias vezes")):
        _add("SLEEP_NOTE", "poor_sleep", text.strip()[:120], 0.80)

    return updates


class ClinicalCorrelator:
    """Cross-correlates chat symptoms, sensor snapshots, history, and crew baseline."""

    def __init__(
        self,
        *,
        db_path: Optional[Path | str] = None,
        knowledge_base_path: Optional[Path | str] = None,
        allow_yaml_for_tests: bool = False,
    ) -> None:
        default_kb = Path(__file__).resolve().parents[3] / "knowledge-base" / "nasa_causal_graph.yaml"
        kb_path = Path(knowledge_base_path) if knowledge_base_path else default_kb

        self.clinical_store = ClinicalStore(db_path=db_path, knowledge_base_path=kb_path)
        self.symptom_extractor = SymptomExtractor(clinical_store=self.clinical_store)
        self.db_path = Path(db_path) if db_path is not None else None
        self.causal_graph = CausalGraph(
            knowledge_base_path=kb_path,
            db_path=db_path,
            allow_yaml_for_tests=allow_yaml_for_tests,
        )
        self.disambiguator = Disambiguator()

    def correlate(
        self,
        req: ChatCorrelateReqPayload,
        *,
        peripherals: Sequence[PeripheralReading] = (),
        inference: Optional[AIInferencePayload] = None,
        thresholds: Optional[dict[str, Threshold]] = None,
        baseline: Optional[CrewBaseline] = None,
    ) -> ChatCorrelateRespPayload:
        """Run end-to-end clinical causal correlation and build ``CHAT_CORRELATE_RESP``."""
        objective=None
        memory=[]
        crew: dict[str, Any] = {}
        memory_updates = extract_permanent_facts(req.text)
        if self.db_path is not None and req.crew_id:
            with ClinicalRepository(self.db_path) as repo:
                crew=repo.crew(req.crew_id)
                memory=repo.memory(req.crew_id)
            profile_kwargs = {k: crew[k] for k in CrewProfile.model_fields if k in crew}
            req=req.model_copy(update={"profile":CrewProfile(**profile_kwargs)})

        now_ts = now_us()
        episode_cutoff_us = now_ts - 6 * 3600_000_000
        in_multiturn = bool(req.recent_history)
        answered_questions: dict[str, str] = {
            str(m["fact_key"]): str(m["fact_value"])
            for m in memory
            if m.get("fact_type") == "ANSWERED_TOPIC"
            and m.get("fact_key")
            and m.get("fact_value") in ("yes", "no")
            and (
                in_multiturn
                or str(m.get("source_role") or "") == "SEED"
                or int(m.get("updated_us") or 0) >= episode_cutoff_us
            )
        }
        last = next(
            (m["fact_value"] for m in memory if m["fact_key"] == "last_question_id" and m["fact_type"] == "PREFERENCE"),
            None,
        )
        if not last and req.recent_history:
            for msg in reversed(req.recent_history):
                if msg.role == "assistant":
                    msg_norm = _normalize_text(msg.content)
                    for cond in self.causal_graph.conditions:
                        for q in cond.disambiguation_questions:
                            if q.prompt and _normalize_text(q.prompt) in msg_norm:
                                last = q.id
                                break
                        if last:
                            break
                    break

        skip_questions_this_turn: set[str] = set()
        polarity = detect_followup_polarity(req.text)
        if last and polarity in ("yes", "no"):
            answered_questions[last] = polarity
            memory_updates.append(
                dict(
                    fact_type="ANSWERED_TOPIC",
                    fact_key=last,
                    fact_value=polarity,
                    confidence=1.0,
                    source_role="user",
                )
            )
        elif last and polarity == "unsure":
            # Uncertain answer: do NOT shift Bayesian posterior, just advance past this question.
            skip_questions_this_turn.add(last)
        extracted = self.symptom_extractor.extract(
            req.text,
            recent_history=req.recent_history,
            summary_24h=req.summary_24h,
        )
        intent = classify_intent(
            req.text,
            extracted,
            has_pending_question=bool(last),
            polarity=polarity,
        )

        assessment = self.causal_graph.evaluate(
            symptoms=extracted,
            peripherals=peripherals,
            inference=inference,
            thresholds=thresholds,
            profile=req.profile,
            baseline=baseline,
            answered_questions=answered_questions or None,
            prior_multipliers=derive_prior_multipliers([*memory, *memory_updates], crew) or None,
        )

        store_docs = (
            list(extracted.fallback_docs)
            if extracted.fallback_docs
            else self.clinical_store.search(
                req.text,
                concepts=extracted.concepts,
                limit=3,
            )
        )

        top_hypotheses = assessment.hypotheses
        top = top_hypotheses[0] if top_hypotheses else None

        sensors_nominal = (
            not assessment.red_breach
            and not assessment.yellow_breach
            and not assessment.threshold_breaches
            and _sensors_are_nominal(assessment.metrics)
        )
        if intent == "SYMPTOM_OR_FOLLOWUP" and not extracted.concepts and sensors_nominal:
            evidence_nominal: list[str] = []
            for reading in peripherals:
                evidence_nominal.append(f"Sensor {reading.type.value}: {reading.value:.2f} {reading.unit}")
            if inference is not None:
                evidence_nominal.append(
                    f"CSI vitals: posture={inference.posture}, HR={inference.heart_rate_bpm:.1f} bpm, "
                    f"RR={inference.respiration_hz * 60.0:.1f} bpm, anomaly={inference.anomaly_score:.2f}, "
                    f"conf={inference.confidence:.2f}"
                )
            for doc in store_docs[:2]:
                evidence_nominal.append(f"Clinical base ({doc.source}): {doc.doc_id} - {doc.title}")

            if self.db_path is not None and req.crew_id:
                with ClinicalRepository(self.db_path) as repo:
                    objective = repo.assess_fixture(req.crew_id, assessment.metrics, allow_engineering=True)

            crew_label = req.profile.name if (req.profile and req.profile.name) else "crew member"
            telemetry_str = _format_telemetry_summary(assessment.metrics, req.profile)
            clarification_prompt = (
                "No specific symptoms were identified in your message and sensor readings are nominal. "
                "Could you describe what you are feeling (pain location, duration, nausea, dizziness, "
                "visual changes, or shortness of breath)?"
            )
            fts_note = ""
            if extracted.fallback_docs:
                titles = "; ".join(d.title for d in extracted.fallback_docs[:2])
                fts_note = f" Related NASA references retrieved via FTS5: {titles}."
            source_ids_nom = [d.source_id or d.doc_id for d in store_docs[:2] if (d.source_id or d.doc_id)] or ["EDGESPACE-AI-V1"]
            return ChatCorrelateRespPayload(
                matched_condition_ids=[m["condition_id"] for m in objective["matches"]] if objective else None,
                max_severity=objective["max_severity"] if objective else None,
                blocked_actions=objective["blocked_actions"] if objective else None,
                memory_updates=memory_updates or None,
                text=(
                    f"{crew_label}, no specific symptoms were recognized in your message and your current "
                    f"sensors ({telemetry_str}) are within nominal limits.{fts_note} "
                    "Please describe what you are feeling (location, intensity, and duration) so I can investigate further."
                ),
                differentials=None,
                evidence=evidence_nominal or None,
                countermeasures=[
                    "Describe symptom location, intensity, and duration for clinical re-evaluation.",
                    "Maintain continuous monitoring of vital signs and cabin environment.",
                ],
                source_ids=source_ids_nom,
                escalation=Escalation.LOCAL,
                disclaimer=CLINICAL_DISCLAIMER,
                disambiguation_question=clarification_prompt,
                actions=None,
            )

        # Evidence list
        evidence: list[str] = []
        if extracted.concepts:
            evidence.append(f"Detected symptoms: {', '.join(extracted.concepts)}")
        for reading in peripherals:
            evidence.append(f"Sensor {reading.type.value}: {reading.value:.2f} {reading.unit}")
        if inference is not None:
            evidence.append(
                f"CSI vitals: posture={inference.posture}, HR={inference.heart_rate_bpm:.1f} bpm, "
                f"RR={inference.respiration_hz * 60.0:.1f} bpm, anomaly={inference.anomaly_score:.2f}, "
                f"conf={inference.confidence:.2f}"
            )
        for breach in assessment.threshold_breaches:
            evidence.append(f"Threshold exceeded: {breach}")
        if top and top.matched_sensor_evidence:
            evidence.extend(top.matched_sensor_evidence)
        for doc in store_docs[:2]:
            evidence.append(f"Clinical base ({doc.source}): {doc.doc_id} - {doc.title}")

        # Differentials list
        differentials: list[str] = []
        if not (intent in ("GREETING", "HEALTH_CHECKUP") and sensors_nominal):
            for h in top_hypotheses[:3]:
                if h.posterior >= 0.08 or len(differentials) == 0:
                    differentials.append(f"{h.condition.name} (P={h.posterior:.2f})")

        # Disambiguation question via information gain (skipped for pure greetings or nominal check-ups)
        disambig = None
        if intent == "SYMPTOM_OR_FOLLOWUP" or (intent == "HEALTH_CHECKUP" and not sensors_nominal):
            disambig = self.disambiguator.select_question(
                top_hypotheses,
                answered_topics=(
                    set(extracted.answered_topics)
                    | set(answered_questions.keys())
                    | skip_questions_this_turn
                    | {m["fact_key"] for m in memory_updates if m.get("fact_type") == "ANSWERED_TOPIC"}
                ),
                observed_concepts=extracted.concepts,
            )

        # Escalation policy
        escalation = Escalation.LOCAL
        if intent in ("GREETING", "HEALTH_CHECKUP") and sensors_nominal:
            escalation = Escalation.LOCAL
        elif assessment.red_breach:
            escalation = Escalation.STORE_AND_FORWARD
        elif top and top.posterior >= 0.55 and top.condition.default_escalation == Escalation.STORE_AND_FORWARD:
            escalation = Escalation.STORE_AND_FORWARD
        elif assessment.yellow_breach or (top and top.posterior >= 0.45 and top.condition.default_escalation == Escalation.CREW):
            escalation = Escalation.CREW

        # Countermeasures, source IDs, and actions
        if intent in ("GREETING", "HEALTH_CHECKUP") and sensors_nominal:
            countermeasures = ["Maintain continuous monitoring of vital signs and cabin environment."]
            actions = []
        else:
            countermeasures = list(top.condition.countermeasures) if top else [
                "Maintain continuous monitoring of vital signs and cabin environment."
            ]
            actions = list(top.condition.actions) if top else []

        blocked_by_memory: list[str] = []
        active_mem = [*memory, *memory_updates]
        allergy_med_facts = [
            m for m in active_mem
            if m.get("fact_type") in ("ALLERGY", "MEDICATION")
        ]
        contra_metrics = dict(assessment.metrics)
        for m in allergy_med_facts:
            ftype = str(m.get("fact_type", "")).lower()
            fkey = str(m.get("fact_key", "")).lower()
            fval = str(m.get("fact_value", "")).lower()
            if fkey:
                contra_metrics[f"{ftype}_{fkey}"] = 1
            if fval:
                contra_metrics.setdefault(ftype, fval)

        if self.db_path is not None:
            with ClinicalRepository(self.db_path) as repo:
                long_row = repo.longitudinal(req.crew_id) if req.crew_id else {}
                if req.crew_id:
                    objective = repo.assess_fixture(req.crew_id, contra_metrics, allow_engineering=True)
                for row in repo.connection.execute('SELECT * FROM causal_contraindications'):
                    guard_val = contra_metrics.get(row['guard_metric'])
                    triggered = repo.compare(
                        guard_val, row['guard_op'], row['guard_value'],
                        rule_scope=row['rule_scope'] if 'rule_scope' in row.keys() else None,
                        metric=row['guard_metric'],
                        longitudinal=long_row,
                    )
                    if not triggered and allergy_med_facts:
                        hay = f"{row['guard_metric']} {row['blocked_action']} {row['rationale']}".lower()
                        for m in allergy_med_facts:
                            token = _normalize_text(str(m.get("fact_value") or m.get("fact_key") or ""))
                            if token and len(token) >= 3 and (token in hay or token[:5] in hay):
                                triggered = True
                                break
                    if triggered:
                        b_act = row['blocked_action']
                        if b_act not in blocked_by_memory:
                            blocked_by_memory.append(b_act)
                        actions = [a for a in actions if a != b_act]
                        evidence.append(
                            f"Blocked action: {b_act} — safety guard triggered "
                            f"({row['guard_metric']} {row['guard_op']} {row['guard_value']})"
                        )
            if disambig:
                memory_updates.append(dict(fact_type='PREFERENCE',fact_key='last_question_id',fact_value=disambig.question.id,confidence=1.0,source_role='assistant'))

        for m in allergy_med_facts:
            token = _normalize_text(str(m.get("fact_value") or m.get("fact_key") or ""))
            if not token or len(token) < 3:
                continue
            stem = token[:5] if len(token) >= 5 else token
            for act in list(actions):
                if stem in _normalize_text(act):
                    actions.remove(act)
                    if act not in blocked_by_memory:
                        blocked_by_memory.append(act)
                    evidence.append(f"Blocked action ({m.get('fact_type')}): {act} — conflict with {m.get('fact_value')}")
            if m.get("fact_type") == "ALLERGY":
                filtered_cm = []
                for cm in countermeasures:
                    if stem in _normalize_text(cm):
                        evidence.append(f"Countermeasure omitted due to allergy ({m.get('fact_value')}): {cm}")
                    else:
                        filtered_cm.append(cm)
                countermeasures = filtered_cm or countermeasures

        merged_blocked = list(objective["blocked_actions"]) if objective else []
        for b in blocked_by_memory:
            if b not in merged_blocked:
                merged_blocked.append(b)
        source_ids: list[str] = []
        for h in top_hypotheses[:2]:
            if h.posterior >= 0.15 and h.condition.source_id not in source_ids:
                source_ids.append(h.condition.source_id)
        for doc in store_docs:
            source=doc.source_id or doc.doc_id
            if source not in source_ids:
                source_ids.append(source)
        if not source_ids:
            source_ids.append("EDGESPACE-AI-V1")

        if intent == "GREETING":
            summary_text = _build_greeting_text(
                crew_profile=req.profile,
                metrics=assessment.metrics,
                breaches=assessment.threshold_breaches,
                sensors_nominal=sensors_nominal,
            )
        elif intent == "HEALTH_CHECKUP":
            summary_text = _build_health_checkup_text(
                crew_profile=req.profile,
                metrics=assessment.metrics,
                top=top,
                countermeasures=countermeasures,
                breaches=assessment.threshold_breaches,
                sensors_nominal=sensors_nominal,
            )
        elif top is not None:
            summary_text = _build_clinical_summary_text(
                crew_profile=req.profile,
                concepts=extracted.concepts,
                metrics=assessment.metrics,
                top=top,
                second=top_hypotheses[1] if len(top_hypotheses) > 1 else None,
                countermeasures=countermeasures,
                disambig_prompt=disambig.question.prompt if disambig else None,
                actions=actions,
                breaches=assessment.threshold_breaches,
                is_followup=bool(last and polarity in ("yes", "no", "unsure")),
            )
        else:
            crew_label = req.profile.name if (req.profile and req.profile.name) else "crew member"
            telemetry_str = _format_telemetry_summary(assessment.metrics, req.profile)
            summary_text = (
                f"{crew_label}, I reviewed your message '{req.text.strip()}' "
                f"alongside current telemetry ({telemetry_str})."
            )

        return ChatCorrelateRespPayload(
            matched_condition_ids=[m["condition_id"] for m in objective["matches"]] if objective else None,
            max_severity=objective["max_severity"] if objective else None,
            blocked_actions=merged_blocked or None,
            memory_updates=memory_updates or None,
            model_status="ENGINEERING_TEST_ONLY",
            text=summary_text,
            differentials=differentials or None,
            evidence=evidence or None,
            countermeasures=countermeasures,
            source_ids=source_ids,
            escalation=escalation,
            disclaimer=CLINICAL_DISCLAIMER,
            disambiguation_question=disambig.question.prompt if disambig else None,
            actions=actions or None,
        )


_HEALTH_CHECKUP_RE = re.compile(
    r"\b(?:"
    r"minha\s+saude|saude\s+hoje|como\s+esta\s+(?:a\s+)?minha\s+saude|"
    r"como\s+estao\s+(?:os\s+)?(?:meus\s+)?sinais|sinais\s+vitais|"
    r"status\s+(?:dos\s+)?(?:sinais|vitais|saude|hoje)|"
    r"check\s*-?\s*up|boletim\s+(?:clinico|medico|de\s+saude)|"
    r"resumo\s+(?:clinico|de\s+saude|dos\s+sinais)|"
    r"telemetria\s+(?:atual|de\s+hoje)|"
    r"como\s+estou(?:\s+hoje)?|como\s+eu\s+estou|"
    r"tudo\s+bem\s+comigo|estou\s+bem|"
    r"health\s+status|vital\s+signs|how\s+am\s+i|how\s+is\s+my\s+health|"
    r"am\s+i\s+(?:ok|okay|alright|good|fine)|check\s+my\s+(?:health|vitals)|daily\s+health"
    r")\b"
)


def classify_intent(
    text: str,
    extracted: Any,
    *,
    has_pending_question: bool = False,
    polarity: Optional[str] = None,
) -> str:
    """Route astronaut message into GREETING, HEALTH_CHECKUP, or SYMPTOM_OR_FOLLOWUP."""
    if getattr(extracted, "concepts", ()):
        return "SYMPTOM_OR_FOLLOWUP"
    if has_pending_question and polarity in ("yes", "no", "unsure"):
        return "SYMPTOM_OR_FOLLOWUP"
    norm = _normalize_text(text)
    if _HEALTH_CHECKUP_RE.search(norm):
        return "HEALTH_CHECKUP"
    if is_pure_greeting(text) or (
        getattr(extracted, "is_greeting", False) and not getattr(extracted, "fallback_docs", ())
    ):
        return "GREETING"
    return "SYMPTOM_OR_FOLLOWUP"


def _sensors_are_nominal(metrics: dict[str, Any]) -> bool:
    """Return True when all observed sensor readings and context flags are nominal."""
    if metrics.get("eva_context", 0.0) >= 1.0 or metrics.get("radiation_context", 0.0) >= 1.0:
        return False
    co2 = metrics.get("co2_ppm")
    if isinstance(co2, (int, float)) and co2 >= 1500.0:
        return False
    spo2 = metrics.get("spo2_pct")
    if isinstance(spo2, (int, float)) and spo2 <= 94.0:
        return False
    pressure = metrics.get("pressure_hpa")
    if isinstance(pressure, (int, float)) and pressure <= 750.0:
        return False
    temp = metrics.get("temp_c")
    if isinstance(temp, (int, float)) and temp >= 37.5:
        return False
    hr = metrics.get("heart_rate_bpm")
    if isinstance(hr, (int, float)) and (hr >= 95.0 or hr <= 45.0):
        return False
    rr = metrics.get("respiration_hz")
    if isinstance(rr, (int, float)) and rr >= 0.32:
        return False
    hrv = metrics.get("hrv_ms")
    if isinstance(hrv, (int, float)) and hrv <= 30.0:
        return False
    anomaly = metrics.get("anomaly_score")
    if isinstance(anomaly, (int, float)) and anomaly >= 0.50:
        return False
    return True


_CONCEPT_EN_LABELS: dict[str, str] = {
    "headache": "headache",
    "photophobia": "photophobia (light sensitivity)",
    "visual_disturbance": "visual distortion/disturbance",
    "blurred_vision": "blurred vision",
    "eye_pressure": "ocular pressure",
    "nasal_congestion": "nasal congestion",
    "facial_puffiness": "facial puffiness",
    "fluid_shift": "cephalic fluid shift",
    "papilledema": "papilledema",
    "dizziness": "dizziness",
    "fatigue": "fatigue",
    "dyspnea": "shortness of breath (dyspnea)",
    "confusion": "cognitive confusion",
    "nausea": "nausea",
    "flushed_skin": "facial flushing",
    "cyanosis": "cyanosis",
    "insomnia": "insomnia",
    "malaise": "malaise",
    "rash_infection": "skin rash/lesion",
    "flank_pain": "flank pain",
    "gi_slowdown": "gastrointestinal slowdown",
    "back_pain": "lower back pain",
    "hematuria": "hematuria",
    "dysuria": "dysuria",
    "joint_pain": "joint pain",
    "muscle_pain": "muscle pain",
    "muscle_weakness": "muscle weakness",
    "limb_swelling": "limb swelling",
    "bone_pain": "bone pain",
    "orthostatic_intolerance": "orthostatic intolerance",
    "abdominal_pain": "abdominal pain",
    "paresthesia": "paresthesia (tingling)",
    "chest_pain": "chest pain",
}


def _format_symptoms_en(concepts: Sequence[str]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for c in concepts:
        if c == "blurred_vision" and "visual_disturbance" in concepts:
            continue
        lbl = _CONCEPT_EN_LABELS.get(c, c.replace("_", " "))
        if lbl not in seen:
            seen.add(lbl)
            labels.append(lbl)
    if not labels:
        return "reported clinical changes"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


_format_symptoms_pt = _format_symptoms_en


def _format_telemetry_summary(metrics: dict[str, Any], profile: Optional[CrewProfile]) -> str:
    parts: list[str] = []
    if isinstance(metrics.get("co2_ppm"), (int, float)):
        parts.append(f"CO2 SCD40={metrics['co2_ppm']:.0f} ppm")
    if isinstance(metrics.get("spo2_pct"), (int, float)):
        parts.append(f"SpO2 MAX30102={metrics['spo2_pct']:.1f}%")
    if isinstance(metrics.get("heart_rate_bpm"), (int, float)):
        parts.append(f"HR={metrics['heart_rate_bpm']:.0f} bpm")
    if isinstance(metrics.get("temp_c"), (int, float)):
        parts.append(f"Temp={metrics['temp_c']:.1f}°C")
    if metrics.get("posture"):
        parts.append(f"posture={metrics['posture']}")
    day = metrics.get("mission_day") or (profile.mission_day if profile else None)
    if isinstance(day, (int, float)) and day > 0:
        parts.append(f"mission day {int(day)}")
    return ", ".join(parts) if parts else "peripheral readings under monitoring"


def _build_greeting_text(
    *,
    crew_profile: Optional[CrewProfile],
    metrics: dict[str, Any],
    breaches: Sequence[str],
    sensors_nominal: bool,
) -> str:
    crew_label = crew_profile.name if (crew_profile and crew_profile.name) else "crew member"
    if sensors_nominal:
        return (
            f"Hello, {crew_label}! Everything looks steady here — your vital signs and cabin "
            "environment are nominal. How are you feeling today?"
        )

    co2 = metrics.get("co2_ppm")
    spo2 = metrics.get("spo2_pct")
    if isinstance(co2, (int, float)) and co2 >= 1500.0:
        alert_note = (
            f"I noticed cabin CO2 is elevated ({co2:.0f} ppm) — "
            "are you feeling any discomfort, fatigue, or headache?"
        )
    elif isinstance(spo2, (int, float)) and spo2 <= 94.0:
        alert_note = (
            f"I noticed your SpO2 saturation is low ({spo2:.1f}%) — "
            "are you feeling short of breath or dizzy?"
        )
    elif breaches:
        alert_note = (
            f"I noticed an active sensor alert ({breaches[0]}) — "
            "are you feeling any discomfort right now?"
        )
    else:
        alert_note = (
            "I noticed a slight shift in your current physiological readings — "
            "are you feeling any discomfort right now?"
        )
    return f"Hello, {crew_label}! Good to hear from you. {alert_note}"


def _build_health_checkup_text(
    *,
    crew_profile: Optional[CrewProfile],
    metrics: dict[str, Any],
    top: Any,
    countermeasures: Sequence[str],
    breaches: Sequence[str],
    sensors_nominal: bool,
) -> str:
    crew_label = crew_profile.name if (crew_profile and crew_profile.name) else "crew member"

    vital_parts: list[str] = []
    if isinstance(metrics.get("heart_rate_bpm"), (int, float)):
        vital_parts.append(f"HR {metrics['heart_rate_bpm']:.0f} bpm")
    if isinstance(metrics.get("spo2_pct"), (int, float)):
        vital_parts.append(f"SpO2 {metrics['spo2_pct']:.1f}%")
    if isinstance(metrics.get("respiration_hz"), (int, float)):
        vital_parts.append(f"respiration {metrics['respiration_hz'] * 60.0:.0f} bpm")
    if metrics.get("posture"):
        vital_parts.append(f"posture {metrics['posture']}")
    vitals_str = ", ".join(vital_parts) if vital_parts else "vital signs under monitoring"

    cabin_parts: list[str] = []
    if isinstance(metrics.get("co2_ppm"), (int, float)):
        cabin_parts.append(f"CO2 at {metrics['co2_ppm']:.0f} ppm")
    if isinstance(metrics.get("temp_c"), (int, float)):
        cabin_parts.append(f"temperature {metrics['temp_c']:.1f}°C")
    cabin_str = ", ".join(cabin_parts) if cabin_parts else "cabin parameters under monitoring"

    if sensors_nominal:
        return (
            f"Here is your daily health briefing, {crew_label}: "
            f"your vital signs are within expected limits ({vitals_str}) and the cabin environment "
            f"remains nominal ({cabin_str}). How are you feeling?"
        )

    cm_raw = countermeasures[0] if countermeasures else "Check ventilation and maintain continuous monitoring."
    cm_clean = re.sub(r"^\d+\.\s*", "", cm_raw).strip()
    co2 = metrics.get("co2_ppm")
    spo2 = metrics.get("spo2_pct")

    if isinstance(co2, (int, float)) and co2 >= 1500.0 and top is not None:
        cause_note = (
            f"In the cabin ({cabin_str}), elevated CO2 points to {top.condition.name} "
            f"({top.posterior:.0%}) as the probable cause."
        )
    elif isinstance(spo2, (int, float)) and spo2 <= 94.0 and top is not None:
        cause_note = (
            f"There is reduced oxygenation ({cabin_str}), compatible with {top.condition.name} "
            f"({top.posterior:.0%})."
        )
    elif top is not None:
        alert_lbl = "; ".join(breaches[:2]) if breaches else cabin_str
        cause_note = (
            f"There is an active parameter alert ({alert_lbl}), suggesting attention to "
            f"{top.condition.name} ({top.posterior:.0%})."
        )
    else:
        cause_note = f"In the cabin environment ({cabin_str}), readings are outside the nominal range."

    return (
        f"Here is your clinical vital signs briefing today, {crew_label}: {vitals_str}. "
        f"{cause_note} Recommended immediate action: {cm_clean} "
        "Are you experiencing any discomfort, headache, or shortness of breath?"
    )


def _build_clinical_summary_text(
    *,
    crew_profile: Optional[CrewProfile],
    concepts: Sequence[str],
    metrics: dict[str, Any],
    top: Any,
    second: Any,
    countermeasures: Sequence[str],
    disambig_prompt: Optional[str],
    actions: Sequence[str],
    breaches: Sequence[str],
    is_followup: bool = False,
) -> str:
    crew_label = crew_profile.name if (crew_profile and crew_profile.name) else "crew member"
    telemetry_str = _format_telemetry_summary(metrics, crew_profile)

    if concepts:
        s1 = f"{crew_label}, I logged your report of {_format_symptoms_en(concepts)}."
    elif is_followup:
        s1 = f"{crew_label}, I updated the clinical workup with your follow-up response."
    else:
        s1 = f"{crew_label}, I noted relevant sensor deviations that merit investigation."

    if breaches:
        sensor_note = f"with active alerts ({'; '.join(breaches[:2])})"
    elif isinstance(metrics.get("co2_ppm"), (int, float)) and metrics["co2_ppm"] < 1500.0:
        sensor_note = "with cabin CO2 in nominal range, lowering the likelihood of primary hypercapnia"
    else:
        sensor_note = "cross-referenced directly with your clinical presentation"
    s2 = f"Current telemetry ({telemetry_str}) was evaluated {sensor_note}."

    diff_clause = ""
    if second is not None and second.posterior >= 0.08 and second.condition.id != top.condition.id:
        diff_clause = f", keeping {second.condition.name} ({second.posterior:.0%}) as a differential"
    s3 = (
        f"The primary hypothesis per {top.condition.source_id} is "
        f"{top.condition.name} ({top.posterior:.0%}){diff_clause}."
    )

    cm_raw = countermeasures[0] if countermeasures else "Maintain continuous monitoring of vital signs."
    cm_clean = re.sub(r"^\d+\.\s*", "", cm_raw).strip()
    amsler_hint = " (OPEN_AMSLER_GRID action recommended)" if "OPEN_AMSLER_GRID" in actions and "amsler" not in cm_clean.lower() else ""
    s4 = f"Immediate action: {cm_clean}{amsler_hint}"

    sentences = [s1, s2, s3, s4]
    if disambig_prompt:
        sentences.append(disambig_prompt.strip())
    return " ".join(sentences)
