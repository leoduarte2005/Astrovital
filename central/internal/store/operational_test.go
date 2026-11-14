package store

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"path/filepath"
	"testing"

	"edgespace/central/internal/contracts"
)

func operationalStore(t *testing.T, dbPath string) *Store {
	t.Helper()
	s, err := New(Config{DBPath: dbPath, MigrationsDir: filepath.Join("..", "..", "..", "database", "migrations"), RequireOperational: true}, Deps{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err != nil {
		t.Fatal(err)
	}
	if !s.operational || s.fallback != nil {
		t.Fatal("operational store must not allocate fallback data")
	}
	return s
}

func TestOperationalMigrationsPersistClinicalDataAcrossRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "operational.db")
	s := operationalStore(t, path)
	defer func() { _ = s.shutdown() }()
	ctx := context.Background()
	crew := "crew_001"
	if err := s.SaveAudit(ctx, &crew, "CREW_CHANGED", `{"source":"test"}`, 100); err != nil {
		t.Fatal(err)
	}
	blob := []byte{1, 2, 3, 4}
	if err := s.SaveCSIBlob(ctx, CSIBlobWriteRecord{TsUs: 101, CrewID: &crew, Reason: "calibration", Blob: blob}); err != nil {
		t.Fatal(err)
	}
	if err := s.SavePeripheral1Hz(ctx, 102, []PeripheralReadingRecord{{CrewID: &crew, NodeID: 1, Type: contracts.PeripheralMAX30102, Value: 98, Unit: "%", TsUs: 102}}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveSelfExam(ctx, crew, contracts.SelfExamPayload{ExamType: "amsler_grid", Result: `{"abnormal_flag":true}`}, 103); err != nil {
		t.Fatal(err)
	}
	response := contracts.ChatCorrelateRespPayload{Text: "Review context", Differentials: []string{"SANS"}, Evidence: []string{"Amsler"}, DisambiguationQuestion: "New visual change?", Escalation: contracts.EscalationCrew}
	if err := s.SaveChatExchange(ctx, crew, contracts.ChatMsgPayload{Text: "vision"}, response, 104); err != nil {
		t.Fatal(err)
	}
	protocol, err := s.GetProtocol(ctx, "amsler_grid")
	if err != nil || len(protocol.RichSteps) == 0 || len(protocol.Materials) == 0 || protocol.DurationS == nil {
		t.Fatalf("rich protocol: %+v, %v", protocol, err)
	}
	if err := s.shutdown(); err != nil {
		t.Fatal(err)
	}
	s = operationalStore(t, path)
	for table, want := range map[string]int{"audit_log": 1, "csi_blobs": 1, "peripheral_readings": 1, "self_exams": 1, "chat_messages": 2, "schema_version": 4, "causal_conditions": 22} {
		var count int
		if err := s.readerDB.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&count); err != nil || count != want {
			t.Fatalf("%s count=%d want=%d err=%v", table, count, want, err)
		}
	}
	var stored []byte
	var size int
	if err := s.readerDB.QueryRow("SELECT byte_len,blob FROM csi_blobs").Scan(&size, &stored); err != nil || size != len(blob) || string(stored) != string(blob) {
		t.Fatalf("CSI payload was not preserved: %v", err)
	}
	var linked string
	if err := s.readerDB.QueryRow("SELECT crew_id FROM peripheral_readings").Scan(&linked); err != nil || linked != crew {
		t.Fatalf("crew association: %q %v", linked, err)
	}
	var protocolID, payload string
	var abnormal int
	if err := s.readerDB.QueryRow("SELECT protocol_id,payload_json,abnormal_flag FROM self_exams").Scan(&protocolID, &payload, &abnormal); err != nil || protocolID != "amsler_grid" || abnormal != 1 || !json.Valid([]byte(payload)) {
		t.Fatalf("self exam metadata: %s %d %s %v", protocolID, abnormal, payload, err)
	}
	var metadata string
	if err := s.readerDB.QueryRow("SELECT metadata_json FROM chat_messages WHERE role='assistant'").Scan(&metadata); err != nil {
		t.Fatal(err)
	}
	var decoded contracts.ChatCorrelateRespPayload
	if err := json.Unmarshal([]byte(metadata), &decoded); err != nil || len(decoded.Differentials) != 1 || decoded.DisambiguationQuestion != response.DisambiguationQuestion {
		t.Fatalf("AI metadata lost: %s %v", metadata, err)
	}
}

func TestOperationalSchemaFailureNeverFallsBackToRAM(t *testing.T) {
	s := operationalStore(t, filepath.Join(t.TempDir(), "operational.db"))
	defer s.shutdown()
	if _, err := s.writerDB.Exec("ALTER TABLE telemetry_timeseries RENAME COLUMN heart_rate_bpm TO removed_hr"); err != nil {
		t.Fatal(err)
	}
	err := s.SaveTelemetry1Hz(context.Background(), Telemetry1HzRecord{TsUs: 1, MissionMode: contracts.ModeRestVitals})
	if err == nil {
		t.Fatal("missing operational columns must be reported")
	}
	if _, err := s.writerDB.Exec("DROP TABLE audit_log"); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveAudit(context.Background(), nil, "event", "details", 1); err == nil {
		t.Fatal("missing audit table must be reported")
	}
}

func TestProductionRequiresOperationalMigrations(t *testing.T) {
	s, err := New(Config{DBPath: filepath.Join(t.TempDir(), "empty.db"), RequireOperational: true}, Deps{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err == nil {
		s.shutdown()
		t.Fatal("production cannot use schema-less fallback mode")
	}
}
