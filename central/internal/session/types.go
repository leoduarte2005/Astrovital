// Package session owns the active astronaut session (crew_id), mission_mode,
// calibration state, atomic Snapshot, and serialized hot-swap orchestration.
//
// This package MUST NOT import any other internal package besides contracts.
package session

import (
	"context"
	"errors"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	// DefaultCmdChCap is the bounded capacity of session.CmdCh (§2.2).
	DefaultCmdChCap = 16
	// DefaultSetCrewTimeout is the CREW_ACK deadline (§4.1).
	DefaultSetCrewTimeout = 2 * time.Second
	// DefaultChatTimeout is the CHAT_CORRELATE_RESP deadline. Edge AI bounds SLM
	// synthesis at 15 s (DEFAULT_TIMEOUT_S, deterministic fallback); Central adds
	// a 5 s margin for correlation + IPC so a stuck worker never blocks chat.
	DefaultChatTimeout = 20 * time.Second
	// DefaultCalibrationTimeout is the CALIBRATION_FEEDBACK deadline (§4.1).
	DefaultCalibrationTimeout = 2 * time.Second
	// DefaultChatHistoryLimit is the number of recent messages attached to CHAT_CORRELATE_REQ.
	DefaultChatHistoryLimit = 10
	// MaxChatTextBytes bounds incoming CHAT_MSG text length (§4.2).
	MaxChatTextBytes = 2000
	// DefaultChatDisclaimer is attached when AI omits a disclaimer.
	DefaultChatDisclaimer = "Clinical decision support only — not a medical diagnosis."
)

var (
	ErrBusy           = errors.New("session: command queue busy")
	ErrStopped        = errors.New("session: manager stopped")
	ErrInvalidCrewID  = errors.New("session: invalid crew_id")
	ErrNoActiveCrew   = errors.New("session: no active crew_id")
	ErrCrewMismatch   = errors.New("session: crew_id does not match active crew")
	ErrInvalidMode    = errors.New("session: invalid mission_mode")
	ErrInvalidInput   = errors.New("session: invalid input")
	ErrSwapSuperseded = errors.New("session: crew swap superseded by newer request")
)

// Snapshot is an immutable point-in-time view of active session state.
type Snapshot struct {
	ActiveCrewID        string
	Profile             contracts.CrewProfile
	BaselinePath        string
	Thresholds          map[string]contracts.Threshold
	MissionMode         contracts.MissionMode
	AIReady             bool
	CalibrationRequired bool
	CalibrationActive   bool
	CalibStepID         string
	SwapSeq             uint64
}

// CrewProfileData is returned by StorePort.LoadProfile.
//
// CalibrationRequired carries the store's single calibration rule
// (store.IsCalibrated) so WS CREW_STATE matches GET /api/crew and
// GET /api/crew/{id}/profile even before/without a CREW_ACK.
type CrewProfileData struct {
	Profile             contracts.CrewProfile
	BaselinePath        string
	CalibrationRequired bool
	Thresholds          map[string]contracts.Threshold
}

// StorePort decouples session from internal/store.
type StorePort interface {
	Flush(ctx context.Context) error
	LoadProfile(ctx context.Context, crewID string) (CrewProfileData, error)
	LoadSummary24h(ctx context.Context, crewID string) (string, error)
	LoadRecentChat(ctx context.Context, crewID string, limit int) ([]contracts.ChatMessage, error)
	SaveAudit(ctx context.Context, crewID *string, eventType string, details string, tsUs int64) error
	SaveChat(ctx context.Context, crewID string, req contracts.ChatMsgPayload, resp contracts.ChatCorrelateRespPayload, tsUs int64) error
	SaveSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload, tsUs int64) error
	SaveOutbox(ctx context.Context, rec contracts.OutboxRecord) error
}

// IPCPort decouples session from internal/ipc.
type IPCPort interface {
	SendSetActiveCrew(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error)
	SendChatCorrelate(ctx context.Context, reqID uint64, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error)
	SendCalibrationStep(ctx context.Context, reqID uint64, crewID string, payload contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error)
}

// UDPPort decouples session from internal/udp.
type UDPPort interface {
	SendModeCmd(ctx context.Context, mode contracts.MissionMode) error
}

// UIEvent carries an immediate outbound WS event toward httpws.
type UIEvent struct {
	Type                contracts.WSMsgType
	TsUs                int64
	CrewID              *string
	CrewState           *contracts.CrewStatePayload
	ChatReply           *contracts.ChatReplyPayload
	CalibrationFeedback *contracts.CalibrationFeedbackPayload
}

// UIPort decouples session from internal/httpws EventCh.
type UIPort interface {
	EmitEvent(ev UIEvent) bool
}

// SelfExamNotifier notifies pipeline when a new SELF_EXAM arrives so subsystems re-evaluate.
type SelfExamNotifier interface {
	NotifySelfExam(exam contracts.SelfExamPayload, receivedAt time.Time)
}

// Metrics exposes session counters for observability and testing.
type Metrics struct {
	SwapsRequested uint64
	SwapsCompleted uint64
	SwapTimeouts   uint64
	StaleAcks      uint64
	ReconnectSyncs uint64
	ChatRequests   uint64
	SelfExams      uint64
	CalibSteps     uint64
	ModeChanges    uint64
	UIEventsFailed uint64
}

// Config configures session timeouts and initial mode.
type Config struct {
	CmdChCap           int
	InitialMode        contracts.MissionMode
	SetCrewTimeout     time.Duration
	ChatTimeout        time.Duration
	CalibrationTimeout time.Duration
	ChatHistoryLimit   int
	Now                func() time.Time
}

// Deps wires external ports into Manager.
type Deps struct {
	Store            StorePort
	IPC              IPCPort
	UDP              UDPPort
	UI               UIPort
	SelfExamNotifier SelfExamNotifier
}
