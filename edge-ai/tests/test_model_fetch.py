"""Tests for first-run SLM GGUF downloader (local HTTP server, no internet)."""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path
from typing import Iterator

import pytest

from edgespace_ai.utils import model_fetch
from edgespace_ai.utils.model_fetch import ModelSpec, download_model, ensure_model, find_existing_gguf

PAYLOAD = (b"GGUF" + bytes(range(256))) * 4096  # ~1 MB


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    payload = PAYLOAD
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _RangeHandler.hits.append(self.headers.get("Range") or "")
        if self.path.endswith("/missing.gguf"):
            self.send_error(404)
            return
        data = self.payload
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-", 1)[0])
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture()
def server_url() -> Iterator[str]:
    _RangeHandler.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _spec(url: str, sha: str | None = None) -> ModelSpec:
    return ModelSpec(
        filename="model.gguf",
        url=f"{url}/model.gguf",
        size=len(PAYLOAD),
        sha256=sha if sha is not None else hashlib.sha256(PAYLOAD).hexdigest(),
    )


def test_download_fresh_verifies_sha_and_renames_atomically(tmp_path: Path, server_url: str) -> None:
    seen: list[int] = []
    path = download_model(tmp_path / "slm", spec=_spec(server_url), progress=lambda d, _t: seen.append(d))
    assert path == tmp_path / "slm" / "model.gguf"
    assert path.read_bytes() == PAYLOAD
    assert not (tmp_path / "slm" / "model.gguf.part").exists()
    assert seen and seen[-1] == len(PAYLOAD)

    # Second call is a no-op (no new HTTP request)
    hits_before = len(_RangeHandler.hits)
    assert download_model(tmp_path / "slm", spec=_spec(server_url)) == path
    assert len(_RangeHandler.hits) == hits_before


def test_download_resumes_partial_file_with_range(tmp_path: Path, server_url: str) -> None:
    slm = tmp_path / "slm"
    slm.mkdir()
    half = len(PAYLOAD) // 2
    (slm / "model.gguf.part").write_bytes(PAYLOAD[:half])

    path = download_model(slm, spec=_spec(server_url))
    assert path.read_bytes() == PAYLOAD
    assert _RangeHandler.hits[-1] == f"bytes={half}-"


def test_download_checksum_mismatch_discards_part(tmp_path: Path, server_url: str) -> None:
    with pytest.raises(RuntimeError, match="SHA-256"):
        download_model(tmp_path / "slm", spec=_spec(server_url, sha="0" * 64))
    assert not (tmp_path / "slm" / "model.gguf").exists()
    assert not (tmp_path / "slm" / "model.gguf.part").exists()


def test_download_404_fails_fast_without_retries(tmp_path: Path, server_url: str) -> None:
    spec = ModelSpec("missing.gguf", f"{server_url}/missing.gguf", None, None)
    with pytest.raises(RuntimeError, match="falha ao baixar"):
        download_model(tmp_path / "slm", spec=spec, retry_wait_s=0.01)
    assert len(_RangeHandler.hits) == 1


def test_ensure_model_respects_existing_and_disable_flag(
    tmp_path: Path, server_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    slm = tmp_path / "slm"
    # Disabled via env (conftest default) -> no download
    assert ensure_model(slm) is None
    assert find_existing_gguf(slm) is None

    # Enabled with mirror URL -> downloads into slm dir
    monkeypatch.setenv("EDGESPACE_SLM_AUTO_DOWNLOAD", "1")
    monkeypatch.setenv("EDGESPACE_SLM_URL", f"{server_url}/model.gguf")
    monkeypatch.setenv("EDGESPACE_SLM_SHA256", hashlib.sha256(PAYLOAD).hexdigest())
    got = ensure_model(slm, progress=lambda *_: None)
    assert got == slm / "model.gguf" and got.read_bytes() == PAYLOAD

    # Existing GGUF is reused without hitting the network
    hits_before = len(_RangeHandler.hits)
    assert ensure_model(slm) == got
    assert len(_RangeHandler.hits) == hits_before


def test_cli_check_and_download(tmp_path: Path, server_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGESPACE_SLM_URL", f"{server_url}/model.gguf")
    monkeypatch.setenv("EDGESPACE_SLM_SHA256", hashlib.sha256(PAYLOAD).hexdigest())
    assert model_fetch.main(["--models-dir", str(tmp_path), "--check"]) == 1
    assert model_fetch.main(["--models-dir", str(tmp_path)]) == 0
    assert (tmp_path / "slm" / "model.gguf").read_bytes() == PAYLOAD
    assert model_fetch.main(["--models-dir", str(tmp_path), "--check"]) == 0


def test_default_spec_points_to_official_qwen_q4_k_m(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDGESPACE_SLM_URL", raising=False)
    spec = model_fetch.default_model_spec()
    assert spec.filename == "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    assert spec.url.startswith("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/")
    assert spec.size == 1_117_320_736
    assert spec.sha256 and len(spec.sha256) == 64
