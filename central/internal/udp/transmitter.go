package udp

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"sort"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

// PeerEntry describes a registered node_id -> MAC pair shared with real ESP32-S3 hardware.
type PeerEntry struct {
	NodeID uint8  `json:"node_id"`
	MAC    string `json:"mac"`
}

// NodeAssignPayload is sent unicast to an ESP32-S3 node upon NODE_HELLO / resync
// so identical firmware binaries learn their assigned node_id, slot_id, and peer MAC table.
type NodeAssignPayload struct {
	V           int         `json:"v"`
	Type        string      `json:"type"`
	MAC         string      `json:"mac"`
	NodeID      uint8       `json:"node_id"`
	SlotID      int         `json:"slot_id"`
	CycleSeq    uint32      `json:"cycle_seq"`
	TimestampUs int64       `json:"timestamp_us"`
	Peers       []PeerEntry `json:"peers,omitempty"`
}

// TransmitterConfig configures a UDP Transmitter.
type TransmitterConfig struct {
	BroadcastAddr string
	TickInterval  time.Duration
	InitialMode   contracts.MissionMode
	Now           func() time.Time
}

// Transmitter broadcasts CLUSTER_SYNC at 10 Hz (100ms monotonic ticker) with
// monotonic cycle_seq (P1) and sends immediate MODE_CMD on mission mode updates.
type Transmitter struct {
	cfg          TransmitterConfig
	slotProvider SlotProvider
	tickInterval time.Duration
	now          func() time.Time

	slots atomic.Pointer[SlotPlan]
	mode  atomic.Value // contracts.MissionMode

	cycleSeq atomic.Uint32
	sentSync atomic.Uint64
	sentMode atomic.Uint64

	mu         sync.Mutex
	conn       *net.UDPConn
	dstAddr    *net.UDPAddr
	extraBcast []*net.UDPAddr
	peersMu    sync.RWMutex
	peers      map[string]*net.UDPAddr
}

// NewTransmitter creates a Transmitter. slotProvider may be nil (uses UpdateSlots).
func NewTransmitter(cfg TransmitterConfig, slotProvider SlotProvider) *Transmitter {
	bcast := cfg.BroadcastAddr
	if bcast == "" {
		bcast = "10.42.0.255:5005"
	}
	interval := cfg.TickInterval
	if interval <= 0 {
		interval = DefaultSyncInterval
	}
	mode := cfg.InitialMode
	if !mode.IsValid() {
		mode = contracts.ModeCabinTomography
	}
	nowFn := cfg.Now
	if nowFn == nil {
		nowFn = time.Now
	}
	cfg.BroadcastAddr = bcast
	t := &Transmitter{
		cfg:          cfg,
		slotProvider: slotProvider,
		tickInterval: interval,
		now:          nowFn,
		peers:        make(map[string]*net.UDPAddr),
	}
	t.mode.Store(mode)
	t.slots.Store(&SlotPlan{})
	return t
}

// Bind resolves BroadcastAddr and opens an outbound UDP socket.
func (t *Transmitter) Bind() error {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.conn != nil {
		return nil
	}
	dst, err := net.ResolveUDPAddr("udp", t.cfg.BroadcastAddr)
	if err != nil {
		return fmt.Errorf("udp transmitter resolve %q: %w", t.cfg.BroadcastAddr, err)
	}
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	if err != nil {
		return fmt.Errorf("udp transmitter listen: %w", err)
	}
	t.dstAddr = dst
	t.conn = conn
	if t.cfg.BroadcastAddr == "10.42.0.255:5005" {
		t.extraBcast = discoverInterfaceBroadcasts(dst.Port, dst.IP)
	} else {
		t.extraBcast = nil
	}
	return nil
}

// RegisterPeer remembers a discovered node's IP so CLUSTER_SYNC, MODE_CMD, and NODE_ASSIGN
// reach ESP32-S3 hardware even on Windows Hotspot / routed Wi-Fi LANs.
func (t *Transmitter) RegisterPeer(srcAddr string) {
	if srcAddr == "" {
		return
	}
	host, _, err := net.SplitHostPort(srcAddr)
	if err != nil || host == "" {
		return
	}
	port := 5005
	t.mu.Lock()
	if t.dstAddr != nil && t.dstAddr.Port > 0 {
		port = t.dstAddr.Port
	}
	t.mu.Unlock()

	target := net.JoinHostPort(host, strconv.Itoa(port))
	addr, err := net.ResolveUDPAddr("udp4", target)
	if err != nil {
		return
	}
	t.peersMu.Lock()
	t.peers[host] = addr
	t.peersMu.Unlock()
}

// SendNodeAssign sends a unicast NODE_ASSIGN packet to a node's source IP:5005.
func (t *Transmitter) SendNodeAssign(srcAddr, mac string, nodeID uint8, slotID int, peersMap map[uint8]string) error {
	if srcAddr == "" {
		return nil
	}
	if err := t.Bind(); err != nil {
		return err
	}
	host, _, err := net.SplitHostPort(srcAddr)
	if err != nil || host == "" {
		return fmt.Errorf("udp transmitter invalid peer %q", srcAddr)
	}
	port := 5005
	t.mu.Lock()
	conn := t.conn
	if t.dstAddr != nil && t.dstAddr.Port > 0 {
		port = t.dstAddr.Port
	}
	t.mu.Unlock()
	if conn == nil {
		return fmt.Errorf("udp transmitter: socket not bound")
	}

	dst, err := net.ResolveUDPAddr("udp4", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		return err
	}

	peers := make([]PeerEntry, 0, len(peersMap))
	for id, m := range peersMap {
		peers = append(peers, PeerEntry{NodeID: id, MAC: m})
	}
	sort.Slice(peers, func(i, j int) bool { return peers[i].NodeID < peers[j].NodeID })

	payload := NodeAssignPayload{
		V:           contracts.Version,
		Type:        "NODE_ASSIGN",
		MAC:         mac,
		NodeID:      nodeID,
		SlotID:      slotID,
		CycleSeq:    t.cycleSeq.Load(),
		TimestampUs: t.now().UnixMicro(),
		Peers:       peers,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = conn.WriteToUDP(raw, dst)
	return err
}

// UpdateSlots atomically replaces the internal SlotPlan used when SlotProvider is nil.
func (t *Transmitter) UpdateSlots(plan SlotPlan) {
	cp := SlotPlan{
		SlotMs:         plan.SlotMs,
		ActiveNodeMask: plan.ActiveNodeMask,
		Slots:          append([]contracts.SlotAssignment(nil), plan.Slots...),
	}
	t.slots.Store(&cp)
}

// Mode returns the current atomic MissionMode.
func (t *Transmitter) Mode() contracts.MissionMode {
	if v := t.mode.Load(); v != nil {
		if m, ok := v.(contracts.MissionMode); ok {
			return m
		}
	}
	return contracts.ModeCabinTomography
}

// CycleSeq returns the latest cycle_seq emitted by CLUSTER_SYNC.
func (t *Transmitter) CycleSeq() uint32 {
	return t.cycleSeq.Load()
}

// SentSyncCount returns the total CLUSTER_SYNC packets sent.
func (t *Transmitter) SentSyncCount() uint64 { return t.sentSync.Load() }

// SentModeCmdCount returns the total MODE_CMD packets sent.
func (t *Transmitter) SentModeCmdCount() uint64 { return t.sentMode.Load() }

// Run starts the 100ms monotonic ticker sending CLUSTER_SYNC until ctx is canceled.
func (t *Transmitter) Run(ctx context.Context) error {
	if err := t.Bind(); err != nil {
		return err
	}
	defer func() {
		t.mu.Lock()
		if t.conn != nil {
			_ = t.conn.Close()
			t.conn = nil
		}
		t.mu.Unlock()
	}()

	ticker := time.NewTicker(t.tickInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if err := t.SendSync(); err != nil && ctx.Err() == nil {
				return err
			}
		}
	}
}

// SendSync increments cycle_seq atomically, reads SlotPlan + MissionMode atomically,
// and broadcasts one CLUSTER_SYNC datagram.
func (t *Transmitter) SendSync() error {
	if err := t.Bind(); err != nil {
		return err
	}
	var plan SlotPlan
	if t.slotProvider != nil {
		plan = t.slotProvider.CurrentSlotPlan()
	} else if p := t.slots.Load(); p != nil {
		plan = *p
	}

	seq := t.cycleSeq.Add(1)
	payload := contracts.ClusterSyncPayload{
		V:              contracts.Version,
		Type:           contracts.UDPMsgClusterSync,
		CycleSeq:       seq,
		TimestampUs:    t.now().UnixMicro(),
		Mode:           t.Mode(),
		SlotMs:         plan.SlotMs,
		ActiveNodeMask: plan.ActiveNodeMask,
		Slots:          plan.Slots,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("udp transmitter marshal CLUSTER_SYNC: %w", err)
	}
	if err := t.writePacket(raw); err != nil {
		return err
	}
	t.sentSync.Add(1)
	return nil
}

// SendModeCmd atomically updates MissionMode and immediately broadcasts a MODE_CMD datagram.
func (t *Transmitter) SendModeCmd(mode contracts.MissionMode) error {
	if !mode.IsValid() {
		return fmt.Errorf("udp transmitter: invalid mission mode %q", mode)
	}
	if err := t.Bind(); err != nil {
		return err
	}
	t.mode.Store(mode)
	payload := contracts.ModeCmdPayload{
		V:           contracts.Version,
		Type:        contracts.UDPMsgModeCmd,
		Mode:        mode,
		TimestampUs: t.now().UnixMicro(),
		CycleSeq:    t.cycleSeq.Load(),
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("udp transmitter marshal MODE_CMD: %w", err)
	}
	if err := t.writePacket(raw); err != nil {
		return err
	}
	t.sentMode.Add(1)
	return nil
}

func (t *Transmitter) writePacket(raw []byte) error {
	t.mu.Lock()
	conn := t.conn
	dst := t.dstAddr
	extra := append([]*net.UDPAddr(nil), t.extraBcast...)
	t.mu.Unlock()
	if conn == nil || dst == nil {
		return fmt.Errorf("udp transmitter: socket not bound")
	}

	t.peersMu.RLock()
	peerAddrs := make([]*net.UDPAddr, 0, len(t.peers))
	for _, a := range t.peers {
		peerAddrs = append(peerAddrs, a)
	}
	t.peersMu.RUnlock()

	var firstErr error
	sentAny := false

	if _, err := conn.WriteToUDP(raw, dst); err != nil {
		firstErr = fmt.Errorf("udp transmitter write: %w", err)
	} else {
		sentAny = true
	}

	for _, b := range extra {
		if _, err := conn.WriteToUDP(raw, b); err == nil {
			sentAny = true
		}
	}
	for _, p := range peerAddrs {
		if _, err := conn.WriteToUDP(raw, p); err == nil {
			sentAny = true
		}
	}

	if !sentAny && firstErr != nil && len(extra) == 0 && len(peerAddrs) == 0 && t.cfg.BroadcastAddr != "10.42.0.255:5005" {
		return firstErr
	}
	return nil
}

func discoverInterfaceBroadcasts(port int, skipIP net.IP) []*net.UDPAddr {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	seen := make(map[string]struct{})
	if skipIP != nil {
		seen[skipIP.String()] = struct{}{}
	}
	var out []*net.UDPAddr
	for _, iface := range ifaces {
		if (iface.Flags&net.FlagUp) == 0 || (iface.Flags&net.FlagLoopback) != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			ipNet, ok := a.(*net.IPNet)
			if !ok || ipNet.IP == nil {
				continue
			}
			ip4 := ipNet.IP.To4()
			if ip4 == nil || len(ipNet.Mask) != 4 {
				continue
			}
			// Host routes / point-to-point links (e.g. VPN /32) and unconfigured
			// link-local adapters have no usable LAN broadcast address.
			if ones, _ := ipNet.Mask.Size(); ones >= 31 || ip4.IsLinkLocalUnicast() {
				continue
			}
			bcast := make(net.IP, 4)
			for i := 0; i < 4; i++ {
				bcast[i] = ip4[i] | ^ipNet.Mask[i]
			}
			key := bcast.String()
			if _, exists := seen[key]; exists {
				continue
			}
			seen[key] = struct{}{}
			out = append(out, &net.UDPAddr{IP: bcast, Port: port})
		}
	}
	return out
}
