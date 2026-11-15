// Package pipeline implements the zero-GC hot-path CSI cycle assembler,
// 20-link ring buffer, 1 Hz I2C peripheral aggregator, clinical threshold engine,
// and decoupled outputs for ipc, store, and httpws.
//
// This package MUST NOT import any other internal package besides contracts.
package pipeline

import (
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	// NumNodes is the fixed cluster node count (IDs 0..4).
	NumNodes = 5
	// NumLinks is the number of ordered directional pairs (tx, rx) with tx != rx.
	NumLinks = NumNodes * (NumNodes - 1) // 20
	// RingCapacity is 30 s of samples per link at 10 Hz.
	RingCapacity = 300
	// NumBuckets is the number of in-flight TDM cycle buckets indexed by cycle_seq % 4.
	NumBuckets = 4
	// DefaultWindowCycles is the number of closed cycles per CSI_WINDOW (5 = 500 ms = 2 Hz).
	DefaultWindowCycles = 5
	// DefaultCycleGrace is the wait deadline after cycle open before closing a partial cycle.
	DefaultCycleGrace = 30 * time.Millisecond
	// DefaultEmit1HzInterval is the decimation period for 1 Hz IPC/store outputs.
	DefaultEmit1HzInterval = 1 * time.Second
	// DefaultSelfExamTTL is how long a recent SELF_EXAM influences clinical thresholds.
	DefaultSelfExamTTL = 24 * time.Hour
	// MaxSubcarriers bounds inline I/Q storage inside LinkSample (zero pointers).
	MaxSubcarriers = 64
	// AllLinksMask has all 20 directional link bits set.
	AllLinksMask uint32 = (1 << NumLinks) - 1
)

// LinkIndex maps a directional pair (tx, rx) in 0..4 (tx != rx) to a deterministic index 0..19.
func LinkIndex(tx, rx uint8) (int, bool) {
	if tx >= NumNodes || rx >= NumNodes || tx == rx {
		return 0, false
	}
	if rx > tx {
		return int(tx)*4 + int(rx) - 1, true
	}
	return int(tx)*4 + int(rx), true
}

// LinkPair maps a deterministic link index 0..19 back to (tx, rx).
func LinkPair(idx int) (tx, rx uint8, ok bool) {
	if idx < 0 || idx >= NumLinks {
		return 0, 0, false
	}
	tx = uint8(idx / 4)
	r := uint8(idx % 4)
	if r >= tx {
		rx = r + 1
	} else {
		rx = r
	}
	return tx, rx, true
}

// ActiveLinkMaskFromNodes computes the 20-bit active link mask from a 5-bit active node mask.
func ActiveLinkMaskFromNodes(activeNodeMask uint8) uint32 {
	var mask uint32
	for idx := 0; idx < NumLinks; idx++ {
		tx, rx, _ := LinkPair(idx)
		if (activeNodeMask&(1<<tx)) != 0 && (activeNodeMask&(1<<rx)) != 0 {
			mask |= 1 << idx
		}
	}
	return mask
}

// IQF32 is a pointer-free complex CSI sample stored inline in LinkSample.
type IQF32 struct {
	Real float32
	Imag float32
}

// LinkSample is a fixed-size, pointer-free CSI sample stored in the [20][300]LinkSample ring buffer.
type LinkSample struct {
	CycleSeq    uint32
	TimestampUs int64
	TxNodeID    uint8
	RxNodeID    uint8
	RSSIDbm     int16
	NoiseFloor  float32
	SampleCount uint16
	Valid       bool
	IQ          [MaxSubcarriers]IQF32
}

// DataMsg mirrors udp.DataMsg without importing internal/udp.
type DataMsg struct {
	Type       contracts.UDPMsgType
	CSI        *contracts.CSIFrame
	Peripheral *contracts.PeripheralDataPayload
	ReceivedAt time.Time
	SrcAddr    string
}

// SelfExamInput carries a validated SELF_EXAM payload from httpws/sim.
type SelfExamInput struct {
	Payload    contracts.SelfExamPayload
	ReceivedAt time.Time
}

// SessionView is a read-only snapshot of active session state (decoupled from internal/session).
type SessionView struct {
	CrewID            string
	MissionMode       contracts.MissionMode
	AIReady           bool
	CalibrationActive bool
	CalibrationStepID string
	Thresholds        map[string]contracts.Threshold
}

// SessionProvider supplies the current SessionView atomically without import coupling.
type SessionProvider interface {
	Snapshot() SessionView
}

// LinkMaskProvider supplies the current 20-bit active directional link mask.
type LinkMaskProvider interface {
	ActiveLinkMask() uint32
}

// CSIWindowEmit is emitted at 2 Hz (every WindowCycles closed cycles) for ipc.
type CSIWindowEmit struct {
	TsUs              int64
	CrewID            *string
	Payload           contracts.CSIWindowPayload
	CalibrationActive bool
	CalibrationStepID string
}

// PeripheralMeta preserves node_id and reading age alongside contracts.PeripheralReading.
type PeripheralMeta struct {
	NodeID uint8
	Type   contracts.Peripheral
	Value  float64
	Unit   string
	TsUs   int64
	AgeMs  int64
}

// PeripheralSnapshotEmit is emitted at 1 Hz for ipc (CrewID is always nil for cabin environment).
type PeripheralSnapshotEmit struct {
	TsUs    int64
	CrewID  *string
	Payload contracts.PeripheralSnapshotPayload
	Meta    []PeripheralMeta
}

// IPCSink receives 2 Hz CSI windows and 1 Hz peripheral snapshots non-blockingly.
type IPCSink interface {
	TrySendCSIWindow(msg CSIWindowEmit) bool
	TrySendPeripheralSnapshot(msg PeripheralSnapshotEmit) bool
}

// StoreTelemetryRecord is emitted at 1 Hz (decimated) for store telemetry_timeseries.
type StoreTelemetryRecord struct {
	TsUs        int64
	CrewID      *string
	MissionMode contracts.MissionMode
	AIReady     bool
	Vitals      contracts.VitalsData
	Environment contracts.EnvironmentData
	Inference   *contracts.AIInferencePayload
}

// StorePeripheralRecord is emitted at 1 Hz for store peripheral_readings.
type StorePeripheralRecord struct {
	TsUs     int64
	CrewID   *string
	Readings []PeripheralMeta
}

// StoreAlertRecord is emitted on alert transitions for store alerts_audit (+ outbox when WriteOutbox is true).
type StoreAlertRecord struct {
	TsUs        int64
	CrewID      *string
	Alert       contracts.AlertEventPayload
	WriteOutbox bool
}

// StoreCSIBlobRecord is emitted only on calibration windows or RED alert 30 s dumps.
type StoreCSIBlobRecord struct {
	TsUs              int64
	CrewID            *string
	CycleSeqFirst     uint32
	Reason            string
	CalibrationStepID string
	Window            *contracts.CSIWindowPayload
	Samples           []LinkSample
}

// StoreSink receives decimated 1 Hz records and event-driven alerts/CSI blobs.
type StoreSink interface {
	EmitTelemetry1Hz(rec StoreTelemetryRecord) bool
	EmitPeripherals1Hz(rec StorePeripheralRecord) bool
	EmitAlert(rec StoreAlertRecord) bool
	EmitCSIBlob(rec StoreCSIBlobRecord) bool
}

// ClosedCycleInfo summarizes the most recently closed TDM cycle.
type ClosedCycleInfo struct {
	CycleSeq     uint32
	ExpectedMask uint32
	ReceivedMask uint32
	Complete     bool
	ClosedAt     time.Time
}

// Metrics holds pipeline operational counters.
type Metrics struct {
	FramesReceived      uint64
	InvalidFrames       uint64
	LateFrames          uint64
	CyclesClosed        uint64
	PartialCycles       uint64
	WindowsEmitted      uint64
	IPCDropped          uint64
	PeripheralSnapshots uint64
	StoreRecords        uint64
	StoreDropped        uint64
	AlertsEmitted       uint64
	EventsDropped       uint64
	InferencesApplied   uint64
	SelfExamsApplied    uint64
}

// Config configures pipeline timing and thresholds.
type Config struct {
	CycleGrace      time.Duration
	WindowCycles    int
	Emit1HzInterval time.Duration
	SelfExamTTL     time.Duration
	DefaultLinkMask uint32
	Now             func() time.Time
}

// Deps wires external decoupled channels, providers, and sinks into Pipeline.
type Deps struct {
	DataCh      <-chan DataMsg
	InferenceCh <-chan contracts.AIInferencePayload
	SelfExamCh  <-chan SelfExamInput
	Session     SessionProvider
	LinkMask    LinkMaskProvider
	IPC         IPCSink
	Store       StoreSink
	EventCh     chan<- contracts.AlertEventPayload
	Latest      *atomic.Pointer[contracts.TelemetrySnapshot]
}
