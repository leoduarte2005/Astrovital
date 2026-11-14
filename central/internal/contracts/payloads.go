package contracts

import "encoding/json"

// TelemetryFramePayload is sent over WS at 2-10 Hz.
type TelemetryFramePayload struct {
	Vitals      VitalsData       `json:"vitals"`
	Environment EnvironmentData  `json:"environment"`
	Subsystems  []SubsystemState `json:"subsystems"`
	AIReady     bool             `json:"ai_ready"`
}

// AlertEventPayload is sent immediately over WS on alert transitions.
type AlertEventPayload struct {
	Subsystem      Subsystem  `json:"subsystem"`
	Severity       Severity   `json:"severity"`
	Message        string     `json:"message"`
	Countermeasure string     `json:"countermeasure"`
	Escalation     Escalation `json:"escalation"`
	SourceID       string     `json:"source_id"`
}

// CrewStatePayload is sent on WS connect and crew/mode/calibration changes.
type CrewStatePayload struct {
	CrewID              *string      `json:"crew_id"`
	Profile             *CrewSummary `json:"profile,omitempty"`
	MissionMode         MissionMode  `json:"mission_mode"`
	AIReady             bool         `json:"ai_ready"`
	CalibrationRequired bool         `json:"calibration_required"`
}

// ClusterStatusPayload is sent on WS connect, changes, and 1 Hz updates.
type ClusterStatusPayload struct {
	Nodes          []NodeStatus `json:"nodes"`
	ActiveLinks    int          `json:"active_links"`
	TotalLinks     int          `json:"total_links"`
	AILink         string       `json:"ai_link"`
	DroppedFrames  uint64       `json:"dropped_frames"`
	DroppedCtrl    uint64       `json:"dropped_ctrl"`
	DroppedWindows uint64       `json:"dropped_windows"`
}

// ErrorPayload is sent over WS when client message validation fails (P4).
type ErrorPayload struct {
	Code        string  `json:"code"`
	Message     string  `json:"message"`
	ClientMsgID *string `json:"client_msg_id,omitempty"`
}

// SetCrewPayload is received from WS client (SET_CREW).
type SetCrewPayload struct {
	CrewID string `json:"crew_id"`
}

// ChatMsgPayload is received from WS client (CHAT_MSG).
type ChatMsgPayload struct {
	Text string `json:"text"`
}

// ChatReplyPayload is sent to WS client (CHAT_REPLY).
// Optional differentials, disambiguation_question and actions keep v1 clients compatible.
type ChatReplyPayload struct {
	Text                   string     `json:"text"`
	Evidence               []string   `json:"evidence"`
	Countermeasures        []string   `json:"countermeasures"`
	SourceIDs              []string   `json:"source_ids"`
	Escalation             Escalation `json:"escalation"`
	Disclaimer             string     `json:"disclaimer"`
	Differentials          []string   `json:"differentials,omitempty"`
	DisambiguationQuestion string     `json:"disambiguation_question,omitempty"`
	Actions                []string   `json:"actions,omitempty"`
}

// SelfExamPayload is received from WS client (SELF_EXAM).
type SelfExamPayload struct {
	ExamType     string `json:"exam_type"`
	Result       string `json:"result"`
	Observations string `json:"observations,omitempty"`
}

// CalibrationStepPayload is received from WS client (CALIBRATION_STEP) and
// forwarded Central -> Edge AI over IPC (CALIBRATION_STEP request).
type CalibrationStepPayload struct {
	StepID     string `json:"step_id"`
	Action     string `json:"action"`
	DurationMs int    `json:"duration_ms,omitempty"`
}

// NewWSEnvelope marshals payload into a validated v1 WSEnvelope.
func NewWSEnvelope(msgType WSMsgType, tsUs int64, crewID *string, clientMsgID *string, payload any) (WSEnvelope, error) {
	if crewID != nil && *crewID == "" {
		crewID = nil
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return WSEnvelope{}, err
	}
	env := WSEnvelope{
		V:           Version,
		Type:        msgType,
		TsUs:        tsUs,
		CrewID:      crewID,
		ClientMsgID: clientMsgID,
		Payload:     raw,
	}
	if err := env.Validate(); err != nil {
		return WSEnvelope{}, err
	}
	return env, nil
}

// NewIPCEnvelope marshals payload into a validated v1 IPCEnvelope.
func NewIPCEnvelope(msgType IPCMsgType, tsUs int64, crewID *string, reqID *uint64, payload any) (IPCEnvelope, error) {
	if crewID != nil && *crewID == "" {
		crewID = nil
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return IPCEnvelope{}, err
	}
	env := IPCEnvelope{
		V:       Version,
		Type:    msgType,
		TsUs:    tsUs,
		CrewID:  crewID,
		ReqID:   reqID,
		Payload: raw,
	}
	if err := env.Validate(); err != nil {
		return IPCEnvelope{}, err
	}
	return env, nil
}
