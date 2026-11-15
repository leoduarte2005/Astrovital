"""Incremental EMA calibration engine updating per-crew and per-posture baselines."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..dsp.feature_extractor import FEATURE_DIM
from ..utils.logging import get_logger
from .baseline_registry import BaselineRegistry, CrewBaseline, make_default_baseline

logger = get_logger("edgespace_ai.adaptation.calibration_engine")

_KNOWN_POSTURES = ("supine", "sitting", "standing", "exercise", "prone")
# Online (clean-session) adaptation: slow EMA, frozen threshold, immutable anchor.
ONLINE_EMA_ALPHA = 0.02
ONLINE_MIN_INTERVAL_S = 60.0
ONLINE_MIN_LINK_QUALITY = 0.8
ONLINE_ANOMALY_FRACTION = 0.5
ONLINE_MAX_ANCHOR_DRIFT = 3.0
_POSTURE_ALIASES = {"exercising": "exercise", "exercise": "exercise", "seated": "sitting"}


def canonical_posture(posture: Optional[str]) -> Optional[str]:
    """Map DSP posture labels (e.g. ``exercising``) to the per_posture_stats keys (``exercise``)."""
    if not posture:
        return None
    low = posture.strip().lower()
    if low in ("", "unknown"):
        return None
    return _POSTURE_ALIASES.get(low, low)


def _infer_posture(action: str, posture: Optional[str] = None) -> Optional[str]:
    if posture:
        return canonical_posture(posture)
    low = action.lower()
    for p in _KNOWN_POSTURES:
        if p in low:
            return p
    return None


@dataclass(frozen=True)
class CalibrationResult:
    """Result returned for a single CALIBRATION_STEP."""

    step_id: str
    progress: int
    quality: float
    baseline: CrewBaseline


class CalibrationEngine:
    """Incrementally adapts a crew member's baseline via EMA and persists to JSON."""

    def __init__(
        self,
        registry: BaselineRegistry,
        *,
        ema_alpha: float = 0.25,
        min_std: float = 1e-3,
        target_steps: int = 3,
    ) -> None:
        if getattr(registry, "db_path", None) is None:
            raise ValueError("BaselineRegistry with db_path is required for CalibrationEngine")
        self.registry = registry
        self.ema_alpha = float(np.clip(ema_alpha, 0.01, 1.0))
        self.min_std = float(max(1e-5, min_std))
        self.target_steps = max(1, target_steps)
        self._step_counts: dict[str, int] = {}
        self._anchors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._last_online_s: dict[str, float] = {}

    def anchor_drift(self, crew_id: str) -> Optional[float]:
        """Mean |z| distance of the current baseline mean from the immutable session anchor."""
        anchor = self._anchors.get(crew_id)
        current = self.registry.get(crew_id)
        if anchor is None or current is None:
            return None
        a_mean, a_std = anchor
        safe = np.where(a_std > 1e-4, a_std, 1.0)
        return float(np.mean(np.abs((current.mean - a_mean) / safe)))

    def apply_clean_sample(
        self,
        crew_id: str,
        features: Optional[np.ndarray],
        *,
        anomaly_score: Optional[float],
        link_quality: float = 1.0,
        posture: Optional[str] = None,
        symptomatic: bool = False,
        now_s: Optional[float] = None,
    ) -> Optional[CrewBaseline]:
        """Slow EMA update during clean sessions only; returns None when any gate rejects the sample.

        Gates: calibrated baseline, known posture, finite 64-d vector, no recent symptoms, link quality,
        anomaly well below the (frozen) threshold, rate limit, and bounded drift from the anchor.
        The anomaly threshold is never modified here, so slow pathologies cannot raise it.
        """
        if features is None or anomaly_score is None or symptomatic:
            return None
        canon = canonical_posture(posture)
        if canon is None or link_quality < ONLINE_MIN_LINK_QUALITY:
            return None
        vec = np.asarray(features, dtype=np.float32)
        if vec.shape != (FEATURE_DIM,) or not np.all(np.isfinite(vec)):
            return None
        if not self.registry.is_ready(crew_id):
            return None
        current = self.registry.get(crew_id)
        if current is None or current.sample_count <= 0:
            return None
        if not np.isfinite(anomaly_score) or anomaly_score >= ONLINE_ANOMALY_FRACTION * current.threshold:
            return None
        ts = time.monotonic() if now_s is None else now_s
        last = self._last_online_s.get(crew_id)
        if last is not None and (ts - last) < ONLINE_MIN_INTERVAL_S:
            return None
        drift = self.anchor_drift(crew_id)
        if drift is not None and drift > ONLINE_MAX_ANCHOR_DRIFT:
            return None
        self._last_online_s[crew_id] = ts
        # anomaly_score=None keeps the threshold frozen.
        return self.apply_sample(
            crew_id, vec, anomaly_score=None, posture=canon, persist=False, alpha=ONLINE_EMA_ALPHA
        )

    def apply_sample(
        self,
        crew_id: str,
        features: np.ndarray,
        *,
        anomaly_score: Optional[float] = None,
        posture: Optional[str] = None,
        persist: bool = True,
        alpha: Optional[float] = None,
    ) -> CrewBaseline:
        """Update crew baseline statistics with one 64-feature observation using EMA."""
        posture = canonical_posture(posture)
        ema_alpha = float(np.clip(alpha, 0.001, 1.0)) if alpha is not None else self.ema_alpha
        vec = np.asarray(features, dtype=np.float32)
        if vec.shape != (FEATURE_DIM,):
            raise ValueError("Calibration requires 64 features")
        if not np.all(np.isfinite(vec)):
            raise ValueError("Missing or invalid calibration features are not zero")

        current = self.registry.get(crew_id) or make_default_baseline(crew_id)
        n_prev = current.sample_count
        if n_prev > 0 and crew_id not in self._anchors:
            # Immutable reference captured before the first adaptive update of this session.
            self._anchors[crew_id] = (current.mean.copy(), current.std.copy())

        if n_prev == 0:
            new_mean = vec.copy()
            new_std = np.maximum(np.abs(vec) * 0.1, self.min_std).astype(np.float32)
            new_threshold = current.threshold
        else:
            alpha = ema_alpha
            diff = vec - current.mean
            new_mean = ((1.0 - alpha) * current.mean + alpha * vec).astype(np.float32)
            prev_var = np.square(current.std.astype(np.float64))
            new_var = (1.0 - alpha) * prev_var + alpha * np.square(diff.astype(np.float64))
            new_std = np.maximum(np.sqrt(new_var), self.min_std).astype(np.float32)
            if anomaly_score is not None and np.isfinite(anomaly_score):
                target_th = float(np.clip(anomaly_score * 1.35 + 0.15, 0.45, 0.95))
                new_threshold = float((1.0 - alpha) * current.threshold + alpha * target_th)
            else:
                new_threshold = current.threshold

        new_pps = {k: dict(v) for k, v in current.per_posture_stats.items()}
        if posture:
            pstats = dict(new_pps.get(posture) or {})
            p_n = int(pstats.get("sample_count", 0))
            if p_n == 0 or "mean" not in pstats or "std" not in pstats:
                p_mean = vec.copy()
                p_std = np.maximum(np.abs(vec) * 0.1, self.min_std).astype(np.float32)
            else:
                alpha = ema_alpha
                prev_pm = np.asarray(pstats["mean"], dtype=np.float32)
                prev_ps = np.asarray(pstats["std"], dtype=np.float32)
                p_diff = vec - prev_pm
                p_mean = ((1.0 - alpha) * prev_pm + alpha * vec).astype(np.float32)
                p_var = (1.0 - alpha) * np.square(prev_ps.astype(np.float64)) + alpha * np.square(p_diff.astype(np.float64))
                p_std = np.maximum(np.sqrt(p_var), self.min_std).astype(np.float32)
            pstats["sample_count"] = p_n + 1
            pstats["mean"] = [float(v) for v in p_mean.tolist()]
            pstats["std"] = [float(v) for v in p_std.tolist()]
            new_pps[posture] = pstats

        updated = CrewBaseline(
            crew_id=crew_id,
            mean=new_mean,
            std=new_std,
            threshold=new_threshold,
            sample_count=n_prev + 1,
            updated_at_us=time.time_ns() // 1000,
            model_path=current.model_path,
            per_posture_stats=new_pps,
        )
        self.registry.update_baseline(updated)
        return updated

    def process_step(
        self,
        *,
        crew_id: str,
        step_id: str,
        action: str,
        latest_features: Optional[np.ndarray],
        latest_anomaly_score: Optional[float] = None,
        link_quality: float = 1.0,
        posture: Optional[str] = None,
    ) -> CalibrationResult:
        """Process one CALIBRATION_STEP command, updating EMA baseline in memory for Central persistence."""
        count = self._step_counts.get(crew_id, 0) + 1
        self._step_counts[crew_id] = count

        action_lower = action.lower()
        if "reset" in action_lower:
            self._step_counts[crew_id] = 0
            baseline = make_default_baseline(crew_id)
            self.registry.update_baseline(baseline)
            return CalibrationResult(step_id=step_id, progress=0, quality=1.0, baseline=baseline)

        inferred_posture = _infer_posture(action, posture)
        if latest_features is not None:
            baseline = self.apply_sample(
                crew_id,
                latest_features,
                anomaly_score=latest_anomaly_score,
                posture=inferred_posture,
                persist=False,
            )
            quality = float(np.clip(link_quality, 0.1, 1.0))
        else:
            baseline = self.registry.get(crew_id) or make_default_baseline(crew_id)
            quality = float(np.clip(link_quality * 0.85, 0.1, 1.0))

        if "complete" in action_lower or "finish" in action_lower:
            progress = 100
        else:
            progress = min(100, int(round((count / float(self.target_steps)) * 100.0)))

        logger.info(
            "calibration step applied",
            extra={
                "crew_id": crew_id,
                "step_id": step_id,
                "action": action,
                "progress": progress,
                "sample_count": baseline.sample_count,
            },
        )
        return CalibrationResult(
            step_id=step_id,
            progress=progress,
            quality=quality,
            baseline=baseline,
        )
