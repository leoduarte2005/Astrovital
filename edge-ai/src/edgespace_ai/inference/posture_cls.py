"""ONNX posture classifier wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from ..dsp.feature_extractor import ExtractedFeatures
from ..ipc.protocol import MissionMode
from .session_manager import SessionManager

POSTURE_CLASSES: tuple[str, ...] = ("supine", "sitting", "standing", "exercising", "prone")


@dataclass(frozen=True)
class PosturePrediction:
    posture: str
    confidence: float
    probabilities: dict[str, float]


class PostureClassifier:
    """Classifies crew posture from the 64-feature vector using ``posture_cls.onnx``."""

    MODEL_NAME = "posture_cls"

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def predict(
        self,
        extracted: ExtractedFeatures,
        *,
        mode: Optional[MissionMode] = None,
    ) -> PosturePrediction:
        outputs = self._sm.run(self.MODEL_NAME, extracted.vector)
        if outputs:
            return self._decode_outputs(outputs)
        return self._heuristic_fallback(extracted, mode=mode)

    @staticmethod
    def _decode_outputs(outputs: list[Any]) -> PosturePrediction:
        raw_label = outputs[0][0]
        if isinstance(raw_label, (bytes, np.bytes_)):
            label = raw_label.decode("utf-8")
        elif isinstance(raw_label, (int, np.integer)):
            idx = int(raw_label)
            label = POSTURE_CLASSES[idx] if 0 <= idx < len(POSTURE_CLASSES) else str(idx)
        else:
            label = str(raw_label)

        probs: dict[str, float] = {}
        confidence = 0.75

        if len(outputs) > 1:
            prob_out = outputs[1]
            if isinstance(prob_out, list) and prob_out and isinstance(prob_out[0], dict):
                probs = {str(k): float(v) for k, v in prob_out[0].items()}
                if probs:
                    confidence = float(max(probs.values()))
            else:
                arr = np.asarray(prob_out, dtype=np.float64).ravel()
                if arr.size == len(POSTURE_CLASSES):
                    probs = {cls: float(p) for cls, p in zip(POSTURE_CLASSES, arr)}
                    confidence = float(np.max(arr))
                elif arr.size > 0:
                    confidence = float(np.max(arr))

        return PosturePrediction(
            posture=label,
            confidence=float(np.clip(confidence, 0.0, 1.0)),
            probabilities=probs,
        )

    @staticmethod
    def _heuristic_fallback(
        extracted: ExtractedFeatures,
        *,
        mode: Optional[MissionMode] = None,
    ) -> PosturePrediction:
        if mode == MissionMode.MODE_COUNTERMEASURE_EXERCISE or extracted.motion_energy > 0.15:
            return PosturePrediction("exercising", 0.65, {"exercising": 0.65})
        if mode == MissionMode.MODE_REST_VITALS or extracted.motion_energy < 0.01:
            return PosturePrediction("supine", 0.60, {"supine": 0.60})
        return PosturePrediction("sitting", 0.55, {"sitting": 0.55})
