package pipeline

import (
	"fmt"
	"strings"
	"time"

	"edgespace/central/internal/contracts"
)

// DefaultThresholds returns baseline NASA/cabin safety thresholds used when SessionView.Thresholds lacks a metric.
func DefaultThresholds() map[string]contracts.Threshold {
	return map[string]contracts.Threshold{
		"co2_ppm":        {MetricName: "co2_ppm", YellowHigh: 1000, RedHigh: 3500},
		"spo2_pct":       {MetricName: "spo2_pct", YellowLow: 94, RedLow: 90},
		"heart_rate_bpm": {MetricName: "heart_rate_bpm", YellowHigh: 110, RedHigh: 140, YellowLow: 45, RedLow: 38},
		"hrv_ms":         {MetricName: "hrv_ms", YellowLow: 25, RedLow: 15},
		"resp_rate_bpm":  {MetricName: "resp_rate_bpm", YellowHigh: 24, RedHigh: 30, YellowLow: 8, RedLow: 6},
		"temp_c":         {MetricName: "temp_c", YellowHigh: 28, RedHigh: 32, YellowLow: 16, RedLow: 12},
		"humidity_pct":   {MetricName: "humidity_pct", YellowHigh: 75, RedHigh: 85, YellowLow: 25, RedLow: 15},
		"pressure_hpa":   {MetricName: "pressure_hpa", YellowLow: 950, RedLow: 850},
		"anomaly_score":  {MetricName: "anomaly_score", YellowHigh: 0.70, RedHigh: 0.90},
	}
}

type alertDecision struct {
	Alert contracts.AlertEventPayload
}

type selfExamRecord struct {
	Payload    contracts.SelfExamPayload
	ReceivedAt time.Time
}

type clinicalState struct {
	hasCO2       bool
	hasTemp      bool
	hasHumidity  bool
	hasPressure  bool
	hasSpO2      bool
	hasMAXHR     bool
	hasInference bool

	maxHRBpm    float64
	lastInf     contracts.AIInferencePayload
	vitals      contracts.VitalsData
	env         contracts.EnvironmentData
	amslerExam  *selfExamRecord
	cardioExam  *selfExamRecord
	musculoExam *selfExamRecord
	immuneExam  *selfExamRecord
	neuroExam   *selfExamRecord
	prev        [6]contracts.SubsystemState
	defaults    map[string]contracts.Threshold
	selfExamTTL time.Duration
}

func newClinicalState(selfExamTTL time.Duration) clinicalState {
	if selfExamTTL <= 0 {
		selfExamTTL = DefaultSelfExamTTL
	}
	return clinicalState{
		prev:        initialSubsystems(),
		defaults:    DefaultThresholds(),
		selfExamTTL: selfExamTTL,
	}
}

func initialSubsystems() [6]contracts.SubsystemState {
	return [6]contracts.SubsystemState{
		{Subsystem: contracts.SubsystemCardiovascularFluids, Severity: contracts.SeverityGreen},
		{Subsystem: contracts.SubsystemRespiratoryAtmosphere, Severity: contracts.SeverityGreen},
		{Subsystem: contracts.SubsystemNeuroOcularSANS, Severity: contracts.SeverityGreen},
		{Subsystem: contracts.SubsystemMusculoskeletalPosture, Severity: contracts.SeverityGreen},
		{Subsystem: contracts.SubsystemImmuneHematoNutrition, Severity: contracts.SeverityGreen},
		{Subsystem: contracts.SubsystemNeurobehavioralRadiation, Severity: contracts.SeverityGreen},
	}
}

func severityRank(s contracts.Severity) int {
	switch s {
	case contracts.SeverityRed:
		return 2
	case contracts.SeverityYellow:
		return 1
	default:
		return 0
	}
}

func (c *clinicalState) thresholdFor(metric string, overrides map[string]contracts.Threshold) contracts.Threshold {
	if overrides != nil {
		if t, ok := overrides[metric]; ok {
			return t
		}
		if t, ok := overrides[strings.ToLower(metric)]; ok {
			return t
		}
	}
	return c.defaults[metric]
}

func (c *clinicalState) applyPeripheral(r contracts.PeripheralReading) {
	unit := strings.ToLower(strings.TrimSpace(r.Unit))
	switch r.Type {
	case contracts.PeripheralSCD40:
		c.env.CO2Ppm = r.Value
		c.hasCO2 = true
	case contracts.PeripheralBME280:
		switch unit {
		case "c", "°c", "degc", "celsius":
			c.env.TempC = r.Value
			c.hasTemp = true
		case "%", "%rh", "rh":
			c.env.HumidityPct = r.Value
			c.hasHumidity = true
		case "hpa", "mbar":
			c.env.PressureHpa = r.Value
			c.hasPressure = true
		case "pa":
			c.env.PressureHpa = r.Value / 100.0
			c.hasPressure = true
		}
	case contracts.PeripheralMAX30102:
		switch unit {
		case "bpm":
			c.maxHRBpm = r.Value
			c.hasMAXHR = true
			if !c.hasInference {
				c.vitals.HeartRateBpm = r.Value
			}
		case "%", "spo2", "%spo2":
			c.vitals.SpO2Pct = r.Value
			c.hasSpO2 = true
		}
	}
}

func (c *clinicalState) applyInference(inf contracts.AIInferencePayload) {
	c.lastInf = inf
	c.hasInference = true
	c.vitals.HeartRateBpm = inf.HeartRateBpm
	c.vitals.HRVMs = inf.HRVMs
	c.vitals.RespRateBpm = inf.RespirationHz * 60.0
	c.vitals.Posture = inf.Posture
	c.vitals.ConfidenceScore = inf.Confidence
}

func (c *clinicalState) freezeBiometrics() {
	c.hasInference = false
	c.vitals.HeartRateBpm = 0
	c.vitals.HRVMs = 0
	c.vitals.RespRateBpm = 0
	c.vitals.Posture = ""
	c.vitals.ConfidenceScore = 0
	if c.hasMAXHR {
		c.vitals.HeartRateBpm = c.maxHRBpm
	}
}

func (c *clinicalState) applySelfExam(in SelfExamInput, now time.Time) {
	ts := in.ReceivedAt
	if ts.IsZero() {
		ts = now
	}
	rec := &selfExamRecord{Payload: in.Payload, ReceivedAt: ts}
	et := strings.ToLower(strings.TrimSpace(in.Payload.ExamType))
	switch {
	case strings.Contains(et, "amsler") || strings.Contains(et, "ocular") || strings.Contains(et, "vision") || strings.Contains(et, "onsd"):
		c.amslerExam = rec
	case strings.Contains(et, "cardio") || strings.Contains(et, "bp") || strings.Contains(et, "ortho"):
		c.cardioExam = rec
	case strings.Contains(et, "musculo") || strings.Contains(et, "posture") || strings.Contains(et, "back") || strings.Contains(et, "joint"):
		c.musculoExam = rec
	case strings.Contains(et, "sleep") || strings.Contains(et, "hydrat") || strings.Contains(et, "nutrit") || strings.Contains(et, "immune") || strings.Contains(et, "temp"):
		c.immuneExam = rec
	default:
		c.neuroExam = rec
	}
}

func (c *clinicalState) isRecent(rec *selfExamRecord, now time.Time) bool {
	if rec == nil {
		return false
	}
	if c.selfExamTTL <= 0 {
		return true
	}
	return now.Sub(rec.ReceivedAt) <= c.selfExamTTL
}

func isSelfExamAltered(result string) (altered bool, severe bool) {
	r := strings.ToLower(strings.TrimSpace(result))
	switch r {
	case "", "normal", "ok", "negative", "clear", "none", "green", "pass":
		return false, false
	case "red", "severe", "critical", "acute":
		return true, true
	default:
		return true, false
	}
}

// Exercise heart-rate ceilings applied in MODE_COUNTERMEASURE_EXERCISE.
const (
	ExerciseHRYellowHigh = 165.0
	ExerciseHRRedHigh    = 185.0
)

// exerciseHeartRateThreshold raises resting HR ceilings to exercise levels.
// Crew-specific thresholds (e.g. seeded 110/140 resting) must not trigger
// RED during ARED/CEVIS countermeasures; ceilings already above the exercise
// floor are kept, and low limits (bradycardia) are preserved unchanged.
func exerciseHeartRateThreshold(t contracts.Threshold) contracts.Threshold {
	if t.MetricName == "" {
		t.MetricName = "heart_rate_bpm"
	}
	if t.YellowHigh < ExerciseHRYellowHigh {
		t.YellowHigh = ExerciseHRYellowHigh
	}
	if t.RedHigh < ExerciseHRRedHigh {
		t.RedHigh = ExerciseHRRedHigh
	}
	return t
}

func evalHighLow(val float64, t contracts.Threshold) contracts.Severity {
	if t.RedHigh > 0 && val > t.RedHigh {
		return contracts.SeverityRed
	}
	if t.RedLow > 0 && val < t.RedLow {
		return contracts.SeverityRed
	}
	if t.YellowHigh > 0 && val > t.YellowHigh {
		return contracts.SeverityYellow
	}
	if t.YellowLow > 0 && val < t.YellowLow {
		return contracts.SeverityYellow
	}
	return contracts.SeverityGreen
}

func pickWorst(curSev contracts.Severity, curMsg, curCM, curSrc string, candSev contracts.Severity, candMsg, candCM, candSrc string) (contracts.Severity, string, string, string) {
	if severityRank(candSev) > severityRank(curSev) {
		return candSev, candMsg, candCM, candSrc
	}
	return curSev, curMsg, curCM, curSrc
}

func (c *clinicalState) evaluate(now time.Time, view SessionView) ([6]contracts.SubsystemState, []alertDecision) {
	next := initialSubsystems()
	var cms [6]string
	var srcs [6]string

	// 0: CARDIOVASCULAR_FLUIDS
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		hr := c.vitals.HeartRateBpm
		if hr > 0 {
			t := c.thresholdFor("heart_rate_bpm", view.Thresholds)
			if view.MissionMode == contracts.ModeCountermeasureExercise {
				t = exerciseHeartRateThreshold(t)
			}
			if s := evalHighLow(hr, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Heart rate out of range: %.0f bpm", hr),
					"Verify rest posture, hydrate, and repeat ECG/pulse check",
					"NASA-HRP-CV-01")
			}
		}
		if c.hasInference && c.vitals.HRVMs > 0 {
			t := c.thresholdFor("hrv_ms", view.Thresholds)
			if s := evalHighLow(c.vitals.HRVMs, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Depressed HRV: %.1f ms", c.vitals.HRVMs),
					"Assess hydration, orthostatic stress, and rest schedule",
					"NASA-HRP-CV-HRV")
			}
		}
		if c.isRecent(c.cardioExam, now) {
			if alt, severe := isSelfExamAltered(c.cardioExam.Payload.Result); alt {
				s := contracts.SeverityYellow
				if severe {
					s = contracts.SeverityRed
				}
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Cardiovascular self-exam altered: %s", c.cardioExam.Payload.Result),
					"Perform orthostatic vitals and fluid loading protocol",
					"NASA-HRP-CV-EXAM")
			}
		}
		next[0].Severity, next[0].Message = sev, msg
		cms[0], srcs[0] = cm, src
	}

	// 1: RESPIRATORY_ATMOSPHERE
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		if c.hasCO2 {
			t := c.thresholdFor("co2_ppm", view.Thresholds)
			if s := evalHighLow(c.env.CO2Ppm, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Hypercapnia alert: cabin CO2 %.0f ppm", c.env.CO2Ppm),
					"Increase cabin ventilation, inspect CO2 scrubber, and verify O2 mask",
					"NASA-STD-3001-CO2")
			}
		}
		if c.hasSpO2 {
			t := c.thresholdFor("spo2_pct", view.Thresholds)
			if s := evalHighLow(c.vitals.SpO2Pct, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Hypoxemia alert: SpO2 %.1f%%", c.vitals.SpO2Pct),
					"Administer supplemental O2 and verify cabin partial pressure",
					"NASA-HRP-HYPOXIA")
			}
		}
		if c.hasInference && c.vitals.RespRateBpm > 0 {
			t := c.thresholdFor("resp_rate_bpm", view.Thresholds)
			if s := evalHighLow(c.vitals.RespRateBpm, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Abnormal respiratory rate: %.1f bpm", c.vitals.RespRateBpm),
					"Check CO2 exposure and perform calm breathing check",
					"NASA-HRP-RESP-01")
			}
		}
		if c.hasPressure {
			t := c.thresholdFor("pressure_hpa", view.Thresholds)
			if s := evalHighLow(c.env.PressureHpa, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Cabin pressure anomaly: %.1f hPa", c.env.PressureHpa),
					"Inspect hull seals and pressure regulation valves",
					"NASA-STD-3001-PRESS")
			}
		}
		next[1].Severity, next[1].Message = sev, msg
		cms[1], srcs[1] = cm, src
	}

	// 2: NEURO_OCULAR_SANS
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		if c.isRecent(c.amslerExam, now) {
			if alt, severe := isSelfExamAltered(c.amslerExam.Payload.Result); alt {
				s := contracts.SeverityYellow
				if severe {
					s = contracts.SeverityRed
				}
				sev = s
				msg = fmt.Sprintf("Amsler/ocular self-exam altered (%s)", c.amslerExam.Payload.Result)
				cm = "Apply Thigh Cuffs, perform ONSD ultrasound, and review B-complex protocol"
				src = "NASA-HRP-SANS-VIIP"
			}
		}
		next[2].Severity, next[2].Message = sev, msg
		cms[2], srcs[2] = cm, src
	}

	// 3: MUSCULOSKELETAL_POSTURE
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		if c.hasInference {
			posture := strings.ToLower(strings.TrimSpace(c.vitals.Posture))
			if posture == "fallen" || posture == "collapse" || posture == "collapsed" {
				sev, msg, cm, src = contracts.SeverityRed,
					"Critical posture alert: crew member fallen/collapsed",
					"Immediate crew check and medical response",
					"NASA-HRP-MSK-FALL"
			} else if posture == "slumped" || posture == "unstable" {
				sev, msg, cm, src = contracts.SeverityYellow,
					fmt.Sprintf("Abnormal posture detected: %s", c.vitals.Posture),
					"Check crew responsiveness and ergonomic restraint",
					"NASA-HRP-MSK-01"
			}
		}
		if c.isRecent(c.musculoExam, now) {
			if alt, severe := isSelfExamAltered(c.musculoExam.Payload.Result); alt {
				s := contracts.SeverityYellow
				if severe {
					s = contracts.SeverityRed
				}
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Musculoskeletal self-exam altered: %s", c.musculoExam.Payload.Result),
					"Adjust ARED/resistive countermeasure load and rest affected region",
					"NASA-HRP-MSK-EXAM")
			}
		}
		next[3].Severity, next[3].Message = sev, msg
		cms[3], srcs[3] = cm, src
	}

	// 4: IMMUNE_HEMATO_NUTRITION
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		if c.hasTemp {
			t := c.thresholdFor("temp_c", view.Thresholds)
			if s := evalHighLow(c.env.TempC, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Cabin temperature out of range: %.1f C", c.env.TempC),
					"Adjust thermal control loop and monitor crew hydration",
					"NASA-STD-3001-TEMP")
			}
		}
		if c.hasHumidity {
			t := c.thresholdFor("humidity_pct", view.Thresholds)
			if s := evalHighLow(c.env.HumidityPct, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Cabin humidity out of range: %.1f%%", c.env.HumidityPct),
					"Check condensing heat exchanger and crew fluid intake",
					"NASA-STD-3001-RH")
			}
		}
		if c.isRecent(c.immuneExam, now) {
			if alt, severe := isSelfExamAltered(c.immuneExam.Payload.Result); alt {
				s := contracts.SeverityYellow
				if severe {
					s = contracts.SeverityRed
				}
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Sleep/hydration/immune self-exam altered: %s", c.immuneExam.Payload.Result),
					"Initiate Nutrition SMO hydration & circadian realignment protocol",
					"NASA-HRP-IMMUNE-01")
			}
		}
		next[4].Severity, next[4].Message = sev, msg
		cms[4], srcs[4] = cm, src
	}

	// 5: NEUROBEHAVIORAL_RADIATION
	{
		sev := contracts.SeverityGreen
		var msg, cm, src string
		if view.MissionMode == contracts.ModeRadiationAlert {
			sev = contracts.SeverityRed
			msg = "MODE_RADIATION_ALERT active: Solar Particle Event exposure risk"
			cm = "Move to radiation shelter immediately and administer Vitamins C & E protocol"
			src = "NASA-HRP-CANS-SPE"
		}
		if c.hasInference {
			t := c.thresholdFor("anomaly_score", view.Thresholds)
			if s := evalHighLow(c.lastInf.AnomalyScore, t); s != contracts.SeverityGreen {
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Elevated behavioral/biometric anomaly score: %.2f", c.lastInf.AnomalyScore),
					"Review circadian, stress, and cognitive checklist",
					"NASA-HRP-BMed-01")
			}
		}
		if c.isRecent(c.neuroExam, now) {
			if alt, severe := isSelfExamAltered(c.neuroExam.Payload.Result); alt {
				s := contracts.SeverityYellow
				if severe {
					s = contracts.SeverityRed
				}
				sev, msg, cm, src = pickWorst(sev, msg, cm, src, s,
					fmt.Sprintf("Neurobehavioral self-exam altered: %s", c.neuroExam.Payload.Result),
					"Conduct fatigue/cognitive assessment and light therapy adjustment",
					"NASA-HRP-BMed-EXAM")
			}
		}
		next[5].Severity, next[5].Message = sev, msg
		cms[5], srcs[5] = cm, src
	}

	var alerts []alertDecision
	for i := 0; i < 6; i++ {
		prev := c.prev[i]
		curr := next[i]
		if curr.Severity == contracts.SeverityGreen {
			continue
		}
		worsened := severityRank(curr.Severity) > severityRank(prev.Severity)
		redChanged := curr.Severity == contracts.SeverityRed && curr.Message != prev.Message
		if worsened || redChanged {
			esc := contracts.EscalationCrew
			if curr.Severity == contracts.SeverityRed {
				esc = contracts.EscalationStoreAndForward
			}
			alerts = append(alerts, alertDecision{
				Alert: contracts.AlertEventPayload{
					Subsystem:      curr.Subsystem,
					Severity:       curr.Severity,
					Message:        curr.Message,
					Countermeasure: cms[i],
					Escalation:     esc,
					SourceID:       srcs[i],
				},
			})
		}
	}
	c.prev = next
	return next, alerts
}
