package udp

import (
	"context"
	"encoding/json"
	"net"
	"runtime"
	"sync/atomic"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

type staticSlotProvider struct {
	plan atomic.Pointer[SlotPlan]
}

func (p *staticSlotProvider) CurrentSlotPlan() SlotPlan {
	if v := p.plan.Load(); v != nil {
		return *v
	}
	return SlotPlan{}
}

func TestReceiverRoundTripP6AndControl(t *testing.T) {
	sink := NewChannelSink()
	rx := NewReceiver(ReceiverConfig{Addr: "127.0.0.1:0"}, sink)
	if err := rx.Bind(); err != nil {
		t.Fatalf("rx.Bind: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	go func() { errCh <- rx.Run(ctx) }()

	dstAddr := rx.Addr().(*net.UDPAddr)
	sender, err := net.DialUDP("udp", nil, dstAddr)
	if err != nil {
		t.Fatalf("DialUDP: %v", err)
	}
	defer sender.Close()

	// 1. P6 CSI_FRAME round-trip (JSON header + '\n' + binary I/Q payload)
	samples := []contracts.IQSample{
		{Real: 1.25, Imaginary: -0.5},
		{Real: -2.0, Imaginary: 0.75},
	}
	csiBin := contracts.EncodeCSIBinary(nil, 1, 3, -54, -92.5, samples)
	pkt, err := contracts.EncodeUDPDatagram(nil, contracts.UDPHeader{
		V:           contracts.Version,
		Type:        contracts.UDPMsgCSIFrame,
		NodeID:      3,
		SlotID:      1,
		Mode:        contracts.ModeCabinTomography,
		TimestampUs: 123456,
		CycleSeq:    42,
	}, csiBin)
	if err != nil {
		t.Fatalf("EncodeUDPDatagram: %v", err)
	}
	if _, err := sender.Write(pkt); err != nil {
		t.Fatalf("Write CSI_FRAME: %v", err)
	}

	select {
	case msg := <-sink.DataCh:
		if msg.Type != contracts.UDPMsgCSIFrame || msg.CSI == nil {
			t.Fatalf("unexpected DataMsg: %+v", msg)
		}
		if msg.CSI.Header.CycleSeq != 42 || msg.CSI.TxNodeID != 1 || msg.CSI.RxNodeID != 3 || msg.CSI.RSSIDbm != -54 {
			t.Fatalf("decoded CSI mismatch: %+v", msg.CSI)
		}
		if len(msg.CSI.Samples) != 2 || msg.CSI.Samples[0].Real != 1.25 || msg.CSI.Samples[1].Imaginary != 0.75 {
			t.Fatalf("decoded IQ samples mismatch: %+v", msg.CSI.Samples)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for CSI_FRAME on DataCh")
	}

	// 2. PERIPHERAL_DATA round-trip
	periphPkt, err := contracts.EncodeUDPDatagram(nil, contracts.UDPHeader{
		V:           contracts.Version,
		Type:        contracts.UDPMsgPeripheralData,
		NodeID:      2,
		CycleSeq:    43,
		TimestampUs: 200000,
		Peripherals: []contracts.PeripheralReading{
			{Type: contracts.PeripheralSCD40, Value: 512.5, Unit: "ppm", TimestampUs: 200000},
		},
	}, nil)
	if err != nil {
		t.Fatalf("EncodeUDPDatagram periph: %v", err)
	}
	if _, err := sender.Write(periphPkt); err != nil {
		t.Fatalf("Write PERIPHERAL_DATA: %v", err)
	}
	select {
	case msg := <-sink.DataCh:
		if msg.Type != contracts.UDPMsgPeripheralData || msg.Peripheral == nil || len(msg.Peripheral.Peripherals) != 1 {
			t.Fatalf("unexpected PERIPHERAL_DATA msg: %+v", msg)
		}
		if msg.Peripheral.Peripherals[0].Value != 512.5 {
			t.Fatalf("periph value=%v, want 512.5", msg.Peripheral.Peripherals[0].Value)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for PERIPHERAL_DATA")
	}

	// 3. NODE_HELLO & HEARTBEAT -> ControlCh
	helloBytes, _ := json.Marshal(contracts.NodeHelloPayload{
		V:           contracts.Version,
		Type:        contracts.UDPMsgNodeHello,
		MAC:         "AA:BB:CC:DD:EE:01",
		Peripherals: []contracts.Peripheral{contracts.PeripheralMAX30102},
	})
	if _, err := sender.Write(helloBytes); err != nil {
		t.Fatalf("Write NODE_HELLO: %v", err)
	}
	select {
	case cmsg := <-sink.ControlCh:
		if cmsg.Type != contracts.UDPMsgNodeHello || cmsg.Hello == nil || cmsg.Hello.MAC != "AA:BB:CC:DD:EE:01" {
			t.Fatalf("unexpected ControlMsg: %+v", cmsg)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for NODE_HELLO")
	}

	cancel()
	if err := <-errCh; err != nil {
		t.Fatalf("rx.Run error: %v", err)
	}
}

func TestTransmitterClusterSyncAndSendModeCmd(t *testing.T) {
	rxConn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 0})
	if err != nil {
		t.Fatalf("ListenUDP: %v", err)
	}
	defer rxConn.Close()

	sp := &staticSlotProvider{}
	sp.plan.Store(&SlotPlan{
		SlotMs:         25,
		ActiveNodeMask: 0x0F,
		Slots: []contracts.SlotAssignment{
			{NodeID: 0, SlotID: 0, Ms: 25},
			{NodeID: 1, SlotID: 1, Ms: 25},
			{NodeID: 2, SlotID: 2, Ms: 25},
			{NodeID: 3, SlotID: 3, Ms: 25},
		},
	})

	tx := NewTransmitter(TransmitterConfig{
		BroadcastAddr: rxConn.LocalAddr().String(),
		TickInterval:  20 * time.Millisecond,
		InitialMode:   contracts.ModeCabinTomography,
	}, sp)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- tx.Run(ctx) }()

	// Read 3 CLUSTER_SYNC datagrams and verify strictly monotonic cycle_seq.
	buf := make([]byte, 2048)
	var seqs []uint32
	for len(seqs) < 3 {
		_ = rxConn.SetReadDeadline(time.Now().Add(2 * time.Second))
		n, _, err := rxConn.ReadFromUDP(buf)
		if err != nil {
			t.Fatalf("ReadFromUDP sync: %v", err)
		}
		var syncMsg contracts.ClusterSyncPayload
		if err := json.Unmarshal(buf[:n], &syncMsg); err != nil {
			t.Fatalf("Unmarshal CLUSTER_SYNC: %v", err)
		}
		if syncMsg.Type != contracts.UDPMsgClusterSync {
			t.Fatalf("got type %q, want CLUSTER_SYNC", syncMsg.Type)
		}
		if syncMsg.SlotMs != 25 || syncMsg.ActiveNodeMask != 0x0F || len(syncMsg.Slots) != 4 {
			t.Fatalf("unexpected slots in CLUSTER_SYNC: %+v", syncMsg)
		}
		seqs = append(seqs, syncMsg.CycleSeq)
	}
	if !(seqs[0] < seqs[1] && seqs[1] < seqs[2]) {
		t.Fatalf("cycle_seq not strictly monotonic: %v", seqs)
	}

	// SendModeCmd must immediately dispatch MODE_CMD and update mode for subsequent CLUSTER_SYNC.
	if err := tx.SendModeCmd(contracts.ModeRadiationAlert); err != nil {
		t.Fatalf("SendModeCmd: %v", err)
	}
	if tx.Mode() != contracts.ModeRadiationAlert {
		t.Fatalf("tx.Mode=%v, want MODE_RADIATION_ALERT", tx.Mode())
	}

	sawModeCmd := false
	sawUpdatedSync := false
	deadline := time.Now().Add(2 * time.Second)
	for !(sawModeCmd && sawUpdatedSync) && time.Now().Before(deadline) {
		_ = rxConn.SetReadDeadline(deadline)
		n, _, err := rxConn.ReadFromUDP(buf)
		if err != nil {
			t.Fatalf("ReadFromUDP after SendModeCmd: %v", err)
		}
		var hdr contracts.UDPHeader
		if err := json.Unmarshal(buf[:n], &hdr); err != nil {
			t.Fatalf("Unmarshal hdr: %v", err)
		}
		if hdr.Type == contracts.UDPMsgModeCmd && hdr.Mode == contracts.ModeRadiationAlert {
			sawModeCmd = true
		}
		if hdr.Type == contracts.UDPMsgClusterSync && hdr.Mode == contracts.ModeRadiationAlert {
			sawUpdatedSync = true
		}
	}
	if !sawModeCmd || !sawUpdatedSync {
		t.Fatalf("sawModeCmd=%v sawUpdatedSync=%v, want both true", sawModeCmd, sawUpdatedSync)
	}

	cancel()
	if err := <-errCh; err != nil {
		t.Fatalf("tx.Run: %v", err)
	}
}

func TestReceiverRxDisabledAndNonBlockingDrop(t *testing.T) {
	sink := NewChannelSink()
	rxDisabled := NewReceiver(ReceiverConfig{Addr: "127.0.0.1:0", RxDisabled: true}, sink)
	if err := rxDisabled.Bind(); err != nil {
		t.Fatalf("RxDisabled Bind: %v", err)
	}
	if rxDisabled.Addr() != nil {
		t.Fatalf("RxDisabled Addr=%v, want nil (no socket)", rxDisabled.Addr())
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- rxDisabled.Run(ctx) }()
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("RxDisabled Run: %v", err)
	}

	// Prove non-blocking when DataCh (cap 512) is completely full.
	for i := 0; i < DataChCap; i++ {
		if !sink.TrySendData(DataMsg{Type: contracts.UDPMsgCSIFrame, CSI: &contracts.CSIFrame{}}) {
			t.Fatalf("unexpected drop at %d", i)
		}
	}
	doneSend := make(chan struct{})
	go func() {
		for i := 0; i < 10; i++ {
			if sink.TrySendData(DataMsg{Type: contracts.UDPMsgCSIFrame, CSI: &contracts.CSIFrame{}}) {
				t.Errorf("expected TrySendData to return false when full")
			}
		}
		close(doneSend)
	}()
	select {
	case <-doneSend:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("TrySendData blocked when DataCh was full")
	}
	if got := sink.DroppedFrames(); got != 10 {
		t.Fatalf("DroppedFrames=%d, want 10", got)
	}

	// Prove non-blocking ControlCh drop counter.
	for i := 0; i < ControlChCap; i++ {
		if !sink.TrySendControl(ControlMsg{Type: contracts.UDPMsgHeartbeat}) {
			t.Fatalf("unexpected ctrl drop at %d", i)
		}
	}
	if sink.TrySendControl(ControlMsg{Type: contracts.UDPMsgHeartbeat}) {
		t.Fatal("expected TrySendControl false when full")
	}
	if got := sink.DroppedCtrl(); got != 1 {
		t.Fatalf("DroppedCtrl=%d, want 1", got)
	}
}

func TestReceiverFlood5000NonBlockingShutdownAndNoGoroutineLeak(t *testing.T) {
	sink := NewChannelSink()
	// Pre-fill DataCh completely so every incoming CSI_FRAME triggers a drop.
	for i := 0; i < DataChCap; i++ {
		if !sink.TrySendData(DataMsg{Type: contracts.UDPMsgCSIFrame, CSI: &contracts.CSIFrame{}}) {
			t.Fatalf("prefill DataCh failed at %d", i)
		}
	}

	rx := NewReceiver(ReceiverConfig{Addr: "127.0.0.1:0"}, sink)
	if err := rx.Bind(); err != nil {
		t.Fatalf("rx.Bind: %v", err)
	}
	boundAddr := rx.Addr().(*net.UDPAddr)

	baseGoroutines := runtime.NumGoroutine()

	ctx, cancel := context.WithCancel(context.Background())
	rxDone := make(chan error, 1)
	go func() { rxDone <- rx.Run(ctx) }()

	sender, err := net.DialUDP("udp", nil, boundAddr)
	if err != nil {
		cancel()
		<-rxDone
		t.Fatalf("DialUDP: %v", err)
	}
	defer sender.Close()

	samples := make([]contracts.IQSample, 16)
	csiBin := contracts.EncodeCSIBinary(nil, 0, 1, -50, -92.0, samples)
	pkt, err := contracts.EncodeUDPDatagram(nil, contracts.UDPHeader{
		V:           contracts.Version,
		Type:        contracts.UDPMsgCSIFrame,
		NodeID:      1,
		SlotID:      0,
		Mode:        contracts.ModeCabinTomography,
		TimestampUs: 1000,
		CycleSeq:    1,
	}, csiBin)
	if err != nil {
		cancel()
		<-rxDone
		t.Fatalf("EncodeUDPDatagram: %v", err)
	}

	const floodCount = 5000
	for i := 0; i < floodCount; i++ {
		if _, err := sender.Write(pkt); err != nil {
			t.Fatalf("Write %d: %v", i, err)
		}
		if i%250 == 249 {
			time.Sleep(time.Millisecond)
		}
	}

	deadline := time.Now().Add(time.Second)
	for sink.DroppedFrames() == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if sink.DroppedFrames() == 0 {
		t.Fatalf("expected DroppedFrames > 0 under 5000-datagram flood (rxPackets=%d)", rx.RxPackets())
	}

	stopStart := time.Now()
	cancel()
	select {
	case err := <-rxDone:
		if err != nil {
			t.Fatalf("rx.Run returned error on cancel: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("rx.Run did not shut down within 1s")
	}
	if elapsed := time.Since(stopStart); elapsed >= time.Second {
		t.Fatalf("shutdown took %v, want < 1s", elapsed)
	}

	// Socket must be closed (re-binding same port must succeed).
	rebind, err := net.ListenUDP("udp", boundAddr)
	if err != nil {
		t.Fatalf("expected socket closed after ctx cancel, re-bind failed: %v", err)
	}
	_ = rebind.Close()

	// Verify no goroutine leak after Run exits.
	leakDeadline := time.Now().Add(500 * time.Millisecond)
	for runtime.NumGoroutine() > baseGoroutines && time.Now().Before(leakDeadline) {
		runtime.Gosched()
		time.Sleep(10 * time.Millisecond)
	}
	if got := runtime.NumGoroutine(); got > baseGoroutines {
		t.Fatalf("goroutine leak: before=%d after=%d", baseGoroutines, got)
	}
}
