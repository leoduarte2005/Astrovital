package pipeline

import (
	"context"
	"sort"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

type cycleBucket struct {
	active       bool
	cycleSeq     uint32
	mode         contracts.MissionMode
	openedAt     time.Time
	deadline     time.Time
	expectedMask uint32
	receivedMask uint32
	frames       [NumLinks]LinkSample
}

type closedCycleSlot struct {
	cycleSeq     uint32
	receivedMask uint32
	mode         contracts.MissionMode
	ringPos      int
}

type peripheralKey struct {
	Type contracts.Peripheral
	Unit string
}

type peripheralEntry struct {
	NodeID     uint8
	Reading    contracts.PeripheralReading
	ReceivedAt time.Time
}

// Pipeline executes G4 cycle assembly, ring buffering, 2 Hz CSI_WINDOW emission,
// 1 Hz I2C/store decimation, Latest atomic snapshot updates, and 6-subsystem clinical thresholds.
type Pipeline struct {
	cfg  Config
	deps Deps

	// Pre-allocated zero-GC hot-path structures.
	ring     [NumLinks][RingCapacity]LinkSample
	ringHead [NumLinks]int
	ringUsed [NumLinks]int
	buckets  [NumBuckets]cycleBucket

	seqInitialized bool
	nextCloseSeq   uint32

	windowBuf   []closedCycleSlot
	windowCount int

	peripherals map[peripheralKey]peripheralEntry
	clinical    clinicalState

	Latest     *atomic.Pointer[contracts.TelemetrySnapshot]
	lastClosed atomic.Pointer[ClosedCycleInfo]

	framesReceived      atomic.Uint64
	invalidFrames       atomic.Uint64
	lateFrames          atomic.Uint64
	cyclesClosed        atomic.Uint64
	partialCycles       atomic.Uint64
	windowsEmitted      atomic.Uint64
	ipcDropped          atomic.Uint64
	peripheralSnapshots atomic.Uint64
	storeRecords        atomic.Uint64
	storeDropped        atomic.Uint64
	alertsEmitted       atomic.Uint64
	eventsDropped       atomic.Uint64
	inferencesApplied   atomic.Uint64
	selfExamsApplied    atomic.Uint64
}

// New allocates a Pipeline with pre-allocated [20][300]LinkSample ring buffer and [4][20] cycle buckets.
func New(cfg Config, deps Deps) *Pipeline {
	if cfg.CycleGrace <= 0 {
		cfg.CycleGrace = DefaultCycleGrace
	}
	if cfg.WindowCycles <= 0 {
		cfg.WindowCycles = DefaultWindowCycles
	}
	if cfg.Emit1HzInterval <= 0 {
		cfg.Emit1HzInterval = DefaultEmit1HzInterval
	}
	if cfg.SelfExamTTL <= 0 {
		cfg.SelfExamTTL = DefaultSelfExamTTL
	}
	if cfg.DefaultLinkMask == 0 {
		cfg.DefaultLinkMask = AllLinksMask
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}

	latest := deps.Latest
	if latest == nil {
		latest = &atomic.Pointer[contracts.TelemetrySnapshot]{}
	}

	p := &Pipeline{
		cfg:         cfg,
		deps:        deps,
		windowBuf:   make([]closedCycleSlot, cfg.WindowCycles),
		peripherals: make(map[peripheralKey]peripheralEntry, 8),
		clinical:    newClinicalState(cfg.SelfExamTTL),
		Latest:      latest,
	}
	p.publishLatest(cfg.Now(), p.sessionSnapshot())
	return p
}

// Metrics returns an atomic snapshot of pipeline counters.
func (p *Pipeline) Metrics() Metrics {
	return Metrics{
		FramesReceived:      p.framesReceived.Load(),
		InvalidFrames:       p.invalidFrames.Load(),
		LateFrames:          p.lateFrames.Load(),
		CyclesClosed:        p.cyclesClosed.Load(),
		PartialCycles:       p.partialCycles.Load(),
		WindowsEmitted:      p.windowsEmitted.Load(),
		IPCDropped:          p.ipcDropped.Load(),
		PeripheralSnapshots: p.peripheralSnapshots.Load(),
		StoreRecords:        p.storeRecords.Load(),
		StoreDropped:        p.storeDropped.Load(),
		AlertsEmitted:       p.alertsEmitted.Load(),
		EventsDropped:       p.eventsDropped.Load(),
		InferencesApplied:   p.inferencesApplied.Load(),
		SelfExamsApplied:    p.selfExamsApplied.Load(),
	}
}

// LastClosedCycle returns metadata for the most recently closed cycle, if any.
func (p *Pipeline) LastClosedCycle() (ClosedCycleInfo, bool) {
	v := p.lastClosed.Load()
	if v == nil {
		return ClosedCycleInfo{}, false
	}
	return *v, true
}

func (p *Pipeline) now() time.Time {
	return p.cfg.Now()
}

func (p *Pipeline) sessionSnapshot() SessionView {
	if p.deps.Session == nil {
		return SessionView{MissionMode: contracts.ModeCabinTomography}
	}
	v := p.deps.Session.Snapshot()
	if v.MissionMode == "" {
		v.MissionMode = contracts.ModeCabinTomography
	}
	return v
}

func (p *Pipeline) currentExpectedMask() uint32 {
	if p.deps.LinkMask != nil {
		return p.deps.LinkMask.ActiveLinkMask() & AllLinksMask
	}
	return p.cfg.DefaultLinkMask & AllLinksMask
}

// Run executes the single-goroutine G4 cycleAssembler event loop until ctx is cancelled,
// draining buffered input channels before returning.
func (p *Pipeline) Run(ctx context.Context) error {
	ticker1Hz := time.NewTicker(p.cfg.Emit1HzInterval)
	defer ticker1Hz.Stop()

	graceTimer := time.NewTimer(time.Hour)
	if !graceTimer.Stop() {
		select {
		case <-graceTimer.C:
		default:
		}
	}
	defer graceTimer.Stop()

	resetGrace := func() {
		if !graceTimer.Stop() {
			select {
			case <-graceTimer.C:
			default:
			}
		}
		if d, ok := p.nextGraceDelay(p.now()); ok {
			graceTimer.Reset(d)
		}
	}

	for {
		select {
		case <-ctx.Done():
			p.drainInputs()
			return nil
		case msg, ok := <-p.deps.DataCh:
			if !ok {
				p.deps.DataCh = nil
				continue
			}
			p.handleDataMsg(msg)
			resetGrace()
		case inf, ok := <-p.deps.InferenceCh:
			if !ok {
				p.deps.InferenceCh = nil
				continue
			}
			p.handleInference(inf)
		case ex, ok := <-p.deps.SelfExamCh:
			if !ok {
				p.deps.SelfExamCh = nil
				continue
			}
			p.handleSelfExam(ex)
		case <-graceTimer.C:
			p.flushExpiredCycles(p.now())
			resetGrace()
		case <-ticker1Hz.C:
			p.emit1Hz(p.now())
		}
	}
}

func (p *Pipeline) drainInputs() {
	for {
		drained := false
		if p.deps.DataCh != nil {
			select {
			case msg, ok := <-p.deps.DataCh:
				if !ok {
					p.deps.DataCh = nil
				} else {
					p.handleDataMsg(msg)
					drained = true
				}
			default:
			}
		}
		if p.deps.InferenceCh != nil {
			select {
			case inf, ok := <-p.deps.InferenceCh:
				if !ok {
					p.deps.InferenceCh = nil
				} else {
					p.handleInference(inf)
					drained = true
				}
			default:
			}
		}
		if p.deps.SelfExamCh != nil {
			select {
			case ex, ok := <-p.deps.SelfExamCh:
				if !ok {
					p.deps.SelfExamCh = nil
				} else {
					p.handleSelfExam(ex)
					drained = true
				}
			default:
			}
		}
		if !drained {
			return
		}
	}
}

func (p *Pipeline) nextGraceDelay(now time.Time) (time.Duration, bool) {
	if !p.seqInitialized {
		return 0, false
	}
	var earliest time.Time
	found := false
	for i := 0; i < NumBuckets; i++ {
		b := &p.buckets[i]
		if !b.active {
			continue
		}
		if !found || b.deadline.Before(earliest) {
			earliest = b.deadline
			found = true
		}
	}
	if !found {
		return 0, false
	}
	d := earliest.Sub(now)
	if d < 0 {
		d = 0
	}
	return d, true
}

func (p *Pipeline) handleDataMsg(msg DataMsg) {
	now := p.now()
	switch msg.Type {
	case contracts.UDPMsgCSIFrame:
		p.handleCSIFrame(msg.CSI, msg.ReceivedAt, now)
	case contracts.UDPMsgPeripheralData:
		p.handlePeripheralData(msg.Peripheral, msg.ReceivedAt, now)
	default:
		p.invalidFrames.Add(1)
	}
}

func (p *Pipeline) handleCSIFrame(frame *contracts.CSIFrame, recvAt, now time.Time) {
	p.framesReceived.Add(1)
	if frame == nil {
		p.invalidFrames.Add(1)
		return
	}
	linkIdx, ok := LinkIndex(frame.TxNodeID, frame.RxNodeID)
	if !ok {
		p.invalidFrames.Add(1)
		return
	}

	ts := recvAt
	if ts.IsZero() {
		ts = now
	}
	seq := frame.Header.CycleSeq

	if !p.seqInitialized {
		p.seqInitialized = true
		p.nextCloseSeq = seq
	}

	diff := int32(seq - p.nextCloseSeq)
	if diff < 0 || diff >= NumBuckets {
		p.lateFrames.Add(1)
		return
	}

	// Activate any skipped buckets between nextCloseSeq and seq so ordering never deadlocks.
	view := p.sessionSnapshot()
	expectedMask := p.currentExpectedMask()
	for s := p.nextCloseSeq; int32(seq-s) >= 0; s++ {
		b := &p.buckets[s%NumBuckets]
		if !b.active {
			mode := frame.Header.Mode
			if mode == "" {
				mode = view.MissionMode
			}
			*b = cycleBucket{
				active:       true,
				cycleSeq:     s,
				mode:         mode,
				openedAt:     now,
				deadline:     now.Add(p.cfg.CycleGrace),
				expectedMask: expectedMask,
			}
		}
	}

	b := &p.buckets[seq%NumBuckets]
	if frame.Header.Mode != "" {
		b.mode = frame.Header.Mode
	}

	// Copy I/Q samples into fixed inline LinkSample (zero heap allocation).
	dst := &b.frames[linkIdx]
	n := len(frame.Samples)
	if n > MaxSubcarriers {
		n = MaxSubcarriers
	}
	dst.CycleSeq = seq
	dst.TimestampUs = frame.Header.TimestampUs
	dst.TxNodeID = frame.TxNodeID
	dst.RxNodeID = frame.RxNodeID
	dst.RSSIDbm = frame.RSSIDbm
	dst.NoiseFloor = frame.NoiseFloor
	dst.SampleCount = uint16(n)
	dst.Valid = true
	for i := 0; i < n; i++ {
		dst.IQ[i] = IQF32{
			Real: float32(frame.Samples[i].Real),
			Imag: float32(frame.Samples[i].Imaginary),
		}
	}
	b.receivedMask |= 1 << linkIdx

	p.closeReadyCycles(now)
}

func (p *Pipeline) closeReadyCycles(now time.Time) {
	for {
		b := &p.buckets[p.nextCloseSeq%NumBuckets]
		if !b.active {
			return
		}
		complete := b.expectedMask != 0 && (b.receivedMask&b.expectedMask) == b.expectedMask
		expired := !now.Before(b.deadline)
		if !complete && !expired {
			return
		}
		p.closeCycleBucket(b, complete, now)
		p.nextCloseSeq++
	}
}

func (p *Pipeline) flushExpiredCycles(now time.Time) {
	p.closeReadyCycles(now)
}

func (p *Pipeline) closeCycleBucket(b *cycleBucket, complete bool, now time.Time) {
	// Write all 20 link slots into the pre-allocated [20][300]LinkSample ring buffer (zero GC).
	ringPos := p.ringHead[0]
	for linkIdx := 0; linkIdx < NumLinks; linkIdx++ {
		pos := p.ringHead[linkIdx]
		if (b.receivedMask & (1 << linkIdx)) != 0 {
			p.ring[linkIdx][pos] = b.frames[linkIdx]
		} else {
			tx, rx, _ := LinkPair(linkIdx)
			p.ring[linkIdx][pos] = LinkSample{
				CycleSeq: b.cycleSeq,
				TxNodeID: tx,
				RxNodeID: rx,
				Valid:    false,
			}
		}
		p.ringHead[linkIdx] = (pos + 1) % RingCapacity
		if p.ringUsed[linkIdx] < RingCapacity {
			p.ringUsed[linkIdx]++
		}
	}

	info := &ClosedCycleInfo{
		CycleSeq:     b.cycleSeq,
		ExpectedMask: b.expectedMask,
		ReceivedMask: b.receivedMask,
		Complete:     complete,
		ClosedAt:     now,
	}
	p.lastClosed.Store(info)
	p.cyclesClosed.Add(1)
	if !complete {
		p.partialCycles.Add(1)
	}

	p.windowBuf[p.windowCount] = closedCycleSlot{
		cycleSeq:     b.cycleSeq,
		receivedMask: b.receivedMask,
		mode:         b.mode,
		ringPos:      ringPos,
	}
	p.windowCount++

	// Clear bucket for reuse without heap allocation.
	*b = cycleBucket{}

	view := p.sessionSnapshot()
	if !view.AIReady && p.clinical.hasInference {
		p.clinical.freezeBiometrics()
	}

	if p.windowCount >= p.cfg.WindowCycles {
		p.emitCSIWindow(now, view)
		p.windowCount = 0
	}

	p.evaluateAndPublish(now, view)
}

func (p *Pipeline) emitCSIWindow(now time.Time, view SessionView) {
	nCycles := p.windowCount
	if nCycles <= 0 {
		return
	}
	first := p.windowBuf[0]
	mode := first.mode
	if mode == "" {
		mode = view.MissionMode
	}

	var windowMask uint32
	links := make([]contracts.CSILink, 0, NumLinks)
	quality := make([]float64, 0, NumLinks)

	for linkIdx := 0; linkIdx < NumLinks; linkIdx++ {
		validCount := 0
		totalIQ := 0
		for c := 0; c < nCycles; c++ {
			pos := p.windowBuf[c].ringPos
			s := &p.ring[linkIdx][pos]
			if s.Valid {
				validCount++
				totalIQ += int(s.SampleCount)
			}
		}
		if validCount == 0 {
			continue
		}
		windowMask |= 1 << linkIdx
		tx, rx, _ := LinkPair(linkIdx)

		iq := make([]contracts.IQSample, 0, totalIQ)
		var lastRSSI int
		var lastNoise float64
		for c := 0; c < nCycles; c++ {
			pos := p.windowBuf[c].ringPos
			s := &p.ring[linkIdx][pos]
			if !s.Valid {
				continue
			}
			lastRSSI = int(s.RSSIDbm)
			lastNoise = float64(s.NoiseFloor)
			sc := int(s.SampleCount)
			for k := 0; k < sc; k++ {
				iq = append(iq, contracts.IQSample{
					Real:      float64(s.IQ[k].Real),
					Imaginary: float64(s.IQ[k].Imag),
				})
			}
		}

		links = append(links, contracts.CSILink{
			TxNodeID:   tx,
			RxNodeID:   rx,
			IQSamples:  iq,
			RSSIDbm:    lastRSSI,
			NoiseFloor: lastNoise,
		})
		quality = append(quality, float64(validCount)/float64(nCycles))
	}

	payload := contracts.CSIWindowPayload{
		CycleSeqFirst:  first.cycleSeq,
		ActiveLinkMask: windowMask,
		Mode:           mode,
		Links:          links,
		QualityPerLink: quality,
	}

	// Attach crew_id ONLY when SessionView.AIReady == true.
	var crewPtr *string
	if view.AIReady && view.CrewID != "" {
		c := view.CrewID
		crewPtr = &c
	}

	tsUs := now.UnixMicro()
	msg := CSIWindowEmit{
		TsUs:              tsUs,
		CrewID:            crewPtr,
		Payload:           payload,
		CalibrationActive: view.CalibrationActive,
		CalibrationStepID: view.CalibrationStepID,
	}

	if p.deps.IPC != nil {
		if p.deps.IPC.TrySendCSIWindow(msg) {
			p.windowsEmitted.Add(1)
		} else {
			p.ipcDropped.Add(1)
		}
	} else {
		p.windowsEmitted.Add(1)
	}

	if view.CalibrationActive && p.deps.Store != nil {
		var calCrew *string
		if view.CrewID != "" {
			c := view.CrewID
			calCrew = &c
		}
		payloadCopy := payload
		if !p.deps.Store.EmitCSIBlob(StoreCSIBlobRecord{
			TsUs:              tsUs,
			CrewID:            calCrew,
			CycleSeqFirst:     payload.CycleSeqFirst,
			Reason:            "calibration",
			CalibrationStepID: view.CalibrationStepID,
			Window:            &payloadCopy,
		}) {
			p.storeDropped.Add(1)
		}
	}
}

func (p *Pipeline) handlePeripheralData(data *contracts.PeripheralDataPayload, recvAt, now time.Time) {
	if data == nil {
		p.invalidFrames.Add(1)
		return
	}
	ts := recvAt
	if ts.IsZero() {
		ts = now
	}
	for _, r := range data.Peripherals {
		if !r.Type.IsValid() {
			p.invalidFrames.Add(1)
			continue
		}
		if r.TimestampUs <= 0 {
			r.TimestampUs = data.TimestampUs
			if r.TimestampUs <= 0 {
				r.TimestampUs = ts.UnixMicro()
			}
		}
		key := peripheralKey{Type: r.Type, Unit: r.Unit}
		p.peripherals[key] = peripheralEntry{
			NodeID:     data.NodeID,
			Reading:    r,
			ReceivedAt: ts,
		}
		p.clinical.applyPeripheral(r)
	}
	p.evaluateAndPublish(now, p.sessionSnapshot())
}

func (p *Pipeline) handleInference(inf contracts.AIInferencePayload) {
	now := p.now()
	view := p.sessionSnapshot()
	if !view.AIReady {
		// Freeze biometric inference while AI is not ready / during crew hot-swap.
		p.clinical.freezeBiometrics()
		p.evaluateAndPublish(now, view)
		return
	}
	p.clinical.applyInference(inf)
	p.inferencesApplied.Add(1)
	p.evaluateAndPublish(now, view)
}

func (p *Pipeline) handleSelfExam(ex SelfExamInput) {
	now := p.now()
	p.clinical.applySelfExam(ex, now)
	p.selfExamsApplied.Add(1)
	p.evaluateAndPublish(now, p.sessionSnapshot())
}

func (p *Pipeline) buildPeripheralLists(now time.Time) ([]contracts.PeripheralReading, []PeripheralMeta) {
	if len(p.peripherals) == 0 {
		return nil, nil
	}
	keys := make([]peripheralKey, 0, len(p.peripherals))
	for k := range p.peripherals {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].Type != keys[j].Type {
			return keys[i].Type < keys[j].Type
		}
		return keys[i].Unit < keys[j].Unit
	})

	readings := make([]contracts.PeripheralReading, 0, len(keys))
	meta := make([]PeripheralMeta, 0, len(keys))
	nowUs := now.UnixMicro()
	for _, k := range keys {
		ent := p.peripherals[k]
		ageMs := int64(0)
		if ent.Reading.TimestampUs > 0 && nowUs >= ent.Reading.TimestampUs {
			ageMs = (nowUs - ent.Reading.TimestampUs) / 1000
		} else if !ent.ReceivedAt.IsZero() && !now.Before(ent.ReceivedAt) {
			ageMs = now.Sub(ent.ReceivedAt).Milliseconds()
		}
		readings = append(readings, ent.Reading)
		meta = append(meta, PeripheralMeta{
			NodeID: ent.NodeID,
			Type:   ent.Reading.Type,
			Value:  ent.Reading.Value,
			Unit:   ent.Reading.Unit,
			TsUs:   ent.Reading.TimestampUs,
			AgeMs:  ageMs,
		})
	}
	return readings, meta
}

func (p *Pipeline) emit1Hz(now time.Time) {
	view := p.sessionSnapshot()
	if !view.AIReady && p.clinical.hasInference {
		p.clinical.freezeBiometrics()
	}

	tsUs := now.UnixMicro()
	readings, meta := p.buildPeripheralLists(now)

	// 1 Hz PERIPHERAL_SNAPSHOT to IPC (environment always has crew_id = nil).
	if len(readings) > 0 && p.deps.IPC != nil {
		msg := PeripheralSnapshotEmit{
			TsUs:   tsUs,
			CrewID: nil,
			Payload: contracts.PeripheralSnapshotPayload{
				Readings:    readings,
				TimestampUs: tsUs,
			},
			Meta: meta,
		}
		if p.deps.IPC.TrySendPeripheralSnapshot(msg) {
			p.peripheralSnapshots.Add(1)
		} else {
			p.ipcDropped.Add(1)
		}
	}

	// 1 Hz decimated telemetry + peripheral records to Store.
	if p.deps.Store != nil {
		var crewPtr *string
		if view.CrewID != "" {
			c := view.CrewID
			crewPtr = &c
		}
		var infPtr *contracts.AIInferencePayload
		if view.AIReady && p.clinical.hasInference {
			infCopy := p.clinical.lastInf
			infPtr = &infCopy
		}
		if p.deps.Store.EmitTelemetry1Hz(StoreTelemetryRecord{
			TsUs:        tsUs,
			CrewID:      crewPtr,
			MissionMode: view.MissionMode,
			AIReady:     view.AIReady,
			Vitals:      p.clinical.vitals,
			Environment: p.clinical.env,
			Inference:   infPtr,
		}) {
			p.storeRecords.Add(1)
		} else {
			p.storeDropped.Add(1)
		}

		if len(meta) > 0 {
			if p.deps.Store.EmitPeripherals1Hz(StorePeripheralRecord{
				TsUs:     tsUs,
				Readings: meta,
			}) {
				p.storeRecords.Add(1)
			} else {
				p.storeDropped.Add(1)
			}
		}
	}

	// Also refresh Latest snapshot on 1 Hz cadence if mode/thresholds changed externally.
	p.evaluateAndPublish(now, view)
}

func (p *Pipeline) evaluateAndPublish(now time.Time, view SessionView) {
	subs, alerts := p.clinical.evaluate(now, view)
	tsUs := now.UnixMicro()

	var crewPtr *string
	if view.CrewID != "" {
		c := view.CrewID
		crewPtr = &c
	}

	snap := &contracts.TelemetrySnapshot{
		TsUs:        tsUs,
		CrewID:      crewPtr,
		MissionMode: view.MissionMode,
		AIReady:     view.AIReady,
		Vitals:      p.clinical.vitals,
		Environment: p.clinical.env,
		Subsystems:  subs,
	}
	p.Latest.Store(snap)

	redTriggered := false
	for _, dec := range alerts {
		p.alertsEmitted.Add(1)
		if p.deps.EventCh != nil {
			select {
			case p.deps.EventCh <- dec.Alert:
			default:
				p.eventsDropped.Add(1)
			}
		}
		if p.deps.Store != nil {
			isRed := dec.Alert.Severity == contracts.SeverityRed
			if isRed {
				redTriggered = true
			}
			var alertCrew *string
			if view.CrewID != "" {
				c := view.CrewID
				alertCrew = &c
			}
			if !p.deps.Store.EmitAlert(StoreAlertRecord{
				TsUs:        tsUs,
				CrewID:      alertCrew,
				Alert:       dec.Alert,
				WriteOutbox: isRed,
			}) {
				p.storeDropped.Add(1)
			}
		}
	}

	if redTriggered && p.deps.Store != nil {
		if samples := p.snapshotRing30s(); len(samples) > 0 {
			var dumpCrew *string
			if view.CrewID != "" {
				c := view.CrewID
				dumpCrew = &c
			}
			if !p.deps.Store.EmitCSIBlob(StoreCSIBlobRecord{
				TsUs:    tsUs,
				CrewID:  dumpCrew,
				Reason:  "red_alert_dump",
				Samples: samples,
			}) {
				p.storeDropped.Add(1)
			}
		}
	}
}

func (p *Pipeline) publishLatest(now time.Time, view SessionView) {
	p.evaluateAndPublish(now, view)
}

func (p *Pipeline) snapshotRing30s() []LinkSample {
	total := 0
	for linkIdx := 0; linkIdx < NumLinks; linkIdx++ {
		total += p.ringUsed[linkIdx]
	}
	if total == 0 {
		return nil
	}
	out := make([]LinkSample, 0, total)
	for linkIdx := 0; linkIdx < NumLinks; linkIdx++ {
		used := p.ringUsed[linkIdx]
		if used == 0 {
			continue
		}
		start := (p.ringHead[linkIdx] - used + RingCapacity) % RingCapacity
		for i := 0; i < used; i++ {
			s := p.ring[linkIdx][(start+i)%RingCapacity]
			if s.Valid {
				out = append(out, s)
			}
		}
	}
	return out
}
