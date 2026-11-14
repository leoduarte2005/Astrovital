"""Real end-to-end integration test: Edge Space AI worker (:5006) + Go Central (no --mock-ai)."""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_AI_DIR = REPO_ROOT / "edge-ai"


def _find_central_binary(explicit: Optional[Path] = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    env_bin = os.environ.get("CENTRAL_BIN")
    if env_bin:
        candidates.append(Path(env_bin))
    if sys.platform == "win32":
        candidates.extend(
            [
                REPO_ROOT / "build" / "edgespace-central.exe",
                REPO_ROOT / "build" / "edgespace-central",
            ]
        )
    else:
        candidates.extend(
            [
                REPO_ROOT / "build" / "edgespace-central",
                REPO_ROOT / "build" / "edgespace-central.exe",
            ]
        )

    for candidate in candidates:
        p = candidate if candidate.is_absolute() else (REPO_ROOT / candidate)
        if p.is_file():
            return p
    raise FileNotFoundError(f"Go Central binary not found among: {[str(c) for c in candidates]}")


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_tcp_open(host: str, port: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.15)
    raise TimeoutError(f"TCP endpoint {host}:{port} did not open within {timeout_s}s")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: Optional[dict[str, Any]] = None,
    timeout_s: float = 3.0,
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(raw) if raw else {}


def _wait_http_ok(url: str, timeout_s: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout_s
    last_err: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            status, payload = _http_json(url, timeout_s=1.0)
            if status == 200:
                return payload
        except Exception as exc:
            last_err = exc
        time.sleep(0.2)
    raise TimeoutError(f"HTTP {url} did not become ready within {timeout_s}s: {last_err}")


def _win_descendant_pids(root_pid: int) -> list[int]:
    TH32CS_SNAPPROCESS = 0x00000002

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    children_by_parent: dict[int, list[int]] = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    if not snap or snap == INVALID_HANDLE_VALUE:
        return [root_pid]

    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                children_by_parent.setdefault(int(entry.th32ParentProcessID), []).append(int(entry.th32ProcessID))
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)

    pids = [root_pid]
    queue = [root_pid]
    while queue:
        cur = queue.pop(0)
        for child in children_by_parent.get(cur, []):
            if child not in pids:
                pids.append(child)
                queue.append(child)
    return pids


def _get_pid_rss_mb(pid: int) -> Optional[float]:
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL

        # Measure full process tree (Windows venv launcher spawns a child python.exe).
        total_bytes = 0
        any_measured = False
        for target_pid in _win_descendant_pids(pid):
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, target_pid)
            if h_proc:
                try:
                    pmc = _ProcessMemoryCounters()
                    pmc.cb = ctypes.sizeof(_ProcessMemoryCounters)
                    if kernel32.K32GetProcessMemoryInfo(h_proc, ctypes.byref(pmc), pmc.cb):
                        total_bytes += int(pmc.WorkingSetSize)
                        any_measured = True
                finally:
                    kernel32.CloseHandle(h_proc)
        return (total_bytes / (1024.0 * 1024.0)) if any_measured else None

    status_path = Path(f"/proc/{pid}/status")
    if status_path.is_file():
        for line in status_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    return None


class _SimpleWSClient:
    """Minimal RFC 6455 text WebSocket client built on stdlib socket."""

    def __init__(self, host: str, port: int, path: str = "/ws") -> None:
        self.sock = socket.create_connection((host, port), timeout=5.0)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        self.buf = bytearray()
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed: EOF")
            self.buf.extend(chunk)
        header_end = self.buf.index(b"\r\n\r\n") + 4
        header_text = bytes(self.buf[:header_end]).decode("latin-1")
        del self.buf[:header_end]
        status_line = header_text.splitlines()[0]
        if "101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade rejected: {status_line}")

    def send_json(self, obj: dict[str, Any]) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(header + mask + masked)

    def _send_pong(self, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", 0x8A, 0x80 | n)
        else:
            header = struct.pack("!BBH", 0x8A, 0x80 | 126, n)
        self.sock.sendall(header + mask + masked)

    def recv_for(self, duration_s: float) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            remaining = max(0.05, min(0.3, deadline - time.monotonic()))
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(16384)
                if not chunk:
                    break
                self.buf.extend(chunk)
            except socket.timeout:
                pass

            while len(self.buf) >= 2:
                b1, b2 = self.buf[0], self.buf[1]
                length = b2 & 0x7F
                idx = 2
                if length == 126:
                    if len(self.buf) < 4:
                        break
                    (length,) = struct.unpack("!H", self.buf[2:4])
                    idx = 4
                elif length == 127:
                    if len(self.buf) < 10:
                        break
                    (length,) = struct.unpack("!Q", self.buf[2:10])
                    idx = 10
                if len(self.buf) < idx + length:
                    break
                payload = bytes(self.buf[idx : idx + length])
                del self.buf[: idx + length]

                opcode = b1 & 0x0F
                if opcode == 0x8:
                    return frames
                if opcode == 0x9:
                    self._send_pong(payload)
                    continue
                if opcode == 0x1:
                    frames.append(json.loads(payload.decode("utf-8")))
        return frames

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _terminate_process(proc: subprocess.Popen[str], name: str) -> int:
    if proc.poll() is not None:
        return proc.returncode
    proc.terminate()
    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=3)


def run_e2e(
    *,
    ipc_host: str = "127.0.0.1",
    ipc_port: int = 5006,
    central_bin: Optional[Path] = None,
) -> dict[str, Any]:
    central_path = _find_central_binary(central_bin)
    http_port = _free_tcp_port()

    with tempfile.TemporaryDirectory(prefix="edgespace_e2e_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        central_db = tmp_dir / "central_e2e.db"

        worker_env = os.environ.copy()
        worker_env["PYTHONPATH"] = str(EDGE_AI_DIR / "src")
        worker_cmd = [
            sys.executable,
            "-m",
            "edgespace_ai",
            "--listen",
            f"{ipc_host}:{ipc_port}",
            "--models-dir",
            str(EDGE_AI_DIR / "models"),
            "--db",
            str(central_db),
        ]
        worker_proc = subprocess.Popen(
            worker_cmd,
            cwd=str(EDGE_AI_DIR),
            env=worker_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        central_proc: Optional[subprocess.Popen[str]] = None
        ws: Optional[_SimpleWSClient] = None
        try:
            _wait_tcp_open(ipc_host, ipc_port, timeout_s=15.0)

            central_cmd = [
                str(central_path),
                "-mock-cluster=inproc",
                f"-ipc-addr={ipc_host}:{ipc_port}",
                f"-http-addr=127.0.0.1:{http_port}",
                f"-db={central_db}",
                "-migrations",
                str(REPO_ROOT / "database" / "migrations"),
            ]
            central_proc = subprocess.Popen(
                central_cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            base_http = f"http://127.0.0.1:{http_port}"
            metrics_0 = _wait_http_ok(f"{base_http}/api/metrics", timeout_s=15.0)
            status_crew, crew_list = _http_json(f"{base_http}/api/crew")
            assert status_crew == 200 and isinstance(crew_list, list) and len(crew_list) >= 2, (
                f"unexpected /api/crew response: {status_crew} {crew_list}"
            )

            # Open /ws and collect real AI-backed CREW_STATE & TELEMETRY_FRAME
            ws = _SimpleWSClient("127.0.0.1", http_port, "/ws")
            initial_frames = ws.recv_for(2.5)

            crew_states = [f for f in initial_frames if f.get("type") == "CREW_STATE"]
            telemetry_frames = [f for f in initial_frames if f.get("type") == "TELEMETRY_FRAME"]
            assert crew_states, f"no CREW_STATE frames received; got {[f.get('type') for f in initial_frames]}"
            assert any(f.get("payload", {}).get("ai_ready") is True for f in crew_states), (
                f"Central did not report ai_ready=true: {crew_states[-1]}"
            )
            assert telemetry_frames, "no TELEMETRY_FRAME received from Central"
            latest_vitals = telemetry_frames[-1]["payload"]["vitals"]
            assert latest_vitals["posture"] != "unknown"
            assert latest_vitals["confidence_score"] > 0.0
            assert 35.0 <= latest_vitals["heart_rate_bpm"] <= 200.0
            assert 4.0 <= latest_vitals["resp_rate_bpm"] <= 45.0

            # Trigger crew swap via /ws (SET_CREW -> crew_002)
            target_crew = crew_list[1]["crew_id"]
            ws.send_json(
                {
                    "v": 1,
                    "ts_us": time.time_ns() // 1000,
                    "type": "SET_CREW",
                    "crew_id": target_crew,
                    "payload": {"crew_id": target_crew},
                }
            )
            swap_frames = ws.recv_for(1.2)
            swapped_states = [
                f
                for f in swap_frames
                if f.get("type") == "CREW_STATE" and f.get("payload", {}).get("crew_id") == target_crew
            ]
            assert swapped_states and swapped_states[-1]["payload"].get("ai_ready") is True, (
                f"Crew swap to {target_crew} failed or ai_ready!=true: {swap_frames}"
            )

            # Trigger real Edge AI chat correlation via /ws ("dor de cabeca")
            ws.send_json(
                {
                    "v": 1,
                    "ts_us": time.time_ns() // 1000,
                    "type": "CHAT_MSG",
                    "crew_id": target_crew,
                    "payload": {"text": "estou com dor de cabeca"},
                }
            )
            chat_frames = ws.recv_for(2.0)
            chat_replies = [f for f in chat_frames if f.get("type") == "CHAT_REPLY"]
            assert chat_replies, f"no CHAT_REPLY received after CHAT_MSG: {[f.get('type') for f in chat_frames]}"
            reply_payload = chat_replies[-1]["payload"]
            assert reply_payload.get("text"), "empty CHAT_REPLY text"
            assert reply_payload.get("countermeasures"), "missing countermeasures in CHAT_REPLY"
            assert reply_payload.get("source_ids"), "missing source_ids in CHAT_REPLY"

            # Inject node_loss scenario -> degraded topology while AI inference stays alive
            sc_status, sc_resp = _http_json(
                f"{base_http}/api/dev/scenario",
                method="POST",
                body={"scenario": "node_loss"},
            )
            assert sc_status == 200 and sc_resp.get("status") == "ok", f"scenario failed: {sc_resp}"

            # Observe cluster and telemetry after node_loss trigger (inproc mock may keep 20 links unless UDP stops)
            cluster_frames: list[dict[str, Any]] = []
            degraded_telems: list[dict[str, Any]] = []
            degraded_observed = False
            deadline_loss = time.monotonic() + 3.5
            while time.monotonic() < deadline_loss:
                batch = ws.recv_for(1.0)
                for f in batch:
                    if f.get("type") == "CLUSTER_STATUS":
                        cluster_frames.append(f)
                        pl = f.get("payload", {})
                        nodes = pl.get("nodes") or []
                        non_active = any(n.get("state") != "ACTIVE" for n in nodes)
                        if int(pl.get("active_links", 20)) < 20 or non_active:
                            degraded_observed = True
                    elif f.get("type") == "TELEMETRY_FRAME":
                        degraded_telems.append(f)

            last_cluster = cluster_frames[-1]["payload"] if cluster_frames else {}
            assert cluster_frames, "missing CLUSTER_STATUS after node_loss scenario"
            assert last_cluster.get("ai_link") == "online", f"AI IPC link dropped during node_loss: {last_cluster}"
            assert degraded_telems, "telemetry stopped after node_loss scenario"

            _, metrics_after = _http_json(f"{base_http}/api/metrics")
            worker_rss_mb = _get_pid_rss_mb(worker_proc.pid)
            if worker_rss_mb is not None:
                assert worker_rss_mb < 400.0, f"worker RAM exceeds 400 MB budget: {worker_rss_mb:.1f} MB"

            return {
                "status": "PASS",
                "ipc_addr": f"{ipc_host}:{ipc_port}",
                "http_addr": base_http,
                "initial_crew_ai_ready": crew_states[-1]["payload"]["ai_ready"],
                "sample_vitals": latest_vitals,
                "swapped_crew_id": target_crew,
                "chat_reply_sources": reply_payload.get("source_ids"),
                "chat_reply_text": reply_payload.get("text"),
                "node_loss_scenario_ack": sc_resp,
                "cluster_degraded_in_inproc_mock": degraded_observed,
                "node_loss_cluster": last_cluster,
                "worker_rss_mb": round(worker_rss_mb, 2) if worker_rss_mb is not None else None,
                "central_metrics_before": metrics_0,
                "central_metrics_after": metrics_after,
            }
        finally:
            if ws is not None:
                ws.close()
            if central_proc is not None:
                _terminate_process(central_proc, "edgespace-central")
            _terminate_process(worker_proc, "edgespace-ai")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Edge Space AI + Go Central E2E integration test.")
    parser.add_argument("--ipc-host", default="127.0.0.1")
    parser.add_argument("--ipc-port", type=int, default=5006)
    parser.add_argument("--central-bin", type=Path, default=None)
    args = parser.parse_args()

    result = run_e2e(
        ipc_host=args.ipc_host,
        ipc_port=args.ipc_port,
        central_bin=args.central_bin,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
