package store

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

func waitFilesGone(dbPath string) {
	deadline := time.Now().Add(300 * time.Millisecond)
	for time.Now().Before(deadline) {
		_, wErr := os.Stat(dbPath + "-wal")
		_, sErr := os.Stat(dbPath + "-shm")
		if os.IsNotExist(wErr) && os.IsNotExist(sErr) {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func tempDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Cleanup(func() {
		// Retry briefly on Windows NTFS when AV/indexer transiently holds a closed SQLite file.
		for i := 0; i < 20; i++ {
			if err := os.RemoveAll(dir); err == nil {
				return
			}
			time.Sleep(15 * time.Millisecond)
		}
	})
	return dir
}

func TestStorePragmasAndMigrations(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "test.db")
	migDir := filepath.Join(dir, "migrations")
	if err := os.MkdirAll(migDir, 0o755); err != nil {
		t.Fatal(err)
	}

	var logBuf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&logBuf, &slog.HandlerOptions{Level: slog.LevelWarn}))

	s, err := New(Config{DBPath: dbPath, MigrationsDir: migDir}, Deps{Logger: logger})
	if err != nil {
		t.Fatalf("New store: %v", err)
	}
	defer func() {
		_ = s.shutdown()
		waitFilesGone(dbPath)
	}()

	if !strings.Contains(logBuf.String(), `"level":"WARN"`) {
		t.Fatalf("expected warning log for empty migrations dir, got %s", logBuf.String())
	}

	var journalMode string
	if err := s.writerDB.QueryRow("PRAGMA journal_mode;").Scan(&journalMode); err != nil {
		t.Fatal(err)
	}
	if journalMode != "wal" {
		t.Fatalf("journal_mode = %q, want wal", journalMode)
	}

	var syncMode, fk, busy, autoCkpt int
	if err := s.writerDB.QueryRow("PRAGMA synchronous;").Scan(&syncMode); err != nil {
		t.Fatal(err)
	}
	if syncMode != 1 { // NORMAL = 1
		t.Fatalf("synchronous = %d, want 1 (NORMAL)", syncMode)
	}
	if err := s.writerDB.QueryRow("PRAGMA foreign_keys;").Scan(&fk); err != nil {
		t.Fatal(err)
	}
	if fk != 1 {
		t.Fatalf("foreign_keys = %d, want 1", fk)
	}
	if err := s.writerDB.QueryRow("PRAGMA busy_timeout;").Scan(&busy); err != nil {
		t.Fatal(err)
	}
	if busy != 5000 {
		t.Fatalf("busy_timeout = %d, want 5000", busy)
	}
	if err := s.writerDB.QueryRow("PRAGMA wal_autocheckpoint;").Scan(&autoCkpt); err != nil {
		t.Fatal(err)
	}
	if autoCkpt != 1000 {
		t.Fatalf("wal_autocheckpoint = %d, want 1000", autoCkpt)
	}

	// Reader pool must reject writes.
	if _, err := s.readerDB.Exec(`INSERT INTO central_registry(key,value,updated_us) VALUES ('ro','fail',1)`); err == nil {
		t.Fatal("expected error when writing via read-only pool")
	}

	if err := s.Reader().Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}
	crew, err := s.Reader().ListCrew(context.Background())
	if err != nil {
		t.Fatalf("ListCrew without table: %v", err)
	}
	if len(crew) != 3 || crew[0].CrewID != "crew_001" || !crew[2].CalibrationRequired {
		t.Fatalf("expected 3 fallback crew summaries (crew_003 calibration_required), got %#v", crew)
	}

	// Missing migrations directory also warns without error and returns fallback crew.
	var missBuf bytes.Buffer
	missLog := slog.New(slog.NewJSONHandler(&missBuf, &slog.HandlerOptions{Level: slog.LevelWarn}))
	missDB := filepath.Join(dir, "missing.db")
	sMiss, err := New(Config{DBPath: missDB, MigrationsDir: filepath.Join(dir, "nope")}, Deps{Logger: missLog})
	if err != nil {
		t.Fatalf("New missing migrations dir: %v", err)
	}
	defer func() {
		_ = sMiss.shutdown()
		waitFilesGone(missDB)
	}()
	if !strings.Contains(missBuf.String(), `"level":"WARN"`) {
		t.Fatalf("expected warning log for missing migrations dir, got %s", missBuf.String())
	}
	crewMiss, err := sMiss.Reader().ListCrew(context.Background())
	if err != nil || len(crewMiss) != 3 {
		t.Fatalf("expected 3 fallback crew for missing migrations dir, got %#v, err=%v", crewMiss, err)
	}
}

func TestStoreBatchByTimeAndFlushAndShutdownCheckpoint(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "batch_time.db")

	s, err := New(Config{
		DBPath:        dbPath,
		MigrationsDir: filepath.Join(dir, "missing"),
		BatchSize:     512, // Default BatchInterval = 250ms (<= ~300ms)
	}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	go func() { errCh <- s.Run(ctx) }()

	// 1) Batch by time (~250ms <= ~300ms).
	start := time.Now()
	if err := s.Enqueue(RegistrySet{Key: "k1", Value: "v1"}); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}
	deadline := time.Now().Add(400 * time.Millisecond)
	for s.Stats().Commits == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	elapsed := time.Since(start)
	if s.Stats().Commits != 1 {
		t.Fatalf("expected 1 time-triggered commit, got %d (elapsed=%v)", s.Stats().Commits, elapsed)
	}
	if elapsed > 350*time.Millisecond {
		t.Fatalf("time batch took too long: %v (expected <= ~300ms)", elapsed)
	}

	// 2) Synchronous Flush returns only after commit is visible via reader.
	if err := s.Enqueue(RegistrySet{Key: "k2", Value: "v2"}); err != nil {
		t.Fatalf("Enqueue k2: %v", err)
	}
	fctx, fcancel := context.WithTimeout(context.Background(), time.Second)
	defer fcancel()
	if err := s.Flush(fctx); err != nil {
		t.Fatalf("Flush: %v", err)
	}
	var v2 string
	if err := s.readerDB.QueryRow(`SELECT value FROM central_registry WHERE key='k2'`).Scan(&v2); err != nil || v2 != "v2" {
		t.Fatalf("reader could not see k2 immediately after Flush: val=%q err=%v", v2, err)
	}
	if s.Stats().Commits != 2 {
		t.Fatalf("expected 2 commits after Flush, got %d", s.Stats().Commits)
	}

	// 3) Enqueue before shutdown -> drained + final flush + wal_checkpoint(TRUNCATE).
	if err := s.Enqueue(RegistrySet{Key: "k3", Value: "v3"}); err != nil {
		t.Fatalf("Enqueue k3: %v", err)
	}
	cancel()
	if err := <-errCh; err != nil {
		t.Fatalf("Run shutdown: %v", err)
	}

	// Verify WAL is truncated (0 bytes or removed cleanly on close) and k3 persisted.
	if st, err := os.Stat(dbPath + "-wal"); err == nil && st.Size() != 0 {
		t.Fatalf("expected truncated WAL, size=%d", st.Size())
	}

	s2, err := New(Config{DBPath: dbPath}, Deps{})
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer func() {
		_ = s2.shutdown()
		waitFilesGone(dbPath)
	}()
	var val string
	if err := s2.readerDB.QueryRow(`SELECT value FROM central_registry WHERE key='k3'`).Scan(&val); err != nil {
		t.Fatalf("read k3 after shutdown: %v", err)
	}
	if val != "v3" {
		t.Fatalf("k3 = %q, want v3", val)
	}
}

func TestStoreBatchBySize512(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "batch_size.db")

	s, err := New(Config{
		DBPath:        dbPath,
		BatchInterval: 10 * time.Second, // ensure size triggers, not timer
		BatchSize:     512,
	}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()

	for i := 0; i < 512; i++ {
		if err := s.Enqueue(RegistrySet{Key: "same_key", Value: "val"}); err != nil {
			t.Fatalf("Enqueue %d: %v", i, err)
		}
	}

	deadline := time.Now().Add(2 * time.Second)
	for s.Stats().Commits == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if s.Stats().Commits != 1 {
		t.Fatalf("expected 1 size-triggered commit for 512 cmds, got %d", s.Stats().Commits)
	}

	cancel()
	if err := <-done; err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	waitFilesGone(dbPath)
}

func TestStoreMigrationsOrderIdempotentAndInvalidRollback(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "mig.db")
	migDir := filepath.Join(dir, "migrations")
	if err := os.MkdirAll(migDir, 0o755); err != nil {
		t.Fatal(err)
	}

	// Write 0002 first to ensure ordering is lexicographic by filename.
	if err := os.WriteFile(filepath.Join(migDir, "0002_seed.sql"), []byte(`
		INSERT INTO crew_profiles(crew_id, name) VALUES ('c1', 'Alice'), ('c2', 'Bob');
	`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(migDir, "0001_crew.sql"), []byte(`
		CREATE TABLE crew_profiles (crew_id TEXT PRIMARY KEY, name TEXT NOT NULL);
	`), 0o644); err != nil {
		t.Fatal(err)
	}

	s, err := New(Config{DBPath: dbPath, MigrationsDir: migDir}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	crew, err := s.Reader().ListCrew(context.Background())
	if err != nil {
		t.Fatalf("ListCrew: %v", err)
	}
	if len(crew) != 2 || crew[0].CrewID != "c1" || crew[1].Name != "Bob" {
		t.Fatalf("unexpected crew: %+v", crew)
	}

	var applied0001, applied0002 int64
	if err := s.readerDB.QueryRow(`SELECT applied_at_us FROM schema_version WHERE filename='0001_crew.sql'`).Scan(&applied0001); err != nil {
		t.Fatal(err)
	}
	if err := s.readerDB.QueryRow(`SELECT applied_at_us FROM schema_version WHERE filename='0002_seed.sql'`).Scan(&applied0002); err != nil {
		t.Fatal(err)
	}
	if applied0001 > applied0002 {
		t.Fatalf("expected 0001 applied before 0002: %d > %d", applied0001, applied0002)
	}
	_ = s.shutdown()

	// Re-open -> idempotent (no re-apply).
	s2, err := New(Config{DBPath: dbPath, MigrationsDir: migDir}, Deps{})
	if err != nil {
		t.Fatalf("Reopen idempotent: %v", err)
	}
	var applied0002Again int64
	if err := s2.readerDB.QueryRow(`SELECT applied_at_us FROM schema_version WHERE filename='0002_seed.sql'`).Scan(&applied0002Again); err != nil {
		t.Fatal(err)
	}
	if applied0002Again != applied0002 {
		t.Fatalf("migration was re-applied: %d != %d", applied0002Again, applied0002)
	}
	_ = s2.shutdown()
	waitFilesGone(dbPath)

	// Invalid SQL migration -> New returns error and rolls back partial DDL + schema_version.
	badDir := tempDir(t)
	badDB := filepath.Join(badDir, "bad.db")
	badMigDir := filepath.Join(badDir, "migrations")
	if err := os.MkdirAll(badMigDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(badMigDir, "0001_bad.sql"), []byte(`
		CREATE TABLE should_not_exist (id INTEGER PRIMARY KEY);
		THIS IS NOT VALID SQL;
	`), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := New(Config{DBPath: badDB, MigrationsDir: badMigDir}, Deps{}); err == nil {
		t.Fatal("expected error for invalid SQL migration")
	}

	s3, err := New(Config{DBPath: badDB}, Deps{})
	if err != nil {
		t.Fatalf("Reopen after bad migration: %v", err)
	}
	defer func() {
		_ = s3.shutdown()
		waitFilesGone(badDB)
	}()

	var cnt int
	if err := s3.readerDB.QueryRow(`SELECT COUNT(1) FROM schema_version WHERE filename='0001_bad.sql'`).Scan(&cnt); err != nil {
		t.Fatal(err)
	}
	if cnt != 0 {
		t.Fatalf("expected 0001_bad.sql not recorded, got count=%d", cnt)
	}
	var tblCnt int
	if err := s3.readerDB.QueryRow(`SELECT COUNT(1) FROM sqlite_master WHERE type='table' AND name='should_not_exist'`).Scan(&tblCnt); err != nil {
		t.Fatal(err)
	}
	if tblCnt != 0 {
		t.Fatal("expected partial DDL rolled back, found should_not_exist")
	}
}

func TestStoreConcurrency10kCmdsAndParallelReads(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "conc.db")
	migDir := filepath.Join(dir, "migrations")
	if err := os.MkdirAll(migDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(migDir, "0001_crew.sql"), []byte(`
		CREATE TABLE crew_profiles (crew_id TEXT PRIMARY KEY, name TEXT NOT NULL);
		INSERT INTO crew_profiles(crew_id, name) VALUES ('c1', 'Alice');
	`), 0o644); err != nil {
		t.Fatal(err)
	}

	s, err := New(Config{
		DBPath:        dbPath,
		MigrationsDir: migDir,
		BatchInterval: 20 * time.Millisecond,
		BatchSize:     512,
		CmdBuffer:     16384,
	}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()

	const writers = 8
	const perWriter = 1250 // 8 * 1250 = 10,000 cmds

	var wg sync.WaitGroup
	errCh := make(chan error, 64)

	for w := 0; w < writers; w++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for i := 0; i < perWriter; i++ {
				if err := s.Enqueue(RegistrySet{
					Key:   fmt.Sprintf("k_%d_%d", id, i%50),
					Value: fmt.Sprintf("v_%d", i),
				}); err != nil {
					errCh <- err
					return
				}
			}
		}(w)
	}

	stopReaders := make(chan struct{})
	var rwg sync.WaitGroup
	for r := 0; r < 4; r++ {
		rwg.Add(1)
		go func() {
			defer rwg.Done()
			for {
				select {
				case <-stopReaders:
					return
				default:
					if err := s.Reader().Health(context.Background()); err != nil {
						errCh <- err
						return
					}
					if _, err := s.Reader().ListCrew(context.Background()); err != nil {
						errCh <- err
						return
					}
				}
			}
		}()
	}

	wg.Wait()
	fctx, fcancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer fcancel()
	if err := s.Flush(fctx); err != nil {
		t.Fatalf("Flush after 10k cmds: %v", err)
	}
	close(stopReaders)
	rwg.Wait()

	close(errCh)
	for e := range errCh {
		t.Fatalf("concurrent error: %v", e)
	}

	stats := s.Stats()
	if stats.Failed != 0 || stats.Dropped != 0 {
		t.Fatalf("unexpected failed/dropped stats: %+v", stats)
	}

	var rows int
	if err := s.readerDB.QueryRow(`SELECT COUNT(1) FROM central_registry`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != writers*50 {
		t.Fatalf("expected %d registry keys, got %d", writers*50, rows)
	}

	cancel()
	if err := <-done; err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	waitFilesGone(dbPath)
}

func TestStoreFallbackModeAndRegistry(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "fallback.db")
	s, err := New(Config{DBPath: dbPath, MigrationsDir: filepath.Join(dir, "absent"), BatchInterval: 20 * time.Millisecond}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()
	defer func() {
		cancel()
		<-done
		waitFilesGone(dbPath)
	}()

	// RegistryStore persistence in central_registry when cluster_nodes is absent.
	if err := s.SaveNodeID(ctx, "02:ED:6E:00:00:00", 0); err != nil {
		t.Fatalf("SaveNodeID: %v", err)
	}
	if err := s.SaveNodeID(ctx, "02:ED:6E:00:00:01", 1); err != nil {
		t.Fatalf("SaveNodeID: %v", err)
	}
	nodes, err := s.LoadNodeIDs(ctx)
	if err != nil || nodes["02:ED:6E:00:00:00"] != 0 || nodes["02:ED:6E:00:00:01"] != 1 {
		t.Fatalf("LoadNodeIDs mismatch: %#v err=%v", nodes, err)
	}

	// Crew profiles fallback (crew_001, crew_002, crew_003).
	p1, err := s.GetCrewProfile(ctx, "crew_001")
	if err != nil || p1.Profile.Name != "Cmdr. Silva" || p1.BaselinePath == "" {
		t.Fatalf("crew_001 mismatch: %+v err=%v", p1, err)
	}
	p3, err := s.GetCrewProfile(ctx, "crew_003")
	if err != nil || p3.Profile.Name != "Eng. Sato" || p3.BaselinePath != "" {
		t.Fatalf("crew_003 mismatch: %+v err=%v", p3, err)
	}
	if _, err := s.GetCrewProfile(ctx, "unknown"); err == nil {
		t.Fatal("expected ErrNotFound for unknown crew")
	}

	// Telemetry + peripheral + timeseries decimation in memory.
	cid := "crew_001"
	now := time.Now().UnixMicro()
	_ = s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{
		TsUs:        now - 10_000_000,
		CrewID:      &cid,
		MissionMode: contracts.ModeCabinTomography,
		Vitals:      contracts.VitalsData{HeartRateBpm: 70, SpO2Pct: 98},
		Environment: contracts.EnvironmentData{CO2Ppm: 800},
	})
	_ = s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{
		TsUs:        now - 9_500_000,
		CrewID:      &cid,
		MissionMode: contracts.ModeCabinTomography,
		Vitals:      contracts.VitalsData{HeartRateBpm: 80, SpO2Pct: 96},
		Environment: contracts.EnvironmentData{CO2Ppm: 1200},
	})
	_ = s.SavePeripheral1Hz(ctx, now, []PeripheralReadingRecord{{NodeID: 0, Type: contracts.PeripheralSCD40, Value: 1200, Unit: "ppm", TsUs: now}})

	tsResp, err := s.QueryTimeseries(ctx, "crew_001", "", now-20_000_000, now, 5)
	if err != nil || len(tsResp.Buckets) != 1 {
		t.Fatalf("QueryTimeseries fallback got %+v err=%v", tsResp, err)
	}
	if tsResp.Buckets[0].Vitals.HeartRateBpm != 75 || tsResp.Buckets[0].Environment.CO2Ppm != 1000 {
		t.Fatalf("unexpected averaged bucket: %+v", tsResp.Buckets[0])
	}

	// Alert + RED outbox + SelfExam + Chat + Summary24h + Protocols.
	_ = s.SaveAlertAndOutbox(ctx, AlertWriteRecord{
		TsUs:   now,
		CrewID: &cid,
		Alert: contracts.AlertEventPayload{
			Subsystem:      contracts.SubsystemRespiratoryAtmosphere,
			Severity:       contracts.SeverityRed,
			Message:        "CO2 > 3500 ppm",
			Countermeasure: "Ventilate",
			Escalation:     contracts.EscalationStoreAndForward,
			SourceID:       "NASA-STD-3001",
		},
		WriteOutbox: true,
	})
	alerts, err := s.ListAlerts(ctx, 10)
	if err != nil || len(alerts) != 1 || alerts[0].Severity != contracts.SeverityRed {
		t.Fatalf("ListAlerts fallback: %+v err=%v", alerts, err)
	}
	outbox, err := s.ListOutbox(ctx)
	if err != nil || len(outbox) != 1 {
		t.Fatalf("ListOutbox fallback: %+v err=%v", outbox, err)
	}

	_ = s.SaveSelfExam(ctx, "crew_001", contracts.SelfExamPayload{ExamType: "amsler", Result: "altered"}, now)
	_ = s.SaveChatExchange(ctx, "crew_001", contracts.ChatMsgPayload{Text: "headache"}, contracts.ChatCorrelateRespPayload{Text: "check CO2"}, now)
	hist, err := s.RecentChat(ctx, "crew_001", 10)
	if err != nil || len(hist) != 2 || hist[0].Role != "user" || hist[1].Role != "assistant" {
		t.Fatalf("RecentChat fallback: %+v err=%v", hist, err)
	}
	sum, err := s.Summary24h(ctx, "crew_001")
	if err != nil || !strings.Contains(sum, "samples=2") {
		t.Fatalf("Summary24h fallback: %q err=%v", sum, err)
	}

	for _, pid := range []string{"amsler_grid", "capillary_blood", "ultrasound_onsd", "blood_pressure", "temperature"} {
		proto, err := s.GetProtocol(ctx, pid)
		if err != nil || proto.ProtocolID != pid || len(proto.Steps) == 0 {
			t.Fatalf("GetProtocol(%s) failed: %+v err=%v", pid, proto, err)
		}
	}
}

func TestStoreWithTempM1Schema(t *testing.T) {
	dir := tempDir(t)
	dbPath := filepath.Join(dir, "m1.db")
	migDir := filepath.Join(dir, "migrations")
	if err := os.MkdirAll(migDir, 0o755); err != nil {
		t.Fatal(err)
	}
	schema := `
CREATE TABLE cluster_nodes (mac TEXT PRIMARY KEY, node_id INTEGER NOT NULL);
CREATE TABLE crew_profiles (crew_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, mission_day INTEGER, age INTEGER, baseline_path TEXT, thresholds_json TEXT);
INSERT INTO crew_profiles(crew_id, name, role, mission_day, age, baseline_path, thresholds_json)
VALUES ('crew_sql', 'Dr. Vega', 'Science', 10, 34, 'baselines/vega.onnx', '{"co2_ppm":{"metric_name":"co2_ppm","yellow_high":800,"red_high":2500}}');
CREATE TABLE telemetry_timeseries (ts_us INTEGER NOT NULL, crew_id TEXT, mission_mode TEXT, heart_rate_bpm REAL, hrv_ms REAL, resp_rate_bpm REAL, spo2_pct REAL, posture TEXT, confidence REAL, co2_ppm REAL, temp_c REAL, humidity_pct REAL, pressure_hpa REAL);
CREATE TABLE peripheral_readings (ts_us INTEGER NOT NULL, node_id INTEGER, sensor_type TEXT, value REAL, unit TEXT);
CREATE TABLE alerts_audit (alert_id TEXT PRIMARY KEY, ts_us INTEGER NOT NULL, crew_id TEXT, subsystem TEXT, severity TEXT, message TEXT, countermeasure TEXT, escalation TEXT, handled INTEGER);
CREATE TABLE store_and_forward_outbox (outbox_id TEXT PRIMARY KEY, ts_us INTEGER NOT NULL, subsystem TEXT, severity TEXT, message TEXT, destination TEXT, sent INTEGER);
CREATE TABLE self_exams (ts_us INTEGER NOT NULL, crew_id TEXT, exam_type TEXT, result TEXT, observations TEXT);
CREATE TABLE chat_messages (ts_us INTEGER NOT NULL, crew_id TEXT, role TEXT, content TEXT);
CREATE TABLE protocols (protocol_id TEXT PRIMARY KEY, name TEXT NOT NULL, subsystems_json TEXT, description TEXT, steps_json TEXT);
INSERT INTO protocols(protocol_id, name, subsystems_json, description, steps_json)
VALUES ('amsler_grid', 'Amsler SQL', '["NEURO_OCULAR_SANS"]', 'SQL desc', '["Step 1"]');
`
	if err := os.WriteFile(filepath.Join(migDir, "0001_m1.sql"), []byte(schema), 0o644); err != nil {
		t.Fatal(err)
	}

	s, err := New(Config{DBPath: dbPath, MigrationsDir: migDir, BatchInterval: 20 * time.Millisecond}, Deps{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()
	defer func() {
		cancel()
		<-done
		waitFilesGone(dbPath)
	}()

	if err := s.SaveNodeID(ctx, "AA:BB:CC:DD:EE:01", 2); err != nil {
		t.Fatalf("SaveNodeID M1: %v", err)
	}
	nodes, err := s.LoadNodeIDs(ctx)
	if err != nil || nodes["AA:BB:CC:DD:EE:01"] != 2 {
		t.Fatalf("LoadNodeIDs M1: %#v err=%v", nodes, err)
	}

	prof, err := s.GetCrewProfile(ctx, "crew_sql")
	if err != nil || prof.Profile.Name != "Dr. Vega" || prof.Thresholds["co2_ppm"].YellowHigh != 800 {
		t.Fatalf("GetCrewProfile M1: %+v err=%v", prof, err)
	}

	cid := "crew_sql"
	now := time.Now().UnixMicro()
	_ = s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{
		TsUs: now - 2_000_000, CrewID: &cid, MissionMode: contracts.ModeCabinTomography,
		Vitals: contracts.VitalsData{HeartRateBpm: 60, SpO2Pct: 99}, Environment: contracts.EnvironmentData{CO2Ppm: 500},
	})
	_ = s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{
		TsUs: now - 1_500_000, CrewID: &cid, MissionMode: contracts.ModeCabinTomography,
		Vitals: contracts.VitalsData{HeartRateBpm: 70, SpO2Pct: 97}, Environment: contracts.EnvironmentData{CO2Ppm: 700},
	})
	_ = s.SaveAlertAndOutbox(ctx, AlertWriteRecord{
		TsUs: now, CrewID: &cid, WriteOutbox: true,
		Alert: contracts.AlertEventPayload{Subsystem: contracts.SubsystemRespiratoryAtmosphere, Severity: contracts.SeverityRed, Message: "SQL alert", Escalation: contracts.EscalationStoreAndForward},
	})
	_ = s.SaveChatExchange(ctx, cid, contracts.ChatMsgPayload{Text: "hi"}, contracts.ChatCorrelateRespPayload{Text: "hello"}, now)
	_ = s.SaveSelfExam(ctx, cid, contracts.SelfExamPayload{ExamType: "amsler", Result: "ok"}, now)

	if err := s.Flush(ctx); err != nil {
		t.Fatalf("Flush M1: %v", err)
	}

	tsResp, err := s.QueryTimeseries(ctx, cid, "", now-10_000_000, now, 10)
	if err != nil || len(tsResp.Buckets) != 1 || tsResp.Buckets[0].Vitals.HeartRateBpm != 65 {
		t.Fatalf("QueryTimeseries M1: %+v err=%v", tsResp, err)
	}
	alerts, err := s.ListAlerts(ctx, 10)
	if err != nil || len(alerts) != 1 || alerts[0].Message != "SQL alert" {
		t.Fatalf("ListAlerts M1: %+v err=%v", alerts, err)
	}
	outbox, err := s.ListOutbox(ctx)
	if err != nil || len(outbox) != 1 {
		t.Fatalf("ListOutbox M1: %+v err=%v", outbox, err)
	}
	hist, err := s.RecentChat(ctx, cid, 10)
	if err != nil || len(hist) != 2 {
		t.Fatalf("RecentChat M1: %+v err=%v", hist, err)
	}
	proto, err := s.GetProtocol(ctx, "amsler_grid")
	if err != nil || proto.Name != "Amsler SQL" {
		t.Fatalf("GetProtocol M1: %+v err=%v", proto, err)
	}
}
