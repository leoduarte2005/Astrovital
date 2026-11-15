package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"edgespace/central/internal/cluster"
	"edgespace/central/internal/contracts"
	"edgespace/central/internal/httpws"
	"edgespace/central/internal/ipc"
	"edgespace/central/internal/pipeline"
	"edgespace/central/internal/session"
	"edgespace/central/internal/sim"
	"edgespace/central/internal/store"
	"edgespace/central/internal/udp"
)

type storeSessionAdapter struct {
	st *store.Store
}

func (a storeSessionAdapter) Flush(ctx context.Context) error { return a.st.Flush(ctx) }
func (a storeSessionAdapter) LoadProfile(ctx context.Context, crewID string) (session.CrewProfileData, error) {
	rec, err := a.st.GetCrewProfile(ctx, crewID)
	if err != nil {
		return session.CrewProfileData{}, err
	}
	return session.CrewProfileData{
		Profile:      rec.Profile,
		BaselinePath: rec.BaselinePath,
		Thresholds:   rec.Thresholds,
	}, nil
}
func (a storeSessionAdapter) LoadSummary24h(ctx context.Context, crewID string) (string, error) {
	return a.st.Summary24h(ctx, crewID)
}
func (a storeSessionAdapter) LoadRecentChat(ctx context.Context, crewID string, limit int) ([]contracts.ChatMessage, error) {
	return a.st.RecentChat(ctx, crewID, limit)
}
func (a storeSessionAdapter) SaveAudit(ctx context.Context, crewID *string, eventType, details string, tsUs int64) error {
	return a.st.SaveAudit(ctx, crewID, eventType, details, tsUs)
}
func (a storeSessionAdapter) SaveBaseline(ctx context.Context, crew string, data []byte, ts int64) error {
	return a.st.SaveBaselineUpdate(ctx, crew, data, ts)
}
func (a storeSessionAdapter) SaveChat(ctx context.Context, crewID string, req contracts.ChatMsgPayload, resp contracts.ChatCorrelateRespPayload, tsUs int64) error {
	return a.st.SaveChatExchange(ctx, crewID, req, resp, tsUs)
}
func (a storeSessionAdapter) SaveSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload, tsUs int64) error {
	return a.st.SaveSelfExam(ctx, crewID, exam, tsUs)
}
func (a storeSessionAdapter) SaveOutbox(ctx context.Context, rec contracts.OutboxRecord) error {
	return a.st.SaveOutbox(ctx, rec)
}

type storeHTTPAdapter struct {
	st *store.Store
}

func (a storeHTTPAdapter) Health(ctx context.Context) error { return a.st.Health(ctx) }
func (a storeHTTPAdapter) ListCrew(ctx context.Context) ([]contracts.CrewSummary, error) {
	return a.st.ListCrew(ctx)
}
func (a storeHTTPAdapter) GetCrewProfile(ctx context.Context, id string) (httpws.CrewProfileDTO, error) {
	rec, err := a.st.GetCrewProfile(ctx, id)
	if err != nil {
		return httpws.CrewProfileDTO{}, err
	}
	return httpws.CrewProfileDTO{
		Profile:             rec.Profile,
		BaselinePath:        rec.BaselinePath,
		CalibrationRequired: rec.BaselinePath == "",
		Thresholds:          rec.Thresholds,
	}, nil
}
func (a storeHTTPAdapter) QueryTimeseries(ctx context.Context, crewID, metric string, fromUs, toUs int64, bucketSec int) (contracts.TimeseriesResponse, error) {
	return a.st.QueryTimeseries(ctx, crewID, metric, fromUs, toUs, bucketSec)
}
func (a storeHTTPAdapter) GetProtocol(ctx context.Context, id string) (contracts.ProtocolDTO, error) {
	return a.st.GetProtocol(ctx, id)
}
func (a storeHTTPAdapter) ListAlerts(ctx context.Context, limit int) ([]contracts.AlertRecord, error) {
	return a.st.ListAlerts(ctx, limit)
}
func (a storeHTTPAdapter) ListOutbox(ctx context.Context) ([]contracts.OutboxRecord, error) {
	return a.st.ListOutbox(ctx)
}

type ipcSessionAdapter struct {
	client *ipc.Client
}

func (a ipcSessionAdapter) SendSetActiveCrew(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
	return a.client.SendSetActiveCrew(ctx, reqID, payload)
}
func (a ipcSessionAdapter) SendChatCorrelate(ctx context.Context, reqID uint64, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error) {
	cid := payload.CrewID
	return a.client.SendChatCorrelate(ctx, &cid, payload)
}
func (a ipcSessionAdapter) SendCalibrationStep(ctx context.Context, reqID uint64, crewID string, payload contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	var cid *string
	if crewID != "" {
		c := crewID
		cid = &c
	}
	return a.client.SendCalibrationStep(ctx, cid, payload)
}

type udpSessionAdapter struct {
	tx     *udp.Transmitter
	inproc bool
	log    *slog.Logger
}

func (a udpSessionAdapter) SendModeCmd(ctx context.Context, mode contracts.MissionMode) error {
	if a.inproc || a.tx == nil {
		return nil
	}
	return a.tx.SendModeCmd(mode)
}

type uiSessionAdapter struct {
	eventCh chan<- contracts.WSEnvelope
}

func (a uiSessionAdapter) EmitEvent(ev session.UIEvent) bool {
	var payload any
	switch ev.Type {
	case contracts.WSMsgCrewState:
		if ev.CrewState == nil {
			return false
		}
		payload = ev.CrewState
	case contracts.WSMsgChatReply:
		if ev.ChatReply == nil {
			return false
		}
		payload = ev.ChatReply
	case contracts.WSMsgCalibrationFeedback:
		if ev.CalibrationFeedback == nil {
			return false
		}
		payload = ev.CalibrationFeedback
	default:
		return false
	}
	env, err := contracts.NewWSEnvelope(ev.Type, ev.TsUs, ev.CrewID, nil, payload)
	if err != nil {
		return false
	}
	select {
	case a.eventCh <- env:
		return true
	default:
		return false
	}
}

type pipelineSessionAdapter struct {
	sess *session.Manager
}

func (a pipelineSessionAdapter) Snapshot() pipeline.SessionView {
	sn := a.sess.Snapshot()
	if sn == nil {
		return pipeline.SessionView{MissionMode: contracts.ModeCabinTomography}
	}
	return pipeline.SessionView{
		CrewID:            sn.ActiveCrewID,
		MissionMode:       sn.MissionMode,
		AIReady:           sn.AIReady,
		CalibrationActive: sn.CalibrationActive,
		CalibrationStepID: sn.CalibStepID,
		Thresholds:        sn.Thresholds,
	}
}

type pipelineMaskAdapter struct {
	cm *cluster.Manager
}

func (a pipelineMaskAdapter) ActiveLinkMask() uint32 {
	sm := a.cm.SlotMap()
	if sm == nil {
		return 0
	}
	return sm.ActiveLinkMask
}

type pipelineIPCAdapter struct {
	client *ipc.Client
}

func (a pipelineIPCAdapter) TrySendCSIWindow(msg pipeline.CSIWindowEmit) bool {
	return a.client.EnqueueCSIWindow(msg.CrewID, msg.Payload) == nil
}
func (a pipelineIPCAdapter) TrySendPeripheralSnapshot(msg pipeline.PeripheralSnapshotEmit) bool {
	return a.client.EnqueuePeripheralSnapshot(msg.Payload) == nil
}

type pipelineStoreAdapter struct {
	st *store.Store
}

func (a pipelineStoreAdapter) EmitTelemetry1Hz(rec pipeline.StoreTelemetryRecord) bool {
	return a.st.SaveTelemetry1Hz(context.Background(), store.Telemetry1HzRecord{
		TsUs:        rec.TsUs,
		CrewID:      rec.CrewID,
		MissionMode: rec.MissionMode,
		Vitals:      rec.Vitals,
		Environment: rec.Environment,
	}) == nil
}

func (a pipelineStoreAdapter) EmitPeripherals1Hz(rec pipeline.StorePeripheralRecord) bool {
	out := make([]store.PeripheralReadingRecord, 0, len(rec.Readings))
	for _, r := range rec.Readings {
		out = append(out, store.PeripheralReadingRecord{
			CrewID: rec.CrewID,
			NodeID: r.NodeID,
			Type:   r.Type,
			Value:  r.Value,
			Unit:   r.Unit,
			TsUs:   r.TsUs,
		})
	}
	return a.st.SavePeripheral1Hz(context.Background(), rec.TsUs, out) == nil
}

func (a pipelineStoreAdapter) EmitAlert(rec pipeline.StoreAlertRecord) bool {
	return a.st.SaveAlertAndOutbox(context.Background(), store.AlertWriteRecord{
		TsUs:        rec.TsUs,
		CrewID:      rec.CrewID,
		Alert:       rec.Alert,
		WriteOutbox: rec.WriteOutbox,
	}) == nil
}

func (a pipelineStoreAdapter) EmitCSIBlob(rec pipeline.StoreCSIBlobRecord) bool {
	blob, err := json.Marshal(struct {
		Window            *contracts.CSIWindowPayload `json:"window,omitempty"`
		Samples           []pipeline.LinkSample       `json:"samples,omitempty"`
		CycleSeqFirst     uint32                      `json:"cycle_seq_first"`
		CalibrationStepID string                      `json:"calibration_step_id,omitempty"`
	}{rec.Window, rec.Samples, rec.CycleSeqFirst, rec.CalibrationStepID})
	if err != nil || (rec.Window == nil && len(rec.Samples) == 0) {
		return false
	}
	return a.st.SaveCSIBlob(context.Background(), store.CSIBlobWriteRecord{
		TsUs:   rec.TsUs,
		CrewID: rec.CrewID,
		Reason: rec.Reason,
		Blob:   blob,
	}) == nil
}

type httpSessionAdapter struct {
	sess    *session.Manager
	latest  *atomic.Pointer[contracts.TelemetrySnapshot]
	lastInf *atomic.Pointer[contracts.AIInferencePayload]
}

func (a httpSessionAdapter) SetCrew(ctx context.Context, crewID string) (contracts.CrewStatePayload, error) {
	return a.sess.SetCrew(ctx, crewID)
}

func (a httpSessionAdapter) HandleChatMsg(ctx context.Context, crewID, text string) (contracts.ChatReplyPayload, error) {
	var periphs []contracts.PeripheralReading
	if snap := a.latest.Load(); snap != nil {
		ts := snap.TsUs
		periphs = []contracts.PeripheralReading{
			{Type: contracts.PeripheralSCD40, Value: snap.Environment.CO2Ppm, Unit: "ppm", TimestampUs: ts},
			{Type: contracts.PeripheralBME280, Value: snap.Environment.TempC, Unit: "C", TimestampUs: ts},
			{Type: contracts.PeripheralMAX30102, Value: snap.Vitals.SpO2Pct, Unit: "%", TimestampUs: ts},
		}
	}
	return a.sess.HandleChatMsg(ctx, crewID, text, periphs, a.lastInf.Load())
}

func (a httpSessionAdapter) HandleSelfExam(ctx context.Context, crewID string, exam contracts.SelfExamPayload) error {
	return a.sess.HandleSelfExam(ctx, crewID, exam)
}

func (a httpSessionAdapter) HandleCalibrationStep(ctx context.Context, crewID string, step contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	return a.sess.HandleCalibrationStep(ctx, crewID, step)
}

type simClusterSinkAdapter struct {
	ctx    context.Context
	cm     *cluster.Manager
	dataCh chan<- pipeline.DataMsg
	log    *slog.Logger
}

func (a simClusterSinkAdapter) PushControl(ev sim.ControlEvent) bool {
	switch ev.Type {
	case contracts.UDPMsgNodeHello:
		if ev.Hello != nil {
			if _, err := a.cm.HandleNodeHello(a.ctx, *ev.Hello); err != nil {
				a.log.Warn("cluster hello failed", "err", err)
			}
		}
	case contracts.UDPMsgHeartbeat:
		if ev.Heartbeat != nil {
			if err := a.cm.HandleHeartbeat(a.ctx, *ev.Heartbeat); err != nil {
				a.log.Warn("cluster heartbeat failed", "err", err)
			}
		}
	}
	return true
}

func (a simClusterSinkAdapter) PushData(ev sim.DataEvent) bool {
	if ev.Type == contracts.UDPMsgCSIFrame && ev.CSI != nil {
		a.cm.HandlePacketSeen(ev.CSI.RxNodeID, int(ev.CSI.RSSIDbm))
	} else if ev.Type == contracts.UDPMsgPeripheralData && ev.Peripheral != nil {
		a.cm.HandlePeripherals(ev.Peripheral.NodeID, ev.Peripheral.Peripherals)
	}
	msg := pipeline.DataMsg{
		Type:       ev.Type,
		CSI:        ev.CSI,
		Peripheral: ev.Peripheral,
		ReceivedAt: ev.ReceivedAt,
		SrcAddr:    ev.SrcAddr,
	}
	select {
	case a.dataCh <- msg:
		return true
	default:
		return false
	}
}

type devControllerAdapter struct {
	mc *sim.MockCluster
	ai *sim.MockAI
}

func (a devControllerAdapter) SetScenario(ctx context.Context, scenario string, seed int64) error {
	if !sim.IsValidScenario(scenario) {
		return fmt.Errorf("invalid scenario %q", scenario)
	}
	if a.mc != nil {
		return a.mc.SetScenario(scenario)
	}
	if a.ai != nil {
		a.ai.SetScenario(scenario)
	}
	return nil
}

func (a devControllerAdapter) KillNode(ctx context.Context, nodeID uint8) error {
	if a.mc == nil {
		return fmt.Errorf("mock cluster not enabled")
	}
	a.mc.KillNode(nodeID)
	return nil
}

func (a devControllerAdapter) ReviveNode(ctx context.Context, nodeID uint8) error {
	if a.mc == nil {
		return fmt.Errorf("mock cluster not enabled")
	}
	a.mc.ReviveNode(nodeID)
	return nil
}

type selfExamNotifierAdapter struct {
	ch chan<- pipeline.SelfExamInput
}

func (a selfExamNotifierAdapter) NotifySelfExam(exam contracts.SelfExamPayload, receivedAt time.Time) {
	select {
	case a.ch <- pipeline.SelfExamInput{Payload: exam, ReceivedAt: receivedAt}:
	default:
	}
}

type clusterSlotPlanAdapter struct {
	cm *cluster.Manager
}

func (a clusterSlotPlanAdapter) CurrentSlotPlan() udp.SlotPlan {
	sm := a.cm.SlotMap()
	if sm == nil {
		return udp.SlotPlan{}
	}
	return udp.SlotPlan{
		SlotMs:         sm.SlotMs,
		ActiveNodeMask: sm.ActiveNodeMask,
		Slots:          sm.Slots,
	}
}

func buildClusterStatusPayload(snap contracts.ClusterSnapshot, aiStats ipc.Stats, udpSink *udp.ChannelSink) contracts.ClusterStatusPayload {
	var df, dc uint64
	if udpSink != nil {
		df = udpSink.DroppedFrames()
		dc = udpSink.DroppedCtrl()
	}
	nodes := snap.Nodes
	if nodes == nil {
		nodes = []contracts.NodeStatus{}
	}
	return contracts.ClusterStatusPayload{
		Nodes:          nodes,
		ActiveLinks:    snap.ActiveLinks,
		TotalLinks:     snap.TotalLinks,
		AILink:         aiStats.AILink,
		DroppedFrames:  df,
		DroppedCtrl:    dc,
		DroppedWindows: aiStats.DroppedWindows,
	}
}

func startBridges(
	ctx context.Context,
	wg *sync.WaitGroup,
	log *slog.Logger,
	wsEventCh chan<- contracts.WSEnvelope,
	wsOutCh <-chan contracts.WSEnvelope,
	pipeInfCh chan<- contracts.AIInferencePayload,
	pipeEventCh <-chan contracts.AlertEventPayload,
	pipeDataCh chan<- pipeline.DataMsg,
	udpSink *udp.ChannelSink,
	cm *cluster.Manager,
	ipcClient *ipc.Client,
	sessMgr *session.Manager,
	lastInf *atomic.Pointer[contracts.AIInferencePayload],
	latestCluster *atomic.Pointer[contracts.ClusterStatusPayload],
) {
	// 1. session UI events -> httpws EventCh
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case env := <-wsOutCh:
				select {
				case wsEventCh <- env:
				default:
				}
			}
		}
	}()

	// 2. ipc InferenceCh -> lastInference + pipeline InferenceCh
	wg.Add(1)
	go func() {
		defer wg.Done()
		infCh := ipcClient.InferenceCh()
		for {
			select {
			case <-ctx.Done():
				return
			case msg := <-infCh:
				infCopy := msg.Payload
				lastInf.Store(&infCopy)
				select {
				case pipeInfCh <- msg.Payload:
				default:
				}
			}
		}
	}()

	// 3. cluster StatusCh -> latestClusterStatus + httpws EventCh
	wg.Add(1)
	go func() {
		defer wg.Done()
		stCh := cm.StatusCh()
		for {
			select {
			case <-ctx.Done():
				return
			case snap := <-stCh:
				cs := buildClusterStatusPayload(snap, ipcClient.Stats(), udpSink)
				csCopy := cs
				latestCluster.Store(&csCopy)
				env, err := contracts.NewWSEnvelope(contracts.WSMsgClusterStatus, snap.TsUs, nil, nil, cs)
				if err != nil {
					continue
				}
				select {
				case wsEventCh <- env:
				default:
				}
			}
		}
	}()

	// 4. pipeline EventCh -> httpws EventCh (ALERT_EVENT)
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case al := <-pipeEventCh:
				var crewPtr *string
				if sn := sessMgr.Snapshot(); sn != nil && sn.ActiveCrewID != "" {
					c := sn.ActiveCrewID
					crewPtr = &c
				}
				env, err := contracts.NewWSEnvelope(contracts.WSMsgAlertEvent, time.Now().UnixMicro(), crewPtr, nil, al)
				if err != nil {
					continue
				}
				select {
				case wsEventCh <- env:
				default:
				}
			}
		}
	}()

	// 5. udpSink -> cluster & pipeline (when UDP RX is active)
	if udpSink != nil {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case msg := <-udpSink.ControlCh:
					switch msg.Type {
					case contracts.UDPMsgNodeHello:
						if msg.Hello != nil {
							if _, err := cm.HandleNodeHello(ctx, *msg.Hello); err != nil {
								log.Warn("udp hello failed", "err", err)
							}
						}
					case contracts.UDPMsgHeartbeat:
						if msg.Heartbeat != nil {
							if err := cm.HandleHeartbeat(ctx, *msg.Heartbeat); err != nil {
								log.Warn("udp heartbeat failed", "err", err)
							}
						}
					}
				}
			}
		}()

		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case msg := <-udpSink.DataCh:
					if msg.Type == contracts.UDPMsgCSIFrame && msg.CSI != nil {
						cm.HandlePacketSeen(msg.CSI.RxNodeID, int(msg.CSI.RSSIDbm))
					} else if msg.Type == contracts.UDPMsgPeripheralData && msg.Peripheral != nil {
						cm.HandlePeripherals(msg.Peripheral.NodeID, msg.Peripheral.Peripherals)
					}
					pmsg := pipeline.DataMsg{
						Type:       msg.Type,
						CSI:        msg.CSI,
						Peripheral: msg.Peripheral,
						ReceivedAt: msg.ReceivedAt,
						SrcAddr:    msg.SrcAddr,
					}
					select {
					case pipeDataCh <- pmsg:
					default:
					}
				}
			}
		}()
	}
}

func waitStep(shutCtx context.Context, log *slog.Logger, name string, done chan error, exitCode *int) {
	if done == nil {
		return
	}
	select {
	case err := <-done:
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Error(name+" shutdown error", "err", err)
			*exitCode = 1
		}
	case <-shutCtx.Done():
		log.Warn(name + " shutdown timeout")
		*exitCode = 1
	}
}

func buildMockCluster(
	ctx context.Context,
	cfg config,
	log *slog.Logger,
	clusterMgr *cluster.Manager,
	sessMgr *session.Manager,
	pipeDataCh chan<- pipeline.DataMsg,
	udpRx *udp.Receiver,
	mockAI *sim.MockAI,
) (*sim.MockCluster, error) {
	simMode := sim.SimModeInproc
	targetAddr := ""
	if cfg.mockCluster == "udp" {
		simMode = sim.SimModeUDP
		if err := udpRx.Bind(); err != nil {
			return nil, fmt.Errorf("udp rx bind failed: %w", err)
		}
		if addr := udpRx.Addr(); addr != nil {
			targetAddr = addr.String()
		}
	}
	var sink sim.ClusterSink
	if simMode == sim.SimModeInproc {
		sink = simClusterSinkAdapter{ctx: ctx, cm: clusterMgr, dataCh: pipeDataCh, log: log}
	}
	return sim.NewMockCluster(sim.MockClusterConfig{
		Mode:       simMode,
		TargetAddr: targetAddr,
		Seed:       cfg.seed,
		TimeScale:  cfg.timeScale,
		LossRate:   cfg.simLoss,
		JitterMs:   cfg.simJitterMs,
		Scenario:   cfg.scenario,
		MockAI:     mockAI,
		SlotScheduleFn: func() sim.SlotSchedule {
			sm := clusterMgr.SlotMap()
			if sm == nil {
				return sim.SlotSchedule{}
			}
			return sim.SlotSchedule{ActiveNodeMask: sm.ActiveNodeMask, Slots: sm.Slots}
		},
		MissionModeFn: func() contracts.MissionMode {
			if sn := sessMgr.Snapshot(); sn != nil && sn.MissionMode.IsValid() {
				return sn.MissionMode
			}
			return contracts.ModeCabinTomography
		},
		OnModeChange: func(mode contracts.MissionMode) {
			go func() {
				mctx, mcancel := context.WithTimeout(context.Background(), time.Second)
				defer mcancel()
				if _, err := sessMgr.SetMode(mctx, mode); err != nil {
					log.Warn("sim mode change failed", "mode", mode, "err", err)
				}
			}()
		},
		OnSelfExam: func(ev sim.SelfExamEvent) {
			go func() {
				ectx, ecancel := context.WithTimeout(context.Background(), time.Second)
				defer ecancel()
				res := "normal"
				if ev.Metamorphopsia {
					res = "metamorphopsia"
				}
				if err := sessMgr.HandleSelfExam(ectx, "", contracts.SelfExamPayload{
					ExamType:     ev.Kind,
					Result:       res,
					Observations: fmt.Sprintf("BP %d/%d", ev.SystolicMmHg, ev.DiastolicMmHg),
				}); err != nil {
					log.Warn("sim self exam failed", "err", err)
				}
			}()
		},
	}, sink)
}

func buildHTTPServer(
	cfg config,
	log *slog.Logger,
	st *store.Store,
	sessMgr *session.Manager,
	pipe *pipeline.Pipeline,
	clusterMgr *cluster.Manager,
	ipcClient *ipc.Client,
	udpSink *udp.ChannelSink,
	devCtrl httpws.DevController,
	lastInference *atomic.Pointer[contracts.AIInferencePayload],
	latestClusterStatus *atomic.Pointer[contracts.ClusterStatusPayload],
) (*httpws.Server, error) {
	httpReader := storeHTTPAdapter{st: st}
	return httpws.New(httpws.Config{Addr: cfg.httpAddr, WSHz: cfg.wsHz}, httpws.Deps{
		Logger:         log,
		Reader:         httpReader,
		ExtendedReader: httpReader,
		Session:        httpSessionAdapter{sess: sessMgr, latest: pipe.Latest, lastInf: lastInference},
		Dev:            devCtrl,
		StoreStats: func() httpws.StoreStats {
			stats := st.Stats()
			return httpws.StoreStats{Commits: stats.Commits, Backlog: stats.Backlog}
		},
		ExtraMetrics: func() httpws.ExtraMetrics {
			var df, dc uint64
			if udpSink != nil {
				df = udpSink.DroppedFrames()
				dc = udpSink.DroppedCtrl()
			}
			aiStats := ipcClient.Stats()
			return httpws.ExtraMetrics{
				DroppedFrames: df, DroppedCtrl: dc, IPCDroppedWindows: aiStats.DroppedWindows,
				IPCReconnects: aiStats.Reconnects, LateFrames: pipe.Metrics().LateFrames,
				FailoverLastMs: clusterMgr.FailoverLastMs(),
			}
		},
		CrewStateFn: func() contracts.CrewStatePayload {
			sn := sessMgr.Snapshot()
			if sn == nil {
				return contracts.CrewStatePayload{MissionMode: contracts.ModeCabinTomography}
			}
			var cid *string
			var prof *contracts.CrewSummary
			if sn.ActiveCrewID != "" {
				c := sn.ActiveCrewID
				cid = &c
				prof = &contracts.CrewSummary{
					CrewID: sn.ActiveCrewID, Name: sn.Profile.Name, Role: sn.Profile.Role,
					MissionDay: sn.Profile.MissionDay, CalibrationRequired: sn.CalibrationRequired,
				}
			}
			return contracts.CrewStatePayload{
				CrewID: cid, Profile: prof, MissionMode: sn.MissionMode,
				AIReady: sn.AIReady, CalibrationRequired: sn.CalibrationRequired,
			}
		},
		ClusterStatusFn: func() contracts.ClusterStatusPayload {
			if cs := latestClusterStatus.Load(); cs != nil {
				return *cs
			}
			return buildClusterStatusPayload(clusterMgr.Status(), ipcClient.Stats(), udpSink)
		},
	})
}
