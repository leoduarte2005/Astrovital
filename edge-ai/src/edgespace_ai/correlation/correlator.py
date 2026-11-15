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
    "Apoio à decisão clínica a bordo; não substitui avaliação do Flight Surgeon."
)

_STOP_WORDS_FACT = frozenset({"e", "and", "mas", "but", "porque", "because", "com", "with", "que", "that", "agua", "water", "banho", "cuidado", "care"})


def _slug_fact_key(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", _normalize_text(text)).strip("_")
    return cleaned[:48] or "unspecified"


def _trim_entity(raw: str) -> str:
    head = re.split(r"[,.;!?\n]|(?:\s+(?:e|and|mas|but|porque|because|com|with)\s+)", raw.strip(), maxsplit=1)[0]
    words = [w for w in head.strip().split() if w]
    return " ".join(words[:4]).strip()


def extract_permanent_facts(text: str) -> list[dict[str, Any]]:
    """Deterministically extract PT/EN permanent clinical facts for crew_clinical_memory."""
    norm = _normalize_text(text)
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

    # ALLERGY (PT/EN)
    for pat in (
        r"\b(?:sou|tenho|estou)\s+alergic[oa]\s+a(?:o|s)?\s+([a-z0-9\- ]{2,45})",
        r"\balergia\s+a(?:o|s)?\s+([a-z0-9\- ]{2,45})",
        r"\b(?:i\s+am|i'm|im)\s+allergic\s+to\s+([a-z0-9\- ]{2,45})",
        r"\ballerg(?:y|ic)\s+to\s+([a-z0-9\- ]{2,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            if ent and _slug_fact_key(ent) not in _STOP_WORDS_FACT:
                _add("ALLERGY", _slug_fact_key(ent), ent, 0.95)

    # MEDICATION (PT/EN)
    for pat in (
        r"\b(?:tomo|estou\s+tomando|uso\s+continuo\s+de|faco\s+uso\s+de|uso)\s+([a-z0-9\- ]{2,45})",
        r"\b(?:i\s+take|i\s+am\s+taking|i'm\s+taking|currently\s+taking|on\s+medication)\s+([a-z0-9\- ]{2,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug not in _STOP_WORDS_FACT and not slug.startswith(("agua", "banho", "cuidado", "care", "a_look", "a_breath")):
                _add("MEDICATION", slug, ent, 0.90)

    # CONDITION_HISTORY (PT/EN)
    if any(p in norm for p in ("enjoo espacial", "space motion sickness", "motion sickness")):
        if any(c in norm for c in ("ja tive", "historico", "history", "previously", "had ")):
            _add("CONDITION_HISTORY", "space_motion_sickness", "1", 0.85)
    for pat in (
        r"\b(?:ja\s+tive|tenho\s+historico\s+de|historico\s+previo\s+de|i\s+have\s+a\s+history\s+of|history\s+of|previously\s+had)\s+([a-z0-9\- ]{3,45})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug not in _STOP_WORDS_FACT and "motion_sickness" not in slug and "enjoo_espacial" not in slug:
                _add("CONDITION_HISTORY", slug, "1", 0.85)

    # SENSITIVITY (PT/EN)
    if re.search(r"\bco2\b.*(?:dor\s+de\s+cabeca|headache|sensivel|sensibilidade|sensitive|mal)", norm) or any(
        p in norm for p in ("sensivel a co2", "sensibilidade a co2", "sensitive to co2", "co2 sensitivity")
    ):
        _add("SENSITIVITY", "co2_sensitivity", "1", 0.85)
    for pat in (
        r"\b(?:sensivel\s+a|sensibilidade\s+a|sensitive\s+to)\s+([a-z0-9\- ]{2,35})",
    ):
        for m in re.finditer(pat, norm):
            ent = _trim_entity(m.group(1))
            slug = _slug_fact_key(ent)
            if ent and slug != "co2":
                _add("SENSITIVITY", f"{slug}_sensitivity", "1", 0.85)

    # SLEEP_NOTE (PT/EN)
    if any(p in norm for p in ("dormi mal", "nao dormi", "pouco sono", "insonia", "acordei varias vezes", "slept poorly", "bad sleep", "poor sleep", "insomnia", "didn't sleep", "didnt sleep")):
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
        memory_updates = extract_permanent_facts(req.text)
        if self.db_path is not None and req.crew_id:
            with ClinicalRepository(self.db_path) as repo:
                crew=repo.crew(req.crew_id)
                memory=repo.memory(req.crew_id)
            profile_kwargs = {k: crew[k] for k in CrewProfile.model_fields if k in crew}
            req=req.model_copy(update={"profile":CrewProfile(**profile_kwargs)})

        answered_questions: dict[str, str] = {
            str(m["fact_key"]): str(m["fact_value"])
            for m in memory
            if m.get("fact_type") == "ANSWERED_TOPIC" and m.get("fact_key") and m.get("fact_value") in ("yes", "no")
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
        extracted = self.symptom_extractor.extract(
            req.text,
            recent_history=req.recent_history,
            summary_24h=req.summary_24h,
        )

        assessment = self.causal_graph.evaluate(
            symptoms=extracted,
            peripherals=peripherals,
            inference=inference,
            thresholds=thresholds,
            profile=req.profile,
            baseline=baseline,
            answered_questions=answered_questions or None,
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
        if not extracted.concepts and sensors_nominal:
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
                evidence_nominal.append(f"Base clínica ({doc.source}): {doc.doc_id} - {doc.title}")

            if self.db_path is not None and req.crew_id:
                with ClinicalRepository(self.db_path) as repo:
                    objective = repo.assess_fixture(req.crew_id, assessment.metrics, allow_engineering=True)

            crew_label = req.profile.name if (req.profile and req.profile.name) else "tripulante"
            telemetry_str = _format_telemetry_summary(assessment.metrics, req.profile)

            if extracted.is_greeting and not extracted.fallback_docs:
                greeting_text = (
                    f"Olá, {crew_label}. Telemetria atual nominal ({telemetry_str}). "
                    "Como está se sentindo e como posso ajudar hoje?"
                )
                return ChatCorrelateRespPayload(
                    matched_condition_ids=[m["condition_id"] for m in objective["matches"]] if objective else None,
                    max_severity=objective["max_severity"] if objective else None,
                    blocked_actions=objective["blocked_actions"] if objective else None,
                    memory_updates=memory_updates or None,
                    text=greeting_text,
                    differentials=None,
                    evidence=evidence_nominal or None,
                    countermeasures=[
                        "Manter monitoramento contínuo de sinais vitais e ambiente da cabine.",
                    ],
                    source_ids=["EDGESPACE-AI-V1"],
                    escalation=Escalation.LOCAL,
                    disclaimer=CLINICAL_DISCLAIMER,
                    disambiguation_question=None,
                    actions=None,
                )

            clarification_prompt = (
                "Não identifiquei sintomas específicos no seu relato e os sensores estão nominais. "
                "Pode detalhar o que está sentindo (localização da dor, duração, náusea, tontura, "
                "alteração visual ou falta de ar)?"
            )
            fts_note = ""
            if extracted.fallback_docs:
                titles = "; ".join(d.title for d in extracted.fallback_docs[:2])
                fts_note = f" Referências NASA próximas recuperadas via FTS5: {titles}."
            source_ids_nom = [d.source_id or d.doc_id for d in store_docs[:2] if (d.source_id or d.doc_id)] or ["EDGESPACE-AI-V1"]
            return ChatCorrelateRespPayload(
                matched_condition_ids=[m["condition_id"] for m in objective["matches"]] if objective else None,
                max_severity=objective["max_severity"] if objective else None,
                blocked_actions=objective["blocked_actions"] if objective else None,
                memory_updates=memory_updates or None,
                text=(
                    f"Entendido, {crew_label} — nenhum sintoma específico foi reconhecido na mensagem, "
                    f"e a telemetria atual ({telemetry_str}) está nominal.{fts_note} "
                    "Por favor, detalhe os sintomas (localização, intensidade e duração) para correlação clínica."
                ),
                differentials=None,
                evidence=evidence_nominal or None,
                countermeasures=[
                    "Descrever localização, intensidade e duração dos sintomas para nova avaliação.",
                    "Manter monitoramento contínuo de sinais vitais e ambiente da cabine.",
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
            evidence.append(f"Sintomas detectados: {', '.join(extracted.concepts)}")
        for reading in peripherals:
            evidence.append(f"Sensor {reading.type.value}: {reading.value:.2f} {reading.unit}")
        if inference is not None:
            evidence.append(
                f"CSI vitals: posture={inference.posture}, HR={inference.heart_rate_bpm:.1f} bpm, "
                f"RR={inference.respiration_hz * 60.0:.1f} bpm, anomaly={inference.anomaly_score:.2f}, "
                f"conf={inference.confidence:.2f}"
            )
        for breach in assessment.threshold_breaches:
            evidence.append(f"Limite ultrapassado: {breach}")
        if top and top.matched_sensor_evidence:
            evidence.extend(top.matched_sensor_evidence)
        for doc in store_docs[:2]:
            evidence.append(f"Base clínica ({doc.source}): {doc.doc_id} - {doc.title}")

        # Differentials list
        differentials: list[str] = []
        for h in top_hypotheses[:3]:
            if h.posterior >= 0.08 or len(differentials) == 0:
                differentials.append(f"{h.condition.name} (P={h.posterior:.2f})")

        # Disambiguation question via information gain
        disambig = self.disambiguator.select_question(
            top_hypotheses,
            answered_topics=set(extracted.answered_topics)|{m["fact_key"] for m in memory+memory_updates if m.get("fact_type")=="ANSWERED_TOPIC"},
            observed_concepts=extracted.concepts,
        )

        # Escalation policy
        escalation = Escalation.LOCAL
        if assessment.red_breach:
            escalation = Escalation.STORE_AND_FORWARD
        elif top and top.posterior >= 0.55 and top.condition.default_escalation == Escalation.STORE_AND_FORWARD:
            escalation = Escalation.STORE_AND_FORWARD
        elif assessment.yellow_breach or (top and top.posterior >= 0.45 and top.condition.default_escalation == Escalation.CREW):
            escalation = Escalation.CREW

        # Countermeasures, source IDs, and actions
        countermeasures = list(top.condition.countermeasures) if top else [
            "Manter monitoramento contínuo de sinais vitais e ambiente da cabine."
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
                        evidence.append('Ação bloqueada: ' + b_act + ' — ' + row['rationale'])
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
                    evidence.append(f"Ação bloqueada ({m.get('fact_type')}): {act} — conflito com {m.get('fact_value')}")
            if m.get("fact_type") == "ALLERGY":
                filtered_cm = []
                for cm in countermeasures:
                    if stem in _normalize_text(cm):
                        evidence.append(f"Contramedida omitida por alergia ({m.get('fact_value')}): {cm}")
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

        if top is not None:
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
            )
        else:
            crew_label = req.profile.name if (req.profile and req.profile.name) else "tripulante"
            telemetry_str = _format_telemetry_summary(assessment.metrics, req.profile)
            summary_text = (
                f"Entendido, {crew_label} — avaliação inicial para '{req.text.strip()}' "
                f"cruzada com a telemetria atual ({telemetry_str})."
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


_CONCEPT_PT_LABELS: dict[str, str] = {
    "headache": "cefaleia (dor de cabeça)",
    "photophobia": "fotofobia (sensibilidade à luz)",
    "visual_disturbance": "distorção/alteração visual",
    "blurred_vision": "visão turva/embaçada",
    "eye_pressure": "pressão ocular",
    "nasal_congestion": "congestão nasal",
    "facial_puffiness": "edema facial",
    "fluid_shift": "redistribuição cefálica de fluidos",
    "papilledema": "papiledema",
    "dizziness": "tontura",
    "fatigue": "fadiga",
    "dyspnea": "dispneia (falta de ar)",
    "confusion": "confusão cognitiva",
    "nausea": "náusea",
    "flushed_skin": "rubor facial",
    "cyanosis": "cianose",
    "insomnia": "insônia",
    "malaise": "mal-estar",
    "rash_infection": "lesão/erupção cutânea",
    "flank_pain": "dor em flanco",
    "gi_slowdown": "lentidão gastrointestinal",
    "back_pain": "dor lombar",
    "hematuria": "hematúria",
    "dysuria": "disúria",
    "joint_pain": "dor articular",
    "muscle_pain": "dor muscular",
    "muscle_weakness": "fraqueza muscular",
    "limb_swelling": "edema em membro",
    "bone_pain": "dor óssea",
    "orthostatic_intolerance": "intolerância ortostática",
    "abdominal_pain": "dor abdominal",
    "paresthesia": "parestesia (formigamento)",
    "chest_pain": "dor torácica",
}


def _format_symptoms_pt(concepts: Sequence[str]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for c in concepts:
        if c == "blurred_vision" and "visual_disturbance" in concepts:
            continue
        lbl = _CONCEPT_PT_LABELS.get(c, c.replace("_", " "))
        if lbl not in seen:
            seen.add(lbl)
            labels.append(lbl)
    if not labels:
        return "alterações clínicas relatadas"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" e {labels[-1]}"


def _format_telemetry_summary(metrics: dict[str, Any], profile: Optional[CrewProfile]) -> str:
    parts: list[str] = []
    if isinstance(metrics.get("co2_ppm"), (int, float)):
        parts.append(f"CO2 SCD40={metrics['co2_ppm']:.0f} ppm")
    if isinstance(metrics.get("spo2_pct"), (int, float)):
        parts.append(f"SpO2 MAX30102={metrics['spo2_pct']:.1f}%")
    if isinstance(metrics.get("heart_rate_bpm"), (int, float)):
        parts.append(f"FC={metrics['heart_rate_bpm']:.0f} bpm")
    if isinstance(metrics.get("temp_c"), (int, float)):
        parts.append(f"Temp={metrics['temp_c']:.1f}°C")
    if metrics.get("posture"):
        parts.append(f"postura={metrics['posture']}")
    day = metrics.get("mission_day") or (profile.mission_day if profile else None)
    if isinstance(day, (int, float)) and day > 0:
        parts.append(f"dia {int(day)} de missão")
    return ", ".join(parts) if parts else "leituras periféricas em monitoramento"


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
) -> str:
    crew_label = crew_profile.name if (crew_profile and crew_profile.name) else "tripulante"
    telemetry_str = _format_telemetry_summary(metrics, crew_profile)

    if concepts:
        s1 = f"Entendido, {crew_label} — registrei {_format_symptoms_pt(concepts)}."
    else:
        s1 = f"Entendido, {crew_label} — identifiquei desvios relevantes na telemetria atual."

    if breaches:
        sensor_note = f"com alertas ativos ({'; '.join(breaches[:2])})"
    elif isinstance(metrics.get("co2_ppm"), (int, float)) and metrics["co2_ppm"] < 1500.0:
        sensor_note = "com CO2 em faixa nominal, reduzindo a chance de hipercapnia primária"
    else:
        sensor_note = "cruzados diretamente com sua queixa clínica"
    s2 = f"Na telemetria deste instante ({telemetry_str}), os dados foram avaliados {sensor_note}."

    diff_clause = ""
    if second is not None and second.posterior >= 0.08 and second.condition.id != top.condition.id:
        diff_clause = f", mantendo {second.condition.name} ({second.posterior:.0%}) como diferencial"
    s3 = (
        f"A hipótese principal pela base {top.condition.source_id} é "
        f"{top.condition.name} ({top.posterior:.0%}){diff_clause}."
    )

    cm_raw = countermeasures[0] if countermeasures else "Manter monitoramento contínuo de sinais vitais."
    cm_clean = re.sub(r"^\d+\.\s*", "", cm_raw).strip()
    amsler_hint = " (ação OPEN_AMSLER_GRID recomendada)" if "OPEN_AMSLER_GRID" in actions and "amsler" not in cm_clean.lower() else ""
    s4 = f"Conduta imediata: {cm_clean}{amsler_hint}"

    sentences = [s1, s2, s3, s4]
    if disambig_prompt:
        sentences.append(disambig_prompt.strip())
    return " ".join(sentences)
