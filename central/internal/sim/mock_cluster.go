package sim

import (
	"context"
	"fmt"
	"math"
	"math/rand"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

const (
	// VirtualNodeCount is the fixed 5-node cluster size (IDs 0..4).
	VirtualNodeCount = 5
	// DefaultSubcarriers is the I/Q subcarrier count per CSI_FRAME (datagram < 1400 B).
	DefaultSubcarriers = 56
	// MaxSubcarriers bounds I/Q count so header + 10 B + 4 B*N stays below 1400 B.
	MaxSubcarriers = 256
	// DefaultCycleDuration is the base TDM cycle period (100 ms = 10 Hz).
	DefaultCycleDuration = 100 * time.Millisecond

	sinTableSize = 1024
)

// FixedMACs are the 5 locally administered virtual ESP32-S3 MAC addresses (§5.2).
var FixedMACs = [VirtualNodeCount]string{
	"02:ED:6E:00:00:00",
	"02:ED:6E:00:00:01",
	"02:ED:6E:00:00:02",
	"02:ED:6E:00:00:03",
	"02:ED:6E:00:00:04",
}

// SimMode selects in-process sink injection vs real UDP datagrams on localhost/LAN.
type SimMode string

const (
	SimModeInproc SimMode = "inproc"
	SimModeUDP    SimMode = "udp"
)

// ControlEvent mirrors a decoded NODE_HELLO or HEARTBEAT pushed to ClusterSink.
type ControlEvent struct {
	Type       contracts.UDPMsgType
	Hello      *contracts.NodeHelloPayload
	Heartbeat  *contracts.HeartbeatPayload
	ReceivedAt time.Time
	SrcAddr    string
}

// DataEvent mirrors a decoded CSI_FRAME or PERIPHERAL_DATA pushed to ClusterSink.
type DataEvent struct {
	Type       contracts.UDPMsgType
	CSI        *contracts.CSIFrame
	Peripheral *contracts.PeripheralDataPayload
	ReceivedAt time.Time
	SrcAddr    string
}

// ClusterSink receives virtual cluster control and data events in inproc mode.
// Tests or cmd/ wire an adapter from ClusterSink to udp.Sink.
type ClusterSink interface {
	PushControl(ev ControlEvent) bool
	PushData(ev DataEvent) bool
}

// SlotSchedule describes active nodes and TDM slots provided to MockCluster without importing cluster.
type SlotSchedule struct {
	ActiveNodeMask uint8
	Slots          []contracts.SlotAssignment
}

// MockClusterConfig configures the deterministic 5-node virtual ESP32-S3 cluster.
type MockClusterConfig struct {
	Mode           SimMode
	TargetAddr     string // UDP destination when Mode == SimModeUDP (default "127.0.0.1:5005")
	Seed           int64
	TimeScale      float64 // 1.0 = real-time 100ms cycles; 10.0 = 10x faster
	LossRate       float64 // 0.0..1.0 simulated packet drop probability
	JitterMs       int     // max random TX jitter in Run (ms)
	Subcarriers    int     // I/Q count per CSI_FRAME (default 56, datagram < 1400 B)
	Scenario       string  // initial scenario
	BaseTime       time.Time
	SlotScheduleFn func() SlotSchedule
	CycleSeqFn     func() uint32
	MissionModeFn  func() contracts.MissionMode
	OnModeChange   func(contracts.MissionMode)
	OnSelfExam     func(SelfExamEvent)
	MockAI         *MockAI // optional, synchronized on SetScenario
}

// MockCluster simulates 5 ESP32-S3 nodes emitting NODE_HELLO, HEARTBEAT, CSI_FRAME, and PERIPHERAL_DATA.
type MockCluster struct {
	cfg            MockClusterConfig
	sink           ClusterSink
	sinTable       [sinTableSize]float64
	rng            *rand.Rand // CSI noise + I2C noise only (keeps frames reproducible)
	lossRng        *rand.Rand
	jitRng         *rand.Rand
	subcarriers    int
	timeScale      float64
	baseTime       time.Time
	slotScheduleFn func() SlotSchedule

	mu          sync.Mutex
	cycle       uint64
	helloSent   [VirtualNodeCount]bool
	scenario    scenarioState
	udpConn     *net.UDPConn
	dstAddr     *net.UDPAddr
	dgramBuf    []byte
	csiBinBuf   []byte
	missionMode contracts.MissionMode
	iqBuf       []contracts.IQSample
	pending     []func()

	killed [VirtualNodeCount]atomic.Bool
}

// NewMockCluster creates a deterministic virtual cluster simulator.
func NewMockCluster(cfg MockClusterConfig, sink ClusterSink) (*MockCluster, error) {
	if cfg.Mode == "" {
		cfg.Mode = SimModeInproc
	}
	if cfg.Mode != SimModeInproc && cfg.Mode != SimModeUDP {
		return nil, fmt.Errorf("sim: unknown mode %q", cfg.Mode)
	}
	if cfg.Mode == SimModeInproc && sink == nil {
		return nil, fmt.Errorf("sim: inproc mode requires a ClusterSink")
	}
	if cfg.Mode == SimModeUDP && cfg.TargetAddr == "" {
		cfg.TargetAddr = "127.0.0.1:5005"
	}
	if cfg.Seed == 0 {
		cfg.Seed = 42
	}
	ts := cfg.TimeScale
	if ts <= 0 {
		ts = 1.0
	}
	sub := cfg.Subcarriers
	if sub <= 0 {
		sub = DefaultSubcarriers
	}
	base := cfg.BaseTime
	if base.IsZero() {
		base = time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	}
	if sub > MaxSubcarriers {
		return nil, fmt.Errorf("sim: subcarriers %d exceed %d (datagram must stay < 1400 B)", sub, MaxSubcarriers)
	}
	if !IsValidScenario(cfg.Scenario) {
		return nil, fmt.Errorf("sim: unknown scenario %q", cfg.Scenario)
	}

	mc := &MockCluster{
		cfg:         cfg,
		sink:        sink,
		rng:         rand.New(rand.NewSource(cfg.Seed)),
		lossRng:     rand.New(rand.NewSource(cfg.Seed + 1)),
		jitRng:      rand.New(rand.NewSource(cfg.Seed + 2)),
		subcarriers: sub,
		timeScale:   ts,
		baseTime:    base,
		scenario:    newScenarioState(cfg.Scenario, base),
		dgramBuf:    make([]byte, 0, 1400),
		csiBinBuf:   make([]byte, 0, 1400),
		iqBuf:       make([]contracts.IQSample, 0, sub),
		missionMode: contracts.ModeCabinTomography,
	}
	for i := 0; i < sinTableSize; i++ {
		mc.sinTable[i] = math.Sin(2.0 * math.Pi * float64(i) / float64(sinTableSize))
	}
	if cfg.SlotScheduleFn != nil {
		mc.slotScheduleFn = cfg.SlotScheduleFn
	} else {
		mc.slotScheduleFn = defaultFullSchedule
	}
	if cfg.MockAI != nil {
		cfg.MockAI.SetScenario(cfg.Scenario)
	}
	if cfg.Mode == SimModeUDP {
		dst, err := net.ResolveUDPAddr("udp", cfg.TargetAddr)
		if err != nil {
			return nil, fmt.Errorf("sim: resolve target %q: %w", cfg.TargetAddr, err)
		}
		conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
		if err != nil {
			return nil, fmt.Errorf("sim: open udp socket: %w", err)
		}
		mc.dstAddr = dst
		mc.udpConn = conn
	}
	return mc, nil
}

// Close releases any UDP socket held by MockCluster.
func (mc *MockCluster) Close() error {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	if mc.udpConn != nil {
		err := mc.udpConn.Close()
		mc.udpConn = nil
		return err
	}
	return nil
}

// KillNode silences virtual node id (0..4) until ReviveNode is called.
func (mc *MockCluster) KillNode(id uint8) {
	if id < VirtualNodeCount {
		mc.killed[id].Store(true)
	}
}

// ReviveNode restores virtual node id (0..4). The node reboots: it re-sends
// NODE_HELLO and re-syncs through heartbeats before returning to ACTIVE.
func (mc *MockCluster) ReviveNode(id uint8) {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	mc.reviveLocked(id)
}

func (mc *MockCluster) reviveLocked(id uint8) {
	if id < VirtualNodeCount && mc.killed[id].Load() {
		mc.killed[id].Store(false)
		mc.helloSent[id] = false
	}
}

// SetScenario switches the active scenario and synchronizes MockAI if configured.
func (mc *MockCluster) SetScenario(s string) error {
	if !IsValidScenario(s) {
		return fmt.Errorf("sim: unknown scenario %q", s)
	}
	mc.mu.Lock()
	now := mc.simTimeLocked()
	mc.scenario = newScenarioState(s, now)
	mc.mu.Unlock()
	if mc.cfg.MockAI != nil {
		mc.cfg.MockAI.SetScenario(s)
	}
	return nil
}

// Scenario returns the active scenario name.
func (mc *MockCluster) Scenario() string {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	return mc.scenario.name
}

// Run executes 100ms TDM cycles (scaled by TimeScale) until ctx is canceled.
func (mc *MockCluster) Run(ctx context.Context) error {
	defer mc.Close()
	period := time.Duration(float64(DefaultCycleDuration) / mc.timeScale)
	if period < time.Millisecond {
		period = time.Millisecond
	}
	ticker := time.NewTicker(period)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if mc.cfg.JitterMs > 0 {
				mc.mu.Lock()
				jit := time.Duration(mc.jitRng.Intn(mc.cfg.JitterMs+1)) * time.Millisecond
				mc.mu.Unlock()
				if jit > 0 {
					timer := time.NewTimer(jit)
					select {
					case <-ctx.Done():
						timer.Stop()
						return nil
					case <-timer.C:
					}
				}
			}
			if err := mc.Step(ctx); err != nil && ctx.Err() == nil {
				return err
			}
		}
	}
}

// Step advances the virtual cluster by exactly one deterministic 100ms TDM cycle.
func (mc *MockCluster) Step(_ context.Context) error {
	mc.mu.Lock()
	err := mc.stepLocked()
	pending := mc.pending
	mc.pending = nil
	mc.mu.Unlock()
	// Scenario callbacks run outside the lock so they may call back into MockCluster.
	for _, fn := range pending {
		fn()
	}
	return err
}

func (mc *MockCluster) stepLocked() error {
	simNow := mc.simTimeLocked()
	mc.applyScenarioEffectsLocked(simNow)

	var cycleSeq uint32
	if mc.cfg.CycleSeqFn != nil {
		cycleSeq = mc.cfg.CycleSeqFn()
	}
	if cycleSeq == 0 {
		cycleSeq = uint32(mc.cycle + 1)
	}

	mode := mc.missionMode
	if mc.cfg.MissionModeFn != nil {
		if m := mc.cfg.MissionModeFn(); m.IsValid() {
			mode = m
		}
	}
	mc.missionMode = mode

	sched := mc.slotScheduleFn()
	tsUs := simNow.UnixMicro()
	elapsedSec := simNow.Sub(mc.baseTime).Seconds()

	// 1. Discovery (NODE_HELLO) + liveness (HEARTBEAT) + 1 Hz PERIPHERAL_DATA
	for id := uint8(0); id < VirtualNodeCount; id++ {
		if mc.killed[id].Load() {
			continue
		}
		periphs := nodePeripherals(id)
		if !mc.helloSent[id] {
			mc.helloSent[id] = true
			if err := mc.emitHelloLocked(id, periphs, tsUs, simNow); err != nil {
				return err
			}
		}
		isActive := sched.ActiveNodeMask&(1<<id) != 0
		// Syncing nodes send HEARTBEAT every cycle until promoted ACTIVE;
		// ACTIVE nodes send HEARTBEAT at 1 Hz (every 10 cycles).
		if !isActive || mc.cycle%10 == 0 {
			if err := mc.emitHeartbeatLocked(id, periphs, cycleSeq, tsUs, simNow); err != nil {
				return err
			}
		}
		if mc.cycle%10 == 0 {
			if err := mc.emitPeripheralDataLocked(id, cycleSeq, tsUs, simNow); err != nil {
				return err
			}
		}
	}

	// 2. TDM CSI_FRAMEs across all active slots: each TX transmits, each other active RX captures.
	for _, slot := range sched.Slots {
		tx := slot.NodeID
		if tx >= VirtualNodeCount || mc.killed[tx].Load() {
			continue
		}
		for rx := uint8(0); rx < VirtualNodeCount; rx++ {
			if rx == tx || sched.ActiveNodeMask&(1<<rx) == 0 || mc.killed[rx].Load() {
				continue
			}
			if mc.shouldDropLocked() {
				continue
			}
			if err := mc.emitCSIFrameLocked(tx, rx, slot.SlotID, cycleSeq, mode, tsUs, elapsedSec, simNow); err != nil {
				return err
			}
		}
	}

	mc.cycle++
	return nil
}

const (
	fwVersion        = "sim-1.0.0"
	maxDatagramBytes = 1400 // target < 1400 B (no IP fragmentation)
	csiNoiseFloorDbm = float32(-92.0)
)

func defaultFullSchedule() SlotSchedule {
	s := SlotSchedule{
		ActiveNodeMask: 0x1F,
		Slots:          make([]contracts.SlotAssignment, VirtualNodeCount),
	}
	for i := range s.Slots {
		s.Slots[i] = contracts.SlotAssignment{NodeID: uint8(i), SlotID: uint8(i), Ms: 20}
	}
	return s
}

// nodePeripherals returns I2C sensors per virtual node.
// Node 0 holds the "finger resting" MAX30102 sensor (SpO2 / HR).
func nodePeripherals(id uint8) []contracts.Peripheral {
	switch id {
	case 0:
		return []contracts.Peripheral{contracts.PeripheralMAX30102, contracts.PeripheralBME280, contracts.PeripheralSCD40}
	case 1:
		return []contracts.Peripheral{contracts.PeripheralBME280, contracts.PeripheralSCD40}
	default:
		return []contracts.Peripheral{contracts.PeripheralBME280}
	}
}

// simTimeLocked advances purely by completed 100 ms cycles, independent of wall-clock jitter.
func (mc *MockCluster) simTimeLocked() time.Time {
	return mc.baseTime.Add(time.Duration(mc.cycle) * DefaultCycleDuration)
}

func (mc *MockCluster) shouldDropLocked() bool {
	if mc.cfg.LossRate <= 0 {
		return false
	}
	return mc.lossRng.Float64() < mc.cfg.LossRate
}

func (mc *MockCluster) sinTurns(turns float64) float64 {
	f := turns - math.Floor(turns)
	return mc.sinTable[int(f*sinTableSize)&(sinTableSize-1)]
}

func (mc *MockCluster) sendUDPLocked(hdr contracts.UDPHeader, csi []byte) error {
	if mc.udpConn == nil {
		return fmt.Errorf("sim: udp socket closed")
	}
	dg, err := contracts.EncodeUDPDatagram(mc.dgramBuf, hdr, csi)
	if err != nil {
		return err
	}
	if len(dg) >= maxDatagramBytes {
		return fmt.Errorf("sim: datagram %d B exceeds %d B", len(dg), maxDatagramBytes)
	}
	mc.dgramBuf = dg[:0]
	_, err = mc.udpConn.WriteToUDP(dg, mc.dstAddr)
	return err
}

func (mc *MockCluster) emitHelloLocked(id uint8, periphs []contracts.Peripheral, tsUs int64, now time.Time) error {
	if mc.cfg.Mode == SimModeUDP {
		return mc.sendUDPLocked(contracts.UDPHeader{
			V: contracts.Version, Type: contracts.UDPMsgNodeHello, NodeID: id,
			TimestampUs: tsUs, MAC: FixedMACs[id], FWVersion: fwVersion,
			SupportedPeripherals: periphs,
		}, nil)
	}
	mc.sink.PushControl(ControlEvent{
		Type: contracts.UDPMsgNodeHello, ReceivedAt: now, SrcAddr: "sim",
		Hello: &contracts.NodeHelloPayload{
			V: contracts.Version, Type: contracts.UDPMsgNodeHello, MAC: FixedMACs[id],
			NodeID: id, FWVersion: fwVersion, Peripherals: periphs, TimestampUs: tsUs,
		},
	})
	return nil
}

func (mc *MockCluster) emitHeartbeatLocked(id uint8, periphs []contracts.Peripheral, cycleSeq uint32, tsUs int64, now time.Time) error {
	if mc.shouldDropLocked() {
		return nil
	}
	rssi := -45 - int(id)
	if mc.cfg.Mode == SimModeUDP {
		return mc.sendUDPLocked(contracts.UDPHeader{
			V: contracts.Version, Type: contracts.UDPMsgHeartbeat, NodeID: id,
			TimestampUs: tsUs, CycleSeq: cycleSeq, MAC: FixedMACs[id], RSSIDbm: rssi,
			SupportedPeripherals: periphs,
		}, nil)
	}
	mc.sink.PushControl(ControlEvent{
		Type: contracts.UDPMsgHeartbeat, ReceivedAt: now, SrcAddr: "sim",
		Heartbeat: &contracts.HeartbeatPayload{
			V: contracts.Version, Type: contracts.UDPMsgHeartbeat, MAC: FixedMACs[id],
			NodeID: id, CycleSeq: cycleSeq, RSSIDbm: rssi, Peripherals: periphs, TimestampUs: tsUs,
		},
	})
	return nil
}

func (mc *MockCluster) peripheralReadingsLocked(id uint8, tsUs int64) []contracts.PeripheralReading {
	var out []contracts.PeripheralReading
	elapsed := mc.simTimeLocked().Sub(mc.scenario.startedAt)
	for _, p := range nodePeripherals(id) {
		switch p {
		case contracts.PeripheralSCD40:
			out = append(out, contracts.PeripheralReading{
				Type: p, Value: round2(mc.scenario.co2Ppm(elapsed) + mc.rng.NormFloat64()*5), Unit: "ppm", TimestampUs: tsUs,
			})
		case contracts.PeripheralBME280:
			out = append(out,
				contracts.PeripheralReading{Type: p, Value: round2(22 + mc.rng.NormFloat64()*0.05), Unit: "C", TimestampUs: tsUs},
				contracts.PeripheralReading{Type: p, Value: round2(45 + mc.rng.NormFloat64()*0.2), Unit: "%RH", TimestampUs: tsUs},
				contracts.PeripheralReading{Type: p, Value: round2(1013 + mc.rng.NormFloat64()*0.1), Unit: "hPa", TimestampUs: tsUs},
			)
		case contracts.PeripheralMAX30102:
			out = append(out,
				contracts.PeripheralReading{Type: p, Value: round2(mc.scenario.heartRateBpm() + mc.rng.NormFloat64()*0.5), Unit: "bpm", TimestampUs: tsUs},
				contracts.PeripheralReading{Type: p, Value: round2(98 + mc.rng.NormFloat64()*0.1), Unit: "%", TimestampUs: tsUs},
			)
		}
	}
	return out
}

func round2(v float64) float64 { return math.Round(v*100) / 100 }

func (mc *MockCluster) emitPeripheralDataLocked(id uint8, cycleSeq uint32, tsUs int64, now time.Time) error {
	readings := mc.peripheralReadingsLocked(id, tsUs)
	if mc.shouldDropLocked() {
		return nil
	}
	if mc.cfg.Mode == SimModeUDP {
		return mc.sendUDPLocked(contracts.UDPHeader{
			V: contracts.Version, Type: contracts.UDPMsgPeripheralData, NodeID: id,
			TimestampUs: tsUs, CycleSeq: cycleSeq, MAC: FixedMACs[id], Peripherals: readings,
		}, nil)
	}
	mc.sink.PushData(DataEvent{
		Type: contracts.UDPMsgPeripheralData, ReceivedAt: now, SrcAddr: "sim",
		Peripheral: &contracts.PeripheralDataPayload{
			V: contracts.Version, Type: contracts.UDPMsgPeripheralData, MAC: FixedMACs[id],
			NodeID: id, CycleSeq: cycleSeq, TimestampUs: tsUs, Peripherals: readings,
		},
	})
	return nil
}

// synthesizeIQLocked builds synthetic CSI from precomputed sine tables:
// respiration (0.25 Hz) + cardiac (1.2 Hz) + Gaussian noise + linear subcarrier phase offset.
func (mc *MockCluster) synthesizeIQLocked(tx, rx uint8, t float64) []contracts.IQSample {
	link := int(tx)*VirtualNodeCount + int(rx)
	baseAmp := 0.8 + 0.04*float64(link%7)
	slope := 0.004 * float64(1+link%3)
	linkPhase := 0.013 * float64(link)
	cardHz, cardAmp := mc.scenario.cardiacModulation()
	resp := 0.06 * mc.sinTurns(nominalRespHz*t+3*linkPhase)
	card := 0.02 * cardAmp * mc.sinTurns(cardHz*t+5*linkPhase)
	mod := 1 + resp + card

	out := mc.iqBuf[:0]
	for k := 0; k < mc.subcarriers; k++ {
		amp := baseAmp * mod * (1 + 0.01*mc.rng.NormFloat64())
		turns := linkPhase + slope*float64(k) + 0.1*(resp+card)
		out = append(out, contracts.IQSample{
			Real:      amp * mc.sinTurns(turns+0.25),
			Imaginary: amp * mc.sinTurns(turns),
		})
	}
	mc.iqBuf = out
	return out
}

func (mc *MockCluster) emitCSIFrameLocked(tx, rx, slotID uint8, cycleSeq uint32, mode contracts.MissionMode, tsUs int64, elapsedSec float64, now time.Time) error {
	samples := mc.synthesizeIQLocked(tx, rx, elapsedSec)
	rssi := int16(-40 - 2*int(tx) - 3*int(rx))
	mc.csiBinBuf = contracts.EncodeCSIBinary(mc.csiBinBuf, tx, rx, rssi, csiNoiseFloorDbm, samples)
	hdr := contracts.UDPHeader{
		V: contracts.Version, Type: contracts.UDPMsgCSIFrame, NodeID: rx, SlotID: slotID,
		Mode: mode, TimestampUs: tsUs, CycleSeq: cycleSeq, RSSIDbm: int(rssi),
	}
	if mc.cfg.Mode == SimModeUDP {
		return mc.sendUDPLocked(hdr, mc.csiBinBuf)
	}
	_, _, _, _, decoded, err := contracts.DecodeCSIBinary(mc.csiBinBuf, nil)
	if err != nil {
		return err
	}
	mc.sink.PushData(DataEvent{
		Type: contracts.UDPMsgCSIFrame, ReceivedAt: now, SrcAddr: "sim",
		CSI: &contracts.CSIFrame{
			Header: hdr, TxNodeID: tx, RxNodeID: rx, RSSIDbm: rssi, NoiseFloor: csiNoiseFloorDbm,
			Samples: decoded, RawPayload: append([]byte(nil), mc.csiBinBuf...),
		},
	})
	return nil
}
