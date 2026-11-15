"""ONNX exercise cadence regressor wrapper."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..dsp.feature_extractor import ExtractedFeatures
from .session_manager import SessionManager


@dataclass(frozen=True)
class ExerciseCadencePrediction:
    cadence_hz: float
    cadence_spm: float
    is_exercising: bool


class ExerciseCadenceEstimator:
    """Estimates exercise movement cadence (Hz / steps-per-min) via ``exercise_cadence.onnx``."""

    MODEL_NAME = "exercise_cadence"

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def predict(self, extracted: ExtractedFeatures) -> ExerciseCadencePrediction:
        outputs = self._sm.run(self.MODEL_NAME, extracted.vector)
        if outputs:
            val = float(np.asarray(outputs[0], dtype=np.float64).ravel()[0])
            cadence_hz = float(np.clip(val, 0.0, 4.0))
        else:
            cadence_hz = float(np.clip(extracted.cadence_hz_est, 0.0, 4.0))

        # Suppress negligible noise cadence when overall motion energy is resting level
        if extracted.motion_energy < 0.01 and cadence_hz < 0.4:
            cadence_hz = 0.0

        return ExerciseCadencePrediction(
            cadence_hz=cadence_hz,
            cadence_spm=cadence_hz * 60.0,
            is_exercising=cadence_hz >= 0.75 and extracted.motion_energy >= 0.03,
        )
