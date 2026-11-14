package session

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

type mockStore struct {
	mu       sync.Mutex
	calls    []string
	profiles map[string]CrewProfileData
	summary  string
	history  []contracts.ChatMessage
	audits   []string
	chats    []string
	exams    []contracts.SelfExamPayload
	outbox   []contracts.OutboxRecord
}

func newMockStore() *mockStore {
	return &mockStore{
		profiles: make(map[string]CrewProfileData),
	}
}

func (s *mockStore) Flush(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "flush")
	return nil
}

func (s *mockStore) LoadProfile(ctx context.Context, crewID string) (CrewProfileData, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "load_profile:"+crewID)
	p, ok := s.profiles[crewID]
	if !ok {
		return CrewProfileData{}, fmt.Errorf("crew %q not found", crewID)
	}
	return p, nil
}

func (s *mockStore) LoadSummary24h(ctx context.Context, crewID string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "load_summary:"+crewID)
	return s.summary, nil
}

func (s *mockStore) LoadRecentChat(ctx context.Context, crewID string, limit int) ([]contracts.ChatMessage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, fmt.Sprintf("load_chat:%s:%d", crewID, limit))
	return append([]contracts.ChatMessage(nil), s.history...), nil
}

func (s *mockStore) SaveAudit(ctx context.Context, crewID *string, eventType string, details string, tsUs int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.audits = append(s.audits, eventType+":"+details)
	return nil
}

func (s *mockStore) SaveChat(ctx context.Context, crewID string, req contracts.ChatMsgPayload, resp contracts.ChatCorrelateRespPayload, tsUs int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.chats = append(s.chats, req.Text+"->"+resp.Text)
	return nil
}

func (s *mockStore) SaveSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload, tsUs int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.exams = append(s.exams, exam)
	return nil
}

func (s *mockStore) SaveOutbox(ctx context.Context, rec contracts.OutboxRecord) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.outbox = append(s.outbox, rec)
	return nil
}

func (s *mockStore) Calls() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.calls...)
}

type mockIPC struct {
	mu          sync.Mutex
	calls       []string
	setCrewFn   func(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error)
	chatFn      func(ctx context.Context, reqID uint64, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error)
	calibFn     func(ctx context.Context, reqID uint64, crewID string, payload contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error)
	lastChatReq *contracts.ChatCorrelateReqPayload
}

func (i *mockIPC) SendSetActiveCrew(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
	i.mu.Lock()
	i.calls = append(i.calls, "ipc_set_crew:"+payload.CrewID)
	fn := i.setCrewFn
	i.mu.Unlock()
	if fn != nil {
		return fn(ctx, reqID, payload)
	}
	return contracts.CrewAckPayload{OK: true, BaselineFound: true}, nil
}

func (i *mockIPC) SendChatCorrelate(ctx context.Context, reqID uint64, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error) {
	i.mu.Lock()
	cp := payload
	i.lastChatReq = &cp
	fn := i.chatFn
	i.mu.Unlock()
	if fn != nil {
		return fn(ctx, reqID, payload)
	}
	return contracts.ChatCorrelateRespPayload{Text: "ok", Escalation: contracts.EscalationLocal}, nil
}

func (i *mockIPC) SendCalibrationStep(ctx context.Context, reqID uint64, crewID string, payload contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	i.mu.Lock()
	fn := i.calibFn
	i.mu.Unlock()
	if fn != nil {
		return fn(ctx, reqID, crewID, payload)
	}
	return contracts.CalibrationFeedbackPayload{StepID: payload.StepID, Progress: 100, Quality: 0.95}, nil
}

type mockUDP struct {
	mu    sync.Mutex
	modes []contracts.MissionMode
}

func (u *mockUDP) SendModeCmd(ctx context.Context, mode contracts.MissionMode) error {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.modes = append(u.modes, mode)
	return nil
}

type mockUI struct {
	mu     sync.Mutex
	events []UIEvent
}

func (u *mockUI) EmitEvent(ev UIEvent) bool {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.events = append(u.events, ev)
	return true
}

func (u *mockUI) Events() []UIEvent {
	u.mu.Lock()
	defer u.mu.Unlock()
	return append([]UIEvent(nil), u.events...)
}

type mockSelfExamNotifier struct {
	mu    sync.Mutex
	exams []contracts.SelfExamPayload
}

func (n *mockSelfExamNotifier) NotifySelfExam(exam contracts.SelfExamPayload, receivedAt time.Time) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.exams = append(n.exams, exam)
}

func startManager(t *testing.T, m *Manager) func() {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- m.Run(ctx)
	}()
	return func() {
		cancel()
		if err := <-done; err != nil {
			t.Fatalf("Manager.Run returned error: %v", err)
		}
	}
}

func waitCond(t *testing.T, timeout time.Duration, cond func() bool, desc string) {
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

func TestSessionHotSwapSuccessAndFlushOrder(t *testing.T) {
	store := newMockStore()
	store.profiles["crew-1"] = CrewProfileData{
		Profile:      contracts.CrewProfile{CrewID: "crew-1", Name: "Helena", Role: "Commander", MissionDay: 14},
		BaselinePath: "/baselines/crew-1.onnx",
		Thresholds: map[string]contracts.Threshold{
			"co2_ppm": {MetricName: "co2_ppm", YellowHigh: 900, RedHigh: 3000},
		},
	}
	store.profiles["crew-2"] = CrewProfileData{
		Profile:      contracts.CrewProfile{CrewID: "crew-2", Name: "Marcus", Role: "Flight Engineer", MissionDay: 14},
		BaselinePath: "/baselines/crew-2.onnx",
	}

	ipc := &mockIPC{}
	var orderAtIPC []string
	ipc.setCrewFn = func(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
		orderAtIPC = store.Calls()
		if payload.CrewID == "crew-1" {
			return contracts.CrewAckPayload{OK: true, BaselineFound: false}, nil
		}
		return contracts.CrewAckPayload{OK: true, BaselineFound: true}, nil
	}
	ui := &mockUI{}

	m := New(Config{}, Deps{Store: store, IPC: ipc, UI: ui})
	stop := startManager(t, m)
	defer stop()

	ctx := context.Background()
	st1, err := m.SetCrew(ctx, "crew-1")
	if err != nil {
		t.Fatalf("SetCrew(crew-1) failed: %v", err)
	}
	if len(orderAtIPC) != 2 || orderAtIPC[0] != "flush" || orderAtIPC[1] != "load_profile:crew-1" {
		t.Fatalf("expected Flush before LoadProfile before SET_ACTIVE_CREW, got %v", orderAtIPC)
	}
	if !st1.AIReady || !st1.CalibrationRequired {
		t.Fatalf("expected AIReady=true and CalibrationRequired=true when BaselineFound=false, got %+v", st1)
	}
	snap := m.Snapshot()
	if snap.ActiveCrewID != "crew-1" || !snap.AIReady || !snap.CalibrationRequired || snap.SwapSeq != 1 {
		t.Fatalf("unexpected snapshot after crew-1 swap: %+v", snap)
	}

	// Idempotent SetCrew when already active and AIReady should not flush or call IPC again.
	stSame, err := m.SetCrew(ctx, "crew-1")
	if err != nil || stSame.CrewID == nil || *stSame.CrewID != "crew-1" {
		t.Fatalf("idempotent SetCrew failed: %+v err=%v", stSame, err)
	}
	if len(store.Calls()) != 2 {
		t.Fatalf("expected no extra store calls on idempotent SetCrew, got %v", store.Calls())
	}

	// Swap to crew-2 with BaselineFound=true -> CalibrationRequired=false.
	st2, err := m.SetCrew(ctx, "crew-2")
	if err != nil {
		t.Fatalf("SetCrew(crew-2) failed: %v", err)
	}
	if !st2.AIReady || st2.CalibrationRequired {
		t.Fatalf("expected AIReady=true and CalibrationRequired=false, got %+v", st2)
	}

	evs := ui.Events()
	if len(evs) != 2 || evs[0].Type != contracts.WSMsgCrewState || evs[1].Type != contracts.WSMsgCrewState {
		t.Fatalf("expected 2 CREW_STATE UI events, got %+v", evs)
	}
}

func TestSessionHotSwapTimeoutAndAutoHealing(t *testing.T) {
	store := newMockStore()
	store.profiles["crew-1"] = CrewProfileData{
		Profile: contracts.CrewProfile{CrewID: "crew-1", Name: "Helena"},
	}
	ipc := &mockIPC{
		setCrewFn: func(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
			<-ctx.Done()
			return contracts.CrewAckPayload{}, ctx.Err()
		},
	}
	ui := &mockUI{}

	m := New(Config{
		SetCrewTimeout: 35 * time.Millisecond,
	}, Deps{
		Store: store,
		IPC:   ipc,
		UI:    ui,
	})
	stop := startManager(t, m)
	defer stop()

	st, err := m.SetCrew(context.Background(), "crew-1")
	if err != nil {
		t.Fatalf("SetCrew returned unexpected error on IPC timeout: %v", err)
	}
	if st.CrewID == nil || *st.CrewID != "crew-1" || st.AIReady {
		t.Fatalf("expected ActiveCrewID='crew-1' with AIReady=false on timeout, got %+v", st)
	}
	if snap := m.Snapshot(); snap.ActiveCrewID != "crew-1" || snap.AIReady {
		t.Fatalf("unexpected snapshot after timeout: %+v", snap)
	}

	// Heal IPC and trigger NotifyIPCReconnect() -> promotes AIReady=true.
	ipc.mu.Lock()
	ipc.setCrewFn = func(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
		return contracts.CrewAckPayload{OK: true, BaselineFound: true}, nil
	}
	ipc.mu.Unlock()

	m.NotifyIPCReconnect()
	waitCond(t, 200*time.Millisecond, func() bool {
		return m.Snapshot().AIReady
	}, "AIReady=true after NotifyIPCReconnect")

	if m.Metrics().ReconnectSyncs != 1 {
		t.Fatalf("ReconnectSyncs = %d, want 1", m.Metrics().ReconnectSyncs)
	}
}

func TestSessionRejectsUnknownCrewKeepsPrevious(t *testing.T) {
	store := newMockStore()
	store.profiles["crew-1"] = CrewProfileData{
		Profile: contracts.CrewProfile{CrewID: "crew-1", Name: "Helena"},
	}
	ipc := &mockIPC{}
	ui := &mockUI{}

	m := New(Config{}, Deps{Store: store, IPC: ipc, UI: ui})
	stop := startManager(t, m)
	defer stop()

	if _, err := m.SetCrew(context.Background(), "crew-1"); err != nil {
		t.Fatalf("SetCrew(crew-1) failed: %v", err)
	}
	if _, err := m.SetCrew(context.Background(), "unknown-99"); err == nil {
		t.Fatalf("expected error for unknown crew_id")
	}

	snap := m.Snapshot()
	if snap.ActiveCrewID != "crew-1" || snap.Profile.Name != "Helena" || !snap.AIReady {
		t.Fatalf("previous crew not preserved after unknown crew error: %+v", snap)
	}
}

func TestSessionDiscardStaleSwapSeq(t *testing.T) {
	store := newMockStore()
	store.profiles["crew-1"] = CrewProfileData{Profile: contracts.CrewProfile{CrewID: "crew-1", Name: "Helena"}}
	store.profiles["crew-2"] = CrewProfileData{Profile: contracts.CrewProfile{CrewID: "crew-2", Name: "Marcus"}}

	crew1Started := make(chan struct{})
	releaseCrew1 := make(chan struct{})
	crew1Returned := make(chan struct{})

	ipc := &mockIPC{
		setCrewFn: func(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
			if payload.CrewID == "crew-1" {
				close(crew1Started)
				<-releaseCrew1
				defer close(crew1Returned)
				return contracts.CrewAckPayload{OK: true, BaselineFound: false}, nil
			}
			return contracts.CrewAckPayload{OK: true, BaselineFound: true}, nil
		},
	}
	ui := &mockUI{}

	m := New(Config{
		SetCrewTimeout: 500 * time.Millisecond,
	}, Deps{
		Store: store,
		IPC:   ipc,
		UI:    ui,
	})
	stop := startManager(t, m)
	defer stop()

	// Start slow swap to crew-1 (swap_seq = 1).
	errCh1 := make(chan error, 1)
	go func() {
		_, err := m.SetCrew(context.Background(), "crew-1")
		errCh1 <- err
	}()
	<-crew1Started

	// Supersede immediately with swap to crew-2 (swap_seq = 2).
	st2, err := m.SetCrew(context.Background(), "crew-2")
	if err != nil {
		t.Fatalf("SetCrew(crew-2) failed: %v", err)
	}
	if st2.CrewID == nil || *st2.CrewID != "crew-2" || !st2.AIReady || st2.CalibrationRequired {
		t.Fatalf("unexpected crew-2 state: %+v", st2)
	}

	if err1 := <-errCh1; !errors.Is(err1, ErrSwapSuperseded) {
		t.Fatalf("expected ErrSwapSuperseded for crew-1, got %v", err1)
	}

	// Release slow response for crew-1 (swap_seq=1) + inject another stale ACK; crew-2 must remain intact.
	close(releaseCrew1)
	<-crew1Returned
	m.DeliverCrewAck(1, contracts.CrewAckPayload{OK: false, BaselineFound: false})

	waitCond(t, 100*time.Millisecond, func() bool {
		return m.Metrics().StaleAcks >= 2
	}, "stale ACKs discarded")

	snap := m.Snapshot()
	if snap.ActiveCrewID != "crew-2" || !snap.AIReady || snap.CalibrationRequired || snap.SwapSeq != 2 {
		t.Fatalf("stale ACK corrupted current crew-2 snapshot: %+v", snap)
	}
}

func TestSessionChatCorrelateAndStoreAndForward(t *testing.T) {
	store := newMockStore()
	store.profiles["crew-1"] = CrewProfileData{
		Profile: contracts.CrewProfile{CrewID: "crew-1", Name: "Helena", Role: "Commander", MissionDay: 21},
		Thresholds: map[string]contracts.Threshold{
			"co2_ppm": {MetricName: "co2_ppm", YellowHigh: 1000, RedHigh: 3500},
		},
	}
	store.summary = "24h summary: sleep 4.5h, HRV -25%"
	store.history = []contracts.ChatMessage{
		{SentAt: 100, Role: "user", Content: "Mild headache"},
		{SentAt: 200, Role: "assistant", Content: "Monitor CO2 and hydration"},
	}

	ipc := &mockIPC{
		chatFn: func(ctx context.Context, reqID uint64, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error) {
			return contracts.ChatCorrelateRespPayload{
				Text:            "Acute SPE radiation + headache risk: shelter immediately.",
				Differentials:   []string{"SPE exposure", "Hypercapnia"},
				Evidence:        []string{"MODE_RADIATION_ALERT", "sleep 4.5h"},
				Countermeasures: []string{"Seek shelter", "Vitamins C & E"},
				SourceIDs:       []string{"NASA-HRP-CANS-SPE"},
				Escalation:      contracts.EscalationStoreAndForward,
			}, nil
		},
	}
	udp := &mockUDP{}
	ui := &mockUI{}
	notifier := &mockSelfExamNotifier{}

	m := New(Config{}, Deps{
		Store:            store,
		IPC:              ipc,
		UDP:              udp,
		UI:               ui,
		SelfExamNotifier: notifier,
	})
	stop := startManager(t, m)
	defer stop()

	ctx := context.Background()
	if _, err := m.SetCrew(ctx, "crew-1"); err != nil {
		t.Fatalf("SetCrew failed: %v", err)
	}

	// SetMode -> dispatches SendModeCmd + CREW_STATE.
	modeState, err := m.SetMode(ctx, contracts.ModeRadiationAlert)
	if err != nil {
		t.Fatalf("SetMode failed: %v", err)
	}
	if modeState.MissionMode != contracts.ModeRadiationAlert || m.Snapshot().MissionMode != contracts.ModeRadiationAlert {
		t.Fatalf("MissionMode not updated: %+v", modeState)
	}
	udp.mu.Lock()
	udpModes := append([]contracts.MissionMode(nil), udp.modes...)
	udp.mu.Unlock()
	if len(udpModes) != 1 || udpModes[0] != contracts.ModeRadiationAlert {
		t.Fatalf("expected SendModeCmd(MODE_RADIATION_ALERT), got %v", udpModes)
	}

	// HandleChatMsg -> loads 24h summary + 10 recent msgs, persists chat + outbox, emits CHAT_REPLY.
	peripherals := []contracts.PeripheralReading{{Type: contracts.PeripheralSCD40, Value: 1400, Unit: "ppm"}}
	inf := &contracts.AIInferencePayload{HeartRateBpm: 88, HRVMs: 22, Confidence: 0.9}
	reply, err := m.HandleChatMsg(ctx, "crew-1", "Headache during solar alert", peripherals, inf)
	if err != nil {
		t.Fatalf("HandleChatMsg failed: %v", err)
	}
	if reply.Escalation != contracts.EscalationStoreAndForward || reply.Disclaimer == "" {
		t.Fatalf("unexpected CHAT_REPLY: %+v", reply)
	}

	store.mu.Lock()
	chatCount := len(store.chats)
	outbox := append([]contracts.OutboxRecord(nil), store.outbox...)
	store.mu.Unlock()
	if chatCount != 1 {
		t.Fatalf("expected 1 persisted chat, got %d", chatCount)
	}
	if len(outbox) != 1 || outbox[0].Severity != contracts.SeverityRed {
		t.Fatalf("expected 1 RED outbox record on STORE_AND_FORWARD, got %+v", outbox)
	}
	if ipc.lastChatReq == nil || ipc.lastChatReq.Summary24h != store.summary || len(ipc.lastChatReq.RecentHistory) != 2 {
		t.Fatalf("CHAT_CORRELATE_REQ missing context: %+v", ipc.lastChatReq)
	}

	// HandleSelfExam -> persists + notifies pipeline callback.
	if err := m.HandleSelfExam(ctx, "crew-1", contracts.SelfExamPayload{ExamType: "amsler", Result: "metamorphopsia"}); err != nil {
		t.Fatalf("HandleSelfExam failed: %v", err)
	}
	notifier.mu.Lock()
	nExams := len(notifier.exams)
	notifier.mu.Unlock()
	if nExams != 1 {
		t.Fatalf("expected SelfExamNotifier called once, got %d", nExams)
	}

	// HandleCalibrationStep -> updates snapshot CalibrationActive + emits CALIBRATION_FEEDBACK.
	fb, err := m.HandleCalibrationStep(ctx, "crew-1", contracts.CalibrationStepPayload{StepID: "step-1", Action: "start", DurationMs: 5000})
	if err != nil || fb.Progress != 100 {
		t.Fatalf("HandleCalibrationStep failed: fb=%+v err=%v", fb, err)
	}
	if !m.Snapshot().CalibrationActive || m.Snapshot().CalibStepID != "step-1" {
		t.Fatalf("expected CalibrationActive=true, got %+v", m.Snapshot())
	}

	var sawChatReply, sawCalibFb bool
	for _, ev := range ui.Events() {
		if ev.Type == contracts.WSMsgChatReply {
			sawChatReply = true
		}
		if ev.Type == contracts.WSMsgCalibrationFeedback {
			sawCalibFb = true
		}
	}
	if !sawChatReply || !sawCalibFb {
		t.Fatalf("missing UI events: chatReply=%v calibFb=%v", sawChatReply, sawCalibFb)
	}
}
