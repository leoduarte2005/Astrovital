"""Typed IPC v1 message dispatchers wiring DSP, ONNX inference, and adaptation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import os
import sys
from typing import Any, Optional

import numpy as np
from pydantic import ValidationError

from ..adaptation.baseline_registry import BaselineRegistry
from ..adaptation.calibration_engine import CalibrationEngine
from ..correlation.correlator import ClinicalCorrelator
from ..correlation.synthesizer import LocalSLMSynthesizer
from ..dsp.csi_processor import CSIProcessor
from ..dsp.feature_extractor import FeatureExtractor
from ..dsp.link_fusion import LinkFusion
from ..dsp.window_buffer import WindowBuffer
from ..inference.anomaly_scorer import AnomalyScorer
from ..inference.exercise_cadence import ExerciseCadenceEstimator
from ..inference.posture_cls import PostureClassifier
from ..inference.session_manager import SessionManager
from ..inference.vitals_reg import VitalsRegressor
from ..utils.config import Settings, get_settings
from ..utils.logging import get_logger
from .protocol import (
    AIInferencePayload,
    CSIWindowPayload,
    CalibrationFeedbackPayload,
    CalibrationStepPayload,
    ChatCorrelateReqPayload,
    ChatCorrelateRespPayload,
    CrewAckPayload,
    Escalation,
    IPCEnvelope,
    IPCMsgType,
    Peripheral,
    PeripheralReading,
    PeripheralSnapshotPayload,
    SetActiveCrewPayload,
    Threshold,
    make_envelope,
)

logger = get_logger("edgespace_ai.ipc.handlers")


@dataclass
class IPCState:
    """In-memory state tracked across IPC messages and reconnects."""

    active_crew_id: Optional[str] = None
    baseline_path: Optional[str] = None
    thresholds: dict[str, Threshold] = field(default_factory=dict)
    latest_peripherals: list[PeripheralReading] = field(default_factory=list)
    latest_peripheral_ts_us: Optional[int] = None
    latest_inference: Optional[AIInferencePayload] = None
    latest_features: Optional[np.ndarray] = None
    latest_anomaly_score: Optional[float] = None
    latest_link_quality: float = 1.0


class IPCHandler:
    """Typed IPC v1 dispatcher connecting DSP, ONNX inference, and crew adaptation."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        disable_slm: Optional[bool] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.state = IPCState()

        # DSP pipeline
        self.csi_processor = CSIProcessor()
        self.window_buffer = WindowBuffer(maxlen=32)
        self.link_fusion = LinkFusion()
        self.feature_extractor = FeatureExtractor()

        # ONNX Runtime session manager (boot load + 1 warmup)
        self.session_manager = SessionManager(
            models_dir=self._settings.models_dir,
            intra_op_num_threads=self._settings.ort_threads,
            inter_op_num_threads=1,
        )
        self.session_manager.load_all()

        self.posture_cls = PostureClassifier(self.session_manager)
        self.exercise_cadence = ExerciseCadenceEstimator(self.session_manager)
        self.vitals_reg = VitalsRegressor(self.session_manager)
        self.anomaly_scorer = AnomalyScorer(self.session_manager)

        # Multi-astronaut baseline registry & incremental EMA calibration
        self.baseline_registry = BaselineRegistry(models_dir=self._settings.models_dir)
        self.calibration_engine = CalibrationEngine(self.baseline_registry)

        # Causal clinical correlator (SQLite FTS5 mode=ro + nasa_causal_graph.yaml fallback)
        self.correlator = ClinicalCorrelator(db_path=self._settings.db_path)

        # Local GGUF SLM conversational writer (ARM64 offline, --disable-slm / env / settings)
        slm_disabled = (
            disable_slm
            if disable_slm is not None
            else (
                bool(getattr(self._settings, "disable_slm", False))
                or os.environ.get("EDGESPACE_DISABLE_SLM", "").strip().lower() in {"1", "true", "yes", "on"}
                or "--disable-slm" in sys.argv
            )
        )
        self.synthesizer = LocalSLMSynthesizer(
            models_dir=self._settings.models_dir,
            disabled=slm_disabled,
        )

    async def handle(self, env: IPCEnvelope) -> Optional[IPCEnvelope]:
        """Dispatch an incoming IPCEnvelope and return a correlated reply if applicable."""
        if env.type == IPCMsgType.SET_ACTIVE_CREW:
            return await self._handle_set_active_crew(env)
        if env.type == IPCMsgType.CHAT_CORRELATE_REQ:
            return await self._handle_chat_correlate(env)
        if env.type == IPCMsgType.CALIBRATION_STEP:
            return await self._handle_calibration_step(env)
        if env.type == IPCMsgType.CSI_WINDOW:
            return await self._handle_csi_window(env)
        if env.type == IPCMsgType.PERIPHERAL_SNAPSHOT:
            return await self._handle_peripheral_snapshot(env)

        logger.warning("unhandled ipc message type", extra={"msg_type": env.type.value})
        return None

    async def _handle_set_active_crew(self, env: IPCEnvelope) -> IPCEnvelope:
        try:
            req = SetActiveCrewPayload.model_validate(env.payload)
        except ValidationError as exc:
            logger.warning("invalid SET_ACTIVE_CREW payload", extra={"req_id": env.req_id, "err": str(exc)})
            return make_envelope(
                IPCMsgType.CREW_ACK,
                CrewAckPayload(ok=False, baseline_found=False, error=str(exc)),
                crew_id=env.crew_id,
                req_id=env.req_id,
            )

        self.state.active_crew_id = req.crew_id
        self.state.baseline_path = req.baseline_path
        if req.thresholds is not None:
            self.state.thresholds = dict(req.thresholds)

        _, baseline_found = self.baseline_registry.set_active_crew(
            req.crew_id,
            baseline_path=req.baseline_path,
        )
        # Optionally load crew-specific ONNX autoencoder if present
        if self.session_manager.load_crew_autoencoder(req.crew_id, req.baseline_path) is not None:
            baseline_found = True

        logger.info(
            "active crew updated",
            extra={
                "crew_id": req.crew_id,
                "req_id": env.req_id,
                "baseline_found": baseline_found,
                "switch_ms": round(self.baseline_registry.last_switch_ms, 3),
            },
        )
        return make_envelope(
            IPCMsgType.CREW_ACK,
            CrewAckPayload(ok=True, baseline_found=baseline_found),
            crew_id=req.crew_id,
            req_id=env.req_id,
        )

    async def _handle_chat_correlate(self, env: IPCEnvelope) -> IPCEnvelope:
        try:
            req = ChatCorrelateReqPayload.model_validate(env.payload)
        except ValidationError as exc:
            logger.warning("invalid CHAT_CORRELATE_REQ payload", extra={"req_id": env.req_id, "err": str(exc)})
            return make_envelope(
                IPCMsgType.CHAT_CORRELATE_RESP,
                ChatCorrelateRespPayload(
                    text="Unable to parse correlation request payload.",
                    escalation=Escalation.LOCAL,
                    disclaimer="Clinical decision support only; verify telemetry directly.",
                ),
                crew_id=env.crew_id or self.state.active_crew_id,
                req_id=env.req_id,
            )

        crew_id = req.crew_id or env.crew_id or self.state.active_crew_id
        peripherals = _merge_valid_peripherals(
            state_readings=self.state.latest_peripherals,
            req_readings=req.last_peripherals,
        )
        inference = req.last_inference or self.state.latest_inference
        thresholds = req.thresholds if req.thresholds is not None else self.state.thresholds
        active_baseline = (
            self.baseline_registry.get(crew_id) if crew_id else None
        ) or self.baseline_registry.active_baseline()

        resp = self.correlator.correlate(
            req,
            peripherals=peripherals,
            inference=inference,
            thresholds=thresholds,
            baseline=active_baseline,
        )

        if self.synthesizer.is_ready:
            memory_facts = _collect_memory_facts(req, crew_id=crew_id)
            sensor_snapshot = _build_sensor_snapshot(
                peripherals=peripherals,
                inference=inference,
                crew_id=crew_id,
            )
            synthesized_text = await asyncio.to_thread(
                self.synthesizer.synthesize_response,
                resp,
                memory_facts,
                sensor_snapshot,
            )
            if synthesized_text:
                resp = resp.model_copy(update={"text": synthesized_text})

        logger.debug("chat correlate handled", extra={"req_id": env.req_id, "crew_id": crew_id})
        return make_envelope(
            IPCMsgType.CHAT_CORRELATE_RESP,
            resp,
            crew_id=crew_id,
            req_id=env.req_id,
        )

    async def _handle_calibration_step(self, env: IPCEnvelope) -> IPCEnvelope:
        try:
            req = CalibrationStepPayload.model_validate(env.payload)
        except ValidationError as exc:
            logger.warning("invalid CALIBRATION_STEP payload", extra={"req_id": env.req_id, "err": str(exc)})
            return make_envelope(
                IPCMsgType.CALIBRATION_FEEDBACK,
                CalibrationFeedbackPayload(step_id="", progress=0, quality=0.0, error=str(exc)),
                crew_id=env.crew_id or self.state.active_crew_id,
                req_id=env.req_id,
            )

        crew_id = env.crew_id or self.state.active_crew_id or "default"
        result = self.calibration_engine.process_step(
            crew_id=crew_id,
            step_id=req.step_id,
            action=req.action,
            latest_features=self.state.latest_features,
            latest_anomaly_score=self.state.latest_anomaly_score,
            link_quality=self.state.latest_link_quality,
        )

        return make_envelope(
            IPCMsgType.CALIBRATION_FEEDBACK,
            CalibrationFeedbackPayload(
                step_id=result.step_id,
                progress=result.progress,
                quality=result.quality,
            ),
            crew_id=crew_id,
            req_id=env.req_id,
        )

    async def _handle_csi_window(self, env: IPCEnvelope) -> Optional[IPCEnvelope]:
        try:
            win = CSIWindowPayload.model_validate(env.payload)
        except ValidationError as exc:
            logger.warning("invalid CSI_WINDOW payload", extra={"err": str(exc)})
            return None

        self.window_buffer.push(win, ts_us=env.ts_us)
        recent_windows = self.window_buffer.latest(10)
        fs_hz = self.window_buffer.estimate_sample_rate_hz()

        fused = self.link_fusion.fuse_windows(
            recent_windows,
            processor=self.csi_processor,
            sample_rate_hz=fs_hz,
        )

        if fused is None:
            inference = AIInferencePayload(
                cycle_seq_first=win.cycle_seq_first,
                posture="unknown",
                respiration_hz=0.25,
                heart_rate_bpm=68.0,
                hrv_ms=45.0,
                anomaly_score=0.0,
                confidence=0.0,
            )
            self.state.latest_inference = inference
            return make_envelope(
                IPCMsgType.AI_INFERENCE,
                inference,
                crew_id=env.crew_id or self.state.active_crew_id,
                req_id=None,
            )

        extracted = self.feature_extractor.extract(fused)
        self.state.latest_features = extracted.vector
        self.state.latest_link_quality = float(np.clip(fused.degradation_ratio, 0.1, 1.0))

        posture_pred = self.posture_cls.predict(extracted, mode=win.mode)
        cadence_pred = self.exercise_cadence.predict(extracted)
        posture_label = "exercising" if cadence_pred.is_exercising else posture_pred.posture

        vitals_pred = self.vitals_reg.predict(
            extracted,
            degradation_ratio=fused.degradation_ratio,
            mean_snr_db=fused.mean_snr_db,
            peripherals=self.state.latest_peripherals,
            reference_ts_us=env.ts_us,
            snapshot_ts_us=self.state.latest_peripheral_ts_us,
        )

        active_baseline = self.baseline_registry.active_baseline()
        anomaly_pred = self.anomaly_scorer.score(extracted, baseline=active_baseline)
        self.state.latest_anomaly_score = anomaly_pred.anomaly_score

        inference = AIInferencePayload(
            cycle_seq_first=win.cycle_seq_first,
            posture=posture_label,
            respiration_hz=round(vitals_pred.respiration_hz, 4),
            heart_rate_bpm=round(vitals_pred.heart_rate_bpm, 2),
            hrv_ms=round(vitals_pred.hrv_ms, 2),
            anomaly_score=round(anomaly_pred.anomaly_score, 4),
            confidence=round(vitals_pred.confidence, 4),
        )
        self.state.latest_inference = inference

        return make_envelope(
            IPCMsgType.AI_INFERENCE,
            inference,
            crew_id=env.crew_id or self.state.active_crew_id,
            req_id=None,
        )

    async def _handle_peripheral_snapshot(self, env: IPCEnvelope) -> None:
        try:
            snap = PeripheralSnapshotPayload.model_validate(env.payload)
        except ValidationError as exc:
            logger.warning("invalid PERIPHERAL_SNAPSHOT payload", extra={"err": str(exc)})
            return None

        self.state.latest_peripherals = snap.readings
        self.state.latest_peripheral_ts_us = snap.timestamp_us or env.ts_us
        return None


def _is_valid_reading(r: PeripheralReading, *, all_zero_batch: bool = False) -> bool:
    """Filter uninitialized placeholder readings (e.g., 0 ppm CO2 or 0% SpO2)."""
    if not math.isfinite(r.value):
        return False
    unit_low = r.unit.strip().lower()
    if r.type in (Peripheral.SCD40, Peripheral.MAX30102):
        return r.value > 0.0
    if r.type == Peripheral.BME280:
        if "pa" in unit_low or "%" in unit_low:
            return r.value > 0.0
        if all_zero_batch and r.value == 0.0:
            return False
    return True


def _merge_valid_peripherals(
    *,
    state_readings: list[PeripheralReading],
    req_readings: Optional[list[PeripheralReading]],
) -> list[PeripheralReading]:
    """Combine cached PERIPHERAL_SNAPSHOT readings with valid non-zero request overrides."""
    merged: dict[tuple[Peripheral, str], PeripheralReading] = {}
    state_all_zero = bool(state_readings) and all(r.value == 0.0 for r in state_readings)
    for r in state_readings:
        if _is_valid_reading(r, all_zero_batch=state_all_zero):
            merged[(r.type, r.unit.strip().lower())] = r

    if req_readings:
        req_all_zero = all(r.value == 0.0 for r in req_readings)
        for r in req_readings:
            if _is_valid_reading(r, all_zero_batch=req_all_zero):
                merged[(r.type, r.unit.strip().lower())] = r

    return list(merged.values())


def _collect_memory_facts(req: ChatCorrelateReqPayload, *, crew_id: Optional[str]) -> list[str]:
    """Extract compact persistent crew context and profile cues for SLM grounding."""
    facts: list[str] = []
    if req.profile is not None:
        parts = [req.profile.name]
        if req.profile.role:
            parts.append(req.profile.role)
        if req.profile.mission_day is not None:
            parts.append(f"dia {req.profile.mission_day}")
        facts.append("Tripulante: " + ", ".join(parts))
    elif crew_id:
        facts.append(f"crew_id={crew_id}")
    if req.summary_24h:
        facts.append(f"Resumo 24h: {req.summary_24h.strip()[:180]}")
    if req.recent_history:
        user_turns = [m.content.strip()[:80] for m in req.recent_history if m.role == "user" and m.content.strip()]
        if user_turns:
            facts.append("Queixa recente: " + " | ".join(user_turns[-2:]))
    return facts


def _build_sensor_snapshot(
    *,
    peripherals: list[PeripheralReading],
    inference: Optional[AIInferencePayload],
    crew_id: Optional[str],
) -> dict[str, Any]:
    """Serialize latest ESP32-S3 peripheral readings and CSI inference with semantic labels."""
    snapshot: dict[str, Any] = {}
    for r in peripherals:
        u = r.unit.strip().lower()
        if r.type == Peripheral.SCD40:
            snapshot["CO2_ppm"] = round(r.value, 1)
        elif r.type == Peripheral.MAX30102 and "%" in u:
            snapshot["SpO2_pct"] = round(r.value, 1)
        elif r.type == Peripheral.MAX30102 and "bpm" in u:
            snapshot["FC_oximetro_bpm"] = round(r.value, 1)
        elif r.type == Peripheral.BME280 and ("c" in u or "deg" in u):
            snapshot["Temp_C"] = round(r.value, 1)
        elif r.type == Peripheral.BME280 and "rh" in u:
            snapshot["Umidade_pct"] = round(r.value, 1)
        elif r.type == Peripheral.BME280 and "pa" in u:
            snapshot["Pressao_hPa"] = round(r.value, 1)
        else:
            snapshot[f"{r.type.value}_{r.unit}"] = round(r.value, 2)
    if inference is not None:
        snapshot["CSI_postura"] = inference.posture
        snapshot["CSI_FC_bpm"] = round(inference.heart_rate_bpm, 1)
        snapshot["CSI_FR_rpm"] = round(inference.respiration_hz * 60.0, 1)
        snapshot["CSI_anomalia"] = round(inference.anomaly_score, 2)
    return snapshot

