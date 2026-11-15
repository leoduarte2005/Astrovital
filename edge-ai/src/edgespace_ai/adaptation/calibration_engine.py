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


def _infer_posture(action: str, posture: Optional[str] = None) -> Optional[str]:
    if posture:
        return posture.strip().lower()
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

    def apply_sample(
        self,
        crew_id: str,
        features: np.ndarray,
        *,
        anomaly_score: Optional[float] = None,
        posture: Optional[str] = None,
        persist: bool = True,
    ) -> CrewBaseline:
        """Update crew baseline statistics with one 64-feature observation using EMA."""
        vec = np.asarray(features, dtype=np.float32)
        if vec.shape != (FEATURE_DIM,):
            raise ValueError("Calibration requires 64 features")
        if not np.all(np.isfinite(vec)):
            raise ValueError("Missing or invalid calibration features are not zero")

        current = self.registry.get(crew_id) or make_default_baseline(crew_id)
        n_prev = current.sample_count

        if n_prev == 0:
            new_mean = vec.copy()
            new_std = np.maximum(np.abs(vec) * 0.1, self.min_std).astype(np.float32)
            new_threshold = current.threshold
        else:
            alpha = self.ema_alpha
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
                alpha = self.ema_alpha
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
