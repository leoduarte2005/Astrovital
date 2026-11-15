package store

import (
	"context"
	"fmt"
	"strings"

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
// if the table or either column is absent it returns the fallback crew list.
func (s *Store) ListCrew(ctx context.Context) ([]contracts.CrewSummary, error) {
	if s.operational {
		rows, err := s.readerDB.QueryContext(ctx, `
			SELECT crew_id, name, COALESCE(role,''), COALESCE(mission_day,0),
			       COALESCE(calibration_status,'REQUIRES_CALIBRATION'), COALESCE(sample_count,0)
			FROM v_active_crew_baselines
			ORDER BY crew_id`)
		if err != nil {
			return nil, fmt.Errorf("store: list crew from v_active_crew_baselines: %w", err)
		}
		defer rows.Close()

		out := []contracts.CrewSummary{}
		for rows.Next() {
			var c contracts.CrewSummary
			var calibrationStatus string
			var sampleCount int64
			if err := rows.Scan(&c.CrewID, &c.Name, &c.Role, &c.MissionDay, &calibrationStatus, &sampleCount); err != nil {
				return nil, fmt.Errorf("store: scan crew: %w", err)
			}
			calibrated := (calibrationStatus == "READY" || calibrationStatus == "SYNTHETIC_SEED") && sampleCount > 0
			c.CalibrationRequired = !calibrated
			out = append(out, c)
		}
		return out, rows.Err()
	}

	cols, err := s.tableCols(ctx, "crew_profiles")
	if err != nil {
		return nil, fmt.Errorf("store: inspect crew_profiles: %w", err)
	}
	if !hasCols(cols, "crew_id", "name") {
		return s.fallback.listCrew(), nil
	}

	selectCols := []string{"crew_id", "name"}
	hasRole := cols["role"]
	hasDay := cols["mission_day"]
	hasBase := cols["baseline_path"]
	if hasRole {
		selectCols = append(selectCols, "COALESCE(role,'')")
	}
	if hasDay {
		selectCols = append(selectCols, "COALESCE(mission_day,0)")
	}
	if hasBase {
		selectCols = append(selectCols, "COALESCE(baseline_path,'')")
	}

	q := fmt.Sprintf("SELECT %s FROM crew_profiles ORDER BY crew_id", strings.Join(selectCols, ","))
	rows, err := s.readerDB.QueryContext(ctx, q)
	if err != nil {
		return nil, fmt.Errorf("store: list crew: %w", err)
	}
	defer rows.Close()

	out := []contracts.CrewSummary{}
	for rows.Next() {
		var c contracts.CrewSummary
		var baselinePath string
		dest := []any{&c.CrewID, &c.Name}
		if hasRole {
			dest = append(dest, &c.Role)
		}
		if hasDay {
			dest = append(dest, &c.MissionDay)
		}
		if hasBase {
			dest = append(dest, &baselinePath)
		}
		if err := rows.Scan(dest...); err != nil {
			return nil, fmt.Errorf("store: scan crew: %w", err)
		}
		c.CalibrationRequired = baselinePath == ""
		out = append(out, c)
	}
	return out, rows.Err()
}
