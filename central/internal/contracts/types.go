package contracts

import (
	"encoding/json"
	"fmt"
)

// Version is the protocol version for all v1 contracts.
const Version = 1

// WSEnvelope is the bidirectional WebSocket envelope (:8000/ws).
// Includes optional client_msg_id (P4).
type WSEnvelope struct {
	V           int             `json:"v"`
	Type        WSMsgType       `json:"type"`
	TsUs        int64           `json:"ts_us"`
	CrewID      *string         `json:"crew_id"`
	ClientMsgID *string         `json:"client_msg_id,omitempty"` // P4
	Payload     json.RawMessage `json:"payload"`
}

func (e *WSEnvelope) Validate() error {
	if e.V != Version {
		return fmt.Errorf("invalid WS version: %d (want %d)", e.V, Version)
	}
	if !e.Type.IsValid() {
		return fmt.Errorf("invalid WS type: %q", e.Type)
	}
	if len(e.Payload) == 0 {
		return fmt.Errorf("empty WS payload")
	}
	return nil
}

// IPCEnvelope is the TCP :5006 envelope between Central and Edge AI.
// Includes optional req_id (P3).
type IPCEnvelope struct {
	V       int             `json:"v"`
	Type    IPCMsgType      `json:"type"`
	TsUs    int64           `json:"ts_us"`
	CrewID  *string         `json:"crew_id"`
	ReqID   *uint64         `json:"req_id,omitempty"` // P3
	Payload json.RawMessage `json:"payload"`
}

func (e *IPCEnvelope) Validate() error {
	if e.V != Version {
		return fmt.Errorf("invalid IPC version: %d (want %d)", e.V, Version)
	}
	if !e.Type.IsValid() {
		return fmt.Errorf("invalid IPC type: %q", e.Type)
	}
	if len(e.Payload) == 0 {
		return fmt.Errorf("empty IPC payload")
	}
	return nil
}

// UDPHeader is the compact JSON header for UDP :5005 datagrams.
// Binary csi_payload follows '\n' separator when present (P6), and cycle_seq links TDM frames (P1).
type UDPHeader struct {
	V                    int                 `json:"v"`
	Type                 UDPMsgType          `json:"type"`
	NodeID               uint8               `json:"node_id"`
	SlotID               uint8               `json:"slot_id"`
	Mode                 MissionMode         `json:"mode"`
	TimestampUs          int64               `json:"timestamp_us"`
	CycleSeq             uint32              `json:"cycle_seq"` // P1
	MAC                  string              `json:"mac,omitempty"`
	RSSIDbm              int                 `json:"rssi_dbm,omitempty"`
	FWVersion            string              `json:"fw_version,omitempty"`
	SupportedPeripherals []Peripheral        `json:"supported_peripherals,omitempty"`
	Peripherals          []PeripheralReading `json:"peripherals,omitempty"`
}

func (h *UDPHeader) Validate() error {
	if h.V != Version {
		return fmt.Errorf("invalid UDP version: %d (want %d)", h.V, Version)
	}
	if !h.Type.IsValid() {
		return fmt.Errorf("invalid UDP type: %q", h.Type)
	}
	if h.Mode != "" && !h.Mode.IsValid() {
		return fmt.Errorf("invalid mission_mode: %q", h.Mode)
	}
	for _, p := range h.Peripherals {
		if !p.Type.IsValid() {
			return fmt.Errorf("invalid peripheral: %q", p.Type)
		}
	}
	return nil
}

// PeripheralReading represents an I2C sensor reading attached to UDP or snapshots.
type PeripheralReading struct {
	Type        Peripheral `json:"type"`
	Value       float64    `json:"value"`
	Unit        string     `json:"unit"`
	TimestampUs int64      `json:"timestamp_us"`
}

// TelemetrySnapshot holds the latest telemetry state shared with httpws via atomic.Pointer.
type TelemetrySnapshot struct {
	TsUs        int64             `json:"ts_us"`
	CrewID      *string           `json:"crew_id"`
	MissionMode MissionMode       `json:"mission_mode"`
	AIReady     bool              `json:"ai_ready"`
	Vitals      VitalsData        `json:"vitals"`
	Environment EnvironmentData   `json:"environment"`
	Subsystems  [6]SubsystemState `json:"subsystems"`
}

// VitalsData contains crew biometric readings.
type VitalsData struct {
	HeartRateBpm    float64 `json:"heart_rate_bpm"`
	HRVMs           float64 `json:"hrv_ms"`
	RespRateBpm     float64 `json:"resp_rate_bpm"`
	SpO2Pct         float64 `json:"spo2_pct"`
	Posture         string  `json:"posture"`
	ConfidenceScore float64 `json:"confidence_score"`
}

// EnvironmentData contains cabin atmosphere readings.
type EnvironmentData struct {
	CO2Ppm      float64 `json:"co2_ppm"`
	TempC       float64 `json:"temp_c"`
	HumidityPct float64 `json:"humidity_pct"`
	PressureHpa float64 `json:"pressure_hpa"`
}

// SubsystemState holds status for one of the 6 physiological subsystems.
type SubsystemState struct {
	Subsystem Subsystem `json:"subsystem"`
	Severity  Severity  `json:"severity"`
	Message   string    `json:"message,omitempty"`
}

// ClusterSnapshot holds cluster state for CLUSTER_STATUS.
type ClusterSnapshot struct {
	TsUs           int64        `json:"ts_us"`
	Nodes          []NodeStatus `json:"nodes"`
	ActiveLinks    int          `json:"active_links"`
	TotalLinks     int          `json:"total_links"`
	AILink         string       `json:"ai_link"`
	DroppedFrames  uint64       `json:"dropped_frames"`
	DroppedCtrl    uint64       `json:"dropped_ctrl"`
	DroppedWindows uint64       `json:"dropped_windows"`
}

// NodeStatus represents one ESP32-S3 node in CLUSTER_STATUS.
type NodeStatus struct {
	NodeID      uint8        `json:"node_id"`
	MAC         string       `json:"mac"`
	State       NodeState    `json:"state"`
	Slot        int          `json:"slot"`
	Peripherals []Peripheral `json:"peripherals"`
	LastSeenUs  int64        `json:"last_seen_us"`
	RSSIDbm     int          `json:"rssi_dbm,omitempty"`
}

// CrewSummary is a lightweight crew profile record returned by store/REST.
type CrewSummary struct {
	CrewID              string `json:"crew_id"`
	Name                string `json:"name"`
	Role                string `json:"role,omitempty"`
	MissionDay          int    `json:"mission_day,omitempty"`
	CalibrationRequired bool   `json:"calibration_required"`
}

// --- IPC Payloads ---

// CSIWindowPayload sent C→IA at 2 Hz (5 cycles aggregated).
type CSIWindowPayload struct {
	CycleSeqFirst  uint32      `json:"cycle_seq_first"`
	ActiveLinkMask uint32      `json:"active_link_mask"` // 20-bit mask of active (tx,rx) pairs
	Mode           MissionMode `json:"mode"`
	Links          []CSILink   `json:"links"`
	QualityPerLink []float64   `json:"quality_per_link,omitempty"`
}

// CSILink represents I/Q samples from one (tx,rx) pair over 5 cycles.
type CSILink struct {
	TxNodeID   uint8      `json:"tx_node_id"`
	RxNodeID   uint8      `json:"rx_node_id"`
	IQSamples  []IQSample `json:"iq_samples"`
	RSSIDbm    int        `json:"rssi_dbm"`
	NoiseFloor float64    `json:"noise_floor"`
}

// IQSample is one complex CSI sample.
type IQSample struct {
	Real      float64 `json:"real"`
	Imaginary float64 `json:"imag"`
}

// PeripheralSnapshotPayload sent C→IA at 1 Hz.
type PeripheralSnapshotPayload struct {
	Readings    []PeripheralReading `json:"readings"`
	TimestampUs int64               `json:"timestamp_us"`
}

// SetActiveCrewPayload sent C→IA in IPC (request).
type SetActiveCrewPayload struct {
	CrewID       string               `json:"crew_id"`
	BaselinePath string               `json:"baseline_path,omitempty"`
	Thresholds   map[string]Threshold `json:"thresholds,omitempty"`
}

// Threshold represents one alert threshold for a subsystem/metric.
type Threshold struct {
	MetricName string  `json:"metric_name"`
	YellowHigh float64 `json:"yellow_high"`
	RedHigh    float64 `json:"red_high"`
	YellowLow  float64 `json:"yellow_low,omitempty"`
	RedLow     float64 `json:"red_low,omitempty"`
}

// CrewAckPayload sent IA→C (response to SET_ACTIVE_CREW).
type CrewAckPayload struct {
	OK            bool   `json:"ok"`
	BaselineFound bool   `json:"baseline_found"`
	Error         string `json:"error,omitempty"`
}

// AIInferencePayload sent IA→C at ~2 Hz.
type AIInferencePayload struct {
	CycleSeqFirst uint32  `json:"cycle_seq_first"` // Links back to CSI_WINDOW
	Posture       string  `json:"posture"`
	RespirationHz float64 `json:"respiration_hz"`
	HeartRateBpm  float64 `json:"heart_rate_bpm"`
	HRVMs         float64 `json:"hrv_ms"`
	AnomalyScore  float64 `json:"anomaly_score"`
	Confidence    float64 `json:"confidence"`
}

// ChatCorrelateReqPayload sent C→IA (request).
type ChatCorrelateReqPayload struct {
	Text            string               `json:"text"`
	CrewID          string               `json:"crew_id,omitempty"`
	Profile         *CrewProfile         `json:"profile,omitempty"`
	Thresholds      map[string]Threshold `json:"thresholds,omitempty"`
	LastPeripherals []PeripheralReading  `json:"last_peripherals,omitempty"`
	LastInference   *AIInferencePayload  `json:"last_inference,omitempty"`
	Summary24h      string               `json:"summary_24h,omitempty"`
	RecentHistory   []ChatMessage        `json:"recent_history,omitempty"`
}

// CrewProfile is a minimal crew record for IPC context.
type CrewProfile struct {
	CrewID     string `json:"crew_id"`
	Name       string `json:"name"`
	Role       string `json:"role,omitempty"`
	MissionDay int    `json:"mission_day,omitempty"`
	Age        int    `json:"age,omitempty"`
}

// ChatMessage is one record in chat history.
type ChatMessage struct {
	SentAt  int64  `json:"sent_at_us"`
	Role    string `json:"role"` // "user" | "assistant"
	Content string `json:"content"`
}

// ChatCorrelateRespPayload sent IA→C (response).
type ChatCorrelateRespPayload struct {
	MemoryUpdates          []ClinicalMemoryUpdate `json:"memory_updates,omitempty"`
	ModelStatus            string                 `json:"model_status,omitempty"`
	Text                   string                 `json:"text"`
	Differentials          []string               `json:"differentials,omitempty"`
	Evidence               []string               `json:"evidence,omitempty"`
	Countermeasures        []string               `json:"countermeasures,omitempty"`
	SourceIDs              []string               `json:"source_ids,omitempty"`
	Escalation             Escalation             `json:"escalation"`
	Disclaimer             string                 `json:"disclaimer,omitempty"`
	DisambiguationQuestion string                 `json:"disambiguation_question,omitempty"`
	Actions                []string               `json:"actions,omitempty"`
}

// CalibrationFeedbackPayload sent IA→C (response).
type CalibrationFeedbackPayload struct {
	BaselineUpdate json.RawMessage `json:"baseline_update,omitempty"`
	StepID         string          `json:"step_id"`
	Progress       int             `json:"progress"` // 0-100
	Quality        float64         `json:"quality"`
	Error          string          `json:"error,omitempty"`
}

type ClinicalMemoryUpdate struct {
	FactType   string  `json:"fact_type"`
	FactKey    string  `json:"fact_key"`
	FactValue  string  `json:"fact_value"`
	Confidence float64 `json:"confidence"`
	SourceRole string  `json:"source_role"`
}

// --- REST Response Payloads ---

// TimeseriesResponse returned by GET /api/crew/{id}/timeseries.
type TimeseriesResponse struct {
	CrewID  string            `json:"crew_id"`
	StartUs int64             `json:"start_us"`
	EndUs   int64             `json:"end_us"`
	Buckets []TelemetryBucket `json:"buckets"`
}

// TelemetryBucket is one time-aggregated snapshot.
type TelemetryBucket struct {
	TsUs        int64           `json:"ts_us"`
	Vitals      VitalsData      `json:"vitals"`
	Environment EnvironmentData `json:"environment"`
}

// ProtocolDTO represents one clinical protocol/guideline.
type ProtocolDTO struct {
	ProtocolID   string          `json:"protocol_id"`
	Name         string          `json:"name"`
	Subsystems   []Subsystem     `json:"subsystems"`
	Description  string          `json:"description,omitempty"`
	Steps        []string        `json:"steps,omitempty"`
	DurationS    *int64          `json:"duration_s,omitempty"`
	Materials    []string        `json:"materials,omitempty"`
	RichSteps    json.RawMessage `json:"rich_steps,omitempty"`
	ResultSchema json.RawMessage `json:"result_schema,omitempty"`
	LinkedRisks  []string        `json:"linked_risks,omitempty"`
}

// AlertRecord is one alert event from the audit log.
type AlertRecord struct {
	AlertID        string     `json:"alert_id"`
	TsUs           int64      `json:"ts_us"`
	CrewID         *string    `json:"crew_id,omitempty"`
	Subsystem      Subsystem  `json:"subsystem"`
	Severity       Severity   `json:"severity"`
	Message        string     `json:"message"`
	Countermeasure string     `json:"countermeasure,omitempty"`
	Escalation     Escalation `json:"escalation"`
	Handled        bool       `json:"handled"`
}

// OutboxRecord is one message in store-and-forward queue.
type OutboxRecord struct {
	OutboxID    string    `json:"outbox_id"`
	TsUs        int64     `json:"ts_us"`
	Subsystem   Subsystem `json:"subsystem"`
	Severity    Severity  `json:"severity"`
	Message     string    `json:"message"`
	Destination string    `json:"destination,omitempty"`
	Sent        bool      `json:"sent"`
}

// DevScenarioReq is the request body for POST /api/dev/scenario.
type DevScenarioReq struct {
	Scenario string `json:"scenario"`
	Seed     int64  `json:"seed,omitempty"`
}
