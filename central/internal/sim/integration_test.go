package sim_test

import (
	"context"
	"encoding/json"
	"math/bits"
	"net"
	"sync"
	"testing"
	"time"

	"edgespace/central/internal/cluster"
	"edgespace/central/internal/contracts"
	"edgespace/central/internal/sim"
	"edgespace/central/internal/udp"
)

type udpChannelAdapter struct {
	sink *udp.ChannelSink
}

func (a *udpChannelAdapter) PushControl(ev sim.ControlEvent) bool {
	return a.sink.TrySendControl(udp.ControlMsg{
		Type:       ev.Type,
		Hello:      ev.Hello,
		Heartbeat:  ev.Heartbeat,
		ReceivedAt: ev.ReceivedAt,
		SrcAddr:    ev.SrcAddr,
	})
}

func (a *udpChannelAdapter) PushData(ev sim.DataEvent) bool {
	return a.sink.TrySendData(udp.DataMsg{
		Type:       ev.Type,
		CSI:        ev.CSI,
		Peripheral: ev.Peripheral,
		ReceivedAt: ev.ReceivedAt,
		SrcAddr:    ev.SrcAddr,
	})
}

type managerSlotProvider struct {
	mgr *cluster.Manager
}

func (p *managerSlotProvider) CurrentSlotPlan() udp.SlotPlan {
	sm := p.mgr.SlotMap()
	return udp.SlotPlan{
		SlotMs:         sm.SlotMs,
		ActiveNodeMask: sm.ActiveNodeMask,
		Slots:          sm.Slots,
	}
}

func TestIntegrationMockClusterUDPSinkClusterManagerAndTransmitter(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Loopback listener simulating ESP32-S3 cluster receiving CLUSTER_SYNC from udp.Transmitter.
	rxConn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 0})
	if err != nil {
		t.Fatalf("ListenUDP loopback: %v", err)
	}
	defer rxConn.Close()

	go func() {
		<-ctx.Done()
		_ = rxConn.Close()
	}()

	mgr := cluster.New(cluster.Config{
		ScanInterval:   50 * time.Millisecond,
		StatusInterval: 250 * time.Millisecond,
	}, nil)

	tx := udp.NewTransmitter(udp.TransmitterConfig{
		BroadcastAddr: rxConn.LocalAddr().String(),
		TickInterval:  50 * time.Millisecond,
		InitialMode:   contracts.ModeCabinTomography,
	}, &managerSlotProvider{mgr: mgr})
	if err := tx.Bind(); err != nil {
		t.Fatalf("tx.Bind: %v", err)
	}

	sink := udp.NewChannelSink()
	mc, err := sim.NewMockCluster(sim.MockClusterConfig{
		Mode:      sim.SimModeInproc,
		Seed:      77,
		TimeScale: 1.0,
		SlotScheduleFn: func() sim.SlotSchedule {
			sm := mgr.SlotMap()
			return sim.SlotSchedule{ActiveNodeMask: sm.ActiveNodeMask, Slots: sm.Slots}
		},
		CycleSeqFn:    tx.CycleSeq,
		MissionModeFn: tx.Mode,
	}, &udpChannelAdapter{sink: sink})
	if err != nil {
		t.Fatalf("NewMockCluster: %v", err)
	}

	var wg sync.WaitGroup
	errCh := make(chan error, 3)

	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := mgr.Run(ctx); err != nil && ctx.Err() == nil {
			errCh <- err
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := tx.Run(ctx); err != nil && ctx.Err() == nil {
			errCh <- err
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case ctrl := <-sink.ControlCh:
				switch ctrl.Type {
				case contracts.UDPMsgNodeHello:
					if ctrl.Hello != nil {
						_, _ = mgr.HandleNodeHello(ctx, *ctrl.Hello)
					}
				case contracts.UDPMsgHeartbeat:
					if ctrl.Heartbeat != nil {
						_ = mgr.HandleHeartbeat(ctx, *ctrl.Heartbeat)
					}
				}
			case data := <-sink.DataCh:
				switch data.Type {
				case contracts.UDPMsgCSIFrame:
					if data.CSI != nil {
						mgr.HandlePacketSeen(data.CSI.Header.NodeID, int(data.CSI.RSSIDbm))
					}
				case contracts.UDPMsgPeripheralData:
					if data.Peripheral != nil {
						mgr.HandlePeripherals(data.Peripheral.NodeID, data.Peripheral.Peripherals)
					}
				}
			}
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := mc.Run(ctx); err != nil && ctx.Err() == nil {
			errCh <- err
		}
	}()

	waitFor := func(desc string, cond func() bool) {
		t.Helper()
		for !cond() {
			select {
			case err := <-errCh:
				t.Fatalf("%s: component error: %v", desc, err)
			case <-ctx.Done():
				t.Fatalf("timeout waiting for %s (links=%d nodes=%d)", desc, mgr.SlotMap().ActiveLinks, mgr.SlotMap().ActiveNodes)
			default:
				time.Sleep(10 * time.Millisecond)
			}
		}
	}

	// 1. Converge to 5 ACTIVE nodes and 20 links.
	waitFor("5 ACTIVE nodes and 20 links", func() bool {
		sm := mgr.SlotMap()
		if sm.ActiveNodes != 5 || sm.ActiveLinks != 20 || bits.OnesCount32(sm.ActiveLinkMask) != 20 {
			return false
		}
		snap := mgr.Status()
		if len(snap.Nodes) != 5 {
			return false
		}
		for _, n := range snap.Nodes {
			if n.State != contracts.NodeStateActive {
				return false
			}
		}
		return true
	})

	// 2. Verify CLUSTER_SYNC broadcasts on loopback with strictly increasing cycle_seq
	// (draining any packets buffered in the OS socket prior to convergence).
	var prevSeq uint32
	var convergedSyncs int
	buf := make([]byte, 2048)
	for convergedSyncs < 4 {
		_ = rxConn.SetReadDeadline(time.Now().Add(time.Second))
		n, _, err := rxConn.ReadFromUDP(buf)
		if err != nil {
			t.Fatalf("ReadFromUDP CLUSTER_SYNC: %v", err)
		}
		var syncMsg contracts.ClusterSyncPayload
		if err := json.Unmarshal(buf[:n], &syncMsg); err != nil {
			t.Fatalf("Unmarshal CLUSTER_SYNC: %v", err)
		}
		if syncMsg.Type != contracts.UDPMsgClusterSync {
			continue
		}
		if prevSeq > 0 && syncMsg.CycleSeq <= prevSeq {
			t.Fatalf("cycle_seq not strictly increasing: %d -> %d", prevSeq, syncMsg.CycleSeq)
		}
		prevSeq = syncMsg.CycleSeq
		if syncMsg.ActiveNodeMask == 0x1F && len(syncMsg.Slots) == 5 {
			convergedSyncs++
		}
	}

	// 3. Simulate node_loss on node 3 -> failover to 12 links in < 500 ms.
	killAt := time.Now()
	mc.KillNode(3)
	waitFor("failover to 12 links", func() bool {
		sm := mgr.SlotMap()
		return sm.ActiveNodes == 4 && sm.ActiveLinks == 12 && bits.OnesCount32(sm.ActiveLinkMask) == 12
	})
	failoverElapsed := time.Since(killAt)
	if failoverElapsed >= 500*time.Millisecond {
		t.Fatalf("failover elapsed=%v, want < 500ms", failoverElapsed)
	}
	if fms := mgr.FailoverLastMs(); fms <= 0 || fms > 400 {
		t.Fatalf("FailoverLastMs=%d, want (0, 400]", fms)
	}

	// 4. ReviveNode(3) -> return to 5 nodes ACTIVE and 20 links.
	mc.ReviveNode(3)
	waitFor("recovery to 20 links after ReviveNode(3)", func() bool {
		sm := mgr.SlotMap()
		return sm.ActiveNodes == 5 && sm.ActiveLinks == 20 && bits.OnesCount32(sm.ActiveLinkMask) == 20
	})

	if drops := sink.DroppedCtrl() + sink.DroppedFrames(); drops != 0 {
		t.Fatalf("unexpected channel drops during integration test: %d", drops)
	}

	cancel()
	wg.Wait()
}
