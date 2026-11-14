"""Asyncio TCP server for IPC v1 (:5006) with HiPri/LoPri priority queues."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..utils.logging import get_logger
from .protocol import (
    BadVersionError,
    FrameSizeError,
    IPCEnvelope,
    IPCMsgType,
    InvalidEnvelopeError,
    now_us,
    parse_envelope_bytes,
    read_frame,
    write_frame,
)

logger = get_logger("edgespace_ai.ipc.server")

HI_PRI_TYPES = frozenset(
    {
        IPCMsgType.SET_ACTIVE_CREW,
        IPCMsgType.CHAT_CORRELATE_REQ,
        IPCMsgType.CALIBRATION_STEP,
    }
)

LO_PRI_TYPES = frozenset(
    {
        IPCMsgType.CSI_WINDOW,
        IPCMsgType.PERIPHERAL_SNAPSHOT,
    }
)

_EPOCH_US_THRESHOLD = 1_000_000_000_000

MessageHandler = Callable[[IPCEnvelope], Awaitable[Optional[IPCEnvelope]]]


@dataclass
class ServerStats:
    """Operational counters exposed for observability and testing."""

    frames_rx: int = 0
    frames_tx: int = 0
    hi_pri_enqueued: int = 0
    lo_pri_enqueued: int = 0
    hi_pri_processed: int = 0
    lo_pri_processed: int = 0
    dropped_windows: int = 0
    dropped_hi_pri: int = 0
    protocol_errors: int = 0
    bad_version: int = 0
    active_connections: int = 0


@dataclass
class _SessionQueues:
    """Per-connection prioritized queues with oldest-drop backpressure on LoPri."""

    hi_pri_cap: int
    lo_pri_cap: int
    hi_pri: deque[IPCEnvelope] = field(default_factory=deque)
    lo_pri: deque[IPCEnvelope] = field(default_factory=deque)
    work_event: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    def enqueue_hi_pri(self, env: IPCEnvelope, stats: ServerStats) -> bool:
        if len(self.hi_pri) >= self.hi_pri_cap:
            stats.dropped_hi_pri += 1
            return False
        self.hi_pri.append(env)
        stats.hi_pri_enqueued += 1
        self.work_event.set()
        return True

    def enqueue_lo_pri(self, env: IPCEnvelope, stats: ServerStats) -> None:
        if len(self.lo_pri) >= self.lo_pri_cap:
            self.lo_pri.popleft()
            stats.dropped_windows += 1
        self.lo_pri.append(env)
        stats.lo_pri_enqueued += 1
        self.work_event.set()

    def close(self) -> None:
        self.closed = True
        self.work_event.set()


class IPCServer:
    """Asyncio TCP server receiving IPC v1 frames and dispatching with HiPri > LoPri."""

    def __init__(
        self,
        handler: MessageHandler,
        *,
        host: str = "127.0.0.1",
        port: int = 5006,
        hi_pri_cap: int = 64,
        lo_pri_cap: int = 8,
        max_window_age_ms: int = 1000,
    ) -> None:
        self._handler = handler
        self._host = host
        self._port = port
        self._hi_pri_cap = hi_pri_cap
        self._lo_pri_cap = lo_pri_cap
        self._max_window_age_us = max_window_age_ms * 1000

        self.stats = ServerStats()
        self._server: Optional[asyncio.AbstractServer] = None
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._stop_event = asyncio.Event()

    @property
    def bound_port(self) -> int:
        """Return actual bound TCP port (useful when started with port=0)."""
        if self._server and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self._port

    async def start(self) -> None:
        """Start listening for incoming TCP connections."""
        if self._server is not None:
            return
        self._stop_event.clear()
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._host,
            port=self._port,
            reuse_address=True,
        )
        logger.info(
            "ipc server listening",
            extra={"host": self._host, "port": self.bound_port},
        )

    async def serve_forever(self) -> None:
        """Start server if needed and wait until stop() is called."""
        await self.start()
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Stop accepting connections and gracefully drain active sessions."""
        self._stop_event.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        tasks = list(self._client_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._client_tasks.clear()
        logger.info("ipc server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        current_task = asyncio.current_task()
        if current_task is not None:
            self._client_tasks.add(current_task)

        self.stats.active_connections += 1
        logger.info("ipc client connected", extra={"peer": str(peer)})

        queues = _SessionQueues(
            hi_pri_cap=self._hi_pri_cap,
            lo_pri_cap=self._lo_pri_cap,
        )
        write_lock = asyncio.Lock()

        worker_task = asyncio.create_task(
            self._worker_loop(queues, writer, write_lock),
            name=f"ipc-worker-{peer}",
        )

        try:
            await self._reader_loop(reader, queues, peer)
        except asyncio.CancelledError:
            raise
        finally:
            queues.close()
            if not worker_task.done():
                try:
                    await asyncio.wait_for(worker_task, timeout=2.0)
                except asyncio.TimeoutError:
                    worker_task.cancel()
                    await asyncio.gather(worker_task, return_exceptions=True)
                except asyncio.CancelledError:
                    worker_task.cancel()
                    raise

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            self.stats.active_connections = max(0, self.stats.active_connections - 1)
            if current_task is not None:
                self._client_tasks.discard(current_task)
            logger.info("ipc client disconnected", extra={"peer": str(peer)})

    async def _reader_loop(
        self,
        reader: asyncio.StreamReader,
        queues: _SessionQueues,
        peer: object,
    ) -> None:
        while not self._stop_event.is_set():
            try:
                raw = await read_frame(reader)
            except FrameSizeError as exc:
                self.stats.protocol_errors += 1
                logger.warning("ipc frame size error", extra={"peer": str(peer), "err": str(exc)})
                return
            except asyncio.IncompleteReadError as exc:
                self.stats.protocol_errors += 1
                logger.warning("ipc truncated frame", extra={"peer": str(peer), "err": str(exc)})
                return
            except ConnectionResetError:
                return

            if raw is None:
                return

            self.stats.frames_rx += 1

            try:
                env = parse_envelope_bytes(raw)
            except BadVersionError as exc:
                self.stats.bad_version += 1
                logger.warning("ipc bad version", extra={"peer": str(peer), "err": str(exc)})
                continue
            except InvalidEnvelopeError as exc:
                self.stats.protocol_errors += 1
                logger.warning("ipc invalid envelope", extra={"peer": str(peer), "err": str(exc)})
                return

            if env.type in HI_PRI_TYPES or env.req_id is not None:
                if not queues.enqueue_hi_pri(env, self.stats):
                    logger.warning(
                        "ipc hi_pri queue full; dropping request",
                        extra={"msg_type": env.type.value, "req_id": env.req_id},
                    )
            elif env.type in LO_PRI_TYPES:
                prev_dropped = self.stats.dropped_windows
                queues.enqueue_lo_pri(env, self.stats)
                if self.stats.dropped_windows > prev_dropped:
                    logger.debug(
                        "ipc lo_pri backpressure dropped oldest window",
                        extra={"dropped_windows": self.stats.dropped_windows},
                    )
            else:
                logger.debug(
                    "ipc ignored unsolicited message type",
                    extra={"msg_type": env.type.value},
                )

    async def _worker_loop(
        self,
        queues: _SessionQueues,
        writer: asyncio.StreamWriter,
        write_lock: asyncio.Lock,
    ) -> None:
        while True:
            is_hi_pri = False
            if queues.hi_pri:
                env = queues.hi_pri.popleft()
                is_hi_pri = True
            elif queues.lo_pri:
                env = queues.lo_pri.popleft()
            elif queues.closed or self._stop_event.is_set():
                return
            else:
                queues.work_event.clear()
                if queues.hi_pri or queues.lo_pri or queues.closed or self._stop_event.is_set():
                    continue
                await queues.work_event.wait()
                continue

            if not is_hi_pri and env.type == IPCMsgType.CSI_WINDOW and self._is_stale_window(env):
                self.stats.dropped_windows += 1
                logger.debug(
                    "ipc dropped stale csi_window",
                    extra={"ts_us": env.ts_us, "dropped_windows": self.stats.dropped_windows},
                )
                continue

            if is_hi_pri:
                self.stats.hi_pri_processed += 1
            else:
                self.stats.lo_pri_processed += 1

            try:
                resp = await self._handler(env)
            except Exception as exc:
                logger.exception(
                    "ipc handler failed",
                    extra={"msg_type": env.type.value, "req_id": env.req_id, "err": str(exc)},
                )
                continue

            if resp is None:
                continue

            if env.req_id is not None and resp.req_id is None:
                resp = resp.model_copy(update={"req_id": env.req_id})

            try:
                body = resp.to_json_bytes()
                async with write_lock:
                    await write_frame(writer, body)
                self.stats.frames_tx += 1
            except (ConnectionError, OSError) as exc:
                logger.warning("ipc write failed", extra={"err": str(exc)})
                return
            except FrameSizeError as exc:
                self.stats.protocol_errors += 1
                logger.error("ipc response exceeded max frame size", extra={"err": str(exc)})

    def _is_stale_window(self, env: IPCEnvelope) -> bool:
        if self._max_window_age_us <= 0:
            return False
        if env.ts_us < _EPOCH_US_THRESHOLD:
            return False
        return (now_us() - env.ts_us) > self._max_window_age_us
