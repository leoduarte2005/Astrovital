package ipc

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"edgespace/central/internal/contracts"
)

func TestIPCFrameLimitsAndErrors(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	var fw contracts.FrameWriter
	var fr contracts.FrameReader

	errCh := make(chan error, 1)
	go func() { errCh <- fw.Write(c1, []byte(`{"v":1}`)) }()
	got, err := fr.Read(c2)
	if err != nil {
		t.Fatalf("FrameReader.Read: %v", err)
	}
	if err := <-errCh; err != nil {
		t.Fatalf("FrameWriter.Write: %v", err)
	}
	if string(got) != `{"v":1}` {
		t.Fatalf("got %q", string(got))
	}

	// len == 0 -> ErrFrameSize
	go func() {
		var hdr [4]byte
		_, _ = c1.Write(hdr[:])
	}()
	if _, err := fr.Read(c2); !errors.Is(err, contracts.ErrFrameSize) {
		t.Fatalf("expected ErrFrameSize for len=0, got %v", err)
	}

	// len > 1 MiB -> ErrFrameSize
	go func() {
		var hdr [4]byte
		binary.BigEndian.PutUint32(hdr[:], contracts.MaxFrameBytes+1)
		_, _ = c1.Write(hdr[:])
	}()
	if _, err := fr.Read(c2); !errors.Is(err, contracts.ErrFrameSize) {
		t.Fatalf("expected ErrFrameSize for >1MiB, got %v", err)
	}

	// Client handles invalid JSON and oversized frame by incrementing ProtocolErrors and reconnecting.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	var connIdx atomic.Int32
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			idx := connIdx.Add(1)
			go func(c net.Conn, n int32) {
				defer c.Close()
				switch n {
				case 1:
					var fw contracts.FrameWriter
					_ = fw.Write(c, []byte(`{not-json`))
					time.Sleep(100 * time.Millisecond)
				case 2:
					var hdr [4]byte
					binary.BigEndian.PutUint32(hdr[:], contracts.MaxFrameBytes+5)
					_, _ = c.Write(hdr[:])
					time.Sleep(100 * time.Millisecond)
				default:
					var fr contracts.FrameReader
					var fw contracts.FrameWriter
					raw, err := fr.Read(c)
					if err != nil {
						return
					}
					var env contracts.IPCEnvelope
					if json.Unmarshal(raw, &env) == nil && env.ReqID != nil {
						ack, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCrewAck, time.Now().UnixMicro(), env.CrewID, env.ReqID, contracts.CrewAckPayload{OK: true, BaselineFound: true})
						b, _ := json.Marshal(ack)
						_ = fw.Write(c, b)
					}
					time.Sleep(100 * time.Millisecond)
				}
			}(conn, idx)
		}
	}()

	client, err := New(Config{
		Addr:       ln.Addr().String(),
		MinBackoff: 15 * time.Millisecond,
		MaxBackoff: 30 * time.Millisecond,
	}, Deps{})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	deadline := time.Now().Add(3 * time.Second)
	for (client.Stats().ProtocolErrors < 2 || client.Stats().Reconnects < 2 || !client.Connected()) && time.Now().Before(deadline) {
		time.Sleep(15 * time.Millisecond)
	}
	st := client.Stats()
	if st.ProtocolErrors < 2 || st.Reconnects < 2 {
		t.Fatalf("expected ProtocolErrors>=2 and Reconnects>=2, got %+v", st)
	}

	ack, err := client.SendSetActiveCrew(ctx, 1, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
	if err != nil || !ack.OK {
		t.Fatalf("SendSetActiveCrew after recovery failed: ack=%+v err=%v", ack, err)
	}
	cancel()
	<-done
}

func TestIPCPriorityHiOverLo(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	var dialed atomic.Bool
	client, err := New(Config{
		MaxWindowAge: 200 * time.Millisecond,
		Dial: func(ctx context.Context, addr string) (net.Conn, error) {
			if dialed.Swap(true) {
				<-ctx.Done()
				return nil, ctx.Err()
			}
			return c1, nil
		},
	}, Deps{})
	if err != nil {
		t.Fatal(err)
	}

	// Pre-populate LoPri with 1 obsolete window (>MaxWindowAge) and 2 fresh windows, plus 1 HiPri.
	staleTs := time.Now().Add(-1 * time.Second).UnixMicro()
	staleWin, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCSIWindow, staleTs, nil, nil, contracts.CSIWindowPayload{CycleSeqFirst: 1, Mode: contracts.ModeCabinTomography})
	freshWin, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCSIWindow, time.Now().UnixMicro(), nil, nil, contracts.CSIWindowPayload{CycleSeqFirst: 2, Mode: contracts.ModeCabinTomography})
	client.loPriCh <- staleWin
	client.loPriCh <- freshWin

	reqID := uint64(42)
	crew := "crew_001"
	hiEnv, _ := contracts.NewIPCEnvelope(contracts.IPCMsgSetActiveCrew, time.Now().UnixMicro(), &crew, &reqID, contracts.SetActiveCrewPayload{CrewID: crew})
	client.hiPriCh <- hiEnv

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	var fr contracts.FrameReader
	readEnv := func() contracts.IPCEnvelope {
		raw, err := fr.Read(c2)
		if err != nil {
			t.Fatalf("Read frame: %v", err)
		}
		var env contracts.IPCEnvelope
		if err := json.Unmarshal(raw, &env); err != nil {
			t.Fatalf("Unmarshal frame: %v", err)
		}
		return env
	}

	first := readEnv()
	if first.Type != contracts.IPCMsgSetActiveCrew {
		t.Fatalf("expected HiPri SET_ACTIVE_CREW first, got %s", first.Type)
	}
	second := readEnv()
	if second.Type != contracts.IPCMsgCSIWindow {
		t.Fatalf("expected CSI_WINDOW second, got %s", second.Type)
	}
	var wp contracts.CSIWindowPayload
	if err := json.Unmarshal(second.Payload, &wp); err != nil {
		t.Fatal(err)
	}
	if wp.CycleSeqFirst != 2 {
		t.Fatalf("expected stale window (seq=1) dropped and seq=2 sent, got seq=%d", wp.CycleSeqFirst)
	}
	if client.Stats().DroppedWindows == 0 {
		t.Fatal("expected DroppedWindows >= 1 for obsolete window")
	}

	cancel()
	_ = c2.Close()
	<-done
}

func TestIPCReqIDTimeoutAndStale(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	staleSent := make(chan struct{})
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		var fr contracts.FrameReader
		var fw contracts.FrameWriter
		for {
			raw, err := fr.Read(conn)
			if err != nil {
				return
			}
			var env contracts.IPCEnvelope
			if json.Unmarshal(raw, &env) != nil || env.ReqID == nil {
				continue
			}
			if *env.ReqID == 10 {
				// Delay longer than CrewAckTimeout so req_id=10 times out, then send late ACK -> StaleResp.
				time.Sleep(180 * time.Millisecond)
				ack, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCrewAck, time.Now().UnixMicro(), env.CrewID, env.ReqID, contracts.CrewAckPayload{OK: true, BaselineFound: true})
				b, _ := json.Marshal(ack)
				_ = fw.Write(conn, b)
				// Also send an unknown req_id=9999.
				unkID := uint64(9999)
				unk, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCrewAck, time.Now().UnixMicro(), env.CrewID, &unkID, contracts.CrewAckPayload{OK: true})
				b2, _ := json.Marshal(unk)
				_ = fw.Write(conn, b2)
				close(staleSent)
			} else {
				ack, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCrewAck, time.Now().UnixMicro(), env.CrewID, env.ReqID, contracts.CrewAckPayload{OK: true, BaselineFound: false})
				b, _ := json.Marshal(ack)
				_ = fw.Write(conn, b)
			}
		}
	}()

	client, err := New(Config{
		Addr:           ln.Addr().String(),
		CrewAckTimeout: 80 * time.Millisecond,
		SweepInterval:  15 * time.Millisecond,
	}, Deps{})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	deadline := time.Now().Add(2 * time.Second)
	for !client.Connected() && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if !client.Connected() {
		t.Fatal("not connected")
	}

	_, err = client.SendSetActiveCrew(ctx, 10, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
	if !errors.Is(err, ErrTimeout) {
		t.Fatalf("expected ErrTimeout, got %v", err)
	}

	select {
	case <-staleSent:
	case <-time.After(2 * time.Second):
		t.Fatal("stale responses not sent in time")
	}

	// Follow-up request must still work cleanly and confirm reader processed prior stale frames.
	ack, err := client.SendSetActiveCrew(ctx, 11, contracts.SetActiveCrewPayload{CrewID: "crew_003"})
	if err != nil || !ack.OK || ack.BaselineFound {
		t.Fatalf("expected OK=true BaselineFound=false for req 11, got ack=%+v err=%v", ack, err)
	}
	if client.Stats().StaleResp < 2 {
		t.Fatalf("expected StaleResp >= 2, got %d", client.Stats().StaleResp)
	}

	cancel()
	<-done
}

func TestIPCReconnectAndWatchdog(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	var connNum atomic.Int32
	var releaseFirst atomic.Bool
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			n := connNum.Add(1)
			go func(c net.Conn, idx int32) {
				defer c.Close()
				var fr contracts.FrameReader
				var fw contracts.FrameWriter
				for {
					raw, err := fr.Read(c)
					if err != nil {
						return
					}
					var env contracts.IPCEnvelope
					if json.Unmarshal(raw, &env) != nil {
						continue
					}
					if idx == 1 && env.Type == contracts.IPCMsgSetActiveCrew {
						// Hold pending without answering until test observes ErrAIUnavailable after disconnect/watchdog.
						for !releaseFirst.Load() {
							time.Sleep(10 * time.Millisecond)
						}
						return
					}
					if idx >= 2 && env.Type == contracts.IPCMsgSetActiveCrew && env.ReqID != nil {
						ack, _ := contracts.NewIPCEnvelope(contracts.IPCMsgCrewAck, time.Now().UnixMicro(), env.CrewID, env.ReqID, contracts.CrewAckPayload{OK: true, BaselineFound: true})
						b, _ := json.Marshal(ack)
						_ = fw.Write(c, b)
					}
				}
			}(conn, n)
		}
	}()

	var reconnectCBs atomic.Int32
	client, err := New(Config{
		Addr:            ln.Addr().String(),
		CrewAckTimeout:  2 * time.Second,
		SilenceWatchdog: 100 * time.Millisecond,
		SweepInterval:   15 * time.Millisecond,
		MinBackoff:      15 * time.Millisecond,
		MaxBackoff:      30 * time.Millisecond,
	}, Deps{
		OnReconnect: func() { reconnectCBs.Add(1) },
	})
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	deadline := time.Now().Add(2 * time.Second)
	for !client.Connected() && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if !client.Connected() {
		t.Fatal("did not connect")
	}

	// Start pending HiPri request + activate LoPri with no AI_INFERENCE -> silence watchdog triggers disconnect.
	reqErrCh := make(chan error, 1)
	go func() {
		_, rerr := client.SendSetActiveCrew(ctx, 1, contracts.SetActiveCrewPayload{CrewID: "crew_001"})
		reqErrCh <- rerr
	}()

	time.Sleep(20 * time.Millisecond)
	_ = client.EnqueueCSIWindow(nil, contracts.CSIWindowPayload{CycleSeqFirst: 1, Mode: contracts.ModeCabinTomography})

	select {
	case rerr := <-reqErrCh:
		if !errors.Is(rerr, ErrAIUnavailable) {
			t.Fatalf("expected ErrAIUnavailable on watchdog drop, got %v", rerr)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("pending request did not fail on silence watchdog")
	}
	releaseFirst.Store(true)

	// Wait for reconnect + OnReconnect callback.
	deadline = time.Now().Add(2 * time.Second)
	for (reconnectCBs.Load() < 2 || !client.Connected()) && time.Now().Before(deadline) {
		time.Sleep(15 * time.Millisecond)
	}
	if reconnectCBs.Load() < 2 || client.Stats().Reconnects < 1 {
		t.Fatalf("expected reconnects>=1 and OnReconnect>=2, got callbacks=%d stats=%+v", reconnectCBs.Load(), client.Stats())
	}

	cancel()
	<-done
}
