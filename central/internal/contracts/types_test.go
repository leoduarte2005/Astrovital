package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"math"
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

func TestP6UDPDatagramWithCSIPayload(t *testing.T) {
	hdr := UDPHeader{
		V:           1,
		Type:        UDPMsgCSIFrame,
		NodeID:      1,
		SlotID:      0,
		Mode:        ModeCabinTomography,
		TimestampUs: 1700000000000000,
		CycleSeq:    100,
		MAC:         "02:ED:6E:00:00:01",
		RSSIDbm:     -45,
	}

	samples := []IQSample{
		{Real: 0.123, Imaginary: -0.456},
		{Real: 0.789, Imaginary: 0.012},
	}
	csiPart := EncodeCSIBinary(nil, 0, 1, -45, -90.5, samples)

	// Encode to UDP datagram
	datagram, err := EncodeUDPDatagram(nil, hdr, csiPart)
	if err != nil {
		t.Fatalf("EncodeUDPDatagram error: %v", err)
	}

	// Decode back
	decHdr, decCSI, err := DecodeUDPDatagram(datagram)
	if err != nil {
		t.Fatalf("DecodeUDPDatagram error: %v", err)
	}
	if decHdr.CycleSeq != hdr.CycleSeq {
		t.Fatalf("cycle_seq mismatch: %d != %d", decHdr.CycleSeq, hdr.CycleSeq)
	}
	if decHdr.MAC != hdr.MAC {
		t.Fatalf("MAC mismatch: %s != %s", decHdr.MAC, hdr.MAC)
	}

	// Decode CSI binary
	tx, rx, rssi, _, decSamples, err := DecodeCSIBinary(decCSI, nil)
	if err != nil {
		t.Fatalf("DecodeCSIBinary error: %v", err)
	}
	if tx != 0 || rx != 1 || rssi != -45 {
		t.Fatalf("CSI header mismatch: tx=%d rx=%d rssi=%d", tx, rx, rssi)
	}
	if len(decSamples) != len(samples) {
		t.Fatalf("sample count mismatch: %d != %d", len(decSamples), len(samples))
	}
	for i, s := range decSamples {
		// Allow small Q10 quantization loss
		if math.Abs(s.Real-samples[i].Real) > 0.002 || math.Abs(s.Imaginary-samples[i].Imaginary) > 0.002 {
			t.Fatalf("sample %d mismatch: %+v != %+v", i, s, samples[i])
		}
	}

	// Test reuse of buffers
	datagram2, err := EncodeUDPDatagram(datagram[:0], hdr, csiPart)
	if err != nil {
		t.Fatalf("reuse EncodeUDPDatagram error: %v", err)
	}
	if !bytes.Equal(datagram2, datagram) {
		t.Fatalf("reused datagram differs")
	}
}

func TestP6EmptyCSIPayload(t *testing.T) {
	hdr := UDPHeader{
		V:           1,
		Type:        UDPMsgHeartbeat,
		NodeID:      2,
		TimestampUs: 1700000000000000,
		CycleSeq:    50,
	}

	datagram, err := EncodeUDPDatagram(nil, hdr, nil)
	if err != nil {
		t.Fatalf("EncodeUDPDatagram with nil payload error: %v", err)
	}

	decHdr, decCSI, err := DecodeUDPDatagram(datagram)
	if err != nil {
		t.Fatalf("DecodeUDPDatagram error: %v", err)
	}
	if len(decCSI) != 0 {
		t.Fatalf("expected empty CSI, got %d bytes", len(decCSI))
	}
	if decHdr.CycleSeq != hdr.CycleSeq {
		t.Fatalf("cycle_seq mismatch: %d != %d", decHdr.CycleSeq, hdr.CycleSeq)
	}
}

func TestAllNewPayloadsRoundTrip(t *testing.T) {
	roundTrip := func(name string, in any, out any) {
		t.Helper()
		b, err := json.Marshal(in)
		if err != nil {
			t.Fatalf("%s marshal: %v", name, err)
		}
		if err := json.Unmarshal(b, out); err != nil {
			t.Fatalf("%s unmarshal: %v", name, err)
		}
	}

	var syncOut ClusterSyncPayload
	roundTrip("ClusterSync", ClusterSyncPayload{
		V: 1, Type: UDPMsgClusterSync, CycleSeq: 12, TimestampUs: 1000,
		Mode: ModeCabinTomography, SlotMs: 20, ActiveNodeMask: 0x1f,
		Slots: []SlotAssignment{{NodeID: 0, SlotID: 0, Ms: 20}},
	}, &syncOut)
	if syncOut.CycleSeq != 12 || len(syncOut.Slots) != 1 {
		t.Fatalf("ClusterSync mismatch: %+v", syncOut)
	}

	var modeOut ModeCmdPayload
	roundTrip("ModeCmd", ModeCmdPayload{V: 1, Type: UDPMsgModeCmd, Mode: ModeRadiationAlert, TimestampUs: 2000, CycleSeq: 13}, &modeOut)
	if modeOut.Mode != ModeRadiationAlert {
		t.Fatalf("ModeCmd mismatch: %+v", modeOut)
	}

	var helloOut NodeHelloPayload
	roundTrip("NodeHello", NodeHelloPayload{V: 1, Type: UDPMsgNodeHello, MAC: "02:ED:6E:00:00:00", NodeID: 0, Peripherals: []Peripheral{PeripheralSCD40}}, &helloOut)
	if helloOut.MAC != "02:ED:6E:00:00:00" {
		t.Fatalf("NodeHello mismatch: %+v", helloOut)
	}

	var hbOut HeartbeatPayload
	roundTrip("Heartbeat", HeartbeatPayload{V: 1, Type: UDPMsgHeartbeat, NodeID: 1, CycleSeq: 14, RSSIDbm: -42}, &hbOut)
	if hbOut.CycleSeq != 14 {
		t.Fatalf("Heartbeat mismatch: %+v", hbOut)
	}

	var pdataOut PeripheralDataPayload
	roundTrip("PeripheralData", PeripheralDataPayload{
		V: 1, Type: UDPMsgPeripheralData, NodeID: 2, CycleSeq: 15, TimestampUs: 3000,
		Peripherals: []PeripheralReading{{Type: PeripheralSCD40, Value: 750, Unit: "ppm", TimestampUs: 3000}},
	}, &pdataOut)
	if len(pdataOut.Peripherals) != 1 || pdataOut.Peripherals[0].Value != 750 {
		t.Fatalf("PeripheralData mismatch: %+v", pdataOut)
	}
}

func TestIPCAndRESTPayloadsRoundTrip(t *testing.T) {
	roundTrip := func(name string, in any, out any) {
		t.Helper()
		b, err := json.Marshal(in)
		if err != nil {
			t.Fatalf("%s marshal: %v", name, err)
		}
		if err := json.Unmarshal(b, out); err != nil {
			t.Fatalf("%s unmarshal: %v", name, err)
		}
	}

	var winOut CSIWindowPayload
	roundTrip("CSIWindow", CSIWindowPayload{
		CycleSeqFirst: 20, ActiveLinkMask: 0xfffff, Mode: ModeRestVitals,
		Links: []CSILink{{TxNodeID: 0, RxNodeID: 1, IQSamples: []IQSample{{Real: 1.5, Imaginary: -0.5}}, RSSIDbm: -50, NoiseFloor: -92}},
	}, &winOut)
	if winOut.CycleSeqFirst != 20 || len(winOut.Links) != 1 {
		t.Fatalf("CSIWindow mismatch: %+v", winOut)
	}

	var psOut PeripheralSnapshotPayload
	roundTrip("PeripheralSnapshot", PeripheralSnapshotPayload{
		TimestampUs: 4000, Readings: []PeripheralReading{{Type: PeripheralBME280, Value: 22.5, Unit: "C", TimestampUs: 4000}},
	}, &psOut)
	if len(psOut.Readings) != 1 {
		t.Fatalf("PeripheralSnapshot mismatch: %+v", psOut)
	}

	var sacOut SetActiveCrewPayload
	roundTrip("SetActiveCrew", SetActiveCrewPayload{
		CrewID: "crew_001", BaselinePath: "/var/lib/edgespace/crew_001.onnx",
		Thresholds: map[string]Threshold{"co2_ppm": {MetricName: "co2_ppm", YellowHigh: 2000, RedHigh: 5000}},
	}, &sacOut)
	if sacOut.CrewID != "crew_001" {
		t.Fatalf("SetActiveCrew mismatch: %+v", sacOut)
	}

	var ackOut CrewAckPayload
	roundTrip("CrewAck", CrewAckPayload{OK: true, BaselineFound: true}, &ackOut)
	if !ackOut.OK || !ackOut.BaselineFound {
		t.Fatalf("CrewAck mismatch: %+v", ackOut)
	}

	var aiOut AIInferencePayload
	roundTrip("AIInference", AIInferencePayload{
		CycleSeqFirst: 20, Posture: "supine", RespirationHz: 0.25, HeartRateBpm: 64, HRVMs: 52, AnomalyScore: 0.1, Confidence: 0.94,
	}, &aiOut)
	if aiOut.CycleSeqFirst != 20 || aiOut.Posture != "supine" {
		t.Fatalf("AIInference mismatch: %+v", aiOut)
	}

	var creqOut ChatCorrelateReqPayload
	roundTrip("ChatCorrelateReq", ChatCorrelateReqPayload{
		Text: "dor de cabeca", CrewID: "crew_001",
		Profile:       &CrewProfile{CrewID: "crew_001", Name: "Cmdr", Age: 39},
		RecentHistory: []ChatMessage{{SentAt: 100, Role: "user", Content: "oi"}},
	}, &creqOut)
	if creqOut.Text != "dor de cabeca" || creqOut.Profile.Age != 39 {
		t.Fatalf("ChatCorrelateReq mismatch: %+v", creqOut)
	}

	var crespOut ChatCorrelateRespPayload
	roundTrip("ChatCorrelateResp", ChatCorrelateRespPayload{
		Text: "CO2 elevado", Differentials: []string{"Hipercapnia"}, DisambiguationQuestion: "Tem nausea?",
		Actions: []string{"OPEN_VENT"}, Evidence: []string{"SCD40 2400ppm"}, Countermeasures: []string{"Ventilar"},
		SourceIDs: []string{"NASA-HRP-CO2"}, Escalation: EscalationCrew, Disclaimer: "Apoio clinico",
	}, &crespOut)
	if len(crespOut.Differentials) != 1 || crespOut.DisambiguationQuestion == "" || len(crespOut.Actions) != 1 {
		t.Fatalf("ChatCorrelateResp mismatch: %+v", crespOut)
	}

	var chatReplyOut ChatReplyPayload
	roundTrip("ChatReply", ChatReplyPayload{
		Text: "CO2 elevado", Differentials: []string{"Hipercapnia"}, DisambiguationQuestion: "Tem nausea?",
		Actions: []string{"OPEN_VENT"}, Evidence: []string{"SCD40 2400ppm"}, Countermeasures: []string{"Ventilar"},
		SourceIDs: []string{"NASA-HRP-CO2"}, Escalation: EscalationCrew, Disclaimer: "Apoio clinico",
	}, &chatReplyOut)
	if len(chatReplyOut.Differentials) != 1 {
		t.Fatalf("ChatReply mismatch: %+v", chatReplyOut)
	}

	var csOut CalibrationStepPayload
	roundTrip("CalibrationStep", CalibrationStepPayload{StepID: "step_1", Action: "stand_still", DurationMs: 5000}, &csOut)
	if csOut.DurationMs != 5000 {
		t.Fatalf("CalibrationStep mismatch: %+v", csOut)
	}

	var cfOut CalibrationFeedbackPayload
	roundTrip("CalibrationFeedback", CalibrationFeedbackPayload{StepID: "step_1", Progress: 100, Quality: 0.95}, &cfOut)
	if cfOut.Progress != 100 {
		t.Fatalf("CalibrationFeedback mismatch: %+v", cfOut)
	}

	var tsOut TimeseriesResponse
	roundTrip("TimeseriesResponse", TimeseriesResponse{
		CrewID: "crew_001", StartUs: 100, EndUs: 200,
		Buckets: []TelemetryBucket{{TsUs: 150, Vitals: VitalsData{HeartRateBpm: 65}, Environment: EnvironmentData{CO2Ppm: 600}}},
	}, &tsOut)
	if len(tsOut.Buckets) != 1 {
		t.Fatalf("TimeseriesResponse mismatch: %+v", tsOut)
	}

	var protoOut ProtocolDTO
	roundTrip("ProtocolDTO", ProtocolDTO{ProtocolID: "p_co2", Name: "CO2", Subsystems: []Subsystem{SubsystemRespiratoryAtmosphere}, Steps: []string{"Ventilar"}}, &protoOut)
	if protoOut.ProtocolID != "p_co2" {
		t.Fatalf("ProtocolDTO mismatch: %+v", protoOut)
	}

	var alertOut AlertRecord
	roundTrip("AlertRecord", AlertRecord{AlertID: "a1", TsUs: 100, Subsystem: SubsystemRespiratoryAtmosphere, Severity: SeverityRed, Message: "CO2", Escalation: EscalationStoreAndForward}, &alertOut)
	if alertOut.AlertID != "a1" {
		t.Fatalf("AlertRecord mismatch: %+v", alertOut)
	}

	var obOut OutboxRecord
	roundTrip("OutboxRecord", OutboxRecord{OutboxID: "o1", TsUs: 100, Subsystem: SubsystemRespiratoryAtmosphere, Severity: SeverityRed, Message: "CO2", Destination: "MCC"}, &obOut)
	if obOut.OutboxID != "o1" {
		t.Fatalf("OutboxRecord mismatch: %+v", obOut)
	}

	var devOut DevScenarioReq
	roundTrip("DevScenarioReq", DevScenarioReq{Scenario: "hypercapnia", Seed: 42}, &devOut)
	if devOut.Scenario != "hypercapnia" || devOut.Seed != 42 {
		t.Fatalf("DevScenarioReq mismatch: %+v", devOut)
	}
}

func TestEncodeDecodeCSIBinaryZeroAlloc(t *testing.T) {
	samples := make([]IQSample, 56)
	for i := range samples {
		samples[i] = IQSample{Real: float64(i) * 0.01, Imaginary: -float64(i) * 0.02}
	}
	binBuf := make([]byte, 0, 512)
	samplesDst := make([]IQSample, 0, 64)

	// Warm-up to stabilize any one-time initialization.
	binBuf = EncodeCSIBinary(binBuf, 0, 1, -45, -92.0, samples)
	_, _, _, _, samplesDst, err := DecodeCSIBinary(binBuf, samplesDst)
	if err != nil {
		t.Fatalf("warmup DecodeCSIBinary: %v", err)
	}

	encAllocs := testing.AllocsPerRun(100, func() {
		binBuf = EncodeCSIBinary(binBuf, 0, 1, -45, -92.0, samples)
	})
	if encAllocs != 0 {
		t.Fatalf("EncodeCSIBinary allocs=%.2f, want 0", encAllocs)
	}

	decAllocs := testing.AllocsPerRun(100, func() {
		var derr error
		_, _, _, _, samplesDst, derr = DecodeCSIBinary(binBuf, samplesDst)
		if derr != nil {
			t.Fatalf("DecodeCSIBinary: %v", derr)
		}
	})
	if decAllocs != 0 {
		t.Fatalf("DecodeCSIBinary allocs=%.2f, want 0", decAllocs)
	}
}

func TestDecodeUDPDatagramInvalidAndTruncated(t *testing.T) {
	cases := []struct {
		name string
		raw  []byte
	}{
		{"empty", nil},
		{"invalid_json_no_newline", []byte(`{"v":1,"type":`)},
		{"garbage_no_newline", []byte(`not-json-at-all`)},
		{"invalid_version_with_newline", []byte("{\"v\":99,\"type\":\"HEARTBEAT\",\"node_id\":1}\n")},
		{"invalid_type_with_newline", []byte("{\"v\":1,\"type\":\"UNKNOWN\",\"node_id\":1}\n")},
		{"truncated_json_before_newline", []byte("{\"v\":1,\"type\":\"CSI_FRAME\"\n\x00\x01")},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, _, err := DecodeUDPDatagram(tc.raw)
			if !errors.Is(err, ErrInvalidUDPDatagram) {
				t.Fatalf("%s: got err=%v, want ErrInvalidUDPDatagram", tc.name, err)
			}
		})
	}

	// CSI_FRAME without '\n' produces nil csiPayload; DecodeCSIBinary must return ErrInvalidUDPDatagram without panic.
	hdrOnly := []byte(`{"v":1,"type":"CSI_FRAME","node_id":1,"slot_id":0,"mode":"MODE_CABIN_TOMOGRAPHY","timestamp_us":1,"cycle_seq":1}`)
	hdr, csi, err := DecodeUDPDatagram(hdrOnly)
	if err != nil {
		t.Fatalf("valid header without newline unexpectedly failed: %v", err)
	}
	if hdr.Type != UDPMsgCSIFrame || csi != nil {
		t.Fatalf("unexpected hdr=%+v len(csi)=%d", hdr, len(csi))
	}
	if _, _, _, _, _, err := DecodeCSIBinary(csi, nil); !errors.Is(err, ErrInvalidUDPDatagram) {
		t.Fatalf("DecodeCSIBinary(nil): got %v, want ErrInvalidUDPDatagram", err)
	}

	// Truncated binary CSI payload (short header, and header claiming 10 samples with only 4 bytes).
	for _, rawCSI := range [][]byte{
		{1, 2, 3},
		make([]byte, 9),
		{0, 1, 0, 0, 0, 0, 0, 0, 10, 0, 1, 2, 3, 4},
	} {
		if _, _, _, _, _, err := DecodeCSIBinary(rawCSI, nil); !errors.Is(err, ErrInvalidUDPDatagram) {
			t.Fatalf("DecodeCSIBinary(%x): got %v, want ErrInvalidUDPDatagram", rawCSI, err)
		}
	}
}

func FuzzDecodeUDPDatagram(f *testing.F) {
	f.Add([]byte(`{"v":1,"type":"HEARTBEAT","node_id":0,"timestamp_us":1,"cycle_seq":1}`))
	f.Add([]byte("{\"v\":1,\"type\":\"CSI_FRAME\",\"node_id\":1,\"slot_id\":0,\"mode\":\"MODE_CABIN_TOMOGRAPHY\",\"timestamp_us\":1,\"cycle_seq\":1}\n\x00\x01\xd3\xff\x00\x00\xb8\xc2\x01\x00\x01\x00\x02\x00"))
	f.Add([]byte(`{"v":1`))
	f.Add([]byte{})
	f.Add([]byte("\n\xff\xff\xff\xff"))

	f.Fuzz(func(t *testing.T, data []byte) {
		hdr, csi, err := DecodeUDPDatagram(data)
		if err == nil && (hdr.Type == UDPMsgCSIFrame || len(csi) > 0) {
			_, _, _, _, _, _ = DecodeCSIBinary(csi, nil)
		}
	})
}
