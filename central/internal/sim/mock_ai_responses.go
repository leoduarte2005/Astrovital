package sim

import (
	"strings"

	"edgespace/central/internal/contracts"
)

func inferenceFor(scenario string, cycleSeq uint32) contracts.AIInferencePayload {
	switch scenario {
	case "hypercapnia":
		return contracts.AIInferencePayload{
			CycleSeqFirst: cycleSeq, Posture: "supine", RespirationHz: 0.38,
			HeartRateBpm: 78, HRVMs: 32, AnomalyScore: 0.72, Confidence: 0.92,
		}
	case "sans":
		return contracts.AIInferencePayload{
			CycleSeqFirst: cycleSeq, Posture: "upright", RespirationHz: 0.28,
			HeartRateBpm: 84, HRVMs: 28, AnomalyScore: 0.62, Confidence: 0.89,
		}
	case "solar_storm":
		return contracts.AIInferencePayload{
			CycleSeqFirst: cycleSeq, Posture: "shelter_crouch", RespirationHz: 0.30,
			HeartRateBpm: 86, HRVMs: 26, AnomalyScore: 0.45, Confidence: 0.87,
		}
	case "dehydration_sleep":
		return contracts.AIInferencePayload{
			CycleSeqFirst: cycleSeq, Posture: "supine", RespirationHz: 0.22,
			HeartRateBpm: 82, HRVMs: 18, AnomalyScore: 0.58, Confidence: 0.84,
		}
	default:
		return contracts.AIInferencePayload{
			CycleSeqFirst: cycleSeq, Posture: "upright", RespirationHz: 0.25,
			HeartRateBpm: 65, HRVMs: 52, AnomalyScore: 0.05, Confidence: 0.95,
		}
	}
}

func chatFor(scenario, text string) contracts.ChatCorrelateRespPayload {
	q := strings.ToLower(text)
	has := func(keys ...string) bool {
		for _, k := range keys {
			if strings.Contains(q, k) {
				return true
			}
		}
		return false
	}

	if scenario == "solar_storm" || has("radiation", "spe", "solar storm", "radiac", "tempestade") {
		return contracts.ChatCorrelateRespPayload{
			Text:            "Active solar particle event (SPE) detected. Move to radiation shelter immediately.",
			Differentials:   []string{"Acute SPE Exposure (CANS/ROS)", "Neurobehavioral Fatigue"},
			Evidence:        []string{"MODE_RADIATION_ALERT active", "Elevated HR: 86 bpm"},
			Countermeasures: []string{"Central high-shielding shelter", "Vitamins C and E supplementation"},
			SourceIDs:       []string{"NASA-HRP-RAD-001", "CSA-SPE-002"},
			Escalation:      contracts.EscalationStoreAndForward,
			Actions:         []string{"ENTER_SHELTER", "LOG_DOSIMETRY"},
			Disclaimer:      "Onboard clinical decision support; does not replace Flight Surgeon evaluation.",
		}
	}

	if scenario == "sans" || has("amsler", "vision", "visual", "ocular", "metamorph", "visao") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Headache with positive Amsler Grid findings suggests SANS/VIIP (intracranial pressure).",
			Differentials:          []string{"SANS / VIIP (headache + metamorphopsia)", "Mild Hypercapnia"},
			DisambiguationQuestion: "Any worsening near vision or diplopia upon waking?",
			Evidence:               []string{"Positive Amsler self-exam", "Cephalic fluid shift"},
			Countermeasures:        []string{"Apply Thigh Cuffs (Braslet)", "ONSD Ultrasound", "B-Complex"},
			SourceIDs:              []string{"NASA-HRP-SANS-001", "CSA-VIIP-003"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"APPLY_THIGH_CUFFS", "RUN_ONSD_US"},
			Disclaimer:             "Onboard clinical decision support; does not replace Flight Surgeon evaluation.",
		}
	}

	if scenario == "dehydration_sleep" || has("sleep", "dehydrat", "thirst", "sono", "desidrat", "sede") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Headache and fatigue correlate with sleep deprivation (4h) and 30% HRV reduction.",
			Differentials:          []string{"Dehydration + Sleep Restriction", "Circadian Stress"},
			DisambiguationQuestion: "What was your fluid intake over the last 12 hours?",
			Evidence:               []string{"4h cumulative sleep", "HRV -30% (~18 ms)", "Elevated resting HR"},
			Countermeasures:        []string{"Oral hydration + electrolytes bolus", "Nutrition SMO", "Circadian lighting adjustment"},
			SourceIDs:              []string{"NASA-HRP-SLEEP-004", "NASA-IMM-NUT-002"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"HYDRATION_BOLUS", "SHIFT_LIGHT_CYCLE"},
			Disclaimer:             "Onboard clinical decision support; does not replace Flight Surgeon evaluation.",
		}
	}

	if scenario == "hypercapnia" || has("co2", "headache", "ventilat", "cefaleia", "cabeca", "cabeça") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Headache correlates with hypercapnia (elevated CO2 in the module).",
			Differentials:          []string{"Hypercapnia (elevated CO2)", "Mild Dehydration", "Early SANS"},
			DisambiguationQuestion: "Does the headache improve near the ventilation diffuser?",
			Evidence:               []string{"SCD40 trending upward", "Increased respiratory rate"},
			Countermeasures:        []string{"Increase cabin ventilation", "Check CO2 scrubber CDRA/CO2", "Hydration"},
			SourceIDs:              []string{"NASA-HRP-CO2-001"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"BOOST_VENTILATION", "CHECK_CO2_SCRUBBER"},
			Disclaimer:             "Onboard clinical decision support; does not replace Flight Surgeon evaluation.",
		}
	}

	return contracts.ChatCorrelateRespPayload{
		Text:            "Telemetry within nominal limits for active crew member.",
		Differentials:   []string{"No acute finding"},
		Evidence:        []string{"Stable vital signs", "Nominal atmosphere"},
		Countermeasures: []string{"Maintain routine monitoring"},
		SourceIDs:       []string{"NASA-HRP-GEN-000"},
		Escalation:      contracts.EscalationLocal,
		Disclaimer:      "Onboard clinical decision support; does not replace Flight Surgeon evaluation.",
	}
}
