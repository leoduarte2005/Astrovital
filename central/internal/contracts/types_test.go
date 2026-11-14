package contracts

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestEnumValidation(t *testing.T) {
	roundTrip := func(v any, dst any) {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatalf("marshal %v: %v", v, err)
		}
		if err := json.Unmarshal(b, dst); err != nil {
			t.Fatalf("unmarshal %s: %v", string(b), err)
		}
	}

	for _, m := range []MissionMode{
		ModeCabinTomography, ModeRestVitals, ModeCountermeasureExercise, ModeRadiationAlert,
	} {
		var got MissionMode
		roundTrip(m, &got)
		if got != m || !got.IsValid() {
			t.Fatalf("MissionMode round-trip failed: got %q want %q", got, m)
		}
	}
	if MissionMode("").IsValid() || MissionMode("INVALID").IsValid() {
		t.Fatal("expected invalid MissionMode")
	}

	for _, s := range []Subsystem{
		SubsystemCardiovascularFluids, SubsystemRespiratoryAtmosphere, SubsystemNeuroOcularSANS,
		SubsystemMusculoskeletalPosture, SubsystemImmuneHematoNutrition, SubsystemNeurobehavioralRadiation,
	} {
		var got Subsystem
		roundTrip(s, &got)
		if got != s || !got.IsValid() {
			t.Fatalf("Subsystem round-trip failed: got %q want %q", got, s)
		}
	}
	if Subsystem("").IsValid() || Subsystem("UNKNOWN").IsValid() {
		t.Fatal("expected invalid Subsystem")
	}

	for _, sv := range []Severity{SeverityGreen, SeverityYellow, SeverityRed} {
		var got Severity
		roundTrip(sv, &got)
		if got != sv || !got.IsValid() {
			t.Fatalf("Severity round-trip failed: got %q want %q", got, sv)
		}
	}
	if Severity("").IsValid() || Severity("ORANGE").IsValid() {
		t.Fatal("expected invalid Severity")
	}

	for _, e := range []Escalation{EscalationLocal, EscalationCrew, EscalationStoreAndForward} {
		var got Escalation
		roundTrip(e, &got)
		if got != e || !got.IsValid() {
			t.Fatalf("Escalation round-trip failed: got %q want %q", got, e)
		}
	}
	if Escalation("").IsValid() || Escalation("GROUND").IsValid() {
		t.Fatal("expected invalid Escalation")
	}

	for _, u := range []UDPMsgType{
		UDPMsgClusterSync, UDPMsgModeCmd, UDPMsgNodeHello, UDPMsgHeartbeat, UDPMsgCSIFrame, UDPMsgPeripheralData,
	} {
		var got UDPMsgType
		roundTrip(u, &got)
		if got != u || !got.IsValid() {
			t.Fatalf("UDPMsgType round-trip failed: got %q want %q", got, u)
		}
	}
	if UDPMsgType("").IsValid() || UDPMsgType("PING").IsValid() {
		t.Fatal("expected invalid UDPMsgType")
	}

	for _, i := range []IPCMsgType{
		IPCMsgCSIWindow, IPCMsgPeripheralSnapshot, IPCMsgSetActiveCrew, IPCMsgCrewAck,
		IPCMsgAIInference, IPCMsgChatCorrelateReq, IPCMsgChatCorrelateResp, IPCMsgCalibrationFeedback,
	} {
		var got IPCMsgType
		roundTrip(i, &got)
		if got != i || !got.IsValid() {
			t.Fatalf("IPCMsgType round-trip failed: got %q want %q", got, i)
		}
	}
	if IPCMsgType("").IsValid() || IPCMsgType("NOOP").IsValid() {
		t.Fatal("expected invalid IPCMsgType")
	}

	for _, w := range []WSMsgType{
		WSMsgTelemetryFrame, WSMsgAlertEvent, WSMsgCrewState, WSMsgClusterStatus,
		WSMsgChatReply, WSMsgCalibrationFeedback, WSMsgSetCrew, WSMsgChatMsg,
		WSMsgSelfExam, WSMsgCalibrationStep, WSMsgError,
	} {
		var got WSMsgType
		roundTrip(w, &got)
		if got != w || !got.IsValid() {
			t.Fatalf("WSMsgType round-trip failed: got %q want %q", got, w)
		}
	}
	if WSMsgType("").IsValid() || WSMsgType("BAD").IsValid() {
		t.Fatal("expected invalid WSMsgType")
	}

	for _, p := range []Peripheral{PeripheralMAX30102, PeripheralBME280, PeripheralSCD40} {
		var got Peripheral
		roundTrip(p, &got)
		if got != p || !got.IsValid() {
			t.Fatalf("Peripheral round-trip failed: got %q want %q", got, p)
		}
	}
	if Peripheral("").IsValid() || Peripheral("MPU6050").IsValid() {
		t.Fatal("expected invalid Peripheral")
	}

	for _, ns := range []NodeState{
		NodeStateDiscovered, NodeStateSyncing, NodeStateActive, NodeStateSuspect, NodeStateLost,
	} {
		var got NodeState
		roundTrip(ns, &got)
		if got != ns || !got.IsValid() {
			t.Fatalf("NodeState round-trip failed: got %q want %q", got, ns)
		}
	}
	if NodeState("").IsValid() || NodeState("DEAD").IsValid() {
		t.Fatal("expected invalid NodeState")
	}
}

func TestWSEnvelopeRoundTripAndValidation(t *testing.T) {
	crew := "astronaut_01"
	cid := "msg-42"
	env, err := NewWSEnvelope(WSMsgError, 1700000000000000, &crew, &cid, ErrorPayload{
		Code:        "BAD_SCHEMA",
		Message:     "invalid payload",
		ClientMsgID: &cid,
	})
	if err != nil {
		t.Fatalf("NewWSEnvelope error: %v", err)
	}

	b, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded WSEnvelope
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if err := decoded.Validate(); err != nil {
		t.Fatalf("Validate error: %v", err)
	}
	if decoded.V != Version || decoded.Type != WSMsgError {
		t.Fatalf("unexpected decoded header: %+v", decoded)
	}
	if decoded.ClientMsgID == nil || *decoded.ClientMsgID != cid {
		t.Fatalf("client_msg_id lost: %v", decoded.ClientMsgID)
	}
	if decoded.CrewID == nil || *decoded.CrewID != crew {
		t.Fatalf("crew_id lost: %v", decoded.CrewID)
	}

	var ep ErrorPayload
	if err := json.Unmarshal(decoded.Payload, &ep); err != nil {
		t.Fatalf("unmarshal ErrorPayload: %v", err)
	}
	if ep.Code != "BAD_SCHEMA" {
		t.Fatalf("unexpected ErrorPayload: %+v", ep)
	}
}

func TestWSEnvelopeVersionValidation(t *testing.T) {
	cases := []struct {
		name string
		raw  string
	}{
		{"v0", `{"v":0,"type":"SET_CREW","ts_us":1,"crew_id":null,"payload":{"crew_id":"a"}}`},
		{"v2", `{"v":2,"type":"SET_CREW","ts_us":1,"crew_id":null,"payload":{"crew_id":"a"}}`},
		{"bad_type", `{"v":1,"type":"UNKNOWN","ts_us":1,"crew_id":null,"payload":{}}`},
		{"empty_payload", `{"v":1,"type":"SET_CREW","ts_us":1,"crew_id":null}`},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var env WSEnvelope
			if err := json.Unmarshal([]byte(tc.raw), &env); err != nil {
				t.Fatalf("unmarshal: %v", err)
			}
			if err := env.Validate(); err == nil {
				t.Fatalf("expected validation error for %s", tc.name)
			}
		})
	}

	ipcCases := []struct {
		name string
		raw  string
	}{
		{"v2", `{"v":2,"type":"SET_ACTIVE_CREW","ts_us":1,"crew_id":null,"payload":{"crew_id":"a"}}`},
		{"bad_type", `{"v":1,"type":"UNKNOWN","ts_us":1,"crew_id":null,"payload":{}}`},
		{"empty_payload", `{"v":1,"type":"SET_ACTIVE_CREW","ts_us":1,"crew_id":null}`},
	}
	for _, tc := range ipcCases {
		t.Run("ipc_"+tc.name, func(t *testing.T) {
			var env IPCEnvelope
			if err := json.Unmarshal([]byte(tc.raw), &env); err != nil {
				t.Fatalf("unmarshal: %v", err)
			}
			if err := env.Validate(); err == nil {
				t.Fatalf("expected IPC validation error for %s", tc.name)
			}
		})
	}
}

func TestCrewIDSerializesAsNullWhenEmpty(t *testing.T) {
	empty := ""
	wsNil, err := NewWSEnvelope(WSMsgCrewState, 1, nil, nil, CrewStatePayload{MissionMode: ModeCabinTomography})
	if err != nil {
		t.Fatal(err)
	}
	bNil, _ := json.Marshal(wsNil)
	if !strings.Contains(string(bNil), `"crew_id":null`) {
		t.Fatalf("expected crew_id:null for nil, got %s", string(bNil))
	}

	wsEmpty, err := NewWSEnvelope(WSMsgCrewState, 1, &empty, nil, CrewStatePayload{MissionMode: ModeCabinTomography})
	if err != nil {
		t.Fatal(err)
	}
	bEmpty, _ := json.Marshal(wsEmpty)
	if !strings.Contains(string(bEmpty), `"crew_id":null`) {
		t.Fatalf("expected crew_id:null for empty string, got %s", string(bEmpty))
	}

	ipcEmpty, err := NewIPCEnvelope(IPCMsgCSIWindow, 1, &empty, nil, map[string]any{"ok": true})
	if err != nil {
		t.Fatal(err)
	}
	bIPC, _ := json.Marshal(ipcEmpty)
	if !strings.Contains(string(bIPC), `"crew_id":null`) {
		t.Fatalf("expected IPC crew_id:null for empty string, got %s", string(bIPC))
	}
}

func TestIPCEnvelopeRoundTripWithReqID(t *testing.T) {
	crew := "astronaut_02"
	reqID := uint64(77)
	env, err := NewIPCEnvelope(IPCMsgSetActiveCrew, 1700000001000000, &crew, &reqID, SetCrewPayload{
		CrewID: crew,
	})
	if err != nil {
		t.Fatalf("NewIPCEnvelope error: %v", err)
	}

	b, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded IPCEnvelope
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if err := decoded.Validate(); err != nil {
		t.Fatalf("Validate error: %v", err)
	}
	if decoded.ReqID == nil || *decoded.ReqID != reqID {
		t.Fatalf("req_id mismatch: %v", decoded.ReqID)
	}

	decoded.V = 99
	if err := decoded.Validate(); err == nil {
		t.Fatal("expected version error for v=99")
	}
}

func TestUDPHeaderRoundTripWithCycleSeq(t *testing.T) {
	hdr := UDPHeader{
		V:           1,
		Type:        UDPMsgCSIFrame,
		NodeID:      2,
		SlotID:      2,
		Mode:        ModeRestVitals,
		TimestampUs: 1700000002000000,
		CycleSeq:    4201,
		Peripherals: []PeripheralReading{
			{
				Type:        PeripheralSCD40,
				Value:       615.5,
				Unit:        "ppm",
				TimestampUs: 1700000002000000,
			},
		},
	}

	b, err := json.Marshal(hdr)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded UDPHeader
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if err := decoded.Validate(); err != nil {
		t.Fatalf("Validate error: %v", err)
	}
	if decoded.CycleSeq != 4201 {
		t.Fatalf("cycle_seq mismatch: %d", decoded.CycleSeq)
	}

	decoded.V = 0
	if err := decoded.Validate(); err == nil {
		t.Fatal("expected version validation error")
	}
}
