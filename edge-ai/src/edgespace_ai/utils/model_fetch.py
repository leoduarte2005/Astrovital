"""First-run downloader for the local SLM GGUF model (stdlib only).

The GGUF file (~1.1 GB) exceeds GitHub's 100 MB limit, so it is not versioned.
On first run it is fetched from the official Hugging Face repository into
``edge-ai/models/slm/`` with resume support, SHA-256 verification and an
atomic rename, so a partially downloaded file is never loaded.

CLI::

    python -m edgespace_ai.utils.model_fetch [--models-dir DIR] [--force] [--check]

Environment overrides:
    EDGESPACE_SLM_URL            alternative download URL (mirror)
    EDGESPACE_SLM_SHA256         expected SHA-256 for the alternative URL ("" skips check)
    EDGESPACE_SLM_AUTO_DOWNLOAD  "0"/"false" disables automatic download
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from .logging import get_logger

logger = get_logger("edgespace_ai.utils.model_fetch")

DEFAULT_MODEL_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/" + DEFAULT_MODEL_FILENAME
)
DEFAULT_MODEL_SIZE = 1_117_320_736
DEFAULT_MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"

_CHUNK = 1024 * 1024
_READ_TIMEOUT_S = 60.0
_MAX_ATTEMPTS = 5
_FALSE_VALUES = {"0", "false", "no", "off"}

ProgressCallback = Callable[[int, Optional[int]], None]


@dataclass(frozen=True)
class ModelSpec:
    """Remote GGUF artifact description."""

    filename: str
    url: str
    size: Optional[int]
    sha256: Optional[str]


def default_model_spec() -> ModelSpec:
    """Return the default spec, honoring ``EDGESPACE_SLM_URL``/``EDGESPACE_SLM_SHA256``."""
    url = os.environ.get("EDGESPACE_SLM_URL", "").strip()
    if not url:
        return ModelSpec(DEFAULT_MODEL_FILENAME, DEFAULT_MODEL_URL, DEFAULT_MODEL_SIZE, DEFAULT_MODEL_SHA256)
    sha = os.environ.get("EDGESPACE_SLM_SHA256", "").strip().lower() or None
    filename = url.rsplit("/", 1)[-1].split("?", 1)[0] or DEFAULT_MODEL_FILENAME
    if not filename.endswith(".gguf"):
        filename = DEFAULT_MODEL_FILENAME
    return ModelSpec(filename, url, None, sha)


def auto_download_enabled() -> bool:
    """Whether automatic download is allowed (``EDGESPACE_SLM_AUTO_DOWNLOAD``, default on)."""
    raw = os.environ.get("EDGESPACE_SLM_AUTO_DOWNLOAD", "").strip().lower()
    return raw not in _FALSE_VALUES


def default_slm_dir() -> Path:
    """``edge-ai/models/slm`` resolved from the package location."""
    return Path(__file__).resolve().parents[3] / "models" / "slm"


def find_existing_gguf(slm_dir: Path) -> Optional[Path]:
    """Return any complete ``*.gguf`` already present in ``slm_dir``."""
    if not slm_dir.is_dir():
        return None
    for path in sorted(slm_dir.glob("*.gguf")):
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _console_progress(stream=None) -> ProgressCallback:
    out = stream or sys.stderr
    is_tty = bool(getattr(out, "isatty", lambda: False)())
    state = {"last_pct": -1, "last_t": 0.0, "t0": time.monotonic(), "b0": None}

    def _cb(done: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if state["b0"] is None:
            state["b0"] = done
        elapsed = max(now - state["t0"], 1e-6)
        speed = (done - state["b0"]) / elapsed / (1024 * 1024)
        if total:
            pct = int(done * 100 / total)
            finished = done >= total
            if not finished and pct == state["last_pct"]:
                return
            if not is_tty and not finished and pct % 5 != 0:
                return
            state["last_pct"] = pct
            line = (
                f"[slm] baixando modelo: {pct:3d}% "
                f"({done / 1048576:,.0f}/{total / 1048576:,.0f} MB, {speed:.1f} MB/s)"
            )
        else:
            if now - state["last_t"] < 2.0:
                return
            line = f"[slm] baixando modelo: {done / 1048576:,.0f} MB ({speed:.1f} MB/s)"
        state["last_t"] = now
        out.write(("\r" + line) if is_tty else (line + "\n"))
        if is_tty and total and done >= total:
            out.write("\n")
        out.flush()

    return _cb


class _ChecksumError(RuntimeError):
    pass


class _IncompleteError(RuntimeError):
    pass


def download_model(
    slm_dir: Optional[Path | str] = None,
    *,
    spec: Optional[ModelSpec] = None,
    force: bool = False,
    progress: Optional[ProgressCallback] = None,
    max_attempts: int = _MAX_ATTEMPTS,
    retry_wait_s: float = 2.0,
) -> Path:
    """Ensure the GGUF model exists in ``slm_dir``; download it if missing.

    Resumes ``<file>.part`` across attempts/runs, verifies size and SHA-256, then
    atomically renames to the final name. Raises ``RuntimeError`` on failure.
    """
    target_dir = Path(slm_dir) if slm_dir is not None else default_slm_dir()
    spec = spec or default_model_spec()
    final_path = target_dir / spec.filename
    part_path = target_dir / (spec.filename + ".part")

    if final_path.is_file() and not force:
        return final_path

    target_dir.mkdir(parents=True, exist_ok=True)
    if force:
        final_path.unlink(missing_ok=True)
        part_path.unlink(missing_ok=True)

    if spec.size:
        have = part_path.stat().st_size if part_path.exists() else 0
        free = shutil.disk_usage(target_dir).free
        if free < (spec.size - have) + 64 * 1024 * 1024:
            raise RuntimeError(
                f"espaco em disco insuficiente em {target_dir}: "
                f"livre {free / 1048576:.0f} MB, necessario ~{(spec.size - have) / 1048576:.0f} MB"
            )

    logger.info("downloading SLM GGUF model", extra={"url": spec.url, "dest": str(final_path)})
    last_err: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            _download_once(spec, part_path, progress)
            last_err = None
            break
        except (urllib.error.URLError, OSError, _IncompleteError) as exc:
            last_err = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
                break  # permanent error: retrying will not help
            wait_s = min(30.0, retry_wait_s * (2 ** (attempt - 1)))
            logger.warning(
                "SLM download attempt failed; retrying",
                extra={"attempt": attempt, "max_attempts": max_attempts, "err": str(exc), "retry_in_s": wait_s},
            )
            if attempt < max_attempts:
                time.sleep(wait_s)
    if last_err is not None:
        raise RuntimeError(f"falha ao baixar {spec.url}: {last_err}") from last_err

    if spec.sha256:
        actual = sha256_file(part_path)
        if actual.lower() != spec.sha256.lower():
            part_path.unlink(missing_ok=True)
            raise _ChecksumError(
                f"SHA-256 divergente para {spec.filename}: esperado {spec.sha256}, obtido {actual}"
            )

    os.replace(part_path, final_path)
    logger.info("SLM GGUF model ready", extra={"path": str(final_path), "bytes": final_path.stat().st_size})
    return final_path



def _download_once(spec: ModelSpec, part_path: Path, progress: Optional[ProgressCallback]) -> None:
    offset = part_path.stat().st_size if part_path.exists() else 0
    if spec.size and offset > spec.size:
        part_path.unlink()
        offset = 0
    if spec.size and offset == spec.size:
        return

    headers = {"User-Agent": "edgespace-ai/0.1 (+model_fetch)"}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(spec.url, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=_READ_TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset > 0:
            # Range not satisfiable: stale/corrupt .part; restart from zero next attempt.
            part_path.unlink(missing_ok=True)
            raise _IncompleteError("range nao satisfeito; reiniciando download") from exc
        raise

    with resp:
        status = getattr(resp, "status", 200)
        if offset > 0 and status != 206:
            offset = 0  # server ignored Range: rewrite from the start
        length_hdr = resp.headers.get("Content-Length")
        if spec.size:
            total: Optional[int] = spec.size
        elif length_hdr and length_hdr.isdigit():
            total = offset + int(length_hdr)
        else:
            total = None

        done = offset
        with part_path.open("ab" if offset > 0 else "wb") as fh:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)

    if total is not None and done != total:
        raise _IncompleteError(f"download incompleto: {done}/{total} bytes")


def ensure_model(
    slm_dir: Optional[Path | str] = None,
    *,
    progress: Optional[ProgressCallback] = None,
) -> Optional[Path]:
    """Return an existing GGUF or download the default one; ``None`` on failure/disabled."""
    target_dir = Path(slm_dir) if slm_dir is not None else default_slm_dir()
    existing = find_existing_gguf(target_dir)
    if existing is not None:
        return existing
    if not auto_download_enabled():
        logger.info("SLM auto-download disabled (EDGESPACE_SLM_AUTO_DOWNLOAD=0)")
        return None
    try:
        return download_model(target_dir, progress=progress or _console_progress())
    except Exception as exc:
        logger.warning(
            "SLM model download failed; deterministic fallback stays active",
            extra={"err": str(exc)},
        )
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Baixa o modelo GGUF do SLM local (Qwen2.5-1.5B Q4_K_M).")
    parser.add_argument("--models-dir", type=Path, default=None, help="Diretorio de modelos (usa <dir>/slm)")
    parser.add_argument("--force", action="store_true", help="Rebaixa mesmo se o arquivo ja existir")
    parser.add_argument("--check", action="store_true", help="Somente verifica; exit 1 se ausente")
    args = parser.parse_args(argv)

    slm_dir = (args.models_dir / "slm") if args.models_dir is not None else default_slm_dir()
    existing = find_existing_gguf(slm_dir)
    if args.check:
        print(f"[slm] OK: {existing}" if existing else f"[slm] ausente em {slm_dir}", flush=True)
        return 0 if existing else 1
    if existing is not None and not args.force:
        print(f"[slm] modelo ja presente: {existing}", flush=True)
        return 0

    spec = default_model_spec()
    size_txt = f" (~{spec.size / 1048576:,.0f} MB)" if spec.size else ""
    print(f"[slm] baixando {spec.filename}{size_txt}", flush=True)
    print(f"[slm] origem: {spec.url}", flush=True)
    print(f"[slm] destino: {slm_dir}", flush=True)
    try:
        path = download_model(slm_dir, spec=spec, force=args.force, progress=_console_progress())
    except Exception as exc:
        print(f"[slm] ERRO: {exc}", file=sys.stderr, flush=True)
        return 1
    print(f"[slm] modelo pronto: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

