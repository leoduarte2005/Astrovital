// Package contracts defines types and enums matching contracts/ 1:1.
// This package must not import any other internal package.
package contracts

// MissionMode mirrors contracts/enums/ mission_mode.
type MissionMode string

const (
	ModeCabinTomography        MissionMode = "MODE_CABIN_TOMOGRAPHY"
	ModeRestVitals             MissionMode = "MODE_REST_VITALS"
	ModeCountermeasureExercise MissionMode = "MODE_COUNTERMEASURE_EXERCISE"
	ModeRadiationAlert         MissionMode = "MODE_RADIATION_ALERT"
)

func (m MissionMode) IsValid() bool {
	switch m {
	case ModeCabinTomography, ModeRestVitals, ModeCountermeasureExercise, ModeRadiationAlert:
		return true
	default:
		return false
	}
}

// Subsystem mirrors contracts/enums/ subsystem.
type Subsystem string

const (
	SubsystemCardiovascularFluids     Subsystem = "CARDIOVASCULAR_FLUIDS"
	SubsystemRespiratoryAtmosphere    Subsystem = "RESPIRATORY_ATMOSPHERE"
	SubsystemNeuroOcularSANS          Subsystem = "NEURO_OCULAR_SANS"
	SubsystemMusculoskeletalPosture   Subsystem = "MUSCULOSKELETAL_POSTURE"
	SubsystemImmuneHematoNutrition    Subsystem = "IMMUNE_HEMATO_NUTRITION"
	SubsystemNeurobehavioralRadiation Subsystem = "NEUROBEHAVIORAL_RADIATION"
)

func (s Subsystem) IsValid() bool {
	switch s {
	case SubsystemCardiovascularFluids,
		SubsystemRespiratoryAtmosphere,
		SubsystemNeuroOcularSANS,
		SubsystemMusculoskeletalPosture,
		SubsystemImmuneHematoNutrition,
		SubsystemNeurobehavioralRadiation:
		return true
	default:
		return false
	}
}

// Severity mirrors contracts/enums/ severity.
type Severity string

const (
	SeverityGreen  Severity = "GREEN"
	SeverityYellow Severity = "YELLOW"
	SeverityRed    Severity = "RED"
)

func (s Severity) IsValid() bool {
	switch s {
	case SeverityGreen, SeverityYellow, SeverityRed:
		return true
	default:
		return false
	}
}

// Escalation mirrors contracts/enums/ escalation.
type Escalation string

const (
	EscalationLocal           Escalation = "LOCAL"
	EscalationCrew            Escalation = "CREW"
	EscalationStoreAndForward Escalation = "STORE_AND_FORWARD"
)

func (e Escalation) IsValid() bool {
	switch e {
	case EscalationLocal, EscalationCrew, EscalationStoreAndForward:
		return true
	default:
		return false
	}
}

// UDPMsgType mirrors contracts/enums/ udp_msg_type.
type UDPMsgType string

const (
	UDPMsgClusterSync    UDPMsgType = "CLUSTER_SYNC"
	UDPMsgModeCmd        UDPMsgType = "MODE_CMD"
	UDPMsgNodeHello      UDPMsgType = "NODE_HELLO"
	UDPMsgHeartbeat      UDPMsgType = "HEARTBEAT"
	UDPMsgCSIFrame       UDPMsgType = "CSI_FRAME"
	UDPMsgPeripheralData UDPMsgType = "PERIPHERAL_DATA"
)

func (t UDPMsgType) IsValid() bool {
	switch t {
	case UDPMsgClusterSync, UDPMsgModeCmd, UDPMsgNodeHello, UDPMsgHeartbeat, UDPMsgCSIFrame, UDPMsgPeripheralData:
		return true
	default:
		return false
	}
}

// IPCMsgType mirrors contracts/enums/ ipc_msg_type.
type IPCMsgType string

const (
	IPCMsgCSIWindow           IPCMsgType = "CSI_WINDOW"
	IPCMsgPeripheralSnapshot  IPCMsgType = "PERIPHERAL_SNAPSHOT"
	IPCMsgSetActiveCrew       IPCMsgType = "SET_ACTIVE_CREW"
	IPCMsgCrewAck             IPCMsgType = "CREW_ACK"
	IPCMsgAIInference         IPCMsgType = "AI_INFERENCE"
	IPCMsgChatCorrelateReq    IPCMsgType = "CHAT_CORRELATE_REQ"
	IPCMsgChatCorrelateResp   IPCMsgType = "CHAT_CORRELATE_RESP"
	IPCMsgCalibrationStep     IPCMsgType = "CALIBRATION_STEP"
	IPCMsgCalibrationFeedback IPCMsgType = "CALIBRATION_FEEDBACK"
)

func (t IPCMsgType) IsValid() bool {
	switch t {
	case IPCMsgCSIWindow,
		IPCMsgPeripheralSnapshot,
		IPCMsgSetActiveCrew,
		IPCMsgCrewAck,
		IPCMsgAIInference,
		IPCMsgChatCorrelateReq,
		IPCMsgChatCorrelateResp,
		IPCMsgCalibrationStep,
		IPCMsgCalibrationFeedback:
		return true
	default:
		return false
	}
}

// WSMsgType mirrors contracts/enums/ ws_msg_type + ERROR (P4).
type WSMsgType string

const (
	WSMsgTelemetryFrame      WSMsgType = "TELEMETRY_FRAME"
	WSMsgAlertEvent          WSMsgType = "ALERT_EVENT"
	WSMsgCrewState           WSMsgType = "CREW_STATE"
	WSMsgClusterStatus       WSMsgType = "CLUSTER_STATUS"
	WSMsgChatReply           WSMsgType = "CHAT_REPLY"
	WSMsgCalibrationFeedback WSMsgType = "CALIBRATION_FEEDBACK"
	WSMsgSetCrew             WSMsgType = "SET_CREW"
	WSMsgChatMsg             WSMsgType = "CHAT_MSG"
	WSMsgSelfExam            WSMsgType = "SELF_EXAM"
	WSMsgCalibrationStep     WSMsgType = "CALIBRATION_STEP"
	WSMsgError               WSMsgType = "ERROR" // P4
)

func (t WSMsgType) IsValid() bool {
	switch t {
	case WSMsgTelemetryFrame,
		WSMsgAlertEvent,
		WSMsgCrewState,
		WSMsgClusterStatus,
		WSMsgChatReply,
		WSMsgCalibrationFeedback,
		WSMsgSetCrew,
		WSMsgChatMsg,
		WSMsgSelfExam,
		WSMsgCalibrationStep,
		WSMsgError:
		return true
	default:
		return false
	}
}

// Peripheral mirrors contracts/enums/ peripheral.
type Peripheral string

const (
	PeripheralMAX30102 Peripheral = "MAX30102"
	PeripheralBME280   Peripheral = "BME280"
	PeripheralSCD40    Peripheral = "SCD40"
)

func (p Peripheral) IsValid() bool {
	switch p {
	case PeripheralMAX30102, PeripheralBME280, PeripheralSCD40:
		return true
	default:
		return false
	}
}

// NodeState mirrors contracts/enums/ node_state.
type NodeState string

const (
	NodeStateDiscovered NodeState = "DISCOVERED"
	NodeStateSyncing    NodeState = "SYNCING"
	NodeStateActive     NodeState = "ACTIVE"
	NodeStateSuspect    NodeState = "SUSPECT"
	NodeStateLost       NodeState = "LOST"
)

func (s NodeState) IsValid() bool {
	switch s {
	case NodeStateDiscovered, NodeStateSyncing, NodeStateActive, NodeStateSuspect, NodeStateLost:
		return true
	default:
		return false
	}
}
