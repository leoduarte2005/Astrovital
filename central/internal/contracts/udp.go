package contracts

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
)

// MaxUDPPayloadBytes bounds a single UDP datagram on :5005.
const MaxUDPPayloadBytes = 65507

// ErrInvalidUDPDatagram is returned when a UDP datagram cannot be decoded.
var ErrInvalidUDPDatagram = errors.New("contracts: invalid UDP datagram")

// SlotAssignment describes one TDM slot in CLUSTER_SYNC.
type SlotAssignment struct {
	NodeID uint8 `json:"node_id"`
	SlotID uint8 `json:"slot_id"`
	Ms     int   `json:"ms"`
}

// ClusterSyncPayload is broadcast by Central at 10 Hz (CLUSTER_SYNC).
type ClusterSyncPayload struct {
	V              int              `json:"v"`
	Type           UDPMsgType       `json:"type"`
	CycleSeq       uint32           `json:"cycle_seq"` // P1
	TimestampUs    int64            `json:"timestamp_us"`
	Mode           MissionMode      `json:"mode"`
	SlotMs         int              `json:"slot_ms"`
	ActiveNodeMask uint8            `json:"active_node_mask"`
	Slots          []SlotAssignment `json:"slots"`
}

// ModeCmdPayload is broadcast immediately on mission_mode changes (MODE_CMD).
type ModeCmdPayload struct {
	V           int         `json:"v"`
	Type        UDPMsgType  `json:"type"`
	Mode        MissionMode `json:"mode"`
	TimestampUs int64       `json:"timestamp_us"`
	CycleSeq    uint32      `json:"cycle_seq"`
}

// NodeHelloPayload is sent by an ESP32-S3 node upon boot/discovery (NODE_HELLO).
type NodeHelloPayload struct {
	V           int          `json:"v"`
	Type        UDPMsgType   `json:"type"`
	MAC         string       `json:"mac"`
	NodeID      uint8        `json:"node_id"`
	FWVersion   string       `json:"fw_version,omitempty"`
	Peripherals []Peripheral `json:"peripherals,omitempty"`
	TimestampUs int64        `json:"timestamp_us"`
}

// HeartbeatPayload is sent by a node when it has no CSI data or to keep liveness (HEARTBEAT).
type HeartbeatPayload struct {
	V           int          `json:"v"`
	Type        UDPMsgType   `json:"type"`
	MAC         string       `json:"mac,omitempty"`
	NodeID      uint8        `json:"node_id"`
	CycleSeq    uint32       `json:"cycle_seq"`
	RSSIDbm     int          `json:"rssi_dbm,omitempty"`
	Peripherals []Peripheral `json:"peripherals,omitempty"`
	TimestampUs int64        `json:"timestamp_us"`
}

// CSIFrame represents a decoded CSI_FRAME datagram (header + binary P6 csi_payload).
type CSIFrame struct {
	Header     UDPHeader
	TxNodeID   uint8
	RxNodeID   uint8
	RSSIDbm    int16
	NoiseFloor float32
	Samples    []IQSample
	RawPayload []byte
}

// PeripheralDataPayload represents a PERIPHERAL_DATA UDP message.
type PeripheralDataPayload struct {
	V           int                 `json:"v"`
	Type        UDPMsgType          `json:"type"`
	MAC         string              `json:"mac,omitempty"`
	NodeID      uint8               `json:"node_id"`
	CycleSeq    uint32              `json:"cycle_seq"`
	TimestampUs int64               `json:"timestamp_us"`
	Peripherals []PeripheralReading `json:"peripherals"`
}

// EncodeUDPDatagram encodes a JSON header followed by optional '\n' + binary csi_payload (P6).
// Reuses dst[:0] to avoid allocations on hot paths.
func EncodeUDPDatagram(dst []byte, hdr UDPHeader, csiPayload []byte) ([]byte, error) {
	if err := hdr.Validate(); err != nil {
		return nil, err
	}
	hdrBytes, err := json.Marshal(hdr)
	if err != nil {
		return nil, err
	}
	needed := len(hdrBytes)
	if len(csiPayload) > 0 {
		needed += 1 + len(csiPayload)
	}
	if needed > MaxUDPPayloadBytes {
		return nil, fmt.Errorf("%w: size %d exceeds %d", ErrInvalidUDPDatagram, needed, MaxUDPPayloadBytes)
	}
	out := dst[:0]
	if cap(out) < needed {
		out = make([]byte, 0, needed)
	}
	out = append(out, hdrBytes...)
	if len(csiPayload) > 0 {
		out = append(out, '\n')
		out = append(out, csiPayload...)
	}
	return out, nil
}

// DecodeUDPDatagram splits a UDP datagram at the first '\n' (P6) and unmarshals UDPHeader.
// Returned csiPayload aliases data directly (zero allocation).
func DecodeUDPDatagram(data []byte) (hdr UDPHeader, csiPayload []byte, err error) {
	if len(data) == 0 {
		return hdr, nil, fmt.Errorf("%w: empty datagram", ErrInvalidUDPDatagram)
	}
	hdrPart := data
	if idx := bytes.IndexByte(data, '\n'); idx >= 0 {
		hdrPart = data[:idx]
		if idx+1 < len(data) {
			csiPayload = data[idx+1:]
		}
	}
	if err := json.Unmarshal(hdrPart, &hdr); err != nil {
		return hdr, nil, fmt.Errorf("%w: json: %v", ErrInvalidUDPDatagram, err)
	}
	if err := hdr.Validate(); err != nil {
		return hdr, nil, fmt.Errorf("%w: %v", ErrInvalidUDPDatagram, err)
	}
	return hdr, csiPayload, nil
}

const csiHeaderSize = 10

// EncodeCSIBinary packs tx, rx, rssi, noiseFloor and I/Q samples into dst[:0] without unnecessary allocs.
// Format (10B header + 4B * N samples, int16 Q10 fixed-point):
// [tx:1][rx:1][rssi:int16 LE][noise:float32 LE][count:uint16 LE][I0:int16 LE][Q0:int16 LE]...
func EncodeCSIBinary(dst []byte, tx, rx uint8, rssi int16, noiseFloor float32, samples []IQSample) []byte {
	n := len(samples)
	if n > 65535 {
		n = 65535
	}
	total := csiHeaderSize + n*4
	out := dst[:0]
	if cap(out) < total {
		out = make([]byte, 0, total)
	}
	out = out[:total]
	out[0] = tx
	out[1] = rx
	binary.LittleEndian.PutUint16(out[2:4], uint16(rssi))
	binary.LittleEndian.PutUint32(out[4:8], math.Float32bits(noiseFloor))
	binary.LittleEndian.PutUint16(out[8:10], uint16(n))
	off := csiHeaderSize
	for i := 0; i < n; i++ {
		iv := clampInt16(samples[i].Real * 1000.0)
		qv := clampInt16(samples[i].Imaginary * 1000.0)
		binary.LittleEndian.PutUint16(out[off:off+2], uint16(iv))
		binary.LittleEndian.PutUint16(out[off+2:off+4], uint16(qv))
		off += 4
	}
	return out
}

// DecodeCSIBinary unpacks a P6 binary csi_payload into samplesDst[:0] (reusing backing array).
func DecodeCSIBinary(raw []byte, samplesDst []IQSample) (tx, rx uint8, rssi int16, noiseFloor float32, samples []IQSample, err error) {
	if len(raw) < csiHeaderSize {
		return 0, 0, 0, 0, samplesDst[:0], fmt.Errorf("%w: csi payload too short (%d)", ErrInvalidUDPDatagram, len(raw))
	}
	tx = raw[0]
	rx = raw[1]
	rssi = int16(binary.LittleEndian.Uint16(raw[2:4]))
	noiseFloor = math.Float32frombits(binary.LittleEndian.Uint32(raw[4:8]))
	n := int(binary.LittleEndian.Uint16(raw[8:10]))
	expected := csiHeaderSize + n*4
	if len(raw) < expected {
		return 0, 0, 0, 0, samplesDst[:0], fmt.Errorf("%w: csi payload truncated (%d < %d)", ErrInvalidUDPDatagram, len(raw), expected)
	}
	samples = samplesDst[:0]
	if cap(samples) < n {
		samples = make([]IQSample, 0, n)
	}
	off := csiHeaderSize
	for i := 0; i < n; i++ {
		iv := int16(binary.LittleEndian.Uint16(raw[off : off+2]))
		qv := int16(binary.LittleEndian.Uint16(raw[off+2 : off+4]))
		samples = append(samples, IQSample{
			Real:      float64(iv) / 1000.0,
			Imaginary: float64(qv) / 1000.0,
		})
		off += 4
	}
	return tx, rx, rssi, noiseFloor, samples, nil
}

func clampInt16(v float64) int16 {
	if v > 32767 {
		return 32767
	}
	if v < -32768 {
		return -32768
	}
	return int16(math.Round(v))
}
