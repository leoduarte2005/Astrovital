package httpws

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"sync"
	"time"

	"github.com/coder/websocket"

	"edgespace/central/internal/contracts"
)

type wsClient struct {
	hub    *wsHub
	conn   *websocket.Conn
	teleCh chan []byte
	evCh   chan []byte
	cancel context.CancelFunc
	once   sync.Once
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, nil)
	if err != nil {
		s.log.Warn("ws accept failed", "err", err)
		return
	}
	conn.SetReadLimit(maxWSMessageBytes)

	ctx, cancel := context.WithCancel(r.Context())
	c := &wsClient{
		hub:    s.hub,
		conn:   conn,
		teleCh: make(chan []byte, clientTeleBuf),
		evCh:   make(chan []byte, clientEventBuf),
		cancel: cancel,
	}
	s.hub.addClient(c)
	defer func() {
		s.hub.removeClient(c)
		c.closeWith(websocket.StatusNormalClosure, "")
	}()

	s.hub.sendInitialSnapshot(c)

	writeDone := make(chan struct{})
	go func() {
		defer close(writeDone)
		c.writeLoop(ctx)
		cancel()
	}()

	c.readLoop(ctx)
	cancel()
	<-writeDone
}

func (h *wsHub) sendInitialSnapshot(c *wsClient) {
	nowUs := time.Now().UnixMicro()
	crewPayload := contracts.CrewStatePayload{
		MissionMode:         contracts.ModeCabinTomography,
		AIReady:             false,
		CalibrationRequired: false,
	}
	if h.srv.deps.CrewStateFn != nil {
		crewPayload = h.srv.deps.CrewStateFn()
	}
	crewEnv, err := contracts.NewWSEnvelope(contracts.WSMsgCrewState, nowUs, crewPayload.CrewID, nil, crewPayload)
	if err == nil {
		if raw, err := json.Marshal(crewEnv); err == nil {
			select {
			case c.evCh <- raw:
			default:
			}
		}
	}

	clusterPayload := contracts.ClusterStatusPayload{
		Nodes:  []contracts.NodeStatus{},
		AILink: "offline",
	}
	if h.srv.deps.ClusterStatusFn != nil {
		clusterPayload = h.srv.deps.ClusterStatusFn()
	}
	clusterEnv, err := contracts.NewWSEnvelope(contracts.WSMsgClusterStatus, nowUs, nil, nil, clusterPayload)
	if err == nil {
		if raw, err := json.Marshal(clusterEnv); err == nil {
			select {
			case c.evCh <- raw:
			default:
			}
		}
	}

	if raw, err := h.buildTelemetryFrameBytes(); err == nil {
		select {
		case c.teleCh <- raw:
		default:
		}
	}
}

func (c *wsClient) closeWith(code websocket.StatusCode, reason string) {
	c.once.Do(func() {
		_ = c.conn.Close(code, reason)
		c.cancel()
	})
}

func (c *wsClient) writeLoop(ctx context.Context) {
	ping := time.NewTicker(wsPingInterval)
	defer ping.Stop()

	writeMsg := func(msg []byte) bool {
		wctx, cancel := context.WithTimeout(ctx, wsWriteTimeout)
		err := c.conn.Write(wctx, websocket.MessageText, msg)
		cancel()
		return err == nil
	}

	for {
		// Prioritize events over telemetry frames.
		select {
		case msg := <-c.evCh:
			if !writeMsg(msg) {
				return
			}
			continue
		default:
		}

		select {
		case msg := <-c.evCh:
			if !writeMsg(msg) {
				return
			}
		case msg := <-c.teleCh:
			if !writeMsg(msg) {
				return
			}
		case <-ping.C:
			pctx, cancel := context.WithTimeout(ctx, wsWriteTimeout)
			err := c.conn.Ping(pctx)
			cancel()
			if err != nil {
				return
			}
		case <-ctx.Done():
			return
		}
	}
}

func (c *wsClient) readLoop(ctx context.Context) {
	for {
		_, data, err := c.conn.Read(ctx)
		if err != nil {
			var cerr websocket.CloseError
			if !errors.As(err, &cerr) && ctx.Err() == nil {
				c.hub.log.Debug("ws read ended", "err", err)
			}
			return
		}
		c.handleIncoming(ctx, data)
	}
}

func (c *wsClient) handleIncoming(ctx context.Context, data []byte) {
	var env contracts.WSEnvelope
	if err := json.Unmarshal(data, &env); err != nil {
		c.sendError(nil, "INVALID_JSON", "malformed JSON envelope")
		return
	}
	if err := env.Validate(); err != nil {
		c.sendError(env.ClientMsgID, "INVALID_ENVELOPE", err.Error())
		return
	}
	if err := validateClientPayload(&env); err != nil {
		c.sendError(env.ClientMsgID, "INVALID_PAYLOAD", err.Error())
		return
	}
	sess := c.hub.srv.deps.Session
	if sess == nil {
		return
	}
	crewID := ""
	if env.CrewID != nil {
		crewID = *env.CrewID
	}
	msgID := env.ClientMsgID
	go c.dispatchSessionCmd(ctx, sess, env.Type, crewID, msgID, env.Payload)
}

func (c *wsClient) dispatchSessionCmd(ctx context.Context, sess SessionCommander, typ contracts.WSMsgType, crewID string, msgID *string, raw json.RawMessage) {
	var cmdCtx context.Context
	var cancel context.CancelFunc
	if typ == contracts.WSMsgChatMsg {
		cmdCtx, cancel = context.WithCancel(ctx)
	} else {
		cmdCtx, cancel = context.WithTimeout(ctx, 10*time.Second)
	}
	defer cancel()

	switch typ {
	case contracts.WSMsgSetCrew:
		var p contracts.SetCrewPayload
		_ = json.Unmarshal(raw, &p)
		if _, err := sess.SetCrew(cmdCtx, p.CrewID); err != nil {
			c.sendError(msgID, "SET_CREW_ERROR", err.Error())
		}
	case contracts.WSMsgChatMsg:
		var p contracts.ChatMsgPayload
		_ = json.Unmarshal(raw, &p)
		if _, err := sess.HandleChatMsg(cmdCtx, crewID, p.Text); err != nil {
			c.sendError(msgID, "CHAT_ERROR", err.Error())
		}
	case contracts.WSMsgSelfExam:
		var p contracts.SelfExamPayload
		_ = json.Unmarshal(raw, &p)
		if err := sess.HandleSelfExam(cmdCtx, crewID, p); err != nil {
			c.sendError(msgID, "SELF_EXAM_ERROR", err.Error())
		}
	case contracts.WSMsgCalibrationStep:
		var p contracts.CalibrationStepPayload
		_ = json.Unmarshal(raw, &p)
		if _, err := sess.HandleCalibrationStep(cmdCtx, crewID, p); err != nil {
			c.sendError(msgID, "CALIBRATION_ERROR", err.Error())
		}
	}
}

func validateClientPayload(env *contracts.WSEnvelope) error {
	switch env.Type {
	case contracts.WSMsgSetCrew:
		var p contracts.SetCrewPayload
		if err := json.Unmarshal(env.Payload, &p); err != nil || p.CrewID == "" {
			return errors.New("SET_CREW requires non-empty crew_id")
		}
	case contracts.WSMsgChatMsg:
		var p contracts.ChatMsgPayload
		if err := json.Unmarshal(env.Payload, &p); err != nil || p.Text == "" || len(p.Text) > 2000 {
			return errors.New("CHAT_MSG requires text (1..2000 bytes)")
		}
	case contracts.WSMsgSelfExam:
		var p contracts.SelfExamPayload
		if err := json.Unmarshal(env.Payload, &p); err != nil || p.ExamType == "" {
			return errors.New("SELF_EXAM requires exam_type")
		}
	case contracts.WSMsgCalibrationStep:
		var p contracts.CalibrationStepPayload
		if err := json.Unmarshal(env.Payload, &p); err != nil || p.StepID == "" {
			return errors.New("CALIBRATION_STEP requires step_id")
		}
	default:
		return errors.New("unsupported client message type")
	}
	return nil
}

func (c *wsClient) sendError(clientMsgID *string, code, msg string) {
	env, err := contracts.NewWSEnvelope(
		contracts.WSMsgError,
		time.Now().UnixMicro(),
		nil,
		clientMsgID,
		contracts.ErrorPayload{
			Code:        code,
			Message:     msg,
			ClientMsgID: clientMsgID,
		},
	)
	if err != nil {
		return
	}
	raw, err := json.Marshal(env)
	if err != nil {
		return
	}
	select {
	case c.evCh <- raw:
	default:
		c.closeWith(websocket.StatusPolicyViolation, "slow consumer")
	}
}
