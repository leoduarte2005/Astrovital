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
	if crew == nil || len(crew) != 0 {
		t.Fatalf("expected non-nil empty crew slice, got %#v", crew)
	}

	// Missing migrations directory also warns without error and ListCrew -> [].
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
	if err != nil || crewMiss == nil || len(crewMiss) != 0 {
		t.Fatalf("expected [] for missing migrations dir, got %#v, err=%v", crewMiss, err)
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
