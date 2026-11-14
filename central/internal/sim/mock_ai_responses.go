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

	if scenario == "solar_storm" || has("radiac", "radiation", "spe", "tempestade") {
		return contracts.ChatCorrelateRespPayload{
			Text:            "Evento de particulas solares (SPE) ativo. Mover para abrigo de radiacao imediatamente.",
			Differentials:   []string{"Exposicao aguda SPE (CANS/ROS)", "Fadiga neurocomportamental"},
			Evidence:        []string{"Modo MODE_RADIATION_ALERT ativo", "FC elevada: 86 bpm"},
			Countermeasures: []string{"Abrigo central de alta blindagem", "Suplementacao Vitaminas C e E"},
			SourceIDs:       []string{"NASA-HRP-RAD-001", "CSA-SPE-002"},
			Escalation:      contracts.EscalationStoreAndForward,
			Actions:         []string{"ENTER_SHELTER", "LOG_DOSIMETRY"},
			Disclaimer:      "Apoio a decisao clinica embarcada; nao substitui medico de voo.",
		}
	}

	if scenario == "sans" || has("amsler", "visao", "vision", "ocular", "metamorf") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Cefaleia associada a alteracao no teste de Amsler sugere SANS/VIIP (pressao intracraniana).",
			Differentials:          []string{"SANS / VIIP (cefaleia + metamorfopsia)", "Hipercapnia leve"},
			DisambiguationQuestion: "Ha piora da visao para perto ou diplopia ao acordar?",
			Evidence:               []string{"Autoexame Amsler positivo", "Deslocamento cefalico de fluidos"},
			Countermeasures:        []string{"Aplicar Thigh Cuffs (Braslet)", "Ultrassom ONSD", "Complexo B"},
			SourceIDs:              []string{"NASA-HRP-SANS-001", "CSA-VIIP-003"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"APPLY_THIGH_CUFFS", "RUN_ONSD_US"},
			Disclaimer:             "Apoio a decisao clinica embarcada; nao substitui medico de voo.",
		}
	}

	if scenario == "dehydration_sleep" || has("sono", "sleep", "desidrat", "dehydrat", "sede") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Cefaleia e fadiga correlacionam com privacao de sono (4h) e reducao de 30% no HRV.",
			Differentials:          []string{"Desidratacao + restricao de sono", "Estresse circadiano"},
			DisambiguationQuestion: "Qual o volume hidrico ingerido nas ultimas 12h?",
			Evidence:               []string{"Sono 4h acumulado", "HRV -30% (~18 ms)", "FC repouso elevada"},
			Countermeasures:        []string{"Protocolo de hidratacao oral + eletrolitos", "Nutrition SMO", "Ajuste circadiano"},
			SourceIDs:              []string{"NASA-HRP-SLEEP-004", "NASA-IMM-NUT-002"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"HYDRATION_BOLUS", "SHIFT_LIGHT_CYCLE"},
			Disclaimer:             "Apoio a decisao clinica embarcada; nao substitui medico de voo.",
		}
	}

	if scenario == "hypercapnia" || has("co2", "cefaleia", "cabeca", "cabeça", "headache", "ventila") {
		return contracts.ChatCorrelateRespPayload{
			Text:                   "Cefaleia correlacionada com hipercapnia (CO2 em elevacao no modulo).",
			Differentials:          []string{"Hipercapnia (CO2 elevado)", "Desidratacao leve", "SANS inicial"},
			DisambiguationQuestion: "A cefaleia melhora proximo ao difusor de ventilacao?",
			Evidence:               []string{"SCD40 em elevacao", "Frequencia respiratoria aumentada"},
			Countermeasures:        []string{"Aumentar ventilacao de cabine", "Verificar scrubber CDRA/CO2", "Hidratacao"},
			SourceIDs:              []string{"NASA-HRP-CO2-001"},
			Escalation:             contracts.EscalationCrew,
			Actions:                []string{"BOOST_VENTILATION", "CHECK_CO2_SCRUBBER"},
			Disclaimer:             "Apoio a decisao clinica embarcada; nao substitui medico de voo.",
		}
	}

	return contracts.ChatCorrelateRespPayload{
		Text:            "Telemetria dentro dos limites nominais para o tripulante ativo.",
		Differentials:   []string{"Sem achado agudo"},
		Evidence:        []string{"Sinais vitais estaveis", "Atmosfera nominal"},
		Countermeasures: []string{"Manter monitoramento de rotina"},
		SourceIDs:       []string{"NASA-HRP-GEN-000"},
		Escalation:      contracts.EscalationLocal,
		Disclaimer:      "Apoio a decisao clinica embarcada; nao substitui medico de voo.",
	}
}
