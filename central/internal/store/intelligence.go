package store

import (
	"context"
	"database/sql"
	"edgespace/central/internal/contracts"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"time"
)

// MissionEventRecord represents a row in mission_context_events.
type MissionEventRecord struct {
	EventID       string
	CrewID        *string
	EventType     string
	TsUs          int64
	EndUs         *int64
	LookbackHours float64
	Severity      string
	DetailsJSON   string
	DataClass     string
}

// NutritionLogRecord represents a row in nutrition_hydration_logs.
type NutritionLogRecord struct {
	LogID              string
	CrewID             string
	TsUs               int64
	WaterMl            *float64
	EnergyKcal         *float64
	ProteinG           *float64
	CalciumMg          *float64
	IronMg             *float64
	VitaminDUg         *float64
	PotassiumCitrateMg *float64
	SodiumMg           *float64
	BodyMassKg         *float64
	SourceNote         string
	DataClass          string
}

// CircadianScheduleRecord represents a row in crew_circadian_schedule.
type CircadianScheduleRecord struct {
	ScheduleID         string
	CrewID             string
	DayUTC             string
	SleepStartUs       int64
	SleepEndUs         int64
	LightStartUs       *int64
	LightEndUs         *int64
	LightLux           *float64
	ActualSleepStartUs *int64
	ActualSleepEndUs   *int64
	SleepQualityScore  *float64
	DataClass          string
}

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
		{Query: `UPDATE crew_profiles SET baseline_path=COALESCE(?, baseline_path) WHERE crew_id=?`, Args: []any{model, crew}},
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
func (s *Store) SaveMissionEvent(ctx context.Context, rec MissionEventRecord) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	cols, err := s.tableCols(ctx, "mission_context_events")
	if err != nil || !hasCols(cols, "event_id", "event_type", "ts_us", "lookback_hours", "severity", "details_json", "data_class") {
		return s.schemaError("mission_context_events", err)
	}
	if rec.EventType == "" {
		return errors.New("store: event_type required")
	}
	tsUs := rec.TsUs
	if tsUs <= 0 {
		tsUs = time.Now().UnixMicro()
	}
	eventID := rec.EventID
	if eventID == "" {
		eventID = fmt.Sprintf("evt-%s-%d", rec.EventType, tsUs)
	}
	lookback := rec.LookbackHours
	if lookback <= 0 {
		if rec.EventType == "EVA" || rec.EventType == "RADIATION_SPE_ALERT" {
			lookback = 72
		} else {
			lookback = 2
		}
	}
	severity := rec.Severity
	if severity == "" {
		severity = "INFO"
	}
	details := rec.DetailsJSON
	if details == "" {
		details = "{}"
	}
	dataClass := rec.DataClass
	if dataClass == "" {
		dataClass = "REAL"
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO mission_context_events(event_id, crew_id, event_type, ts_us, end_us, lookback_hours, severity, details_json, data_class)
		        VALUES (?,?,?,?,?,?,?,?,?)
		        ON CONFLICT(event_id) DO UPDATE SET end_us=excluded.end_us, lookback_hours=excluded.lookback_hours, severity=excluded.severity, details_json=excluded.details_json`,
		Args: []any{eventID, nullableCrew(rec.CrewID), rec.EventType, tsUs, nullableInt64(rec.EndUs), lookback, severity, details, dataClass},
	}, false)
}

func (s *Store) SaveNutritionLog(ctx context.Context, rec NutritionLogRecord) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	cols, err := s.tableCols(ctx, "nutrition_hydration_logs")
	if err != nil || !hasCols(cols, "log_id", "crew_id", "ts_us", "source_note", "data_class") {
		return s.schemaError("nutrition_hydration_logs", err)
	}
	if rec.CrewID == "" {
		return errors.New("store: crew_id required")
	}
	tsUs := rec.TsUs
	if tsUs <= 0 {
		tsUs = time.Now().UnixMicro()
	}
	logID := rec.LogID
	if logID == "" {
		logID = fmt.Sprintf("nut-%s-%d", rec.CrewID, tsUs)
	}
	dataClass := rec.DataClass
	if dataClass == "" {
		dataClass = "REAL"
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO nutrition_hydration_logs(log_id, crew_id, ts_us, water_ml, energy_kcal, protein_g, calcium_mg, iron_mg, vitamin_d_ug, potassium_citrate_mg, sodium_mg, body_mass_kg, source_note, data_class)
		        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
		        ON CONFLICT(log_id) DO UPDATE SET water_ml=excluded.water_ml, energy_kcal=excluded.energy_kcal, protein_g=excluded.protein_g, calcium_mg=excluded.calcium_mg, iron_mg=excluded.iron_mg, vitamin_d_ug=excluded.vitamin_d_ug, potassium_citrate_mg=excluded.potassium_citrate_mg, sodium_mg=excluded.sodium_mg, body_mass_kg=excluded.body_mass_kg, source_note=excluded.source_note`,
		Args: []any{logID, rec.CrewID, tsUs, nullableFloat(rec.WaterMl), nullableFloat(rec.EnergyKcal), nullableFloat(rec.ProteinG), nullableFloat(rec.CalciumMg), nullableFloat(rec.IronMg), nullableFloat(rec.VitaminDUg), nullableFloat(rec.PotassiumCitrateMg), nullableFloat(rec.SodiumMg), nullableFloat(rec.BodyMassKg), rec.SourceNote, dataClass},
	}, false)
}

func (s *Store) SaveCircadianSchedule(ctx context.Context, rec CircadianScheduleRecord) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	cols, err := s.tableCols(ctx, "crew_circadian_schedule")
	if err != nil || !hasCols(cols, "schedule_id", "crew_id", "day_utc", "sleep_start_us", "sleep_end_us", "data_class") {
		return s.schemaError("crew_circadian_schedule", err)
	}
	if rec.CrewID == "" || rec.DayUTC == "" {
		return errors.New("store: crew_id and day_utc required")
	}
	schedID := rec.ScheduleID
	if schedID == "" {
		schedID = fmt.Sprintf("circ-%s-%s", rec.CrewID, rec.DayUTC)
	}
	dataClass := rec.DataClass
	if dataClass == "" {
		dataClass = "REAL"
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO crew_circadian_schedule(schedule_id, crew_id, day_utc, sleep_start_us, sleep_end_us, light_start_us, light_end_us, light_lux, data_class, actual_sleep_start_us, actual_sleep_end_us, sleep_quality_score)
		        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
		        ON CONFLICT(crew_id, day_utc) DO UPDATE SET sleep_start_us=excluded.sleep_start_us, sleep_end_us=excluded.sleep_end_us, light_start_us=excluded.light_start_us, light_end_us=excluded.light_end_us, light_lux=excluded.light_lux, actual_sleep_start_us=excluded.actual_sleep_start_us, actual_sleep_end_us=excluded.actual_sleep_end_us, sleep_quality_score=excluded.sleep_quality_score, data_class=excluded.data_class`,
		Args: []any{schedID, rec.CrewID, rec.DayUTC, rec.SleepStartUs, rec.SleepEndUs, nullableInt64(rec.LightStartUs), nullableInt64(rec.LightEndUs), nullableFloat(rec.LightLux), dataClass, nullableInt64(rec.ActualSleepStartUs), nullableInt64(rec.ActualSleepEndUs), nullableFloat(rec.SleepQualityScore)},
	}, false)
}

func (s *Store) StartChatSession(ctx context.Context, sessionID, crewID string, startedUs int64) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	cols, err := s.tableCols(ctx, "chat_sessions")
	if err != nil || !hasCols(cols, "session_id", "crew_id", "started_us") {
		return s.schemaError("chat_sessions", err)
	}
	if sessionID == "" || crewID == "" {
		return errors.New("store: session_id and crew_id required")
	}
	if startedUs <= 0 {
		startedUs = time.Now().UnixMicro()
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO chat_sessions(session_id, crew_id, started_us) VALUES (?,?,?) ON CONFLICT(session_id) DO NOTHING`,
		Args:  []any{sessionID, crewID, startedUs},
	}, true)
}

func (s *Store) EndChatSession(ctx context.Context, sessionID string, endedUs int64) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	cols, err := s.tableCols(ctx, "chat_sessions")
	if err != nil || !hasCols(cols, "session_id", "ended_us") {
		return s.schemaError("chat_sessions", err)
	}
	if sessionID == "" {
		return errors.New("store: session_id required")
	}
	if endedUs <= 0 {
		endedUs = time.Now().UnixMicro()
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `UPDATE chat_sessions SET ended_us=? WHERE session_id=?`,
		Args:  []any{endedUs, sessionID},
	}, true)
}

func (s *Store) RollupShift(ctx context.Context, crewID string, shiftStartUs int64) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	if crewID == "" {
		return errors.New("store: crew_id required")
	}
	cols, err := s.tableCols(ctx, "telemetry_shift_rollups")
	if err != nil || !hasCols(cols, "crew_id", "shift_start_us", "shift_end_us", "shift_label", "day_utc", "sample_count") {
		return s.schemaError("telemetry_shift_rollups", err)
	}
	t := time.UnixMicro(shiftStartUs).UTC()
	dayUTC := t.Format("2006-01-02")
	shiftEndUs := shiftStartUs + int64(8*time.Hour/time.Microsecond)
	shiftLabel := "WORK_PM"
	if t.Hour() < 8 {
		shiftLabel = "SLEEP"
	} else if t.Hour() < 16 {
		shiftLabel = "WORK_AM"
	}
	var sampleCount int64
	var hrMean, hrvMean, respMean, spo2Mean, co2Mean, tempMean sql.NullFloat64
	err = s.readerDB.QueryRowContext(ctx, `
		SELECT COUNT(1), AVG(heart_rate_bpm), AVG(hrv_ms), AVG(resp_rate_bpm), AVG(spo2_pct), AVG(co2_ppm), AVG(temp_c)
		FROM telemetry_timeseries WHERE crew_id=? AND ts_us>=? AND ts_us<?`,
		crewID, shiftStartUs, shiftEndUs,
	).Scan(&sampleCount, &hrMean, &hrvMean, &respMean, &spo2Mean, &co2Mean, &tempMean)
	if err != nil {
		return fmt.Errorf("store: rollup shift query: %w", err)
	}
	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO telemetry_shift_rollups(crew_id, shift_start_us, shift_end_us, shift_label, day_utc, sample_count, hr_mean, hrv_mean, resp_mean, spo2_mean, co2_mean, temp_mean, data_class)
		        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'DERIVED')
		        ON CONFLICT(crew_id, shift_start_us) DO UPDATE SET shift_end_us=excluded.shift_end_us, shift_label=excluded.shift_label, day_utc=excluded.day_utc, sample_count=excluded.sample_count, hr_mean=excluded.hr_mean, hrv_mean=excluded.hrv_mean, resp_mean=excluded.resp_mean, spo2_mean=excluded.spo2_mean, co2_mean=excluded.co2_mean, temp_mean=excluded.temp_mean, data_class=excluded.data_class`,
		Args: []any{crewID, shiftStartUs, shiftEndUs, shiftLabel, dayUTC, sampleCount, nullFloat(hrMean), nullFloat(hrvMean), nullFloat(respMean), nullFloat(spo2Mean), nullFloat(co2Mean), nullFloat(tempMean)},
	}, true)
}

func (s *Store) RollupDay(ctx context.Context, crewID, dayUTC string) error {
	if !s.operational {
		return errors.New("store: operational schema required")
	}
	if crewID == "" || dayUTC == "" {
		return errors.New("store: crew_id and day_utc required")
	}
	t, err := time.Parse("2006-01-02", dayUTC)
	if err != nil {
		return fmt.Errorf("store: invalid day_utc %q: %w", dayUTC, err)
	}
	cols, err := s.tableCols(ctx, "telemetry_daily_rollups")
	if err != nil || !hasCols(cols, "crew_id", "day_utc", "mission_day", "sample_count", "energy_kcal_total", "alerts_yellow_count", "alerts_red_count") {
		return s.schemaError("telemetry_daily_rollups", err)
	}
	startUs := t.UTC().UnixMicro()
	endUs := t.UTC().Add(24 * time.Hour).UnixMicro()

	var missionDay int
	var missionStartUs sql.NullInt64
	if err := s.readerDB.QueryRowContext(ctx,
		`SELECT COALESCE(mission_day,0), mission_start_us FROM crew_profiles WHERE crew_id=?`, crewID,
	).Scan(&missionDay, &missionStartUs); err != nil {
		return fmt.Errorf("store: rollup day crew %s: %w", crewID, err)
	}
	if missionStartUs.Valid && missionStartUs.Int64 > 0 {
		if d := int((startUs-missionStartUs.Int64)/(86400*1_000_000)) + 1; d > 0 {
			missionDay = d
		}
	}

	var sampleCount int64
	var hrMean, hrMin, hrMax, hrvMean, respMean, spo2Mean, spo2Min, co2Mean, co2Max, tempMean sql.NullFloat64
	if err := s.readerDB.QueryRowContext(ctx, `
		SELECT COUNT(1), AVG(heart_rate_bpm), MIN(heart_rate_bpm), MAX(heart_rate_bpm),
		       AVG(hrv_ms), AVG(resp_rate_bpm), AVG(spo2_pct), MIN(spo2_pct),
		       AVG(co2_ppm), MAX(co2_ppm), AVG(temp_c)
		FROM telemetry_timeseries WHERE crew_id=? AND ts_us>=? AND ts_us<?`,
		crewID, startUs, endUs,
	).Scan(&sampleCount, &hrMean, &hrMin, &hrMax, &hrvMean, &respMean, &spo2Mean, &spo2Min, &co2Mean, &co2Max, &tempMean); err != nil {
		return fmt.Errorf("store: rollup day telemetry: %w", err)
	}

	var hrvP10 any
	hrvRows, err := s.readerDB.QueryContext(ctx,
		`SELECT hrv_ms FROM telemetry_timeseries WHERE crew_id=? AND ts_us>=? AND ts_us<? AND hrv_ms IS NOT NULL ORDER BY hrv_ms ASC`,
		crewID, startUs, endUs)
	if err != nil {
		return fmt.Errorf("store: rollup day hrv: %w", err)
	}
	var hrvVals []float64
	for hrvRows.Next() {
		var v float64
		if err := hrvRows.Scan(&v); err != nil {
			hrvRows.Close()
			return err
		}
		hrvVals = append(hrvVals, v)
	}
	hrvRows.Close()
	if err := hrvRows.Err(); err != nil {
		return err
	}
	if len(hrvVals) > 0 {
		hrvP10 = hrvVals[int(math.Floor(0.10*float64(len(hrvVals)-1)))]
	}

	var alertsYellow, alertsRed int64
	if err := s.readerDB.QueryRowContext(ctx, `
		SELECT COALESCE(SUM(CASE WHEN severity='YELLOW' THEN 1 ELSE 0 END), 0),
		       COALESCE(SUM(CASE WHEN severity='RED' THEN 1 ELSE 0 END), 0)
		FROM alerts_audit WHERE crew_id=? AND ts_us>=? AND ts_us<?`,
		crewID, startUs, endUs,
	).Scan(&alertsYellow, &alertsRed); err != nil {
		return fmt.Errorf("store: rollup day alerts: %w", err)
	}

	var exerciseMin, evaMin, radiationMsv float64
	var sleepFromEvt sql.NullFloat64
	if err := s.readerDB.QueryRowContext(ctx, `
		SELECT
			COALESCE(SUM(CASE WHEN event_type IN ('EXERCISE_ARED','EXERCISE_AEROBIC') THEN
				CASE WHEN end_us IS NOT NULL THEN (end_us - ts_us)/60000000.0
				     ELSE COALESCE(CAST(json_extract(details_json,'$.duration_min') AS REAL), 0) END
			ELSE 0 END), 0),
			COALESCE(SUM(CASE WHEN event_type='EVA' THEN
				CASE WHEN end_us IS NOT NULL THEN (end_us - ts_us)/60000000.0
				     ELSE COALESCE(CAST(json_extract(details_json,'$.duration_min') AS REAL), 0) END
			ELSE 0 END), 0),
			COALESCE(SUM(CASE WHEN event_type IN ('EVA','RADIATION_SPE_ALERT') THEN
				COALESCE(CAST(json_extract(details_json,'$.dose_msv') AS REAL), 0)
			ELSE 0 END), 0),
			SUM(CASE WHEN event_type='SLEEP_WINDOW' AND end_us IS NOT NULL THEN (end_us - ts_us)/3600000000.0 END)
		FROM mission_context_events WHERE crew_id=? AND ts_us>=? AND ts_us<?`,
		crewID, startUs, endUs,
	).Scan(&exerciseMin, &evaMin, &radiationMsv, &sleepFromEvt); err != nil {
		return fmt.Errorf("store: rollup day events: %w", err)
	}
	var sleepFromCirc sql.NullFloat64
	err = s.readerDB.QueryRowContext(ctx, `
		SELECT (COALESCE(actual_sleep_end_us, sleep_end_us) - COALESCE(actual_sleep_start_us, sleep_start_us)) / 3600000000.0
		FROM crew_circadian_schedule WHERE crew_id=? AND day_utc=?`,
		crewID, dayUTC,
	).Scan(&sleepFromCirc)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("store: rollup day circadian: %w", err)
	}
	var sleepDur any
	if sleepFromEvt.Valid && sleepFromEvt.Float64 >= 0 {
		sleepDur = sleepFromEvt.Float64
	} else if sleepFromCirc.Valid && sleepFromCirc.Float64 >= 0 {
		sleepDur = sleepFromCirc.Float64
	}

var kcalCnt, waterCnt int64
	var kcalSum, waterSum sql.NullFloat64
	if err := s.readerDB.QueryRowContext(ctx, `
		SELECT COUNT(energy_kcal), SUM(energy_kcal), COUNT(water_ml), SUM(water_ml)
		FROM nutrition_hydration_logs WHERE crew_id=? AND ts_us>=? AND ts_us<?`,
		crewID, startUs, endUs,
	).Scan(&kcalCnt, &kcalSum, &waterCnt, &waterSum); err != nil {
		return fmt.Errorf("store: rollup day nutrition: %w", err)
	}
	var energyTotal, waterTotal any
	if kcalCnt > 0 {
		energyTotal = kcalSum.Float64
	}
	if waterCnt > 0 {
		waterTotal = waterSum.Float64
	}

	var bodyMass sql.NullFloat64
	err = s.readerDB.QueryRowContext(ctx, `
		SELECT body_mass_kg FROM nutrition_hydration_logs
		WHERE crew_id=? AND ts_us>=? AND ts_us<? AND body_mass_kg IS NOT NULL
		ORDER BY ts_us DESC LIMIT 1`,
		crewID, startUs, endUs,
	).Scan(&bodyMass)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("store: rollup day body mass: %w", err)
	}

	return s.writeNowOrEnqueue(ctx, Exec{
		Query: `INSERT INTO telemetry_daily_rollups(
			crew_id, day_utc, mission_day, sample_count,
			hr_mean, hr_min, hr_max, hrv_mean, hrv_p10, resp_mean,
			spo2_mean, spo2_min, co2_mean, co2_max, temp_mean,
			sleep_duration_h, exercise_minutes, radiation_dose_msv,
			data_class, body_mass_kg, energy_kcal_total, water_ml_total, eva_minutes,
			alerts_yellow_count, alerts_red_count
		) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DERIVED',?,?,?,?,?,?)
		ON CONFLICT(crew_id, day_utc) DO UPDATE SET
			mission_day=excluded.mission_day, sample_count=excluded.sample_count,
			hr_mean=excluded.hr_mean, hr_min=excluded.hr_min, hr_max=excluded.hr_max,
			hrv_mean=excluded.hrv_mean, hrv_p10=excluded.hrv_p10, resp_mean=excluded.resp_mean,
			spo2_mean=excluded.spo2_mean, spo2_min=excluded.spo2_min,
			co2_mean=excluded.co2_mean, co2_max=excluded.co2_max, temp_mean=excluded.temp_mean,
			sleep_duration_h=COALESCE(excluded.sleep_duration_h, telemetry_daily_rollups.sleep_duration_h),
			exercise_minutes=excluded.exercise_minutes, radiation_dose_msv=excluded.radiation_dose_msv,
			data_class=excluded.data_class,
			body_mass_kg=COALESCE(excluded.body_mass_kg, telemetry_daily_rollups.body_mass_kg),
			energy_kcal_total=excluded.energy_kcal_total, water_ml_total=excluded.water_ml_total,
			eva_minutes=excluded.eva_minutes, alerts_yellow_count=excluded.alerts_yellow_count,
			alerts_red_count=excluded.alerts_red_count`,
		Args: []any{
			crewID, dayUTC, missionDay, sampleCount,
			nullFloat(hrMean), nullFloat(hrMin), nullFloat(hrMax),
			nullFloat(hrvMean), hrvP10, nullFloat(respMean),
			nullFloat(spo2Mean), nullFloat(spo2Min),
			nullFloat(co2Mean), nullFloat(co2Max), nullFloat(tempMean),
			sleepDur, exerciseMin, radiationMsv,
			nullFloat(bodyMass), energyTotal, waterTotal, evaMin,
			alertsYellow, alertsRed,
		},
	}, true)
}

func (s *Store) rollupLoop(ctx context.Context) {
	ticker := time.NewTicker(time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			s.runHourlyRollup(ctx, now.UTC())
		}
	}
}

func (s *Store) runHourlyRollup(ctx context.Context, now time.Time) {
	rows, err := s.readerDB.QueryContext(ctx, `SELECT crew_id FROM crew_profiles ORDER BY crew_id`)
	if err != nil {
		if ctx.Err() == nil {
			s.log.Warn("hourly rollup list crew failed", "err", err)
		}
		return
	}
	var crewIDs []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return
		}
		crewIDs = append(crewIDs, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return
	}
	shiftHour := (now.Hour() / 8) * 8
	shiftStartUs := time.Date(now.Year(), now.Month(), now.Day(), shiftHour, 0, 0, 0, time.UTC).UnixMicro()
	dayUTC := now.Format("2006-01-02")
	for _, id := range crewIDs {
		if ctx.Err() != nil {
			return
		}
		if err := s.RollupShift(ctx, id, shiftStartUs); err != nil && ctx.Err() == nil {
			s.log.Warn("hourly RollupShift failed", "crew_id", id, "err", err)
		}
		if err := s.RollupDay(ctx, id, dayUTC); err != nil && ctx.Err() == nil {
			s.log.Warn("hourly RollupDay failed", "crew_id", id, "err", err)
		}
	}
}

func nullableFloat(v *float64) any {
	if v == nil {
		return nil
	}
	return *v
}

func nullableInt64(v *int64) any {
	if v == nil {
		return nil
	}
	return *v
}

func nullFloat(v sql.NullFloat64) any {
	if !v.Valid {
		return nil
	}
	return v.Float64
}


