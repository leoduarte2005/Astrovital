package sim

import (
	"time"

	"edgespace/central/internal/contracts"
)

// Supported scenario names matching --scenario and POST /api/dev/scenario (§5.2).
const (
	ScenarioNominal          = ""
	ScenarioHypercapnia      = "hypercapnia"
	ScenarioSANS             = "sans"
	ScenarioSolarStorm       = "solar_storm"
	ScenarioDehydrationSleep = "dehydration_sleep"
	ScenarioNodeLoss         = "node_loss"
)

// Scenario timeline in simulated time (one 100 ms cycle = 100 ms of sim time).
// Wall-clock time is simulated time / TimeScale, so TimeScale=10 runs these 10x faster.
const (
	hypercapniaRamp     = 120 * time.Second
	sansExamAt          = 2 * time.Second
	solarStormAt        = 10 * time.Second
	nodeLossKillAt      = 15 * time.Second
	nodeLossReviveAt    = 45 * time.Second
	nodeLossTargetNode  = 3
	nominalCO2Ppm       = 600.0
	hypercapniaPeakPpm  = 5000.0
	nominalHeartRateBpm = 65.0
	nominalHeartHz      = 1.2
	nominalRespHz       = 0.25
)

// SelfExamEvent is the synthetic self-exam injected by the sans scenario:
// Amsler grid with metamorphopsia plus elevated blood pressure, CO2 normal.
type SelfExamEvent struct {
	Kind           string // "AMSLER"
	Metamorphopsia bool
	SystolicMmHg   int
	DiastolicMmHg  int
	TimestampUs    int64
}

// IsValidScenario reports whether s is a recognized scenario identifier.
func IsValidScenario(s string) bool {
	switch s {
	case ScenarioNominal,
		ScenarioHypercapnia,
		ScenarioSANS,
		ScenarioSolarStorm,
		ScenarioDehydrationSleep,
		ScenarioNodeLoss:
		return true
	default:
		return false
	}
}

type scenarioState struct {
	name      string
	startedAt time.Time
	fired     bool // sans exam / solar alert emitted
	killed    bool // node_loss kill applied
	revived   bool // node_loss revive applied
}

func newScenarioState(name string, now time.Time) scenarioState {
	return scenarioState{name: name, startedAt: now}
}

// co2Ppm returns the SCD40 CO2 reading: 600 ppm nominal, ramp to 5000 ppm in 120 s on hypercapnia.
func (s *scenarioState) co2Ppm(elapsed time.Duration) float64 {
	if s.name != ScenarioHypercapnia {
		return nominalCO2Ppm
	}
	if elapsed <= 0 {
		return nominalCO2Ppm
	}
	frac := float64(elapsed) / float64(hypercapniaRamp)
	if frac > 1 {
		frac = 1
	}
	return nominalCO2Ppm + (hypercapniaPeakPpm-nominalCO2Ppm)*frac
}

// heartRateBpm returns the MAX30102 HR; dehydration_sleep raises resting HR (+20%).
func (s *scenarioState) heartRateBpm() float64 {
	if s.name == ScenarioDehydrationSleep {
		return nominalHeartRateBpm * 1.2
	}
	return nominalHeartRateBpm
}

// cardiacModulation returns the cardiac frequency (Hz) and relative amplitude applied to CSI.
// dehydration_sleep: elevated resting HR and HRV -30% (cardiac modulation amplitude x0.7).
func (s *scenarioState) cardiacModulation() (hz, amp float64) {
	if s.name == ScenarioDehydrationSleep {
		return nominalHeartHz * 1.2, 0.7
	}
	return nominalHeartHz, 1.0
}

// applyScenarioEffectsLocked evaluates time-based scenario events at simNow.
// Callbacks are queued in mc.pending and run after mc.mu is released.
func (mc *MockCluster) applyScenarioEffectsLocked(simNow time.Time) {
	sc := &mc.scenario
	elapsed := simNow.Sub(sc.startedAt)

	switch sc.name {
	case ScenarioSANS:
		if !sc.fired && elapsed >= sansExamAt {
			sc.fired = true
			if cb := mc.cfg.OnSelfExam; cb != nil {
				ev := SelfExamEvent{
					Kind:           "AMSLER",
					Metamorphopsia: true,
					SystolicMmHg:   150,
					DiastolicMmHg:  95,
					TimestampUs:    simNow.UnixMicro(),
				}
				mc.pending = append(mc.pending, func() { cb(ev) })
			}
		}
	case ScenarioSolarStorm:
		if !sc.fired && elapsed >= solarStormAt {
			sc.fired = true
			mc.missionMode = contracts.ModeRadiationAlert
			if cb := mc.cfg.OnModeChange; cb != nil {
				mc.pending = append(mc.pending, func() { cb(contracts.ModeRadiationAlert) })
			}
		}
	case ScenarioNodeLoss:
		if !sc.killed && elapsed >= nodeLossKillAt {
			sc.killed = true
			mc.killed[nodeLossTargetNode].Store(true)
		}
		if sc.killed && !sc.revived && elapsed >= nodeLossReviveAt {
			sc.revived = true
			mc.reviveLocked(nodeLossTargetNode)
		}
	}
}
