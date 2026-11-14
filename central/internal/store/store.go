// Package store is the single-writer SQLite (WAL) persistence layer plus a
// separate read-only pool for REST queries. No other package opens the DB file.
package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	_ "modernc.org/sqlite" // pure-Go driver (CGO_ENABLED=0)
)

const (
	DefaultBatchInterval = 250 * time.Millisecond
	DefaultBatchSize     = 512
	DefaultCmdBuffer     = 4096
	readerConns          = 4
)

var (
	// ErrBacklogFull is returned by Enqueue when the command channel is full.
	ErrBacklogFull = errors.New("store: command channel full")
	// ErrClosed is returned after shutdown started.
	ErrClosed = errors.New("store: closed")
)

// Config configures Store.
type Config struct {
	DBPath        string
	MigrationsDir string
	BatchInterval time.Duration // default 250ms
	BatchSize     int           // default 512
	CmdBuffer     int           // default 4096
}

// Deps are Store dependencies.
type Deps struct {
	Logger *slog.Logger
}

// Cmd is a write command executed by writerLoop inside a batched transaction.
type Cmd interface{ isCmd() }

// Exec runs a parameterized statement in the batch transaction.
type Exec struct {
	Query string
	Args  []any
}

func (Exec) isCmd() {}

// RegistrySet upserts a key in the internal central_registry table.
type RegistrySet struct {
	Key   string
	Value string
}

func (RegistrySet) isCmd() {}

// Flush forces an immediate commit of pending commands; result sent on Done.
type Flush struct {
	Done chan<- error
}

func (Flush) isCmd() {}

// Stats are point-in-time counters.
type Stats struct {
	Commits int64
	Backlog int64 // commands queued (channel length)
	Dropped int64 // commands rejected because channel was full
	Failed  int64 // commands lost in failed transactions
}

// Store owns the writer connection, the read-only pool and the writer goroutine.
type Store struct {
	cfg      Config
	log      *slog.Logger
	writerDB *sql.DB
	readerDB *sql.DB
	cmdCh    chan Cmd

	closing atomic.Bool
	commits atomic.Int64
	dropped atomic.Int64
	failed  atomic.Int64
}

// New opens the DB (WAL + PRAGMAs), creates internal tables and applies migrations.
func New(cfg Config, deps Deps) (*Store, error) {
	if cfg.DBPath == "" {
		return nil, errors.New("store: DBPath required")
	}
	if cfg.BatchInterval <= 0 {
		cfg.BatchInterval = DefaultBatchInterval
	}
	if cfg.BatchSize <= 0 {
		cfg.BatchSize = DefaultBatchSize
	}
	if cfg.CmdBuffer <= 0 {
		cfg.CmdBuffer = DefaultCmdBuffer
	}
	log := deps.Logger
	if log == nil {
		log = slog.Default()
	}
	if err := os.MkdirAll(filepath.Dir(cfg.DBPath), 0o755); err != nil {
		return nil, fmt.Errorf("store: mkdir: %w", err)
	}

	w, err := openWriter(cfg.DBPath)
	if err != nil {
		return nil, fmt.Errorf("store: open writer: %w", err)
	}
	if err := ensureInternalSchema(w); err != nil {
		w.Close()
		return nil, fmt.Errorf("store: internal schema: %w", err)
	}
	if err := applyMigrations(w, cfg.MigrationsDir, log); err != nil {
		w.Close()
		return nil, fmt.Errorf("store: migrations: %w", err)
	}
	r, err := openReader(cfg.DBPath)
	if err != nil {
		w.Close()
		return nil, fmt.Errorf("store: open reader: %w", err)
	}
	return &Store{cfg: cfg, log: log, writerDB: w, readerDB: r, cmdCh: make(chan Cmd, cfg.CmdBuffer)}, nil
}

func dsn(path string, params url.Values) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	u := url.URL{Scheme: "file", Opaque: filepath.ToSlash(abs)}
	return u.String() + "?" + params.Encode()
}

func openWriter(path string) (*sql.DB, error) {
	q := url.Values{}
	q.Set("mode", "rwc")
	// _pragma is applied on every new connection, so pragmas survive reconnects.
	for _, p := range []string{
		"journal_mode(WAL)", "synchronous(NORMAL)", "foreign_keys(ON)",
		"busy_timeout(5000)", "wal_autocheckpoint(1000)",
	} {
		q.Add("_pragma", p)
	}
	db, err := sql.Open("sqlite", dsn(path, q))
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func openReader(path string) (*sql.DB, error) {
	q := url.Values{}
	q.Set("mode", "ro")
	q.Add("_pragma", "busy_timeout(5000)")
	q.Add("_pragma", "foreign_keys(ON)")
	db, err := sql.Open("sqlite", dsn(path, q))
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(readerConns)
	db.SetMaxIdleConns(readerConns)
	db.SetConnMaxLifetime(0)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// Enqueue never blocks: returns ErrBacklogFull when channel is full.
func (s *Store) Enqueue(c Cmd) error {
	if s.closing.Load() {
		return ErrClosed
	}
	select {
	case s.cmdCh <- c:
		return nil
	default:
		s.dropped.Add(1)
		return ErrBacklogFull
	}
}

// Flush commits all commands queued before it and waits for the result.
func (s *Store) Flush(ctx context.Context) error {
	done := make(chan error, 1)
	if err := s.Enqueue(Flush{Done: done}); err != nil {
		return err
	}
	select {
	case err := <-done:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Stats returns current counters.
func (s *Store) Stats() Stats {
	return Stats{
		Commits: s.commits.Load(),
		Backlog: int64(len(s.cmdCh)),
		Dropped: s.dropped.Load(),
		Failed:  s.failed.Load(),
	}
}
