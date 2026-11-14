package store

import (
	"context"
	"fmt"

	"edgespace/central/internal/contracts"
)

// Reader is the small read-only query surface consumed by httpws.
type Reader interface {
	// Health verifies the read-only pool answers queries.
	Health(ctx context.Context) error
	// ListCrew returns crew profiles; empty slice if schema/seeds absent.
	ListCrew(ctx context.Context) ([]contracts.CrewSummary, error)
}

// Reader returns a Reader backed by the read-only pool.
func (s *Store) Reader() Reader { return s }

// Health implements Reader.
func (s *Store) Health(ctx context.Context) error {
	var one int
	return s.readerDB.QueryRowContext(ctx, "SELECT 1").Scan(&one)
}

// ListCrew implements Reader. Depends on M1 table crew_profiles(crew_id, name);
// if the table or either column is absent it returns an empty list.
func (s *Store) ListCrew(ctx context.Context) ([]contracts.CrewSummary, error) {
	var cols int
	err := s.readerDB.QueryRowContext(ctx,
		`SELECT COUNT(1) FROM pragma_table_info('crew_profiles') WHERE name IN ('crew_id','name')`).Scan(&cols)
	if err != nil {
		return nil, fmt.Errorf("store: inspect crew_profiles: %w", err)
	}
	out := []contracts.CrewSummary{}
	if cols < 2 {
		if s.operational {
			return nil, s.schemaError("crew_profiles", nil)
		}
		return s.fallback.listCrew(), nil
	}
	rows, err := s.readerDB.QueryContext(ctx, `SELECT crew_id, name FROM crew_profiles ORDER BY crew_id`)
	if err != nil {
		return nil, fmt.Errorf("store: list crew: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var c contracts.CrewSummary
		if err := rows.Scan(&c.CrewID, &c.Name); err != nil {
			return nil, fmt.Errorf("store: scan crew: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
