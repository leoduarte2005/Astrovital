"""ONNX Runtime inference wrappers for posture, cadence, vitals, and anomalies."""

from .anomaly_scorer import AnomalyPrediction, AnomalyScorer
from .exercise_cadence import ExerciseCadenceEstimator, ExerciseCadencePrediction
from .posture_cls import POSTURE_CLASSES, PostureClassifier, PosturePrediction
from .session_manager import DEFAULT_MODEL_FILES, LoadedSession, SessionManager
from .vitals_reg import (
    DEFAULT_MAX30102_MAX_AGE_US,
    RF_ONLY_MAX_CONFIDENCE,
    VitalsPrediction,
    VitalsRegressor,
    has_recent_max30102,
)

__all__ = [
    "AnomalyPrediction",
    "AnomalyScorer",
    "DEFAULT_MAX30102_MAX_AGE_US",
    "DEFAULT_MODEL_FILES",
    "ExerciseCadenceEstimator",
    "ExerciseCadencePrediction",
    "LoadedSession",
    "POSTURE_CLASSES",
    "PostureClassifier",
    "PosturePrediction",
    "RF_ONLY_MAX_CONFIDENCE",
    "SessionManager",
    "VitalsPrediction",
    "VitalsRegressor",
    "has_recent_max30102",
]
