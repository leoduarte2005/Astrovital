package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"edgespace/central/internal/contracts"
)

// ErrNotFound is returned when a crew profile or protocol does not exist.
var ErrNotFound = errors.New("store: not found")

const (
	fallbackTimeseriesCap = 86400
	fallbackPeripheralCap = 86400
	fallbackAlertsCap     = 4096
	fallbackOutboxCap     = 4096
	fallbackChatCap       = 1024
	fallbackExamCap       = 1024
)

// CrewProfileRecord extends contracts.CrewProfile with baseline path and individual thresholds.
type CrewProfileRecord struct {
	Profile      contracts.CrewProfile
	BaselinePath string
	Thresholds   map[string]contracts.Threshold
}

// Telemetry1HzRecord is a decimated 1 Hz telemetry snapshot for telemetry_timeseries.
type Telemetry1HzRecord struct {
	TsUs        int64
	CrewID      *string
	MissionMode contracts.MissionMode
	Vitals      contracts.VitalsData
	Environment contracts.EnvironmentData
}

// PeripheralReadingRecord is a 1 Hz I2C reading for peripheral_readings.
type PeripheralReadingRecord struct {
	CrewID *string
	NodeID uint8
	Type   contracts.Peripheral
	Value  float64
	Unit   string
	TsUs   int64
}

// AlertWriteRecord is an alert event (+ optional outbox copy when RED).
type AlertWriteRecord struct {
	AlertID     string
	TsUs        int64
	CrewID      *string
	Alert       contracts.AlertEventPayload
	WriteOutbox bool
}

// CSIBlobWriteRecord captures calibration or RED alert raw CSI dumps.
type CSIBlobWriteRecord struct {
	TsUs   int64
	CrewID *string
	Reason string
	Blob   []byte
}

type chatLogEntry struct {
	CrewID string
	Msg    contracts.ChatMessage
}

type examLogEntry struct {
	TsUs   int64
	CrewID string
	Exam   contracts.SelfExamPayload
}

type auditLogEntry struct {
	TsUs      int64
	CrewID    *string
	EventType string
	Details   string
}

type fallbackStore struct {
	mu          sync.RWMutex
	crew        map[string]CrewProfileRecord
	crewOrder   []string
	protocols   map[string]contracts.ProtocolDTO
	timeseries  []Telemetry1HzRecord
	peripherals []PeripheralReadingRecord
	alerts      []contracts.AlertRecord
	outbox      []contracts.OutboxRecord
	chats       []chatLogEntry
	exams       []examLogEntry
	audits      []auditLogEntry
	blobs       []CSIBlobWriteRecord
}

func newFallbackStore() *fallbackStore {
	defaultThresh := map[string]contracts.Threshold{
		"co2_ppm":        {MetricName: "co2_ppm", YellowHigh: 1000, RedHigh: 3500},
		"spo2_pct":       {MetricName: "spo2_pct", YellowLow: 94, RedLow: 90},
		"heart_rate_bpm": {MetricName: "heart_rate_bpm", YellowHigh: 110, RedHigh: 140, YellowLow: 45, RedLow: 38},
	}
	cloneT := func() map[string]contracts.Threshold {
		m := make(map[string]contracts.Threshold, len(defaultThresh))
		for k, v := range defaultThresh {
			m[k] = v
		}
		return m
	}

	crew := map[string]CrewProfileRecord{
		"crew_001": {
			Profile:      contracts.CrewProfile{CrewID: "crew_001", Name: "Cmdr. Silva", Role: "Commander", MissionDay: 42, Age: 41},
			BaselinePath: "baselines/crew_001.onnx",
			Thresholds:   cloneT(),
		},
		"crew_002": {
			Profile:      contracts.CrewProfile{CrewID: "crew_002", Name: "Dr. Costa", Role: "Flight Surgeon", MissionDay: 42, Age: 38},
			BaselinePath: "baselines/crew_002.onnx",
			Thresholds:   cloneT(),
		},
		"crew_003": {
			Profile:      contracts.CrewProfile{CrewID: "crew_003", Name: "Eng. Sato", Role: "Flight Engineer", MissionDay: 42, Age: 35},
			BaselinePath: "",
			Thresholds:   cloneT(),
		},
	}

	return &fallbackStore{
		crew:      crew,
		crewOrder: []string{"crew_001", "crew_002", "crew_003"},
		protocols: defaultProtocols(),
	}
}

func defaultProtocols() map[string]contracts.ProtocolDTO {
	return map[string]contracts.ProtocolDTO{
		"amsler_grid": {
			ProtocolID:  "amsler_grid",
			Name:        "Amsler Grid Ocular Self-Exam (SANS/VIIP)",
			Subsystems:  []contracts.Subsystem{contracts.SubsystemNeuroOcularSANS},
			Description: "Visual screening for metamorphopsia or scotoma associated with Spaceflight Associated Neuro-ocular Syndrome.",
			Steps: []string{
				"Position Amsler grid at 30 cm under uniform cabin lighting.",
				"Cover left eye and fixate on central black dot with right eye.",
				"Note any wavy, blurred, distorted, or missing grid lines.",
				"Repeat with left eye and record result via SELF_EXAM.",
			},
		},
		"capillary_blood": {
			ProtocolID:  "capillary_blood",
			Name:        "Capillary Blood Micro-Sample",
			Subsystems:  []contracts.Subsystem{contracts.SubsystemImmuneHematoNutrition},
			Description: "Fingerstick capillary sample for hematocrit, lactate, and immune markers.",
			Steps: []string{
				"Warm fingertip and disinfect with alcohol swab.",
				"Perform lateral fingerstick with sterile safety lancet.",
				"Wipe first drop, fill microcuvette, and apply sterile gauze.",
			},
		},
		"ultrasound_onsd": {
			ProtocolID:  "ultrasound_onsd",
			Name:        "Ocular Ultrasound Optic Nerve Sheath Diameter (ONSD)",
			Subsystems:  []contracts.Subsystem{contracts.SubsystemNeuroOcularSANS},
			Description: "B-mode ultrasound measurement 3 mm posterior to globe to screen elevated ICP.",
			Steps: []string{
				"Apply sterile acoustic gel over closed upper eyelid.",
				"Acquire transverse and sagittal globe views with linear probe.",
				"Measure optic nerve sheath diameter 3 mm behind retina (alert if > 5.0 mm).",
			},
		},
		"blood_pressure": {
			ProtocolID:  "blood_pressure",
			Name:        "Resting & Orthostatic Blood Pressure Check",
			Subsystems:  []contracts.Subsystem{contracts.SubsystemCardiovascularFluids},
			Description: "Cuff blood pressure measurement for fluid-shift and orthostatic evaluation.",
			Steps: []string{
				"Rest quietly for 5 minutes with cuff at heart level.",
				"Record systolic/diastolic pressure and resting heart rate.",
				"Repeat after lower-body negative pressure or thigh-cuff change if indicated.",
			},
		},
		"temperature": {
			ProtocolID:  "temperature",
			Name:        "Core / Tympanic Temperature Measurement",
			Subsystems:  []contracts.Subsystem{contracts.SubsystemImmuneHematoNutrition},
			Description: "Core temperature check for fever, thermal stress, or circadian shift.",
			Steps: []string{
				"Ensure probe cover is clean and intact.",
				"Measure tympanic or oral temperature and wait for steady tone.",
				"Log reading via SELF_EXAM if >= 37.8 C or <= 35.5 C.",
			},
		},
	}
}

func (f *fallbackStore) listCrew() []contracts.CrewSummary {
	f.mu.RLock()
	defer f.mu.RUnlock()
	out := make([]contracts.CrewSummary, 0, len(f.crewOrder))
	for _, id := range f.crewOrder {
		c := f.crew[id]
		out = append(out, contracts.CrewSummary{
			CrewID:              c.Profile.CrewID,
			Name:                c.Profile.Name,
			Role:                c.Profile.Role,
			MissionDay:          c.Profile.MissionDay,
			CalibrationRequired: c.BaselinePath == "",
		})
	}
	return out
}

func (s *Store) tableCols(ctx context.Context, table string) (map[string]bool, error) {
	rows, err := s.readerDB.QueryContext(ctx, `SELECT name FROM pragma_table_info(?)`, table)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cols := make(map[string]bool)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		cols[strings.ToLower(name)] = true
	}
	return cols, rows.Err()
}

// schemaError prevents an operational database from silently falling back to RAM.
func (s *Store) schemaError(table string, err error) error {
	if err != nil {
		return fmt.Errorf("store: operational %s: %w", table, err)
	}
	return fmt.Errorf("store: operational %s is missing required columns", table)
}

func hasCols(cols map[string]bool, req ...string) bool {
	for _, r := range req {
		if !cols[strings.ToLower(r)] {
			return false
		}
	}
	return true
}

func (s *Store) writeNowOrEnqueue(ctx context.Context, cmd Cmd, flush bool) error {
	if s.running.Load() {
		if err := s.Enqueue(cmd); err != nil {
			return err
		}
		if flush {
			return s.Flush(ctx)
		}
		return nil
	}
	return s.runTx([]Cmd{cmd})
}

// LoadNodeIDs implements cluster.RegistryStore.
func (s *Store) LoadNodeIDs(ctx context.Context) (map[string]uint8, error) {
	cols, err := s.tableCols(ctx, "cluster_nodes")
	if err != nil {
		return nil, err
	}
	out := make(map[string]uint8)
	if hasCols(cols, "mac", "node_id") {
		rows, err := s.readerDB.QueryContext(ctx, `SELECT mac, node_id FROM cluster_nodes`)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		for rows.Next() {
			var mac string
			var id int
			if err := rows.Scan(&mac, &id); err != nil {
				return nil, err
			}
			if id >= 0 && id < 256 {
				out[mac] = uint8(id)
			}
		}
		return out, rows.Err()
	}

	rows, err := s.readerDB.QueryContext(ctx, `SELECT key, value FROM central_registry WHERE key LIKE 'mac:%'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return nil, err
		}
		id, err := strconv.Atoi(strings.TrimSpace(v))
		if err == nil && id >= 0 && id < 256 {
			out[strings.TrimPrefix(k, "mac:")] = uint8(id)
		}
	}
	return out, rows.Err()
}

// SaveNodeID implements cluster.RegistryStore.
func (s *Store) SaveNodeID(ctx context.Context, mac string, nodeID uint8) error {
	cols, err := s.tableCols(ctx, "cluster_nodes")
	if err != nil {
		return err
	}
	var cmd Cmd
	if hasCols(cols, "mac", "node_id") {
		nowUs := time.Now().UnixMicro()
		if hasCols(cols, "first_seen_us", "last_seen_us") {
			cmd = Exec{
				Query: `INSERT INTO cluster_nodes(mac, node_id, first_seen_us, last_seen_us) VALUES (?,?,?,?)
				        ON CONFLICT(mac) DO UPDATE SET node_id=excluded.node_id, last_seen_us=excluded.last_seen_us`,
				Args: []any{mac, int(nodeID), nowUs, nowUs},
			}
		} else {
			cmd = Exec{
				Query: `INSERT INTO cluster_nodes(mac, node_id) VALUES (?,?)
				        ON CONFLICT(mac) DO UPDATE SET node_id=excluded.node_id`,
				Args: []any{mac, int(nodeID)},
			}
		}
	} else {
		cmd = RegistrySet{
			Key:   "mac:" + mac,
			Value: strconv.Itoa(int(nodeID)),
		}
	}
	return s.writeNowOrEnqueue(ctx, cmd, true)
}

// GetCrewProfile loads a crew profile + thresholds from M1 crew_profiles or fallback memory.
func (s *Store) GetCrewProfile(ctx context.Context, id string) (CrewProfileRecord, error) {
	cols, err := s.tableCols(ctx, "crew_profiles")
	if err != nil {
		return CrewProfileRecord{}, err
	}
	if hasCols(cols, "crew_id", "name") {
		selectCols := []string{"crew_id", "name"}
		var rec CrewProfileRecord
		var threshJSON string
		dest := []any{&rec.Profile.CrewID, &rec.Profile.Name}

		if cols["role"] {
			selectCols = append(selectCols, "COALESCE(role,'')")
			dest = append(dest, &rec.Profile.Role)
		}
		if cols["mission_day"] {
			selectCols = append(selectCols, "COALESCE(mission_day,0)")
			dest = append(dest, &rec.Profile.MissionDay)
		}
		if cols["age"] {
			selectCols = append(selectCols, "COALESCE(age,0)")
			dest = append(dest, &rec.Profile.Age)
		}
		if cols["baseline_path"] {
			selectCols = append(selectCols, "COALESCE(baseline_path,'')")
			dest = append(dest, &rec.BaselinePath)
		}
		if cols["thresholds_json"] {
			selectCols = append(selectCols, "COALESCE(thresholds_json,'')")
			dest = append(dest, &threshJSON)
		}

		type strOpt struct {
			col string
			dst **string
			val sql.NullString
		}
		type fltOpt struct {
			col string
			dst **float64
			val sql.NullFloat64
		}
		strOpts := []*strOpt{
			{col: "biological_sex", dst: &rec.Profile.BiologicalSex},
			{col: "sans_susceptibility", dst: &rec.Profile.SANSSusceptibility},
			{col: "co2_sensitivity", dst: &rec.Profile.CO2Sensitivity},
			{col: "motion_sickness_history", dst: &rec.Profile.MotionSicknessHistory},
		}
		fltOpts := []*fltOpt{
			{col: "height_cm", dst: &rec.Profile.HeightCm},
			{col: "preflight_weight_kg", dst: &rec.Profile.PreflightWeightKg},
			{col: "vo2max_baseline", dst: &rec.Profile.VO2MaxBaseline},
			{col: "preflight_hr_bpm", dst: &rec.Profile.PreflightHRBpm},
			{col: "preflight_hrv_ms", dst: &rec.Profile.PreflightHRVMs},
			{col: "preflight_spo2_pct", dst: &rec.Profile.PreflightSpO2Pct},
			{col: "preflight_sbp_mmhg", dst: &rec.Profile.PreflightSBPMmHg},
			{col: "preflight_dbp_mmhg", dst: &rec.Profile.PreflightDBPMmHg},
			{col: "preflight_ferritin_ug_l", dst: &rec.Profile.PreflightFerritinUgL},
			{col: "preflight_hemoglobin_g_dl", dst: &rec.Profile.PreflightHemoglobinGDl},
			{col: "preflight_onsd_mm", dst: &rec.Profile.PreflightONSDMm},
			{col: "target_kcal_day", dst: &rec.Profile.TargetKcalDay},
			{col: "target_water_ml_day", dst: &rec.Profile.TargetWaterMlDay},
			{col: "radiation_career_limit_msv", dst: &rec.Profile.RadiationCareerLimitMsv},
		}
		for _, o := range strOpts {
			if cols[o.col] {
				selectCols = append(selectCols, o.col)
				dest = append(dest, &o.val)
			}
		}
		for _, o := range fltOpts {
			if cols[o.col] {
				selectCols = append(selectCols, o.col)
				dest = append(dest, &o.val)
			}
		}
		var missionStart sql.NullInt64
		if cols["mission_start_us"] {
			selectCols = append(selectCols, "mission_start_us")
			dest = append(dest, &missionStart)
		}

		q := fmt.Sprintf("SELECT %s FROM crew_profiles WHERE crew_id=?", strings.Join(selectCols, ","))
		if err := s.readerDB.QueryRowContext(ctx, q, id).Scan(dest...); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return CrewProfileRecord{}, ErrNotFound
			}
			return CrewProfileRecord{}, err
		}
		for _, o := range strOpts {
			if o.val.Valid {
				v := o.val.String
				*o.dst = &v
			}
		}
		for _, o := range fltOpts {
			if o.val.Valid {
				v := o.val.Float64
				*o.dst = &v
			}
		}
		if missionStart.Valid {
			v := missionStart.Int64
			rec.Profile.MissionStartUs = &v
		}
		if threshJSON != "" {
			_ = json.Unmarshal([]byte(threshJSON), &rec.Thresholds)
		}
		if s.operational {
			var modelPath string
			if err := s.readerDB.QueryRowContext(ctx,
				`SELECT COALESCE(model_path,'') FROM v_active_crew_baselines WHERE crew_id=?`, id,
			).Scan(&modelPath); err != nil {
				return CrewProfileRecord{}, err
			}
			rec.BaselinePath = modelPath
		}
		return rec, nil
	}

	if s.operational {
		return CrewProfileRecord{}, s.schemaError("crew_profiles", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	rec, ok := s.fallback.crew[id]
	if !ok {
		return CrewProfileRecord{}, ErrNotFound
	}
	return rec, nil
}

func appendBounded[T any](s []T, v T, max int) []T {
	if len(s) >= max {
		copy(s, s[1:])
		s[len(s)-1] = v
		return s
	}
	return append(s, v)
}

func nullableCrew(crewID *string) any {
	if crewID == nil || *crewID == "" {
		return nil
	}
	return *crewID
}

// SaveTelemetry1Hz persists a 1 Hz decimated telemetry sample to M1 telemetry_timeseries or fallback memory.
func (s *Store) SaveTelemetry1Hz(ctx context.Context, rec Telemetry1HzRecord) error {
	cols, err := s.tableCols(ctx, "telemetry_timeseries")
	if err == nil && hasCols(cols, "ts_us", "heart_rate_bpm", "co2_ppm") {
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO telemetry_timeseries(
				ts_us, crew_id, mission_mode, heart_rate_bpm, hrv_ms, resp_rate_bpm,
				spo2_pct, posture, confidence, co2_ppm, temp_c, humidity_pct, pressure_hpa
			) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
			Args: []any{
				rec.TsUs, nullableCrew(rec.CrewID), string(rec.MissionMode),
				rec.Vitals.HeartRateBpm, rec.Vitals.HRVMs, rec.Vitals.RespRateBpm,
				rec.Vitals.SpO2Pct, rec.Vitals.Posture, rec.Vitals.ConfidenceScore,
				rec.Environment.CO2Ppm, rec.Environment.TempC, rec.Environment.HumidityPct, rec.Environment.PressureHpa,
			},
		}, false)
	}

	if s.operational {
		return s.schemaError("telemetry_timeseries", err)
	}

	s.fallback.mu.Lock()
	s.fallback.timeseries = appendBounded(s.fallback.timeseries, rec, fallbackTimeseriesCap)
	s.fallback.mu.Unlock()
	return nil
}

// SavePeripheral1Hz persists 1 Hz I2C readings to M1 peripheral_readings or fallback memory.
func (s *Store) SavePeripheral1Hz(ctx context.Context, tsUs int64, readings []PeripheralReadingRecord) error {
	if len(readings) == 0 {
		return nil
	}
	cols, err := s.tableCols(ctx, "peripheral_readings")
	if err == nil && hasCols(cols, "ts_us", "sensor_type", "value") {
		for _, r := range readings {
			rts := r.TsUs
			if rts <= 0 {
				rts = tsUs
			}
			query := `INSERT INTO peripheral_readings(ts_us, node_id, sensor_type, value, unit) VALUES (?,?,?,?,?)`
			args := []any{rts, int(r.NodeID), string(r.Type), r.Value, r.Unit}
			if cols["crew_id"] {
				query = `INSERT INTO peripheral_readings(ts_us, node_id, sensor_type, value, unit, crew_id) VALUES (?,?,?,?,?,?)`
				args = append(args, nullableCrew(r.CrewID))
			}
			if err := s.writeNowOrEnqueue(ctx, Exec{Query: query, Args: args}, false); err != nil {
				return err
			}
		}
		return nil
	}

	if s.operational {
		return s.schemaError("peripheral_readings", err)
	}

	s.fallback.mu.Lock()
	for _, r := range readings {
		s.fallback.peripherals = appendBounded(s.fallback.peripherals, r, fallbackPeripheralCap)
	}
	s.fallback.mu.Unlock()
	return nil
}

// SaveAlertAndOutbox persists an alert to alerts_audit and, when WriteOutbox is true (RED), to store_and_forward_outbox.
func (s *Store) SaveAlertAndOutbox(ctx context.Context, rec AlertWriteRecord) error {
	alertID := rec.AlertID
	if alertID == "" {
		alertID = fmt.Sprintf("al-%d-%s", rec.TsUs, rec.Alert.Subsystem)
	}
	cols, err := s.tableCols(ctx, "alerts_audit")
	if err == nil && hasCols(cols, "alert_id", "ts_us", "subsystem", "severity", "message") {
		if err := s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT OR IGNORE INTO alerts_audit(
				alert_id, ts_us, crew_id, subsystem, severity, message, countermeasure, escalation, handled
			) VALUES (?,?,?,?,?,?,?,?,0)`,
			Args: []any{
				alertID, rec.TsUs, nullableCrew(rec.CrewID), string(rec.Alert.Subsystem),
				string(rec.Alert.Severity), rec.Alert.Message, rec.Alert.Countermeasure, string(rec.Alert.Escalation),
			},
		}, false); err != nil {
			return err
		}
		if rec.WriteOutbox {
			return s.SaveOutbox(ctx, contracts.OutboxRecord{
				OutboxID:    "ob-" + alertID,
				TsUs:        rec.TsUs,
				Subsystem:   rec.Alert.Subsystem,
				Severity:    rec.Alert.Severity,
				Message:     rec.Alert.Message,
				Destination: "ground_control",
				Sent:        false,
			})
		}
		return nil
	}

	if s.operational {
		return s.schemaError("alerts_audit", err)
	}

	s.fallback.mu.Lock()
	s.fallback.alerts = appendBounded(s.fallback.alerts, contracts.AlertRecord{
		AlertID:        alertID,
		TsUs:           rec.TsUs,
		CrewID:         rec.CrewID,
		Subsystem:      rec.Alert.Subsystem,
		Severity:       rec.Alert.Severity,
		Message:        rec.Alert.Message,
		Countermeasure: rec.Alert.Countermeasure,
		Escalation:     rec.Alert.Escalation,
		Handled:        false,
	}, fallbackAlertsCap)
	if rec.WriteOutbox {
		s.fallback.outbox = appendBounded(s.fallback.outbox, contracts.OutboxRecord{
			OutboxID:    "ob-" + alertID,
			TsUs:        rec.TsUs,
			Subsystem:   rec.Alert.Subsystem,
			Severity:    rec.Alert.Severity,
			Message:     rec.Alert.Message,
			Destination: "ground_control",
			Sent:        false,
		}, fallbackOutboxCap)
	}
	s.fallback.mu.Unlock()
	return nil
}

// SaveOutbox queues an entry into store_and_forward_outbox or fallback memory.
func (s *Store) SaveOutbox(ctx context.Context, rec contracts.OutboxRecord) error {
	if rec.OutboxID == "" {
		rec.OutboxID = fmt.Sprintf("ob-%d", rec.TsUs)
	}
	cols, err := s.tableCols(ctx, "store_and_forward_outbox")
	if err == nil && hasCols(cols, "outbox_id", "ts_us", "subsystem", "severity", "message") {
		sentInt := 0
		if rec.Sent {
			sentInt = 1
		}
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT OR IGNORE INTO store_and_forward_outbox(
				outbox_id, ts_us, subsystem, severity, message, destination, sent
			) VALUES (?,?,?,?,?,?,?)`,
			Args: []any{rec.OutboxID, rec.TsUs, string(rec.Subsystem), string(rec.Severity), rec.Message, rec.Destination, sentInt},
		}, false)
	}
	if s.operational {
		return s.schemaError("store_and_forward_outbox", err)
	}

	s.fallback.mu.Lock()
	s.fallback.outbox = appendBounded(s.fallback.outbox, rec, fallbackOutboxCap)
	s.fallback.mu.Unlock()
	return nil
}

// SaveSelfExam persists a self-exam into M1 self_exams or fallback memory.
func (s *Store) SaveSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload, tsUs int64) error {
	cols, err := s.tableCols(ctx, "self_exams")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "exam_type", "result") {
		if hasCols(cols, "protocol_id", "payload_json", "abnormal_flag") {
			payload, err := json.Marshal(exam)
			if err != nil {
				return err
			}
			var protocolID sql.NullString
			err = s.readerDB.QueryRowContext(ctx, `SELECT protocol_id FROM protocols WHERE protocol_id=?`, exam.ExamType).Scan(&protocolID)
			if err != nil && !errors.Is(err, sql.ErrNoRows) {
				return err
			}
			var result struct {
				Abnormal bool `json:"abnormal_flag"`
			}
			_ = json.Unmarshal([]byte(exam.Result), &result)
			return s.writeNowOrEnqueue(ctx, Exec{
				Query: `INSERT INTO self_exams(ts_us,crew_id,exam_type,result,observations,protocol_id,payload_json,abnormal_flag) VALUES (?,?,?,?,?,?,?,?)`,
				Args:  []any{tsUs, crewID, exam.ExamType, exam.Result, exam.Observations, protocolID, string(payload), result.Abnormal},
			}, false)
		}
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO self_exams(ts_us, crew_id, exam_type, result, observations) VALUES (?,?,?,?,?)`,
			Args:  []any{tsUs, crewID, exam.ExamType, exam.Result, exam.Observations},
		}, false)
	}
	if s.operational {
		return s.schemaError("self_exams", err)
	}

	s.fallback.mu.Lock()
	s.fallback.exams = appendBounded(s.fallback.exams, examLogEntry{TsUs: tsUs, CrewID: crewID, Exam: exam}, fallbackExamCap)
	s.fallback.mu.Unlock()
	return nil
}

// SaveChatExchange persists user message and AI reply into M1 chat_messages or fallback memory.
func (s *Store) SaveChatExchange(ctx context.Context, crewID string, req contracts.ChatMsgPayload, resp contracts.ChatCorrelateRespPayload, tsUs int64) error {
	cols, err := s.tableCols(ctx, "chat_messages")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "role", "content") {
		if cols["metadata_json"] {
			metadata, err := json.Marshal(resp)
			if err != nil {
				return err
			}
			writes, err := s.memoryWrites(crewID, resp.MemoryUpdates, tsUs)
			if err != nil {
				return err
			}
			if cols["session_id"] {
				var sessionID string
				qErr := s.readerDB.QueryRowContext(ctx,
					`SELECT session_id FROM chat_sessions WHERE crew_id=? AND ended_us IS NULL ORDER BY started_us DESC LIMIT 1`,
					crewID,
				).Scan(&sessionID)
				var prefix []Exec
				if errors.Is(qErr, sql.ErrNoRows) || sessionID == "" {
					sessionID = fmt.Sprintf("chat-%s-%d", crewID, tsUs)
					prefix = append(prefix, Exec{
						Query: `INSERT OR IGNORE INTO chat_sessions(session_id, crew_id, started_us) VALUES (?,?,?)`,
						Args:  []any{sessionID, crewID, tsUs},
					})
				} else if qErr != nil {
					return qErr
				}
				prefix = append(prefix, Exec{
					Query: `INSERT INTO chat_messages(ts_us,crew_id,role,content,metadata_json,session_id) VALUES (?,?,'user',?,'{}',?),(?,?,'assistant',?,?,?)`,
					Args:  []any{tsUs, crewID, req.Text, sessionID, tsUs + 1, crewID, resp.Text, string(metadata), sessionID},
				})
				writes = append(prefix, writes...)
				return s.writeNowOrEnqueue(ctx, Statements{Items: writes}, true)
			}
			writes = append([]Exec{{Query: `INSERT INTO chat_messages(ts_us,crew_id,role,content,metadata_json) VALUES (?,?,'user',?,'{}'),(?,?,'assistant',?,?)`, Args: []any{tsUs, crewID, req.Text, tsUs + 1, crewID, resp.Text, string(metadata)}}}, writes...)
			return s.writeNowOrEnqueue(ctx, Statements{Items: writes}, true)
		}
		if err := s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO chat_messages(ts_us, crew_id, role, content) VALUES (?,?,?,?)`,
			Args:  []any{tsUs, crewID, "user", req.Text},
		}, false); err != nil {
			return err
		}
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO chat_messages(ts_us, crew_id, role, content) VALUES (?,?,?,?)`,
			Args:  []any{tsUs + 1, crewID, "assistant", resp.Text},
		}, false)
	}

	if s.operational {
		return s.schemaError("chat_messages", err)
	}

	s.fallback.mu.Lock()
	s.fallback.chats = appendBounded(s.fallback.chats, chatLogEntry{
		CrewID: crewID,
		Msg:    contracts.ChatMessage{SentAt: tsUs, Role: "user", Content: req.Text},
	}, fallbackChatCap)
	s.fallback.chats = appendBounded(s.fallback.chats, chatLogEntry{
		CrewID: crewID,
		Msg:    contracts.ChatMessage{SentAt: tsUs + 1, Role: "assistant", Content: resp.Text},
	}, fallbackChatCap)
	s.fallback.mu.Unlock()
	return nil
}

// SaveAudit persists audit events; memory is retained only for legacy schema-less tests.
func (s *Store) SaveAudit(ctx context.Context, crewID *string, eventType, details string, tsUs int64) error {
	cols, err := s.tableCols(ctx, "audit_log")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "event_type", "details") {
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO audit_log(ts_us,crew_id,event_type,details) VALUES (?,?,?,?)`,
			Args:  []any{tsUs, nullableCrew(crewID), eventType, details},
		}, false)
	}
	if s.operational {
		return s.schemaError("audit_log", err)
	}
	s.fallback.mu.Lock()
	s.fallback.audits = appendBounded(s.fallback.audits, auditLogEntry{
		TsUs: tsUs, CrewID: crewID, EventType: eventType, Details: details,
	}, fallbackAlertsCap)
	s.fallback.mu.Unlock()
	return nil
}

// SaveCSIBlob persists complete calibration/RED CSI dumps in the operational database.
func (s *Store) SaveCSIBlob(ctx context.Context, rec CSIBlobWriteRecord) error {
	cols, err := s.tableCols(ctx, "csi_blobs")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "reason", "byte_len", "blob") {
		if len(rec.Blob) == 0 {
			return errors.New("store: empty CSI dump")
		}
		return s.writeNowOrEnqueue(ctx, Exec{
			Query: `INSERT INTO csi_blobs(ts_us,crew_id,reason,byte_len,blob) VALUES (?,?,?,?,?)`,
			Args:  []any{rec.TsUs, nullableCrew(rec.CrewID), rec.Reason, len(rec.Blob), rec.Blob},
		}, false)
	}
	if s.operational {
		return s.schemaError("csi_blobs", err)
	}
	s.fallback.mu.Lock()
	s.fallback.blobs = appendBounded(s.fallback.blobs, rec, 64)
	s.fallback.mu.Unlock()
	return nil
}

// Summary24h builds a compact 24h clinical summary for CHAT_CORRELATE_REQ.
func (s *Store) Summary24h(ctx context.Context, crewID string) (string, error) {
	nowUs := time.Now().UnixMicro()
	cutoff := nowUs - int64(24*time.Hour/time.Microsecond)

	if s.operational {
		var n int
		var avgHR, avgSpO2, maxCO2 sql.NullFloat64
		if err := s.readerDB.QueryRowContext(ctx,
			`SELECT COUNT(1), AVG(heart_rate_bpm), AVG(spo2_pct), MAX(co2_ppm)
			 FROM telemetry_timeseries WHERE crew_id=? AND ts_us>=?`,
			crewID, cutoff,
		).Scan(&n, &avgHR, &avgSpO2, &maxCO2); err != nil {
			return "", s.schemaError("telemetry_timeseries", err)
		}

		var targetKcal, targetWater sql.NullFloat64
		var avgKcal7d, avgWater7d, deepSleep3d, hrvDelta, rad30d sql.NullFloat64
		err := s.readerDB.QueryRowContext(ctx, `
			SELECT cp.target_kcal_day, cp.target_water_ml_day,
			       w.energy_7d_avg_kcal, w.water_7d_avg_ml,
			       w.deep_sleep_3d_avg_h, w.hrv_delta_7d_vs_30d_ms, w.radiation_30d_sum_msv
			FROM crew_profiles cp
			LEFT JOIN v_crew_longitudinal_windows w ON w.crew_id = cp.crew_id
			WHERE cp.crew_id=?`, crewID,
		).Scan(&targetKcal, &targetWater, &avgKcal7d, &avgWater7d, &deepSleep3d, &hrvDelta, &rad30d)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return "", s.schemaError("v_crew_longitudinal_windows", err)
		}

		var eva72h, spe72h, ex2h int
		if err := s.readerDB.QueryRowContext(ctx, `
			SELECT
				COUNT(CASE WHEN event_type='EVA' AND COALESCE(end_us, ts_us) >= ? - CAST(lookback_hours * 3600000000 AS INTEGER) THEN 1 END),
				COUNT(CASE WHEN event_type='RADIATION_SPE_ALERT' AND COALESCE(end_us, ts_us) >= ? - CAST(lookback_hours * 3600000000 AS INTEGER) THEN 1 END),
				COUNT(CASE WHEN event_type IN ('EXERCISE_ARED','EXERCISE_AEROBIC') AND COALESCE(end_us, ts_us) >= ? - CAST(lookback_hours * 3600000000 AS INTEGER) THEN 1 END)
			FROM mission_context_events
			WHERE (crew_id=? OR crew_id IS NULL) AND ts_us <= ?`,
			nowUs, nowUs, nowUs, crewID, nowUs,
		).Scan(&eva72h, &spe72h, &ex2h); err != nil {
			return "", s.schemaError("mission_context_events", err)
		}

		var alertsY, alertsR int
		if err := s.readerDB.QueryRowContext(ctx, `
			SELECT COALESCE(SUM(CASE WHEN severity='YELLOW' THEN 1 ELSE 0 END), 0),
			       COALESCE(SUM(CASE WHEN severity='RED' THEN 1 ELSE 0 END), 0)
			FROM alerts_audit
			WHERE (crew_id=? OR crew_id IS NULL) AND ts_us>=?`,
			crewID, cutoff,
		).Scan(&alertsY, &alertsR); err != nil {
			return "", s.schemaError("alerts_audit", err)
		}

		var abnExams int
		if err := s.readerDB.QueryRowContext(ctx,
			`SELECT COUNT(1) FROM self_exams WHERE crew_id=? AND ts_us>=? AND abnormal_flag=1`,
			crewID, cutoff,
		).Scan(&abnExams); err != nil {
			return "", s.schemaError("self_exams", err)
		}

		deficitKcal := "na"
		if targetKcal.Valid && avgKcal7d.Valid {
			deficitKcal = fmt.Sprintf("%.0f", targetKcal.Float64-avgKcal7d.Float64)
		}
		deficitWater := "na"
		if targetWater.Valid && avgWater7d.Valid {
			deficitWater = fmt.Sprintf("%.0f", targetWater.Float64-avgWater7d.Float64)
		}
		out := fmt.Sprintf(
			"24h samples=%d hr=%.1f spo2=%.1f co2=%.0f | eva_72h=%d spe_72h=%d ex_2h=%d | alerts_y=%d alerts_r=%d abn_exams=%d | deficit_kcal_7d=%s deficit_water_7d=%s rad_30d=%.2f",
			n, avgHR.Float64, avgSpO2.Float64, maxCO2.Float64,
			eva72h, spe72h, ex2h, alertsY, alertsR, abnExams,
			deficitKcal, deficitWater, rad30d.Float64,
		)
		if len(out) > 600 {
			out = out[:600]
		}
		return out, nil
	}

	cols, err := s.tableCols(ctx, "telemetry_timeseries")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "heart_rate_bpm", "co2_ppm") {
		var n int
		var avgHR, avgSpO2, maxCO2 sql.NullFloat64
		q := `SELECT COUNT(1), AVG(heart_rate_bpm), AVG(spo2_pct), MAX(co2_ppm)
		      FROM telemetry_timeseries WHERE crew_id=? AND ts_us>=?`
		if err := s.readerDB.QueryRowContext(ctx, q, crewID, cutoff).Scan(&n, &avgHR, &avgSpO2, &maxCO2); err != nil {
			return "", err
		}
		if n == 0 {
			return "No 24h telemetry recorded yet.", nil
		}
		return fmt.Sprintf("24h samples=%d avg_hr=%.1f bpm avg_spo2=%.1f%% max_co2=%.0f ppm",
			n, avgHR.Float64, avgSpO2.Float64, maxCO2.Float64), nil
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	var n int
	var sumHR, sumSpO2, maxCO2 float64
	for _, r := range s.fallback.timeseries {
		if r.TsUs < cutoff {
			continue
		}
		if r.CrewID != nil && *r.CrewID != crewID {
			continue
		}
		n++
		sumHR += r.Vitals.HeartRateBpm
		sumSpO2 += r.Vitals.SpO2Pct
		if r.Environment.CO2Ppm > maxCO2 {
			maxCO2 = r.Environment.CO2Ppm
		}
	}
	if n == 0 {
		return "No 24h telemetry recorded yet.", nil
	}
	return fmt.Sprintf("24h samples=%d avg_hr=%.1f bpm avg_spo2=%.1f%% max_co2=%.0f ppm",
		n, sumHR/float64(n), sumSpO2/float64(n), maxCO2), nil
}

// RecentChat returns the most recent `limit` chat messages for crewID in chronological order.
func (s *Store) RecentChat(ctx context.Context, crewID string, limit int) ([]contracts.ChatMessage, error) {
	if limit <= 0 {
		limit = 10
	}
	cols, err := s.tableCols(ctx, "chat_messages")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "role", "content") {
		rows, err := s.readerDB.QueryContext(ctx,
			`SELECT ts_us, role, content FROM chat_messages WHERE crew_id=? ORDER BY ts_us DESC LIMIT ?`,
			crewID, limit)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		var rev []contracts.ChatMessage
		for rows.Next() {
			var m contracts.ChatMessage
			if err := rows.Scan(&m.SentAt, &m.Role, &m.Content); err != nil {
				return nil, err
			}
			rev = append(rev, m)
		}
		if err := rows.Err(); err != nil {
			return nil, err
		}
		for i, j := 0, len(rev)-1; i < j; i, j = i+1, j-1 {
			rev[i], rev[j] = rev[j], rev[i]
		}
		return rev, nil
	}

	if s.operational {
		return nil, s.schemaError("chat_messages", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	var matched []contracts.ChatMessage
	for _, entry := range s.fallback.chats {
		if entry.CrewID == crewID {
			matched = append(matched, entry.Msg)
		}
	}
	if len(matched) > limit {
		matched = matched[len(matched)-limit:]
	}
	out := make([]contracts.ChatMessage, len(matched))
	copy(out, matched)
	return out, nil
}

// QueryTimeseries returns bucket-decimated telemetry for crewID in [fromUs, toUs].
func (s *Store) QueryTimeseries(ctx context.Context, crewID string, metric string, fromUs, toUs int64, bucketSec int) (contracts.TimeseriesResponse, error) {
	if toUs <= 0 {
		toUs = time.Now().UnixMicro()
	}
	if fromUs <= 0 {
		fromUs = toUs - int64(24*time.Hour/time.Microsecond)
	}
	if bucketSec <= 0 {
		bucketSec = 1
	}
	bucketUs := int64(bucketSec) * 1_000_000

	resp := contracts.TimeseriesResponse{
		CrewID:  crewID,
		StartUs: fromUs,
		EndUs:   toUs,
		Buckets: []contracts.TelemetryBucket{},
	}

	cols, err := s.tableCols(ctx, "telemetry_timeseries")
	if err == nil && hasCols(cols, "ts_us", "crew_id", "heart_rate_bpm", "co2_ppm") {
		q := `SELECT (ts_us / ?) * ? AS b_ts,
		             COALESCE(AVG(heart_rate_bpm),0), COALESCE(AVG(hrv_ms),0), COALESCE(AVG(resp_rate_bpm),0),
		             COALESCE(AVG(spo2_pct),0), COALESCE(AVG(confidence),0),
		             COALESCE(AVG(co2_ppm),0), COALESCE(AVG(temp_c),0), COALESCE(AVG(humidity_pct),0), COALESCE(AVG(pressure_hpa),0)
		      FROM telemetry_timeseries
		      WHERE crew_id=? AND ts_us>=? AND ts_us<=?
		      GROUP BY (ts_us / ?)
		      ORDER BY b_ts ASC`
		rows, err := s.readerDB.QueryContext(ctx, q, bucketUs, bucketUs, crewID, fromUs, toUs, bucketUs)
		if err != nil {
			return resp, err
		}
		defer rows.Close()
		for rows.Next() {
			var b contracts.TelemetryBucket
			if err := rows.Scan(
				&b.TsUs,
				&b.Vitals.HeartRateBpm, &b.Vitals.HRVMs, &b.Vitals.RespRateBpm,
				&b.Vitals.SpO2Pct, &b.Vitals.ConfidenceScore,
				&b.Environment.CO2Ppm, &b.Environment.TempC, &b.Environment.HumidityPct, &b.Environment.PressureHpa,
			); err != nil {
				return resp, err
			}
			resp.Buckets = append(resp.Buckets, b)
		}
		return resp, rows.Err()
	}

	if s.operational {
		return resp, s.schemaError("telemetry_timeseries", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	type acc struct {
		n     float64
		hr    float64
		hrv   float64
		rr    float64
		spo2  float64
		conf  float64
		co2   float64
		temp  float64
		rh    float64
		press float64
	}
	groups := make(map[int64]*acc)
	for _, r := range s.fallback.timeseries {
		if r.TsUs < fromUs || r.TsUs > toUs {
			continue
		}
		if crewID != "" && r.CrewID != nil && *r.CrewID != crewID {
			continue
		}
		key := (r.TsUs / bucketUs) * bucketUs
		a := groups[key]
		if a == nil {
			a = &acc{}
			groups[key] = a
		}
		a.n++
		a.hr += r.Vitals.HeartRateBpm
		a.hrv += r.Vitals.HRVMs
		a.rr += r.Vitals.RespRateBpm
		a.spo2 += r.Vitals.SpO2Pct
		a.conf += r.Vitals.ConfidenceScore
		a.co2 += r.Environment.CO2Ppm
		a.temp += r.Environment.TempC
		a.rh += r.Environment.HumidityPct
		a.press += r.Environment.PressureHpa
	}
	keys := make([]int64, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	for _, k := range keys {
		a := groups[k]
		resp.Buckets = append(resp.Buckets, contracts.TelemetryBucket{
			TsUs: k,
			Vitals: contracts.VitalsData{
				HeartRateBpm:    a.hr / a.n,
				HRVMs:           a.hrv / a.n,
				RespRateBpm:     a.rr / a.n,
				SpO2Pct:         a.spo2 / a.n,
				ConfidenceScore: a.conf / a.n,
			},
			Environment: contracts.EnvironmentData{
				CO2Ppm:      a.co2 / a.n,
				TempC:       a.temp / a.n,
				HumidityPct: a.rh / a.n,
				PressureHpa: a.press / a.n,
			},
		})
	}
	return resp, nil
}

// GetProtocol fetches a clinical protocol by ID from M1 protocols table or offline defaults.
func (s *Store) GetProtocol(ctx context.Context, id string) (contracts.ProtocolDTO, error) {
	cols, err := s.tableCols(ctx, "protocols")
	if err == nil && hasCols(cols, "protocol_id", "name") {
		var p contracts.ProtocolDTO
		var subsJSON, stepsJSON string
		q := `SELECT protocol_id, name, COALESCE(subsystems_json,'[]'), COALESCE(description,''), COALESCE(steps_json,'[]')
		      FROM protocols WHERE protocol_id=?`
		if !cols["subsystems_json"] || !cols["steps_json"] {
			q = `SELECT protocol_id, name, '[]', COALESCE(description,''), '[]' FROM protocols WHERE protocol_id=?`
		}
		if err := s.readerDB.QueryRowContext(ctx, q, id).Scan(&p.ProtocolID, &p.Name, &subsJSON, &p.Description, &stepsJSON); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return contracts.ProtocolDTO{}, ErrNotFound
			}
			return contracts.ProtocolDTO{}, err
		}
		_ = json.Unmarshal([]byte(subsJSON), &p.Subsystems)
		_ = json.Unmarshal([]byte(stepsJSON), &p.Steps)
		if hasCols(cols, "duration_s", "materials_json", "rich_steps_json", "result_schema_json", "linked_risks_json") {
			var duration sql.NullInt64
			var materials, rich, schema, risks string
			if err := s.readerDB.QueryRowContext(ctx, `SELECT duration_s,materials_json,rich_steps_json,result_schema_json,linked_risks_json FROM protocols WHERE protocol_id=?`, id).Scan(&duration, &materials, &rich, &schema, &risks); err != nil {
				return p, err
			}
			if duration.Valid {
				p.DurationS = &duration.Int64
			}
			if err := json.Unmarshal([]byte(materials), &p.Materials); err != nil {
				return p, err
			}
			if err := json.Unmarshal([]byte(risks), &p.LinkedRisks); err != nil {
				return p, err
			}
			p.RichSteps = json.RawMessage(rich)
			p.ResultSchema = json.RawMessage(schema)
		}
		return p, nil
	}

	if s.operational {
		return contracts.ProtocolDTO{}, s.schemaError("protocols", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	p, ok := s.fallback.protocols[id]
	if !ok {
		return contracts.ProtocolDTO{}, ErrNotFound
	}
	return p, nil
}

// ListAlerts returns newest alerts (up to limit) from M1 alerts_audit or fallback memory.
func (s *Store) ListAlerts(ctx context.Context, limit int) ([]contracts.AlertRecord, error) {
	if limit <= 0 {
		limit = 50
	}
	cols, err := s.tableCols(ctx, "alerts_audit")
	if err == nil && hasCols(cols, "alert_id", "ts_us", "subsystem", "severity", "message") {
		rows, err := s.readerDB.QueryContext(ctx,
			`SELECT alert_id, ts_us, crew_id, subsystem, severity, message, COALESCE(countermeasure,''), COALESCE(escalation,'LOCAL'), COALESCE(handled,0)
			 FROM alerts_audit ORDER BY ts_us DESC LIMIT ?`, limit)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := []contracts.AlertRecord{}
		for rows.Next() {
			var r contracts.AlertRecord
			var cid sql.NullString
			var handledInt int
			if err := rows.Scan(&r.AlertID, &r.TsUs, &cid, &r.Subsystem, &r.Severity, &r.Message, &r.Countermeasure, &r.Escalation, &handledInt); err != nil {
				return nil, err
			}
			if cid.Valid && cid.String != "" {
				c := cid.String
				r.CrewID = &c
			}
			r.Handled = handledInt != 0
			out = append(out, r)
		}
		return out, rows.Err()
	}

	if s.operational {
		return nil, s.schemaError("alerts_audit", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	n := len(s.fallback.alerts)
	if n == 0 {
		return []contracts.AlertRecord{}, nil
	}
	if limit > n {
		limit = n
	}
	out := make([]contracts.AlertRecord, 0, limit)
	for i := n - 1; i >= n-limit; i-- {
		out = append(out, s.fallback.alerts[i])
	}
	return out, nil
}

// ListOutbox returns store-and-forward messages from M1 store_and_forward_outbox or fallback memory.
func (s *Store) ListOutbox(ctx context.Context) ([]contracts.OutboxRecord, error) {
	cols, err := s.tableCols(ctx, "store_and_forward_outbox")
	if err == nil && hasCols(cols, "outbox_id", "ts_us", "subsystem", "severity", "message") {
		rows, err := s.readerDB.QueryContext(ctx,
			`SELECT outbox_id, ts_us, subsystem, severity, message, COALESCE(destination,''), COALESCE(sent,0)
			 FROM store_and_forward_outbox ORDER BY ts_us DESC`)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := []contracts.OutboxRecord{}
		for rows.Next() {
			var r contracts.OutboxRecord
			var sentInt int
			if err := rows.Scan(&r.OutboxID, &r.TsUs, &r.Subsystem, &r.Severity, &r.Message, &r.Destination, &sentInt); err != nil {
				return nil, err
			}
			r.Sent = sentInt != 0
			out = append(out, r)
		}
		return out, rows.Err()
	}

	if s.operational {
		return nil, s.schemaError("store_and_forward_outbox", err)
	}

	s.fallback.mu.RLock()
	defer s.fallback.mu.RUnlock()
	n := len(s.fallback.outbox)
	out := make([]contracts.OutboxRecord, 0, n)
	for i := n - 1; i >= 0; i-- {
		out = append(out, s.fallback.outbox[i])
	}
	return out, nil
}
