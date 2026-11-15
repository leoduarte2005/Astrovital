package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.String()
}

// tempDir retries cleanup briefly: on Windows NTFS a just-closed SQLite file can
// stay locked for a few ms (same approach as store tests).
func tempDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "central-main-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		for i := 0; i < 40; i++ {
			if err := os.RemoveAll(dir); err == nil {
				return
			}
			time.Sleep(25 * time.Millisecond)
		}
	})
	return dir
}

func TestParseFlagsDefaultsAndValidation(t *testing.T) {
	cfg, err := parseFlags(nil, io.Discard)
	if err != nil {
		t.Fatalf("parseFlags defaults: %v", err)
	}
	if cfg.db != "./var/edgespace.db" ||
		cfg.migrations != "../database/migrations" ||
		cfg.udpAddr != ":5005" ||
		cfg.broadcastAddr != "10.42.0.255:5005" ||
		cfg.ipcAddr != "127.0.0.1:5006" ||
		cfg.httpAddr != ":8000" ||
		cfg.wsHz != 2 ||
		cfg.mockCluster != "false" ||
		cfg.mockAI != false ||
		cfg.scenario != "" ||
		cfg.seed != 1 ||
		cfg.timeScale != 1 ||
		cfg.logLevel != "info" {
		t.Fatalf("defaults mismatch §7: %+v", cfg)
	}

	// --mock-cluster alone = inproc
	cfgMock, err := parseFlags([]string{"--mock-cluster"}, io.Discard)
	if err != nil {
		t.Fatalf("--mock-cluster alone: %v", err)
	}
	if cfgMock.mockCluster != "inproc" {
		t.Fatalf("--mock-cluster = %q, want inproc", cfgMock.mockCluster)
	}

	// --mock-cluster=udp valid
	cfgUDP, err := parseFlags([]string{"--mock-cluster=udp"}, io.Discard)
	if err != nil {
		t.Fatalf("--mock-cluster=udp: %v", err)
	}
	if cfgUDP.mockCluster != "udp" {
		t.Fatalf("--mock-cluster=udp = %q, want udp", cfgUDP.mockCluster)
	}

	// --mock-cluster inproc (space-separated) must not break --mock-ai or --scenario.
	cfgSpace, err := parseFlags([]string{
		"--mock-cluster", "inproc",
		"--mock-ai",
		"--scenario", "hypercapnia",
		"--sim-loss", "0.05",
		"--sim-jitter-ms", "5",
		"--mock-ai-latency-ms", "10",
		"--mock-ai-drop-ack",
		"--mock-ai-crash-after", "2s",
	}, io.Discard)
	if err != nil {
		t.Fatalf("--mock-cluster inproc + chaos flags: %v", err)
	}
	if cfgSpace.mockCluster != "inproc" || !cfgSpace.mockAI || cfgSpace.scenario != "hypercapnia" ||
		cfgSpace.simLoss != 0.05 || cfgSpace.simJitterMs != 5 || cfgSpace.mockAILatencyMs != 10 ||
		!cfgSpace.mockAIDropAck || cfgSpace.mockAICrashAfter != 2*time.Second {
		t.Fatalf("parsed flags mismatch: %+v", cfgSpace)
	}

	// Invalid cases
	invalidCases := []struct {
		name string
		args []string
	}{
		{"ws-hz 11", []string{"--ws-hz", "11"}},
		{"ws-hz 1", []string{"--ws-hz", "1"}},
		{"mock-cluster foo", []string{"--mock-cluster=foo"}},
		{"mock-cluster space foo", []string{"--mock-cluster", "foo"}},
		{"positional extra", []string{"--mock-cluster", "inproc", "stray-arg"}},
		{"sim-loss out of range", []string{"--sim-loss", "1.5"}},
		{"scenario invalid", []string{"--scenario", "unknown_scen"}},
		{"log-level invalid", []string{"--log-level=trace"}},
	}
	for _, tc := range invalidCases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := parseFlags(tc.args, io.Discard); err == nil {
				t.Fatalf("expected error for %v", tc.args)
			}
			if code := run(context.Background(), tc.args, &bytes.Buffer{}); code != 2 {
				t.Fatalf("run(%v) exit code = %d, want 2", tc.args, code)
			}
		})
	}
}

func TestRunGracefulShutdownOrder(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "central.db")
	migDir := filepath.Join(dir, "migrations")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var logBuf syncBuffer
	done := make(chan int, 1)
	args := []string{
		"--db", dbPath,
		"--migrations", migDir,
		"--http-addr", "127.0.0.1:0",
		"--ipc-addr", "127.0.0.1:0",
		"--ws-hz", "2",
		"--mock-cluster", "inproc",
		"--mock-ai",
		"--log-level", "info",
	}

	go func() {
		done <- run(ctx, args, &logBuf)
	}()

	// Wait until httpws is listening before cancelling ctx.
	deadline := time.Now().Add(4 * time.Second)
	for !strings.Contains(logBuf.String(), `"msg":"httpws listening"`) {
		if time.Now().After(deadline) {
			cancel()
			t.Fatalf("timed out waiting for httpws listening; logs:\n%s", logBuf.String())
		}
		time.Sleep(10 * time.Millisecond)
	}

	shutStart := time.Now()
	cancel()

	code := <-done
	shutElapsed := time.Since(shutStart)
	if code != 0 {
		t.Fatalf("run exit code = %d, want 0; logs:\n%s", code, logBuf.String())
	}
	if shutElapsed >= 5*time.Second {
		t.Fatalf("shutdown took %v, expected < 5s", shutElapsed)
	}

	logs := logBuf.String()
	lines := strings.Split(strings.TrimSpace(logs), "\n")
	httpIdx, storeIdx := -1, -1
	for i, line := range lines {
		var entry map[string]any
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("invalid JSON log line %d (%q): %v", i, line, err)
		}
		switch entry["msg"] {
		case "httpws stopped":
			httpIdx = i
		case "store stopped":
			storeIdx = i
		}
	}
	if httpIdx == -1 || storeIdx == -1 || httpIdx >= storeIdx {
		t.Fatalf("expected httpws stopped (%d) before store stopped (%d); logs:\n%s", httpIdx, storeIdx, logs)
	}
}

func TestChatPeripheralsFromSnapshotAndDataClass(t *testing.T) {
	if got := dataClassFor(config{mockCluster: "inproc"}); got != "SYNTHETIC" {
		t.Fatalf("dataClassFor(inproc)=%q want SYNTHETIC", got)
	}
	if got := dataClassFor(config{mockCluster: "false"}); got != "REAL" {
		t.Fatalf("dataClassFor(false)=%q want REAL", got)
	}
	snap := &contracts.TelemetrySnapshot{
		TsUs: 1234,
		Vitals: contracts.VitalsData{
			HeartRateBpm: 72,
			SpO2Pct:      98,
		},
		Environment: contracts.EnvironmentData{
			CO2Ppm:      900,
			TempC:       22.5,
			HumidityPct: 45,
			PressureHpa: 1013,
		},
	}
	got := chatPeripheralsFromSnapshot(snap)
	if len(got) != 6 {
		t.Fatalf("chatPeripheralsFromSnapshot len=%d want 6: %+v", len(got), got)
	}
	units := map[string]float64{}
	for _, r := range got {
		units[string(r.Type)+":"+r.Unit] = r.Value
	}
	for _, k := range []string{"SCD40:ppm", "BME280:C", "BME280:%RH", "BME280:hPa", "MAX30102:bpm", "MAX30102:%"} {
		if _, ok := units[k]; !ok {
			t.Fatalf("missing %s in chatPeripheralsFromSnapshot: %+v", k, got)
		}
	}
}
