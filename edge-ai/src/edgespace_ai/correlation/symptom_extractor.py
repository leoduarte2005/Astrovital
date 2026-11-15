"""Bilingual (PT/EN) lexical and semantic symptom extractor for crew chat messages."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..ipc.protocol import ChatMessage


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


SYMPTOM_LEXICON: dict[str, tuple[str, ...]] = {
    "headache": (
        "dor de cabeca",
        "cabeca doendo",
        "cefaleia",
        "enxaqueca",
        "pressao na cabeca",
        "headache",
        "migraine",
        "head pressure",
    ),
    "blurred_vision": (
        "visao turva",
        "visao embacada",
        "vista embacada",
        "enxergando mal",
        "escotoma",
        "linhas onduladas",
        "grade de amsler",
        "amsler",
        "blurred vision",
        "blurry vision",
        "blurry",
        "visual distortion",
    ),
    "eye_pressure": (
        "pressao ocular",
        "pressao nos olhos",
        "olhos pesados",
        "dor atras dos olhos",
        "eye pressure",
        "ocular pressure",
        "pain behind eyes",
    ),
    "nasal_congestion": (
        "nariz entupido",
        "congestao nasal",
        "seios da face",
        "nasal congestion",
        "stuffy nose",
        "sinus pressure",
    ),
    "facial_puffiness": (
        "rosto inchado",
        "edema facial",
        "cara inchada",
        "puffy face",
        "facial edema",
    ),
    "fluid_shift": (
        "fluid shift",
        "deslocamento de fluidos",
        "pressao elevada",
        "pressao intracraniana",
        "pressao cefalica",
        "cabeca pesada",
        "elevated pressure",
    ),
    "papilledema": ("papiledema", "papilledema", "optic disc"),
    "dizziness": (
        "tontura",
        "tonto",
        "tonta",
        "vertigem",
        "zonzeira",
        "cabeca leve",
        "dizziness",
        "dizzy",
        "vertigo",
        "lightheaded",
    ),
    "fatigue": (
        "cansaco",
        "cansado",
        "cansada",
        "fadiga",
        "exausto",
        "exaustao",
        "sem energia",
        "sono excessivo",
        "fatigue",
        "tired",
        "exhausted",
        "exhaustion",
    ),
    "dyspnea": (
        "falta de ar",
        "dificuldade para respirar",
        "dispneia",
        "ofegante",
        "ar pesado",
        "shortness of breath",
        "breathless",
        "dyspnea",
        "cant breathe",
    ),
    "confusion": (
        "confusao",
        "confuso",
        "desorientado",
        "nevoa mental",
        "lentidao mental",
        "confusion",
        "disoriented",
        "brain fog",
        "groggy",
    ),
    "nausea": (
        "nausea",
        "enjoo",
        "enjoado",
        "vomito",
        "vomitos",
        "vomitar",
        "ansia",
        "vomiting",
        "queasy",
    ),
    "flushed_skin": ("rosto vermelho", "rubor", "flushed", "flushing"),
    "cyanosis": ("cianose", "labios roxos", "unhas roxas", "cyanosis", "blue lips"),
    "insomnia": (
        "insonia",
        "nao consigo dormir",
        "sem dormir",
        "privacao de sono",
        "acordando muito",
        "insomnia",
        "cant sleep",
        "sleep deprivation",
    ),
    "malaise": ("mal estar", "mal-estar", "indisposicao", "febre", "calafrio", "malaise", "fever", "chills"),
    "rash_infection": (
        "mancha na pele",
        "erupcao",
        "coceira",
        "lesao cutanea",
        "rash",
        "skin lesion",
        "itching",
    ),
    "flank_pain": (
        "dor no flanco",
        "dor nas costas",
        "dor ao urinar",
        "pedra no rim",
        "calculo renal",
        "colica renal",
        "dor irradiando para virilha",
        "flank pain",
        "kidney pain",
        "kidney stone",
        "renal colic",
    ),
    "gi_slowdown": (
        "constipacao",
        "prisao de ventre",
        "intestino preso",
        "intestino travado",
        "estufamento",
        "estufado",
        "gases",
        "digestao lenta",
        "bloating",
        "bloated",
        "constipation",
        "constipated",
    ),
    "back_pain": ("dor lombar", "dor nas costas", "lombalgia", "back pain", "lower back"),
    "hematuria": ("sangue na urina", "urina escura", "hematuria", "blood in urine", "dark urine"),
    "dysuria": ("ardencia ao urinar", "dor ao urinar", "disuria", "dysuria", "painful urination"),
    "joint_pain": (
        "dor articular",
        "dor nas juntas",
        "artralgia",
        "juntas doendo",
        "joelho doi",
        "dor no joelho",
        "ombro doi",
        "dor no ombro",
        "tornozelo doi",
        "dor no tornozelo",
        "punho doi",
        "cotovelo doi",
        "joint pain",
        "arthralgia",
        "knee pain",
        "shoulder pain",
        "bends",
    ),
    "muscle_pain": (
        "dor muscular",
        "dor na perna",
        "dor nas pernas",
        "perna doi",
        "pernas doem",
        "perna doendo",
        "pernas doendo",
        "dor na coxa",
        "coxa doi",
        "dor na panturrilha",
        "panturrilha doi",
        "panturrilha doendo",
        "dor no braco",
        "braco doi",
        "caimbra",
        "caimbras",
        "mialgia",
        "muscle pain",
        "leg pain",
        "calf pain",
        "thigh pain",
        "arm pain",
        "myalgia",
        "soreness",
        "sore leg",
        "muscle ache",
    ),
    "muscle_weakness": (
        "fraqueza muscular",
        "fraqueza",
        "perna fraca",
        "pernas fracas",
        "sem forca",
        "perda de forca",
        "dificuldade para andar",
        "dificuldade ao andar",
        "quando tento andar",
        "ao andar",
        "ao caminhar",
        "intolerancia ao exercicio",
        "cansaco ao andar",
        "muscle weakness",
        "weakness",
        "weak legs",
        "difficulty walking",
        "exercise intolerance",
    ),
    "limb_swelling": (
        "perna inchada",
        "inchaco na perna",
        "inchaco nas pernas",
        "panturrilha inchada",
        "edema na perna",
        "tornozelo inchado",
        "inchaco no pe",
        "leg swelling",
        "swollen leg",
        "calf swelling",
        "swollen ankle",
        "dvt",
        "tvp",
    ),
    "bone_pain": (
        "dor ossea",
        "dor no osso",
        "dor nos ossos",
        "dor no quadril",
        "quadril doi",
        "bone pain",
        "hip pain",
    ),
    "orthostatic_intolerance": (
        "tontura ao levantar",
        "tontura em pe",
        "pressao baixa",
        "palpitacao",
        "palpitacoes",
        "pre-sincope",
        "quase desmaiei",
        "desmaio",
        "orthostatic dizziness",
        "presyncope",
        "palpitations",
        "hypotension",
        "fainting",
    ),
    "abdominal_pain": (
        "dor de barriga",
        "dor na barriga",
        "barriga doendo",
        "dor abdominal",
        "dor no estomago",
        "estomago doendo",
        "colica",
        "stomach ache",
        "stomachache",
        "stomach pain",
        "abdominal pain",
        "belly pain",
        "cramps",
    ),
    "paresthesia": (
        "formigamento",
        "dormencia",
        "parestesia",
        "agulhadas",
        "paresthesia",
        "tingling",
        "numbness",
    ),
    "chest_pain": ("dor no peito", "dor toracica", "aperto no peito", "chest pain", "chest tightness"),
}

_EVA_KEYWORDS = ("eva", "extraveicular", "caminhada espacial", "airlock", "despressurizacao", "depressurization")
_RADIATION_KEYWORDS = ("radiacao", "radiation", "spe", "gcr", "tempestade solar", "solar particle", "dosimetro")


@dataclass(frozen=True)
class ExtractedSymptoms:
    """Extracted clinical concepts and context cues from chat text and history."""

    concepts: tuple[str, ...]
    matched_terms: dict[str, list[str]]
    eva_context: bool
    radiation_context: bool
    answered_topics: tuple[str, ...]


class SymptomExtractor:
    """Maps free-form Portuguese and English chat text to clinical symptom concepts."""

    def extract(
        self,
        text: str,
        *,
        recent_history: Sequence[ChatMessage] | None = None,
        summary_24h: str | None = None,
    ) -> ExtractedSymptoms:
        current_norm = _normalize_text(text)

        history_texts: list[str] = []
        if recent_history:
            for msg in recent_history[-6:]:
                if msg.role == "user":
                    history_texts.append(_normalize_text(msg.content))
        if summary_24h:
            history_texts.append(_normalize_text(summary_24h))

        combined = " ".join([current_norm, *history_texts]).strip()

        # Symptoms come from the current message only. History/summary may add symptoms
        # only when the current message is a bare follow-up answer (e.g. "sim", "no"),
        # so a stale "headache" from earlier turns never leaks into a new complaint.
        matched = _match_lexicon(current_norm)
        if not matched and _is_followup_answer(current_norm):
            matched = _match_lexicon(" ".join(history_texts))

        eva_ctx = any(_phrase_in_text(kw, combined) for kw in _EVA_KEYWORDS)
        rad_ctx = any(_phrase_in_text(kw, combined) for kw in _RADIATION_KEYWORDS)

        answered_topics: list[str] = []
        if any(_phrase_in_text(p, combined) for p in ("amsler", "linhas onduladas", "visao turva", "blurred vision")):
            answered_topics.append("amsler_grid")
        if any(_phrase_in_text(p, combined) for p in ("ventilacao", "ventilation", "falta de ar", "dyspnea")):
            answered_topics.append("ventilation_air")
        if eva_ctx:
            answered_topics.append("eva_recent")
        if rad_ctx:
            answered_topics.append("nausea_prodrome")

        return ExtractedSymptoms(
            concepts=tuple(matched.keys()),
            matched_terms=matched,
            eva_context=eva_ctx,
            radiation_context=rad_ctx,
            answered_topics=tuple(answered_topics),
        )


_FOLLOWUP_ANSWERS = frozenset(
    {"sim", "nao", "yes", "no", "talvez", "maybe", "um pouco", "bastante", "a little", "not sure", "nao sei"}
)


def _is_followup_answer(norm_text: str) -> bool:
    """True when the message is only a short yes/no style reply to a disambiguation question."""
    cleaned = re.sub(r"[^a-z0-9 ]", " ", norm_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned in _FOLLOWUP_ANSWERS


def _match_lexicon(norm_text: str) -> dict[str, list[str]]:
    """Return lexicon concepts found in already-normalized text. Never invents a default symptom."""
    matched: dict[str, list[str]] = {}
    if not norm_text:
        return matched
    for concept, phrases in SYMPTOM_LEXICON.items():
        hits = [p for p in phrases if _phrase_in_text(p, norm_text)]
        if hits:
            matched[concept] = hits
    return matched


def _phrase_in_text(phrase: str, text: str) -> bool:
    if " " in phrase:
        return phrase in text
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None
