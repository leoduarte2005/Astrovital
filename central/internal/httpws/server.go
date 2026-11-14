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

// ExtraMetrics holds transport, IPC, pipeline, and cluster counters surfaced in /api/metrics.
type ExtraMetrics struct {
	DroppedFrames     uint64
	DroppedCtrl       uint64
	IPCDroppedWindows uint64
	IPCReconnects     uint64
	LateFrames        uint64
	FailoverLastMs    int64
}

// CrewProfileDTO is returned by GET /api/crew/{id}/profile.
type CrewProfileDTO struct {
	Profile             contracts.CrewProfile          `json:"profile"`
	BaselinePath        string                         `json:"baseline_path,omitempty"`
	CalibrationRequired bool                           `json:"calibration_required"`
	Thresholds          map[string]contracts.Threshold `json:"thresholds,omitempty"`
}

// ExtendedReader supplies optional clinical REST queries without coupling httpws to store.
type ExtendedReader interface {
	GetCrewProfile(ctx context.Context, id string) (CrewProfileDTO, error)
	QueryTimeseries(ctx context.Context, crewID, metric string, fromUs, toUs int64, bucketSec int) (contracts.TimeseriesResponse, error)
	GetProtocol(ctx context.Context, id string) (contracts.ProtocolDTO, error)
	ListAlerts(ctx context.Context, limit int) ([]contracts.AlertRecord, error)
	ListOutbox(ctx context.Context) ([]contracts.OutboxRecord, error)
}

// SessionCommander routes validated WS client commands to internal/session.
type SessionCommander interface {
	SetCrew(ctx context.Context, crewID string) (contracts.CrewStatePayload, error)
	HandleChatMsg(ctx context.Context, crewID, text string) (contracts.ChatReplyPayload, error)
	HandleSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload) error
	HandleCalibrationStep(ctx context.Context, crewID string, step contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error)
}

// DevController enables optional /api/dev/* simulation endpoints when injected.
type DevController interface {
	SetScenario(ctx context.Context, scenario string, seed int64) error
	KillNode(ctx context.Context, nodeID uint8) error
	ReviveNode(ctx context.Context, nodeID uint8) error
}

// Config configures the HTTP/WS server.
type Config struct {
	Addr string
	WSHz int
}

// Deps holds injected dependencies (all optional except Logger/Reader when used).
type Deps struct {
	Logger          *slog.Logger
	Reader          Reader
	ExtendedReader  ExtendedReader
	Session         SessionCommander
	Dev             DevController
	StoreStats      func() StoreStats
	ExtraMetrics    func() ExtraMetrics
	CrewStateFn     func() contracts.CrewStatePayload
	ClusterStatusFn func() contracts.ClusterStatusPayload
}

// MetricsSnapshot is the JSON payload returned by GET /api/metrics.
type MetricsSnapshot struct {
	WSClients          int64  `json:"ws_clients"`
	WSDroppedTelemetry int64  `json:"ws_dropped_telemetry"`
	StoreCommits       int64  `json:"store_commits"`
	StoreBacklog       int64  `json:"store_backlog"`
	DroppedFrames      uint64 `json:"dropped_frames"`
	DroppedCtrl        uint64 `json:"dropped_ctrl"`
	IPCDroppedWindows  uint64 `json:"ipc_dropped_windows"`
	IPCReconnects      uint64 `json:"ipc_reconnects"`
	LateFrames         uint64 `json:"late_frames"`
	FailoverLastMs     int64  `json:"failover_last_ms"`
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

// Metrics returns current HTTP/WS + store + transport/pipeline/cluster counters.
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
	if s.deps.ExtraMetrics != nil {
		ex := s.deps.ExtraMetrics()
		m.DroppedFrames = ex.DroppedFrames
		m.DroppedCtrl = ex.DroppedCtrl
		m.IPCDroppedWindows = ex.IPCDroppedWindows
		m.IPCReconnects = ex.IPCReconnects
		m.LateFrames = ex.LateFrames
		m.FailoverLastMs = ex.FailoverLastMs
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
