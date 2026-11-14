package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"

	"edgespace/central/internal/contracts"
	"edgespace/central/internal/httpws"
)

func startCentralE2E(t *testing.T, extraArgs ...string) (baseURL string, stop func()) {
	t.Helper()
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "e2e.db")
	migDir := filepath.Join(dir, "migrations")

	ctx, cancel := context.WithCancel(context.Background())
	var logBuf syncBuffer
	done := make(chan int, 1)

	args := append([]string{
		"--db", dbPath,
		"--migrations", migDir,
		"--http-addr", "127.0.0.1:0",
		"--ipc-addr", "127.0.0.1:0",
		"--ws-hz", "5",
		"--log-level", "info",
	}, extraArgs...)

	go func() {
		done <- run(ctx, args, &logBuf)
	}()

	var boundAddr string
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		for _, line := range strings.Split(logBuf.String(), "\n") {
			if !strings.Contains(line, `"msg":"httpws listening"`) {
				continue
			}
			var entry map[string]any
			if json.Unmarshal([]byte(line), &entry) == nil {
				if addr, ok := entry["addr"].(string); ok && addr != "" {
					boundAddr = addr
					break
				}
			}
		}
		if boundAddr != "" {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if boundAddr == "" {
		cancel()
		<-done
		t.Fatalf("timed out waiting for httpws listening; logs:\n%s", logBuf.String())
	}

	return "http://" + boundAddr, func() {
		shutStart := time.Now()
		cancel()
		code := <-done
		elapsed := time.Since(shutStart)
		if code != 0 {
			t.Fatalf("central exit code = %d, want 0; logs:\n%s", code, logBuf.String())
		}
		if elapsed >= 5*time.Second {
			t.Fatalf("shutdown took %v, expected < 5s", elapsed)
		}
	}
}

func dialWSAndReadUntil(
	t *testing.T,
	ctx context.Context,
	conn *websocket.Conn,
	timeout time.Duration,
	pred func(contracts.WSEnvelope) bool,
	desc string,
) contracts.WSEnvelope {
	t.Helper()
	rctx, rcancel := context.WithTimeout(ctx, timeout)
	defer rcancel()
	for {
		_, data, err := conn.Read(rctx)
		if err != nil {
			t.Fatalf("ws read waiting for %s: %v", desc, err)
		}
		var env contracts.WSEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			t.Fatalf("unmarshal ws env: %v", err)
		}
		if pred(env) {
			return env
		}
	}
}

func TestE2EMockHypercapniaChatAndCrewSwap(t *testing.T) {
	baseURL, stop := startCentralE2E(t,
		"--mock-cluster=inproc",
		"--mock-ai",
		"--scenario=hypercapnia",
		"--time-scale=10",
	)
	defer stop()

	wsURL := "ws" + strings.TrimPrefix(baseURL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("ws dial: %v", err)
	}
	defer conn.CloseNow()

	// 1. Confirm CREW_STATE, CLUSTER_STATUS (20 links), and TELEMETRY_FRAME.
	var saw20Links, sawTelemetry, sawCrew bool
	dialWSAndReadUntil(t, ctx, conn, 5*time.Second, func(env contracts.WSEnvelope) bool {
		switch env.Type {
		case contracts.WSMsgCrewState:
			sawCrew = true
		case contracts.WSMsgTelemetryFrame:
			sawTelemetry = true
		case contracts.WSMsgClusterStatus:
			var cs contracts.ClusterStatusPayload
			if json.Unmarshal(env.Payload, &cs) == nil && cs.ActiveLinks == 20 {
				saw20Links = true
			}
		}
		return sawCrew && sawTelemetry && saw20Links
	}, "initial CREW_STATE + TELEMETRY_FRAME + 20-link CLUSTER_STATUS")

	// 2. Swap to crew_002 (baseline_found=true -> calibration_required=false).
	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"SET_CREW","ts_us":1,"crew_id":null,"client_msg_id":"swap-2","payload":{"crew_id":"crew_002"}}`)); err != nil {
		t.Fatal(err)
	}
	dialWSAndReadUntil(t, ctx, conn, 4*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgCrewState {
			return false
		}
		var st contracts.CrewStatePayload
		return json.Unmarshal(env.Payload, &st) == nil && st.CrewID != nil && *st.CrewID == "crew_002" && st.AIReady && !st.CalibrationRequired
	}, "crew_002 CREW_STATE")

	// 3. Send CHAT_MSG ("dor de cabeca") -> receive CHAT_REPLY.
	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"CHAT_MSG","ts_us":2,"crew_id":"crew_002","client_msg_id":"chat-1","payload":{"text":"dor de cabeca"}}`)); err != nil {
		t.Fatal(err)
	}
	dialWSAndReadUntil(t, ctx, conn, 5*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgChatReply {
			return false
		}
		var rep contracts.ChatReplyPayload
		return json.Unmarshal(env.Payload, &rep) == nil && strings.Contains(strings.ToLower(rep.Text), "hipercapnia")
	}, "CHAT_REPLY")

	// 4. Swap to crew_003 -> calibration_required=true.
	if err := conn.Write(ctx, websocket.MessageText, []byte(`{"v":1,"type":"SET_CREW","ts_us":3,"crew_id":null,"client_msg_id":"swap-3","payload":{"crew_id":"crew_003"}}`)); err != nil {
		t.Fatal(err)
	}
	dialWSAndReadUntil(t, ctx, conn, 4*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgCrewState {
			return false
		}
		var st contracts.CrewStatePayload
		return json.Unmarshal(env.Payload, &st) == nil && st.CrewID != nil && *st.CrewID == "crew_003" && st.AIReady && st.CalibrationRequired
	}, "crew_003 CREW_STATE with calibration_required=true")

	// 5. Receive hypercapnia ALERT_EVENT.
	dialWSAndReadUntil(t, ctx, conn, 8*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgAlertEvent {
			return false
		}
		var al contracts.AlertEventPayload
		return json.Unmarshal(env.Payload, &al) == nil && al.Subsystem == contracts.SubsystemRespiratoryAtmosphere
	}, "hypercapnia ALERT_EVENT")

	// 6. Query REST /api/alerts and /api/crew/crew_002/timeseries.
	respAlerts, err := http.Get(baseURL + "/api/alerts")
	if err != nil {
		t.Fatal(err)
	}
	alertsRaw, _ := io.ReadAll(respAlerts.Body)
	respAlerts.Body.Close()
	if respAlerts.StatusCode != http.StatusOK || !strings.Contains(string(alertsRaw), "RESPIRATORY_ATMOSPHERE") {
		t.Fatalf("unexpected /api/alerts: status=%d body=%s", respAlerts.StatusCode, string(alertsRaw))
	}

	respTS, err := http.Get(baseURL + "/api/crew/crew_002/timeseries?bucket_sec=1")
	if err != nil {
		t.Fatal(err)
	}
	tsRaw, _ := io.ReadAll(respTS.Body)
	respTS.Body.Close()
	if respTS.StatusCode != http.StatusOK {
		t.Fatalf("/api/crew/crew_002/timeseries status=%d body=%s", respTS.StatusCode, string(tsRaw))
	}
}

func TestE2ENodeLossFailover(t *testing.T) {
	baseURL, stop := startCentralE2E(t,
		"--mock-cluster=inproc",
		"--mock-ai",
		"--scenario=node_loss",
		"--time-scale=10",
	)
	defer stop()

	wsURL := "ws" + strings.TrimPrefix(baseURL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("ws dial: %v", err)
	}
	defer conn.CloseNow()

	// 1. Wait for 20 active links initially.
	dialWSAndReadUntil(t, ctx, conn, 5*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgClusterStatus {
			return false
		}
		var cs contracts.ClusterStatusPayload
		return json.Unmarshal(env.Payload, &cs) == nil && cs.ActiveLinks == 20
	}, "20 active links")

	// 2. Wait for node_loss kill at t=1.5s -> drop to 12 links.
	dialWSAndReadUntil(t, ctx, conn, 6*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgClusterStatus {
			return false
		}
		var cs contracts.ClusterStatusPayload
		return json.Unmarshal(env.Payload, &cs) == nil && cs.ActiveLinks == 12
	}, "failover to 12 active links")

	// Check failover_last_ms <= 500 via /api/metrics.
	resp, err := http.Get(baseURL + "/api/metrics")
	if err != nil {
		t.Fatal(err)
	}
	var m httpws.MetricsSnapshot
	_ = json.NewDecoder(resp.Body).Decode(&m)
	resp.Body.Close()
	if m.FailoverLastMs <= 0 || m.FailoverLastMs > 500 {
		t.Fatalf("failover_last_ms = %d, want (0, 500]", m.FailoverLastMs)
	}

	// 3. Wait for node revive at t=4.5s -> recover back to 20 links.
	dialWSAndReadUntil(t, ctx, conn, 8*time.Second, func(env contracts.WSEnvelope) bool {
		if env.Type != contracts.WSMsgClusterStatus {
			return false
		}
		var cs contracts.ClusterStatusPayload
		return json.Unmarshal(env.Payload, &cs) == nil && cs.ActiveLinks == 20
	}, "recovery to 20 active links")
}
