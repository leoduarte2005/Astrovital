"""Local SLM conversational synthesizer (llama-cpp-python + GGUF for ARM64)."""

from __future__ import annotations

import concurrent.futures
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..ipc.protocol import ChatCorrelateRespPayload
from ..utils.logging import get_logger
from ..utils.model_fetch import ensure_model

logger = get_logger("edgespace_ai.correlation.synthesizer")

DEFAULT_N_CTX = 1024
DEFAULT_N_THREADS = 2
DEFAULT_N_THREADS_BATCH = 8
DEFAULT_N_BATCH = 512
DEFAULT_TIMEOUT_S: float = 15.0
DEFAULT_MAX_TOKENS = 280
DEFAULT_MIN_FREE_RAM_MB = 512


def _default_timeout_s() -> float:
    raw = os.environ.get("EDGESPACE_SLM_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        val = float(raw)
        return max(0.1, val)
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _default_n_threads() -> int:
    env_val = os.environ.get("EDGESPACE_SLM_THREADS", "").strip()
    if env_val.isdigit() and int(env_val) > 0:
        return int(env_val)
    arch = platform.machine().lower()
    if arch in {"aarch64", "arm64", "armv7l"}:
        return DEFAULT_N_THREADS
    return min(4, os.cpu_count() or DEFAULT_N_THREADS)


SLM_SYSTEM_PROMPT = (
    "You are the NASA onboard Flight Surgeon in the EdgeSpace clinical system. "
    "Respond exclusively in clear, empathetic, natural English without numbered lists or repetitive technical labels. "
    "STRICT RULES: "
    "1) FORBIDDEN to use robotic or repetitive openings such as 'Understood, ...' or 'At this instant telemetry...'. Vary your opening naturally based on conversation intent. "
    "2) Maintain 100% fidelity to real sensor numbers, NASA HRP/CSA hypotheses, countermeasures, and crew memory constraints provided in context; never invent values or alter the diagnosis. "
    "3) If intent is GREETING: reply warmly and briefly (1 to 3 sentences). If there is an active sensor alert, mention it gently and ask if the astronaut feels any discomfort, without dumping a technical report. "
    "4) If intent is HEALTH_CHECKUP: deliver a clear, supportive daily clinical briefing (vital signs and cabin environment); if an alert is active, explain the probable cause and recommended action without starting with 'Understood'. "
    "5) If intent is SYMPTOM_OR_FOLLOWUP: act as an investigative Flight Surgeon in 3 to 5 sentences — acknowledge symptoms, cross-reference live sensors, present the primary hypothesis plus differential, state the immediate countermeasure, and finish with the disambiguation question or self-exam prompt (e.g., Amsler Grid) if provided."
)


def _default_slm_dir(models_dir: Optional[Path | str] = None) -> Path:
    if models_dir is not None:
        return Path(models_dir) / "slm"
    return Path(__file__).resolve().parents[3] / "models" / "slm"


def _read_available_ram_mb() -> Optional[float]:
    """Best-effort available RAM check without mandatory external dependencies."""
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) / 1024.0
        except OSError:
            pass

    try:
        import psutil  # type: ignore[import-untyped]

        return float(psutil.virtual_memory().available) / (1024.0 * 1024.0)
    except Exception:
        return None


def _discover_gguf_model(slm_dir: Path) -> Optional[Path]:
    """Select the preferred quantized GGUF model inside ``slm_dir``."""
    if not slm_dir.is_dir():
        return None
    candidates = sorted(p for p in slm_dir.glob("*.gguf") if p.is_file())
    if not candidates:
        return None

    preferred_tokens = ("edgespace-medical", "qwen2.5-1.5b", "qwen2.5", "llama-3.2-3b", "llama-3.2")
    for token in preferred_tokens:
        for path in candidates:
            if token in path.name.lower():
                return path
    return candidates[0]


def _format_memory_facts(memory_facts: Sequence[Any]) -> list[str]:
    formatted: list[str] = []
    for fact in memory_facts:
        if fact is None:
            continue
        if isinstance(fact, dict):
            fact_type = str(fact.get("type") or fact.get("fact_type") or fact.get("category") or "fact").strip()
            content = str(
                fact.get("content") or fact.get("fact") or fact.get("fact_value") or fact.get("value") or ""
            ).strip()
            if not content:
                content = json.dumps(fact, ensure_ascii=False)
            formatted.append(f"[{fact_type}] {content}")
        else:
            text = str(fact).strip()
            if text:
                formatted.append(text)
    return formatted


class LocalSLMSynthesizer:
    """Offline ARM64 GGUF conversational writer backed by ``llama-cpp-python``."""

    def __init__(
        self,
        *,
        models_dir: Optional[Path | str] = None,
        slm_dir: Optional[Path | str] = None,
        model_path: Optional[Path | str] = None,
        n_ctx: int = DEFAULT_N_CTX,
        n_threads: Optional[int] = None,
        n_threads_batch: int = DEFAULT_N_THREADS_BATCH,
        n_batch: int = DEFAULT_N_BATCH,
        timeout_s: Optional[float] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.35,
        min_free_ram_mb: float = DEFAULT_MIN_FREE_RAM_MB,
        disabled: bool = False,
        auto_download: Optional[bool] = None,
        llm: Any = None,
        llm_factory: Optional[Callable[..., Any]] = None,
        auto_load: bool = True,
    ) -> None:
        self.slm_dir = Path(slm_dir) if slm_dir is not None else _default_slm_dir(models_dir)
        self.model_path: Optional[Path] = Path(model_path) if model_path is not None else None
        self.n_ctx = max(512, int(n_ctx))
        self.n_threads = max(1, int(n_threads if n_threads is not None else _default_n_threads()))
        self.n_threads_batch = max(1, int(n_threads_batch))
        self.n_batch = max(128, int(n_batch))
        resolved_timeout = _default_timeout_s() if timeout_s is None else float(timeout_s)
        self.timeout_s: Optional[float] = (
            max(0.1, resolved_timeout) if (resolved_timeout is not None and resolved_timeout > 0) else None
        )
        self.max_tokens = max(32, int(max_tokens))
        self.temperature = float(temperature)
        self.min_free_ram_mb = float(min_free_ram_mb)
        self.disabled = bool(disabled)
        # Only auto-download when using the default repo model dir unless explicitly opted in.
        self.auto_download = (
            bool(auto_download)
            if auto_download is not None
            else (models_dir is None and slm_dir is None and model_path is None)
        )
        self._llm_factory = llm_factory
        self._llm: Any = llm
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="edgespace-slm",
        )

        if auto_load and not self.disabled and self._llm is None:
            self.load_model()

    @property
    def is_ready(self) -> bool:
        return not self.disabled and self._llm is not None

    def load_model(self) -> bool:
        """Safely initialize the GGUF model at boot with disk cache when available."""
        if self.disabled:
            logger.info("local SLM synthesizer disabled by configuration")
            return False

        if self._llm is not None:
            return True

        resolved_path = self.model_path or _discover_gguf_model(self.slm_dir)
        if (resolved_path is None or not resolved_path.is_file()) and self.auto_download:
            resolved_path = ensure_model(self.slm_dir)
        if resolved_path is None or not resolved_path.is_file():
            logger.info(
                "SLM GGUF model not found; deterministic template fallback active",
                extra={"slm_dir": str(self.slm_dir)},
            )
            return False
        self.model_path = resolved_path

        avail_ram_mb = _read_available_ram_mb()
        if avail_ram_mb is not None and avail_ram_mb < self.min_free_ram_mb:
            logger.warning(
                "insufficient free RAM for SLM boot; deterministic fallback active",
                extra={"avail_ram_mb": round(avail_ram_mb, 1), "min_free_ram_mb": self.min_free_ram_mb},
            )
            return False

        try:
            cache_dir = self.slm_dir / ".cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("could not create SLM cache dir", extra={"err": str(exc)})
            cache_dir = None

        try:
            if self._llm_factory is not None:
                self._llm = self._llm_factory(
                    model_path=str(resolved_path),
                    n_ctx=self.n_ctx,
                    n_threads=self.n_threads,
                    cache_dir=str(cache_dir) if cache_dir is not None else None,
                )
            else:
                from llama_cpp import Llama  # type: ignore[import-not-found]

                self._llm = Llama(
                    model_path=str(resolved_path),
                    n_ctx=self.n_ctx,
                    n_threads=self.n_threads,
                    n_threads_batch=self.n_threads_batch,
                    n_batch=self.n_batch,
                    use_mmap=True,
                    use_mlock=False,
                    verbose=False,
                )

                # Warmup system-prompt KV prefix once at boot in native C++ context
                if hasattr(self._llm, "create_chat_completion"):
                    self._llm.create_chat_completion(
                        messages=[
                            {"role": "system", "content": SLM_SYSTEM_PROMPT},
                            {"role": "user", "content": "OK"},
                        ],
                        max_tokens=1,
                        temperature=0.0,
                    )

            logger.info(
                "local SLM loaded",
                extra={
                    "model_path": str(resolved_path),
                    "n_ctx": self.n_ctx,
                    "n_threads": self.n_threads,
                },
            )
            return True
        except Exception as exc:
            logger.warning(
                "failed to initialize local SLM; using deterministic fallback",
                extra={"model_path": str(resolved_path), "err": str(exc)},
            )
            self._llm = None
            return False

    @staticmethod
    def _infer_intent(correlate_resp: ChatCorrelateRespPayload, intent: Optional[str] = None) -> str:
        if intent in ("GREETING", "HEALTH_CHECKUP", "SYMPTOM_OR_FOLLOWUP"):
            return intent
        txt = (correlate_resp.text or "").strip().lower()
        has_symptoms = any(
            e.startswith(("Detected symptoms:", "Sintomas detectados:"))
            for e in (correlate_resp.evidence or [])
        )
        if "health briefing" in txt or "vital signs briefing" in txt or "health check" in txt:
            return "HEALTH_CHECKUP"
        if (
            not has_symptoms
            and not correlate_resp.disambiguation_question
            and txt.startswith(("hello,", "hi,", "good morning", "good afternoon", "good evening"))
            and ("everything looks steady" in txt or "good to hear from you" in txt)
        ):
            return "GREETING"
        return "SYMPTOM_OR_FOLLOWUP"

    def build_messages(
        self,
        correlate_resp: ChatCorrelateRespPayload,
        memory_facts: Sequence[Any],
        sensor_snapshot: dict[str, Any],
        *,
        intent: Optional[str] = None,
        user_text: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Assemble chat messages injecting intent, causal context, sensors, and crew memory."""
        resolved_intent = self._infer_intent(correlate_resp, intent)
        facts_list = _format_memory_facts(memory_facts)
        countermeasures = [c.strip() for c in (correlate_resp.countermeasures or [])[:2] if c.strip()]
        sensor_str = json.dumps(sensor_snapshot or {}, ensure_ascii=False, separators=(",", ":"))
        symptom_evidence = [
            e
            for e in (correlate_resp.evidence or [])
            if e.startswith(("Detected symptoms:", "Sintomas detectados:"))
        ]
        breach_evidence = [
            e
            for e in (correlate_resp.evidence or [])
            if e.startswith(("Threshold exceeded:", "Limite ultrapassado:"))
        ]
        sensor_evidence = [
            e
            for e in (correlate_resp.evidence or [])
            if e.startswith(("Sensor ", "CSI vitals:", "Threshold exceeded:", "Limite ultrapassado:"))
        ]

        parts: list[str] = [f"Conversation intent: {resolved_intent}."]
        if user_text:
            parts.append(f"Astronaut message: {user_text.strip()}")

        if resolved_intent == "GREETING":
            parts.append(f"Current readings summary: {sensor_str}")
            if breach_evidence:
                parts.append("Active sensor alerts: " + "; ".join(breach_evidence))
            else:
                parts.append("Active sensor alerts: none (all parameters nominal).")
            parts.append(
                "Instruction: reply in English with a warm, natural greeting (1 to 3 sentences). "
                "If there is an active sensor alert, mention it briefly and ask if the crew member feels any discomfort, without dumping a technical report."
            )
            return [
                {"role": "system", "content": SLM_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(parts)},
            ]

        parts.append(
            f"Clinical escalation: {correlate_resp.escalation.value} | "
            f"Reference draft (DO NOT copy the opening verbatim): {correlate_resp.text.strip()}"
        )
        if symptom_evidence:
            parts.append("Reported complaints/symptoms: " + "; ".join(symptom_evidence))
        if correlate_resp.differentials:
            parts.append("Ranked hypotheses: " + "; ".join(correlate_resp.differentials[:3]))
        if correlate_resp.source_ids:
            parts.append("NASA/CSA sources: " + ", ".join(correlate_resp.source_ids[:3]))
        parts.append(
            f"Live sensor readings: {sensor_str}"
            + (f" | Evidence: {'; '.join(sensor_evidence)}" if sensor_evidence else ".")
        )
        parts.append("Crew memory: " + ("; ".join(facts_list) if facts_list else "no additional alerts."))
        if countermeasures:
            parts.append("Approved immediate countermeasures: " + " ".join(countermeasures))
        if correlate_resp.actions:
            parts.append("Recommended actions: " + ", ".join(correlate_resp.actions))
        if correlate_resp.blocked_actions:
            parts.append("Safety-blocked actions: " + ", ".join(correlate_resp.blocked_actions))
        if correlate_resp.disambiguation_question:
            parts.append(f"Disambiguation / self-exam question: {correlate_resp.disambiguation_question.strip()}")

        if resolved_intent == "HEALTH_CHECKUP":
            parts.append(
                "Instruction: respond in English with a clear, supportive daily clinical briefing (vital signs and cabin environment). "
                "If there is an active alert, explain the probable cause and recommended action. Do not start with 'Understood'."
            )
        else:
            parts.append(
                "Instruction: respond in English as an investigative Flight Surgeon in 3 to 5 varied, natural sentences "
                "(no repetitive openings), keeping all numbers and countermeasures exact."
            )

        return [
            {"role": "system", "content": SLM_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(parts)},
        ]

    def synthesize_response(
        self,
        correlate_resp: ChatCorrelateRespPayload,
        memory_facts: list[Any],
        sensor_snapshot: dict[str, Any],
        *,
        intent: Optional[str] = None,
        user_text: Optional[str] = None,
    ) -> str:
        """Generate natural onboard response or degrade gracefully to deterministic text."""
        resolved_intent = self._infer_intent(correlate_resp, intent)
        fallback_text = correlate_resp.text
        if not self.is_ready:
            return fallback_text

        avail_ram_mb = _read_available_ram_mb()
        if avail_ram_mb is not None and avail_ram_mb < (self.min_free_ram_mb * 0.5):
            logger.warning(
                "low RAM during SLM inference; falling back to deterministic text",
                extra={"avail_ram_mb": round(avail_ram_mb, 1)},
            )
            return fallback_text

        messages = self.build_messages(
            correlate_resp,
            memory_facts,
            sensor_snapshot,
            intent=resolved_intent,
            user_text=user_text,
        )
        started = time.perf_counter()

        future = self._executor.submit(self._run_inference, messages)
        try:
            raw_text = future.result(timeout=self.timeout_s)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.warning(
                "SLM inference exceeded latency budget; deterministic fallback used",
                extra={"timeout_s": self.timeout_s},
            )
            return fallback_text
        except Exception as exc:
            logger.warning(
                "SLM inference failed; deterministic fallback used",
                extra={"err": str(exc)},
            )
            return fallback_text

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cleaned = self._clean_output(raw_text)
        if not cleaned:
            logger.warning("SLM produced empty output; deterministic fallback used")
            return fallback_text
        if self._looks_like_empty_greeting(cleaned, correlate_resp, intent=resolved_intent):
            logger.warning("SLM produced generic greeting despite clinical context; deterministic fallback used")
            return fallback_text

        logger.debug("SLM synthesis completed", extra={"elapsed_ms": round(elapsed_ms, 1)})
        return cleaned

    def _run_inference(self, messages: list[dict[str, str]]) -> str:
        llm = self._llm
        if llm is None:
            return ""

        if hasattr(llm, "create_chat_completion"):
            result = llm.create_chat_completion(
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=0.9,
                repeat_penalty=1.15,
            )
            if isinstance(result, dict):
                choices = result.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                        return msg["content"]
                    if isinstance(choices[0].get("text"), str):
                        return choices[0]["text"]
            elif isinstance(result, str):
                return result
            return ""

        if callable(llm):
            prompt = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages) + "\n\n[ASSISTANT]\n"
            result = llm(prompt, max_tokens=self.max_tokens, temperature=self.temperature)
            if isinstance(result, dict):
                choices = result.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    return str(choices[0].get("text") or "")
            elif isinstance(result, str):
                return result

        return ""

    @staticmethod
    def _looks_like_empty_greeting(
        text: str,
        correlate_resp: ChatCorrelateRespPayload,
        *,
        intent: Optional[str] = None,
    ) -> bool:
        has_breach = any(
            e.startswith(("Threshold exceeded:", "Limite ultrapassado:"))
            for e in (correlate_resp.evidence or [])
        )
        has_symptoms = any(
            e.startswith(("Detected symptoms:", "Sintomas detectados:"))
            for e in (correlate_resp.evidence or [])
        )
        low = text.lower()
        if intent == "GREETING":
            if not has_breach:
                return False
            alert_cues = ("co2", "spo2", "alert", "elevated", "ppm", "low", "reduced", "cabin", "discomfort")
            return not any(cue in low for cue in alert_cues) and len(low) < 160

        has_clinical_ctx = bool(correlate_resp.differentials) or has_symptoms or has_breach
        if not has_clinical_ctx:
            return False
        generic_cues = (
            "how are you feeling",
            "how are you doing",
            "how can i help",
            "what can i help",
            "como está se sentindo",
            "como esta se sentindo",
            "como você está",
            "como voce esta",
            "em que posso ajudar",
            "como posso ajudar",
        )
        return any(cue in low for cue in generic_cues) and len(low) < 160

    @staticmethod
    def _clean_output(text: str) -> str:
        if not isinstance(text, str):
            return ""
        cleaned = text.strip()
        for prefix in ("[ASSISTANT]", "ASSISTANT:", "Flight Surgeon:"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
        return cleaned

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
