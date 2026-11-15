package cluster

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	// SuspectAfter is 2 missed 100ms cycles without a packet from a node.
	SuspectAfter = 200 * time.Millisecond
	// LostAfter is the 3rd missed 100ms cycle without a packet from a node.
	LostAfter = 300 * time.Millisecond
	// RequiredSyncHeartbeats is the number of consecutive heartbeats needed to transition SYNCING -> ACTIVE.
	RequiredSyncHeartbeats = 3
	// DefaultScanInterval is the FSM sweep interval in Run.
	DefaultScanInterval = 100 * time.Millisecond
	// DefaultStatusInterval is the periodic ClusterSnapshot emission rate (1 Hz).
	DefaultStatusInterval = 1 * time.Second
)

var (
	// ErrMissingMAC is returned when a NODE_HELLO lacks a MAC address.
	ErrMissingMAC = errors.New("cluster: missing node MAC")
	// ErrClusterFull is returned when all 5 node IDs (0..4) are already assigned.
	ErrClusterFull = errors.New("cluster: max 5 nodes already registered")
	// ErrUnknownNode is returned when a packet arrives for an unregistered node without MAC.
	ErrUnknownNode = errors.New("cluster: unknown node_id")
)

// RegistryStore persists stable MAC -> node_id (0..4) mappings across reboots (P5).
// Optional: may be nil in tests.
type RegistryStore interface {
	LoadNodeIDs(ctx context.Context) (map[string]uint8, error)
	SaveNodeID(ctx context.Context, mac string, nodeID uint8) error
}

// Config configures a Manager.
type Config struct {
	Now            func() time.Time
	ScanInterval   time.Duration
	StatusInterval time.Duration
	AILink         string
}

type nodeEntry struct {
	id            uint8
	mac           string
	fwVersion     string
	state         contracts.NodeState
	periphMask    uint8
	rssiDBm       int
	lastSeen      time.Time
	consecutiveHB int
}

// Manager owns the cluster node registry, liveness FSM, and TDM SlotMap.
type Manager struct {
	store          RegistryStore
	now            func() time.Time
	scanInterval   time.Duration
	statusInterval time.Duration
	aiLink         string

	mu             sync.Mutex
	loaded         bool
	macToID        map[string]uint8
	usedIDs        [MaxNodes]bool
	nodes          map[uint8]*nodeEntry
	slotVersion    uint64
	lastStatusEmit time.Time

	slotMap        atomic.Pointer[SlotMap]
	failoverLastMs atomic.Int64
	statusCh       chan contracts.ClusterSnapshot
}

// New creates a Manager with optional RegistryStore (may be nil in tests).
func New(cfg Config, store RegistryStore) *Manager {
	nowFn := cfg.Now
	if nowFn == nil {
		nowFn = time.Now
	}
	scanInt := cfg.ScanInterval
	if scanInt <= 0 {
		scanInt = DefaultScanInterval
	}
	statusInt := cfg.StatusInterval
	if statusInt <= 0 {
		statusInt = DefaultStatusInterval
	}
	m := &Manager{
		store:          store,
		now:            nowFn,
		scanInterval:   scanInt,
		statusInterval: statusInt,
		aiLink:         cfg.AILink,
		macToID:        make(map[string]uint8, MaxNodes),
		nodes:          make(map[uint8]*nodeEntry, MaxNodes),
		statusCh:       make(chan contracts.ClusterSnapshot, 16),
	}
	m.slotMap.Store(BuildSlotMap(0, 0))
	return m
}

// Load populates the MAC -> node_id registry from RegistryStore (idempotent).
func (m *Manager) Load(ctx context.Context) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.loaded {
		return nil
	}
	m.loaded = true
	if m.store == nil {
		return nil
	}
	entries, err := m.store.LoadNodeIDs(ctx)
	if err != nil {
		m.loaded = false
		return err
	}
	for rawMAC, id := range entries {
		mac := normalizeMAC(rawMAC)
		if mac == "" || id >= MaxNodes {
			continue
		}
		if _, exists := m.macToID[mac]; exists || m.usedIDs[id] {
			continue
		}
		m.macToID[mac] = id
		m.usedIDs[id] = true
	}
	return nil
}

// Run runs the 100ms FSM sweep and 1 Hz status emission loop until ctx is canceled.
func (m *Manager) Run(ctx context.Context) error {
	if err := m.Load(ctx); err != nil {
		return err
	}
	scanTicker := time.NewTicker(m.scanInterval)
	statusTicker := time.NewTicker(m.statusInterval)
	defer scanTicker.Stop()
	defer statusTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-scanTicker.C:
			m.Tick(ctx)
		case <-statusTicker.C:
			m.emitStatus(m.Status())
		}
	}
}

// SlotMap returns the latest immutable SlotMap lock-free.
func (m *Manager) SlotMap() *SlotMap {
	return m.slotMap.Load()
}

// FailoverLastMs returns the duration in ms of the last ACTIVE/SUSPECT -> LOST failover.
func (m *Manager) FailoverLastMs() int64 {
	return m.failoverLastMs.Load()
}

// StatusCh returns a read-only channel that emits ClusterSnapshot on state change and at 1 Hz.
func (m *Manager) StatusCh() <-chan contracts.ClusterSnapshot {
	return m.statusCh
}

// Status builds and returns the current ClusterSnapshot.
func (m *Manager) Status() contracts.ClusterSnapshot {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.buildSnapshotLocked(m.now())
}

// PeripheralMask returns the tracked peripheral bitmap for nodeID.
func (m *Manager) PeripheralMask(nodeID uint8) uint8 {
	m.mu.Lock()
	defer m.mu.Unlock()
	if n, ok := m.nodes[nodeID]; ok {
		return n.periphMask
	}
	return 0
}

// HandleNodeHello processes a NODE_HELLO message, assigns/reuses a stable node_id,
// and places the node in DISCOVERED state.
func (m *Manager) HandleNodeHello(ctx context.Context, p contracts.NodeHelloPayload) (uint8, error) {
	mac := normalizeMAC(p.MAC)
	if mac == "" {
		return 0, ErrMissingMAC
	}

	m.mu.Lock()
	now := m.now()
	id, err := m.resolveOrAssignNodeIDLocked(ctx, mac)
	if err != nil {
		m.mu.Unlock()
		return 0, err
	}

	entry, exists := m.nodes[id]
	wasActive := exists && entry.state == contracts.NodeStateActive
	if !exists {
		entry = &nodeEntry{id: id, mac: mac}
		m.nodes[id] = entry
	}
	entry.mac = mac
	if p.FWVersion != "" {
		entry.fwVersion = p.FWVersion
	}
	entry.state = contracts.NodeStateDiscovered
	entry.consecutiveHB = 0
	entry.lastSeen = now
	if len(p.Peripherals) > 0 {
		entry.periphMask |= PeripheralsToMask(p.Peripherals)
	}

	if wasActive {
		m.recalculateSlotMapLocked()
	}
	snap := m.buildSnapshotLocked(now)
	m.lastStatusEmit = now
	m.mu.Unlock()

	m.emitStatus(snap)
	return id, nil
}

// HandleHeartbeat processes a HEARTBEAT message, advancing DISCOVERED/LOST -> SYNCING -> ACTIVE
// with 3-heartbeat hysteresis and recovering SUSPECT -> ACTIVE.
func (m *Manager) HandleHeartbeat(ctx context.Context, p contracts.HeartbeatPayload) error {
	m.mu.Lock()
	now := m.now()

	entry, err := m.lookupEntryForHeartbeatLocked(ctx, p)
	if err != nil {
		m.mu.Unlock()
		return err
	}

	gap := now.Sub(entry.lastSeen)
	prevState := entry.state
	prevMask := entry.periphMask

	entry.lastSeen = now
	if p.RSSIDbm != 0 {
		entry.rssiDBm = p.RSSIDbm
	}
	if len(p.Peripherals) > 0 {
		entry.periphMask |= PeripheralsToMask(p.Peripherals)
	}

	switch entry.state {
	case contracts.NodeStateDiscovered, contracts.NodeStateLost:
		entry.state = contracts.NodeStateSyncing
		entry.consecutiveHB = 1
	case contracts.NodeStateSyncing:
		if gap >= SuspectAfter {
			entry.consecutiveHB = 1
		} else {
			entry.consecutiveHB++
		}
		if entry.consecutiveHB >= RequiredSyncHeartbeats {
			entry.state = contracts.NodeStateActive
		}
	case contracts.NodeStateSuspect:
		entry.state = contracts.NodeStateActive
		entry.consecutiveHB = RequiredSyncHeartbeats
	case contracts.NodeStateActive:
		// Keep ACTIVE.
	}

	stateChanged := entry.state != prevState
	if stateChanged && (entry.state == contracts.NodeStateActive || prevState == contracts.NodeStateActive) {
		m.recalculateSlotMapLocked()
	}

	var snap contracts.ClusterSnapshot
	shouldEmit := stateChanged || entry.periphMask != prevMask
	if shouldEmit {
		snap = m.buildSnapshotLocked(now)
		m.lastStatusEmit = now
	}
	m.mu.Unlock()

	if shouldEmit {
		m.emitStatus(snap)
	}
	return nil
}

// HandlePeripherals updates the node's peripheral bitmap and liveness if active/suspect.
func (m *Manager) HandlePeripherals(nodeID uint8, readings []contracts.PeripheralReading) {
	if nodeID >= MaxNodes || len(readings) == 0 {
		return
	}
	m.mu.Lock()
	entry, ok := m.nodes[nodeID]
	if !ok {
		m.mu.Unlock()
		return
	}
	now := m.now()
	prevState := entry.state
	prevMask := entry.periphMask

	for _, r := range readings {
		entry.periphMask |= PeripheralBit(r.Type)
	}
	if entry.state == contracts.NodeStateActive || entry.state == contracts.NodeStateSuspect {
		entry.lastSeen = now
		entry.state = contracts.NodeStateActive
	}

	shouldEmit := entry.state != prevState || entry.periphMask != prevMask
	var snap contracts.ClusterSnapshot
	if shouldEmit {
		snap = m.buildSnapshotLocked(now)
		m.lastStatusEmit = now
	}
	m.mu.Unlock()

	if shouldEmit {
		m.emitStatus(snap)
	}
}

// HandlePacketSeen updates liveness and RSSI when a data packet (e.g. CSI_FRAME) arrives from nodeID.
func (m *Manager) HandlePacketSeen(nodeID uint8, rssiDBm int) {
	if nodeID >= MaxNodes {
		return
	}
	m.mu.Lock()
	entry, ok := m.nodes[nodeID]
	if !ok {
		m.mu.Unlock()
		return
	}
	now := m.now()
	prevState := entry.state
	if rssiDBm != 0 {
		entry.rssiDBm = rssiDBm
	}
	if entry.state == contracts.NodeStateActive || entry.state == contracts.NodeStateSuspect {
		entry.lastSeen = now
		entry.state = contracts.NodeStateActive
	}
	stateChanged := entry.state != prevState
	var snap contracts.ClusterSnapshot
	if stateChanged {
		snap = m.buildSnapshotLocked(now)
		m.lastStatusEmit = now
	}
	m.mu.Unlock()

	if stateChanged {
		m.emitStatus(snap)
	}
}

// Tick evaluates liveness timeouts (200ms -> SUSPECT, 300ms -> LOST), recalculates SlotMap on failover,
// and emits ClusterSnapshot on state changes or every StatusInterval (1 Hz).
func (m *Manager) Tick(_ context.Context) {
	m.mu.Lock()
	now := m.now()

	var stateChanged bool
	var slotMembershipChanged bool
	var failoverOccurred bool
	var maxFailoverMs int64

	for _, entry := range m.nodes {
		elapsed := now.Sub(entry.lastSeen)
		switch entry.state {
		case contracts.NodeStateActive:
			if elapsed >= LostAfter {
				entry.state = contracts.NodeStateLost
				entry.consecutiveHB = 0
				stateChanged = true
				slotMembershipChanged = true
				failoverOccurred = true
				if ms := elapsed.Milliseconds(); ms > maxFailoverMs {
					maxFailoverMs = ms
				}
			} else if elapsed >= SuspectAfter {
				entry.state = contracts.NodeStateSuspect
				stateChanged = true
			}
		case contracts.NodeStateSuspect:
			if elapsed >= LostAfter {
				entry.state = contracts.NodeStateLost
				entry.consecutiveHB = 0
				stateChanged = true
				slotMembershipChanged = true
				failoverOccurred = true
				if ms := elapsed.Milliseconds(); ms > maxFailoverMs {
					maxFailoverMs = ms
				}
			}
		case contracts.NodeStateSyncing:
			if elapsed >= LostAfter {
				entry.state = contracts.NodeStateLost
				entry.consecutiveHB = 0
				stateChanged = true
			} else if elapsed >= SuspectAfter {
				entry.consecutiveHB = 0
			}
		case contracts.NodeStateDiscovered:
			if elapsed >= LostAfter {
				entry.state = contracts.NodeStateLost
				entry.consecutiveHB = 0
				stateChanged = true
			}
		}
	}

	if slotMembershipChanged {
		m.recalculateSlotMapLocked()
	}
	if failoverOccurred {
		m.failoverLastMs.Store(maxFailoverMs)
	}

	periodicDue := m.lastStatusEmit.IsZero() || now.Sub(m.lastStatusEmit) >= m.statusInterval
	var snap contracts.ClusterSnapshot
	shouldEmit := stateChanged || periodicDue
	if shouldEmit {
		snap = m.buildSnapshotLocked(now)
		m.lastStatusEmit = now
	}
	m.mu.Unlock()

	if shouldEmit {
		m.emitStatus(snap)
	}
}

func (m *Manager) resolveOrAssignNodeIDLocked(ctx context.Context, mac string) (uint8, error) {
	if id, ok := m.macToID[mac]; ok {
		return id, nil
	}
	for id := uint8(0); id < MaxNodes; id++ {
		if !m.usedIDs[id] {
			if m.store != nil {
				if err := m.store.SaveNodeID(ctx, mac, id); err != nil {
					return 0, fmt.Errorf("cluster: save node_id: %w", err)
				}
			}
			m.macToID[mac] = id
			m.usedIDs[id] = true
			return id, nil
		}
	}
	return 0, ErrClusterFull
}

func (m *Manager) lookupEntryForHeartbeatLocked(ctx context.Context, p contracts.HeartbeatPayload) (*nodeEntry, error) {
	mac := normalizeMAC(p.MAC)
	if mac != "" {
		if id, ok := m.macToID[mac]; ok {
			entry, exists := m.nodes[id]
			if !exists {
				entry = &nodeEntry{id: id, mac: mac, state: contracts.NodeStateLost}
				m.nodes[id] = entry
			}
			return entry, nil
		}
		id, err := m.resolveOrAssignNodeIDLocked(ctx, mac)
		if err != nil {
			return nil, err
		}
		entry := &nodeEntry{
			id:    id,
			mac:   mac,
			state: contracts.NodeStateDiscovered,
		}
		m.nodes[id] = entry
		return entry, nil
	}

	if p.NodeID < MaxNodes {
		if entry, ok := m.nodes[p.NodeID]; ok {
			return entry, nil
		}
	}
	return nil, ErrUnknownNode
}

func (m *Manager) recalculateSlotMapLocked() {
	var activeMask uint8
	for id, entry := range m.nodes {
		if entry.state == contracts.NodeStateActive && id < MaxNodes {
			activeMask |= 1 << id
		}
	}
	m.slotVersion++
	m.slotMap.Store(BuildSlotMap(m.slotVersion, activeMask))
}

func (m *Manager) buildSnapshotLocked(now time.Time) contracts.ClusterSnapshot {
	sm := m.slotMap.Load()
	nodes := make([]contracts.NodeStatus, 0, len(m.nodes))
	for _, entry := range m.nodes {
		slot := -1
		if entry.state == contracts.NodeStateActive && int(entry.id) < MaxNodes {
			slot = sm.NodeSlot[entry.id]
		}
		nodes = append(nodes, contracts.NodeStatus{
			NodeID:      entry.id,
			MAC:         entry.mac,
			State:       entry.state,
			Slot:        slot,
			Peripherals: MaskToPeripherals(entry.periphMask),
			LastSeenUs:  entry.lastSeen.UnixMicro(),
			RSSIDbm:     entry.rssiDBm,
		})
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].NodeID < nodes[j].NodeID })

	return contracts.ClusterSnapshot{
		TsUs:        now.UnixMicro(),
		Nodes:       nodes,
		ActiveLinks: sm.ActiveLinks,
		TotalLinks:  MaxLinks,
		AILink:      m.aiLink,
	}
}

func (m *Manager) emitStatus(snap contracts.ClusterSnapshot) {
	select {
	case m.statusCh <- snap:
	default:
	}
}

// Peers returns a snapshot map of registered node_id -> MAC address.
func (m *Manager) Peers() map[uint8]string {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make(map[uint8]string, len(m.macToID))
	for mac, id := range m.macToID {
		out[id] = mac
	}
	return out
}

// NodeIDForMAC resolves the assigned node_id and current slot (-1 if inactive) for a MAC.
func (m *Manager) NodeIDForMAC(mac string) (uint8, int, bool) {
	norm := normalizeMAC(mac)
	if norm == "" {
		return 0, -1, false
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.macToID[norm]
	if !ok {
		return 0, -1, false
	}
	sm := m.slotMap.Load()
	slot := -1
	if sm != nil && int(id) < MaxNodes {
		slot = sm.NodeSlot[id]
	}
	return id, slot, true
}

func normalizeMAC(mac string) string {
	return strings.TrimSpace(mac)
}
