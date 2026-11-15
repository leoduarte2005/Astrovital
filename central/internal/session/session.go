package session

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	"edgespace/central/internal/contracts"
)

type cmdKind int

const (
	cmdSetCrew cmdKind = iota
	cmdReconnect
	cmdSetMode
	cmdChat
	cmdSelfExam
	cmdCalibrationStep
	cmdCrewAck
)

type sessionCmd struct {
	kind   cmdKind
	ctx    context.Context
	crewID string
	mode   contracts.MissionMode

	chatText        string
	lastPeripherals []contracts.PeripheralReading
	lastInference   *contracts.AIInferencePayload

	selfExam  contracts.SelfExamPayload
	calibStep contracts.CalibrationStepPayload

	ackReqID uint64
	ack      contracts.CrewAckPayload

	replyCh chan cmdReply
}

type cmdReply struct {
	crewState contracts.CrewStatePayload
	chatReply contracts.ChatReplyPayload
	calibFb   contracts.CalibrationFeedbackPayload
	err       error
}

type swapResult struct {
	seq       uint64
	crewID    string
	ack       contracts.CrewAckPayload
	err       error
	replyCh   chan cmdReply
	fromRetry bool
}

// Manager owns the active crew session state via a single-writer sessionLoop goroutine.
type Manager struct {
	cfg  Config
	deps Deps

	cmdCh      chan sessionCmd
	swapResCh  chan swapResult
	snap       atomic.Pointer[Snapshot]
	loopCtx    context.Context
	loopCancel context.CancelFunc

	state            Snapshot
	nextReqID        uint64
	pendingSwapReply chan cmdReply

	swapsRequested atomic.Uint64
	swapsCompleted atomic.Uint64
	swapTimeouts   atomic.Uint64
	staleAcks      atomic.Uint64
	reconnectSyncs atomic.Uint64
	chatRequests   atomic.Uint64
	selfExams      atomic.Uint64
	calibSteps     atomic.Uint64
	modeChanges    atomic.Uint64
	uiEventsFailed atomic.Uint64
}

// New constructs a Manager with an initialized immutable Snapshot.
func New(cfg Config, deps Deps) *Manager {
	if cfg.CmdChCap <= 0 {
		cfg.CmdChCap = DefaultCmdChCap
	}
	if !cfg.InitialMode.IsValid() {
		cfg.InitialMode = contracts.ModeCabinTomography
	}
	if cfg.SetCrewTimeout <= 0 {
		cfg.SetCrewTimeout = DefaultSetCrewTimeout
	}
	if cfg.ChatTimeout < 0 {
		cfg.ChatTimeout = DefaultChatTimeout
	}
	if cfg.CalibrationTimeout <= 0 {
		cfg.CalibrationTimeout = DefaultCalibrationTimeout
	}
	if cfg.ChatHistoryLimit <= 0 {
		cfg.ChatHistoryLimit = DefaultChatHistoryLimit
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}

	m := &Manager{
		cfg:       cfg,
		deps:      deps,
		cmdCh:     make(chan sessionCmd, cfg.CmdChCap),
		swapResCh: make(chan swapResult, 16),
		state: Snapshot{
			MissionMode: cfg.InitialMode,
		},
	}
	m.publishSnapshot()
	return m
}

// Snapshot returns the latest immutable session Snapshot via atomic.Pointer.
func (m *Manager) Snapshot() *Snapshot {
	return m.snap.Load()
}

// Metrics returns atomic operational counters.
func (m *Manager) Metrics() Metrics {
	return Metrics{
		SwapsRequested: m.swapsRequested.Load(),
		SwapsCompleted: m.swapsCompleted.Load(),
		SwapTimeouts:   m.swapTimeouts.Load(),
		StaleAcks:      m.staleAcks.Load(),
		ReconnectSyncs: m.reconnectSyncs.Load(),
		ChatRequests:   m.chatRequests.Load(),
		SelfExams:      m.selfExams.Load(),
		CalibSteps:     m.calibSteps.Load(),
		ModeChanges:    m.modeChanges.Load(),
		UIEventsFailed: m.uiEventsFailed.Load(),
	}
}

// Run starts the single-owner sessionLoop until ctx is cancelled.
func (m *Manager) Run(ctx context.Context) error {
	return m.sessionLoop(ctx)
}

func (m *Manager) sessionLoop(ctx context.Context) error {
	loopCtx, cancel := context.WithCancel(ctx)
	m.loopCtx = loopCtx
	m.loopCancel = cancel
	defer cancel()

	for {
		select {
		case <-ctx.Done():
			m.failPendingSwap(ErrStopped)
			return nil
		case cmd := <-m.cmdCh:
			m.handleCmd(cmd)
		case res := <-m.swapResCh:
			m.handleSwapResult(res)
		}
	}
}

func (m *Manager) failPendingSwap(err error) {
	if m.pendingSwapReply != nil {
		m.pendingSwapReply <- cmdReply{crewState: m.crewStatePayload(), err: err}
		m.pendingSwapReply = nil
	}
}

func (m *Manager) enqueue(ctx context.Context, cmd sessionCmd) (cmdReply, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	cmd.ctx = ctx
	cmd.replyCh = make(chan cmdReply, 1)

	select {
	case <-ctx.Done():
		return cmdReply{}, ctx.Err()
	case m.cmdCh <- cmd:
	default:
		return cmdReply{}, ErrBusy
	}

	select {
	case <-ctx.Done():
		return cmdReply{}, ctx.Err()
	case rep := <-cmd.replyCh:
		return rep, rep.err
	}
}

// SetCrew performs an atomic hot-swap to crewID.
func (m *Manager) SetCrew(ctx context.Context, crewID string) (contracts.CrewStatePayload, error) {
	rep, err := m.enqueue(ctx, sessionCmd{
		kind:   cmdSetCrew,
		crewID: strings.TrimSpace(crewID),
	})
	return rep.crewState, err
}

// NotifyIPCReconnect triggers asynchronous re-synchronization of ActiveCrewID on IPC reconnect.
func (m *Manager) NotifyIPCReconnect() {
	select {
	case m.cmdCh <- sessionCmd{kind: cmdReconnect}:
	default:
		slog.Warn("session: cmdCh full on NotifyIPCReconnect")
	}
}

// DeliverCrewAck feeds an asynchronous CREW_ACK correlated by reqID (swap_seq) into sessionLoop.
func (m *Manager) DeliverCrewAck(reqID uint64, ack contracts.CrewAckPayload) {
	select {
	case m.cmdCh <- sessionCmd{kind: cmdCrewAck, ackReqID: reqID, ack: ack}:
	default:
		slog.Warn("session: cmdCh full on DeliverCrewAck", "req_id", reqID)
	}
}

// SetMode validates and applies a new MissionMode, notifying UDP and UI.
func (m *Manager) SetMode(ctx context.Context, mode contracts.MissionMode) (contracts.CrewStatePayload, error) {
	rep, err := m.enqueue(ctx, sessionCmd{
		kind: cmdSetMode,
		mode: mode,
	})
	return rep.crewState, err
}

// HandleChatMsg correlates a crew chat prompt with 24h clinical context via Edge AI.
func (m *Manager) HandleChatMsg(
	ctx context.Context,
	crewID string,
	text string,
	lastPeripherals []contracts.PeripheralReading,
	lastInference *contracts.AIInferencePayload,
) (contracts.ChatReplyPayload, error) {
	rep, err := m.enqueue(ctx, sessionCmd{
		kind:            cmdChat,
		crewID:          strings.TrimSpace(crewID),
		chatText:        text,
		lastPeripherals: lastPeripherals,
		lastInference:   lastInference,
	})
	return rep.chatReply, err
}

// HandleSelfExam persists a self-exam and triggers pipeline threshold re-evaluation.
func (m *Manager) HandleSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload) error {
	_, err := m.enqueue(ctx, sessionCmd{
		kind:     cmdSelfExam,
		crewID:   strings.TrimSpace(crewID),
		selfExam: exam,
	})
	return err
}

// HandleCalibrationStep updates calibration state, forwards step to Edge AI, and emits CALIBRATION_FEEDBACK.
func (m *Manager) HandleCalibrationStep(ctx context.Context, crewID string, step contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	rep, err := m.enqueue(ctx, sessionCmd{
		kind:      cmdCalibrationStep,
		crewID:    strings.TrimSpace(crewID),
		calibStep: step,
	})
	return rep.calibFb, err
}

func (m *Manager) handleCmd(cmd sessionCmd) {
	switch cmd.kind {
	case cmdSetCrew:
		m.execSetCrew(cmd)
	case cmdReconnect:
		m.execReconnect()
	case cmdCrewAck:
		m.handleSwapResult(swapResult{
			seq:    cmd.ackReqID,
			crewID: m.state.ActiveCrewID,
			ack:    cmd.ack,
		})
	case cmdSetMode:
		m.execSetMode(cmd)
	case cmdChat:
		m.execChat(cmd)
	case cmdSelfExam:
		m.execSelfExam(cmd)
	case cmdCalibrationStep:
		m.execCalibrationStep(cmd)
	}
}

func (m *Manager) execSetCrew(cmd sessionCmd) {
	if cmd.crewID == "" {
		cmd.replyCh <- cmdReply{err: ErrInvalidCrewID}
		return
	}
	m.swapsRequested.Add(1)

	// 1) Already active and AIReady -> return current CrewState without side effects.
	if m.state.ActiveCrewID == cmd.crewID && m.state.AIReady {
		cmd.replyCh <- cmdReply{crewState: m.crewStatePayload()}
		return
	}

	// 2) Increment swap_seq and flush store BEFORE loading new profile.
	m.state.SwapSeq++
	seq := m.state.SwapSeq

	if m.deps.Store != nil {
		if err := m.deps.Store.Flush(cmd.ctx); err != nil {
			cmd.replyCh <- cmdReply{err: fmt.Errorf("store flush failed: %w", err)}
			return
		}
	}

	// 3) Load profile + thresholds; error preserves previous crew untouched.
	var data CrewProfileData
	if m.deps.Store != nil {
		var err error
		data, err = m.deps.Store.LoadProfile(cmd.ctx, cmd.crewID)
		if err != nil {
			cmd.replyCh <- cmdReply{err: err}
			return
		}
	} else {
		data = CrewProfileData{
			Profile: contracts.CrewProfile{CrewID: cmd.crewID},
		}
	}
	if data.Profile.CrewID == "" {
		data.Profile.CrewID = cmd.crewID
	}

	// Supersede any in-flight SetCrew reply waiting on an older swap_seq.
	m.failPendingSwap(ErrSwapSuperseded)

	// 4) Update Snapshot with new crew_id and AIReady=false.
	m.state.ActiveCrewID = cmd.crewID
	m.state.Profile = data.Profile
	m.state.BaselinePath = data.BaselinePath
	m.state.Thresholds = cloneThresholds(data.Thresholds)
	m.state.AIReady = false
	m.state.CalibrationRequired = false
	m.state.CalibrationActive = false
	m.state.CalibStepID = ""
	m.publishSnapshot()

	if m.deps.IPC == nil {
		st := m.crewStatePayload()
		m.emitCrewState(st)
		m.recordAudit(cmd.ctx, &cmd.crewID, "CREW_SWAP", "no_ipc_port")
		cmd.replyCh <- cmdReply{crewState: st}
		return
	}

	m.pendingSwapReply = cmd.replyCh
	payload := contracts.SetActiveCrewPayload{
		CrewID:       cmd.crewID,
		BaselinePath: data.BaselinePath,
		Thresholds:   cloneThresholds(data.Thresholds),
	}
	m.dispatchSetActiveCrew(seq, cmd.crewID, payload, false)
}

func (m *Manager) dispatchSetActiveCrew(seq uint64, crewID string, payload contracts.SetActiveCrewPayload, fromRetry bool) {
	parent := m.loopCtx
	if parent == nil {
		parent = context.Background()
	}
	go func() {
		ipcCtx, cancel := context.WithTimeout(parent, m.cfg.SetCrewTimeout)
		defer cancel()
		ack, err := m.deps.IPC.SendSetActiveCrew(ipcCtx, seq, payload)
		res := swapResult{
			seq:       seq,
			crewID:    crewID,
			ack:       ack,
			err:       err,
			fromRetry: fromRetry,
		}
		select {
		case m.swapResCh <- res:
		case <-parent.Done():
		}
	}()
}

func (m *Manager) handleSwapResult(res swapResult) {
	// Discard stale responses from superseded swaps.
	if res.seq != m.state.SwapSeq {
		m.staleAcks.Add(1)
		slog.Debug("session: discarding stale CREW_ACK", "ack_seq", res.seq, "current_seq", m.state.SwapSeq, "ack_crew", res.crewID)
		return
	}

	if res.err == nil && res.ack.OK {
		m.state.AIReady = true
		m.state.CalibrationRequired = !res.ack.BaselineFound
		m.swapsCompleted.Add(1)
		if res.fromRetry {
			m.reconnectSyncs.Add(1)
		}
	} else {
		m.state.AIReady = false
		m.swapTimeouts.Add(1)
		slog.Warn("session: SET_ACTIVE_CREW failed or timed out; continuing in degraded I2C/UI mode",
			"crew_id", res.crewID,
			"swap_seq", res.seq,
			"err", res.err,
			"ack_error", res.ack.Error,
		)
	}

	m.publishSnapshot()
	st := m.crewStatePayload()
	m.emitCrewState(st)

	cid := m.state.ActiveCrewID
	detail := fmt.Sprintf("swap_seq=%d ai_ready=%v calib_req=%v", res.seq, m.state.AIReady, m.state.CalibrationRequired)
	m.recordAudit(context.Background(), &cid, "CREW_SWAP", detail)

	if m.pendingSwapReply != nil {
		m.pendingSwapReply <- cmdReply{crewState: st}
		m.pendingSwapReply = nil
	}
}

func (m *Manager) execReconnect() {
	if m.state.ActiveCrewID == "" || m.deps.IPC == nil {
		return
	}
	seq := m.state.SwapSeq
	payload := contracts.SetActiveCrewPayload{
		CrewID:       m.state.ActiveCrewID,
		BaselinePath: m.state.BaselinePath,
		Thresholds:   cloneThresholds(m.state.Thresholds),
	}
	m.dispatchSetActiveCrew(seq, m.state.ActiveCrewID, payload, true)
}

func (m *Manager) execSetMode(cmd sessionCmd) {
	if !cmd.mode.IsValid() {
		cmd.replyCh <- cmdReply{err: ErrInvalidMode}
		return
	}
	m.state.MissionMode = cmd.mode
	m.modeChanges.Add(1)
	m.publishSnapshot()

	if m.deps.UDP != nil {
		if err := m.deps.UDP.SendModeCmd(cmd.ctx, cmd.mode); err != nil {
			cmd.replyCh <- cmdReply{err: err}
			return
		}
	}

	st := m.crewStatePayload()
	m.emitCrewState(st)
	m.recordAudit(cmd.ctx, crewPtr(m.state.ActiveCrewID), "MODE_CHANGE", string(cmd.mode))
	cmd.replyCh <- cmdReply{crewState: st}
}

func (m *Manager) execSelfExam(cmd sessionCmd) {
	if strings.TrimSpace(cmd.selfExam.ExamType) == "" || strings.TrimSpace(cmd.selfExam.Result) == "" {
		cmd.replyCh <- cmdReply{err: ErrInvalidInput}
		return
	}
	targetCrew := cmd.crewID
	if targetCrew == "" {
		targetCrew = m.state.ActiveCrewID
	}
	if targetCrew == "" {
		cmd.replyCh <- cmdReply{err: ErrNoActiveCrew}
		return
	}

	now := m.cfg.Now()
	if m.deps.Store != nil {
		if err := m.deps.Store.SaveSelfExam(cmd.ctx, targetCrew, cmd.selfExam, now.UnixMicro()); err != nil {
			cmd.replyCh <- cmdReply{err: err}
			return
		}
	}
	m.selfExams.Add(1)
	if m.deps.SelfExamNotifier != nil {
		m.deps.SelfExamNotifier.NotifySelfExam(cmd.selfExam, now)
	}
	cmd.replyCh <- cmdReply{}
}

func (m *Manager) execChat(cmd sessionCmd) {
	if m.state.ActiveCrewID == "" {
		cmd.replyCh <- cmdReply{err: ErrNoActiveCrew}
		return
	}
	if cmd.crewID != "" && cmd.crewID != m.state.ActiveCrewID {
		cmd.replyCh <- cmdReply{err: ErrCrewMismatch}
		return
	}
	text := strings.TrimSpace(cmd.chatText)
	if text == "" || len(text) > MaxChatTextBytes {
		cmd.replyCh <- cmdReply{err: ErrInvalidInput}
		return
	}
	if m.deps.IPC == nil {
		cmd.replyCh <- cmdReply{err: fmt.Errorf("session: IPC port not configured")}
		return
	}

	m.chatRequests.Add(1)
	m.nextReqID++
	reqID := m.nextReqID
	crewID := m.state.ActiveCrewID
	profile := m.state.Profile
	thresholds := cloneThresholds(m.state.Thresholds)
	peripherals := append([]contracts.PeripheralReading(nil), cmd.lastPeripherals...)
	var infCopy *contracts.AIInferencePayload
	if cmd.lastInference != nil {
		v := *cmd.lastInference
		infCopy = &v
	}

	go func() {
		var summary24h string
		var history []contracts.ChatMessage
		if m.deps.Store != nil {
			if s, err := m.deps.Store.LoadSummary24h(cmd.ctx, crewID); err == nil {
				summary24h = s
			}
			if h, err := m.deps.Store.LoadRecentChat(cmd.ctx, crewID, m.cfg.ChatHistoryLimit); err == nil {
				history = h
			}
		}

		req := contracts.ChatCorrelateReqPayload{
			Text:            text,
			CrewID:          crewID,
			Profile:         &profile,
			Thresholds:      thresholds,
			LastPeripherals: peripherals,
			LastInference:   infCopy,
			Summary24h:      summary24h,
			RecentHistory:   history,
		}

		var ipcCtx context.Context
		var cancel context.CancelFunc
		if m.cfg.ChatTimeout > 0 {
			ipcCtx, cancel = context.WithTimeout(cmd.ctx, m.cfg.ChatTimeout)
		} else {
			ipcCtx, cancel = context.WithCancel(cmd.ctx)
		}
		defer cancel()
		resp, err := m.deps.IPC.SendChatCorrelate(ipcCtx, reqID, req)
		if err != nil {
			cmd.replyCh <- cmdReply{err: err}
			return
		}

		tsUs := m.cfg.Now().UnixMicro()
		if m.deps.Store != nil {
			if err := m.deps.Store.SaveChat(cmd.ctx, crewID, contracts.ChatMsgPayload{Text: text}, resp, tsUs); err != nil {
				slog.Warn("session: failed to persist chat", "crew_id", crewID, "err", err)
			}
			if resp.Escalation == contracts.EscalationStoreAndForward {
				outbox := contracts.OutboxRecord{
					OutboxID:    fmt.Sprintf("chat-%d-%d", tsUs, reqID),
					TsUs:        tsUs,
					Subsystem:   contracts.SubsystemNeurobehavioralRadiation,
					Severity:    contracts.SeverityRed,
					Message:     resp.Text,
					Destination: "ground_control",
					Sent:        false,
				}
				if err := m.deps.Store.SaveOutbox(cmd.ctx, outbox); err != nil {
					slog.Warn("session: failed to save outbox record", "crew_id", crewID, "err", err)
				}
				m.recordAudit(cmd.ctx, &crewID, "CHAT_STORE_AND_FORWARD", resp.Text)
			}
		}

		disclaimer := resp.Disclaimer
		if disclaimer == "" {
			disclaimer = DefaultChatDisclaimer
		}
		reply := contracts.ChatReplyPayload{
			Text:                   resp.Text,
			Evidence:               resp.Evidence,
			Countermeasures:        resp.Countermeasures,
			SourceIDs:              resp.SourceIDs,
			Escalation:             resp.Escalation,
			Disclaimer:             disclaimer,
			Differentials:          resp.Differentials,
			DisambiguationQuestion: resp.DisambiguationQuestion,
			Actions:                resp.Actions,
		}
		m.emitUI(UIEvent{
			Type:      contracts.WSMsgChatReply,
			TsUs:      tsUs,
			CrewID:    crewPtr(crewID),
			ChatReply: &reply,
		})
		cmd.replyCh <- cmdReply{chatReply: reply}
	}()
}

func (m *Manager) execCalibrationStep(cmd sessionCmd) {
	if strings.TrimSpace(cmd.calibStep.StepID) == "" || strings.TrimSpace(cmd.calibStep.Action) == "" {
		cmd.replyCh <- cmdReply{err: ErrInvalidInput}
		return
	}
	targetCrew := cmd.crewID
	if targetCrew == "" {
		targetCrew = m.state.ActiveCrewID
	}
	if targetCrew == "" {
		cmd.replyCh <- cmdReply{err: ErrNoActiveCrew}
		return
	}
	if m.state.ActiveCrewID != "" && targetCrew != m.state.ActiveCrewID {
		cmd.replyCh <- cmdReply{err: ErrCrewMismatch}
		return
	}

	m.calibSteps.Add(1)
	act := strings.ToLower(strings.TrimSpace(cmd.calibStep.Action))
	if act == "stop" || act == "cancel" || act == "complete" || act == "finish" {
		m.state.CalibrationActive = false
		m.state.CalibStepID = ""
	} else {
		m.state.CalibrationActive = true
		m.state.CalibStepID = cmd.calibStep.StepID
	}
	m.publishSnapshot()

	if m.deps.IPC == nil {
		fb := contracts.CalibrationFeedbackPayload{
			StepID:   cmd.calibStep.StepID,
			Progress: 100,
			Quality:  1.0,
		}
		m.emitUI(UIEvent{
			Type:                contracts.WSMsgCalibrationFeedback,
			TsUs:                m.cfg.Now().UnixMicro(),
			CrewID:              crewPtr(targetCrew),
			CalibrationFeedback: &fb,
		})
		cmd.replyCh <- cmdReply{calibFb: fb}
		return
	}

	m.nextReqID++
	reqID := m.nextReqID
	step := cmd.calibStep

	go func() {
		ipcCtx, cancel := context.WithTimeout(cmd.ctx, m.cfg.CalibrationTimeout)
		defer cancel()
		fb, err := m.deps.IPC.SendCalibrationStep(ipcCtx, reqID, targetCrew, step)
		if err != nil {
			cmd.replyCh <- cmdReply{err: err}
			return
		}
		if len(fb.BaselineUpdate) > 0 {
			if saver, ok := m.deps.Store.(interface {
				SaveBaseline(context.Context, string, []byte, int64) error
			}); ok {
				if err := saver.SaveBaseline(cmd.ctx, targetCrew, []byte(fb.BaselineUpdate), m.cfg.Now().UnixMicro()); err != nil {
					cmd.replyCh <- cmdReply{err: err}
					return
				}
			}
			fb.BaselineUpdate = nil
		}
		m.emitUI(UIEvent{
			Type:                contracts.WSMsgCalibrationFeedback,
			TsUs:                m.cfg.Now().UnixMicro(),
			CrewID:              crewPtr(targetCrew),
			CalibrationFeedback: &fb,
		})
		cmd.replyCh <- cmdReply{calibFb: fb}
	}()
}

func (m *Manager) publishSnapshot() {
	cp := m.state
	cp.Thresholds = cloneThresholds(m.state.Thresholds)
	m.snap.Store(&cp)
}

func (m *Manager) crewStatePayload() contracts.CrewStatePayload {
	var profile *contracts.CrewSummary
	if m.state.ActiveCrewID != "" {
		profile = &contracts.CrewSummary{
			CrewID:              m.state.ActiveCrewID,
			Name:                m.state.Profile.Name,
			Role:                m.state.Profile.Role,
			MissionDay:          m.state.Profile.MissionDay,
			CalibrationRequired: m.state.CalibrationRequired,
		}
	}
	return contracts.CrewStatePayload{
		CrewID:              crewPtr(m.state.ActiveCrewID),
		Profile:             profile,
		MissionMode:         m.state.MissionMode,
		AIReady:             m.state.AIReady,
		CalibrationRequired: m.state.CalibrationRequired,
	}
}

func (m *Manager) emitCrewState(st contracts.CrewStatePayload) {
	m.emitUI(UIEvent{
		Type:      contracts.WSMsgCrewState,
		TsUs:      m.cfg.Now().UnixMicro(),
		CrewID:    st.CrewID,
		CrewState: &st,
	})
}

func (m *Manager) emitUI(ev UIEvent) {
	if m.deps.UI == nil {
		return
	}
	if !m.deps.UI.EmitEvent(ev) {
		m.uiEventsFailed.Add(1)
	}
}

func (m *Manager) recordAudit(ctx context.Context, crewID *string, eventType, details string) {
	if m.deps.Store == nil {
		return
	}
	if err := m.deps.Store.SaveAudit(ctx, crewID, eventType, details, m.cfg.Now().UnixMicro()); err != nil {
		slog.Warn("session: failed to save audit event", "event_type", eventType, "err", err)
	}
}

func crewPtr(crewID string) *string {
	if crewID == "" {
		return nil
	}
	c := crewID
	return &c
}

func cloneThresholds(src map[string]contracts.Threshold) map[string]contracts.Threshold {
	if len(src) == 0 {
		return nil
	}
	dst := make(map[string]contracts.Threshold, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}
