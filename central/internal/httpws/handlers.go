package httpws

import (
	"encoding/json"
	"io/fs"
	"net/http"
	"strconv"
	"strings"

	"edgespace/central/internal/contracts"
)

func (s *Server) registerRoutes(uiFS fs.FS) {
	s.mux.HandleFunc("GET /healthz", s.handleHealthz)
	s.mux.HandleFunc("GET /api/metrics", s.handleMetrics)
	s.mux.HandleFunc("/api/crew", s.handleCrew) // method checked inside handler -> 405 on non-GET
	s.mux.HandleFunc("GET /api/crew/{id}/profile", s.handleCrewProfile)
	s.mux.HandleFunc("GET /api/crew/{id}/timeseries", s.handleCrewTimeseries)
	s.mux.HandleFunc("GET /api/protocols/{id}", s.handleProtocol)
	s.mux.HandleFunc("GET /api/alerts", s.handleAlerts)
	s.mux.HandleFunc("GET /api/outbox", s.handleOutbox)
	if s.deps.Dev != nil {
		s.mux.HandleFunc("POST /api/dev/scenario", s.handleDevScenario)
		s.mux.HandleFunc("POST /api/dev/node/{id}/kill", s.handleDevKillNode)
		s.mux.HandleFunc("POST /api/dev/node/{id}/revive", s.handleDevReviveNode)
	}
	s.mux.HandleFunc("GET /ws", s.handleWS)
	s.mux.Handle("/", http.FileServer(http.FS(uiFS)))
}

func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	if s.deps.Reader != nil {
		if err := s.deps.Reader.Health(r.Context()); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{
				"status": "degraded",
				"db":     err.Error(),
			})
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"status": "ok",
		"db":     "ok",
	})
}

func (s *Server) handleMetrics(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.Metrics())
}

func (s *Server) handleCrew(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	if s.deps.Reader == nil {
		writeJSON(w, http.StatusOK, []any{})
		return
	}
	crew, err := s.deps.Reader.ListCrew(r.Context())
	if err != nil {
		s.log.Error("list crew failed", "err", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to query crew"})
		return
	}
	if crew == nil {
		crew = []contracts.CrewSummary{}
	}
	writeJSON(w, http.StatusOK, crew)
}

func (s *Server) extReader() ExtendedReader {
	if s.deps.ExtendedReader != nil {
		return s.deps.ExtendedReader
	}
	if ex, ok := s.deps.Reader.(ExtendedReader); ok {
		return ex
	}
	return nil
}

func isNotFoundErr(err error) bool {
	return err != nil && strings.Contains(strings.ToLower(err.Error()), "not found")
}

func (s *Server) handleCrewProfile(w http.ResponseWriter, r *http.Request) {
	ex := s.extReader()
	if ex == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "profile reader unavailable"})
		return
	}
	prof, err := ex.GetCrewProfile(r.Context(), r.PathValue("id"))
	if err != nil {
		if isNotFoundErr(err) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "crew not found"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, prof)
}

func (s *Server) handleCrewTimeseries(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	q := r.URL.Query()
	metric := q.Get("metric")
	fromUs := parseQueryInt64(q.Get("from"), parseQueryInt64(q.Get("from_us"), 0))
	toUs := parseQueryInt64(q.Get("to"), parseQueryInt64(q.Get("to_us"), 0))
	bucketSec := int(parseQueryInt64(q.Get("bucket_sec"), parseQueryInt64(q.Get("bucket"), 1)))

	ex := s.extReader()
	if ex == nil {
		writeJSON(w, http.StatusOK, contracts.TimeseriesResponse{
			CrewID:  id,
			StartUs: fromUs,
			EndUs:   toUs,
			Buckets: []contracts.TelemetryBucket{},
		})
		return
	}
	if !contracts.IsTimeseriesMetric(metric) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "unknown metric: " + metric})
		return
	}
	res, err := ex.QueryTimeseries(r.Context(), id, metric, fromUs, toUs, bucketSec)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if res.Buckets == nil {
		res.Buckets = []contracts.TelemetryBucket{}
	}
	writeJSON(w, http.StatusOK, res)
}

func (s *Server) handleProtocol(w http.ResponseWriter, r *http.Request) {
	ex := s.extReader()
	if ex == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "protocols unavailable"})
		return
	}
	p, err := ex.GetProtocol(r.Context(), r.PathValue("id"))
	if err != nil {
		if isNotFoundErr(err) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "protocol not found"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func (s *Server) handleAlerts(w http.ResponseWriter, r *http.Request) {
	limit := int(parseQueryInt64(r.URL.Query().Get("limit"), 50))
	ex := s.extReader()
	if ex == nil {
		writeJSON(w, http.StatusOK, []contracts.AlertRecord{})
		return
	}
	list, err := ex.ListAlerts(r.Context(), limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if list == nil {
		list = []contracts.AlertRecord{}
	}
	writeJSON(w, http.StatusOK, list)
}

func (s *Server) handleOutbox(w http.ResponseWriter, r *http.Request) {
	ex := s.extReader()
	if ex == nil {
		writeJSON(w, http.StatusOK, []contracts.OutboxRecord{})
		return
	}
	list, err := ex.ListOutbox(r.Context())
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if list == nil {
		list = []contracts.OutboxRecord{}
	}
	writeJSON(w, http.StatusOK, list)
}

func (s *Server) handleDevScenario(w http.ResponseWriter, r *http.Request) {
	var req contracts.DevScenarioReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
		return
	}
	if err := s.deps.Dev.SetScenario(r.Context(), req.Scenario, req.Seed); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "scenario": req.Scenario})
}

func (s *Server) handleDevKillNode(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil || id < 0 || id > 4 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "node_id must be 0..4"})
		return
	}
	if err := s.deps.Dev.KillNode(r.Context(), uint8(id)); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "killed", "node_id": id})
}

func (s *Server) handleDevReviveNode(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil || id < 0 || id > 4 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "node_id must be 0..4"})
		return
	}
	if err := s.deps.Dev.ReviveNode(r.Context(), uint8(id)); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "revived", "node_id": id})
}

func parseQueryInt64(s string, def int64) int64 {
	if s == "" {
		return def
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return def
	}
	return v
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
