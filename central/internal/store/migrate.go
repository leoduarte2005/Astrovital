package store

import (
	"database/sql"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// ensureInternalSchema creates only Central-internal bookkeeping tables.
// Clinical tables belong to M1 (database/migrations).
func ensureInternalSchema(db *sql.DB) error {
	_, err := db.Exec(`
CREATE TABLE IF NOT EXISTS schema_version (
	filename      TEXT PRIMARY KEY,
	applied_at_us INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS central_registry (
	key        TEXT PRIMARY KEY,
	value      TEXT NOT NULL,
	updated_us INTEGER NOT NULL
);`)
	return err
}

// applyMigrations applies *.sql files in lexicographic order, once each.
func applyMigrations(db *sql.DB, dir string, log *slog.Logger) error {
	if dir == "" {
		log.Warn("migrations dir not configured; only internal schema created")
		return nil
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			log.Warn("migrations dir missing; only internal schema created", "dir", dir)
			return nil
		}
		return err
	}
	var files []string
	for _, e := range entries {
		if !e.IsDir() && strings.EqualFold(filepath.Ext(e.Name()), ".sql") {
			files = append(files, e.Name())
		}
	}
	sort.Strings(files)
	if len(files) == 0 {
		log.Warn("no SQL migrations found (pending M1 schema); only internal schema created", "dir", dir)
		return nil
	}
	for _, name := range files {
		var n int
		if err := db.QueryRow(`SELECT COUNT(1) FROM schema_version WHERE filename=?`, name).Scan(&n); err != nil {
			return fmt.Errorf("check %s: %w", name, err)
		}
		if n > 0 {
			continue
		}
		body, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return fmt.Errorf("read %s: %w", name, err)
		}
		tx, err := db.Begin()
		if err != nil {
			return err
		}
		if _, err := tx.Exec(string(body)); err != nil {
			tx.Rollback()
			return fmt.Errorf("exec %s: %w", name, err)
		}
		if _, err := tx.Exec(`INSERT INTO schema_version(filename, applied_at_us) VALUES (?,?)`,
			name, time.Now().UnixMicro()); err != nil {
			tx.Rollback()
			return fmt.Errorf("record %s: %w", name, err)
		}
		if err := tx.Commit(); err != nil {
			return fmt.Errorf("commit %s: %w", name, err)
		}
		log.Info("migration applied", "file", name)
	}
	return nil
}
