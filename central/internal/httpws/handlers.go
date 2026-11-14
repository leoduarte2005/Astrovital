package httpws

import (
	"encoding/json"
	"io/fs"
	"net/http"

	"edgespace/central/internal/contracts"
)

func (s *Server) registerRoutes(uiFS fs.FS) {
	s.mux.HandleFunc("GET /healthz", s.handleHealthz)
	s.mux.HandleFunc("GET /api/metrics", s.handleMetrics)
	s.mux.HandleFunc("/api/crew", s.handleCrew) // method checked inside handler -> 405 on non-GET
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

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
