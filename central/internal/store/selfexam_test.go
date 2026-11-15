package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

func TestSelfExamNormalization(t *testing.T) {
	ids := map[string]string{
		"AMSLER": "amsler_grid", "amsler": "amsler_grid", "amsler_grid": "amsler_grid",
		"Blood Pressure": "blood_pressure", "ONSD": "ultrasound_onsd", "unknown_exam": "",
	}
	for in, want := range ids {
		if got := SelfExamProtocolID(in); got != want {
			t.Fatalf("SelfExamProtocolID(%q)=%q want %q", in, got, want)
		}
	}
	abn := map[string]bool{
		"metamorphopsia": true, "altered": true, "normal": false, "OK": false, "": false,
		`{"abnormal_flag":true}`: true, `{"abnormal_flag":false}`: false, `{"abnormal_flag":1}`: true,
		`{"onsd_mm":5.6}`: false, `{"abnormal_flag":"normal"}`: false,
	}
	for in, want := range abn {
		if got := SelfExamAbnormal(in); got != want {
			t.Fatalf("SelfExamAbnormal(%q)=%v want %v", in, got, want)
		}
	}
}

func TestOperationalSelfExamTimeseriesAndDataClass(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "t13.db")
	s, err := New(Config{
		DBPath:             dbPath,
		MigrationsDir:      filepath.Join("..", "..", "..", "database", "migrations"),
		RequireOperational: true,
		DataClass:          DataClassSynthetic,
	}, Deps{})
	if err != nil {
		t.Fatal(err)
	}
	defer s.shutdown()
	ctx := context.Background()
	crew := "crew_001"
	now := time.Now().UnixMicro()

	// SELF_EXAM: string result from WS/sim ("AMSLER" + "metamorphopsia").
	if err := s.SaveSelfExam(ctx, crew, contracts.SelfExamPayload{ExamType: "AMSLER", Result: "metamorphopsia", Observations: "UL"}, now); err != nil {
		t.Fatalf("SaveSelfExam string: %v", err)
	}
	if err := s.SaveSelfExam(ctx, crew, contracts.SelfExamPayload{ExamType: "unknown_exam", Result: "normal"}, now+1); err != nil {
		t.Fatalf("SaveSelfExam unknown: %v", err)
	}

	// Telemetry: two rows in one bucket, second without SpO2 (NULL kept).
	for i, spo2 := range []any{98.0, nil} {
		_, err := s.writerDB.Exec(`INSERT INTO telemetry_timeseries(ts_us,crew_id,mission_mode,heart_rate_bpm,spo2_pct,co2_ppm,data_class) VALUES (?,?,?,?,?,?,?)`,
			now-int64(2-i)*1000, crew, "MODE_REST_VITALS", 60.0+float64(i)*10, spo2, nil, "REAL")
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := s.SaveTelemetry1Hz(ctx, Telemetry1HzRecord{TsUs: now - 500, CrewID: &crew, MissionMode: contracts.ModeRestVitals,
		Vitals: contracts.VitalsData{HeartRateBpm: 70, SpO2Pct: 97}, Environment: contracts.EnvironmentData{CO2Ppm: 800}}); err != nil {
		t.Fatal(err)
	}
	if err := s.SavePeripheral1Hz(ctx, now, []PeripheralReadingRecord{{CrewID: &crew, Type: contracts.PeripheralSCD40, Value: 800, Unit: "ppm", TsUs: now}}); err != nil {
		t.Fatal(err)
	}
	if err := s.Flush(ctx); err != nil {
		t.Fatal(err)
	}

	var pid sql.NullString
	var abnormal int
	var payload string
	if err := s.readerDB.QueryRow(`SELECT protocol_id, abnormal_flag, payload_json FROM self_exams WHERE crew_id=? AND ts_us=?`, crew, now).Scan(&pid, &abnormal, &payload); err != nil {
		t.Fatal(err)
	}
	if pid.String != "amsler_grid" || abnormal != 1 {
		t.Fatalf("self_exam protocol_id=%q abnormal=%d, want amsler_grid/1", pid.String, abnormal)
	}
	var doc map[string]any
	if err := json.Unmarshal([]byte(payload), &doc); err != nil || doc["protocol_id"] != "amsler_grid" || doc["abnormal_flag"] != true {
		t.Fatalf("payload_json=%s err=%v", payload, err)
	}
	if err := s.readerDB.QueryRow(`SELECT protocol_id, abnormal_flag FROM self_exams WHERE crew_id=? AND ts_us=?`, crew, now+1).Scan(&pid, &abnormal); err != nil {
		t.Fatal(err)
	}
	if pid.Valid || abnormal != 0 {
		t.Fatalf("unknown exam protocol_id=%v abnormal=%d, want NULL/0", pid, abnormal)
	}

	// data_class='SYNTHETIC' propagated on Store writes.
	var dc string
	if err := s.readerDB.QueryRow(`SELECT data_class FROM telemetry_timeseries WHERE ts_us=?`, now-500).Scan(&dc); err != nil || dc != DataClassSynthetic {
		t.Fatalf("telemetry data_class=%q err=%v", dc, err)
	}
	if err := s.readerDB.QueryRow(`SELECT data_class FROM peripheral_readings WHERE ts_us=?`, now).Scan(&dc); err != nil || dc != DataClassSynthetic {
		t.Fatalf("peripheral data_class=%q err=%v", dc, err)
	}

	// QueryTimeseries: NULL preserved (CO2 absent in raw rows only -> AVG ignores NULL).
	all, err := s.QueryTimeseries(ctx, crew, "", now-10_000, now, 60)
	if err != nil || len(all.Buckets) != 1 {
		t.Fatalf("QueryTimeseries all: %+v err=%v", all, err)
	}
	b := all.Buckets[0]
	if b.Vitals.HRVMs != nil || b.Environment.TempC != nil {
		t.Fatalf("NULL metrics must stay nil, got hrv=%v temp=%v", b.Vitals.HRVMs, b.Environment.TempC)
	}
	if b.Vitals.SpO2Pct == nil || *b.Vitals.SpO2Pct != 97.5 {
		t.Fatalf("SpO2 AVG must ignore NULL rows: %v", b.Vitals.SpO2Pct)
	}

	// metric filter: only that metric populated.
	hr, err := s.QueryTimeseries(ctx, crew, "heart_rate_bpm", now-10_000, now, 60)
	if err != nil || len(hr.Buckets) != 1 || hr.Metric != "heart_rate_bpm" {
		t.Fatalf("QueryTimeseries metric: %+v err=%v", hr, err)
	}
	hb := hr.Buckets[0]
	if hb.Vitals.HeartRateBpm == nil || hb.Vitals.SpO2Pct != nil || hb.Environment.CO2Ppm != nil {
		t.Fatalf("metric filter leaked other metrics: %+v", hb)
	}
	co2, err := s.QueryTimeseries(ctx, crew, "co2_ppm", now-10_000, now, 60)
	if err != nil || len(co2.Buckets) != 1 || *co2.Buckets[0].Environment.CO2Ppm != 800 {
		t.Fatalf("co2 metric bucket must use only non-NULL rows: %+v err=%v", co2, err)
	}
	if _, err := s.QueryTimeseries(ctx, crew, "co2_ppm; DROP TABLE x", 0, now, 60); !errors.Is(err, ErrInvalidMetric) {
		t.Fatalf("expected ErrInvalidMetric, got %v", err)
	}
}

func TestStoreRejectsInvalidDataClass(t *testing.T) {
	if _, err := New(Config{DBPath: filepath.Join(t.TempDir(), "x.db"), DataClass: "FAKE"}, Deps{}); err == nil {
		t.Fatal("expected invalid DataClass error")
	}
}
