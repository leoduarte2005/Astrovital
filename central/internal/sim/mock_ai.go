// Package sim holds the in-process simulators: MockAI (Edge AI worker) and,
// in later levas, the virtual cluster and scenarios.
package sim

import (
	"context"
	"encoding/json"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

// DefaultAckDelay is the CREW_ACK latency of the mock worker (§5.3).
const DefaultAckDelay = 150 * time.Millisecond

// MockAIConfig configures the in-process Edge AI worker.
type MockAIConfig struct {
	Addr       string        // listen address; "127.0.0.1:0" in tests
	Logger     *slog.Logger  // optional
	Scenario   string        // initial scenario; "" = nominal
	AckDelay   time.Duration // CREW_ACK delay; 0 = DefaultAckDelay
	LatencyMs  int           // extra latency applied to every response
	DropAck    bool          // never answer SET_ACTIVE_CREW (exercises 2s timeout)
	CrashAfter time.Duration // once, close every connection after this delay; 0 = never
}

// MockAI is a real TCP listener speaking the IPC framing so the ipc client
// exercises framing, queues, timeouts and reconnect for real.
type MockAI struct {
	cfg      MockAIConfig
	log      *slog.Logger
	ln       net.Listener
	scenario atomic.Value // string

	mu    sync.Mutex
	conns map[net.Conn]struct{}

	calibMu    sync.Mutex
	calibSteps map[string]int
}

// NewMockAI binds the listener. Call Run to serve.
func NewMockAI(cfg MockAIConfig) (*MockAI, error) {
	if cfg.Addr == "" {
		cfg.Addr = "127.0.0.1:5006"
	}
	if cfg.AckDelay <= 0 {
		cfg.AckDelay = DefaultAckDelay
	}
	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}
	ln, err := net.Listen("tcp", cfg.Addr)
	if err != nil {
		return nil, err
	}
	m := &MockAI{
		cfg:        cfg,
		log:        log,
		ln:         ln,
		conns:      make(map[net.Conn]struct{}),
		calibSteps: make(map[string]int),
	}
	m.scenario.Store(cfg.Scenario)
	return m, nil
}

// Addr returns the bound listen address.
func (m *MockAI) Addr() string { return m.ln.Addr().String() }

// SetScenario switches the active scenario; safe for concurrent use.
func (m *MockAI) SetScenario(s string) { m.scenario.Store(s) }

// Scenario returns the active scenario.
func (m *MockAI) Scenario() string {
	s, _ := m.scenario.Load().(string)
	return s
}

// Run serves until ctx is cancelled, then closes listener and connections.
func (m *MockAI) Run(ctx context.Context) error {
	m.log.Info("mock ai listening", "addr", m.Addr())
	var wg sync.WaitGroup

	if m.cfg.CrashAfter > 0 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			t := time.NewTimer(m.cfg.CrashAfter)
			defer t.Stop()
			select {
			case <-t.C:
				m.log.Warn("mock ai crash injected")
				m.closeConns()
			case <-ctx.Done():
			}
		}()
	}

	go func() {
		<-ctx.Done()
		_ = m.ln.Close()
		m.closeConns()
	}()

	for {
		conn, err := m.ln.Accept()
		if err != nil {
			break
		}
		m.track(conn, true)
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer m.track(conn, false)
			m.serve(ctx, conn)
		}()
	}
	wg.Wait()
	return nil
}

func (m *MockAI) track(c net.Conn, add bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if add {
		m.conns[c] = struct{}{}
		return
	}
	delete(m.conns, c)
	_ = c.Close()
}

func (m *MockAI) closeConns() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for c := range m.conns {
		_ = c.Close()
	}
}

func (m *MockAI) serve(ctx context.Context, conn net.Conn) {
	var fr contracts.FrameReader
	var fw contracts.FrameWriter
	for ctx.Err() == nil {
		raw, err := fr.Read(conn)
		if err != nil {
			return
		}
		var env contracts.IPCEnvelope
		if json.Unmarshal(raw, &env) != nil || env.Validate() != nil {
			continue
		}
		m.handle(conn, &fw, env)
	}
}

func (m *MockAI) reply(conn net.Conn, fw *contracts.FrameWriter, typ contracts.IPCMsgType, crew *string, reqID *uint64, payload any) {
	env, err := contracts.NewIPCEnvelope(typ, time.Now().UnixMicro(), crew, reqID, payload)
	if err != nil {
		return
	}
	body, err := json.Marshal(env)
	if err != nil {
		return
	}
	_ = conn.SetWriteDeadline(time.Now().Add(time.Second))
	_ = fw.Write(conn, body)
}

func (m *MockAI) handle(conn net.Conn, fw *contracts.FrameWriter, req contracts.IPCEnvelope) {
	if m.cfg.LatencyMs > 0 {
		time.Sleep(time.Duration(m.cfg.LatencyMs) * time.Millisecond)
	}
	switch req.Type {
	case contracts.IPCMsgSetActiveCrew:
		if m.cfg.DropAck {
			return
		}
		var p contracts.SetActiveCrewPayload
		if json.Unmarshal(req.Payload, &p) != nil {
			return
		}
		time.Sleep(m.cfg.AckDelay)
		m.reply(conn, fw, contracts.IPCMsgCrewAck, req.CrewID, req.ReqID,
			contracts.CrewAckPayload{OK: true, BaselineFound: p.CrewID != "crew_003"})
	case contracts.IPCMsgCSIWindow:
		var p contracts.CSIWindowPayload
		if json.Unmarshal(req.Payload, &p) != nil {
			return
		}
		m.reply(conn, fw, contracts.IPCMsgAIInference, req.CrewID, nil,
			inferenceFor(m.Scenario(), p.CycleSeqFirst))
	case contracts.IPCMsgChatCorrelateReq:
		var p contracts.ChatCorrelateReqPayload
		if json.Unmarshal(req.Payload, &p) != nil {
			return
		}
		m.reply(conn, fw, contracts.IPCMsgChatCorrelateResp, req.CrewID, req.ReqID,
			chatFor(m.Scenario(), p.Text))
	case contracts.IPCMsgCalibrationStep:
		var p contracts.CalibrationStepPayload
		if json.Unmarshal(req.Payload, &p) != nil {
			return
		}
		m.reply(conn, fw, contracts.IPCMsgCalibrationFeedback, req.CrewID, req.ReqID,
			m.nextCalibration(p.StepID))
	}
}

// nextCalibration advances 25% per CALIBRATION_STEP of the same step_id (0 -> 100).
func (m *MockAI) nextCalibration(stepID string) contracts.CalibrationFeedbackPayload {
	m.calibMu.Lock()
	n := m.calibSteps[stepID] + 1
	if n > 4 {
		n = 4
	}
	m.calibSteps[stepID] = n
	m.calibMu.Unlock()
	return contracts.CalibrationFeedbackPayload{
		StepID:   stepID,
		Progress: n * 25,
		Quality:  0.9 + 0.025*float64(n),
	}
}
