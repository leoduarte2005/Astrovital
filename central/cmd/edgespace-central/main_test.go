package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
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

	// Invalid cases
	invalidCases := []struct {
		name string
		args []string
	}{
		{"ws-hz 11", []string{"--ws-hz", "11"}},
		{"ws-hz 1", []string{"--ws-hz", "1"}},
		{"mock-cluster foo", []string{"--mock-cluster=foo"}},
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

func TestRunGracefulShutdownOrderAndLeva2Warn(t *testing.T) {
	dir := t.TempDir()
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
		"--ws-hz", "2",
		"--mock-cluster",
		"--log-level", "info",
	}

	go func() {
		done <- run(ctx, args, &logBuf)
	}()

	// Wait until httpws is listening before cancelling ctx.
	deadline := time.Now().Add(3 * time.Second)
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
	if !strings.Contains(logs, `"msg":"not implemented in Leva 1"`) {
		t.Fatalf("expected Leva 2 warn log, got:\n%s", logs)
	}

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
