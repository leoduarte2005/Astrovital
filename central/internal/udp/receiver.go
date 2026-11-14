package udp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

// ReceiverConfig configures a UDP Receiver.
type ReceiverConfig struct {
	Addr             string
	ReadBufferBytes  int
	MaxDatagramBytes int
	RxDisabled       bool
	Now              func() time.Time
}

// Receiver listens on UDP (default :5005), decodes incoming datagrams using a reusable
// 2048 B buffer, and forwards messages non-blockingly into Sink.
type Receiver struct {
	cfg      ReceiverConfig
	sink     Sink
	now      func() time.Time
	bufSize  int
	rbufSize int

	mu   sync.Mutex
	conn *net.UDPConn

	rxPackets    atomic.Uint64
	decodeErrors atomic.Uint64
}

// NewReceiver creates a Receiver writing decoded packets to sink.
func NewReceiver(cfg ReceiverConfig, sink Sink) *Receiver {
	addr := cfg.Addr
	if addr == "" {
		addr = ":5005"
	}
	rbuf := cfg.ReadBufferBytes
	if rbuf <= 0 {
		rbuf = DefaultReadBufferBytes
	}
	bufSize := cfg.MaxDatagramBytes
	if bufSize <= 0 {
		bufSize = DefaultMaxDatagramBytes
	}
	nowFn := cfg.Now
	if nowFn == nil {
		nowFn = time.Now
	}
	cfg.Addr = addr
	return &Receiver{
		cfg:      cfg,
		sink:     sink,
		now:      nowFn,
		bufSize:  bufSize,
		rbufSize: rbuf,
	}
}

// Bind opens the UDP read socket and configures the 4 MiB SO_RCVBUF.
// When RxDisabled is true, Bind is a no-op and opens no socket.
func (r *Receiver) Bind() error {
	if r.cfg.RxDisabled {
		return nil
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.conn != nil {
		return nil
	}
	udpAddr, err := net.ResolveUDPAddr("udp", r.cfg.Addr)
	if err != nil {
		return fmt.Errorf("udp receiver resolve %q: %w", r.cfg.Addr, err)
	}
	conn, err := net.ListenUDP("udp", udpAddr)
	if err != nil {
		return fmt.Errorf("udp receiver listen %q: %w", r.cfg.Addr, err)
	}
	if err := conn.SetReadBuffer(r.rbufSize); err != nil {
		_ = conn.Close()
		return fmt.Errorf("udp receiver SetReadBuffer(%d): %w", r.rbufSize, err)
	}
	r.conn = conn
	return nil
}

// Addr returns the bound local UDP address, or nil if RxDisabled or not bound.
func (r *Receiver) Addr() net.Addr {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.conn == nil {
		return nil
	}
	return r.conn.LocalAddr()
}

// Run binds (if needed) and reads UDP datagrams until ctx is canceled.
// If RxDisabled is true, Run opens no socket and blocks until ctx.Done().
func (r *Receiver) Run(ctx context.Context) error {
	if r.cfg.RxDisabled {
		<-ctx.Done()
		return nil
	}
	if err := r.Bind(); err != nil {
		return err
	}

	r.mu.Lock()
	conn := r.conn
	r.mu.Unlock()
	if conn == nil {
		return errors.New("udp receiver: socket not bound")
	}

	go func() {
		<-ctx.Done()
		_ = conn.Close()
	}()

	buf := make([]byte, r.bufSize)
	for {
		n, src, err := conn.ReadFromUDP(buf)
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return fmt.Errorf("udp receiver read: %w", err)
		}
		if n <= 0 {
			continue
		}
		r.rxPackets.Add(1)
		srcStr := ""
		if src != nil {
			srcStr = src.String()
		}
		if err := r.handlePacket(buf[:n], r.now(), srcStr); err != nil {
			r.decodeErrors.Add(1)
		}
	}
}

// RxPackets returns the total number of UDP datagrams read.
func (r *Receiver) RxPackets() uint64 { return r.rxPackets.Load() }

// DecodeErrors returns the total number of datagrams that failed decoding.
func (r *Receiver) DecodeErrors() uint64 { return r.decodeErrors.Load() }

func (r *Receiver) handlePacket(pkt []byte, receivedAt time.Time, srcAddr string) error {
	if r.sink == nil {
		return nil
	}
	hdr, csiPayload, err := contracts.DecodeUDPDatagram(pkt)
	if err != nil {
		// Fallback for NODE_HELLO / HEARTBEAT marshaled directly from
		// contracts.NodeHelloPayload / HeartbeatPayload (where "peripherals" is []Peripheral).
		if msg, ok := tryDecodeControlPayload(pkt, receivedAt, srcAddr); ok {
			r.sink.TrySendControl(msg)
			return nil
		}
		return err
	}

	switch hdr.Type {
	case contracts.UDPMsgNodeHello:
		r.sink.TrySendControl(ControlMsg{
			Type:       contracts.UDPMsgNodeHello,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
			Hello: &contracts.NodeHelloPayload{
				V:           hdr.V,
				Type:        hdr.Type,
				MAC:         hdr.MAC,
				NodeID:      hdr.NodeID,
				FWVersion:   hdr.FWVersion,
				Peripherals: hdr.SupportedPeripherals,
				TimestampUs: hdr.TimestampUs,
			},
		})
	case contracts.UDPMsgHeartbeat:
		r.sink.TrySendControl(ControlMsg{
			Type:       contracts.UDPMsgHeartbeat,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
			Heartbeat: &contracts.HeartbeatPayload{
				V:           hdr.V,
				Type:        hdr.Type,
				MAC:         hdr.MAC,
				NodeID:      hdr.NodeID,
				CycleSeq:    hdr.CycleSeq,
				RSSIDbm:     hdr.RSSIDbm,
				Peripherals: hdr.SupportedPeripherals,
				TimestampUs: hdr.TimestampUs,
			},
		})
	case contracts.UDPMsgCSIFrame:
		tx, rx, rssi, noiseFloor, samples, err := contracts.DecodeCSIBinary(csiPayload, nil)
		if err != nil {
			return err
		}
		frame := &contracts.CSIFrame{
			Header:     hdr,
			TxNodeID:   tx,
			RxNodeID:   rx,
			RSSIDbm:    rssi,
			NoiseFloor: noiseFloor,
			Samples:    samples,
		}
		r.sink.TrySendData(DataMsg{
			Type:       contracts.UDPMsgCSIFrame,
			CSI:        frame,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
		})
	case contracts.UDPMsgPeripheralData:
		periphs := make([]contracts.PeripheralReading, len(hdr.Peripherals))
		copy(periphs, hdr.Peripherals)
		r.sink.TrySendData(DataMsg{
			Type:       contracts.UDPMsgPeripheralData,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
			Peripheral: &contracts.PeripheralDataPayload{
				V:           hdr.V,
				Type:        hdr.Type,
				MAC:         hdr.MAC,
				NodeID:      hdr.NodeID,
				CycleSeq:    hdr.CycleSeq,
				TimestampUs: hdr.TimestampUs,
				Peripherals: periphs,
			},
		})
	default:
		return fmt.Errorf("udp receiver: unsupported msg type %q", hdr.Type)
	}
	return nil
}

func tryDecodeControlPayload(pkt []byte, receivedAt time.Time, srcAddr string) (ControlMsg, bool) {
	hdrPart := pkt
	if idx := bytes.IndexByte(pkt, '\n'); idx >= 0 {
		hdrPart = pkt[:idx]
	}
	var peek struct {
		V    int                  `json:"v"`
		Type contracts.UDPMsgType `json:"type"`
	}
	if err := json.Unmarshal(hdrPart, &peek); err != nil || peek.V != contracts.Version {
		return ControlMsg{}, false
	}
	switch peek.Type {
	case contracts.UDPMsgNodeHello:
		var p contracts.NodeHelloPayload
		if err := json.Unmarshal(hdrPart, &p); err != nil {
			return ControlMsg{}, false
		}
		return ControlMsg{
			Type:       contracts.UDPMsgNodeHello,
			Hello:      &p,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
		}, true
	case contracts.UDPMsgHeartbeat:
		var p contracts.HeartbeatPayload
		if err := json.Unmarshal(hdrPart, &p); err != nil {
			return ControlMsg{}, false
		}
		return ControlMsg{
			Type:       contracts.UDPMsgHeartbeat,
			Heartbeat:  &p,
			ReceivedAt: receivedAt,
			SrcAddr:    srcAddr,
		}, true
	default:
		return ControlMsg{}, false
	}
}
