// Package udp implements non-blocking UDP :5005 transport (Receiver, Transmitter,
// and Sink interface for decoupled injection by sim).
// This package only imports stdlib and internal/contracts.
package udp

import (
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	// ControlChCap is the bounded buffer capacity for NODE_HELLO / HEARTBEAT messages.
	ControlChCap = 64
	// DataChCap is the bounded buffer capacity for CSI_FRAME / PERIPHERAL_DATA messages.
	DataChCap = 512
	// DefaultReadBufferBytes is the OS UDP socket receive buffer size (4 MiB).
	DefaultReadBufferBytes = 4 * 1024 * 1024
	// DefaultMaxDatagramBytes is the reusable per-packet read buffer size (2048 B).
	DefaultMaxDatagramBytes = 2048
	// DefaultSyncInterval is the TDM CLUSTER_SYNC broadcast period (100 ms = 10 Hz).
	DefaultSyncInterval = 100 * time.Millisecond
)

// ControlMsg carries a decoded NODE_HELLO or HEARTBEAT datagram on ControlCh.
type ControlMsg struct {
	Type       contracts.UDPMsgType
	Hello      *contracts.NodeHelloPayload
	Heartbeat  *contracts.HeartbeatPayload
	ReceivedAt time.Time
	SrcAddr    string
}

// DataMsg carries a decoded CSI_FRAME or PERIPHERAL_DATA datagram on DataCh.
type DataMsg struct {
	Type       contracts.UDPMsgType
	CSI        *contracts.CSIFrame
	Peripheral *contracts.PeripheralDataPayload
	ReceivedAt time.Time
	SrcAddr    string
}

// Sink decouples packet producers (UDP Receiver and future sim) from consumers.
// Implementations MUST be strictly non-blocking.
type Sink interface {
	TrySendControl(msg ControlMsg) bool
	TrySendData(msg DataMsg) bool
}

// ChannelSink implements Sink using bounded channels and atomic drop counters.
type ChannelSink struct {
	ControlCh     chan ControlMsg
	DataCh        chan DataMsg
	droppedCtrl   atomic.Uint64
	droppedFrames atomic.Uint64
}

// NewChannelSink creates a ChannelSink with ControlCh (cap 64) and DataCh (cap 512).
func NewChannelSink() *ChannelSink {
	return &ChannelSink{
		ControlCh: make(chan ControlMsg, ControlChCap),
		DataCh:    make(chan DataMsg, DataChCap),
	}
}

// TrySendControl performs a non-blocking send to ControlCh, incrementing DroppedCtrl when full.
func (s *ChannelSink) TrySendControl(msg ControlMsg) bool {
	select {
	case s.ControlCh <- msg:
		return true
	default:
		s.droppedCtrl.Add(1)
		return false
	}
}

// TrySendData performs a non-blocking send to DataCh, incrementing DroppedFrames when full.
func (s *ChannelSink) TrySendData(msg DataMsg) bool {
	select {
	case s.DataCh <- msg:
		return true
	default:
		s.droppedFrames.Add(1)
		return false
	}
}

// DroppedCtrl returns the number of dropped control messages due to full ControlCh.
func (s *ChannelSink) DroppedCtrl() uint64 {
	return s.droppedCtrl.Load()
}

// DroppedFrames returns the number of dropped data messages due to full DataCh.
func (s *ChannelSink) DroppedFrames() uint64 {
	return s.droppedFrames.Load()
}

// SlotPlan describes the active TDM slot schedule read atomically by Transmitter.
type SlotPlan struct {
	SlotMs         int
	ActiveNodeMask uint8
	Slots          []contracts.SlotAssignment
}

// SlotProvider supplies the current SlotPlan without coupling udp to cluster.
type SlotProvider interface {
	CurrentSlotPlan() SlotPlan
}
