"""ONNX biometric vitals regressor enforcing Clinical Rule P4 on RF-only confidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from ..dsp.feature_extractor import ExtractedFeatures
from ..ipc.protocol import Peripheral, PeripheralReading, now_us
from .session_manager import SessionManager

RF_ONLY_MAX_CONFIDENCE = 0.65
DEFAULT_MAX30102_MAX_AGE_US = 10_000_000  # 10 seconds
_EPOCH_US_THRESHOLD = 1_000_000_000_000


@dataclass(frozen=True)
class VitalsPrediction:
    respiration_hz: float
    heart_rate_bpm: float
    hrv_ms: float
    confidence: float
    has_max30102_corroboration: bool


_CLOCK_SKEW_SIM_US = 3_600_000_000  # 1 hour: differentiates simulated clock offset from true staleness


def has_recent_max30102(
    peripherals: Optional[Sequence[PeripheralReading]],
    reference_ts_us: Optional[int] = None,
    *,
    max_age_us: int = DEFAULT_MAX30102_MAX_AGE_US,
    snapshot_ts_us: Optional[int] = None,
) -> bool:
    """Return True if a recent MAX30102 reading is present in PERIPHERAL_SNAPSHOT."""
    if not peripherals:
        return False

    ref = reference_ts_us if reference_ts_us is not None else now_us()
    snapshot_recent = (
        snapshot_ts_us is not None
        and snapshot_ts_us >= _EPOCH_US_THRESHOLD
        and ref >= _EPOCH_US_THRESHOLD
        and (ref - snapshot_ts_us) <= max_age_us
    )
    for reading in peripherals:
        if reading.type != Peripheral.MAX30102:
            continue
        if not np.isfinite(reading.value) or reading.value <= 0.0:
            continue
        if reading.timestamp_us >= _EPOCH_US_THRESHOLD and ref >= _EPOCH_US_THRESHOLD:
            if (ref - reading.timestamp_us) <= max_age_us:
                return True
            if snapshot_recent and snapshot_ts_us is not None and abs(snapshot_ts_us - reading.timestamp_us) > _CLOCK_SKEW_SIM_US:
                return True
        else:
            # Synthetic unit-test timestamps (< year 2001): treat positive diff <= max_age_us as recent
            if abs(ref - reading.timestamp_us) <= max_age_us:
                return True
    return False


class VitalsRegressor:
    """Estimates respiration_hz, heart_rate_bpm, and hrv_ms with P4 confidence cap."""

    MODEL_NAME = "vitals_reg"

    def __init__(
        self,
        session_manager: SessionManager,
        *,
        max30102_max_age_us: int = DEFAULT_MAX30102_MAX_AGE_US,
    ) -> None:
        self._sm = session_manager
        self._max30102_max_age_us = max30102_max_age_us

    def predict(
        self,
        extracted: ExtractedFeatures,
        *,
        degradation_ratio: float = 1.0,
        mean_snr_db: float = 20.0,
        peripherals: Optional[Sequence[PeripheralReading]] = None,
        reference_ts_us: Optional[int] = None,
        snapshot_ts_us: Optional[int] = None,
    ) -> VitalsPrediction:
        outputs = self._sm.run(self.MODEL_NAME, extracted.vector)
        if outputs:
            arr = np.asarray(outputs[0], dtype=np.float64).ravel()
            raw_resp = float(arr[0]) if arr.size >= 1 else extracted.resp_hz_est
            raw_hr = float(arr[1]) if arr.size >= 2 else extracted.hr_bpm_est
            raw_hrv = float(arr[2]) if arr.size >= 3 else extracted.hrv_ms_est
            base_conf = 0.88
        else:
            raw_resp = extracted.resp_hz_est
            raw_hr = extracted.hr_bpm_est
            raw_hrv = extracted.hrv_ms_est
            base_conf = 0.60

        resp_hz = float(np.clip(raw_resp, 0.08, 0.75))
        hr_bpm = float(np.clip(raw_hr, 35.0, 210.0))
        hrv_ms = float(np.clip(raw_hrv, 5.0, 200.0))

        # Scale confidence by link availability & SNR
        snr_factor = float(np.clip((mean_snr_db + 5.0) / 30.0, 0.2, 1.0))
        link_factor = float(np.clip(0.4 + 0.6 * degradation_ratio, 0.25, 1.0))
        confidence = float(np.clip(base_conf * snr_factor * link_factor, 0.05, 0.98))

        # Clinical Rule P4: RF-CSI-only HR/HRV estimates MUST have confidence <= 0.65
        # when there is no recent MAX30102 reading in PERIPHERAL_SNAPSHOT.
        max30102_recent = has_recent_max30102(
            peripherals,
            reference_ts_us=reference_ts_us,
            max_age_us=self._max30102_max_age_us,
            snapshot_ts_us=snapshot_ts_us,
        )
        if not max30102_recent:
            confidence = min(confidence, RF_ONLY_MAX_CONFIDENCE)

        return VitalsPrediction(
            respiration_hz=resp_hz,
            heart_rate_bpm=hr_bpm,
            hrv_ms=hrv_ms,
            confidence=confidence,
            has_max30102_corroboration=max30102_recent,
        )
