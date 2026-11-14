"""Thread-safe LRU registry for per-crew baseline statistics and atomic crew switching."""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..dsp.feature_extractor import FEATURE_DIM
from ..utils.logging import get_logger

logger = get_logger("edgespace_ai.adaptation.baseline_registry")

DEFAULT_ANOMALY_THRESHOLD = 0.75


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

    def normalize(self, features: np.ndarray) -> np.ndarray:
        """Z-score normalize a 1D (64,) or 2D (N, 64) feature vector using baseline stats."""
        safe_std = np.where(self.std > 1e-4, self.std, 1.0).astype(np.float32)
        return ((np.asarray(features, dtype=np.float32) - self.mean) / safe_std).astype(np.float32)

    def to_dict(self) -> dict[str, object]:
        return {
            "crew_id": self.crew_id,
            "mean": [float(v) for v in self.mean.tolist()],
            "std": [float(v) for v in self.std.tolist()],
            "threshold": float(self.threshold),
            "sample_count": int(self.sample_count),
            "updated_at_us": int(self.updated_at_us),
            "model_path": self.model_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object], fallback_crew_id: str = "default") -> "CrewBaseline":
        mean_raw = np.asarray(data.get("mean", np.zeros(FEATURE_DIM)), dtype=np.float32)
        std_raw = np.asarray(data.get("std", np.ones(FEATURE_DIM)), dtype=np.float32)
        if mean_raw.shape != (FEATURE_DIM,):
            mean_raw = np.resize(mean_raw, FEATURE_DIM).astype(np.float32)
        if std_raw.shape != (FEATURE_DIM,):
            std_raw = np.resize(std_raw, FEATURE_DIM).astype(np.float32)
        std_raw = np.maximum(std_raw, 1e-4).astype(np.float32)

        return cls(
            crew_id=str(data.get("crew_id") or fallback_crew_id),
            mean=mean_raw,
            std=std_raw,
            threshold=float(data.get("threshold", DEFAULT_ANOMALY_THRESHOLD)),
            sample_count=int(data.get("sample_count", 0)),
            updated_at_us=int(data.get("updated_at_us", 0)),
            model_path=str(data["model_path"]) if data.get("model_path") else None,
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
    """Thread-safe LRU cache of per-crew baselines with sub-300 ms atomic switching."""

    def __init__(
        self,
        models_dir: Path | str = Path("./models"),
        *,
        max_entries: int = 16,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.profiles_dir = self.models_dir / "profiles"
        self.max_entries = max(1, max_entries)

        self._lock = threading.RLock()
        self._cache: OrderedDict[str, CrewBaseline] = OrderedDict()
        self._active_crew_id: Optional[str] = None
        self._active_baseline: CrewBaseline = self._load_initial_default()
        self.last_switch_ms: float = 0.0

    def profile_path(self, crew_id: str) -> Path:
        safe_id = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in crew_id)
        return self.profiles_dir / f"baseline_{safe_id}.json"

    def active_crew_id(self) -> Optional[str]:
        with self._lock:
            return self._active_crew_id

    def active_baseline(self) -> CrewBaseline:
        with self._lock:
            return self._active_baseline

    def get(self, crew_id: str) -> Optional[CrewBaseline]:
        """Return cached baseline or load from disk if present."""
        with self._lock:
            if crew_id in self._cache:
                self._cache.move_to_end(crew_id)
                return self._cache[crew_id]

        loaded = self._load_from_disk(crew_id)
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

        Returns ``(baseline, baseline_found)``.
        """
        t0 = time.perf_counter()
        baseline: Optional[CrewBaseline] = None
        baseline_found = False

        with self._lock:
            if crew_id in self._cache:
                self._cache.move_to_end(crew_id)
                baseline = self._cache[crew_id]
                baseline_found = baseline.sample_count > 0 or self.profile_path(crew_id).is_file()

        if baseline is None:
            loaded = self._load_from_disk(crew_id, explicit_path=baseline_path)
            if loaded is not None:
                baseline = loaded
                baseline_found = True
            else:
                # Check if an explicit ONNX baseline file exists even without JSON stats
                explicit_onnx_found = bool(baseline_path and Path(baseline_path).is_file())
                default_onnx_found = (self.models_dir / f"baseline_ae_{crew_id}.onnx").is_file() or (
                    self.models_dir / f"{crew_id}.onnx"
                ).is_file()
                baseline_found = explicit_onnx_found or default_onnx_found
                baseline = make_default_baseline(crew_id)
                if explicit_onnx_found and baseline_path:
                    baseline = CrewBaseline(
                        crew_id=crew_id,
                        mean=baseline.mean,
                        std=baseline.std,
                        threshold=baseline.threshold,
                        sample_count=0,
                        updated_at_us=baseline.updated_at_us,
                        model_path=baseline_path,
                    )

        with self._lock:
            self._put_lru(crew_id, baseline)
            self._active_crew_id = crew_id
            self._active_baseline = baseline
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.last_switch_ms = elapsed_ms

        logger.info(
            "active baseline switched",
            extra={
                "crew_id": crew_id,
                "baseline_found": baseline_found,
                "switch_ms": round(elapsed_ms, 3),
            },
        )
        return baseline, baseline_found

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

    def _load_initial_default(self) -> CrewBaseline:
        default_json = self.profiles_dir / "baseline_default.json"
        if default_json.is_file():
            try:
                data = json.loads(default_json.read_text(encoding="utf-8"))
                return CrewBaseline.from_dict(data, fallback_crew_id="default")
            except Exception as exc:
                logger.warning("failed loading default baseline json", extra={"err": str(exc)})
        return make_default_baseline("default")

    def _load_from_disk(
        self,
        crew_id: str,
        explicit_path: Optional[str] = None,
    ) -> Optional[CrewBaseline]:
        candidates: list[Path] = []
        if explicit_path:
            p = Path(explicit_path)
            if p.suffix.lower() == ".json":
                candidates.append(p)
        candidates.append(self.profile_path(crew_id))

        for path in candidates:
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return CrewBaseline.from_dict(data, fallback_crew_id=crew_id)
                except Exception as exc:
                    logger.warning(
                        "failed parsing baseline json",
                        extra={"crew_id": crew_id, "path": str(path), "err": str(exc)},
                    )
        return None
