package httpws

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"

	"edgespace/central/internal/contracts"
)

type stubReader struct {
	crew      []contracts.CrewSummary
	healthErr error
}

func (r stubReader) Health(context.Context) error { return r.healthErr }
func (r stubReader) ListCrew(context.Context) ([]contracts.CrewSummary, error) {
	return r.crew, nil
}

func TestHTTPHealthzCSPAndMetrics(t *testing.T) {
	srv, err := New(Config{WSHz: 5}, Deps{
		Reader: stubReader{crew: nil}, // nil slice must still encode as []
		StoreStats: func() StoreStats {
			return StoreStats{Commits: 7, Backlog: 2}
		},
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	// 1) /healthz 200 + CSP
	resp, err := http.Get(ts.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/healthz status = %d", resp.StatusCode)
	}
	if got := resp.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("CSP = %q, want %q", got, cspPolicy)
	}

	// 2) /api/metrics + CSP + exact keys
	resp, err = http.Get(ts.URL + "/api/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if got := resp.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("metrics CSP = %q", got)
	}
	metricsRaw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	var metricsMap map[string]any
	if err := json.Unmarshal(metricsRaw, &metricsMap); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"ws_clients", "ws_dropped_telemetry", "store_commits", "store_backlog"} {
		if _, ok := metricsMap[key]; !ok {
			t.Fatalf("missing metrics key %q in %s", key, string(metricsRaw))
		}
	}
	var m MetricsSnapshot
	if err := json.Unmarshal(metricsRaw, &m); err != nil {
		t.Fatal(err)
	}
	if m.StoreCommits != 7 || m.StoreBacklog != 2 {
		t.Fatalf("unexpected metrics: %+v", m)
	}

	// 3) /api/crew empty -> [] (not null) + CSP
	respCrew, err := http.Get(ts.URL + "/api/crew")
	if err != nil {
		t.Fatal(err)
	}
	defer respCrew.Body.Close()
	if got := respCrew.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("/api/crew CSP = %q", got)
	}
	crewRaw, err := io.ReadAll(respCrew.Body)
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(crewRaw)) != "[]" {
		t.Fatalf("/api/crew body = %q, want []", string(crewRaw))
	}

	// 4) POST /api/crew -> 405 + CSP
	respPost, err := http.Post(ts.URL+"/api/crew", "application/json", strings.NewReader("{}"))
	if err != nil {
		t.Fatal(err)
	}
	respPost.Body.Close()
	if respPost.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("POST /api/crew status = %d, want 405", respPost.StatusCode)
	}
	if got := respPost.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("POST /api/crew CSP = %q", got)
	}

	// 5) Embedded UI root + CSP
	respUI, err := http.Get(ts.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	uiRaw, err := io.ReadAll(respUI.Body)
	respUI.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if respUI.StatusCode != http.StatusOK {
		t.Fatalf("UI status = %d", respUI.StatusCode)
	}
	if got := respUI.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("UI CSP = %q", got)
	}
	if !strings.Contains(string(uiRaw), "EdgeSpace Central") {
		t.Fatal("expected embedded index.html content")
	}

	// 6) 404 + CSP
	resp404, err := http.Get(ts.URL + "/does-not-exist-404")
	if err != nil {
		t.Fatal(err)
	}
	resp404.Body.Close()
	if resp404.StatusCode != http.StatusNotFound {
		t.Fatalf("404 status = %d", resp404.StatusCode)
	}
	if got := resp404.Header.Get("Content-Security-Policy"); got != cspPolicy {
		t.Fatalf("404 CSP = %q", got)
	}
}

func TestHTTPHealthz503OnReaderError(t *testing.T) {
	srv, err := New(Config{WSHz: 2}, Deps{
		Reader: stubReader{healthErr: errors.New("db unavailable")},
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("/healthz with failing reader = %d, want 503", resp.StatusCode)
	}
}

func TestWSPushAndInvalidJSONError(t *testing.T) {
	srv, err := New(Config{WSHz: 20}, Deps{Reader: stubReader{}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	hubCtx, hubCancel := context.WithCancel(context.Background())
	defer hubCancel()
	go srv.hub.run(hubCtx)

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("Dial: %v", err)
	}
	defer conn.CloseNow()

	// Expect initial CREW_STATE, CLUSTER_STATUS, and periodic TELEMETRY_FRAME.
	seen := map[contracts.WSMsgType]bool{}
	for len(seen) < 3 {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatalf("Read initial/periodic: %v", err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			t.Fatalf("Unmarshal: %v", err)
		}
		if env.V != contracts.Version {
			t.Fatalf("bad version: %d", env.V)
		}
		seen[env.Type] = true
	}
	if !seen[contracts.WSMsgCrewState] || !seen[contracts.WSMsgClusterStatus] || !seen[contracts.WSMsgTelemetryFrame] {
		t.Fatalf("missing expected initial/periodic types: %+v", seen)
	}

	// Send invalid JSON -> expect ERROR envelope while connection stays open.
	if err := conn.Write(ctx, websocket.MessageText, []byte("{not-json")); err != nil {
		t.Fatalf("Write invalid JSON: %v", err)
	}
	gotErr := false
	for !gotErr {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatalf("Read after invalid JSON: %v", err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			t.Fatal(err)
		}
		if env.Type == contracts.WSMsgError {
			gotErr = true
		}
	}

	// Send valid SET_CREW with client_msg_id and confirm connection stays alive.
	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"SET_CREW","ts_us":1,"crew_id":null,"client_msg_id":"c-valid","payload":{"crew_id":"astronaut_01"}}`)); err != nil {
		t.Fatalf("Write valid SET_CREW: %v", err)
	}
	gotAlive := false
	for !gotAlive {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatalf("Read after valid SET_CREW: %v", err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			t.Fatal(err)
		}
		if env.Type == contracts.WSMsgError {
			t.Fatalf("unexpected ERROR after valid SET_CREW: %s", string(data))
		}
		if env.Type == contracts.WSMsgTelemetryFrame {
			gotAlive = true
		}
	}

	// Connection must remain open: send bad version envelope with client_msg_id.
	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":2,"type":"SET_CREW","ts_us":1,"crew_id":null,"client_msg_id":"c1","payload":{"crew_id":"x"}}`)); err != nil {
		t.Fatalf("Write v2: %v", err)
	}
	gotV2Err := false
	for !gotV2Err {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatalf("Read after v2: %v", err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			t.Fatal(err)
		}
		if env.Type == contracts.WSMsgError && env.ClientMsgID != nil && *env.ClientMsgID == "c1" {
			gotV2Err = true
		}
	}
}

func TestWSOversizeClose1009(t *testing.T) {
	srv, err := New(Config{WSHz: 2}, Deps{Reader: stubReader{}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	hubCtx, hubCancel := context.WithCancel(context.Background())
	defer hubCancel()
	go srv.hub.run(hubCtx)

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("Dial: %v", err)
	}
	defer conn.CloseNow()

	// Exceed 64 KB limit.
	oversize := make([]byte, maxWSMessageBytes+1024)
	for i := range oversize {
		oversize[i] = 'a'
	}
	_ = conn.Write(ctx, websocket.MessageText, oversize)

	for {
		_, _, err := conn.Read(ctx)
		if err != nil {
			if status := websocket.CloseStatus(err); status != websocket.StatusMessageTooBig {
				t.Fatalf("expected close 1009 (StatusMessageTooBig), got %v (%v)", status, err)
			}
			return
		}
	}
}

func TestWSBroadcastRates2HzAnd10Hz(t *testing.T) {
	cases := []struct {
		name   string
		hz     int
		minRPS float64
		maxRPS float64
	}{
		{name: "2hz", hz: 2, minRPS: 1.6, maxRPS: 2.4},
		{name: "10hz", hz: 10, minRPS: 8.0, maxRPS: 12.0},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv, err := New(Config{WSHz: tc.hz}, Deps{Reader: stubReader{}})
			if err != nil {
				t.Fatalf("New: %v", err)
			}
			hubCtx, hubCancel := context.WithCancel(context.Background())
			defer hubCancel()
			go srv.hub.run(hubCtx)

			ts := httptest.NewServer(srv.Handler())
			defer ts.Close()

			wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
			dialCtx, dialCancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer dialCancel()
			conn, _, err := websocket.Dial(dialCtx, wsURL, nil)
			if err != nil {
				t.Fatalf("Dial: %v", err)
			}
			defer conn.CloseNow()

			for i := 0; i < 3; i++ {
				if _, _, err := conn.Read(dialCtx); err != nil {
					t.Fatalf("drain initial %d: %v", i, err)
				}
			}

			const window = 3 * time.Second
			readCtx, readCancel := context.WithTimeout(context.Background(), window)
			defer readCancel()

			frames := 0
			for {
				_, data, err := conn.Read(readCtx)
				if err != nil {
					break
				}
				var env contracts.WSEnvelope
				if err := json.Unmarshal(data, &env); err != nil {
					t.Fatal(err)
				}
				if env.Type == contracts.WSMsgTelemetryFrame {
					frames++
				}
			}
			rps := float64(frames) / window.Seconds()
			if rps < tc.minRPS || rps > tc.maxRPS {
				t.Fatalf("WSHz=%d measured rate = %.2f msg/s (%d frames / 3s), want [%.1f, %.1f]",
					tc.hz, rps, frames, tc.minRPS, tc.maxRPS)
			}
		})
	}
}

func TestWSSlowClientDoesNotBlockFastClientAndIncrementsDrops(t *testing.T) {
	srv, err := New(Config{WSHz: 50}, Deps{Reader: stubReader{}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	// 24 KB (< default 32 KB WS client read limit) fills unread TCP recv buffer quickly.
	srv.Latest().Store(&contracts.TelemetrySnapshot{
		TsUs:        time.Now().UnixMicro(),
		MissionMode: contracts.ModeCabinTomography,
		Vitals: contracts.VitalsData{
			Posture: strings.Repeat("P", 24*1024),
		},
	})

	hubCtx, hubCancel := context.WithCancel(context.Background())
	defer hubCancel()
	go srv.hub.run(hubCtx)

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()

	slowConn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("Dial slow: %v", err)
	}
	defer slowConn.CloseNow()

	fastConn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("Dial fast: %v", err)
	}
	defer fastConn.CloseNow()

	fastFrames := 0
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		rctx, rcancel := context.WithTimeout(ctx, 500*time.Millisecond)
		_, data, err := fastConn.Read(rctx)
		rcancel()
		if err != nil {
			t.Fatalf("fast client blocked or failed: %v", err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err == nil && env.Type == contracts.WSMsgTelemetryFrame {
			fastFrames++
		}
		if srv.Metrics().WSDroppedTelemetry > 0 && fastFrames >= 10 {
			break
		}
	}

	if srv.Metrics().WSDroppedTelemetry == 0 {
		t.Fatal("expected ws_dropped_telemetry > 0, got 0")
	}
	if fastFrames < 10 {
		t.Fatalf("expected fast client to keep receiving frames, got %d", fastFrames)
	}
}

func TestWSEventChImmediateAndClientCountReset(t *testing.T) {
	srv, err := New(Config{WSHz: 2}, Deps{Reader: stubReader{}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	hubCtx, hubCancel := context.WithCancel(context.Background())
	defer hubCancel()
	go srv.hub.run(hubCtx)

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("Dial: %v", err)
	}

	for i := 0; i < 3; i++ {
		if _, _, err := conn.Read(ctx); err != nil {
			t.Fatalf("drain %d: %v", i, err)
		}
	}
	if got := srv.Metrics().WSClients; got != 1 {
		t.Fatalf("ws_clients = %d, want 1", got)
	}

	ev, err := contracts.NewWSEnvelope(contracts.WSMsgAlertEvent, time.Now().UnixMicro(), nil, nil, contracts.AlertEventPayload{
		Subsystem:      contracts.SubsystemRespiratoryAtmosphere,
		Severity:       contracts.SeverityRed,
		Message:        "CO2 high",
		Countermeasure: "Ventilate",
		Escalation:     contracts.EscalationCrew,
		SourceID:       "NASA-HRP-01",
	})
	if err != nil {
		t.Fatal(err)
	}

	sentAt := time.Now()
	srv.EventCh() <- ev

	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatalf("Read event: %v", err)
		}
		var got contracts.WSEnvelope
		if err := json.Unmarshal(data, &got); err != nil {
			t.Fatal(err)
		}
		if got.Type == contracts.WSMsgAlertEvent {
			if elapsed := time.Since(sentAt); elapsed >= 100*time.Millisecond {
				t.Fatalf("EventCh delivery took %v, expected < 100ms", elapsed)
			}
			break
		}
	}

	_ = conn.Close(websocket.StatusNormalClosure, "bye")

	deadline := time.Now().Add(time.Second)
	for srv.Metrics().WSClients != 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if got := srv.Metrics().WSClients; got != 0 {
		t.Fatalf("ws_clients after disconnect = %d, want 0", got)
	}
}

func TestServerShutdownClosesWSWith1001(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()

	srv, err := New(Config{Addr: addr, WSHz: 2}, Deps{Reader: stubReader{}})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	runCtx, runCancel := context.WithCancel(context.Background())
	runDone := make(chan error, 1)
	go func() { runDone <- srv.Run(runCtx) }()

	wsURL := "ws://" + addr + "/ws"
	var conn *websocket.Conn
	dialDeadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(dialDeadline) {
		dctx, dcancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
		c, _, derr := websocket.Dial(dctx, wsURL, nil)
		dcancel()
		if derr == nil {
			conn = c
			break
		}
		time.Sleep(15 * time.Millisecond)
	}
	if conn == nil {
		runCancel()
		t.Fatal("failed to dial running server")
	}
	defer conn.CloseNow()

	rctx, rcancel := context.WithTimeout(context.Background(), 2*time.Second)
	if _, _, err := conn.Read(rctx); err != nil {
		rcancel()
		runCancel()
		t.Fatalf("initial read: %v", err)
	}
	rcancel()

	runCancel()

	readCtx, readCancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer readCancel()
	for {
		_, _, err := conn.Read(readCtx)
		if err != nil {
			if status := websocket.CloseStatus(err); status != websocket.StatusGoingAway {
				t.Fatalf("expected close code 1001 (StatusGoingAway), got %v (%v)", status, err)
			}
			break
		}
	}

	if err := <-runDone; err != nil {
		t.Fatalf("Server.Run returned error: %v", err)
	}
}

type stubExtendedReader struct {
	stubReader
	profiles map[string]CrewProfileDTO
	tsResp   contracts.TimeseriesResponse
	protos   map[string]contracts.ProtocolDTO
	alerts   []contracts.AlertRecord
	outbox   []contracts.OutboxRecord
}

func (s *stubExtendedReader) GetCrewProfile(ctx context.Context, id string) (CrewProfileDTO, error) {
	p, ok := s.profiles[id]
	if !ok {
		return CrewProfileDTO{}, errors.New("crew not found")
	}
	return p, nil
}
func (s *stubExtendedReader) QueryTimeseries(ctx context.Context, crewID, metric string, fromUs, toUs int64, bucketSec int) (contracts.TimeseriesResponse, error) {
	return s.tsResp, nil
}
func (s *stubExtendedReader) GetProtocol(ctx context.Context, id string) (contracts.ProtocolDTO, error) {
	p, ok := s.protos[id]
	if !ok {
		return contracts.ProtocolDTO{}, errors.New("protocol not found")
	}
	return p, nil
}
func (s *stubExtendedReader) ListAlerts(ctx context.Context, limit int) ([]contracts.AlertRecord, error) {
	return s.alerts, nil
}
func (s *stubExtendedReader) ListOutbox(ctx context.Context) ([]contracts.OutboxRecord, error) {
	return s.outbox, nil
}

type stubSessionCmd struct {
	mu         sync.Mutex
	setCrewErr error
	setCrews   []string
	chats      []string
	exams      []contracts.SelfExamPayload
	calibs     []contracts.CalibrationStepPayload
}

func (s *stubSessionCmd) SetCrew(ctx context.Context, crewID string) (contracts.CrewStatePayload, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.setCrews = append(s.setCrews, crewID)
	if s.setCrewErr != nil {
		return contracts.CrewStatePayload{}, s.setCrewErr
	}
	return contracts.CrewStatePayload{CrewID: &crewID, MissionMode: contracts.ModeCabinTomography, AIReady: true}, nil
}
func (s *stubSessionCmd) HandleChatMsg(ctx context.Context, crewID, text string) (contracts.ChatReplyPayload, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.chats = append(s.chats, text)
	return contracts.ChatReplyPayload{Text: "ok"}, nil
}
func (s *stubSessionCmd) HandleSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.exams = append(s.exams, exam)
	return nil
}
func (s *stubSessionCmd) HandleCalibrationStep(ctx context.Context, crewID string, step contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calibs = append(s.calibs, step)
	return contracts.CalibrationFeedbackPayload{StepID: step.StepID, Progress: 100}, nil
}

type stubDevCtrl struct {
	scenario string
	killed   []uint8
	revived  []uint8
}

func (d *stubDevCtrl) SetScenario(ctx context.Context, scenario string, seed int64) error {
	d.scenario = scenario
	return nil
}
func (d *stubDevCtrl) KillNode(ctx context.Context, nodeID uint8) error {
	d.killed = append(d.killed, nodeID)
	return nil
}
func (d *stubDevCtrl) ReviveNode(ctx context.Context, nodeID uint8) error {
	d.revived = append(d.revived, nodeID)
	return nil
}

func TestExtendedRESTDevRoutesAndCSPScript(t *testing.T) {
	ext := &stubExtendedReader{
		profiles: map[string]CrewProfileDTO{
			"crew_001": {Profile: contracts.CrewProfile{CrewID: "crew_001", Name: "Cmdr. Silva"}},
		},
		tsResp: contracts.TimeseriesResponse{CrewID: "crew_001", Buckets: []contracts.TelemetryBucket{{TsUs: 1000}}},
		protos: map[string]contracts.ProtocolDTO{
			"amsler_grid": {ProtocolID: "amsler_grid", Name: "Amsler", Steps: []string{"Step 1"}},
		},
		alerts: []contracts.AlertRecord{{AlertID: "a1", Severity: contracts.SeverityYellow}},
		outbox: []contracts.OutboxRecord{{OutboxID: "o1", Severity: contracts.SeverityRed}},
	}

	srvNoDev, err := New(Config{}, Deps{Reader: ext})
	if err != nil {
		t.Fatal(err)
	}
	tsNoDev := httptest.NewServer(srvNoDev.Handler())
	defer tsNoDev.Close()

	resp, err := http.Post(tsNoDev.URL+"/api/dev/scenario", "application/json", strings.NewReader(`{"scenario":"hypercapnia"}`))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("POST /api/dev/scenario without Dev = %d, want 404", resp.StatusCode)
	}

	dev := &stubDevCtrl{}
	srv, err := New(Config{}, Deps{
		Reader: ext,
		Dev:    dev,
		ExtraMetrics: func() ExtraMetrics {
			return ExtraMetrics{DroppedFrames: 1, DroppedCtrl: 2, IPCDroppedWindows: 3, IPCReconnects: 4, LateFrames: 5, FailoverLastMs: 310}
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	for _, path := range []string{
		"/api/crew/crew_001/profile",
		"/api/crew/crew_001/timeseries?bucket_sec=5",
		"/api/protocols/amsler_grid",
		"/api/alerts?limit=10",
		"/api/outbox",
		"/app.js",
		"/style.css",
	} {
		r, err := http.Get(ts.URL + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		r.Body.Close()
		if r.StatusCode != http.StatusOK {
			t.Fatalf("GET %s status = %d, want 200", path, r.StatusCode)
		}
	}

	rScen, err := http.Post(ts.URL+"/api/dev/scenario", "application/json", strings.NewReader(`{"scenario":"hypercapnia","seed":7}`))
	if err != nil || rScen.StatusCode != http.StatusOK {
		t.Fatalf("POST /api/dev/scenario failed: err=%v resp=%v", err, rScen)
	}
	rScen.Body.Close()
	rKill, err := http.Post(ts.URL+"/api/dev/node/3/kill", "application/json", nil)
	if err != nil || rKill.StatusCode != http.StatusOK {
		t.Fatalf("POST /api/dev/node/3/kill failed: err=%v resp=%v", err, rKill)
	}
	rKill.Body.Close()
	rRev, err := http.Post(ts.URL+"/api/dev/node/3/revive", "application/json", nil)
	if err != nil || rRev.StatusCode != http.StatusOK {
		t.Fatalf("POST /api/dev/node/3/revive failed: err=%v resp=%v", err, rRev)
	}
	rRev.Body.Close()
	if dev.scenario != "hypercapnia" || len(dev.killed) != 1 || len(dev.revived) != 1 {
		t.Fatalf("dev controller not invoked: %+v", dev)
	}

	rUI, err := http.Get(ts.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	rawUI, _ := io.ReadAll(rUI.Body)
	rUI.Body.Close()
	if strings.Contains(string(rawUI), "<script>") || !strings.Contains(string(rawUI), `./app.js`) {
		t.Fatalf("index.html violates CSP self-only script rule")
	}
}

func TestWSSessionCommandRoutingAndErrorEnvelope(t *testing.T) {
	sess := &stubSessionCmd{setCrewErr: errors.New("unknown crew")}
	srv, err := New(Config{WSHz: 10}, Deps{
		Reader:  stubReader{},
		Session: sess,
	})
	if err != nil {
		t.Fatal(err)
	}
	hubCtx, hubCancel := context.WithCancel(context.Background())
	defer hubCancel()
	go srv.hub.run(hubCtx)

	ts := httptest.NewServer(srv.Handler())
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.CloseNow()

	for i := 0; i < 3; i++ {
		if _, _, err := conn.Read(ctx); err != nil {
			t.Fatal(err)
		}
	}

	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"SET_CREW","ts_us":1,"crew_id":null,"client_msg_id":"err-1","payload":{"crew_id":"bad"}}`)); err != nil {
		t.Fatal(err)
	}
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatal(err)
		}
		var env contracts.WSEnvelope
		if json.Unmarshal(data, &env) == nil && env.Type == contracts.WSMsgError {
			if env.ClientMsgID == nil || *env.ClientMsgID != "err-1" {
				t.Fatalf("expected client_msg_id=err-1, got %v", env.ClientMsgID)
			}
			break
		}
	}

	_ = conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"CHAT_MSG","ts_us":2,"crew_id":"crew_001","client_msg_id":"m2","payload":{"text":"hello"}}`))
	_ = conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"SELF_EXAM","ts_us":3,"crew_id":"crew_001","client_msg_id":"m3","payload":{"exam_type":"amsler","result":"normal"}}`))
	_ = conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"CALIBRATION_STEP","ts_us":4,"crew_id":"crew_001","client_msg_id":"m4","payload":{"step_id":"s1","action":"start"}}`))

	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		sess.mu.Lock()
		done := len(sess.chats) == 1 && len(sess.exams) == 1 && len(sess.calibs) == 1
		sess.mu.Unlock()
		if done {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	sess.mu.Lock()
	defer sess.mu.Unlock()
	t.Fatalf("expected all WS commands routed, got chats=%d exams=%d calibs=%d", len(sess.chats), len(sess.exams), len(sess.calibs))
}
