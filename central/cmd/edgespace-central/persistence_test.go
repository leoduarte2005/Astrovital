package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"log/slog"
	"path/filepath"
	"testing"

	"edgespace/central/internal/contracts"
	"edgespace/central/internal/pipeline"
	"edgespace/central/internal/store"
)

func TestPipelineAdapterPreservesCSIPayloadAndActiveCrew(t *testing.T) {
	path := filepath.Join(t.TempDir(), "operational.db")
	st, err := store.New(store.Config{DBPath: path, MigrationsDir: filepath.Join("..", "..", "..", "database", "migrations"), RequireOperational: true}, store.Deps{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- st.Run(ctx) }()
	defer func() {
		cancel()
		if err := <-done; err != nil {
			t.Error(err)
		}
	}()
	adapter := pipelineStoreAdapter{st: st}
	crew := "crew_001"
	if !adapter.EmitCSIBlob(pipeline.StoreCSIBlobRecord{TsUs: 1, CrewID: &crew, Reason: "calibration", Window: &contracts.CSIWindowPayload{CycleSeqFirst: 7}, CalibrationStepID: "sitting"}) {
		t.Fatal("emit CSI")
	}
	if !adapter.EmitPeripherals1Hz(pipeline.StorePeripheralRecord{TsUs: 2, CrewID: &crew, Readings: []pipeline.PeripheralMeta{{NodeID: 1, Type: contracts.PeripheralSCD40, Value: 650, Unit: "ppm", TsUs: 2}}}) {
		t.Fatal("emit peripheral")
	}
	if err := st.Flush(ctx); err != nil {
		t.Fatal(err)
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var blob []byte
	if err := db.QueryRow("SELECT blob FROM csi_blobs").Scan(&blob); err != nil {
		t.Fatal(err)
	}
	var result struct {
		Window contracts.CSIWindowPayload `json:"window"`
		Step   string                     `json:"calibration_step_id"`
	}
	if err := json.Unmarshal(blob, &result); err != nil || result.Window.CycleSeqFirst != 7 || result.Step != "sitting" {
		t.Fatalf("CSI data discarded: %s %v", blob, err)
	}
	var actual string
	if err := db.QueryRow("SELECT crew_id FROM peripheral_readings").Scan(&actual); err != nil || actual != crew {
		t.Fatalf("active crew discarded: %s %v", actual, err)
	}
}
