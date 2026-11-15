"""Bayesian causal graph over NASA HRP spaceflight medical conditions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ..adaptation.baseline_registry import CrewBaseline
from ..ipc.protocol import (
    AIInferencePayload,
    CrewProfile,
    Escalation,
    Peripheral,
    PeripheralReading,
    Threshold,
)
from .clinical_store import load_yaml_file
from ..clinical import ClinicalRepository
from .symptom_extractor import SymptomExtractor
from .symptom_extractor import ExtractedSymptoms


# Tunable engineering constants (calibrated offline by training/auto_calibrate_engine.py).
SYMPTOM_GAIN = 4.5
UNMATCHED_SYMPTOM_PENALTY = 0.65
NEGATIVE_EVIDENCE_FLOOR = 0.85
OVERLAP_YES_LIKELIHOOD = 0.50
PRIOR_MULTIPLIER_MIN = 0.5
PRIOR_MULTIPLIER_MAX = 2.0
# Live sensors whose *normal* reading is mild evidence against a threshold-driven condition.
NEGATIVE_EVIDENCE_METRICS = frozenset({"co2_ppm", "spo2_pct"})


def question_p_yes(question: "DisambiguationQuestion", condition: "CausalCondition") -> float:
    """P(answer=yes | condition) shared by Bayesian update and information-gain selection."""
    if condition.id == question.owner_condition_id:
        p_yes = question.yes_likelihood
    elif any(c in condition.symptoms for c in question.positive_concepts):
        p_yes = OVERLAP_YES_LIKELIHOOD
    else:
        p_yes = question.no_likelihood
    return min(max(p_yes, 1e-4), 1.0 - 1e-4)


@dataclass(frozen=True)
class SensorRule:
    metric: str
    op: str
    value: Optional[float] = None
    values: tuple[str, ...] = ()
    likelihood_ratio: float = 1.5
    description: str = ""
    baseline_field: str = ""
    rule_scope: str = "INSTANT"

    def matches(self, metrics: dict[str, Any], *, longitudinal: Optional[dict[str, Any]] = None) -> bool:
        if self.rule_scope.startswith("ROLLUP_") and longitudinal is not None and self.metric in longitudinal and longitudinal[self.metric] is not None:
            observed = longitudinal[self.metric]
        elif self.metric in metrics:
            observed = metrics[self.metric]
        else:
            return False
        if self.baseline_field:
            base=metrics.get(self.baseline_field)
            if observed is None or base is None: return False
            observed=float(observed)-float(base)
        if self.op == "in":
            return str(observed).lower() in {v.lower() for v in self.values}
        if self.value is None:
            return False
        try:
            num = float(observed)
        except (TypeError, ValueError):
            return False
        if self.op == "gte":
            return num >= self.value
        if self.op == "lte":
            return num <= self.value
        if self.op == "gt":
            return num > self.value
        if self.op == "lt":
            return num < self.value
        if self.op == "eq":
            return abs(num - self.value) < 1e-6
        return False


@dataclass(frozen=True)
class DisambiguationQuestion:
    id: str
    prompt: str
    positive_concepts: tuple[str, ...]
    yes_likelihood: float = 0.85
    no_likelihood: float = 0.15
    owner_condition_id: str = ""
    target_differential_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CausalCondition:
    id: str
    name: str
    source_id: str
    subsystem: str
    prior: float
    default_escalation: Escalation
    symptoms: dict[str, float]
    sensor_rules: tuple[SensorRule, ...]
    countermeasures: tuple[str, ...]
    actions: tuple[str, ...]
    disambiguation_questions: tuple[DisambiguationQuestion, ...]


@dataclass(frozen=True)
class HypothesisPosterior:
    condition: CausalCondition
    posterior: float
    matched_symptoms: tuple[str, ...]
    matched_sensor_evidence: tuple[str, ...]


@dataclass
class CausalAssessment:
    hypotheses: list[HypothesisPosterior]
    metrics: dict[str, Any] = field(default_factory=dict)
    threshold_breaches: list[str] = field(default_factory=list)
    red_breach: bool = False
    yellow_breach: bool = False


class CausalGraph:
    """Loads causal graph from SQLite (or YAML only in explicit test mode) and computes P(H|E)."""

    def __init__(
        self,
        knowledge_base_path: Optional[Path | str] = None,
        *,
        db_path: Optional[Path | str] = None,
        allow_yaml_for_tests: bool = False,
    ) -> None:
        default_kb = Path(__file__).resolve().parents[3] / "knowledge-base" / "nasa_causal_graph.yaml"
        self.knowledge_base_path = Path(knowledge_base_path) if knowledge_base_path else default_kb
        self._objective_rules: dict[str, list[dict[str, Any]]] = {}
        self.db_path = Path(db_path) if db_path is not None else None
        if self.db_path is not None:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"SQLite clinical database not found: {self.db_path}")
            self.conditions: list[CausalCondition] = self._load_sqlite()
        elif allow_yaml_for_tests:
            self.conditions = self._load_conditions(self.knowledge_base_path)
        else:
            raise ValueError("db_path is required in production (pass allow_yaml_for_tests=True only in tests)")

    def _load_sqlite(self) -> list[CausalCondition]:
        with ClinicalRepository(self.db_path) as repo:
            rows=repo.conditions()
        extractor=SymptomExtractor()
        conditions=[]
        for row in rows:
            self._objective_rules[row['condition_id']]=[r for r in row['rules'] if r['source_sensor'] in ('LAB','MISSION_CONTEXT')]
            raw_weights=row.get('symptom_weights') or {}
            concepts=extractor.extract(" ".join(row['symptoms'])).concepts
            symptoms={c: float(raw_weights[c]) if c in raw_weights else 0.5 for c in concepts}
            for k,v in raw_weights.items():
                symptoms.setdefault(str(k), float(v))
            rules=[]
            for r in row['rules']:
                op={'GE':'gte','LE':'lte','DELTA_GT':'gt','DELTA_LT':'lt'}.get(r['op'],r['op'].lower())
                values=r['values'] or {}
                bf=r.get('baseline_field') or values.get('baseline_field') or ''
                rs=r.get('rule_scope') or 'INSTANT'
                rules.append(SensorRule(metric=r['metric'],op=op,value=r['threshold_value'],values=tuple(values.get('values',[])),likelihood_ratio=r['likelihood_ratio'],description=r['description'],baseline_field=bf,rule_scope=rs))
            questions=tuple(
                DisambiguationQuestion(
                    id=q['question_id'],
                    prompt=q['prompt'],
                    positive_concepts=tuple(extractor.extract(" ".join(q['positive_concepts'])).concepts),
                    yes_likelihood=q['yes_likelihood'],
                    no_likelihood=q['no_likelihood'],
                    owner_condition_id=row['condition_id'],
                    target_differential_ids=tuple(str(t) for t in (q.get('target_differential_ids') or ())),
                )
                for q in row['questions']
            )
            conditions.append(CausalCondition(id=row['condition_id'],name=row['name'],source_id=row['source_id'],subsystem=row['subsystem'],prior=row['prior'],default_escalation=Escalation(row['default_escalation']),symptoms=symptoms,sensor_rules=tuple(rules),countermeasures=tuple(row['countermeasures']),actions=tuple(row['actions']),disambiguation_questions=questions))
        if len(conditions)<19: raise ValueError('SQLite clinical graph is incomplete; apply operational migrations')

        # Enrich SQLite conditions with YAML clinical refinements (photophobia, visual_disturbance,
        # Amsler/Thigh Cuffs/Complexo B protocol actions & countermeasures) without breaking SQLite IDs.
        yaml_by_id = {c.id: c for c in self._load_conditions(self.knowledge_base_path)} if self.knowledge_base_path.is_file() else {}
        sqlite_to_yaml = {
            "SANS": "sans_viip",
            "HYPERCAPNIA": "hypercapnia_co2",
            "RADIATION_ACUTE": "radiation_ros",
            "RADIATION_CNS": "cns_radiation_effects",
            "SLEEP_CIRCADIAN": "sleep_immune_deprivation",
        }
        enriched: list[CausalCondition] = []
        for cond in conditions:
            yaml_id = sqlite_to_yaml.get(cond.id)
            ycond = yaml_by_id.get(yaml_id) if yaml_id else None
            if ycond is not None:
                merged_symptoms = dict(cond.symptoms)
                for sk, sw in ycond.symptoms.items():
                    merged_symptoms.setdefault(sk, sw)
                merged_actions = list(cond.actions)
                if cond.id == "SANS":
                    for act in ycond.actions:
                        if act not in merged_actions:
                            merged_actions.insert(0, act) if act == "OPEN_AMSLER_GRID" else merged_actions.append(act)
                merged_cms = cond.countermeasures
                merged_rules = cond.sensor_rules
                if cond.id == "SANS" and ycond.sensor_rules:
                    existing_desc = {r.description for r in cond.sensor_rules}
                    extra_rules = [
                        r for r in ycond.sensor_rules
                        if r.metric == "co2_ppm" and r.description not in existing_desc
                    ]
                    merged_rules = (*cond.sensor_rules, *extra_rules)
                enriched.append(
                    CausalCondition(
                        id=cond.id,
                        name=cond.name,
                        source_id=cond.source_id,
                        subsystem=cond.subsystem,
                        prior=cond.prior,
                        default_escalation=cond.default_escalation,
                        symptoms=merged_symptoms,
                        sensor_rules=merged_rules,
                        countermeasures=merged_cms,
                        actions=tuple(merged_actions),
                        disambiguation_questions=cond.disambiguation_questions,
                    )
                )
            else:
                enriched.append(cond)
        return enriched

    def evaluate(
        self,
        *,
        symptoms: ExtractedSymptoms,
        peripherals: Sequence[PeripheralReading] = (),
        inference: Optional[AIInferencePayload] = None,
        thresholds: Optional[dict[str, Threshold]] = None,
        profile: Optional[CrewProfile] = None,
        baseline: Optional[CrewBaseline] = None,
        answered_questions: Optional[dict[str, str]] = None,
        prior_multipliers: Optional[dict[str, float]] = None,
    ) -> CausalAssessment:
        """Evaluate P(H|E) over all causal conditions given symptoms and telemetry."""
        metrics, breaches, red_breach, yellow_breach = self._extract_metrics(
            symptoms=symptoms,
            peripherals=peripherals,
            inference=inference,
            thresholds=thresholds or {},
            profile=profile,
            baseline=baseline,
        )

        long_row: Optional[dict[str, Any]] = None
        if self.db_path is not None and profile is not None:
            with ClinicalRepository(self.db_path) as repo:
                metrics.update({k:v for k,v in repo.crew(profile.crew_id).items() if k.startswith('preflight_')})
                for key,value in repo.context_metrics(profile.crew_id).items(): metrics.setdefault(key,value)
                long_row = repo.longitudinal(profile.crew_id)
                for key,value in long_row.items():
                    if value is not None:
                        metrics.setdefault(key, value)
        if metrics.get('exercise_recent')==1 and 'chest_pain' not in symptoms.concepts:
            breaches=[b for b in breaches if 'heart_rate_bpm' not in b]
            red_breach=any('(RED)' in b for b in breaches)
            yellow_breach=any('(YELLOW)' in b for b in breaches)
        if symptoms.eva_context:
            metrics['eva_recent']=1
            metrics.setdefault('eva_recent_24h', 1)
            metrics.setdefault('eva_recent_72h', 1)
        if symptoms.radiation_context:
            metrics['radiation_event']=1;metrics['spe_alert']=1
        for concept,metric in [('joint_pain','joint_pain'),('confusion','cognitive_change'),('rash','rash'),('dyspnea','dyspnea')]:
            if concept in symptoms.concepts:metrics[metric]=1
        if not self.conditions:
            return CausalAssessment(hypotheses=[], metrics=metrics)

        questions_by_id: dict[str, DisambiguationQuestion] = {}
        for c in self.conditions:
            for q in c.disambiguation_questions:
                if q.id and q.id not in questions_by_id:
                    questions_by_id[q.id] = q

        log_scores: list[float] = []
        details: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

        evaluated_conditions=[]
        for cond in self.conditions:
            if self.db_path is not None:
                objective=self._objective_rules.get(cond.id,[])
                if objective and not all(
                    ClinicalRepository.compare(
                        metrics.get(r['metric']),
                        r['op'],
                        r['threshold_value'],
                        r['values'],
                        metrics,
                        rule_scope=r.get('rule_scope'),
                        metric=r['metric'],
                        longitudinal=long_row,
                    ) is True
                    for r in objective
                ):
                    continue
            log_p = math.log(max(cond.prior, 1e-4))
            matched_sym: list[str] = []
            matched_sens: list[str] = []

            mult = 1.0
            if prior_multipliers:
                mult = min(max(float(prior_multipliers.get(cond.id, 1.0)), PRIOR_MULTIPLIER_MIN), PRIOR_MULTIPLIER_MAX)
                if abs(mult - 1.0) > 1e-9:
                    log_p += math.log(mult)
                    matched_sens.append(f"Histórico do tripulante: prior x{mult:.2f} para {cond.name}")

            for concept in symptoms.concepts:
                weight = cond.symptoms.get(concept)
                if weight is not None:
                    log_p += math.log(1.0 + SYMPTOM_GAIN * weight)
                    matched_sym.append(concept)
                else:
                    log_p += math.log(UNMATCHED_SYMPTOM_PENALTY)

            for rule in cond.sensor_rules:
                if rule.matches(metrics, longitudinal=long_row):
                    log_p += math.log(max(rule.likelihood_ratio, 1.0))
                    if rule.description:
                        matched_sens.append(rule.description)
                elif (
                    rule.metric in NEGATIVE_EVIDENCE_METRICS
                    and rule.rule_scope == "INSTANT"
                    and rule.op in ("gt", "gte", "lt", "lte")
                    and rule.likelihood_ratio > 1.0
                    and isinstance(metrics.get(rule.metric), (int, float))
                ):
                    # Live sensor present and on the benign side of the threshold: mild evidence against.
                    log_p += math.log(max(1.0 / math.sqrt(rule.likelihood_ratio), NEGATIVE_EVIDENCE_FLOOR))

            # Dynamic threshold boost for CO2 / SpO2 if crew thresholds are explicitly configured
            if cond.id in ("hypercapnia_co2","HYPERCAPNIA") and any("co2_ppm" in b for b in breaches):
                log_p += math.log(2.5)
            if cond.id in ("hypoxia","HYPOXIA") and any("spo2_pct" in b for b in breaches):
                log_p += math.log(2.5)

            # Multi-turn Bayesian update from answered disambiguation questions
            if answered_questions:
                for q_id, ans in answered_questions.items():
                    q_obj = questions_by_id.get(q_id)
                    if q_obj is None:
                        continue
                    p_yes = question_p_yes(q_obj, cond)
                    if ans == "yes":
                        log_p += math.log(p_yes)
                        if cond.id == q_obj.owner_condition_id:
                            matched_sens.append(f"Triagem positiva ({q_id})")
                    elif ans == "no":
                        log_p += math.log(1.0 - p_yes)
                        if cond.id == q_obj.owner_condition_id:
                            matched_sens.append(f"Triagem negativa ({q_id})")

            if self.db_path is not None and not matched_sym and (not cond.sensor_rules or not all(r.matches(metrics, longitudinal=long_row) for r in cond.sensor_rules)):
                continue
            evaluated_conditions.append(cond)
            log_scores.append(log_p)
            details.append((tuple(matched_sym), tuple(matched_sens)))

        if not log_scores:
            return CausalAssessment(hypotheses=[],metrics=metrics,threshold_breaches=breaches,red_breach=red_breach,yellow_breach=yellow_breach)
        max_log = max(log_scores)
        exp_scores = [math.exp(ls - max_log) for ls in log_scores]
        total = sum(exp_scores) or 1.0
        probs = [val / total for val in exp_scores]

        ranked = [
            HypothesisPosterior(
                condition=cond,
                posterior=prob,
                matched_symptoms=sym,
                matched_sensor_evidence=sens,
            )
            for cond, prob, (sym, sens) in zip(evaluated_conditions, probs, details)
        ]
        ranked.sort(key=lambda h: h.posterior, reverse=True)

        return CausalAssessment(
            hypotheses=ranked,
            metrics=metrics,
            threshold_breaches=breaches,
            red_breach=red_breach,
            yellow_breach=yellow_breach,
        )

    @staticmethod
    def _extract_metrics(
        *,
        symptoms: ExtractedSymptoms,
        peripherals: Sequence[PeripheralReading],
        inference: Optional[AIInferencePayload],
        thresholds: dict[str, Threshold],
        profile: Optional[CrewProfile],
        baseline: Optional[CrewBaseline],
    ) -> tuple[dict[str, Any], list[str], bool, bool]:
        metrics: dict[str, Any] = {
            "eva_context": 1.0 if symptoms.eva_context else 0.0,
            "radiation_context": 1.0 if symptoms.radiation_context else 0.0,
        }
        breaches: list[str] = []
        red_breach = False
        yellow_breach = False

        for r in peripherals:
            if not math.isfinite(r.value):
                continue
            unit_low = r.unit.strip().lower()
            if r.type == Peripheral.SCD40:
                if r.value <= 0.0:
                    continue
                metrics["co2_ppm"] = float(r.value)
                metric_key = "co2_ppm"
            elif r.type == Peripheral.MAX30102:
                if r.value <= 0.0:
                    continue
                if "bpm" in unit_low:
                    metrics["heart_rate_bpm"] = float(r.value)
                    metric_key = "heart_rate_bpm"
                else:
                    metrics["spo2_pct"] = float(r.value)
                    metric_key = "spo2_pct"
            elif r.type == Peripheral.BME280:
                if "hpa" in unit_low or "pa" in unit_low:
                    if r.value <= 0.0:
                        continue
                    metrics["pressure_hpa"] = float(r.value)
                    metric_key = "pressure_hpa"
                elif "%" in unit_low:
                    if r.value <= 0.0:
                        continue
                    metrics["humidity_pct"] = float(r.value)
                    metric_key = "humidity_pct"
                else:
                    metrics["temp_c"] = float(r.value)
                    metric_key = "temp_c"
            else:
                metric_key = ""

            if metric_key and metric_key in thresholds:
                th = thresholds[metric_key]
                has_low = th.red_low is not None or th.yellow_low is not None
                # Go serializes non-pointer zero floats for unset upper limits on lower-only thresholds (e.g. spo2_pct).
                has_high = (th.red_high > 0.0 or th.yellow_high > 0.0) or not has_low
                if (has_high and th.red_high > 0.0 and r.value >= th.red_high) or (
                    th.red_low is not None and r.value <= th.red_low
                ):
                    red_breach = True
                    breaches.append(f"{metric_key}={r.value:.1f} (RED)")
                elif (has_high and th.yellow_high > 0.0 and r.value >= th.yellow_high) or (
                    th.yellow_low is not None and r.value <= th.yellow_low
                ):
                    yellow_breach = True
                    breaches.append(f"{metric_key}={r.value:.1f} (YELLOW)")

        if inference is not None:
            metrics["posture"] = inference.posture
            metrics["respiration_hz"] = float(inference.respiration_hz)
            metrics.setdefault("heart_rate_bpm", float(inference.heart_rate_bpm))
            metrics["hrv_ms"] = float(inference.hrv_ms)
            metrics["anomaly_score"] = float(inference.anomaly_score)
            if baseline is not None and inference.anomaly_score >= baseline.threshold:
                yellow_breach = True
                breaches.append(
                    f"anomaly_score={inference.anomaly_score:.2f} >= baseline_threshold={baseline.threshold:.2f}"
                )

        if profile is not None and profile.mission_day is not None:
            metrics["mission_day"] = float(profile.mission_day)

        return metrics, breaches, red_breach, yellow_breach

    @staticmethod
    def _load_conditions(path: Path) -> list[CausalCondition]:
        if not path.is_file():
            return []
        data = load_yaml_file(path)
        raw_conditions = data.get("conditions", [])
        if not isinstance(raw_conditions, list):
            return []

        conditions: list[CausalCondition] = []
        for item in raw_conditions:
            if not isinstance(item, dict):
                continue
            cond_id = str(item.get("id", ""))
            rules: list[SensorRule] = []
            for r in item.get("sensor_rules") or []:
                if not isinstance(r, dict):
                    continue
                vals = tuple(str(v) for v in (r.get("values") or []))
                raw_val = r.get("value")
                rules.append(
                    SensorRule(
                        metric=str(r.get("metric", "")),
                        op=str(r.get("op", "gte")),
                        value=float(raw_val) if raw_val is not None else None,
                        values=vals,
                        likelihood_ratio=float(r.get("likelihood_ratio", 1.5)),
                        description=str(r.get("description", "")),
                    )
                )

            questions: list[DisambiguationQuestion] = []
            for q in item.get("disambiguation_questions") or []:
                if not isinstance(q, dict):
                    continue
                questions.append(
                    DisambiguationQuestion(
                        id=str(q.get("id", "")),
                        prompt=str(q.get("prompt", "")),
                        positive_concepts=tuple(str(c) for c in (q.get("positive_concepts") or [])),
                        yes_likelihood=float(q.get("yes_likelihood", 0.85)),
                        no_likelihood=float(q.get("no_likelihood", 0.15)),
                        owner_condition_id=cond_id,
                    )
                )

            esc_str = str(item.get("default_escalation", "LOCAL"))
            try:
                esc = Escalation(esc_str)
            except ValueError:
                esc = Escalation.LOCAL

            raw_symptoms = item.get("symptoms") or {}
            sym_map = {str(k): float(v) for k, v in raw_symptoms.items()} if isinstance(raw_symptoms, dict) else {}

            conditions.append(
                CausalCondition(
                    id=cond_id,
                    name=str(item.get("name", cond_id)),
                    source_id=str(item.get("source_id", cond_id)),
                    subsystem=str(item.get("subsystem", "")),
                    prior=float(item.get("prior", 0.1)),
                    default_escalation=esc,
                    symptoms=sym_map,
                    sensor_rules=tuple(rules),
                    countermeasures=tuple(str(c) for c in (item.get("countermeasures") or [])),
                    actions=tuple(str(a) for a in (item.get("actions") or [])),
                    disambiguation_questions=tuple(questions),
                )
            )
        return conditions
