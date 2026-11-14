package store

import (
	"context"
	"database/sql"
	"time"
)

// Run starts writerLoop and blocks until ctx is cancelled and shutdown
// finished (drain + final flush + wal_checkpoint(TRUNCATE) + close).
func (s *Store) Run(ctx context.Context) error {
	return s.writerLoop(ctx)
}

func (s *Store) writerLoop(ctx context.Context) error {
	s.running.Store(true)
	defer s.running.Store(false)

	ticker := time.NewTicker(s.cfg.BatchInterval)
	defer ticker.Stop()

	batch := make([]Cmd, 0, s.cfg.BatchSize)
	var waiters []chan<- error

	commit := func() {
		err := s.commitBatch(batch)
		for _, w := range waiters {
			w <- err
		}
		batch, waiters = batch[:0], waiters[:0]
	}
	// add returns true when a flush was requested or batch is full.
	add := func(c Cmd) {
		if f, ok := c.(Flush); ok {
			waiters = append(waiters, f.Done)
			commit()
			return
		}
		batch = append(batch, c)
		if len(batch) >= s.cfg.BatchSize {
			commit()
		}
	}

	for {
		select {
		case c := <-s.cmdCh:
			add(c)
		case <-ticker.C:
			if len(batch) > 0 {
				commit()
			}
		case <-ctx.Done():
			s.closing.Store(true)
			for drained := false; !drained; {
				select {
				case c := <-s.cmdCh:
					add(c)
				default:
					drained = true
				}
			}
			commit()
			return s.shutdown()
		}
	}
}

// commitBatch runs the batch in one BEGIN IMMEDIATE ... COMMIT transaction.
func (s *Store) commitBatch(batch []Cmd) error {
	if len(batch) == 0 {
		return nil
	}
	err := s.runTx(batch)
	if err != nil {
		s.failed.Add(int64(len(batch)))
		s.log.Error("store commit failed", "cmds", len(batch), "err", err)
		return err
	}
	s.commits.Add(1)
	return nil
}

func (s *Store) runTx(batch []Cmd) (err error) {
	ctx := context.Background()
	conn, err := s.writerDB.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()

	if _, err = conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	defer func() {
		if err != nil {
			conn.ExecContext(ctx, "ROLLBACK")
		}
	}()
	for _, c := range batch {
		if err = execCmd(ctx, conn, c); err != nil {
			return err
		}
	}
	_, err = conn.ExecContext(ctx, "COMMIT")
	return err
}

func execCmd(ctx context.Context, conn *sql.Conn, c Cmd) error {
	switch v := c.(type) {
	case Exec:
		_, err := conn.ExecContext(ctx, v.Query, v.Args...)
		return err
	case RegistrySet:
		_, err := conn.ExecContext(ctx,
			`INSERT INTO central_registry(key,value,updated_us) VALUES (?,?,?)
			 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_us=excluded.updated_us`,
			v.Key, v.Value, time.Now().UnixMicro())
		return err
	}
	return nil
}

func (s *Store) shutdown() error {
	var first error
	if _, err := s.writerDB.Exec("PRAGMA wal_checkpoint(TRUNCATE)"); err != nil {
		first = err
		s.log.Error("wal checkpoint failed", "err", err)
	}
	if err := s.readerDB.Close(); err != nil && first == nil {
		first = err
	}
	if err := s.writerDB.Close(); err != nil && first == nil {
		first = err
	}
	s.log.Info("store stopped")
	return first
}
