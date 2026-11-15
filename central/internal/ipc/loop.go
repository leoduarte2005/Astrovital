package ipc

import (
	"context"
	"encoding/json"
	"errors"
	"math/rand"
	"net"
	"sync"
	"time"

	"edgespace/central/internal/contracts"
)

// Run maintains the IPC connection with exponential backoff, sweeper and silence watchdog.
func (c *Client) Run(ctx context.Context) error {
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		c.sweepLoop(ctx)
	}()

	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	backoff := c.cfg.MinBackoff

	for ctx.Err() == nil {
		conn, err := c.cfg.Dial(ctx, c.cfg.Addr)
		if err != nil {
			jitter := 0.8 + 0.4*rng.Float64()
			wait := time.Duration(float64(backoff) * jitter)
			timer := time.NewTimer(wait)
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				break
			}
			backoff *= 2
			if backoff > c.cfg.MaxBackoff {
				backoff = c.cfg.MaxBackoff
			}
			continue
		}

		backoff = c.cfg.MinBackoff
		if c.hasConnected.Swap(true) {
			c.reconnects.Add(1)
		}
		c.runConn(ctx, conn)
	}

	c.failAllPending(ErrClosed)
	wg.Wait()
	return nil
}

func (c *Client) runConn(ctx context.Context, conn net.Conn) {
	c.connected.Store(true)
	c.degraded.Store(false)
	c.lastRxUs.Store(time.Now().UnixMicro())
	c.log.Info("ipc connected", "addr", c.cfg.Addr)

	if c.onReconnect != nil {
		go c.onReconnect()
	}

	connCtx, cancelConn := context.WithCancel(ctx)
	defer cancelConn()

	var wg sync.WaitGroup
	wg.Add(3)

	go func() {
		defer wg.Done()
		defer cancelConn()
		c.writerLoop(connCtx, conn)
	}()
	go func() {
		defer wg.Done()
		defer cancelConn()
		c.readerLoop(connCtx, conn)
	}()
	go func() {
		defer wg.Done()
		tick := time.NewTicker(c.cfg.SweepInterval)
		defer tick.Stop()
		for {
			select {
			case <-tick.C:
				if c.loPriActive.Load() {
					age := time.Since(time.UnixMicro(c.lastRxUs.Load()))
					if age > c.cfg.SilenceWatchdog {
						c.degraded.Store(true)
						c.log.Warn("ipc silence watchdog triggered", "silence", age)
						_ = conn.Close()
						return
					}
				}
			case <-connCtx.Done():
				return
			}
		}
	}()

	<-connCtx.Done()
	_ = conn.Close()
	wg.Wait()

	c.connected.Store(false)
	c.loPriActive.Store(false)
	c.drainLoPri()
	c.failAllPending(ErrAIUnavailable)
	if c.onDisconnect != nil {
		c.onDisconnect()
	}
	c.log.Warn("ipc disconnected")
}

func (c *Client) writerLoop(ctx context.Context, conn net.Conn) {
	var fw contracts.FrameWriter
	for {
		var env contracts.IPCEnvelope
		select {
		case env = <-c.hiPriCh:
		default:
			select {
			case env = <-c.hiPriCh:
			case env = <-c.loPriCh:
				if env.Type == contracts.IPCMsgCSIWindow {
					if time.Since(time.UnixMicro(env.TsUs)) > c.cfg.MaxWindowAge {
						c.droppedWindows.Add(1)
						continue
					}
				}
			case <-ctx.Done():
				return
			}
		}
		body, err := json.Marshal(env)
		if err != nil {
			c.protocolErrors.Add(1)
			continue
		}
		_ = conn.SetWriteDeadline(time.Now().Add(c.cfg.WriteTimeout))
		if err := fw.Write(conn, body); err != nil {
			return
		}
	}
}

func (c *Client) readerLoop(ctx context.Context, conn net.Conn) {
	var fr contracts.FrameReader
	for {
		if ctx.Err() != nil {
			return
		}
		raw, err := fr.Read(conn)
		if err != nil {
			if ctx.Err() == nil && !errors.Is(err, net.ErrClosed) {
				if errors.Is(err, contracts.ErrFrameSize) {
					c.protocolErrors.Add(1)
				}
				c.log.Warn("ipc read failed", "err", err)
			}
			return
		}
		c.lastRxUs.Store(time.Now().UnixMicro())
		c.degraded.Store(false)

		var env contracts.IPCEnvelope
		if err := json.Unmarshal(raw, &env); err != nil {
			c.protocolErrors.Add(1)
			c.log.Warn("ipc invalid json frame", "err", err)
			return
		}
		if env.V != contracts.Version {
			c.badVersion.Add(1)
			continue
		}
		if err := env.Validate(); err != nil {
			c.protocolErrors.Add(1)
			return
		}
		c.dispatch(env)
	}
}

func (c *Client) dispatch(env contracts.IPCEnvelope) {
	switch env.Type {
	case contracts.IPCMsgAIInference:
		var p contracts.AIInferencePayload
		if err := json.Unmarshal(env.Payload, &p); err != nil {
			c.protocolErrors.Add(1)
			return
		}
		select {
		case c.inferenceCh <- InferenceMsg{Env: env, Payload: p}:
		default:
			select {
			case <-c.inferenceCh:
			default:
			}
			select {
			case c.inferenceCh <- InferenceMsg{Env: env, Payload: p}:
			default:
			}
		}
	case contracts.IPCMsgCrewAck, contracts.IPCMsgChatCorrelateResp, contracts.IPCMsgCalibrationFeedback:
		if env.ReqID == nil {
			c.staleResp.Add(1)
			return
		}
		c.pendingMu.Lock()
		p, ok := c.pending[*env.ReqID]
		if ok {
			delete(c.pending, *env.ReqID)
		}
		c.pendingMu.Unlock()
		if !ok {
			c.staleResp.Add(1)
			return
		}
		copyEnv := env
		p.replyCh <- pendingReply{env: &copyEnv}
	default:
		c.staleResp.Add(1)
	}
}

func (c *Client) sweepLoop(ctx context.Context) {
	tick := time.NewTicker(c.cfg.SweepInterval)
	defer tick.Stop()
	for {
		select {
		case <-tick.C:
			now := time.Now()
			var expired []pendingReq
			c.pendingMu.Lock()
			for id, p := range c.pending {
				if !p.deadline.IsZero() && now.After(p.deadline) {
					expired = append(expired, p)
					delete(c.pending, id)
				}
			}
			c.pendingMu.Unlock()
			for _, p := range expired {
				p.replyCh <- pendingReply{err: ErrTimeout}
			}
		case <-ctx.Done():
			return
		}
	}
}

func (c *Client) drainLoPri() {
	for {
		select {
		case <-c.loPriCh:
			c.droppedWindows.Add(1)
		default:
			return
		}
	}
}

func (c *Client) failAllPending(err error) {
	c.pendingMu.Lock()
	items := make([]pendingReq, 0, len(c.pending))
	for id, p := range c.pending {
		items = append(items, p)
		delete(c.pending, id)
	}
	c.pendingMu.Unlock()
	for _, p := range items {
		p.replyCh <- pendingReply{err: err}
	}
}
