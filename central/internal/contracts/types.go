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
	V           int                 `json:"v"`
	Type        UDPMsgType          `json:"type"`
	NodeID      uint8               `json:"node_id"`
	SlotID      uint8               `json:"slot_id"`
	Mode        MissionMode         `json:"mode"`
	TimestampUs int64               `json:"timestamp_us"`
	CycleSeq    uint32              `json:"cycle_seq"` // P1
	Peripherals []PeripheralReading `json:"peripherals,omitempty"`
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
