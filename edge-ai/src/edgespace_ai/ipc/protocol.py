"""IPC v1 protocol definitions, Pydantic models, and length-prefixed framing.

Mirrors ``central/internal/contracts/{enums,frame,payloads,types}.go`` 1:1.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION: int = 1
MAX_FRAME_BYTES: int = 1 << 20  # 1 MiB
_HEADER_STRUCT = struct.Struct(">I")


class IPCProtocolError(Exception):
    """Base exception for IPC framing or envelope errors."""


class FrameSizeError(IPCProtocolError):
    """Raised when an IPC frame length is 0 or exceeds MAX_FRAME_BYTES (1 MiB)."""


class InvalidEnvelopeError(IPCProtocolError):
    """Raised when an IPC envelope fails structural or version validation."""


class BadVersionError(InvalidEnvelopeError):
    """Raised when ``v != PROTOCOL_VERSION``."""


class MissionMode(str, Enum):
    MODE_CABIN_TOMOGRAPHY = "MODE_CABIN_TOMOGRAPHY"
    MODE_REST_VITALS = "MODE_REST_VITALS"
    MODE_COUNTERMEASURE_EXERCISE = "MODE_COUNTERMEASURE_EXERCISE"
    MODE_RADIATION_ALERT = "MODE_RADIATION_ALERT"


class Peripheral(str, Enum):
    MAX30102 = "MAX30102"
    BME280 = "BME280"
    SCD40 = "SCD40"


class Escalation(str, Enum):
    LOCAL = "LOCAL"
    CREW = "CREW"
    STORE_AND_FORWARD = "STORE_AND_FORWARD"


class IPCMsgType(str, Enum):
    CSI_WINDOW = "CSI_WINDOW"
    PERIPHERAL_SNAPSHOT = "PERIPHERAL_SNAPSHOT"
    SET_ACTIVE_CREW = "SET_ACTIVE_CREW"
    CREW_ACK = "CREW_ACK"
    AI_INFERENCE = "AI_INFERENCE"
    CHAT_CORRELATE_REQ = "CHAT_CORRELATE_REQ"
    CHAT_CORRELATE_RESP = "CHAT_CORRELATE_RESP"
    CALIBRATION_STEP = "CALIBRATION_STEP"
    CALIBRATION_FEEDBACK = "CALIBRATION_FEEDBACK"


class IPCModel(BaseModel):
    """Base Pydantic model for all IPC v1 structs."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def _none_to_empty_list(value: Any) -> Any:
    return [] if value is None else value


class IQSample(IPCModel):
    real: float
    imag: float


class CSILink(IPCModel):
    tx_node_id: int = Field(ge=0, le=255)
    rx_node_id: int = Field(ge=0, le=255)
    iq_samples: list[IQSample] = Field(default_factory=list)
    rssi_dbm: int
    noise_floor: float

    @field_validator("iq_samples", mode="before")
    @classmethod
    def _coerce_iq_samples(cls, v: Any) -> Any:
        return _none_to_empty_list(v)


class CSIWindowPayload(IPCModel):
    cycle_seq_first: int = Field(ge=0)
    active_link_mask: int = Field(ge=0)
    mode: MissionMode
    links: list[CSILink] = Field(default_factory=list)
    quality_per_link: Optional[list[float]] = None

    @field_validator("links", mode="before")
    @classmethod
    def _coerce_links(cls, v: Any) -> Any:
        return _none_to_empty_list(v)


class PeripheralReading(IPCModel):
    type: Peripheral
    value: float
    unit: str
    timestamp_us: int


class PeripheralSnapshotPayload(IPCModel):
    readings: list[PeripheralReading] = Field(default_factory=list)
    timestamp_us: int

    @field_validator("readings", mode="before")
    @classmethod
    def _coerce_readings(cls, v: Any) -> Any:
        return _none_to_empty_list(v)


class Threshold(IPCModel):
    metric_name: str
    yellow_high: float
    red_high: float
    yellow_low: Optional[float] = None
    red_low: Optional[float] = None


class SetActiveCrewPayload(IPCModel):
    crew_id: str
    profile: Optional[CrewProfile] = None
    baseline_path: Optional[str] = None
    thresholds: Optional[dict[str, Threshold]] = None


class CrewAckPayload(IPCModel):
    ok: bool
    baseline_found: bool
    error: Optional[str] = None


class AIInferencePayload(IPCModel):
    cycle_seq_first: int = Field(ge=0)
    posture: str
    respiration_hz: float
    heart_rate_bpm: float
    hrv_ms: float
    anomaly_score: float
    confidence: float


class CrewProfile(IPCModel):
    crew_id: str
    name: str
    role: Optional[str] = None
    mission_day: Optional[int] = None
    age: Optional[int] = None
    biological_sex: Optional[str] = None
    height_cm: Optional[float] = None
    preflight_weight_kg: Optional[float] = None
    vo2max_baseline: Optional[float] = None
    preflight_hr_bpm: Optional[float] = None
    preflight_hrv_ms: Optional[float] = None
    preflight_spo2_pct: Optional[float] = None
    preflight_sbp_mmhg: Optional[float] = None
    preflight_dbp_mmhg: Optional[float] = None
    preflight_ferritin_ug_l: Optional[float] = None
    preflight_hemoglobin_g_dl: Optional[float] = None
    preflight_onsd_mm: Optional[float] = None
    sans_susceptibility: Optional[str] = None
    co2_sensitivity: Optional[str] = None
    motion_sickness_history: Optional[str] = None
    target_kcal_day: Optional[float] = None
    target_water_ml_day: Optional[float] = None
    radiation_career_limit_msv: Optional[float] = None
    mission_start_us: Optional[int] = None


class ChatMessage(IPCModel):
    sent_at_us: int
    role: str
    content: str


class ChatCorrelateReqPayload(IPCModel):
    text: str
    crew_id: Optional[str] = None
    profile: Optional[CrewProfile] = None
    thresholds: Optional[dict[str, Threshold]] = None
    last_peripherals: Optional[list[PeripheralReading]] = None
    last_inference: Optional[AIInferencePayload] = None
    summary_24h: Optional[str] = None
    recent_history: Optional[list[ChatMessage]] = None


class ChatCorrelateRespPayload(IPCModel):
    memory_updates: Optional[list[dict[str, Any]]] = None
    model_status: str = "ENGINEERING_TEST_ONLY"
    matched_condition_ids: Optional[list[str]] = None
    max_severity: Optional[str] = None
    blocked_actions: Optional[list[str]] = None
    text: str
    differentials: Optional[list[str]] = None
    evidence: Optional[list[str]] = None
    countermeasures: Optional[list[str]] = None
    source_ids: Optional[list[str]] = None
    escalation: Escalation
    disclaimer: Optional[str] = None
    disambiguation_question: Optional[str] = None
    actions: Optional[list[str]] = None


class CalibrationStepPayload(IPCModel):
    step_id: str
    action: str
    duration_ms: Optional[int] = None


class CalibrationFeedbackPayload(IPCModel):
    baseline_update: Optional[dict[str, Any]] = None
    step_id: str
    progress: int = Field(ge=0, le=100)
    quality: float
    error: Optional[str] = None


class IPCEnvelope(IPCModel):
    """TCP :5006 envelope shared between Central (Go) and Edge AI (Python)."""

    v: int = PROTOCOL_VERSION
    type: IPCMsgType
    ts_us: int
    crew_id: Optional[str] = None
    req_id: Optional[int] = Field(default=None, ge=0)
    payload: dict[str, Any]

    @field_validator("v")
    @classmethod
    def _validate_version(cls, v: int) -> int:
        if v != PROTOCOL_VERSION:
            raise ValueError(f"invalid IPC version: {v} (want {PROTOCOL_VERSION})")
        return v

    @field_validator("crew_id", mode="before")
    @classmethod
    def _normalize_crew_id(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        return str(v)

    def to_json_bytes(self) -> bytes:
        """Serialize envelope matching Go JSON tags (crew_id always present, req_id omitempty)."""
        data: dict[str, Any] = {
            "v": self.v,
            "type": self.type.value,
            "ts_us": self.ts_us,
            "crew_id": None if not self.crew_id else self.crew_id,
            "payload": self.payload,
        }
        if self.req_id is not None:
            data["req_id"] = self.req_id
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def now_us() -> int:
    """Current wall-clock time in Unix microseconds."""
    return time.time_ns() // 1000


def make_envelope(
    msg_type: IPCMsgType,
    payload: IPCModel | dict[str, Any],
    *,
    crew_id: Optional[str] = None,
    req_id: Optional[int] = None,
    ts_us: Optional[int] = None,
) -> IPCEnvelope:
    """Build a validated v1 IPCEnvelope from a typed payload model or dict."""
    if isinstance(payload, IPCModel):
        raw_payload = payload.model_dump(mode="json", exclude_none=True)
    else:
        raw_payload = payload

    normalized_crew = None if (crew_id is None or crew_id == "") else crew_id
    return IPCEnvelope(
        v=PROTOCOL_VERSION,
        type=msg_type,
        ts_us=now_us() if ts_us is None else ts_us,
        crew_id=normalized_crew,
        req_id=req_id,
        payload=raw_payload,
    )


def parse_envelope_bytes(raw: bytes) -> IPCEnvelope:
    """Decode and validate a raw JSON frame body into an IPCEnvelope."""
    try:
        decoded = json.loads(raw)
    except Exception as exc:
        raise InvalidEnvelopeError(f"invalid JSON frame: {exc}") from exc

    if not isinstance(decoded, dict):
        raise InvalidEnvelopeError("IPC envelope must be a JSON object")

    version = decoded.get("v")
    if version != PROTOCOL_VERSION:
        raise BadVersionError(f"invalid IPC version: {version!r} (want {PROTOCOL_VERSION})")

    try:
        return IPCEnvelope.model_validate(decoded)
    except Exception as exc:
        raise InvalidEnvelopeError(f"invalid IPC envelope: {exc}") from exc


def encode_frame(body: bytes) -> bytes:
    """Prefix a frame body with its uint32 big-endian length (1..1 MiB)."""
    size = len(body)
    if size == 0 or size > MAX_FRAME_BYTES:
        raise FrameSizeError(f"invalid IPC frame size: {size} (max {MAX_FRAME_BYTES})")
    return _HEADER_STRUCT.pack(size) + body


async def read_frame(reader: asyncio.StreamReader) -> Optional[bytes]:
    """Read one uint32 big-endian length-prefixed frame.

    Returns ``None`` on clean EOF before a frame header.
    Raises ``FrameSizeError`` or ``asyncio.IncompleteReadError`` on protocol errors.
    """
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as exc:
        if len(exc.partial) == 0:
            return None
        raise

    (size,) = _HEADER_STRUCT.unpack(header)
    if size == 0 or size > MAX_FRAME_BYTES:
        raise FrameSizeError(f"invalid IPC frame size: {size} (max {MAX_FRAME_BYTES})")

    return await reader.readexactly(size)


async def write_frame(writer: asyncio.StreamWriter, body: bytes) -> None:
    """Write one length-prefixed frame and drain the stream."""
    writer.write(encode_frame(body))
    await writer.drain()

