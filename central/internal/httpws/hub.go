package httpws

import (
	"context"
	"encoding/json"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"

	"edgespace/central/internal/contracts"
)

const (
	clientTeleBuf  = 8
	clientEventBuf = 16
)

type wsHub struct {
	srv      *Server
	log      *slog.Logger
	interval time.Duration

	mu      sync.RWMutex
	clients map[*wsClient]struct{}

	clientsCount     atomic.Int64
	droppedTelemetry atomic.Int64
}

func newWSHub(srv *Server, log *slog.Logger, interval time.Duration) *wsHub {
	return &wsHub{
		srv:      srv,
		log:      log,
		interval: interval,
		clients:  make(map[*wsClient]struct{}),
	}
}

func (h *wsHub) run(ctx context.Context) {
	ticker := time.NewTicker(h.interval)
	defer ticker.Stop()

	for {
		select {
		case ev := <-h.srv.eventCh:
			h.broadcastEvent(ev)
		case <-ticker.C:
			h.broadcastTelemetry()
		case <-ctx.Done():
			return
		}
	}
}

func (h *wsHub) addClient(c *wsClient) {
	h.mu.Lock()
	h.clients[c] = struct{}{}
	h.mu.Unlock()
	h.clientsCount.Add(1)
}

func (h *wsHub) removeClient(c *wsClient) {
	h.mu.Lock()
	_, exists := h.clients[c]
	if exists {
		delete(h.clients, c)
	}
	h.mu.Unlock()
	if exists {
		h.clientsCount.Add(-1)
	}
}

func (h *wsHub) closeAllGoingAway() {
	h.mu.RLock()
	list := make([]*wsClient, 0, len(h.clients))
	for c := range h.clients {
		list = append(list, c)
	}
	h.mu.RUnlock()

	for _, c := range list {
		c := c
		go c.closeWith(websocket.StatusGoingAway, "server shutting down")
	}
}

func (h *wsHub) broadcastTelemetry() {
	raw, err := h.buildTelemetryFrameBytes()
	if err != nil {
		h.log.Error("marshal telemetry frame failed", "err", err)
		return
	}
	h.mu.RLock()
	for c := range h.clients {
		select {
		case c.teleCh <- raw:
		default:
			h.droppedTelemetry.Add(1)
		}
	}
	h.mu.RUnlock()
}

func (h *wsHub) broadcastEvent(ev contracts.WSEnvelope) {
	raw, err := json.Marshal(ev)
	if err != nil {
		h.log.Error("marshal ws event failed", "err", err)
		return
	}
	var slow []*wsClient
	h.mu.RLock()
	for c := range h.clients {
		select {
		case c.evCh <- raw:
		default:
			slow = append(slow, c)
		}
	}
	h.mu.RUnlock()

	for _, c := range slow {
		h.log.Warn("disconnecting slow ws client on event")
		c.closeWith(websocket.StatusPolicyViolation, "slow consumer")
	}
}

func (h *wsHub) buildTelemetryFrameBytes() ([]byte, error) {
	snap := h.srv.latest.Load()
	nowUs := time.Now().UnixMicro()
	var crewID *string
	var payload contracts.TelemetryFramePayload
	if snap != nil {
		nowUs = snap.TsUs
		crewID = snap.CrewID
		subs := make([]contracts.SubsystemState, len(snap.Subsystems))
		copy(subs, snap.Subsystems[:])
		payload = contracts.TelemetryFramePayload{
			Vitals:      snap.Vitals,
			Environment: snap.Environment,
			Subsystems:  subs,
			AIReady:     snap.AIReady,
		}
	} else {
		payload = defaultTelemetryPayload()
	}
	env, err := contracts.NewWSEnvelope(contracts.WSMsgTelemetryFrame, nowUs, crewID, nil, payload)
	if err != nil {
		return nil, err
	}
	return json.Marshal(env)
}

func defaultTelemetryPayload() contracts.TelemetryFramePayload {
	return contracts.TelemetryFramePayload{
		Subsystems: []contracts.SubsystemState{
			{Subsystem: contracts.SubsystemCardiovascularFluids, Severity: contracts.SeverityGreen},
			{Subsystem: contracts.SubsystemRespiratoryAtmosphere, Severity: contracts.SeverityGreen},
			{Subsystem: contracts.SubsystemNeuroOcularSANS, Severity: contracts.SeverityGreen},
			{Subsystem: contracts.SubsystemMusculoskeletalPosture, Severity: contracts.SeverityGreen},
			{Subsystem: contracts.SubsystemImmuneHematoNutrition, Severity: contracts.SeverityGreen},
			{Subsystem: contracts.SubsystemNeurobehavioralRadiation, Severity: contracts.SeverityGreen},
		},
		AIReady: false,
	}
}
