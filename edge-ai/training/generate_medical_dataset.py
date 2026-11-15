"""Layer 1: Deterministic offline NASA HRP/CSA corpus & ChatML dataset generator."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from edgespace_ai.correlation.clinical_store import load_yaml_file
from edgespace_ai.correlation.correlator import ClinicalCorrelator, _format_symptoms_pt
from edgespace_ai.correlation.synthesizer import LocalSLMSynthesizer
from edgespace_ai.ipc.handlers import _build_sensor_snapshot, _collect_memory_facts
from edgespace_ai.ipc.protocol import (
    AIInferencePayload,
    ChatCorrelateReqPayload,
    CrewProfile,
    Peripheral,
    PeripheralReading,
    now_us,
)


def _apply_migrations(db_file: Path) -> None:
    mig_dir = _REPO_ROOT / "database" / "migrations"
    conn = sqlite3.connect(db_file)
    try:
        for sql_path in sorted(mig_dir.glob("*.sql")):
            conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


CONCEPT_PHRASE_BANK: dict[str, tuple[list[str], list[str]]] = {
    "headache": (
        ["dor de cabeca", "dores de cabeca", "cefaleia", "pressao na cabeca", "headache", "headaches"],
        ["cabeca latejando", "cabeca pulsando de dor", "enxaqueca forte", "pounding headache"],
    ),
    "photophobia": (
        ["ao olhar para a luz", "sensibilidade a luz", "fotofobia", "light sensitivity", "photophobia"],
        ["claridade incomoda muito", "olhos doem com a luz da cabine", "bright cabin light hurts my eyes"],
    ),
    "blurred_vision": (
        ["visao embacada", "visao turva", "vista embacada", "blurred vision", "blurry vision"],
        ["enxergando tudo embacado", "vista meio fora de foco", "my vision feels blurry"],
    ),
    "eye_pressure": (
        ["pressao ocular", "pressao nos olhos", "dor atras dos olhos", "eye pressure", "pain behind eyes"],
        ["olhos pesados e pressionados", "fundo do olho doendo", "eyes hurt behind sockets"],
    ),
    "dizziness": (
        ["tontura", "tonturas", "vertigem", "zonzeira", "dizziness", "dizzy"],
        ["cabeca girando", "sensacao de desequilibrio", "fiquei meio tonto", "feeling lightheaded"],
    ),
    "dyspnea": (
        ["falta de ar", "dispneia", "ofegante", "dificuldade para respirar", "shortness of breath", "dyspnea"],
        ["respiracao curta", "ar nao entra direito", "hard to catch my breath"],
    ),
    "nausea": (
        ["nausea", "enjoo", "enjoos", "vontade de vomitar", "vomito", "queasy"],
        ["estomago embrulhado", "ansia de vomito", "enjoado no modulo", "feeling nauseous"],
    ),
    "insomnia": (
        ["insonia", "nao consigo dormir", "privacao de sono", "insomnia", "cant sleep"],
        ["dormi pouco", "acordando varias vezes", "sono picado", "trouble falling asleep"],
    ),
    "fatigue": (
        ["fadiga", "cansaco", "exaustao", "fatigue", "exhaustion"],
        ["corpo esgotado", "cansado demais", "worn out and tired"],
    ),
    "flank_pain": (
        ["dor no flanco", "colica renal", "dor ao urinar", "flank pain", "kidney pain"],
        ["dor nas costas do lado direito perto do rim", "fisgada na lateral lombar", "sharp side lower back pain"],
    ),
    "joint_pain": (
        ["dor articular", "dor nas articulacoes", "dor no ombro pos eva", "joint pain"],
        ["junta doendo", "joint ache in shoulder", "knee joint soreness"],
    ),
    "muscle_pain": (
        ["dor muscular", "dor na perna", "dor nas pernas", "muscle pain", "leg pain"],
        ["musculo travado e dolorido", "coxa doendo apos treino", "sore calf muscles"],
    ),
    "orthostatic_intolerance": (
        ["tontura ao levantar", "pressao baixa", "palpitacao", "presyncope", "palpitations"],
        ["vista escurece quando fico de pe", "dizzy when standing up", "orthostatic lightheadedness"],
    ),
    "abdominal_pain": (
        ["dor de barriga", "dor abdominal", "dor no estomago", "stomach pain"],
        ["colica na barriga", "abdome dolorido", "cramps in lower belly"],
    ),
    "gi_slowdown": (
        ["estufamento", "prisao de ventre", "constipacao", "bloating", "constipation"],
        ["intestino preso", "barriga estufada", "digestion slowed down"],
    ),
    "rash_infection": (
        ["erupcao na pele", "coceira", "lesao na pele", "skin rash", "itchy rash"],
        ["manchas vermelhas na pele", "irritacao cutanea", "skin irritation and hives"],
    ),
    "bone_pain": (
        ["dor ossea", "dor nos ossos", "bone pain"],
        ["osso doendo", "dor profunda no quadril", "deep bone ache"],
    ),
}

CREW_NAMES = {"crew_001": "Cmdr. Silva", "crew_002": "Dr. Costa", "crew_003": "Eng. Sato"}
GREETINGS = ("ola, ", "oi, ", "bom dia, ", "boa noite, ", "hello, ", "")
LEADS = ("estou com ", "estou sentindo ", "tenho ", "sinto ", "i have ", "i feel ")
NEG_LEADS = ("nao estou com ", "sem ", "nao tenho ", "no ")
MEMORY_SENTENCES = (
    "sou alergico a dipirona",
    "sou alergico a sulfa",
    "tomo melatonina",
    "ja tive enjoo espacial",
    "i am allergic to penicillin",
)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_PCT_RE = re.compile(r"\(\d+%\)")


def load_protocols() -> dict[str, dict[str, Any]]:
    """condition_id -> protocol (name, source_id, first step) from knowledge-base/protocols."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((_REPO_ROOT / "knowledge-base" / "protocols").glob("*.yaml")):
        data = load_yaml_file(p)
        for risk in data.get("linked_risks") or []:
            out.setdefault(str(risk), data)
    return out


def _pick(rng: random.Random, options: tuple[str, ...]) -> str:
    return options[rng.randrange(len(options))]


def _telemetry_text(snapshot: dict[str, Any]) -> str:
    parts: list[str] = []
    if "CO2_ppm" in snapshot:
        parts.append(f"CO2 SCD40={snapshot['CO2_ppm']:.0f} ppm")
    if "SpO2_pct" in snapshot:
        parts.append(f"SpO2 MAX30102={snapshot['SpO2_pct']:.1f}%")
    if "FC_oximetro_bpm" in snapshot:
        parts.append(f"FC={snapshot['FC_oximetro_bpm']:.0f} bpm")
    if "CSI_postura" in snapshot:
        parts.append(f"postura={snapshot['CSI_postura']}")
    return ", ".join(parts)


def compose_flight_surgeon_reply(
    *,
    resp: Any,
    snapshot: dict[str, Any],
    crew_name: str,
    memory_texts: list[str],
    protocols: dict[str, dict[str, Any]],
    top_condition_id: str | None,
    rng: random.Random,
) -> str | None:
    """Deterministic, fully-grounded paraphrase. Returns None when context lacks a hypothesis."""
    if not resp.differentials or not resp.countermeasures:
        return None
    m = re.match(r"^(.*) \(P=([0-9.]+)\)$", resp.differentials[0])
    if not m:
        return None
    name, p_top = m.group(1), float(m.group(2))
    concepts: list[str] = []
    for ev in resp.evidence or []:
        if ev.startswith("Sintomas detectados:"):
            concepts = [c.strip() for c in ev.split(":", 1)[1].split(",") if c.strip()]
    sentences: list[str] = []
    if concepts:
        sym = _format_symptoms_pt(concepts)
        sentences.append(_pick(rng, (
            f"Entendido, {crew_name} — registrei {sym}.",
            f"{crew_name}, anotei {sym} no seu relato.",
            f"Recebi seu relato de {sym}, {crew_name}.",
        )))
    tele = _telemetry_text(snapshot)
    if tele:
        sentences.append(_pick(rng, (
            f"Na telemetria deste instante ({tele}), cruzei os dados com a sua queixa.",
            f"Os sensores marcam {tele}, e comparei esses valores com o que você descreveu.",
            f"Pelos dados atuais ({tele}), avaliei o quadro junto com os sintomas.",
        )))
    diff = ""
    if len(resp.differentials) > 1:
        m2 = re.match(r"^(.*) \(P=([0-9.]+)\)$", resp.differentials[1])
        if m2 and float(m2.group(2)) >= 0.08:
            diff = f", mantendo {m2.group(1)} ({float(m2.group(2)):.0%}) como diferencial"
    src = (resp.source_ids or ["NASA HRP/CSA"])[0]
    sentences.append(_pick(rng, (
        f"A hipótese principal pela base {src} é {name} ({p_top:.0%}){diff}.",
        f"Pela base {src}, o quadro é mais compatível com {name} ({p_top:.0%}){diff}.",
    )))
    cm = re.sub(r"^\d+\.\s*", "", resp.countermeasures[0]).strip()
    sentences.append(_pick(rng, (f"Conduta imediata: {cm}", f"Recomendo agora: {cm}")))
    blocked = list(resp.blocked_actions or [])
    if blocked:
        sentences.append(f"Por segurança, estão bloqueadas as ações: {', '.join(blocked)}.")
    elif memory_texts:
        sentences.append(f"Considerei também o que está registrado no seu histórico: {memory_texts[0]}.")
    proto = protocols.get(top_condition_id or "")
    if resp.disambiguation_question:
        sentences.append(resp.disambiguation_question.strip())
    elif proto:
        sentences.append(f"Protocolo de apoio: {proto.get('name')}.")
    return " ".join(sentences)


def fidelity_ok(text: str, context: str, resp: Any) -> bool:
    """All numbers must come from context; top hypothesis + first countermeasure must be present."""
    if not text or not resp.differentials or not resp.countermeasures:
        return False
    name = resp.differentials[0].rsplit(" (P=", 1)[0]
    cm = re.sub(r"^\d+\.\s*", "", resp.countermeasures[0]).strip()
    if name not in text or cm not in text:
        return False
    stripped = _PCT_RE.sub("", text)
    ctx_nums = {float(x) for x in _NUM_RE.findall(context)}
    return all(float(x) in ctx_nums for x in _NUM_RE.findall(stripped))


SENSOR_PROFILES: tuple[dict[str, Any], ...] = (
    {"name": "nominal", "co2": 600.0, "spo2": 98.5, "hr": 70.0, "posture": "supine", "anom": 0.30},
    {"name": "co2_high", "co2": 3800.0, "spo2": 97.0, "hr": 88.0, "posture": "sitting", "anom": 0.55},
    {"name": "hypoxic", "co2": 700.0, "spo2": 88.0, "hr": 104.0, "posture": "sitting", "anom": 0.60},
    {"name": "mild_co2", "co2": 1800.0, "spo2": 97.5, "hr": 78.0, "posture": "standing", "anom": 0.40},
)


def _readings(profile: dict[str, Any]) -> list[PeripheralReading]:
    ts = now_us()
    return [
        PeripheralReading(type=Peripheral.SCD40, value=profile["co2"], unit="ppm", timestamp_us=ts),
        PeripheralReading(type=Peripheral.MAX30102, value=profile["spo2"], unit="%", timestamp_us=ts),
        PeripheralReading(type=Peripheral.MAX30102, value=profile["hr"], unit="bpm", timestamp_us=ts),
    ]


def _inference(profile: dict[str, Any]) -> AIInferencePayload:
    return AIInferencePayload(
        cycle_seq_first=1,
        posture=profile["posture"],
        respiration_hz=0.24,
        heart_rate_bpm=profile["hr"],
        hrv_ms=48.0,
        anomaly_score=profile["anom"],
        confidence=0.85,
    )


def _build_text(rng: random.Random, phrases: list[str], *, negated: str | None, memory: str | None) -> str:
    chosen = rng.sample(phrases, k=min(len(phrases), rng.choice((1, 1, 2))))
    body = " e ".join(f"{_pick(rng, LEADS)}{p}" if i == 0 else p for i, p in enumerate(chosen))
    if negated:
        body += f", {_pick(rng, NEG_LEADS)}{negated}"
    if memory:
        body += f". {memory}"
    return f"{_pick(rng, GREETINGS)}{body}"


def _dump(path: Path, rows: list[dict[str, Any]]) -> str:
    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n"
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]



def _load_reports() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted((_REPO_ROOT / "knowledge-base" / "nasa_hrp_reports").glob("*.yaml")):
        out.append(load_yaml_file(p))
    return out


def generate(*, seed: int, per_concept: int, out_dir: Path) -> dict[str, Any]:
    rng = random.Random(seed)
    protocols = load_protocols()
    reports = _load_reports()
    golden = json.loads(
        (_REPO_ROOT / "knowledge-base" / "datasets" / "golden_cases" / "golden_cases.yaml").read_text(encoding="utf-8")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    synth = LocalSLMSynthesizer(disabled=True, auto_load=False)

    chat_rows: list[dict[str, Any]] = []
    nlu_train: list[dict[str, Any]] = []
    nlu_eval: list[dict[str, Any]] = []
    stats = {"generated": 0, "dropped_no_hypothesis": 0, "dropped_fidelity": 0}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_file = Path(tmp) / "gen.db"
        _apply_migrations(db_file)
        correlator = ClinicalCorrelator(db_path=db_file)
        cond_by_name = {c.name: c.id for c in correlator.causal_graph.conditions}
        concepts = sorted(CONCEPT_PHRASE_BANK)

        def _emit(text: str, crew_id: str, profile: dict[str, Any], meta: dict[str, Any]) -> None:
            prof = CrewProfile(crew_id=crew_id, name=CREW_NAMES[crew_id], mission_day=5 + (rng.randrange(90)))
            readings = _readings(profile)
            inf = _inference(profile)
            req = ChatCorrelateReqPayload(text=text, crew_id=crew_id, profile=prof)
            resp = correlator.correlate(req, peripherals=readings, inference=inf)
            snapshot = _build_sensor_snapshot(peripherals=readings, inference=inf, crew_id=crew_id)
            top_id = cond_by_name.get(resp.differentials[0].rsplit(" (P=", 1)[0]) if resp.differentials else None
            reply = compose_flight_surgeon_reply(
                resp=resp, snapshot=snapshot, crew_name=CREW_NAMES[crew_id],
                memory_texts=[u["fact_value"] for u in (resp.memory_updates or []) if u.get("fact_value")],
                protocols=protocols, top_condition_id=top_id, rng=rng,
            )
            if reply is None:
                stats["dropped_no_hypothesis"] += 1
                return
            messages = synth.build_messages(resp, _collect_memory_facts(req, crew_id=crew_id), snapshot)
            if not fidelity_ok(reply, " ".join(m["content"] for m in messages), resp):
                stats["dropped_fidelity"] += 1
                return
            chat_rows.append({"messages": [*messages, {"role": "assistant", "content": reply}], "meta": meta})
            stats["generated"] += 1

        for concept in concepts:
            train_phr, eval_phr = CONCEPT_PHRASE_BANK[concept]
            for split, phrases in (("train", train_phr), ("eval", eval_phr)):
                n = per_concept if split == "train" else max(4, per_concept // 4)
                for i in range(n):
                    profile = SENSOR_PROFILES[(i + len(concept)) % len(SENSOR_PROFILES)]
                    other = rng.choice([c for c in concepts if c != concept])
                    negated = rng.choice(CONCEPT_PHRASE_BANK[other][0]) if i % 5 == 0 else None
                    memory = rng.choice(MEMORY_SENTENCES) if i % 4 == 0 else None
                    text = _build_text(rng, phrases, negated=negated, memory=memory)
                    crew_id = ("crew_001", "crew_002", "crew_003")[i % 3]
                    row = {"text": text, "expected_concepts": [concept], "forbidden_concepts": [other] if negated else [], "split": split}
                    (nlu_train if split == "train" else nlu_eval).append(row)
                    if split == "train":
                        _emit(text, crew_id, profile, {"source": "phrase_bank", "concept": concept})

        # Add report primary_symptoms & golden cases structured narratives
        for rep in reports:
            cond = (rep.get("conditions") or [{}])[0]
            cid = str(cond.get("condition_id", ""))
            for sym in (rep.get("primary_symptoms") or [])[:4]:
                _emit(f"estou com {sym}", "crew_001", SENSOR_PROFILES[0], {"source": "report", "condition_id": cid})
        for case in golden.get("cases", []):
            m = case.get("metrics") or {}
            prof = {
                "name": "golden",
                "co2": float(m.get("co2_ppm") if m.get("co2_ppm") is not None else 600.0),
                "spo2": float(m.get("spo2_pct") if m.get("spo2_pct") is not None else 98.0),
                "hr": float(m.get("heart_rate_bpm") if m.get("heart_rate_bpm") is not None else 72.0),
                "posture": "sitting",
                "anom": 0.45,
            }
            _emit(case.get("title", "Revisar sintomas"), case.get("crew_id", "crew_001"), prof, {"source": "golden", "case_id": case.get("case_id")})

    golden_units = len(golden.get("cases", [])) + sum(len(c.get("crews") or {}) for c in golden.get("crew_cases", []))
    digest = _dump(out_dir / "nasa_medical_instruct.jsonl", chat_rows)
    _dump(out_dir / "nlu_train.jsonl", nlu_train)
    _dump(out_dir / "nlu_eval.jsonl", nlu_eval)
    synth.close()
    return {
        **stats,
        "reports_read": len(reports),
        "protocols_read": len({p.get("protocol_id") for p in protocols.values()}),
        "golden_expectation_units": golden_units,
        "nlu_train": len(nlu_train),
        "nlu_eval": len(nlu_eval),
        "chatml_sha256_16": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate EdgeSpace medical ChatML + NLU datasets.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-concept", type=int, default=60)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args()
    print(json.dumps(generate(seed=args.seed, per_concept=args.per_concept, out_dir=args.out_dir), indent=2))


if __name__ == "__main__":
    main()

