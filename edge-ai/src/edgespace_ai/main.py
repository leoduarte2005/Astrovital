"""Entrypoint for the Edge Space AI IPC worker."""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import Optional, Sequence

from .ipc.handlers import IPCHandler
from .ipc.server import IPCServer
from .utils.config import Settings, get_settings
from .utils.logging import configure_logging, get_logger

logger = get_logger("edgespace_ai.main")


async def run_server(settings: Optional[Settings] = None) -> None:
    """Start the IPC TCP server and wait until SIGINT/SIGTERM."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    handler = IPCHandler(settings=cfg)
    server = IPCServer(
        handler.handle,
        host=cfg.ai_host,
        port=cfg.ai_port,
        hi_pri_cap=cfg.ipc_hi_pri_cap,
        lo_pri_cap=cfg.ipc_lo_pri_cap,
        max_window_age_ms=cfg.ipc_max_window_age_ms,
    )

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _request_shutdown(sig_name: str) -> None:
        if not shutdown_event.is_set():
            logger.info("shutdown signal received", extra={"signal": sig_name})
            shutdown_event.set()

    installed_loop_signals: list[signal.Signals] = []
    previous_handlers: dict[signal.Signals, object] = {}

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig.name)
            installed_loop_signals.append(sig)
        except (NotImplementedError, RuntimeError):
            try:
                prev = signal.getsignal(sig)
                previous_handlers[sig] = prev

                def _sync_handler(signum: int, _frame: object, name: str = sig.name) -> None:
                    loop.call_soon_threadsafe(_request_shutdown, name)

                signal.signal(sig, _sync_handler)
            except (ValueError, OSError):
                pass

    await server.start()
    logger.info(
        "edgespace-ai started",
        extra={
            "host": cfg.ai_host,
            "port": server.bound_port,
            "models_dir": str(cfg.models_dir),
            "db_path": str(cfg.db_path),
            "ort_threads": cfg.ort_threads,
        },
    )

    try:
        await shutdown_event.wait()
    finally:
        await server.stop()
        for sig in installed_loop_signals:
            try:
                loop.remove_signal_handler(sig)
            except Exception:
                pass
        for sig, prev in previous_handlers.items():
            try:
                signal.signal(sig, prev)  # type: ignore[arg-type]
            except Exception:
                pass


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Edge Space AI IPC worker")
    parser.add_argument(
        "--listen",
        default=None,
        help="TCP listen address as HOST:PORT or :PORT (overrides EDGESPACE_AI_HOST/PORT)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path (overrides EDGESPACE_DB_PATH)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="Directory containing ONNX models (overrides EDGESPACE_MODELS_DIR)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """CLI entrypoint."""
    args = parse_args(argv)
    cfg = get_settings()
    updates: dict[str, object] = {}

    if args.listen:
        host_part, _, port_part = args.listen.rpartition(":")
        if port_part:
            updates["ai_port"] = int(port_part)
        if host_part:
            updates["ai_host"] = host_part
    if args.db is not None:
        updates["db_path"] = args.db
    if args.models_dir is not None:
        updates["models_dir"] = args.models_dir

    if updates:
        cfg = cfg.model_copy(update=updates)

    try:
        asyncio.run(run_server(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
