package store

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

func operationalStore(t *testing.T, dbPath string) *Store {
	t.Helper()
	s, err := New(Config{DBPath: dbPath, MigrationsDir: filepath.Join("..", "..", "..", "database", "migrations"), RequireOperational: true}, Deps{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err != nil {
		t.Fatal(err)
	}
	if !s.operational || s.fallback != nil {
		t.Fatal("operational store must not allocate fallback data")
	}
	return s
}

func TestOperationalMigrationsPersistClinicalDataAcrossRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "operational.db")
	s := operationalStore(t, path)
	defer func() { _ = s.shutdown() }()
	ctx := context.Background()
	crew := "crew_001"
	if err := s.SaveAudit(ctx, &crew, "CREW_CHANGED", `{"source":"test"}`, 100); err != nil {
		t.Fatal(err)
	}
	blob := []byte{1, 2, 3, 4}
	if err := s.SaveCSIBlob(ctx, CSIBlobWriteRecord{TsUs: 101, CrewID: &crew, Reason: "calibration", Blob: blob}); err != nil {
		t.Fatal(err)
	}
	if err := s.SavePeripheral1Hz(ctx, 102, []PeripheralReadingRecord{{CrewID: &crew, NodeID: 1, Type: contracts.PeripheralMAX30102, Value: 98, Unit: "%", TsUs: 102}}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveSelfExam(ctx, crew, contracts.SelfExamPayload{ExamType: "amsler_grid", Result: `{"abnormal_flag":true}`}, 103); err != nil {
		t.Fatal(err)
	}
	response := contracts.ChatCorrelateRespPayload{Text: "Review context", Differentials: []string{"SANS"}, Evidence: []string{"Amsler"}, DisambiguationQuestion: "New visual change?", Escalation: contracts.EscalationCrew}
	if err := s.SaveChatExchange(ctx, crew, contracts.ChatMsgPayload{Text: "vision"}, response, 104); err != nil {
		t.Fatal(err)
	}
	protocol, err := s.GetProtocol(ctx, "amsler_grid")
	if err != nil || len(protocol.RichSteps) == 0 || len(protocol.Materials) == 0 || protocol.DurationS == nil {
		t.Fatalf("rich protocol: %+v, %v", protocol, err)
	}
	if err := s.shutdown(); err != nil {
		t.Fatal(err)
	}
	s = operationalStore(t, path)
	for table, want := range map[string]int{"audit_log": 1, "csi_blobs": 1, "peripheral_readings": 1, "self_exams": 1, "chat_messages": 2, "schema_version": 6, "causal_conditions": 26} {
		var count int
		if err := s.readerDB.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&count); err != nil || count != want {
			t.Fatalf("%s count=%d want=%d err=%v", table, count, want, err)
		}
	}
	var stored []byte
	var size int
	if err := s.readerDB.QueryRow("SELECT byte_len,blob FROM csi_blobs").Scan(&size, &stored); err != nil || size != len(blob) || string(stored) != string(blob) {
		t.Fatalf("CSI payload was not preserved: %v", err)
	}
	var linked string
	if err := s.readerDB.QueryRow("SELECT crew_id FROM peripheral_readings").Scan(&linked); err != nil || linked != crew {
		t.Fatalf("crew association: %q %v", linked, err)
	}
	var protocolID, payload string
	var abnormal int
	if err := s.readerDB.QueryRow("SELECT protocol_id,payload_json,abnormal_flag FROM self_exams").Scan(&protocolID, &payload, &abnormal); err != nil || protocolID != "amsler_grid" || abnormal != 1 || !json.Valid([]byte(payload)) {
		t.Fatalf("self exam metadata: %s %d %s %v", protocolID, abnormal, payload, err)
	}
	var metadata string
	if err := s.readerDB.QueryRow("SELECT metadata_json FROM chat_messages WHERE role='assistant'").Scan(&metadata); err != nil {
		t.Fatal(err)
	}
	var decoded contracts.ChatCorrelateRespPayload
	if err := json.Unmarshal([]byte(metadata), &decoded); err != nil || len(decoded.Differentials) != 1 || decoded.DisambiguationQuestion != response.DisambiguationQuestion {
		t.Fatalf("AI metadata lost: %s %v", metadata, err)
	}
}

func TestOperationalSchemaFailureNeverFallsBackToRAM(t *testing.T) {
	s := operationalStore(t, filepath.Join(t.TempDir(), "operational.db"))
	defer s.shutdown()
	if _, err := s.writerDB.Exec("ALTER TABLE telemetry_timeseries RENAME COLUMN heart_rate_bpm TO removed_hr"); err != nil {
		t.Fatal(err)
	}
	err := s.SaveTelemetry1Hz(context.Background(), Telemetry1HzRecord{TsUs: 1, MissionMode: contracts.ModeRestVitals})
	if err == nil {
		t.Fatal("missing operational columns must be reported")
	}
	if _, err := s.writerDB.Exec("DROP TABLE audit_log"); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveAudit(context.Background(), nil, "event", "details", 1); err == nil {
		t.Fatal("missing audit table must be reported")
	}
}

func TestProductionRequiresOperationalMigrations(t *testing.T) {
	s, err := New(Config{DBPath: filepath.Join(t.TempDir(), "empty.db"), RequireOperational: true}, Deps{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	if err == nil {
		s.shutdown()
		t.Fatal("production cannot use schema-less fallback mode")
	}
}

func TestOperationalV2WritersSessionAndBaseline(t *testing.T) {
	s := operationalStore(t, filepath.Join(t.TempDir(), "v2.db"))
	defer s.shutdown()
	ctx := context.Background()
	now := time.Now().UTC().UnixMicro()
	crew := "crew_001"

	kcal, water, mass := 1900.0, 1500.0, 74.2
	if err := s.SaveNutritionLog(ctx, NutritionLogRecord{
		LogID: "nut-1", CrewID: crew, TsUs: now, WaterMl: &water, EnergyKcal: &kcal, BodyMassKg: &mass, SourceNote: "meal-1", DataClass: "REAL",
	}); err != nil {
		t.Fatalf("SaveNutritionLog: %v", err)
	}
	endUs := now + 3600_000_000
	if err := s.SaveMissionEvent(ctx, MissionEventRecord{
		EventID: "evt-1", CrewID: &crew, EventType: "EVA", TsUs: now, EndUs: &endUs, Severity: "INFO", DataClass: "REAL",
	}); err != nil {
		t.Fatalf("SaveMissionEvent: %v", err)
	}
	day := time.UnixMicro(now).UTC().Format("2006-01-02")
	if err := s.SaveCircadianSchedule(ctx, CircadianScheduleRecord{
		ScheduleID: "circ-1", CrewID: crew, DayUTC: day, SleepStartUs: now, SleepEndUs: now + 8*3600_000_000, DataClass: "REAL",
	}); err != nil {
		t.Fatalf("SaveCircadianSchedule: %v", err)
	}

	if err := s.StartChatSession(ctx, "sess-explicit-1", crew, now); err != nil {
		t.Fatalf("StartChatSession: %v", err)
	}
	if err := s.SaveChatExchange(ctx, crew, contracts.ChatMsgPayload{Text: "hello"}, contracts.ChatCorrelateRespPayload{Text: "hi", Escalation: contracts.EscalationLocal}, now+10); err != nil {
		t.Fatalf("SaveChatExchange explicit: %v", err)
	}
	var gotSess string
	if err := s.readerDB.QueryRow(`SELECT COALESCE(session_id,'') FROM chat_messages WHERE ts_us=?`, now+10).Scan(&gotSess); err != nil || gotSess != "sess-explicit-1" {
		t.Fatalf("chat_messages.session_id = %q, want sess-explicit-1, err=%v", gotSess, err)
	}
	if err := s.EndChatSession(ctx, "sess-explicit-1", now+20); err != nil {
		t.Fatalf("EndChatSession: %v", err)
	}
	if err := s.SaveChatExchange(ctx, crew, contracts.ChatMsgPayload{Text: "next"}, contracts.ChatCorrelateRespPayload{Text: "ok", Escalation: contracts.EscalationLocal}, now+30); err != nil {
		t.Fatalf("SaveChatExchange auto session: %v", err)
	}
	var autoSess string
	if err := s.readerDB.QueryRow(`SELECT COALESCE(session_id,'') FROM chat_messages WHERE ts_us=?`, now+30).Scan(&autoSess); err != nil || autoSess == "" || autoSess == "sess-explicit-1" {
		t.Fatalf("auto session_id = %q, want non-empty new session, err=%v", autoSess, err)
	}

	mean := make([]float64, 64)
	std := make([]float64, 64)
	for i := range std {
		std[i] = 1.0
	}
	modelPath := "models/profiles/updated_crew_001.onnx"
	rawBaseline, _ := json.Marshal(map[string]any{
		"crew_id": crew, "mean": mean, "std": std, "threshold": 2.5, "sample_count": 200,
		"model_path": modelPath, "feature_schema_id": "EDGESPACE_DSP64_V1",
		"calibration_status": "READY", "clean_window_ratio": 0.95,
		"covered_postures": []string{"supine", "seated"}, "step_id": "step-final",
		"per_posture_stats": map[string]any{"supine": map[string]any{"sample_count": 3, "hr_mean": 58.0}},
	})
	if err := s.SaveBaselineUpdate(ctx, crew, rawBaseline, now+40); err != nil {
		t.Fatalf("SaveBaselineUpdate: %v", err)
	}
	prof, err := s.GetCrewProfile(ctx, crew)
	if err != nil || prof.BaselinePath != modelPath || prof.Profile.BiologicalSex == nil || prof.Profile.TargetKcalDay == nil {
		t.Fatalf("GetCrewProfile after baseline update: %+v err=%v", prof, err)
	}
	var cpPath string
	if err := s.readerDB.QueryRow(`SELECT baseline_path FROM crew_profiles WHERE crew_id=?`, crew).Scan(&cpPath); err != nil || cpPath != modelPath {
		t.Fatalf("crew_profiles.baseline_path = %q want %q err=%v", cpPath, modelPath, err)
	}
	list, err := s.ListCrew(ctx)
	if err != nil {
		t.Fatalf("ListCrew: %v", err)
	}
	for _, c := range list {
		// crew_003 has SYNTHETIC_SEED but no baseline_path -> pending calibration.
		wantRequired := c.CrewID == "crew_003" && c.CrewID != crew
		if c.CalibrationRequired != wantRequired {
			t.Fatalf("crew %s calibration_required=%v, want %v: %+v", c.CrewID, c.CalibrationRequired, wantRequired, c)
		}
		rec, err := s.GetCrewProfile(ctx, c.CrewID)
		if err != nil {
			t.Fatalf("GetCrewProfile(%s): %v", c.CrewID, err)
		}
		if rec.CalibrationRequired != c.CalibrationRequired {
			t.Fatalf("crew %s: profile calibration_required=%v != list %v", c.CrewID, rec.CalibrationRequired, c.CalibrationRequired)
		}
	}

	// per_posture_stats_json persisted from baseline_update.
	var pps string
	if err := s.readerDB.QueryRow(`SELECT per_posture_stats_json FROM individual_baselines WHERE crew_id=? AND is_active=1`, crew).Scan(&pps); err != nil {
		t.Fatalf("read per_posture_stats_json: %v", err)
	}
	if !strings.Contains(pps, `"supine"`) {
		t.Fatalf("per_posture_stats_json = %s, want supine stats", pps)
	}
	var badRaw map[string]any
	_ = json.Unmarshal(rawBaseline, &badRaw)
	badRaw["per_posture_stats"] = []int{1}
	bad, _ := json.Marshal(badRaw)
	if err := s.SaveBaselineUpdate(ctx, crew, bad, now+50); err == nil || !strings.Contains(err.Error(), "per_posture_stats") {
		t.Fatalf("expected per_posture_stats object error, got %v", err)
	}
}

func TestIsCalibratedSingleRule(t *testing.T) {
	cases := []struct {
		status string
		n      int64
		path   string
		want   bool
	}{
		{CalibrationStatusReady, 10, "", true},
		{CalibrationStatusReady, 0, "x", false},
		{CalibrationStatusSyntheticSeed, 164, "models/profiles/baseline_crew_001.json", true},
		{CalibrationStatusSyntheticSeed, 164, "", false},
		{CalibrationStatusSyntheticSeed, 164, "   ", false},
		{CalibrationStatusCalibrating, 50, "x", false},
		{CalibrationStatusRequired, 50, "x", false},
	}
	for _, c := range cases {
		if got := IsCalibrated(c.status, c.n, c.path); got != c.want {
			t.Fatalf("IsCalibrated(%q,%d,%q)=%v want %v", c.status, c.n, c.path, got, c.want)
		}
	}
}

func TestOperationalRollupDayAndSummary24h(t *testing.T) {
	s := operationalStore(t, filepath.Join(t.TempDir(), "rollup.db"))
	defer s.shutdown()
	ctx := context.Background()
	now := time.Now().UTC()
	nowUs := now.UnixMicro()
	dayUTC := now.Format("2006-01-02")
	shiftHour := (now.Hour() / 8) * 8
	shiftStartUs := time.Date(now.Year(), now.Month(), now.Day(), shiftHour, 0, 0, 0, time.UTC).UnixMicro()
	crew := "crew_001"

	for i := 0; i < 3; i++ {
		if err := s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{
			TsUs:        nowUs - int64(i)*1_000_000,
			CrewID:      &crew,
			MissionMode: contracts.ModeCabinTomography,
			Vitals:      contracts.VitalsData{HeartRateBpm: float64(68 + i), HRVMs: float64(40 + i*5), RespRateBpm: 14, SpO2Pct: 98},
			Environment: contracts.EnvironmentData{CO2Ppm: 800, TempC: 22.5},
		}); err != nil {
			t.Fatalf("SaveTelemetry1Hz: %v", err)
		}
	}
	if err := s.SaveAlertAndOutbox(ctx, AlertWriteRecord{
		AlertID: "al-y-1", TsUs: nowUs - 1000, CrewID: &crew,
		Alert: contracts.AlertEventPayload{Subsystem: contracts.SubsystemRespiratoryAtmosphere, Severity: contracts.SeverityYellow, Message: "y", Escalation: contracts.EscalationCrew},
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveAlertAndOutbox(ctx, AlertWriteRecord{
		AlertID: "al-r-1", TsUs: nowUs - 500, CrewID: &crew, WriteOutbox: true,
		Alert: contracts.AlertEventPayload{Subsystem: contracts.SubsystemRespiratoryAtmosphere, Severity: contracts.SeverityRed, Message: "r", Escalation: contracts.EscalationStoreAndForward},
	}); err != nil {
		t.Fatal(err)
	}

	summaryBefore, err := s.Summary24h(ctx, crew)
	if err != nil {
		t.Fatalf("Summary24h before events: %v", err)
	}
	var seedEva, seedSpe int
	if err := s.readerDB.QueryRow(`SELECT
		COUNT(CASE WHEN event_type='EVA' AND COALESCE(end_us, ts_us) >= ? - CAST(lookback_hours * 3600000000 AS INTEGER) THEN 1 END),
		COUNT(CASE WHEN event_type='RADIATION_SPE_ALERT' AND COALESCE(end_us, ts_us) >= ? - CAST(lookback_hours * 3600000000 AS INTEGER) THEN 1 END)
		FROM mission_context_events WHERE (crew_id=? OR crew_id IS NULL) AND ts_us <= ?`,
		nowUs, nowUs, crew, nowUs).Scan(&seedEva, &seedSpe); err != nil {
		t.Fatal(err)
	}
	_ = summaryBefore

	evaEnd := nowUs - 10*60_000_000
	evaStart := evaEnd - 30*60_000_000
	if err := s.SaveMissionEvent(ctx, MissionEventRecord{
		EventID: "eva-active", CrewID: &crew, EventType: "EVA", TsUs: evaStart, EndUs: &evaEnd, LookbackHours: 72, DetailsJSON: `{"dose_msv":0.4}`, DataClass: "REAL",
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveMissionEvent(ctx, MissionEventRecord{
		EventID: "eva-expired", CrewID: &crew, EventType: "EVA", TsUs: nowUs - 5*3600_000_000, LookbackHours: 1, DataClass: "REAL",
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveMissionEvent(ctx, MissionEventRecord{
		EventID: "spe-active", CrewID: &crew, EventType: "RADIATION_SPE_ALERT", TsUs: nowUs - 12*3600_000_000, LookbackHours: 72, DetailsJSON: `{"dose_msv":1.2}`, DataClass: "REAL",
	}); err != nil {
		t.Fatal(err)
	}
	exEnd := nowUs - 5*60_000_000
	exStart := exEnd - 25*60_000_000
	if err := s.SaveMissionEvent(ctx, MissionEventRecord{
		EventID: "ex-active", CrewID: &crew, EventType: "EXERCISE_ARED", TsUs: exStart, EndUs: &exEnd, LookbackHours: 2, DataClass: "REAL",
	}); err != nil {
		t.Fatal(err)
	}

	kcal, water, mass := 2000.0, 1800.0, 75.0
	if err := s.SaveNutritionLog(ctx, NutritionLogRecord{
		LogID: "nut-day", CrewID: crew, TsUs: nowUs - 2000, EnergyKcal: &kcal, WaterMl: &water, BodyMassKg: &mass, SourceNote: "day", DataClass: "REAL",
	}); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveSelfExam(ctx, crew, contracts.SelfExamPayload{ExamType: "amsler_grid", Result: `{"abnormal_flag":true}`}, nowUs-1500); err != nil {
		t.Fatal(err)
	}

	if err := s.RollupShift(ctx, crew, shiftStartUs); err != nil {
		t.Fatalf("RollupShift: %v", err)
	}
	if err := s.RollupDay(ctx, crew, dayUTC); err != nil {
		t.Fatalf("RollupDay: %v", err)
	}

	var shiftSamples int
	if err := s.readerDB.QueryRow(`SELECT sample_count FROM telemetry_shift_rollups WHERE crew_id=? AND shift_start_us=?`, crew, shiftStartUs).Scan(&shiftSamples); err != nil || shiftSamples != 3 {
		t.Fatalf("shift_rollups sample_count=%d err=%v", shiftSamples, err)
	}
	var daySamples, yCnt, rCnt int
	var kcalTot, waterTot, evaMin, exMin float64
	if err := s.readerDB.QueryRow(`SELECT sample_count, alerts_yellow_count, alerts_red_count, energy_kcal_total, water_ml_total, eva_minutes, exercise_minutes FROM telemetry_daily_rollups WHERE crew_id=? AND day_utc=?`, crew, dayUTC).
		Scan(&daySamples, &yCnt, &rCnt, &kcalTot, &waterTot, &evaMin, &exMin); err != nil {
		t.Fatalf("daily_rollups query: %v", err)
	}
	if daySamples != 3 || yCnt != 1 || rCnt != 1 || kcalTot != 2000 || waterTot != 1800 || evaMin < 29 || exMin < 24 {
		t.Fatalf("unexpected daily_rollups: samples=%d y=%d r=%d kcal=%.1f water=%.1f eva=%.1f ex=%.1f", daySamples, yCnt, rCnt, kcalTot, waterTot, evaMin, exMin)
	}

	summary, err := s.Summary24h(ctx, crew)
	if err != nil {
		t.Fatalf("Summary24h: %v", err)
	}
	if len(summary) > 600 {
		t.Fatalf("Summary24h exceeds 600 bytes: len=%d summary=%q", len(summary), summary)
	}
	if len(summary) > 600 {
		t.Fatalf("Summary24h exceeds 600 bytes: len=%d summary=%q", len(summary), summary)
	}
	wantEva := "eva_72h=" + string(rune('0'+seedEva+1))
	if seedEva+1 >= 10 {
		wantEva = "eva_72h="
	}
	wantSpe := "spe_72h=" + string(rune('0'+seedSpe+1))
	if seedSpe+1 >= 10 {
		wantSpe = "spe_72h="
	}
	for _, want := range []string{wantEva, wantSpe, "ex_2h=1", "alerts_y=1", "alerts_r=1", "abn_exams=1", "deficit_kcal_7d=", "deficit_water_7d="} {
		if !strings.Contains(summary, want) {
			t.Fatalf("Summary24h missing %q: %q", want, summary)
		}
	}
}


