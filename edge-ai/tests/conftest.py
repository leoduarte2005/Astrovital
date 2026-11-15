"""Shared pytest configuration for edge-ai tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_slm_network_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never download the ~1.1 GB GGUF model during unit tests."""
    monkeypatch.setenv("EDGESPACE_SLM_AUTO_DOWNLOAD", "0")
