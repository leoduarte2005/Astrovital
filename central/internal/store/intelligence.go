package store

import (
	"context"
	"edgespace/central/internal/contracts"
	"encoding/json"
	"errors"
	"fmt"
	"math"
)

func (s *Store) SaveBaselineUpdate(ctx context.Context, crew string, data []byte, ts int64) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	var b struct {
		CrewID      string     `json:"crew_id"`
		Mean        []*float64 `json:"mean"`
		Std         []*float64 `json:"std"`
		Threshold   float64    `json:"threshold"`
		SampleCount int64      `json:"sample_count"`
		ModelPath   *string    `json:"model_path"`
		Schema      string     `json:"feature_schema_id"`
		Status      string     `json:"calibration_status"`
		Ratio       float64    `json:"clean_window_ratio"`
		Postures    []string   `json:"covered_postures"`
		StepID      string     `json:"step_id"`
	}
	if err := json.Unmarshal(data, &b); err != nil {
		return err
	}
	if b.CrewID != crew || b.Schema != "EDGESPACE_DSP64_V1" || len(b.Mean) != 64 || len(b.Std) != 64 || b.Threshold <= 0 || b.SampleCount < 0 || b.Ratio < 0 || b.Ratio > 1 {
		return errors.New("store: invalid calibration metadata")
	}
	if b.Status != "READY" && b.Status != "CALIBRATING" && b.Status != "REQUIRES_CALIBRATION" {
		return errors.New("store: invalid calibration status")
	}
	if b.Status == "READY" && b.SampleCount == 0 {
		return errors.New("store: no calibration samples")
	}
	for i := range b.Mean {
		if b.Mean[i] == nil || b.Std[i] == nil || math.IsNaN(*b.Mean[i]) || math.IsInf(*b.Mean[i], 0) || math.IsNaN(*b.Std[i]) || math.IsInf(*b.Std[i], 0) || *b.Std[i] <= 0 {
			return errors.New("store: invalid calibration vector")
		}
	}
	mean, _ := json.Marshal(b.Mean)
	std, _ := json.Marshal(b.Std)
	poses, _ := json.Marshal(b.Postures)
	id := fmt.Sprintf("calibration-%s-%d", crew, ts)
	var model any
	if b.ModelPath != nil && *b.ModelPath != "" {
		model = *b.ModelPath
	}
	return s.writeNowOrEnqueue(ctx, Statements{Items: []Exec{
		{Query: `UPDATE individual_baselines SET is_active=0 WHERE crew_id=? AND is_active=1`, Args: []any{crew}},
		{Query: `INSERT INTO individual_baselines(baseline_id,crew_id,version,onnx_model_path,feature_dim,feature_schema_id,mean_json,std_json,anomaly_threshold,sample_count,clean_window_ratio,covered_postures_json,calibration_status,drift_score,is_active,updated_at_us,data_class)
          VALUES (?,?,(SELECT COALESCE(MAX(version),0)+1 FROM individual_baselines WHERE crew_id=?),?,64,?,?,?,?,?,?,?,?,0,1,?,(SELECT data_class FROM crew_profiles WHERE crew_id=?))`,
			Args: []any{id, crew, crew, model, b.Schema, string(mean), string(std), b.Threshold, b.SampleCount, b.Ratio, string(poses), b.Status, ts, crew}},
		{Query: `INSERT INTO calibration_sessions(session_id,crew_id,baseline_id,started_us,ended_us,status,sample_count,clean_window_ratio,covered_postures_json,notes) VALUES (?,?,?,?,?,?,?,?,?,?)`, Args: []any{id, crew, id, ts, ts, b.Status, b.SampleCount, b.Ratio, string(poses), "IPC: " + b.StepID}},
	}}, true)
}

func (s *Store) memoryWrites(crew string, facts []contracts.ClinicalMemoryUpdate, ts int64) ([]Exec, error) {
	allowed := map[string]bool{"ALLERGY": true, "MEDICATION": true, "CONDITION_HISTORY": true, "SENSITIVITY": true, "SLEEP_NOTE": true, "PREFERENCE": true, "ANSWERED_TOPIC": true}
	writes := []Exec{}
	for _, f := range facts {
		if !allowed[f.FactType] || f.FactKey == "" || f.Confidence < 0 || f.Confidence > 1 || math.IsNaN(f.Confidence) || (f.SourceRole != "user" && f.SourceRole != "assistant" && f.SourceRole != "clinician") {
			return nil, errors.New("store: invalid clinical memory")
		}
		writes = append(writes, Exec{Query: `INSERT INTO crew_clinical_memory(memory_id,crew_id,fact_type,fact_key,fact_value,confidence,source_role,active,created_us,updated_us,data_class)
          VALUES (?,?,?,?,?,?,?,1,?,?,(SELECT data_class FROM crew_profiles WHERE crew_id=?))
          ON CONFLICT(crew_id,fact_type,fact_key) DO UPDATE SET fact_value=excluded.fact_value,confidence=excluded.confidence,source_role=excluded.source_role,active=1,updated_us=excluded.updated_us`, Args: []any{crew + ":" + f.FactType + ":" + f.FactKey, crew, f.FactType, f.FactKey, f.FactValue, f.Confidence, f.SourceRole, ts, ts, crew}})
	}
	return writes, nil
}
