"""Bilingual (PT/EN) lexical and semantic symptom extractor for crew chat messages."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional, Sequence

from ..ipc.protocol import ChatMessage
from .clinical_store import ClinicalDocument, ClinicalStore


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


SYMPTOM_LEXICON: dict[str, tuple[str, ...]] = {
    "headache": (
        "headache", "headaches", "migraine", "migraines", "head pressure",
        "pounding headache", "throbbing head", "throbbing headache",
        "frontal headache", "pressure in head", "head hurts", "head aching",
        "dor de cabeca", "dores de cabeca", "dor na cabeca", "dores na cabeca",
        "cabeca doendo", "cefaleia", "cefaleias", "enxaqueca", "pressao na cabeca",
    ),
    "photophobia": (
        "photophobia", "light sensitivity", "sensitive to light",
        "looking at the light", "looking at light", "bright light hurts",
        "bright light discomfort", "light hurts my eyes", "eyes hurt with light",
        "ao olhar para a luz", "olhar para a luz", "sensibilidade a luz",
        "incomodo com a luz", "fotofobia", "luz incomoda", "ardencia nos olhos com luz",
    ),
    "visual_disturbance": (
        "blurred vision", "blurry vision", "visual distortion", "visual disturbance",
        "vision blurry", "wavy lines", "distorted vision", "scotoma",
        "vision problems", "trouble seeing", "double vision", "blurry sight",
        "visao turva", "visao embacada", "vista embacada", "meio embacada",
        "esta embacada", "embacada", "embacado", "enxergando mal",
        "mancha na visao", "linhas tortas", "linhas onduladas", "escotoma",
    ),
    "blurred_vision": (
        "blurred vision", "blurry vision", "blurry", "blurriness",
        "visual distortion", "out of focus", "amsler", "amsler grid",
        "visao turva", "visao embacada", "vista embacada", "meio embacada",
        "esta embacada", "embacada", "embacado", "enxergando mal",
        "mancha na visao", "linhas tortas", "escotoma", "linhas onduladas", "grade de amsler",
    ),
    "eye_pressure": (
        "eye pressure", "ocular pressure", "pain behind eyes",
        "pressure behind eyes", "heavy eyes", "retro orbital pain", "ocular tightness",
        "pressao ocular", "pressao nos olhos", "olhos pesados", "dor atras dos olhos",
    ),
    "nasal_congestion": (
        "nasal congestion", "stuffy nose", "sinus pressure", "blocked nose", "congested nose",
        "nariz entupido", "congestao nasal", "seios da face",
    ),
    "facial_puffiness": (
        "puffy face", "facial edema", "swollen face", "face swelling", "facial puffiness",
        "rosto inchado", "edema facial", "cara inchada",
    ),
    "fluid_shift": (
        "fluid shift", "elevated pressure", "intracranial pressure",
        "cephalic pressure", "heavy head", "head fullness",
        "deslocamento de fluidos", "pressao elevada", "pressao intracraniana",
        "pressao cefalica", "cabeca pesada",
    ),
    "papilledema": ("papilledema", "papiledema", "optic disc", "optic disc edema"),
    "dizziness": (
        "dizziness", "dizzy", "vertigo", "lightheaded", "lightheadedness",
        "spinning sensation", "room spinning", "feeling unsteady", "woozy",
        "head feels light", "tontura", "tonturas", "tonto", "tonta", "vertigem", "zonzeira", "cabeca leve",
    ),
    "fatigue": (
        "fatigue", "exhaustion", "tired", "tiredness", "worn out",
        "low energy", "drained", "extreme tiredness", "fatigued", "exhausted",
        "cansaco", "cansado", "cansada", "fadiga", "exausto", "exaustao", "sem energia", "sono excessivo",
    ),
    "dyspnea": (
        "dyspnea", "shortness of breath", "breathless", "difficulty breathing",
        "hard to breathe", "cant breathe", "can't breathe", "air hunger",
        "labored breathing", "short of breath", "hard to catch my breath",
        "falta de ar", "dificuldade para respirar", "dispneia", "ofegante", "ar pesado",
    ),
    "confusion": (
        "confusion", "confused", "disoriented", "brain fog", "mental fog",
        "groggy", "cognitive fog", "trouble concentrating", "confusao", "confuso", "desorientado", "nevoa mental",
    ),
    "nausea": (
        "nausea", "nauseous", "queasy", "sick to my stomach", "sick to stomach",
        "vomiting", "vomit", "throwing up", "motion sickness", "upset stomach",
        "enjoo", "enjoos", "enjoado", "enjada", "vomito", "vomitos", "vomitar", "ansia",
    ),
    "flushed_skin": ("flushed", "flushing", "red face", "facial flushing", "rosto vermelho", "rubor"),
    "cyanosis": ("cyanosis", "blue lips", "blue fingernails", "bluish skin", "cianose", "labios roxos", "unhas roxas"),
    "insomnia": (
        "insomnia", "cant sleep", "can't sleep", "trouble sleeping",
        "sleep deprivation", "poor sleep", "fragmented sleep",
        "waking up often", "difficulty falling asleep", "barely slept",
        "insonia", "nao consigo dormir", "sem dormir", "privacao de sono", "acordando muito",
    ),
    "malaise": ("malaise", "fever", "chills", "feeling unwell", "general discomfort", "mal estar", "mal-estar", "indisposicao", "febre", "calafrio"),
    "rash_infection": (
        "rash", "skin lesion", "skin lesions", "skin irritation", "itching", "itchy", "hives", "skin rash", "red spots on skin",
        "mancha na pele", "erupcao", "coceira", "lesao cutanea",
    ),
    "flank_pain": (
        "flank pain", "kidney pain", "side pain", "renal colic", "kidney stone", "kidney stone pain", "sharp side pain",
        "dor no flanco", "dor nas costas", "dor ao urinar", "pedra no rim", "calculo renal", "colica renal", "dor irradiando para virilha",
    ),
    "gi_slowdown": (
        "constipation", "constipated", "bloating", "bloated", "slow digestion", "sluggish digestion", "gas", "stomach bloating",
        "constipacao", "prisao de ventre", "intestino preso", "intestino travado", "estufamento", "estufado", "gases", "digestao lenta",
    ),
    "back_pain": ("back pain", "lower back pain", "lower back", "lumbar pain", "dor lombar", "dor nas costas", "lombalgia"),
    "hematuria": ("blood in urine", "dark urine", "hematuria", "bloody urine", "sangue na urina", "urina escura"),
    "dysuria": ("painful urination", "burning urination", "dysuria", "pain when urinating", "ardencia ao urinar", "dor ao urinar", "disuria"),
    "joint_pain": (
        "joint pain", "joint pains", "arthralgia", "knee pain", "shoulder pain",
        "ankle pain", "wrist pain", "elbow pain", "joint ache", "sore joints",
        "joint soreness", "bends", "dor articular", "dor nas juntas", "artralgia",
        "juntas doendo", "joelho doi", "dor no joelho", "ombro doi", "dor no ombro",
        "tornozelo doi", "dor no tornozelo", "punho doi", "cotovelo doi",
    ),
    "muscle_pain": (
        "muscle pain", "leg pain", "leg hurts", "legs hurt", "pain in my leg",
        "calf pain", "thigh pain", "arm pain",
        "myalgia", "soreness", "sore leg", "sore legs", "muscle ache",
        "muscle soreness", "cramp", "cramps", "dor muscular", "dor na perna",
        "dor nas pernas", "perna doi", "pernas doem", "perna doendo", "pernas doendo",
        "dor na coxa", "coxa doi", "dor na panturrilha", "panturrilha doi",
        "panturrilha doendo", "dor no braco", "braco doi", "caimbra", "caimbras", "mialgia",
    ),
    "muscle_weakness": (
        "muscle weakness", "weakness", "weak legs", "difficulty walking",
        "exercise intolerance", "weak when walking", "when i try to walk",
        "try to walk", "hurts to walk", "when walking", "legs feel weak", "loss of strength",
        "fraqueza muscular", "fraqueza", "perna fraca", "pernas fracas", "sem forca",
        "perda de forca", "dificuldade para andar", "dificuldade ao andar",
        "quando tento andar", "ao andar", "ao caminhar", "intolerancia ao exercicio", "cansaco ao andar",
    ),
    "limb_swelling": (
        "leg swelling", "swollen leg", "swollen legs", "calf swelling",
        "swollen ankle", "ankle swelling", "dvt", "deep vein thrombosis",
        "perna inchada", "inchaco na perna", "inchaco nas pernas",
        "panturrilha inchada", "edema na perna", "tornozelo inchado", "inchaco no pe",
    ),
    "bone_pain": ("bone pain", "hip pain", "deep bone ache", "bone ache", "dor ossea", "dor no osso", "dor nos ossos", "dor no quadril", "quadril doi"),
    "orthostatic_intolerance": (
        "orthostatic intolerance", "orthostatic dizziness", "dizzy when standing",
        "lightheaded when standing", "presyncope", "palpitations",
        "fainting", "hypotension", "blackout when standing", "vision darkens when standing",
        "tontura ao levantar", "tontura em pe", "pressao baixa", "palpitacao", "palpitacoes",
        "pre-sincope", "quase desmaiei", "desmaio",
    ),
    "abdominal_pain": (
        "abdominal pain", "stomach ache", "stomachache", "stomach pain", "belly pain",
        "cramps", "stomach cramps", "belly ache", "dor de barriga", "dor na barriga",
        "barriga doendo", "dor abdominal", "dor no estomago", "estomago doendo", "colica",
    ),
    "paresthesia": (
        "paresthesia", "tingling", "numbness", "pins and needles", "tingling sensation",
        "formigamento", "dormencia", "parestesia", "agulhadas",
    ),
    "chest_pain": ("chest pain", "chest tightness", "chest discomfort", "heart pain", "dor no peito", "dor toracica", "aperto no peito"),
}

_EVA_KEYWORDS = ("eva", "extraveicular", "caminhada espacial", "airlock", "despressurizacao", "depressurization")
_RADIATION_KEYWORDS = ("radiacao", "radiation", "spe", "gcr", "tempestade solar", "solar particle", "dosimetro")


_COMPLAINT_CUES = frozenset(
    {
        "pain", "ache", "aching", "hurt", "hurts", "dizziness", "dizzy",
        "nausea", "nauseous", "queasy", "vision", "sight", "blurry", "blurred",
        "fatigue", "tired", "light", "fever", "tingling", "breath", "breathless",
        "headache", "headaches", "head", "eye", "eyes", "chest", "stomach",
        "belly", "leg", "legs", "back", "discomfort", "burning", "pressure",
        "swelling", "swollen", "weakness", "weak", "insomnia", "photophobia",
        "sickness", "sick", "rash", "vomiting", "cramps",
        "dor", "dores", "tontura", "enjoo", "visao", "vista", "cansaco",
        "fadiga", "luz", "febre", "formigamento", "cabeca", "olho", "olhos",
        "peito", "barriga", "estomago", "perna", "costas", "cefaleia",
    }
)
_GREETING_WORDS = frozenset(
    {
        "hello", "hi", "hey", "greetings", "good", "morning", "afternoon", "evening", "there",
        "ola", "oi", "bom", "dia", "boa", "tarde", "noite", "tudo", "bem",
    }
)
_NON_CLINICAL_STOPWORDS = frozenset(
    {
        "hello", "hi", "hey", "good", "morning", "afternoon", "evening", "there",
        "i", "am", "im", "have", "having", "feel", "feeling", "with", "without",
        "for", "the", "and", "but", "very", "not", "no", "yes", "maybe", "help",
        "need", "today", "now", "how", "are", "you", "what", "this", "that",
        "please", "thanks", "thank", "okay", "sure",
        "ola", "oi", "bom", "boa", "dia", "tarde", "noite", "estou", "tenho",
        "sinto", "sentindo", "com", "sem", "para", "por", "que", "uma", "nao",
        "sim", "bem", "mal", "muito", "pouco", "meio", "aqui", "hoje", "agora",
        "preciso", "ajuda", "dor", "dores",
    }
)


def is_pure_greeting(text: str) -> bool:
    """True only when message has <= 3 words, contains a greeting, and has zero clinical cues."""
    norm = _normalize_text(text)
    if not norm or _match_lexicon(norm):
        return False
    if "falta de ar" in norm or "shortness of breath" in norm:
        return False
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", norm).split() if w]
    if not words or len(words) > 3:
        return False
    if any(w in _COMPLAINT_CUES for w in words):
        return False
    return any(w in _GREETING_WORDS for w in words)


def detect_followup_polarity(text: str) -> Optional[str]:
    """Detect affirmative ('yes'), negative ('no'), or uncertain ('unsure') replies."""
    norm = _normalize_text(text)
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", norm)).strip()
    if not cleaned:
        return None
    # Uncertain replies must never move the posterior: checked before yes/no.
    if cleaned in _UNSURE_ANSWERS or cleaned.startswith(_UNSURE_PREFIXES):
        return "unsure"
    if cleaned in _YES_ANSWERS:
        return "yes"
    if cleaned in _NO_ANSWERS:
        return "no"
    tokens = cleaned.split()
    if len(tokens) > 12:
        return None
    if tokens[0] in {"yes", "yep", "yeah", "sure", "correct", "sim", "positivo", "claro"} or cleaned.startswith(
        ("i think so", "that is right", "thats right", "com certeza", "acho que sim", "esta sim", "tenho sim", "sinto sim")
    ):
        return "yes"
    if tokens[0] in {"no", "nope", "negative", "none", "nothing", "nao", "negativo", "nenhum", "nenhuma", "nada"}:
        return "no"
    return None


@dataclass(frozen=True)
class ExtractedSymptoms:
    """Extracted clinical concepts and context cues from chat text and history."""

    concepts: tuple[str, ...]
    matched_terms: dict[str, list[str]]
    eva_context: bool
    radiation_context: bool
    answered_topics: tuple[str, ...]
    fallback_docs: tuple[ClinicalDocument, ...] = ()
    is_greeting: bool = False


class SymptomExtractor:
    """Maps free-form Portuguese and English chat text to clinical symptom concepts."""

    def __init__(self, *, clinical_store: Optional[ClinicalStore] = None) -> None:
        self.clinical_store = clinical_store

    def extract(
        self,
        text: str,
        *,
        recent_history: Sequence[ChatMessage] | None = None,
        summary_24h: str | None = None,
    ) -> ExtractedSymptoms:
        current_norm = _normalize_text(text)
        pure_greeting = is_pure_greeting(text)

        history_texts: list[str] = []
        if recent_history:
            for msg in recent_history[-6:]:
                if msg.role == "user":
                    history_texts.append(_normalize_text(msg.content))
        if summary_24h:
            history_texts.append(_normalize_text(summary_24h))

        combined = " ".join([current_norm, *history_texts]).strip()

        # Symptoms come from the current message only. History/summary may add symptoms
        # only when the current message is a follow-up answer (e.g. "sim", "sim, está meio embaçada"),
        # so a stale "headache" from earlier turns never leaks into a new complaint.
        matched = _match_lexicon(current_norm)
        polarity = detect_followup_polarity(current_norm)
        if not matched and _is_followup_answer(current_norm):
            matched = _match_lexicon(" ".join(history_texts))
        elif polarity is not None and history_texts:
            hist_matched = _match_lexicon(" ".join(history_texts))
            for k, v in hist_matched.items():
                matched.setdefault(k, list(v))

        fallback_docs: tuple[ClinicalDocument, ...] = ()
        non_negated_norm = _strip_negated_clauses(current_norm)
        if (
            not matched
            and not pure_greeting
            and not _is_followup_answer(current_norm)
            and self.clinical_store is not None
            and non_negated_norm
        ):
            relevant_tokens = [
                tok
                for tok in re.findall(r"[a-z0-9]{3,}", non_negated_norm)
                if tok not in _NON_CLINICAL_STOPWORDS
            ]
            if relevant_tokens:
                try:
                    docs = self.clinical_store.search(" ".join(relevant_tokens), limit=2)
                    fallback_docs = tuple(docs[:2])
                    for doc in fallback_docs:
                        doc_norm = _normalize_text(f"{doc.title} {doc.snippet}")
                        if any(tok in doc_norm for tok in relevant_tokens):
                            for k, v in _match_lexicon(doc_norm).items():
                                matched.setdefault(k, [f"fts5:{doc.doc_id}:{v[0]}"])
                except Exception:
                    fallback_docs = ()

        eva_ctx = any(_phrase_in_text(kw, combined) for kw in _EVA_KEYWORDS)
        rad_ctx = any(_phrase_in_text(kw, combined) for kw in _RADIATION_KEYWORDS)

        answered_topics: list[str] = []
        if any(_phrase_in_text(p, combined) for p in ("amsler", "wavy lines", "blurred vision", "distorted vision", "linhas onduladas", "visao turva")):
            answered_topics.append("amsler_grid")
        if any(_phrase_in_text(p, combined) for p in ("ventilation", "vent", "shortness of breath", "dyspnea", "ventilacao", "falta de ar")):
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
            fallback_docs=fallback_docs,
            is_greeting=pure_greeting,
        )


_YES_ANSWERS = frozenset({"yes", "yep", "yeah", "sure", "correct", "sim", "bastante"})
_NO_ANSWERS = frozenset({"no", "nope", "negative", "none", "nao"})
_UNSURE_ANSWERS = frozenset(
    {
        "maybe", "not sure", "unsure", "perhaps", "a little", "a bit", "somewhat",
        "i dont know", "i don t know", "im not sure", "i m not sure",
        "talvez", "nao sei", "sei la", "nao tenho certeza", "um pouco",
    }
)
_UNSURE_PREFIXES = (
    "not sure",
    "im not sure",
    "i m not sure",
    "maybe",
    "perhaps",
    "a little",
    "a bit",
    "i dont know",
    "i don t know",
    "nao sei",
    "nao tenho certeza",
    "talvez",
    "sei la",
)
_FOLLOWUP_ANSWERS = _YES_ANSWERS | _NO_ANSWERS | _UNSURE_ANSWERS


def _is_followup_answer(norm_text: str) -> bool:
    """True when the message is only a short yes/no style reply to a disambiguation question."""
    cleaned = re.sub(r"[^a-z0-9 ]", " ", norm_text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned in _FOLLOWUP_ANSWERS


# Typo tolerance for single-word terms >= 6 chars. 0.85 catches transpositions such as
# "cefaleai" (ratio 0.875) with no extra hits on 25 common non-clinical probe words.
FUZZY_MIN_RATIO = 0.85
_SYNONYM_CACHE: dict[str, tuple[float, dict[str, tuple[str, ...]]]] = {}


def _default_synonyms_path() -> Path:
    env_p = os.environ.get("EDGESPACE_SYNONYMS_PATH", "").strip()
    if env_p:
        return Path(env_p)
    return Path(__file__).resolve().parents[3] / "models" / "clinical_synonyms.json"


def load_clinical_synonyms(path: Optional[Path] = None) -> dict[str, tuple[str, ...]]:
    """Load expanded bilingual synonyms from ``edge-ai/models/clinical_synonyms.json``."""
    target = path or _default_synonyms_path()
    if not target.is_file():
        return {}
    key = str(target)
    try:
        mtime = target.stat().st_mtime
        cached = _SYNONYM_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        raw = json.loads(target.read_text(encoding="utf-8"))
        syn_raw = raw.get("synonyms") if isinstance(raw, dict) else None
        if not isinstance(syn_raw, dict):
            return {}
        parsed = {
            str(k): tuple(dict.fromkeys(_normalize_text(str(p)) for p in v if str(p).strip()))
            for k, v in syn_raw.items()
            if isinstance(v, list)
        }
        _SYNONYM_CACHE[key] = (mtime, parsed)
        return parsed
    except Exception:
        return {}


_CLAUSE_SPLIT_RE = re.compile(r"(?:[,.;!?]+|\b(?:and|but|however|e|mas|porem)\b)")
_NEGATION_RE = re.compile(
    r"(?:^|\s)(?:"
    r"no(?:\s+(?:sign\s+of|evidence\s+of))?|"
    r"without|not\s+(?:having|feeling|experiencing)|"
    r"don'?t\s+have|do\s+not\s+have|never\s+had|denies|deny|"
    r"nao\s+(?:estou\s+com|estou|tenho|sinto|ha)|sem|nenhum|nenhuma|negativo\s+para"
    r")\s*$"
)


def _strip_negated_clauses(norm_text: str) -> str:
    """Keep only clauses not led by an explicit clinical negation marker."""
    if not norm_text:
        return ""
    kept: list[str] = []
    for clause in _CLAUSE_SPLIT_RE.split(norm_text):
        c = clause.strip()
        if not c:
            continue
        if re.match(
            r"^(?:no\b|without\b|not\s+(?:having|feeling|experiencing)\b|don'?t\s+have\b|do\s+not\s+have\b|never\s+had\b|denies\b|deny\b|"
            r"nao\s+(?:estou\s+com|estou|tenho|sinto|ha)\b|sem\b|nenhum\b|nenhuma\b|negativo\s+para\b)",
            c,
        ):
            continue
        kept.append(c)
    return " ".join(kept)


def _has_positive_match(phrase: str, text: str) -> bool:
    """Return True if ``phrase`` occurs in ``text`` outside a negation prefix."""
    if not phrase or not text:
        return False
    if " " in phrase:
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")
    else:
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")
    for m in pat.finditer(text):
        prefix = text[: m.start()]
        # Inspect only text since the last clause boundary
        last_sep = max(
            (s.end() for s in _CLAUSE_SPLIT_RE.finditer(prefix)),
            default=0,
        )
        local_prefix = prefix[last_sep:]
        if _NEGATION_RE.search(local_prefix):
            continue
        return True
    return False


def _match_lexicon(norm_text: str, *, extra_synonyms: Optional[dict[str, tuple[str, ...]]] = None) -> dict[str, list[str]]:
    """Return lexicon concepts found in already-normalized text. Never invents a default symptom."""
    matched: dict[str, list[str]] = {}
    if not norm_text:
        return matched
    ext_syn = extra_synonyms if extra_synonyms is not None else load_clinical_synonyms()
    for concept, phrases in SYMPTOM_LEXICON.items():
        all_phrases = (*phrases, *ext_syn.get(concept, ()))
        hits = [p for p in all_phrases if _has_positive_match(p, norm_text)]
        if hits:
            matched[concept] = list(dict.fromkeys(hits))

    if not matched:
        pos_text = _strip_negated_clauses(norm_text)
        words = [w for w in re.findall(r"[a-z]{6,}", pos_text) if w not in _NON_CLINICAL_STOPWORDS]
        if words:
            for concept, phrases in SYMPTOM_LEXICON.items():
                single_terms = [p for p in (*phrases, *ext_syn.get(concept, ())) if " " not in p and len(p) >= 6]
                for w in words:
                    for term in single_terms:
                        if abs(len(w) - len(term)) <= 2 and SequenceMatcher(None, w, term).ratio() >= FUZZY_MIN_RATIO:
                            matched.setdefault(concept, []).append(f"fuzzy:{w}->{term}")
                            break
    return matched


def _phrase_in_text(phrase: str, text: str) -> bool:
    if " " in phrase:
        return phrase in text
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None
