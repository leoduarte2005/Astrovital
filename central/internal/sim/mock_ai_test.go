package sim

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
	"edgespace/central/internal/ipc"
)

func startMockAndClient(t *testing.T, aiCfg MockAIConfig, cliCfg ipc.Config) (*MockAI, *ipc.Client, context.CancelFunc, <-chan error) {
	t.Helper()
	aiCfg.Addr = "127.0.0.1:0"
	if aiCfg.AckDelay == 0 {
		aiCfg.AckDelay = 20 * time.Millisecond
	}
	mockAI, err := NewMockAI(aiCfg)
	if err != nil {
		t.Fatalf("NewMockAI: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	go func() { _ = mockAI.Run(ctx) }()

	cliCfg.Addr = mockAI.Addr()
	if cliCfg.MinBackoff == 0 {
		cliCfg.MinBackoff = 15 * time.Millisecond
	}
	if cliCfg.MaxBackoff == 0 {
		cliCfg.MaxBackoff = 30 * time.Millisecond
	}
	client, err := ipc.New(cliCfg, ipc.Deps{})
	if err != nil {
		cancel()
		t.Fatalf("ipc.New: %v", err)
	}
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	deadline := time.Now().Add(2 * time.Second)
	for !client.Connected() && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if !client.Connected() {
		cancel()
		<-done
		t.Fatal("ipc client failed to connect to MockAI")
	}
	return mockAI, client, cancel, done
}

func TestMockAISetActiveCrewAndInference(t *testing.T) {
	mockAI, client, cancel, done := startMockAndClient(t, MockAIConfig{Scenario: ""}, ipc.Config{})
	defer func() { cancel(); <-done }()

	ack, err := client.SendSetActiveCrew(context.Background(), 1, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
	if err != nil || !ack.OK || !ack.BaselineFound {
		t.Fatalf("crew_001 expected OK=true BaselineFound=true, got ack=%+v err=%v", ack, err)
	}

	ack3, err := client.SendSetActiveCrew(context.Background(), 2, contracts.SetActiveCrewPayload{CrewID: "crew_003"})
	if err != nil || !ack3.OK || ack3.BaselineFound {
		t.Fatalf("crew_003 expected OK=true BaselineFound=false, got ack=%+v err=%v", ack3, err)
	}

	crew := "crew_001"
	if err := client.EnqueueCSIWindow(&crew, contracts.CSIWindowPayload{
		CycleSeqFirst: 105,
		Mode:          contracts.ModeCabinTomography,
	}); err != nil {
		t.Fatalf("EnqueueCSIWindow: %v", err)
	}
	select {
	case msg := <-client.InferenceCh():
		if msg.Payload.CycleSeqFirst != 105 {
			t.Fatalf("expected cycle_seq_first=105, got %d", msg.Payload.CycleSeqFirst)
		}
		if msg.Payload.AnomalyScore >= 0.2 {
			t.Fatalf("nominal anomaly score should be low, got %v", msg.Payload.AnomalyScore)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for AI_INFERENCE")
	}

	mockAI.SetScenario("hypercapnia")
	if err := client.EnqueueCSIWindow(&crew, contracts.CSIWindowPayload{
		CycleSeqFirst: 110,
		Mode:          contracts.ModeCabinTomography,
	}); err != nil {
		t.Fatalf("EnqueueCSIWindow 2: %v", err)
	}
	select {
	case msg := <-client.InferenceCh():
		if msg.Payload.CycleSeqFirst != 110 || msg.Payload.AnomalyScore < 0.5 {
			t.Fatalf("hypercapnia inference unexpected: %+v", msg.Payload)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for hypercapnia AI_INFERENCE")
	}
}

func TestMockAIChatAndCalibration(t *testing.T) {
	_, client, cancel, done := startMockAndClient(t, MockAIConfig{}, ipc.Config{})
	defer func() { cancel(); <-done }()

	cases := []struct {
		query string
		want  string
	}{
		{"I have a headache and CO2 is rising", "hypercapnia"},
		{"Abnormal Amsler grid test", "sans"},
		{"Poor sleep and dehydration", "hrv"},
		{"Solar particle storm SPE alert", "spe"},
	}
	crew := "crew_001"
	for _, tc := range cases {
		resp, err := client.SendChatCorrelate(context.Background(), &crew, contracts.ChatCorrelateReqPayload{
			Text:   tc.query,
			CrewID: crew,
		})
		if err != nil {
			t.Fatalf("SendChatCorrelate(%q): %v", tc.query, err)
		}
		if !strings.Contains(strings.ToLower(resp.Text), tc.want) {
			t.Fatalf("query %q: expected %q in %q", tc.query, tc.want, resp.Text)
		}
	}

	var lastProg int
	for i := 1; i <= 4; i++ {
		fb, err := client.SendCalibrationStep(context.Background(), &crew, contracts.CalibrationStepPayload{
			StepID: "rest_baseline", Action: "hold", DurationMs: 5000,
		})
		if err != nil {
			t.Fatalf("SendCalibrationStep %d: %v", i, err)
		}
		if fb.Progress <= lastProg {
			t.Fatalf("expected progressive progress, got %d after %d", fb.Progress, lastProg)
		}
		lastProg = fb.Progress
	}
	if lastProg != 100 {
		t.Fatalf("expected final calibration progress 100, got %d", lastProg)
	}
}

func TestMockAIDropAckTimeout(t *testing.T) {
	_, client, cancel, done := startMockAndClient(t,
		MockAIConfig{DropAck: true, LatencyMs: 5},
		ipc.Config{CrewAckTimeout: 80 * time.Millisecond, SweepInterval: 15 * time.Millisecond},
	)
	defer func() { cancel(); <-done }()

	_, err := client.SendSetActiveCrew(context.Background(), 1, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
	if !errors.Is(err, ipc.ErrTimeout) {
		t.Fatalf("expected ipc.ErrTimeout when DropAck=true, got %v", err)
	}
}

func TestMockAICrashAfterReconnect(t *testing.T) {
	_, client, cancel, done := startMockAndClient(t,
		MockAIConfig{CrashAfter: 120 * time.Millisecond},
		ipc.Config{MinBackoff: 15 * time.Millisecond, MaxBackoff: 30 * time.Millisecond},
	)
	defer func() { cancel(); <-done }()

	ack1, err := client.SendSetActiveCrew(context.Background(), 1, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
	if err != nil || !ack1.OK {
		t.Fatalf("initial SendSetActiveCrew failed: ack=%+v err=%v", ack1, err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for (client.Stats().Reconnects < 1 || !client.Connected()) && time.Now().Before(deadline) {
		time.Sleep(15 * time.Millisecond)
	}
	if client.Stats().Reconnects < 1 || !client.Connected() {
		t.Fatalf("expected reconnect after CrashAfter, stats=%+v", client.Stats())
	}

	ack2, err := client.SendSetActiveCrew(context.Background(), 2, contracts.SetActiveCrewPayload{CrewID: "crew_002"})
	if err != nil || !ack2.OK {
		t.Fatalf("SendSetActiveCrew after reconnect failed: ack=%+v err=%v", ack2, err)
	}
}

func TestMockAISetScenarioChangesInferenceAndChat(t *testing.T) {
	mockAI, client, cancel, done := startMockAndClient(t, MockAIConfig{}, ipc.Config{})
	defer func() { cancel(); <-done }()

	crew := "crew_001"
	scenarios := []struct {
		name        string
		wantPosture string
		wantChatSub string
	}{
		{ScenarioHypercapnia, "supine", "hypercapnia"},
		{ScenarioSANS, "upright", "sans"},
		{ScenarioSolarStorm, "shelter_crouch", "spe"},
		{ScenarioDehydrationSleep, "supine", "hrv"},
	}

	seenInf := make(map[contracts.AIInferencePayload]string)
	seenChat := make(map[string]string)

	for i, sc := range scenarios {
		mockAI.SetScenario(sc.name)
		seq := uint32(200 + i)
		if err := client.EnqueueCSIWindow(&crew, contracts.CSIWindowPayload{
			CycleSeqFirst: seq,
			Mode:          contracts.ModeCabinTomography,
		}); err != nil {
			t.Fatalf("%s EnqueueCSIWindow: %v", sc.name, err)
		}
		var inf contracts.AIInferencePayload
		select {
		case msg := <-client.InferenceCh():
			inf = msg.Payload
		case <-time.After(2 * time.Second):
			t.Fatalf("%s timed out waiting for AI_INFERENCE", sc.name)
		}
		if inf.Posture != sc.wantPosture || inf.AnomalyScore < 0.4 {
			t.Fatalf("%s unexpected inference: %+v", sc.name, inf)
		}
		infKey := inf
		infKey.CycleSeqFirst = 0
		if prev, dup := seenInf[infKey]; dup {
			t.Fatalf("scenario %s produced duplicate AI_INFERENCE with %s: %+v", sc.name, prev, inf)
		}
		seenInf[infKey] = sc.name

		resp, err := client.SendChatCorrelate(context.Background(), &crew, contracts.ChatCorrelateReqPayload{
			Text:   "avaliacao clinica de rotina",
			CrewID: crew,
		})
		if err != nil {
			t.Fatalf("%s SendChatCorrelate: %v", sc.name, err)
		}
		if !strings.Contains(strings.ToLower(resp.Text), sc.wantChatSub) {
			t.Fatalf("%s chat text=%q missing %q", sc.name, resp.Text, sc.wantChatSub)
		}
		if prev, dup := seenChat[resp.Text]; dup {
			t.Fatalf("scenario %s produced duplicate chat reply with %s: %q", sc.name, prev, resp.Text)
		}
		seenChat[resp.Text] = sc.name
	}
}
