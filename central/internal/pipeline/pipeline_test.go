package pipeline

import (
	"context"
	"reflect"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

type testSessionProvider struct {
	v atomic.Pointer[SessionView]
}

func newTestSession(v SessionView) *testSessionProvider {
	p := &testSessionProvider{}
	p.Set(v)
	return p
}

func (p *testSessionProvider) Set(v SessionView) {
	cp := v
	p.v.Store(&cp)
}

func (p *testSessionProvider) Snapshot() SessionView {
	v := p.v.Load()
	if v == nil {
		return SessionView{}
	}
	return *v
}

type mockIPCSink struct {
	mu          sync.Mutex
	rejectNext  bool
	windows     []CSIWindowEmit
	peripherals []PeripheralSnapshotEmit
}

func (m *mockIPCSink) TrySendCSIWindow(msg CSIWindowEmit) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.rejectNext {
		return false
	}
	m.windows = append(m.windows, msg)
	return true
}

func (m *mockIPCSink) TrySendPeripheralSnapshot(msg PeripheralSnapshotEmit) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.rejectNext {
		return false
	}
	m.peripherals = append(m.peripherals, msg)
	return true
}

func (m *mockIPCSink) Windows() []CSIWindowEmit {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]CSIWindowEmit, len(m.windows))
	copy(out, m.windows)
	return out
}

func (m *mockIPCSink) Peripherals() []PeripheralSnapshotEmit {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]PeripheralSnapshotEmit, len(m.peripherals))
	copy(out, m.peripherals)
	return out
}

type mockStoreSink struct {
	mu          sync.Mutex
	telemetry   []StoreTelemetryRecord
	peripherals []StorePeripheralRecord
	alerts      []StoreAlertRecord
	blobs       []StoreCSIBlobRecord
}

func (m *mockStoreSink) EmitTelemetry1Hz(rec StoreTelemetryRecord) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.telemetry = append(m.telemetry, rec)
	return true
}

func (m *mockStoreSink) EmitPeripherals1Hz(rec StorePeripheralRecord) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.peripherals = append(m.peripherals, rec)
	return true
}

func (m *mockStoreSink) EmitAlert(rec StoreAlertRecord) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.alerts = append(m.alerts, rec)
	return true
}

func (m *mockStoreSink) EmitCSIBlob(rec StoreCSIBlobRecord) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.blobs = append(m.blobs, rec)
	return true
}

func (m *mockStoreSink) Telemetry() []StoreTelemetryRecord {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]StoreTelemetryRecord, len(m.telemetry))
	copy(out, m.telemetry)
	return out
}

func (m *mockStoreSink) Peripherals() []StorePeripheralRecord {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]StorePeripheralRecord, len(m.peripherals))
	copy(out, m.peripherals)
	return out
}

func (m *mockStoreSink) Alerts() []StoreAlertRecord {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]StoreAlertRecord, len(m.alerts))
	copy(out, m.alerts)
	return out
}

func (m *mockStoreSink) Blobs() []StoreCSIBlobRecord {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]StoreCSIBlobRecord, len(m.blobs))
	copy(out, m.blobs)
	return out
}

func makeCSIFrameMsg(seq uint32, tx, rx uint8, now time.Time) DataMsg {
	return DataMsg{
		Type:       contracts.UDPMsgCSIFrame,
		ReceivedAt: now,
		CSI: &contracts.CSIFrame{
			Header: contracts.UDPHeader{
				V:           contracts.Version,
				Type:        contracts.UDPMsgCSIFrame,
				NodeID:      rx,
				Mode:        contracts.ModeCabinTomography,
				TimestampUs: now.UnixMicro(),
				CycleSeq:    seq,
			},
			TxNodeID:   tx,
			RxNodeID:   rx,
			RSSIDbm:    -48,
			NoiseFloor: -92.5,
			Samples: []contracts.IQSample{
				{Real: 1.0, Imaginary: 0.5},
				{Real: -0.5, Imaginary: 1.25},
			},
		},
	}
}

func sendCycleFrames(ch chan<- DataMsg, seq uint32, skipTx, skipRx int, now time.Time) {
	for idx := 0; idx < NumLinks; idx++ {
		tx, rx, _ := LinkPair(idx)
		if int(tx) == skipTx && int(rx) == skipRx {
			continue
		}
		ch <- makeCSIFrameMsg(seq, tx, rx, now)
	}
}

func waitUntil(t *testing.T, timeout time.Duration, cond func() bool, desc string) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(2 * time.Millisecond)
	}
	t.Fatalf("timeout waiting for %s", desc)
}

func startPipeline(t *testing.T, p *Pipeline) func() {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- p.Run(ctx)
	}()
	return func() {
		cancel()
		if err := <-done; err != nil {
			t.Fatalf("Pipeline.Run returned error: %v", err)
		}
	}
}

func TestPipelineZeroGCPointersAndLinkMapping(t *testing.T) {
	var checkNoPtr func(rt reflect.Type)
	checkNoPtr = func(rt reflect.Type) {
		switch rt.Kind() {
		case reflect.Ptr, reflect.UnsafePointer, reflect.Slice, reflect.Map,
			reflect.String, reflect.Interface, reflect.Chan, reflect.Func:
			t.Fatalf("LinkSample contains GC-tracked kind %s (%s)", rt.Kind(), rt)
		case reflect.Array:
			checkNoPtr(rt.Elem())
		case reflect.Struct:
			for i := 0; i < rt.NumField(); i++ {
				checkNoPtr(rt.Field(i).Type)
			}
		}
	}
	checkNoPtr(reflect.TypeOf(LinkSample{}))

	seen := make(map[int]bool, NumLinks)
	for tx := uint8(0); tx < NumNodes; tx++ {
		for rx := uint8(0); rx < NumNodes; rx++ {
			idx, ok := LinkIndex(tx, rx)
			if tx == rx {
				if ok {
					t.Fatalf("expected LinkIndex(%d,%d) to fail", tx, rx)
				}
				continue
			}
			if !ok || idx < 0 || idx >= NumLinks {
				t.Fatalf("bad LinkIndex(%d,%d) = (%d,%v)", tx, rx, idx, ok)
			}
			if seen[idx] {
				t.Fatalf("duplicate LinkIndex %d", idx)
			}
			seen[idx] = true
			gotTx, gotRx, ok2 := LinkPair(idx)
			if !ok2 || gotTx != tx || gotRx != rx {
				t.Fatalf("LinkPair(%d) = (%d,%d,%v), want (%d,%d,true)", idx, gotTx, gotRx, ok2, tx, rx)
			}
		}
	}
	if len(seen) != NumLinks {
		t.Fatalf("expected %d unique links, got %d", NumLinks, len(seen))
	}
	if bits := popCount32(ActiveLinkMaskFromNodes(0x1F)); bits != 20 {
		t.Fatalf("5 nodes link count = %d, want 20", bits)
	}
	if bits := popCount32(ActiveLinkMaskFromNodes(0x0F)); bits != 12 {
		t.Fatalf("4 nodes link count = %d, want 12", bits)
	}
	if bits := popCount32(ActiveLinkMaskFromNodes(0x07)); bits != 6 {
		t.Fatalf("3 nodes link count = %d, want 6", bits)
	}
}

func popCount32(v uint32) int {
	n := 0
	for v != 0 {
		n += int(v & 1)
		v >>= 1
	}
	return n
}

func TestPipelineCycleAssemblyAndGrace30ms(t *testing.T) {
	dataCh := make(chan DataMsg, 128)
	p := New(Config{
		CycleGrace: 30 * time.Millisecond,
	}, Deps{
		DataCh: dataCh,
	})
	stop := startPipeline(t, p)
	defer stop()

	// 1. Complete cycle (all 20 links) closes immediately without waiting 30 ms.
	start := time.Now()
	sendCycleFrames(dataCh, 1, -1, -1, start)
	waitUntil(t, 20*time.Millisecond, func() bool {
		return p.Metrics().CyclesClosed == 1
	}, "immediate cycle 1 close")

	info, ok := p.LastClosedCycle()
	if !ok || info.CycleSeq != 1 || !info.Complete || info.ReceivedMask != AllLinksMask {
		t.Fatalf("unexpected cycle 1 info: ok=%v %+v", ok, info)
	}

	// 2. Cycle 2 missing link (4, 3) stays open before 30 ms and closes after 30 ms with partial mask.
	missingIdx, _ := LinkIndex(4, 3)
	t2 := time.Now()
	sendCycleFrames(dataCh, 2, 4, 3, t2)
	time.Sleep(12 * time.Millisecond)
	if got := p.Metrics().CyclesClosed; got != 1 {
		t.Fatalf("cycle 2 closed prematurely before 30 ms grace (cyclesClosed=%d)", got)
	}

	waitUntil(t, 120*time.Millisecond, func() bool {
		return p.Metrics().CyclesClosed == 2
	}, "cycle 2 close after 30 ms grace")

	info2, ok := p.LastClosedCycle()
	wantPartial := AllLinksMask &^ (1 << missingIdx)
	if !ok || info2.CycleSeq != 2 || info2.Complete || info2.ReceivedMask != wantPartial {
		t.Fatalf("unexpected cycle 2 info: ok=%v got=%+v wantMask=%#x", ok, info2, wantPartial)
	}
	if p.Metrics().PartialCycles != 1 {
		t.Fatalf("PartialCycles = %d, want 1", p.Metrics().PartialCycles)
	}

	// 3. Late frame (cycle 1 already closed) and out-of-window frame (cycle 10) increment LateFrames.
	dataCh <- makeCSIFrameMsg(1, 0, 1, time.Now())
	dataCh <- makeCSIFrameMsg(10, 0, 1, time.Now())
	waitUntil(t, 50*time.Millisecond, func() bool {
		return p.Metrics().LateFrames == 2
	}, "LateFrames increment")
}

func TestPipelineCSIWindow2HzAndCrewIDGating(t *testing.T) {
	dataCh := make(chan DataMsg, 256)
	sess := newTestSession(SessionView{
		CrewID:      "crew-01",
		MissionMode: contracts.ModeCabinTomography,
		AIReady:     false,
	})
	ipcSink := &mockIPCSink{}
	storeSink := &mockStoreSink{}

	p := New(Config{
		CycleGrace:   30 * time.Millisecond,
		WindowCycles: 5,
	}, Deps{
		DataCh:  dataCh,
		Session: sess,
		IPC:     ipcSink,
		Store:   storeSink,
	})
	stop := startPipeline(t, p)
	defer stop()

	// 5 cycles with AIReady=false -> 1 CSIWindowPayload with crew_id == nil.
	for seq := uint32(1); seq <= 5; seq++ {
		sendCycleFrames(dataCh, seq, -1, -1, time.Now())
	}
	waitUntil(t, 100*time.Millisecond, func() bool {
		return len(ipcSink.Windows()) == 1
	}, "first CSI window")

	w1 := ipcSink.Windows()[0]
	if w1.CrewID != nil {
		t.Fatalf("expected CrewID=nil when AIReady=false, got %q", *w1.CrewID)
	}
	if w1.Payload.CycleSeqFirst != 1 || w1.Payload.ActiveLinkMask != AllLinksMask || len(w1.Payload.Links) != NumLinks {
		t.Fatalf("unexpected w1 payload: seq=%d mask=%#x links=%d", w1.Payload.CycleSeqFirst, w1.Payload.ActiveLinkMask, len(w1.Payload.Links))
	}
	if len(w1.Payload.Links[0].IQSamples) != 10 {
		t.Fatalf("expected 10 IQ samples per link over 5 cycles, got %d", len(w1.Payload.Links[0].IQSamples))
	}

	// Enable AIReady=true and CalibrationActive=true -> 5 more cycles produce crew_id="crew-01" + calibration blob.
	sess.Set(SessionView{
		CrewID:            "crew-01",
		MissionMode:       contracts.ModeCabinTomography,
		AIReady:           true,
		CalibrationActive: true,
		CalibrationStepID: "step-baseline-1",
	})
	for seq := uint32(6); seq <= 10; seq++ {
		sendCycleFrames(dataCh, seq, -1, -1, time.Now())
	}
	waitUntil(t, 100*time.Millisecond, func() bool {
		return len(ipcSink.Windows()) == 2
	}, "second CSI window")

	w2 := ipcSink.Windows()[1]
	if w2.CrewID == nil || *w2.CrewID != "crew-01" {
		t.Fatalf("expected CrewID='crew-01' when AIReady=true, got %v", w2.CrewID)
	}
	if !w2.CalibrationActive || w2.CalibrationStepID != "step-baseline-1" {
		t.Fatalf("expected calibration flags on w2, got %+v", w2)
	}
	waitUntil(t, 50*time.Millisecond, func() bool {
		return len(storeSink.Blobs()) >= 1
	}, "calibration CSI blob")
	if storeSink.Blobs()[0].Reason != "calibration" {
		t.Fatalf("expected calibration blob reason, got %q", storeSink.Blobs()[0].Reason)
	}

	// Full IPC sink must not block and must increment IPCDropped.
	ipcSink.mu.Lock()
	ipcSink.rejectNext = true
	ipcSink.mu.Unlock()
	for seq := uint32(11); seq <= 15; seq++ {
		sendCycleFrames(dataCh, seq, -1, -1, time.Now())
	}
	waitUntil(t, 100*time.Millisecond, func() bool {
		return p.Metrics().IPCDropped == 1
	}, "IPCDropped increment")
}

func TestPipelineHypercapniaAndSelfExamThresholds(t *testing.T) {
	dataCh := make(chan DataMsg, 64)
	selfExamCh := make(chan SelfExamInput, 16)
	eventCh := make(chan contracts.AlertEventPayload, 32)
	sess := newTestSession(SessionView{
		CrewID:      "crew-01",
		MissionMode: contracts.ModeCabinTomography,
		AIReady:     true,
	})
	storeSink := &mockStoreSink{}

	p := New(Config{}, Deps{
		DataCh:     dataCh,
		SelfExamCh: selfExamCh,
		Session:    sess,
		Store:      storeSink,
		EventCh:    eventCh,
	})
	stop := startPipeline(t, p)
	defer stop()

	sendSCD40 := func(ppm float64) {
		now := time.Now()
		dataCh <- DataMsg{
			Type:       contracts.UDPMsgPeripheralData,
			ReceivedAt: now,
			Peripheral: &contracts.PeripheralDataPayload{
				V:           contracts.Version,
				Type:        contracts.UDPMsgPeripheralData,
				NodeID:      0,
				TimestampUs: now.UnixMicro(),
				Peripherals: []contracts.PeripheralReading{
					{Type: contracts.PeripheralSCD40, Value: ppm, Unit: "ppm", TimestampUs: now.UnixMicro()},
				},
			},
		}
	}

	// 1. 600 ppm -> GREEN (no alert).
	sendSCD40(600)
	waitUntil(t, 50*time.Millisecond, func() bool {
		snap := p.Latest.Load()
		return snap != nil && snap.Environment.CO2Ppm == 600
	}, "CO2 600 snapshot")
	if len(eventCh) != 0 {
		t.Fatalf("unexpected alert at 600 ppm")
	}

	// 2. 1500 ppm -> YELLOW (AlertEvent, WriteOutbox=false).
	sendSCD40(1500)
	var ev1 contracts.AlertEventPayload
	select {
	case ev1 = <-eventCh:
	case <-time.After(100 * time.Millisecond):
		t.Fatalf("timeout waiting for YELLOW hypercapnia alert")
	}
	if ev1.Subsystem != contracts.SubsystemRespiratoryAtmosphere || ev1.Severity != contracts.SeverityYellow {
		t.Fatalf("unexpected YELLOW alert: %+v", ev1)
	}
	waitUntil(t, 50*time.Millisecond, func() bool {
		return len(storeSink.Alerts()) == 1
	}, "YELLOW alert stored")
	if storeSink.Alerts()[0].WriteOutbox {
		t.Fatalf("expected WriteOutbox=false for YELLOW alert")
	}

	// 3. 4200 ppm -> RED (AlertEvent, WriteOutbox=true for store_and_forward_outbox).
	sendSCD40(4200)
	var ev2 contracts.AlertEventPayload
	select {
	case ev2 = <-eventCh:
	case <-time.After(100 * time.Millisecond):
		t.Fatalf("timeout waiting for RED hypercapnia alert")
	}
	if ev2.Subsystem != contracts.SubsystemRespiratoryAtmosphere || ev2.Severity != contracts.SeverityRed || ev2.Escalation != contracts.EscalationStoreAndForward {
		t.Fatalf("unexpected RED alert: %+v", ev2)
	}
	waitUntil(t, 50*time.Millisecond, func() bool {
		return len(storeSink.Alerts()) == 2
	}, "RED alert stored")
	if !storeSink.Alerts()[1].WriteOutbox {
		t.Fatalf("expected WriteOutbox=true for RED alert")
	}

	// 4. SelfExam Amsler altered -> NEURO_OCULAR_SANS YELLOW.
	selfExamCh <- SelfExamInput{
		ReceivedAt: time.Now(),
		Payload: contracts.SelfExamPayload{
			ExamType: "amsler",
			Result:   "metamorphopsia",
		},
	}
	var ev3 contracts.AlertEventPayload
	select {
	case ev3 = <-eventCh:
	case <-time.After(100 * time.Millisecond):
		t.Fatalf("timeout waiting for SANS Amsler alert")
	}
	if ev3.Subsystem != contracts.SubsystemNeuroOcularSANS || ev3.Severity != contracts.SeverityYellow {
		t.Fatalf("unexpected SANS alert: %+v", ev3)
	}
	snap := p.Latest.Load()
	if snap.Subsystems[2].Subsystem != contracts.SubsystemNeuroOcularSANS || snap.Subsystems[2].Severity != contracts.SeverityYellow {
		t.Fatalf("expected NEURO_OCULAR_SANS YELLOW in Latest, got %+v", snap.Subsystems[2])
	}

	// 5. MODE_RADIATION_ALERT -> NEUROBEHAVIORAL_RADIATION RED.
	sess.Set(SessionView{
		CrewID:      "crew-01",
		MissionMode: contracts.ModeRadiationAlert,
		AIReady:     true,
	})
	selfExamCh <- SelfExamInput{
		ReceivedAt: time.Now(),
		Payload: contracts.SelfExamPayload{
			ExamType: "amsler",
			Result:   "metamorphopsia",
		},
	}
	var ev4 contracts.AlertEventPayload
	select {
	case ev4 = <-eventCh:
	case <-time.After(100 * time.Millisecond):
		t.Fatalf("timeout waiting for RADIATION RED alert")
	}
	if ev4.Subsystem != contracts.SubsystemNeurobehavioralRadiation || ev4.Severity != contracts.SeverityRed {
		t.Fatalf("unexpected RADIATION alert: %+v", ev4)
	}
}

func TestPipelineLatestSnapshotAndDecimation1Hz(t *testing.T) {
	dataCh := make(chan DataMsg, 256)
	infCh := make(chan contracts.AIInferencePayload, 16)
	eventCh := make(chan contracts.AlertEventPayload, 16)
	latest := &atomic.Pointer[contracts.TelemetrySnapshot]{}
	sess := newTestSession(SessionView{
		CrewID:      "crew-02",
		MissionMode: contracts.ModeRestVitals,
		AIReady:     true,
	})
	ipcSink := &mockIPCSink{}
	storeSink := &mockStoreSink{}

	p := New(Config{
		CycleGrace:      30 * time.Millisecond,
		Emit1HzInterval: 1 * time.Second,
	}, Deps{
		DataCh:      dataCh,
		InferenceCh: infCh,
		Session:     sess,
		IPC:         ipcSink,
		Store:       storeSink,
		EventCh:     eventCh,
		Latest:      latest,
	})
	stop := startPipeline(t, p)
	defer stop()

	now := time.Now()
	dataCh <- DataMsg{
		Type:       contracts.UDPMsgPeripheralData,
		ReceivedAt: now,
		Peripheral: &contracts.PeripheralDataPayload{
			V:           contracts.Version,
			Type:        contracts.UDPMsgPeripheralData,
			NodeID:      2,
			TimestampUs: now.UnixMicro(),
			Peripherals: []contracts.PeripheralReading{
				{Type: contracts.PeripheralSCD40, Value: 720, Unit: "ppm", TimestampUs: now.UnixMicro()},
				{Type: contracts.PeripheralBME280, Value: 22.5, Unit: "C", TimestampUs: now.UnixMicro()},
				{Type: contracts.PeripheralBME280, Value: 45.0, Unit: "%", TimestampUs: now.UnixMicro()},
				{Type: contracts.PeripheralBME280, Value: 1013.2, Unit: "hPa", TimestampUs: now.UnixMicro()},
				{Type: contracts.PeripheralMAX30102, Value: 98.0, Unit: "%", TimestampUs: now.UnixMicro()},
			},
		},
	}

	infCh <- contracts.AIInferencePayload{
		CycleSeqFirst: 1,
		Posture:       "supine",
		RespirationHz: 0.25,
		HeartRateBpm:  68,
		HRVMs:         52,
		AnomalyScore:  0.1,
		Confidence:    0.94,
	}

	// Send 10 rapid CSI cycles in < 100 ms; store must still decimate to 1 Hz (not 10 records).
	for seq := uint32(1); seq <= 10; seq++ {
		sendCycleFrames(dataCh, seq, -1, -1, time.Now())
	}

	waitUntil(t, 100*time.Millisecond, func() bool {
		snap := latest.Load()
		return snap != nil && snap.Vitals.HeartRateBpm == 68 && snap.Environment.CO2Ppm == 720 && snap.Vitals.SpO2Pct == 98
	}, "Latest.Load() updated")

	snap := latest.Load()
	if snap.CrewID == nil || *snap.CrewID != "crew-02" {
		t.Fatalf("expected Latest CrewID='crew-02', got %v", snap.CrewID)
	}
	if snap.Vitals.RespRateBpm != 15.0 || snap.Vitals.Posture != "supine" || snap.Environment.PressureHpa != 1013.2 {
		t.Fatalf("unexpected Latest snapshot fields: %+v", snap)
	}

	// Before 1 s elapses, store should not have accumulated 10 per-cycle telemetry records.
	if got := len(storeSink.Telemetry()); got > 1 {
		t.Fatalf("expected decimation before 1 s, got %d store telemetry records", got)
	}

	// Wait for 1 Hz tick -> 1 store telemetry record, 1 store peripheral record, 1 IPC peripheral snapshot (crew_id=nil).
	waitUntil(t, 1300*time.Millisecond, func() bool {
		return len(storeSink.Telemetry()) >= 1 && len(storeSink.Peripherals()) >= 1 && len(ipcSink.Peripherals()) >= 1
	}, "1 Hz decimated emit")

	if got := len(storeSink.Telemetry()); got != 1 {
		t.Fatalf("expected 1 decimated telemetry record at ~1 Hz, got %d", got)
	}
	ps := ipcSink.Peripherals()[0]
	if ps.CrewID != nil {
		t.Fatalf("expected PeripheralSnapshot CrewID=nil, got %v", ps.CrewID)
	}
	if len(ps.Meta) != 5 || ps.Meta[0].NodeID != 2 {
		t.Fatalf("expected 5 peripheral meta entries from node 2, got %+v", ps.Meta)
	}
}
