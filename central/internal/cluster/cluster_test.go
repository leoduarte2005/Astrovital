package cluster

import (
	"context"
	"errors"
	"fmt"
	"math/bits"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

type fakeClock struct {
	mu  sync.Mutex
	now time.Time
}

func newFakeClock() *fakeClock {
	return &fakeClock{now: time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)}
}

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *fakeClock) Advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

type memRegistry struct {
	mu   sync.Mutex
	data map[string]uint8
}

func newMemRegistry() *memRegistry {
	return &memRegistry{data: make(map[string]uint8)}
}

func (r *memRegistry) LoadNodeIDs(_ context.Context) (map[string]uint8, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]uint8, len(r.data))
	for k, v := range r.data {
		out[k] = v
	}
	return out, nil
}

func (r *memRegistry) SaveNodeID(_ context.Context, mac string, nodeID uint8) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.data[mac] = nodeID
	return nil
}

func drainStatusCh(ch <-chan contracts.ClusterSnapshot) {
	for {
		select {
		case <-ch:
		default:
			return
		}
	}
}

func nodeState(snap contracts.ClusterSnapshot, id uint8) (contracts.NodeStatus, bool) {
	for _, n := range snap.Nodes {
		if n.NodeID == id {
			return n, true
		}
	}
	return contracts.NodeStatus{}, false
}

func TestStableMACToNodeIDAcrossReboot(t *testing.T) {
	ctx := context.Background()
	clk := newFakeClock()
	reg := newMemRegistry()

	m1 := New(Config{Now: clk.Now}, reg)
	if err := m1.Load(ctx); err != nil {
		t.Fatalf("m1.Load: %v", err)
	}
	id0, err := m1.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:01"})
	if err != nil || id0 != 0 {
		t.Fatalf("first node id=%d err=%v, want 0", id0, err)
	}
	id1, err := m1.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:02"})
	if err != nil || id1 != 1 {
		t.Fatalf("second node id=%d err=%v, want 1", id1, err)
	}

	// Simulate reboot: new Manager loading from the same RegistryStore, nodes reconnect in reverse order.
	m2 := New(Config{Now: clk.Now}, reg)
	if err := m2.Load(ctx); err != nil {
		t.Fatalf("m2.Load: %v", err)
	}
	got1, err := m2.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:02"})
	if err != nil || got1 != 1 {
		t.Fatalf("reboot node2 id=%d err=%v, want 1", got1, err)
	}
	got0, err := m2.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:01"})
	if err != nil || got0 != 0 {
		t.Fatalf("reboot node1 id=%d err=%v, want 0", got0, err)
	}
}

func TestFullFSMAndReturnHysteresis(t *testing.T) {
	ctx := context.Background()
	clk := newFakeClock()
	m := New(Config{Now: clk.Now}, nil) // nil RegistryStore allowed in tests

	mac := "10:20:30:40:50:01"
	id, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{
		MAC:         mac,
		Peripherals: []contracts.Peripheral{contracts.PeripheralMAX30102},
	})
	if err != nil {
		t.Fatalf("HandleNodeHello: %v", err)
	}

	// DISCOVERED after NODE_HELLO
	ns, ok := nodeState(m.Status(), id)
	if !ok || ns.State != contracts.NodeStateDiscovered {
		t.Fatalf("after hello state=%v ok=%v, want DISCOVERED", ns.State, ok)
	}

	// 1st HEARTBEAT -> SYNCING
	clk.Advance(50 * time.Millisecond)
	if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id, RSSIDbm: -42}); err != nil {
		t.Fatalf("hb1: %v", err)
	}
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateSyncing {
		t.Fatalf("after hb1 state=%v, want SYNCING", ns.State)
	}

	// 2nd HEARTBEAT -> still SYNCING (hysteresis)
	clk.Advance(100 * time.Millisecond)
	if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id, RSSIDbm: -40}); err != nil {
		t.Fatalf("hb2: %v", err)
	}
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateSyncing {
		t.Fatalf("after hb2 state=%v, want SYNCING", ns.State)
	}

	// 3rd HEARTBEAT -> ACTIVE
	clk.Advance(100 * time.Millisecond)
	if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id, RSSIDbm: -38}); err != nil {
		t.Fatalf("hb3: %v", err)
	}
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateActive || ns.RSSIDbm != -38 {
		t.Fatalf("after hb3 state=%v rssi=%d, want ACTIVE/-38", ns.State, ns.RSSIDbm)
	}

	// Peripheral bitmap update via PERIPHERAL_DATA
	m.HandlePeripherals(id, []contracts.PeripheralReading{
		{Type: contracts.PeripheralSCD40, Value: 450, Unit: "ppm"},
		{Type: contracts.PeripheralBME280, Value: 22.5, Unit: "C"},
	})
	wantMask := PeriphBitMAX30102 | PeriphBitBME280 | PeriphBitSCD40
	if got := m.PeripheralMask(id); got != wantMask {
		t.Fatalf("PeripheralMask=%03b, want %03b", got, wantMask)
	}

	// 2 cycles (200ms) without packet -> SUSPECT
	clk.Advance(200 * time.Millisecond)
	m.Tick(ctx)
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateSuspect {
		t.Fatalf("at 200ms state=%v, want SUSPECT", ns.State)
	}

	// 3rd cycle (300ms total) -> LOST
	clk.Advance(100 * time.Millisecond)
	m.Tick(ctx)
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateLost {
		t.Fatalf("at 300ms state=%v, want LOST", ns.State)
	}

	// Return hysteresis: LOST -> SYNCING; 2 heartbeats do NOT activate, 3rd activates.
	clk.Advance(100 * time.Millisecond)
	_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id})
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateSyncing {
		t.Fatalf("return hb1 state=%v, want SYNCING", ns.State)
	}

	clk.Advance(100 * time.Millisecond)
	_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id})
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateSyncing {
		t.Fatalf("return hb2 state=%v, want SYNCING (2 HBs must not activate)", ns.State)
	}

	clk.Advance(100 * time.Millisecond)
	_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id})
	ns, _ = nodeState(m.Status(), id)
	if ns.State != contracts.NodeStateActive {
		t.Fatalf("return hb3 state=%v, want ACTIVE", ns.State)
	}
}

func activateNodes(t *testing.T, ctx context.Context, m *Manager, clk *fakeClock, count int) []uint8 {
	t.Helper()
	ids := make([]uint8, count)
	for i := 0; i < count; i++ {
		mac := string([]byte{'M', 'A', 'C', ':', '0' + byte(i)})
		id, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: mac})
		if err != nil {
			t.Fatalf("hello %d: %v", i, err)
		}
		ids[i] = id
	}
	for hb := 0; hb < 3; hb++ {
		clk.Advance(100 * time.Millisecond)
		for _, id := range ids {
			if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id}); err != nil {
				t.Fatalf("hb %d node %d: %v", hb, id, err)
			}
		}
	}
	return ids
}

func TestFailoverSlotMapAndTiming(t *testing.T) {
	ctx := context.Background()
	clk := newFakeClock()
	m := New(Config{Now: clk.Now}, nil)

	ids := activateNodes(t, ctx, m, clk, 5)
	sm5 := m.SlotMap()
	if sm5.ActiveNodes != 5 || sm5.SlotMs != 20 || sm5.ActiveNodeMask != 0x1F {
		t.Fatalf("5 nodes SlotMap = %+v", sm5)
	}
	if sm5.ActiveLinks != 20 || bits.OnesCount32(sm5.ActiveLinkMask) != 20 {
		t.Fatalf("5 nodes links=%d maskBits=%d, want 20/20", sm5.ActiveLinks, bits.OnesCount32(sm5.ActiveLinkMask))
	}

	// Node 4 stops sending; nodes 0..3 keep sending every 100ms.
	drainStatusCh(m.StatusCh())
	for step := 1; step <= 3; step++ {
		clk.Advance(100 * time.Millisecond)
		for _, id := range ids[:4] {
			if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id}); err != nil {
				t.Fatalf("keepalive hb node %d: %v", id, err)
			}
		}
		m.Tick(ctx)
		if step == 2 {
			ns, _ := nodeState(m.Status(), ids[4])
			if ns.State != contracts.NodeStateSuspect {
				t.Fatalf("step 2 node4 state=%v, want SUSPECT", ns.State)
			}
		}
	}

	// At 300ms: node 4 -> LOST, SlotMap recalculated for K=4 (slot_ms=25, 12 links), failover <= 400ms.
	sm4 := m.SlotMap()
	if sm4.ActiveNodes != 4 || sm4.SlotMs != 25 || sm4.ActiveNodeMask != 0x0F {
		t.Fatalf("4 nodes SlotMap = %+v", sm4)
	}
	if sm4.ActiveLinks != 12 || bits.OnesCount32(sm4.ActiveLinkMask) != 12 {
		t.Fatalf("4 nodes links=%d maskBits=%d, want 12/12", sm4.ActiveLinks, bits.OnesCount32(sm4.ActiveLinkMask))
	}
	if fms := m.FailoverLastMs(); fms <= 0 || fms > 400 {
		t.Fatalf("FailoverLastMs=%d, want (0, 400]", fms)
	}

	// Node 3 also drops -> K=3 (slot_ms=33, 6 links).
	for step := 1; step <= 3; step++ {
		clk.Advance(100 * time.Millisecond)
		for _, id := range ids[:3] {
			_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id})
		}
		m.Tick(ctx)
	}
	sm3 := m.SlotMap()
	if sm3.ActiveNodes != 3 || sm3.SlotMs != 33 || sm3.ActiveLinks != 6 || bits.OnesCount32(sm3.ActiveLinkMask) != 6 {
		t.Fatalf("3 nodes SlotMap = %+v", sm3)
	}

	// Verify StatusCh receives updates on state change and 1 Hz tick.
	drainStatusCh(m.StatusCh())
	for step := 0; step < 10; step++ {
		clk.Advance(100 * time.Millisecond)
		for _, id := range ids[:3] {
			_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: id})
		}
		m.Tick(ctx)
	}
	select {
	case snap := <-m.StatusCh():
		if snap.ActiveLinks != 6 || snap.TotalLinks != MaxLinks {
			t.Fatalf("1Hz snapshot links=%d/%d, want 6/20", snap.ActiveLinks, snap.TotalLinks)
		}
	default:
		t.Fatal("expected StatusCh snapshot on 1 Hz tick")
	}
}

func TestConcurrentTicksAndHeartbeatsConsistencyAndUnknownMAC(t *testing.T) {
	ctx := context.Background()
	m := New(Config{}, nil)

	for i := 0; i < MaxNodes; i++ {
		mac := fmt.Sprintf("02:ED:6E:00:00:%02X", i)
		if _, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: mac}); err != nil {
			t.Fatalf("hello %d: %v", i, err)
		}
	}

	// 6th unknown MAC must return ErrClusterFull without crashing or corrupting existing nodes.
	if _, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "02:ED:6E:00:00:FF"}); !errors.Is(err, ErrClusterFull) {
		t.Fatalf("6th HandleNodeHello err=%v, want ErrClusterFull", err)
	}
	if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{MAC: "02:ED:6E:00:00:FE"}); !errors.Is(err, ErrClusterFull) {
		t.Fatalf("6th HandleHeartbeat err=%v, want ErrClusterFull", err)
	}
	if err := m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: 99}); !errors.Is(err, ErrUnknownNode) {
		t.Fatalf("unknown node_id err=%v, want ErrUnknownNode", err)
	}

	stop := make(chan struct{})
	var wg sync.WaitGroup

	// 5 concurrent heartbeat + packet-seen writers.
	for id := uint8(0); id < MaxNodes; id++ {
		wg.Add(1)
		go func(nodeID uint8) {
			defer wg.Done()
			for i := 0; i < 200; i++ {
				select {
				case <-stop:
					return
				default:
				}
				_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{NodeID: nodeID, RSSIDbm: -45 - int(nodeID)})
				m.HandlePacketSeen(nodeID, -45-int(nodeID))
				time.Sleep(500 * time.Microsecond)
			}
		}(id)
	}

	// Concurrent Tick caller.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 150; i++ {
			select {
			case <-stop:
				return
			default:
			}
			m.Tick(ctx)
			time.Sleep(500 * time.Microsecond)
		}
	}()

	// Concurrent SlotMap invariant verifier.
	for i := 0; i < 200; i++ {
		sm := m.SlotMap()
		if bits.OnesCount32(sm.ActiveLinkMask) != sm.ActiveLinks {
			close(stop)
			wg.Wait()
			t.Fatalf("SlotMap inconsistent: OnesCount32(%#x)=%d != ActiveLinks=%d", sm.ActiveLinkMask, bits.OnesCount32(sm.ActiveLinkMask), sm.ActiveLinks)
		}
		if bits.OnesCount8(sm.ActiveNodeMask) != sm.ActiveNodes {
			close(stop)
			wg.Wait()
			t.Fatalf("SlotMap inconsistent: OnesCount8(%#x)=%d != ActiveNodes=%d", sm.ActiveNodeMask, bits.OnesCount8(sm.ActiveNodeMask), sm.ActiveNodes)
		}
		expectedLinks := 0
		if sm.ActiveNodes > 1 {
			expectedLinks = sm.ActiveNodes * (sm.ActiveNodes - 1)
		}
		if sm.ActiveLinks != expectedLinks {
			close(stop)
			wg.Wait()
			t.Fatalf("SlotMap ActiveLinks=%d, want %d for ActiveNodes=%d", sm.ActiveLinks, expectedLinks, sm.ActiveNodes)
		}
		if fms := m.FailoverLastMs(); fms > 400 {
			close(stop)
			wg.Wait()
			t.Fatalf("FailoverLastMs=%d > 400", fms)
		}
		time.Sleep(500 * time.Microsecond)
	}

	close(stop)
	wg.Wait()
}

func TestPeersAndNodeIDForMAC(t *testing.T) {
	ctx := context.Background()
	clk := newFakeClock()
	m := New(Config{Now: clk.Now}, nil)

	id0, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:01"})
	if err != nil || id0 != 0 {
		t.Fatalf("HandleNodeHello 0: id=%d err=%v", id0, err)
	}
	id1, err := m.HandleNodeHello(ctx, contracts.NodeHelloPayload{MAC: "AA:BB:CC:DD:EE:02"})
	if err != nil || id1 != 1 {
		t.Fatalf("HandleNodeHello 1: id=%d err=%v", id1, err)
	}
	for i := 0; i < 3; i++ {
		clk.Advance(50 * time.Millisecond)
		_ = m.HandleHeartbeat(ctx, contracts.HeartbeatPayload{MAC: "AA:BB:CC:DD:EE:01"})
	}

	gotID, gotSlot, ok := m.NodeIDForMAC("AA:BB:CC:DD:EE:01")
	if !ok || gotID != 0 || gotSlot != 0 {
		t.Fatalf("NodeIDForMAC 0 = (%d, %d, %v), want (0, 0, true)", gotID, gotSlot, ok)
	}
	peers := m.Peers()
	if len(peers) != 2 || peers[0] != "AA:BB:CC:DD:EE:01" || peers[1] != "AA:BB:CC:DD:EE:02" {
		t.Fatalf("Peers() = %+v", peers)
	}
}

