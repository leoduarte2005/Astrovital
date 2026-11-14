// Package httpws serves the embedded offline UI, REST endpoints (/healthz, /api/*),
// and the non-blocking WebSocket hub (/ws).
package httpws

import (
	"context"
	"embed"
	"errors"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

//go:embed ui/*
var embeddedUI embed.FS

const (
	defaultHTTPAddr   = ":8000"
	defaultWSHz       = 2
	maxWSMessageBytes = 64 * 1024
	wsWriteTimeout    = 1 * time.Second
	wsPingInterval    = 10 * time.Second
	eventChanSize     = 128
	cspPolicy         = "default-src 'self'; connect-src 'self'"
)

// Reader is the small read-only DB interface consumed by REST handlers.
type Reader interface {
	Health(ctx context.Context) error
	ListCrew(ctx context.Context) ([]contracts.CrewSummary, error)
}

// StoreStats holds storage counters surfaced in /api/metrics.
type StoreStats struct {
	Commits int64
	Backlog int64
}

// Config configures the HTTP/WS server.
type Config struct {
	Addr string
	WSHz int
}

// Deps holds injected dependencies (all optional except Logger/Reader when used).
type Deps struct {
	Logger     *slog.Logger
	Reader     Reader
	StoreStats func() StoreStats
}

// MetricsSnapshot is the JSON payload returned by GET /api/metrics.
type MetricsSnapshot struct {
	WSClients          int64 `json:"ws_clients"`
	WSDroppedTelemetry int64 `json:"ws_dropped_telemetry"`
	StoreCommits       int64 `json:"store_commits"`
	StoreBacklog       int64 `json:"store_backlog"`
}

// Server owns the HTTP listener and WebSocket hub.
type Server struct {
	cfg     Config
	deps    Deps
	log     *slog.Logger
	mux     *http.ServeMux
	handler http.Handler
	httpSrv *http.Server

	latest  atomic.Pointer[contracts.TelemetrySnapshot]
	eventCh chan contracts.WSEnvelope
	hub     *wsHub
}

// New constructs a Server with embedded UI, REST handlers, and WS hub.
func New(cfg Config, deps Deps) (*Server, error) {
	if cfg.Addr == "" {
		cfg.Addr = defaultHTTPAddr
	}
	if cfg.WSHz <= 0 {
		cfg.WSHz = defaultWSHz
	}
	log := deps.Logger
	if log == nil {
		log = slog.Default()
	}

	uiSub, err := fs.Sub(embeddedUI, "ui")
	if err != nil {
		return nil, err
	}

	s := &Server{
		cfg:     cfg,
		deps:    deps,
		log:     log,
		mux:     http.NewServeMux(),
		eventCh: make(chan contracts.WSEnvelope, eventChanSize),
	}
	s.hub = newWSHub(s, log, time.Second/time.Duration(cfg.WSHz))

	s.registerRoutes(uiSub)
	s.handler = withSecurityHeaders(s.mux)
	s.httpSrv = &http.Server{
		Addr:              cfg.Addr,
		Handler:           s.handler,
		ReadHeaderTimeout: 5 * time.Second,
	}
	return s, nil
}

// Latest returns the atomic pointer updated by pipeline (latest-wins).
func (s *Server) Latest() *atomic.Pointer[contracts.TelemetrySnapshot] {
	return &s.latest
}

// EventCh returns the immediate event channel consumed by wsBroadcaster.
func (s *Server) EventCh() chan<- contracts.WSEnvelope {
	return s.eventCh
}

// Handler returns the root HTTP handler (useful for httptest).
func (s *Server) Handler() http.Handler {
	return s.handler
}

// Metrics returns current HTTP/WS + store counters.
func (s *Server) Metrics() MetricsSnapshot {
	m := MetricsSnapshot{
		WSClients:          s.hub.clientsCount.Load(),
		WSDroppedTelemetry: s.hub.droppedTelemetry.Load(),
	}
	if s.deps.StoreStats != nil {
		st := s.deps.StoreStats()
		m.StoreCommits = st.Commits
		m.StoreBacklog = st.Backlog
	}
	return m
}

// Run starts the WS broadcaster and HTTP server, shutting down cleanly on ctx.Done().
func (s *Server) Run(ctx context.Context) error {
	ln, err := net.Listen("tcp", s.cfg.Addr)
	if err != nil {
		return err
	}
	s.log.Info("httpws listening", "addr", ln.Addr().String(), "ws_hz", s.cfg.WSHz)

	hubDone := make(chan struct{})
	go func() {
		defer close(hubDone)
		s.hub.run(ctx)
	}()

	srvErr := make(chan error, 1)
	go func() {
		if err := s.httpSrv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			srvErr <- err
		}
		close(srvErr)
	}()

	select {
	case err := <-srvErr:
		return err
	case <-ctx.Done():
	}

	// Strict shutdown: stop accepting new HTTP, close WS clients with 1001, wait hub.
	shutCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := s.httpSrv.Shutdown(shutCtx); err != nil && !errors.Is(err, context.Canceled) {
		s.log.Warn("http shutdown error", "err", err)
	}
	s.hub.closeAllGoingAway()
	<-hubDone
	s.log.Info("httpws stopped")
	return nil
}

func withSecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Security-Policy", cspPolicy)
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}
