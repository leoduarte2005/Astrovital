// Package ipc implements the TCP client to the Edge AI worker (127.0.0.1:5006)
// with uint32 BE framing, HiPri/LoPri queues, req_id correlation, watchdog and reconnect.
package ipc

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	HiPriCap               = 16
	LoPriCap               = 8
	DefaultAddr            = "127.0.0.1:5006"
	DefaultCrewAckTimeout  = 2 * time.Second
	DefaultChatTimeout     = 0 * time.Second // unlimited: wait for local SLM to finish thinking
	DefaultCalibTimeout    = 2 * time.Second
	DefaultWriteTimeout    = 1 * time.Second
	DefaultSilenceWatchdog = 3 * time.Second
	DefaultSweepInterval   = 100 * time.Millisecond
	DefaultMinBackoff      = 250 * time.Millisecond
	DefaultMaxBackoff      = 5 * time.Second
	DefaultMaxWindowAge    = 1 * time.Second
)

var (
	ErrAIUnavailable = errors.New("ai_unavailable")
	ErrTimeout       = errors.New("ipc: request timeout")
	ErrClosed        = errors.New("ipc: closed")
)

// DialFunc allows injecting net.Pipe or custom transports in tests.
type DialFunc func(ctx context.Context, addr string) (net.Conn, error)

// Config configures the IPC client.
type Config struct {
	Addr            string
	Dial            DialFunc
	CrewAckTimeout  time.Duration
	ChatTimeout     time.Duration
	CalibTimeout    time.Duration
	WriteTimeout    time.Duration
	SilenceWatchdog time.Duration
	SweepInterval   time.Duration
	MinBackoff      time.Duration
	MaxBackoff      time.Duration
	MaxWindowAge    time.Duration
}

// Deps holds optional callbacks and logger.
type Deps struct {
	Logger       *slog.Logger
	OnReconnect  func()
	OnDisconnect func()
}

// InferenceMsg carries a decoded AI_INFERENCE frame.
type InferenceMsg struct {
	Env     contracts.IPCEnvelope
	Payload contracts.AIInferencePayload
}

// Stats holds IPC counters exposed in /api/metrics and CLUSTER_STATUS.
type Stats struct {
	AILink         string
	DroppedWindows uint64
	Reconnects     uint64
	ProtocolErrors uint64
	BadVersion     uint64
	StaleResp      uint64
}

type pendingReply struct {
	env *contracts.IPCEnvelope
	err error
}

type pendingReq struct {
	typ      contracts.IPCMsgType
	deadline time.Time
	replyCh  chan pendingReply
}

// Client owns the single TCP connection to the Edge AI worker.
type Client struct {
	cfg          Config
	log          *slog.Logger
	onReconnect  func()
	onDisconnect func()

	hiPriCh     chan contracts.IPCEnvelope
	loPriCh     chan contracts.IPCEnvelope
	inferenceCh chan InferenceMsg

	pendingMu sync.Mutex
	pending   map[uint64]pendingReq

	reqSeq atomic.Uint64

	connected   atomic.Bool
	degraded    atomic.Bool
	loPriActive atomic.Bool
	lastRxUs    atomic.Int64

	droppedWindows atomic.Uint64
	reconnects     atomic.Uint64
	protocolErrors atomic.Uint64
	badVersion     atomic.Uint64
	staleResp      atomic.Uint64
	hasConnected   atomic.Bool
}

// New constructs an IPC Client.
func New(cfg Config, deps Deps) (*Client, error) {
	if cfg.Addr == "" {
		cfg.Addr = DefaultAddr
	}
	if cfg.CrewAckTimeout <= 0 {
		cfg.CrewAckTimeout = DefaultCrewAckTimeout
	}
	if cfg.ChatTimeout < 0 {
		cfg.ChatTimeout = DefaultChatTimeout
	}
	if cfg.CalibTimeout <= 0 {
		cfg.CalibTimeout = DefaultCalibTimeout
	}
	if cfg.WriteTimeout <= 0 {
		cfg.WriteTimeout = DefaultWriteTimeout
	}
	if cfg.SilenceWatchdog <= 0 {
		cfg.SilenceWatchdog = DefaultSilenceWatchdog
	}
	if cfg.SweepInterval <= 0 {
		cfg.SweepInterval = DefaultSweepInterval
	}
	if cfg.MinBackoff <= 0 {
		cfg.MinBackoff = DefaultMinBackoff
	}
	if cfg.MaxBackoff <= 0 {
		cfg.MaxBackoff = DefaultMaxBackoff
	}
	if cfg.MaxWindowAge <= 0 {
		cfg.MaxWindowAge = DefaultMaxWindowAge
	}
	if cfg.Dial == nil {
		cfg.Dial = func(ctx context.Context, addr string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "tcp", addr)
		}
	}
	log := deps.Logger
	if log == nil {
		log = slog.Default()
	}
	return &Client{
		cfg:          cfg,
		log:          log,
		onReconnect:  deps.OnReconnect,
		onDisconnect: deps.OnDisconnect,
		hiPriCh:      make(chan contracts.IPCEnvelope, HiPriCap),
		loPriCh:      make(chan contracts.IPCEnvelope, LoPriCap),
		inferenceCh:  make(chan InferenceMsg, 16),
		pending:      make(map[uint64]pendingReq),
	}, nil
}

// InferenceCh returns the non-blocking stream of AI_INFERENCE payloads.
func (c *Client) InferenceCh() <-chan InferenceMsg { return c.inferenceCh }

// Connected reports whether the TCP link is currently up.
func (c *Client) Connected() bool { return c.connected.Load() }

// Stats returns current IPC status and counters.
func (c *Client) Stats() Stats {
	link := "offline"
	if c.connected.Load() {
		if c.degraded.Load() {
			link = "degraded"
		} else {
			link = "online"
		}
	}
	return Stats{
		AILink:         link,
		DroppedWindows: c.droppedWindows.Load(),
		Reconnects:     c.reconnects.Load(),
		ProtocolErrors: c.protocolErrors.Load(),
		BadVersion:     c.badVersion.Load(),
		StaleResp:      c.staleResp.Load(),
	}
}
