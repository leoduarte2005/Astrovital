"""Clinical causal correlator assembling CHAT_CORRELATE_RESP payloads."""

from __future__ import annotations

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
from .symptom_extractor import SymptomExtractor, _normalize_text
from ..clinical import ClinicalRepository

CLINICAL_DISCLAIMER = (
    "Apoio à decisão clínica a bordo; não substitui avaliação do Flight Surgeon."
)


class ClinicalCorrelator:
    """Cross-correlates chat symptoms, sensor snapshots, history, and crew baseline."""

    def __init__(
        self,
        *,
        db_path: Optional[Path | str] = None,
        knowledge_base_path: Optional[Path | str] = None,
    ) -> None:
        default_kb = Path(__file__).resolve().parents[3] / "knowledge-base" / "nasa_causal_graph.yaml"
        kb_path = Path(knowledge_base_path) if knowledge_base_path else default_kb

        self.symptom_extractor = SymptomExtractor()
        self.clinical_store = ClinicalStore(db_path=db_path, knowledge_base_path=kb_path)
        self.db_path=Path(db_path) if db_path is not None else None
        self.causal_graph = CausalGraph(knowledge_base_path=kb_path,db_path=db_path)
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
        memory_updates=[]
        if self.db_path is not None and req.crew_id:
            with ClinicalRepository(self.db_path) as repo:
                crew=repo.crew(req.crew_id)
                memory=repo.memory(req.crew_id)
            req=req.model_copy(update={"profile":CrewProfile(crew_id=crew["crew_id"],name=crew["name"],role=crew["role"],mission_day=crew["mission_day"],age=crew["age"])})
            last=next((m["fact_value"] for m in memory if m["fact_key"]=="last_question_id" and m["fact_type"]=="PREFERENCE"),None)
            answer=_normalize_text(req.text).strip(".! ")
            if last and answer in ("sim","yes","nao","no"):
                memory_updates.append(dict(fact_type="ANSWERED_TOPIC",fact_key=last,fact_value="yes" if answer in ("sim","yes") else "no",confidence=1.0,source_role="user"))
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
        )

        store_docs = self.clinical_store.search(
            req.text,
            concepts=extracted.concepts,
            limit=3,
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

            clarification_prompt = (
                "Não identifiquei sintomas específicos no seu relato e os sensores estão nominais. "
                "Pode detalhar o que está sentindo (localização da dor, duração, náusea, tontura, "
                "alteração visual ou falta de ar)?"
            )
            return ChatCorrelateRespPayload(
                text=(
                    "Nenhum sintoma específico foi reconhecido na mensagem e a telemetria atual está nominal. "
                    "Por favor, detalhe os sintomas (localização, intensidade e duração) para correlação clínica."
                ),
                differentials=None,
                evidence=evidence_nominal or None,
                countermeasures=[
                    "Descrever localização, intensidade e duração dos sintomas para nova avaliação.",
                    "Manter monitoramento contínuo de sinais vitais e ambiente da cabine.",
                ],
                source_ids=["EDGESPACE-AI-V1"],
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

        if self.db_path is not None:
            with ClinicalRepository(self.db_path) as repo:
                if req.crew_id:objective=repo.assess_fixture(req.crew_id,assessment.metrics,allow_engineering=True)
                for row in repo.connection.execute('SELECT * FROM causal_contraindications'):
                    if repo.compare(assessment.metrics.get(row['guard_metric']),row['guard_op'],row['guard_value']):
                        actions=[a for a in actions if a!=row['blocked_action']]
                        evidence.append('Ação bloqueada: '+row['blocked_action']+' — '+row['rationale'])
            if disambig:
                memory_updates.append(dict(fact_type='PREFERENCE',fact_key='last_question_id',fact_value=disambig.question.id,confidence=1.0,source_role='assistant'))
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
            summary_text = (
                f"Hipótese principal: {top.condition.name} (prioridade heurística {top.posterior:.0%}). "
                f"Foram avaliados {len(extracted.concepts)} sintomas e {len(peripherals)} leituras periféricas."
            )
        else:
            summary_text = (
                f"Avaliação inicial para '{req.text.strip()}': {len(peripherals)} leituras periféricas analisadas."
            )

        return ChatCorrelateRespPayload(
            matched_condition_ids=[m["condition_id"] for m in objective["matches"]] if objective else None,
            max_severity=objective["max_severity"] if objective else None,
            blocked_actions=objective["blocked_actions"] if objective else None,
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
