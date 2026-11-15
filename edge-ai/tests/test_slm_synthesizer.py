"""Unit tests for LocalSLMSynthesizer and IPCHandler SLM integration."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from edgespace_ai.correlation.synthesizer import (
    SLM_SYSTEM_PROMPT,
    LocalSLMSynthesizer,
)
from edgespace_ai.ipc.handlers import IPCHandler
from edgespace_ai.ipc.protocol import (
    ChatCorrelateReqPayload,
    ChatCorrelateRespPayload,
    Escalation,
    IPCMsgType,
    Peripheral,
    PeripheralReading,
    make_envelope,
)


def _sample_correlate_resp() -> ChatCorrelateRespPayload:
    return ChatCorrelateRespPayload(
        text="Hipótese principal: Hipercapnia por CO2 elevado (probabilidade posterior 82%).",
        differentials=[
            "Hipercapnia por CO2 elevado (P=0.82)",
            "SANS / Deslocamento Cefálico de Fluidos (P=0.14)",
        ],
        evidence=[
            "Sintomas detectados: headache, dizziness",
            "Sensor SCD40: 3200.00 ppm",
        ],
        countermeasures=[
            "Verificar e aumentar fluxo de ventilação da cabine imediatamente.",
            "Inspecionar leito de remoção de CO2 (CDRA).",
        ],
        source_ids=["NASA-HRP-CO2-01"],
        escalation=Escalation.CREW,
        disclaimer="Apoio à decisão clínica a bordo; não substitui avaliação do Flight Surgeon.",
        disambiguation_question="A dor de cabeça melhora ao se aproximar da saída de ventilação?",
        actions=["CHECK_VENTILATION"],
    )


class _MockLlama:
    def __init__(self, reply: str = "Resposta sintetizada.", delay_s: float = 0.0, fail: bool = False) -> None:
        self.reply = reply
        self.delay_s = delay_s
        self.fail = fail
        self.last_messages: list[dict[str, str]] | None = None

    def create_chat_completion(self, *, messages: list[dict[str, str]], **_: Any) -> dict[str, Any]:
        self.last_messages = messages
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("simulated llama runtime failure")
        return {"choices": [{"message": {"content": self.reply}}]}


def test_build_messages_injects_causal_sensors_and_memory() -> None:
    synth = LocalSLMSynthesizer(auto_load=False)
    resp = _sample_correlate_resp()
    memory_facts = [
        {"type": "allergy", "content": "Alergia a sulfonamidas"},
        {"type": "history", "content": "Histórico prévio de SANS leve no dia 45"},
        {"type": "contraindication", "content": "Bloqueio de ferro: ferritina > 500 ng/mL"},
    ]
    sensor_snapshot = {
        "crew_id": "astro-01",
        "esp32_s3_peripherals": [
            {"sensor": "SCD40", "value": 3200.0, "unit": "ppm"},
            {"sensor": "MAX30102", "value": 96.0, "unit": "%"},
        ],
    }

    messages = synth.build_messages(resp, memory_facts, sensor_snapshot)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SLM_SYSTEM_PROMPT
    assert "Flight Surgeon" in messages[0]["content"]

    user_msg = messages[1]["content"]
    assert "Hipercapnia por CO2 elevado" in user_msg
    assert "3200.0" in user_msg
    assert "Alergia a sulfonamidas" in user_msg
    assert "SANS" in user_msg
    assert "ferritina > 500" in user_msg
    assert "saída de ventilação" in user_msg
    synth.close()


def test_synthesize_with_mocked_model_and_boot_cache(tmp_path: Path) -> None:
    slm_dir = tmp_path / "slm"
    slm_dir.mkdir(parents=True)
    gguf_file = slm_dir / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    gguf_file.write_bytes(b"GGUF-MOCK")

    mock_llm = _MockLlama(reply="[ASSISTANT] Tripulante, detectamos CO2 em 3200 ppm...")
    factory_calls: list[dict[str, Any]] = []

    def _factory(**kwargs: Any) -> _MockLlama:
        factory_calls.append(kwargs)
        return mock_llm

    synth = LocalSLMSynthesizer(models_dir=tmp_path, n_threads=2, llm_factory=_factory, auto_load=True)
    try:
        assert synth.is_ready is True
        assert factory_calls and factory_calls[0]["n_threads"] == 2
        assert factory_calls[0]["n_ctx"] == 1024
        assert (slm_dir / ".cache").is_dir()

        out = synth.synthesize_response(
            _sample_correlate_resp(),
            ["Alergia a dipirona"],
            {"esp32_s3_peripherals": [{"sensor": "SCD40", "value": 3200, "unit": "ppm"}]},
        )
        assert out == "Tripulante, detectamos CO2 em 3200 ppm..."
        assert mock_llm.last_messages is not None
    finally:
        synth.close()


def test_fallback_on_timeout_error_empty_and_missing_model(tmp_path: Path) -> None:
    resp = _sample_correlate_resp()

    missing = LocalSLMSynthesizer(models_dir=tmp_path, auto_load=True)
    assert missing.is_ready is False
    assert missing.synthesize_response(resp, [], {}) == resp.text
    missing.close()

    slow = LocalSLMSynthesizer(llm=_MockLlama(delay_s=0.35), timeout_s=0.1, auto_load=False)
    assert slow.synthesize_response(resp, [], {}) == resp.text
    slow.close()

    failing = LocalSLMSynthesizer(llm=_MockLlama(fail=True), auto_load=False)
    assert failing.synthesize_response(resp, [], {}) == resp.text
    failing.close()

    empty = LocalSLMSynthesizer(llm=_MockLlama(reply="   "), auto_load=False)
    assert empty.synthesize_response(resp, [], {}) == resp.text
    empty.close()


def test_offline_defaults_timeout_nctx_and_no_auto_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from edgespace_ai.correlation import synthesizer as synth_mod
    from edgespace_ai.utils.config import Settings

    monkeypatch.delenv("EDGESPACE_SLM_TIMEOUT_S", raising=False)
    monkeypatch.delenv("EDGESPACE_SLM_AUTO_DOWNLOAD", raising=False)
    assert Settings().slm_auto_download is False
    assert synth_mod.DEFAULT_N_CTX == 1024
    assert synth_mod.DEFAULT_TIMEOUT_S == 15.0

    synth = LocalSLMSynthesizer(models_dir=tmp_path, auto_load=False)
    try:
        assert synth.n_ctx == 1024
        assert synth.timeout_s == 15.0
        assert synth.auto_download is False
    finally:
        synth.close()

    def _no_network(*_a: Any, **_k: Any) -> Path:
        raise AssertionError("ensure_model must not be called when auto_download=False")

    monkeypatch.setattr(synth_mod, "ensure_model", _no_network)
    offline = LocalSLMSynthesizer(models_dir=tmp_path, auto_download=False, auto_load=True)
    try:
        assert offline.is_ready is False
    finally:
        offline.close()

    monkeypatch.setenv("EDGESPACE_SLM_TIMEOUT_S", "0")
    clamp = LocalSLMSynthesizer(auto_load=False)
    try:
        assert clamp.timeout_s is not None and clamp.timeout_s > 0
    finally:
        clamp.close()


def _apply_real_migrations(db_file: Path) -> None:
    import sqlite3

    mig_dir = Path(__file__).resolve().parents[2] / "database" / "migrations"
    conn = sqlite3.connect(db_file)
    try:
        for sql_path in sorted(mig_dir.glob("*.sql")):
            conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_ipc_handler_chat_correlate_slm_and_disable_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "worker.db"
    _apply_real_migrations(db_file)

    class _FakeSettings:
        models_dir = tmp_path
        db_path = db_file
        ort_threads = 1

    handler_disabled = IPCHandler(settings=_FakeSettings(), disable_slm=True)  # type: ignore[arg-type]
    assert handler_disabled.synthesizer.disabled is True

    monkeypatch.setattr(sys, "argv", ["edgespace-ai", "--disable-slm"])
    handler_cli = IPCHandler(settings=_FakeSettings())  # type: ignore[arg-type]
    assert handler_cli.synthesizer.disabled is True
    monkeypatch.setattr(sys, "argv", ["edgespace-ai"])

    handler_enabled = IPCHandler(settings=_FakeSettings(), disable_slm=False)  # type: ignore[arg-type]
    mock_llm = _MockLlama(reply="Olá tripulante, seu CO2 está elevado em 3400 ppm; aumente a ventilação.")
    handler_enabled.synthesizer._llm = mock_llm

    req = ChatCorrelateReqPayload(
        text="Estou com dor de cabeca e tontura",
        crew_id="crew_001",
        summary_24h="Bloqueio de ferro ativo (ferritina > 500 ng/mL).",
        last_peripherals=[
            PeripheralReading(type=Peripheral.SCD40, value=3400.0, unit="ppm", timestamp_us=1000)
        ],
    )
    env = make_envelope(IPCMsgType.CHAT_CORRELATE_REQ, req, crew_id="crew_001", req_id=7)

    reply_env = asyncio.run(handler_enabled.handle(env))
    assert reply_env is not None
    assert reply_env.type == IPCMsgType.CHAT_CORRELATE_RESP
    assert reply_env.payload["text"].startswith("Olá tripulante, seu CO2 está elevado")
    assert reply_env.payload["countermeasures"]
    assert mock_llm.last_messages is not None
    assert "ferritina > 500" in mock_llm.last_messages[1]["content"]
    handler_enabled.synthesizer.close()


def test_leg_pain_walking_correlates_musculoskeletal_knowledge(tmp_path: Path) -> None:
    import sqlite3
    from edgespace_ai.correlation.correlator import ClinicalCorrelator
    from edgespace_ai.ipc.protocol import CrewProfile

    db_file = tmp_path / "leg.db"
    _apply_real_migrations(db_file)
    with sqlite3.connect(db_file) as c:
        c.execute("DELETE FROM mission_context_events")
        c.execute("DELETE FROM telemetry_daily_rollups")
        c.execute("DELETE FROM nutrition_hydration_logs")
        c.commit()
    correlator = ClinicalCorrelator(db_path=db_file)
    resp = correlator.correlate(
        ChatCorrelateReqPayload(
            text="Minha perna doi quando tento andar",
            crew_id="crew_001",
            profile=CrewProfile(crew_id="crew_001", name="Cmdr. Silva", mission_day=42),
        )
    )
    assert resp.differentials
    assert "Descondicionamento" in resp.differentials[0]
    assert "NASA-FITNESS" in resp.source_ids
    assert resp.countermeasures


