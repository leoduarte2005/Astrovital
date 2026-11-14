package sim_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"math"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/cluster"
	"edgespace/central/internal/contracts"
	"edgespace/central/internal/sim"
	"edgespace/central/internal/udp"
)

type recordingSink struct {
	mu    sync.Mutex
	ctrls []sim.ControlEvent
	datas []sim.DataEvent
}

func (s *recordingSink) PushControl(ev sim.ControlEvent) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ctrls = append(s.ctrls, ev)
	return true
}

func (s *recordingSink) PushData(ev sim.DataEvent) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.datas = append(s.datas, ev)
	return true
}

func TestMockClusterDeterminism(t *testing.T) {
	ctx := context.Background()
	s1 := &recordingSink{}
	s2 := &recordingSink{}

	mc1, err := sim.NewMockCluster(sim.MockClusterConfig{Seed: 1337, Scenario: sim.ScenarioHypercapnia}, s1)
	if err != nil {
		t.Fatalf("NewMockCluster 1: %v", err)
	}
	mc2, err := sim.NewMockCluster(sim.MockClusterConfig{Seed: 1337, Scenario: sim.ScenarioHypercapnia}, s2)
	if err != nil {
		t.Fatalf("NewMockCluster 2: %v", err)
	}

	for i := 0; i < 15; i++ {
		if err := mc1.Step(ctx); err != nil {
			t.Fatalf("mc1.Step(%d): %v", i, err)
		}
		if err := mc2.Step(ctx); err != nil {
			t.Fatalf("mc2.Step(%d): %v", i, err)
		}
	}

	if len(s1.datas) == 0 || len(s1.datas) != len(s2.datas) {
		t.Fatalf("data count mismatch: %d vs %d", len(s1.datas), len(s2.datas))
	}
	var csiCount, periphCount int
	for i := range s1.datas {
		a, b := s1.datas[i], s2.datas[i]
		if a.Type != b.Type {
			t.Fatalf("data[%d] type mismatch: %v vs %v", i, a.Type, b.Type)
		}
		if a.CSI != nil {
			csiCount++
			if !bytes.Equal(a.CSI.RawPayload, b.CSI.RawPayload) {
				t.Fatalf("data[%d] CSI RawPayload differs for identical seed", i)
			}
			if len(a.CSI.Samples) != len(b.CSI.Samples) {
				t.Fatalf("data[%d] IQ len mismatch", i)
			}
			for k := range a.CSI.Samples {
				if a.CSI.Samples[k] != b.CSI.Samples[k] {
					t.Fatalf("data[%d] IQ[%d] differs: %+v vs %+v", i, k, a.CSI.Samples[k], b.CSI.Samples[k])
				}
			}
		}
		if a.Peripheral != nil {
			periphCount++
			if len(a.Peripheral.Peripherals) != len(b.Peripheral.Peripherals) {
				t.Fatalf("data[%d] periph len mismatch", i)
			}
			for k := range a.Peripheral.Peripherals {
				if a.Peripheral.Peripherals[k] != b.Peripheral.Peripherals[k] {
					t.Fatalf("data[%d] periph[%d] differs: %+v vs %+v", i, k, a.Peripheral.Peripherals[k], b.Peripheral.Peripherals[k])
				}
			}
		}
	}
	if csiCount == 0 || periphCount == 0 {
		t.Fatalf("expected both CSI (%d) and peripheral (%d) events", csiCount, periphCount)
	}
}

type clusterAdapter struct {
	ctx context.Context
	mgr *cluster.Manager
}

func (a *clusterAdapter) PushControl(ev sim.ControlEvent) bool {
	switch ev.Type {
	case contracts.UDPMsgNodeHello:
		if ev.Hello != nil {
			_, _ = a.mgr.HandleNodeHello(a.ctx, *ev.Hello)
		}
	case contracts.UDPMsgHeartbeat:
		if ev.Heartbeat != nil {
			_ = a.mgr.HandleHeartbeat(a.ctx, *ev.Heartbeat)
		}
	}
	return true
}

func (a *clusterAdapter) PushData(ev sim.DataEvent) bool {
	switch ev.Type {
	case contracts.UDPMsgCSIFrame:
		if ev.CSI != nil {
			a.mgr.HandlePacketSeen(ev.CSI.Header.NodeID, int(ev.CSI.RSSIDbm))
		}
	case contracts.UDPMsgPeripheralData:
		if ev.Peripheral != nil {
			a.mgr.HandlePeripherals(ev.Peripheral.NodeID, ev.Peripheral.Peripherals)
		}
	}
	return true
}

type fakeClock struct{ now time.Time }

func (c *fakeClock) Now() time.Time { return c.now }

// harness wires MockCluster -> adapter -> cluster.Manager with a fake clock.
type harness struct {
	ctx context.Context
	clk *fakeClock
	mgr *cluster.Manager
	mc  *sim.MockCluster
}

func newHarness(t *testing.T, scenario string, seed int64) *harness {
	t.Helper()
	h := &harness{
		ctx: context.Background(),
		clk: &fakeClock{now: time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)},
	}
	h.mgr = cluster.New(cluster.Config{Now: h.clk.Now}, nil)
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Seed:     seed,
		Scenario: scenario,
		BaseTime: h.clk.now,
		SlotScheduleFn: func() sim.SlotSchedule {
			sm := h.mgr.SlotMap()
			return sim.SlotSchedule{ActiveNodeMask: sm.ActiveNodeMask, Slots: sm.Slots}
		},
		CycleSeqFn: nil,
	}, &clusterAdapter{ctx: h.ctx, mgr: h.mgr})
	if err != nil {
		t.Fatalf("NewMockCluster: %v", err)
	}
	h.mc = mc
	return h
}

// step runs one 100 ms cycle: sim emits, manager sweeps, fake clock advances.
func (h *harness) step(t *testing.T) {
	t.Helper()
	if err := h.mc.Step(h.ctx); err != nil {
		t.Fatalf("Step: %v", err)
	}
	h.mgr.Tick(h.ctx)
	h.clk.now = h.clk.now.Add(100 * time.Millisecond)
}

func TestMockClusterFailoverWithClusterManager(t *testing.T) {
	h := newHarness(t, sim.ScenarioNominal, 99)

	// HELLO + 3 heartbeats -> 5 ACTIVE / 20 links.
	for i := 0; i < 5; i++ {
		h.step(t)
	}
	if sm := h.mgr.SlotMap(); sm.ActiveNodes != 5 || sm.ActiveLinks != 20 {
		t.Fatalf("converged SlotMap nodes=%d links=%d, want 5/20", sm.ActiveNodes, sm.ActiveLinks)
	}

	// KillNode(3): 4 ACTIVE / 12 links within 400 ms.
	h.mc.KillNode(3)
	killedAt := h.clk.now
	var failoverWall time.Duration
	for i := 0; i < 6; i++ {
		h.step(t)
		if failoverWall == 0 && h.mgr.SlotMap().ActiveLinks == 12 {
			failoverWall = h.clk.now.Sub(killedAt)
		}
	}
	if sm := h.mgr.SlotMap(); sm.ActiveNodes != 4 || sm.ActiveLinks != 12 {
		t.Fatalf("after KillNode(3) nodes=%d links=%d, want 4/12", sm.ActiveNodes, sm.ActiveLinks)
	}
	if failoverWall <= 0 || failoverWall > 400*time.Millisecond {
		t.Fatalf("failover took %v, want <= 400ms", failoverWall)
	}
	if fms := h.mgr.FailoverLastMs(); fms <= 0 || fms > 400 {
		t.Fatalf("FailoverLastMs=%d, want (0, 400]", fms)
	}

	// ReviveNode(3): reboot (HELLO + 3 HBs) -> back to 5/20.
	h.mc.ReviveNode(3)
	for i := 0; i < 6; i++ {
		h.step(t)
	}
	if sm := h.mgr.SlotMap(); sm.ActiveNodes != 5 || sm.ActiveLinks != 20 {
		t.Fatalf("after ReviveNode(3) nodes=%d links=%d, want 5/20", sm.ActiveNodes, sm.ActiveLinks)
	}
}

func TestMockClusterNodeLossScenario(t *testing.T) {
	h := newHarness(t, sim.ScenarioNodeLoss, 7)
	var at16s, at44s, at50s int
	for c := 0; c <= 520; c++ {
		h.step(t)
		switch c {
		case 160:
			at16s = h.mgr.SlotMap().ActiveLinks
		case 440:
			at44s = h.mgr.SlotMap().ActiveLinks
		case 520:
			at50s = h.mgr.SlotMap().ActiveLinks
		}
	}
	if at16s != 12 || at44s != 12 || at50s != 20 {
		t.Fatalf("node_loss links t=16s/44s/52s = %d/%d/%d, want 12/12/20", at16s, at44s, at50s)
	}
}

func TestMockClusterUDPMode(t *testing.T) {
	sink := udp.NewChannelSink()
	rx := udp.NewReceiver(udp.ReceiverConfig{Addr: "127.0.0.1:0"}, sink)
	if err := rx.Bind(); err != nil {
		t.Fatalf("rx.Bind: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rxErr := make(chan error, 1)
	go func() { rxErr <- rx.Run(ctx) }()

	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Mode:       sim.SimModeUDP,
		TargetAddr: rx.Addr().String(),
		Seed:       55,
	}, nil)
	if err != nil {
		t.Fatalf("NewMockCluster udp: %v", err)
	}
	defer mc.Close()

	if err := mc.Step(ctx); err != nil {
		t.Fatalf("mc.Step: %v", err)
	}

	seen := make(map[[2]uint8]bool)
	deadline := time.After(3 * time.Second)
	for len(seen) < 20 {
		select {
		case msg := <-sink.DataCh:
			if msg.Type != contracts.UDPMsgCSIFrame || msg.CSI == nil {
				continue
			}
			if msg.CSI.Header.CycleSeq != 1 {
				t.Fatalf("cycle_seq=%d, want 1", msg.CSI.Header.CycleSeq)
			}
			if len(msg.CSI.Samples) != sim.DefaultSubcarriers {
				t.Fatalf("samples=%d, want %d", len(msg.CSI.Samples), sim.DefaultSubcarriers)
			}
			seen[[2]uint8{msg.CSI.TxNodeID, msg.CSI.RxNodeID}] = true
		case <-deadline:
			t.Fatalf("timeout: decoded %d/20 links over UDP", len(seen))
		}
	}
	if d := sink.DroppedFrames(); d != 0 {
		t.Fatalf("DroppedFrames=%d, want 0", d)
	}

	cancel()
	if err := <-rxErr; err != nil {
		t.Fatalf("rx.Run: %v", err)
	}
}

func TestMockClusterScenariosAndMockAISync(t *testing.T) {
	ctx := context.Background()
	ai, err := sim.NewMockAI(sim.MockAIConfig{Addr: "127.0.0.1:0"})
	if err != nil {
		t.Fatalf("NewMockAI: %v", err)
	}
	aiCtx, aiCancel := context.WithCancel(ctx)
	defer aiCancel()
	go func() { _ = ai.Run(aiCtx) }()

	var sawSolar, sawSANS bool
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Seed:   11,
		MockAI: ai,
		OnModeChange: func(m contracts.MissionMode) {
			if m == contracts.ModeRadiationAlert {
				sawSolar = true
			}
		},
		OnSelfExam: func(ev sim.SelfExamEvent) {
			if ev.Metamorphopsia && ev.SystolicMmHg > 140 {
				sawSANS = true
			}
		},
	}, &recordingSink{})
	if err != nil {
		t.Fatalf("NewMockCluster: %v", err)
	}

	if err := mc.SetScenario(sim.ScenarioSolarStorm); err != nil {
		t.Fatalf("SetScenario: %v", err)
	}
	if ai.Scenario() != sim.ScenarioSolarStorm {
		t.Fatalf("MockAI scenario=%q, want solar_storm", ai.Scenario())
	}
	for i := 0; i < 95; i++ {
		_ = mc.Step(ctx)
	}
	if sawSolar {
		t.Fatal("solar_storm fired before t=10s")
	}
	for i := 0; i < 10; i++ {
		_ = mc.Step(ctx)
	}
	if !sawSolar {
		t.Fatal("solar_storm did not fire MODE_RADIATION_ALERT after t=10s")
	}

	if err := mc.SetScenario(sim.ScenarioSANS); err != nil {
		t.Fatalf("SetScenario sans: %v", err)
	}
	for i := 0; i < 25; i++ {
		_ = mc.Step(ctx)
	}
	if !sawSANS {
		t.Fatal("sans did not emit Amsler metamorphopsia self-exam")
	}
	if err := mc.SetScenario("bogus"); err == nil {
		t.Fatal("SetScenario(bogus) must fail")
	}
}

func TestMockClusterHypercapniaRamp(t *testing.T) {
	sink := &recordingSink{}
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{Seed: 3, Scenario: sim.ScenarioHypercapnia}, sink)
	if err != nil {
		t.Fatalf("NewMockCluster: %v", err)
	}
	ctx := context.Background()
	var first, last float64
	for i := 0; i <= 1210; i++ {
		_ = mc.Step(ctx)
	}
	for _, ev := range sink.datas {
		if ev.Peripheral == nil || ev.Peripheral.NodeID != 1 {
			continue
		}
		for _, r := range ev.Peripheral.Peripherals {
			if r.Type == contracts.PeripheralSCD40 {
				if first == 0 {
					first = r.Value
				}
				last = r.Value
			}
		}
	}
	if first < 550 || first > 650 || last < 4900 || last > 5100 {
		t.Fatalf("SCD40 ramp first=%.1f last=%.1f, want ~600 -> ~5000", first, last)
	}
}

func hash3sFrames(t *testing.T, seed int64) [32]byte {
	t.Helper()
	ctx := context.Background()
	sink := &recordingSink{}
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Seed:     seed,
		Scenario: sim.ScenarioHypercapnia,
	}, sink)
	if err != nil {
		t.Fatalf("NewMockCluster(%d): %v", seed, err)
	}
	// 30 cycles * 100 ms = 3 s
	for i := 0; i < 30; i++ {
		if err := mc.Step(ctx); err != nil {
			t.Fatalf("Step(%d): %v", i, err)
		}
	}
	h := sha256.New()
	var buf [8]byte
	for _, ev := range sink.datas {
		_, _ = h.Write([]byte(ev.Type))
		if ev.CSI != nil {
			binary.LittleEndian.PutUint32(buf[:4], ev.CSI.Header.CycleSeq)
			_, _ = h.Write(buf[:4])
			_, _ = h.Write([]byte{ev.CSI.TxNodeID, ev.CSI.RxNodeID})
			_, _ = h.Write(ev.CSI.RawPayload)
		}
		if ev.Peripheral != nil {
			_, _ = h.Write([]byte{ev.Peripheral.NodeID})
			for _, r := range ev.Peripheral.Peripherals {
				_, _ = h.Write([]byte(r.Type))
				binary.LittleEndian.PutUint64(buf[:], math.Float64bits(r.Value))
				_, _ = h.Write(buf[:])
			}
		}
	}
	var sum [32]byte
	copy(sum[:], h.Sum(nil))
	return sum
}

func TestMockClusterSHA256Determinism3sAndDifferentSeeds(t *testing.T) {
	h1 := hash3sFrames(t, 1337)
	h2 := hash3sFrames(t, 1337)
	h3 := hash3sFrames(t, 1338)
	if h1 != h2 {
		t.Fatalf("same seed produced different SHA-256 hashes: %x vs %x", h1, h2)
	}
	if h1 == h3 {
		t.Fatalf("different seeds produced identical SHA-256 hash: %x", h1)
	}
}

func TestMockClusterLossRate50Percent(t *testing.T) {
	ctx := context.Background()
	sink := &recordingSink{}
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Seed:     42,
		LossRate: 0.5,
	}, sink)
	if err != nil {
		t.Fatalf("NewMockCluster: %v", err)
	}
	const cycles = 200
	for i := 0; i < cycles; i++ {
		if err := mc.Step(ctx); err != nil {
			t.Fatalf("Step(%d): %v", i, err)
		}
	}
	var csiCount int
	for _, ev := range sink.datas {
		if ev.Type == contracts.UDPMsgCSIFrame {
			csiCount++
		}
	}
	expected := float64(cycles * 20) // 4000 frames at 0% loss
	ratio := float64(csiCount) / expected
	if ratio < 0.35 || ratio > 0.65 {
		t.Fatalf("LossRate=0.5 delivered %d/%d frames (ratio=%.3f), want 0.50 +- 0.15", csiCount, int(expected), ratio)
	}
}
