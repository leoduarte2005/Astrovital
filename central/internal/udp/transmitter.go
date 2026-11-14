package udp

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

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

	mu      sync.Mutex
	conn    *net.UDPConn
	dstAddr *net.UDPAddr
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
	return nil
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
	t.mu.Unlock()
	if conn == nil || dst == nil {
		return fmt.Errorf("udp transmitter: socket not bound")
	}
	if _, err := conn.WriteToUDP(raw, dst); err != nil {
		return fmt.Errorf("udp transmitter write: %w", err)
	}
	return nil
}
