"""ONNX Runtime session manager configured for Orange Pi 4 Pro (ARM64) thread budgets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import onnxruntime as ort

from ..dsp.feature_extractor import FEATURE_DIM
from ..utils.logging import get_logger

logger = get_logger("edgespace_ai.inference.session_manager")

DEFAULT_MODEL_FILES: dict[str, str] = {
    "posture_cls": "posture_cls.onnx",
    "exercise_cadence": "exercise_cadence.onnx",
    "vitals_reg": "vitals_reg.onnx",
    "baseline_ae_default": "baseline_ae_default.onnx",
    "isolation_forest": "isolation_forest.onnx",
}


@dataclass(frozen=True)
class LoadedSession:
    """Loaded ONNX Runtime session plus its primary input/output metadata."""

    name: str
    path: Path
    session: ort.InferenceSession
    input_name: str
    output_names: tuple[str, ...]
    warmed_up: bool = False


class SessionManager:
    """Loads ONNX Runtime sessions at boot with bounded threads and runs 1 warm-up."""

    def __init__(
        self,
        models_dir: Path | str = Path("./models"),
        *,
        intra_op_num_threads: int = 2,
        inter_op_num_threads: int = 1,
        providers: Optional[list[str]] = None,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.intra_op_num_threads = max(1, int(intra_op_num_threads))
        self.inter_op_num_threads = max(1, int(inter_op_num_threads))
        self.providers = providers or ["CPUExecutionProvider"]
        self._sessions: dict[str, LoadedSession] = {}

    def _build_session_options(self) -> ort.SessionOptions:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.intra_op_num_threads
        opts.inter_op_num_threads = self.inter_op_num_threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return opts

    def load_model(self, name: str, path: Path) -> Optional[LoadedSession]:
        """Load and warm up a single ONNX model file."""
        if not path.is_file():
            logger.warning("onnx model file not found", extra={"model": name, "path": str(path)})
            return None

        opts = self._build_session_options()
        session = ort.InferenceSession(str(path), sess_options=opts, providers=self.providers)
        input_name = session.get_inputs()[0].name
        output_names = tuple(out.name for out in session.get_outputs())

        warmed = self._warmup(name, session, input_name)
        loaded = LoadedSession(
            name=name,
            path=path,
            session=session,
            input_name=input_name,
            output_names=output_names,
            warmed_up=warmed,
        )
        self._sessions[name] = loaded
        logger.info(
            "onnx model loaded",
            extra={
                "model": name,
                "path": str(path),
                "intra_op_threads": self.intra_op_num_threads,
                "inter_op_threads": self.inter_op_num_threads,
                "warmed_up": warmed,
            },
        )
        return loaded

    def load_all(self, model_files: Optional[dict[str, str]] = None) -> dict[str, LoadedSession]:
        """Load and warm up all configured ONNX models at boot."""
        mapping = model_files or DEFAULT_MODEL_FILES
        for name, filename in mapping.items():
            self.load_model(name, self.models_dir / filename)
        return dict(self._sessions)

    def get(self, name: str) -> Optional[LoadedSession]:
        """Return a loaded session by logical name if available."""
        return self._sessions.get(name)

    def load_crew_autoencoder(self, crew_id: str, explicit_path: Optional[str] = None) -> Optional[LoadedSession]:
        """Optionally load a crew-specific autoencoder ONNX model if present on disk."""
        key = f"baseline_ae_{crew_id}"
        if key in self._sessions:
            return self._sessions[key]

        candidates: list[Path] = []
        if explicit_path:
            p = Path(explicit_path)
            if p.suffix.lower() == ".onnx":
                candidates.append(p)
        candidates.append(self.models_dir / f"baseline_ae_{crew_id}.onnx")
        candidates.append(self.models_dir / f"{crew_id}.onnx")

        for cand in candidates:
            if cand.is_file():
                return self.load_model(key, cand)
        return None

    def run(self, name: str, features: np.ndarray) -> Optional[list[Any]]:
        """Execute inference on a 1D (64,) or 2D (N, 64) float32 feature array."""
        loaded = self._sessions.get(name)
        if loaded is None:
            return None
        x = np.asarray(features, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        return loaded.session.run(None, {loaded.input_name: x})

    @staticmethod
    def _warmup(name: str, session: ort.InferenceSession, input_name: str) -> bool:
        try:
            dummy = np.zeros((1, FEATURE_DIM), dtype=np.float32)
            session.run(None, {input_name: dummy})
            return True
        except Exception as exc:
            logger.warning("onnx warmup failed", extra={"model": name, "err": str(exc)})
            return False
