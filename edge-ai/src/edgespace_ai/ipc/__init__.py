"""IPC v1 protocol, TCP server, and typed message handlers."""

from typing import TYPE_CHECKING, Any

from .protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    AIInferencePayload,
    BadVersionError,
    CSILink,
    CSIWindowPayload,
    CalibrationFeedbackPayload,
    CalibrationStepPayload,
    ChatCorrelateReqPayload,
    ChatCorrelateRespPayload,
    ChatMessage,
    CrewAckPayload,
    CrewProfile,
    Escalation,
    FrameSizeError,
    IPCEnvelope,
    IPCMsgType,
    IPCProtocolError,
    IQSample,
    InvalidEnvelopeError,
    MissionMode,
    Peripheral,
    PeripheralReading,
    PeripheralSnapshotPayload,
    SetActiveCrewPayload,
    Threshold,
    encode_frame,
    make_envelope,
    now_us,
    parse_envelope_bytes,
    read_frame,
    write_frame,
)
from .server import HI_PRI_TYPES, LO_PRI_TYPES, IPCServer, ServerStats

if TYPE_CHECKING:
    from .handlers import IPCHandler, IPCState


def __getattr__(name: str) -> Any:
    if name in ("IPCHandler", "IPCState"):
        from . import handlers

        return getattr(handlers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AIInferencePayload",
    "BadVersionError",
    "CSILink",
    "CSIWindowPayload",
    "CalibrationFeedbackPayload",
    "CalibrationStepPayload",
    "ChatCorrelateReqPayload",
    "ChatCorrelateRespPayload",
    "ChatMessage",
    "CrewAckPayload",
    "CrewProfile",
    "Escalation",
    "FrameSizeError",
    "HI_PRI_TYPES",
    "IPCEnvelope",
    "IPCHandler",
    "IPCMsgType",
    "IPCProtocolError",
    "IPCServer",
    "IPCState",
    "IQSample",
    "InvalidEnvelopeError",
    "LO_PRI_TYPES",
    "MAX_FRAME_BYTES",
    "MissionMode",
    "PROTOCOL_VERSION",
    "Peripheral",
    "PeripheralReading",
    "PeripheralSnapshotPayload",
    "ServerStats",
    "SetActiveCrewPayload",
    "Threshold",
    "encode_frame",
    "make_envelope",
    "now_us",
    "parse_envelope_bytes",
    "read_frame",
    "write_frame",
]
