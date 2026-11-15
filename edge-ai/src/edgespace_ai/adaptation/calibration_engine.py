"""Incremental EMA calibration engine persisting per-crew baselines to JSON."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..dsp.feature_extractor import FEATURE_DIM
from ..utils.logging import get_logger
from .baseline_registry import BaselineRegistry, CrewBaseline, make_default_baseline

logger = get_logger("edgespace_ai.adaptation.calibration_engine")


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

        updated = CrewBaseline(
            crew_id=crew_id,
            mean=new_mean,
            std=new_std,
            threshold=new_threshold,
            sample_count=n_prev + 1,
            updated_at_us=time.time_ns() // 1000,
            model_path=current.model_path,
        )
        self.registry.update_baseline(updated)

        if persist:
            self._persist_baseline(updated)

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
    ) -> CalibrationResult:
        """Process one CALIBRATION_STEP command, updating EMA baseline and saving JSON."""
        count = self._step_counts.get(crew_id, 0) + 1
        self._step_counts[crew_id] = count

        action_lower = action.lower()
        if "reset" in action_lower:
            self._step_counts[crew_id] = 0
            baseline = make_default_baseline(crew_id)
            self.registry.update_baseline(baseline)
            self._persist_baseline(baseline)
            return CalibrationResult(step_id=step_id, progress=0, quality=1.0, baseline=baseline)

        if latest_features is not None:
            baseline = self.apply_sample(
                crew_id,
                latest_features,
                anomaly_score=latest_anomaly_score,
                persist=True,
            )
            quality = float(np.clip(link_quality, 0.1, 1.0))
        else:
            baseline = self.registry.get(crew_id) or make_default_baseline(crew_id)
            self._persist_baseline(baseline)
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

    def _persist_baseline(self, baseline: CrewBaseline) -> Optional[Path]:
        if self.registry.db_path is not None:
            return None  # persisted by the Central through CALIBRATION_FEEDBACK
        path = self.registry.profile_path(baseline.crew_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(baseline.to_dict(), indent=2, ensure_ascii=False)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
        return path
