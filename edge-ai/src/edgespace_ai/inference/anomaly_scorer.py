"""Combined Autoencoder + Isolation Forest anomaly scorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..adaptation.baseline_registry import CrewBaseline, make_default_baseline
from ..dsp.feature_extractor import ExtractedFeatures
from .session_manager import SessionManager


@dataclass(frozen=True)
class AnomalyPrediction:
    anomaly_score: float       # normalized [0.0, 1.0]
    ae_mse: float
    iforest_score: float
    is_anomalous: bool


class AnomalyScorer:
    """Combines Autoencoder reconstruction MSE and Isolation Forest score."""

    DEFAULT_AE_NAME = "baseline_ae_default"
    IFOREST_NAME = "isolation_forest"

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def score(
        self,
        extracted: ExtractedFeatures,
        baseline: Optional[CrewBaseline] = None,
    ) -> AnomalyPrediction:
        active = baseline or make_default_baseline()
        x_raw = np.asarray(extracted.vector, dtype=np.float32)
        x_norm = active.normalize(x_raw)

        # 1. Autoencoder reconstruction error on crew-normalized features
        ae_name = f"baseline_ae_{active.crew_id}"
        if self._sm.get(ae_name) is None:
            ae_name = self.DEFAULT_AE_NAME

        ae_outputs = self._sm.run(ae_name, x_norm)
        if ae_outputs:
            recon = np.asarray(ae_outputs[0], dtype=np.float32).ravel()
            ae_mse = float(np.mean(np.square(x_norm.ravel() - recon)))
        else:
            ae_mse = float(np.mean(np.square(x_norm))) * 0.25

        # Map MSE smoothly to [0, 1]
        ae_norm = float(1.0 - np.exp(-ae_mse / 4.0))

        # 2. Isolation Forest score (trained in raw feature space or scaled inside pipeline)
        if_outputs = self._sm.run(self.IFOREST_NAME, x_raw)
        if if_outputs:
            if_norm = self._decode_iforest(if_outputs)
        else:
            z_max = float(np.max(np.abs(x_norm))) if x_norm.size > 0 else 0.0
            if_norm = float(np.clip(z_max / 6.0, 0.0, 1.0))

        if ae_outputs and if_outputs:
            combined = 0.55 * ae_norm + 0.45 * if_norm
        elif ae_outputs:
            combined = ae_norm
        elif if_outputs:
            combined = if_norm
        else:
            combined = 0.5 * ae_norm + 0.5 * if_norm

        combined = float(np.clip(combined, 0.0, 1.0))
        return AnomalyPrediction(
            anomaly_score=combined,
            ae_mse=ae_mse,
            iforest_score=if_norm,
            is_anomalous=combined >= active.threshold,
        )

    @staticmethod
    def _decode_iforest(outputs: list[object]) -> float:
        # skl2onnx IsolationForest emits [label {-1, 1}, scores (decision_function)]
        label = int(np.asarray(outputs[0]).ravel()[0])
        if len(outputs) > 1:
            decision = float(np.asarray(outputs[1], dtype=np.float64).ravel()[0])
            # sklearn decision_function: positive => inlier, negative => outlier
            return float(1.0 / (1.0 + np.exp(4.0 * decision)))
        return 0.85 if label == -1 else 0.15
