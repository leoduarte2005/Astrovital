package store

import (
	"encoding/json"
	"strings"
)

// Self-exam normalization shared with edge-ai/src/edgespace_ai/clinical.py
// (SELF_EXAM_PROTOCOL_ALIASES / normalize_self_exam). Keep both tables in sync.

// selfExamProtocolAliases maps lower-cased ExamType aliases to protocols.protocol_id.
var selfExamProtocolAliases = map[string]string{
	"amsler":                "amsler_grid",
	"amsler_grid":           "amsler_grid",
	"ocular":                "amsler_grid",
	"vision":                "amsler_grid",
	"bp":                    "blood_pressure",
	"blood_pressure":        "blood_pressure",
	"orthostatic":           "blood_pressure",
	"cardio":                "blood_pressure",
	"capillary_blood":       "capillary_blood",
	"fingerstick":           "capillary_blood",
	"onsd":                  "ultrasound_onsd",
	"ultrasound_onsd":       "ultrasound_onsd",
	"temp":                  "temperature",
	"temperature":           "temperature",
	"sleep":                 "sleep_review",
	"sleep_review":          "sleep_review",
	"nutrition":             "nutrition_review",
	"nutrition_review":      "nutrition_review",
	"hydration":             "nutrition_review",
	"environment_check":     "environment_check",
	"cognitive":             "cognitive_check",
	"cognitive_check":       "cognitive_check",
	"behavioral":            "behavioral_check",
	"behavioral_check":      "behavioral_check",
	"musculoskeletal":       "musculoskeletal_check",
	"musculoskeletal_check": "musculoskeletal_check",
	"oxygen":                "oxygen_check",
	"oxygen_check":          "oxygen_check",
	"symptom":               "symptom_review",
	"symptom_review":        "symptom_review",
	"post_eva":              "post_eva_review",
	"post_eva_review":       "post_eva_review",
}

// normalResults are string results interpreted as NOT abnormal.
var normalResults = map[string]bool{
	"normal": true, "ok": true, "negative": true, "clear": true, "none": true,
	"green": true, "pass": true, "passed": true, "no": true, "false": true, "0": true,
}

// SelfExamProtocolID resolves an ExamType to a canonical protocol_id ("" if unknown).
func SelfExamProtocolID(examType string) string {
	key := strings.ToLower(strings.TrimSpace(examType))
	key = strings.ReplaceAll(strings.ReplaceAll(key, "-", "_"), " ", "_")
	return selfExamProtocolAliases[key]
}

// SelfExamAbnormal derives abnormal_flag from a string or JSON result.
//   - JSON object with "abnormal_flag" (bool/number/string) wins;
//   - JSON object without it -> false;
//   - plain string: normal vocabulary -> false, anything else non-empty -> true.
func SelfExamAbnormal(result string) bool {
	r := strings.TrimSpace(result)
	if r == "" {
		return false
	}
	if strings.HasPrefix(r, "{") {
		var obj map[string]any
		if err := json.Unmarshal([]byte(r), &obj); err == nil {
			switch v := obj["abnormal_flag"].(type) {
			case bool:
				return v
			case float64:
				return v != 0
			case string:
				return !normalResults[strings.ToLower(strings.TrimSpace(v))]
			default:
				return false
			}
		}
	}
	return !normalResults[strings.ToLower(r)]
}

// selfExamPayloadJSON stores the original payload plus normalized fields as JSON.
func selfExamPayloadJSON(examType, result, observations, protocolID string, abnormal bool) (string, error) {
	doc := map[string]any{
		"exam_type":     examType,
		"result":        result,
		"abnormal_flag": abnormal,
	}
	if observations != "" {
		doc["observations"] = observations
	}
	if protocolID != "" {
		doc["protocol_id"] = protocolID
	}
	r := strings.TrimSpace(result)
	if strings.HasPrefix(r, "{") {
		var obj map[string]any
		if err := json.Unmarshal([]byte(r), &obj); err == nil {
			doc["result_json"] = obj
		}
	}
	b, err := json.Marshal(doc)
	return string(b), err
}
