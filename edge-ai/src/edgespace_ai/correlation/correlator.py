"""Clinical causal correlator assembling CHAT_CORRELATE_RESP payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from ..adaptation.baseline_registry import CrewBaseline
from ..ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    ChatCorrelateRespPayload,
    Escalation,
    PeripheralReading,
    Threshold,
)
from .causal_graph import CausalGraph
from .clinical_store import ClinicalStore
from .disambiguator import Disambiguator
from .symptom_extractor import SymptomExtractor

CLINICAL_DISCLAIMER = (
    "Apoio à decisão clínica a bordo; não substitui avaliação do Flight Surgeon."
)


class ClinicalCorrelator:
    """Cross-correlates chat symptoms, sensor snapshots, history, and crew baseline."""

    def __init__(
        self,
        *,
        db_path: Path | str = Path("../data/edgespace.db"),
        knowledge_base_path: Optional[Path | str] = None,
    ) -> None:
        default_kb = Path(__file__).resolve().parents[3] / "knowledge-base" / "nasa_causal_graph.yaml"
        kb_path = Path(knowledge_base_path) if knowledge_base_path else default_kb

        self.symptom_extractor = SymptomExtractor()
        self.clinical_store = ClinicalStore(db_path=db_path, knowledge_base_path=kb_path)
        self.causal_graph = CausalGraph(knowledge_base_path=kb_path)
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
            answered_topics=extracted.answered_topics,
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

        source_ids: list[str] = []
        for h in top_hypotheses[:2]:
            if h.posterior >= 0.15 and h.condition.source_id not in source_ids:
                source_ids.append(h.condition.source_id)
        for doc in store_docs:
            if doc.doc_id not in source_ids:
                source_ids.append(doc.doc_id)
        if not source_ids:
            source_ids.append("EDGESPACE-AI-V1")

        if top is not None:
            summary_text = (
                f"Hipótese principal: {top.condition.name} (probabilidade posterior {top.posterior:.0%}). "
                f"Foram avaliados {len(extracted.concepts)} sintomas e {len(peripherals)} leituras periféricas."
            )
        else:
            summary_text = (
                f"Avaliação inicial para '{req.text.strip()}': {len(peripherals)} leituras periféricas analisadas."
            )

        return ChatCorrelateRespPayload(
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
