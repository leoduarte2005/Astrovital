package ipc

import (
	"context"
	"encoding/json"
	"time"

	"edgespace/central/internal/contracts"
)

// EnqueueCSIWindow queues a CSI_WINDOW on LoPri, dropping the oldest entry if full.
func (c *Client) EnqueueCSIWindow(crewID *string, payload contracts.CSIWindowPayload) error {
	env, err := contracts.NewIPCEnvelope(contracts.IPCMsgCSIWindow, time.Now().UnixMicro(), crewID, nil, payload)
	if err != nil {
		return err
	}
	c.loPriActive.Store(true)
	return c.enqueueLoPri(env)
}

// EnqueuePeripheralSnapshot queues a PERIPHERAL_SNAPSHOT on LoPri.
func (c *Client) EnqueuePeripheralSnapshot(payload contracts.PeripheralSnapshotPayload) error {
	env, err := contracts.NewIPCEnvelope(contracts.IPCMsgPeripheralSnapshot, payload.TimestampUs, nil, nil, payload)
	if err != nil {
		return err
	}
	return c.enqueueLoPri(env)
}

func (c *Client) enqueueLoPri(env contracts.IPCEnvelope) error {
	if !c.connected.Load() {
		c.droppedWindows.Add(1)
		return ErrAIUnavailable
	}
	select {
	case c.loPriCh <- env:
		return nil
	default:
		select {
		case <-c.loPriCh:
			c.droppedWindows.Add(1)
		default:
		}
		select {
		case c.loPriCh <- env:
			return nil
		default:
			c.droppedWindows.Add(1)
			return ErrAIUnavailable
		}
	}
}

// SendSetActiveCrew sends SET_ACTIVE_CREW on HiPri and waits up to CrewAckTimeout (2s).
func (c *Client) SendSetActiveCrew(ctx context.Context, reqID uint64, payload contracts.SetActiveCrewPayload) (contracts.CrewAckPayload, error) {
	if reqID == 0 {
		reqID = c.reqSeq.Add(1)
	}
	crew := payload.CrewID
	env, err := contracts.NewIPCEnvelope(contracts.IPCMsgSetActiveCrew, time.Now().UnixMicro(), &crew, &reqID, payload)
	if err != nil {
		return contracts.CrewAckPayload{}, err
	}
	respEnv, err := c.roundTripHiPri(ctx, env, reqID, c.cfg.CrewAckTimeout)
	if err != nil {
		return contracts.CrewAckPayload{}, err
	}
	var ack contracts.CrewAckPayload
	if err := json.Unmarshal(respEnv.Payload, &ack); err != nil {
		return contracts.CrewAckPayload{}, err
	}
	return ack, nil
}

// SendChatCorrelate sends CHAT_CORRELATE_REQ on HiPri and waits up to ChatTimeout (5s).
func (c *Client) SendChatCorrelate(ctx context.Context, crewID *string, payload contracts.ChatCorrelateReqPayload) (contracts.ChatCorrelateRespPayload, error) {
	reqID := c.reqSeq.Add(1)
	env, err := contracts.NewIPCEnvelope(contracts.IPCMsgChatCorrelateReq, time.Now().UnixMicro(), crewID, &reqID, payload)
	if err != nil {
		return contracts.ChatCorrelateRespPayload{}, err
	}
	respEnv, err := c.roundTripHiPri(ctx, env, reqID, c.cfg.ChatTimeout)
	if err != nil {
		return contracts.ChatCorrelateRespPayload{}, err
	}
	var resp contracts.ChatCorrelateRespPayload
	if err := json.Unmarshal(respEnv.Payload, &resp); err != nil {
		return contracts.ChatCorrelateRespPayload{}, err
	}
	return resp, nil
}

// SendCalibrationStep sends CALIBRATION_STEP on HiPri and waits up to CalibTimeout (2s).
func (c *Client) SendCalibrationStep(ctx context.Context, crewID *string, payload contracts.CalibrationStepPayload) (contracts.CalibrationFeedbackPayload, error) {
	reqID := c.reqSeq.Add(1)
	env, err := contracts.NewIPCEnvelope(contracts.IPCMsgCalibrationStep, time.Now().UnixMicro(), crewID, &reqID, payload)
	if err != nil {
		return contracts.CalibrationFeedbackPayload{}, err
	}
	respEnv, err := c.roundTripHiPri(ctx, env, reqID, c.cfg.CalibTimeout)
	if err != nil {
		return contracts.CalibrationFeedbackPayload{}, err
	}
	var fb contracts.CalibrationFeedbackPayload
	if err := json.Unmarshal(respEnv.Payload, &fb); err != nil {
		return contracts.CalibrationFeedbackPayload{}, err
	}
	return fb, nil
}

func (c *Client) roundTripHiPri(ctx context.Context, env contracts.IPCEnvelope, reqID uint64, timeout time.Duration) (*contracts.IPCEnvelope, error) {
	if !c.connected.Load() {
		return nil, ErrAIUnavailable
	}
	replyCh := make(chan pendingReply, 1)
	var deadline time.Time
	if timeout > 0 {
		deadline = time.Now().Add(timeout)
	}
	c.pendingMu.Lock()
	c.pending[reqID] = pendingReq{
		typ:      env.Type,
		deadline: deadline,
		replyCh:  replyCh,
	}
	c.pendingMu.Unlock()

	select {
	case c.hiPriCh <- env:
	case <-ctx.Done():
		c.deletePending(reqID)
		return nil, ctx.Err()
	default:
		timer := time.NewTimer(100 * time.Millisecond)
		select {
		case c.hiPriCh <- env:
			timer.Stop()
		case <-timer.C:
			c.deletePending(reqID)
			return nil, ErrAIUnavailable
		case <-ctx.Done():
			timer.Stop()
			c.deletePending(reqID)
			return nil, ctx.Err()
		}
	}

	select {
	case rep := <-replyCh:
		if rep.err != nil {
			return nil, rep.err
		}
		return rep.env, nil
	case <-ctx.Done():
		c.deletePending(reqID)
		return nil, ctx.Err()
	}
}

func (c *Client) deletePending(reqID uint64) {
	c.pendingMu.Lock()
	delete(c.pending, reqID)
	c.pendingMu.Unlock()
}
