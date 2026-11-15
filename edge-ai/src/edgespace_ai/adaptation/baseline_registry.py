"""Thread-safe LRU registry for per-crew baselines backed by SQLite."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..dsp.feature_extractor import FEATURE_DIM
from ..clinical import ClinicalRepository
from ..utils.logging import get_logger

logger = get_logger("edgespace_ai.adaptation.baseline_registry")

DEFAULT_ANOMALY_THRESHOLD = 0.75

CALIBRATION_STATUS_READY = "READY"
CALIBRATION_STATUS_SYNTHETIC_SEED = "SYNTHETIC_SEED"
CALIBRATION_STATUS_CALIBRATING = "CALIBRATING"
CALIBRATION_STATUS_REQUIRED = "REQUIRES_CALIBRATION"


def is_calibrated(status: Optional[str], sample_count: Optional[int], baseline_path: Optional[str]) -> bool:
    """Single calibration rule mirrored from central/internal/store/reader.go:IsCalibrated.

    - READY with samples is calibrated;
    - SYNTHETIC_SEED with samples is calibrated only when the crew has a baseline_path;
    - anything else requires calibration.
    """
    if not sample_count or int(sample_count) <= 0:
        return False
    if status == CALIBRATION_STATUS_READY:
        return True
    if status == CALIBRATION_STATUS_SYNTHETIC_SEED:
        return bool(baseline_path and str(baseline_path).strip())
    return False


@dataclass(frozen=True)
class CrewBaseline:
    """Immutable snapshot of a crew member's baseline normalization and anomaly threshold."""

    crew_id: str
    mean: np.ndarray          # shape (64,), float32
    std: np.ndarray           # shape (64,), float32
    threshold: float
    sample_count: int = 0
    updated_at_us: int = 0
    model_path: Optional[str] = None
    per_posture_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    def normalize(self, features: np.ndarray, posture: Optional[str] = None) -> np.ndarray:
        """Z-score normalize a 1D (64,) or 2D (N, 64) feature vector, using posture stats if present."""
        mean_vec = self.mean
        std_vec = self.std
        canon = {"exercising": "exercise", "seated": "sitting"}.get(posture.strip().lower(), posture.strip().lower()) if posture else None
        if canon and canon in self.per_posture_stats:
            pstats = self.per_posture_stats[canon]
            if isinstance(pstats, dict) and "mean" in pstats and "std" in pstats:
                p_mean = np.asarray(pstats["mean"], dtype=np.float32)
                p_std = np.asarray(pstats["std"], dtype=np.float32)
                if p_mean.shape == (FEATURE_DIM,) and p_std.shape == (FEATURE_DIM,):
                    mean_vec = p_mean
                    std_vec = p_std
        safe_std = np.where(std_vec > 1e-4, std_vec, 1.0).astype(np.float32)
        return ((np.asarray(features, dtype=np.float32) - mean_vec) / safe_std).astype(np.float32)

    def normalize_vital(self, metric: str, value: float, posture: Optional[str] = None) -> Optional[float]:
        """Z-score normalize a scalar vital reading against per_posture_stats_json."""
        if not posture or posture not in self.per_posture_stats:
            return None
        pstats = self.per_posture_stats[posture]
        if not isinstance(pstats, dict):
            return None
        prefix_map = {
            "heart_rate_bpm": "hr",
            "hr": "hr",
            "hrv_ms": "hrv",
            "hrv": "hrv",
            "resp_rate_bpm": "resp",
            "respiration_hz": "resp",
            "resp": "resp",
            "spo2_pct": "spo2",
            "spo2": "spo2",
        }
        prefix = prefix_map.get(metric, metric)
        m = pstats.get(f"{prefix}_mean")
        if m is None:
            return None
        s = pstats.get(f"{prefix}_std")
        denom = float(s) if (s is not None and float(s) > 1e-4) else 1.0
        return (float(value) - float(m)) / denom

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "crew_id": self.crew_id,
            "mean": [float(v) for v in self.mean.tolist()],
            "std": [float(v) for v in self.std.tolist()],
            "threshold": float(self.threshold),
            "sample_count": int(self.sample_count),
            "updated_at_us": int(self.updated_at_us),
            "model_path": self.model_path,
        }
        if self.per_posture_stats:
            out["per_posture_stats"] = self.per_posture_stats
        return out

    @classmethod
    def from_dict(cls, data: dict[str, object], fallback_crew_id: str = "default") -> "CrewBaseline":
        mean_raw = np.asarray(data.get("mean", np.zeros(FEATURE_DIM)), dtype=np.float32)
        std_raw = np.asarray(data.get("std", np.ones(FEATURE_DIM)), dtype=np.float32)
        if mean_raw.shape != (FEATURE_DIM,):
            raise ValueError("Expected 64 baseline mean features")
        if std_raw.shape != (FEATURE_DIM,):
            raise ValueError("Expected 64 baseline std features")
        if not np.all(np.isfinite(mean_raw)) or not np.all(np.isfinite(std_raw)) or np.any(std_raw<=0):
            raise ValueError("Baseline must be finite with positive std")

        pps_raw = data.get("per_posture_stats")
        pps = dict(pps_raw) if isinstance(pps_raw, dict) else {}

        return cls(
            crew_id=str(data.get("crew_id") or fallback_crew_id),
            mean=mean_raw,
            std=std_raw,
            threshold=float(data.get("threshold", DEFAULT_ANOMALY_THRESHOLD)),
            sample_count=int(data.get("sample_count", 0)),
            updated_at_us=int(data.get("updated_at_us", 0)),
            model_path=str(data["model_path"]) if data.get("model_path") else None,
            per_posture_stats=pps,
        )


def make_default_baseline(crew_id: str = "default") -> CrewBaseline:
    """Create a neutral baseline when no calibrated profile exists yet."""
    return CrewBaseline(
        crew_id=crew_id,
        mean=np.zeros(FEATURE_DIM, dtype=np.float32),
        std=np.ones(FEATURE_DIM, dtype=np.float32),
        threshold=DEFAULT_ANOMALY_THRESHOLD,
        sample_count=0,
        updated_at_us=time.time_ns() // 1000,
    )


class BaselineRegistry:
    """Thread-safe LRU cache of per-crew baselines backed by SQLite."""

    def __init__(
        self,
        models_dir: Path | str = Path("./models"),
        *,
        max_entries: int = 16,
        db_path: Optional[Path | str] = None,
    ) -> None:
        if db_path is None:
            raise ValueError("db_path is required for BaselineRegistry")
        self.db_path = Path(db_path)
        self._readiness: dict[str, bool] = {}
        self.models_dir = Path(models_dir)
        self.max_entries = max(1, max_entries)

        self._lock = threading.RLock()
        self._cache: OrderedDict[str, CrewBaseline] = OrderedDict()
        self._active_crew_id: Optional[str] = None
        self._active_baseline: CrewBaseline = make_default_baseline("uncalibrated")
        self.last_switch_ms: float = 0.0

    def active_crew_id(self) -> Optional[str]:
        with self._lock:
            return self._active_crew_id

    def active_baseline(self) -> CrewBaseline:
        with self._lock:
            return self._active_baseline

    def get(self, crew_id: str) -> Optional[CrewBaseline]:
        """Return cached baseline or load from SQLite if present."""
        with self._lock:
            if crew_id in self._cache:
                self._cache.move_to_end(crew_id)
                return self._cache[crew_id]

        loaded = self._load_from_database(crew_id)
        if loaded is not None:
            with self._lock:
                self._put_lru(crew_id, loaded)
        return loaded

    def set_active_crew(
        self,
        crew_id: str,
        baseline_path: Optional[str] = None,
    ) -> tuple[CrewBaseline, bool]:
        """Atomically switch active crew baseline (< 300 ms target).

        Returns ``(baseline, baseline_found)`` where ``baseline_found`` follows
        :func:`is_calibrated`. ``baseline_path`` (from SET_ACTIVE_CREW) overrides
        the DB ``model_path`` when provided so Central and Edge AI agree.
        """
        t0 = time.perf_counter()
        loaded = self._load_from_database(crew_id, baseline_path=baseline_path)
        if loaded is None:
            loaded = make_default_baseline(crew_id)
            self._readiness[crew_id] = False
        with self._lock:
            self._put_lru(crew_id, loaded)
            self._active_crew_id = crew_id
            self._active_baseline = loaded
            self.last_switch_ms = (time.perf_counter() - t0) * 1000.0
        found = self._readiness.get(crew_id, False)
        logger.info(
            "active baseline switched",
            extra={
                "crew_id": crew_id,
                "baseline_found": found,
                "sample_count": loaded.sample_count,
                "switch_ms": round(self.last_switch_ms, 3),
            },
        )
        return loaded, found

    def is_ready(self, crew_id: str) -> bool:
        """Return the last computed calibration readiness for ``crew_id``."""
        return self._readiness.get(crew_id, False)

    def update_baseline(self, baseline: CrewBaseline) -> None:
        """Insert or update a crew baseline in the LRU cache and active slot."""
        with self._lock:
            self._put_lru(baseline.crew_id, baseline)
            if self._active_crew_id == baseline.crew_id:
                self._active_baseline = baseline

    def _put_lru(self, crew_id: str, baseline: CrewBaseline) -> None:
        self._cache[crew_id] = baseline
        self._cache.move_to_end(crew_id)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)

    def _load_from_database(
        self,
        crew_id: str,
        *,
        baseline_path: Optional[str] = None,
    ) -> Optional[CrewBaseline]:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"SQLite baseline database not found: {self.db_path}")
        with ClinicalRepository(self.db_path) as repo:
            try:
                row = repo.baseline(crew_id)
            except KeyError:
                self._readiness[crew_id] = False
                return None
            effective_path = baseline_path
            if not effective_path:
                effective_path = row.get("onnx_model_path")
            if not effective_path:
                try:
                    effective_path = repo.crew(crew_id).get("baseline_path")
                except KeyError:
                    effective_path = None
        if row.get("feature_schema_id") != "EDGESPACE_DSP64_V1":
            raise ValueError("Unsupported baseline feature schema; calibration required")
        sample_count = int(row.get("sample_count") or 0)
        self._readiness[crew_id] = is_calibrated(row.get("calibration_status"), sample_count, effective_path)
        return CrewBaseline.from_dict(
            dict(
                crew_id=crew_id,
                mean=row["mean"],
                std=row["std"],
                threshold=row["anomaly_threshold"],
                # sample_count is preserved as persisted (incl. SYNTHETIC_SEED) so EMA
                # calibration continues from the stored statistics instead of resetting.
                sample_count=sample_count,
                updated_at_us=row["updated_at_us"],
                model_path=row.get("onnx_model_path"),
                per_posture_stats=row.get("per_posture_stats") or {},
            )
        )
