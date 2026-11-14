"""Unit and integration tests for Edge Space AI (IPC, DSP, ONNX inference, adaptation)."""

from __future__ import annotations

import asyncio
import ctypes
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from edgespace_ai.adaptation import BaselineRegistry, CalibrationEngine
from edgespace_ai.correlation import ClinicalCorrelator, ClinicalStore, SymptomExtractor
from edgespace_ai.dsp import (
    FEATURE_DIM,
    CSIProcessor,
    FeatureExtractor,
    LinkFusion,
    WindowBuffer,
)
from edgespace_ai.inference import (
    RF_ONLY_MAX_CONFIDENCE,
    AnomalyScorer,
    ExerciseCadenceEstimator,
    PostureClassifier,
    SessionManager,
    VitalsRegressor,
)
from edgespace_ai.ipc import (
    AIInferencePayload,
    CSILink,
    CSIWindowPayload,
    CalibrationStepPayload,
    ChatCorrelateReqPayload,
    CrewProfile,
    Escalation,
    IPCHandler,
    IPCMsgType,
    IPCServer,
    IQSample,
    MissionMode,
    Peripheral,
    PeripheralReading,
    PeripheralSnapshotPayload,
    SetActiveCrewPayload,
    Threshold,
    encode_frame,
    make_envelope,
    now_us,
    parse_envelope_bytes,
    read_frame,
    write_frame,
)
from edgespace_ai.utils.config import Settings


def _make_synthetic_iq(n_cycles: int = 5, n_sub: int = 56, freq_hz: float = 0.25, seed: int = 0) -> list[IQSample]:
    rng = np.random.default_rng(seed)
    t = np.arange(n_cycles, dtype=np.float64) / 10.0
    sub_idx = np.arange(n_sub, dtype=np.float64)
    samples: list[IQSample] = []
    for ti in t:
        amp = 1.2 + 0.15 * np.sin(2.0 * np.pi * freq_hz * ti) + 0.03 * np.sin(2.0 * np.pi * 1.15 * ti)
        sto_phase = 0.08 * sub_idx + 0.3  # linear STO + CFO offset
        noise = rng.normal(0.0, 0.01, size=n_sub)
        z = (amp + noise) * np.exp(1j * sto_phase)
        for val in z:
            samples.append(IQSample(real=float(val.real), imag=float(val.imag)))
    return samples


def _make_csi_window(seq: int, n_links: int = 20, mode: MissionMode = MissionMode.MODE_REST_VITALS) -> CSIWindowPayload:
    links: list[CSILink] = []
    count = 0
    for tx in range(5):
        for rx in range(5):
            if tx == rx:
                continue
            links.append(
                CSILink(
                    tx_node_id=tx,
                    rx_node_id=rx,
                    iq_samples=_make_synthetic_iq(seed=seq + count),
                    rssi_dbm=-48 - (count % 10),
                    noise_floor=-92.0,
                )
            )
            count += 1
            if count >= n_links:
                break
        if count >= n_links:
            break
    return CSIWindowPayload(
        cycle_seq_first=seq,
        active_link_mask=(1 << n_links) - 1,
        mode=mode,
        links=links,
    )


def test_ipc_envelope_serialization_and_framing() -> None:
    env = make_envelope(
        IPCMsgType.SET_ACTIVE_CREW,
        SetActiveCrewPayload(crew_id="crew_001"),
        crew_id="",
        req_id=42,
    )
    raw = env.to_json_bytes()
    decoded = json.loads(raw)
    assert decoded["v"] == 1
    assert decoded["crew_id"] is None  # Go expects "crew_id":null when empty
    assert decoded["req_id"] == 42

    frame = encode_frame(raw)
    assert int.from_bytes(frame[:4], "big") == len(raw)
    parsed = parse_envelope_bytes(raw)
    assert parsed.req_id == 42


def test_dsp_sanitization_fusion_and_64_features() -> None:
    proc = CSIProcessor()
    iq = _make_synthetic_iq(n_cycles=10, n_sub=56)
    # Inject a spike outlier on cycle 4
    iq[4 * 56] = IQSample(real=50.0, imag=-50.0)
    processed = proc.process_iq(iq, rssi_dbm=-45, noise_floor=-92.0)
    assert processed.amplitude.shape == (10, 56)
    assert processed.phase.shape == (10, 56)
    # Hampel should suppress the 50+50j outlier
    assert processed.amplitude[4, 0] < 10.0

    # Test N+1 degradation with 20, 12, and 6 active links
    for n_links in (20, 12, 6):
        buf = WindowBuffer(maxlen=16)
        base_ts = now_us()
        for idx, seq in enumerate([10, 5, 15, 20]):  # intentionally out-of-order push
            buf.push(_make_csi_window(seq=seq, n_links=n_links), ts_us=base_ts + idx * 500_000)

        ordered = buf.latest(10)
        assert [w.cycle_seq_first for w in ordered] == [5, 10, 15, 20]

        fused = LinkFusion().fuse_windows(ordered, proc, sample_rate_hz=10.0)
        assert fused is not None
        assert fused.active_links_count == n_links
        assert abs(sum(fused.link_weights.values()) - 1.0) < 1e-6

        extracted = FeatureExtractor().extract(fused)
        assert extracted.vector.shape == (FEATURE_DIM,)
        assert extracted.vector.dtype == np.float32
        assert np.all(np.isfinite(extracted.vector))


def test_clinical_rule_p4_confidence_cap() -> None:
    sm = SessionManager(models_dir=Path("./nonexistent_models"))
    vitals = VitalsRegressor(sm)

    proc = CSIProcessor()
    buf = WindowBuffer()
    ts = now_us()
    for i in range(4):
        buf.push(_make_csi_window(seq=i * 5, n_links=12), ts_us=ts + i * 500_000)
    fused = LinkFusion().fuse_windows(buf.latest(4), proc)
    assert fused is not None
    extracted = FeatureExtractor().extract(fused)

    # Without MAX30102 -> confidence MUST be <= 0.65
    pred_rf_only = vitals.predict(
        extracted,
        degradation_ratio=1.0,
        mean_snr_db=30.0,
        peripherals=[],
        reference_ts_us=ts,
    )
    assert not pred_rf_only.has_max30102_corroboration
    assert pred_rf_only.confidence <= RF_ONLY_MAX_CONFIDENCE

    # With stale MAX30102 (> 10s old) -> confidence MUST still be <= 0.65
    stale = [PeripheralReading(type=Peripheral.MAX30102, value=98.0, unit="%", timestamp_us=ts - 20_000_000)]
    pred_stale = vitals.predict(
        extracted,
        degradation_ratio=1.0,
        mean_snr_db=30.0,
        peripherals=stale,
        reference_ts_us=ts,
    )
    assert not pred_stale.has_max30102_corroboration
    assert pred_stale.confidence <= RF_ONLY_MAX_CONFIDENCE

    # With recent MAX30102 -> corroboration enabled
    recent = [PeripheralReading(type=Peripheral.MAX30102, value=98.5, unit="%", timestamp_us=ts - 500_000)]
    pred_corr = vitals.predict(
        extracted,
        degradation_ratio=1.0,
        mean_snr_db=30.0,
        peripherals=recent,
        reference_ts_us=ts,
    )
    assert pred_corr.has_max30102_corroboration


def test_adaptation_registry_and_calibration(tmp_path: Path) -> None:
    registry = BaselineRegistry(models_dir=tmp_path)
    cal = CalibrationEngine(registry, target_steps=2)

    t0 = time.perf_counter()
    _, found = registry.set_active_crew("astronaut_01")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert not found
    assert elapsed_ms < 300.0

    vec = np.ones(FEATURE_DIM, dtype=np.float32) * 2.5
    res1 = cal.process_step(
        crew_id="astronaut_01",
        step_id="step_1",
        action="rest_supine",
        latest_features=vec,
    )
    assert res1.progress == 50
    res2 = cal.process_step(
        crew_id="astronaut_01",
        step_id="step_2",
        action="rest_supine",
        latest_features=vec * 1.1,
    )
    assert res2.progress == 100

    saved_file = tmp_path / "profiles" / "baseline_astronaut_01.json"
    assert saved_file.is_file()

    # Switching back should find persisted baseline
    registry2 = BaselineRegistry(models_dir=tmp_path)
    _, found2 = registry2.set_active_crew("astronaut_01")
    assert found2


def _get_process_rss_mb() -> float:
    """Measure current process resident working-set memory in MiB cleanly."""
    if sys.platform == "win32":
        from ctypes import wintypes

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
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        handle = kernel32.GetCurrentProcess()
        if kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024.0 * 1024.0)

    proc_status = Path("/proc/self/status")
    if proc_status.is_file():
        for line in proc_status.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                kb = float(line.split()[1])
                return kb / 1024.0

    import resource

    usage = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return (usage / (1024.0 * 1024.0)) if sys.platform == "darwin" else (usage / 1024.0)


def test_onnx_models_arm64_budget_and_warmup() -> None:
    models_dir = Path(__file__).resolve().parent.parent / "models"
    expected_models = (
        "posture_cls.onnx",
        "exercise_cadence.onnx",
        "vitals_reg.onnx",
        "baseline_ae_default.onnx",
        "isolation_forest.onnx",
    )
    for filename in expected_models:
        model_path = models_dir / filename
        assert model_path.is_file() and model_path.stat().st_size > 0, f"missing or empty ONNX model: {model_path}"

    sm = SessionManager(models_dir=models_dir, intra_op_num_threads=2, inter_op_num_threads=1)
    assert sm.intra_op_num_threads == 2
    assert sm.inter_op_num_threads == 1
    loaded = sm.load_all()
    assert len(loaded) == 5
    assert all(s.warmed_up for s in loaded.values())

    proc = CSIProcessor()
    posture_cls = PostureClassifier(sm)
    cadence_est = ExerciseCadenceEstimator(sm)
    vitals_reg = VitalsRegressor(sm)
    anomaly_scorer = AnomalyScorer(sm)

    # Verify N+1 link resilience end-to-end (20 FULL_MESH, 12 DEGRADED_N1, 6 DEGRADED_MIN)
    latencies_ms: list[float] = []
    ts = now_us()
    for n_links in (20, 12, 6):
        buf = WindowBuffer()
        for i in range(4):
            buf.push(_make_csi_window(seq=i * 5, n_links=n_links), ts_us=ts + i * 500_000)
        fused = LinkFusion().fuse_windows(buf.latest(4), proc)
        assert fused is not None
        extracted = FeatureExtractor().extract(fused)
        assert np.all(np.isfinite(extracted.vector))

        # Benchmark pure ONNX inference latency over multiple iterations after warm-up
        iters = 10 if n_links == 20 else 3
        for _ in range(iters):
            t0 = time.perf_counter()
            posture = posture_cls.predict(extracted)
            cadence = cadence_est.predict(extracted)
            vitals = vitals_reg.predict(extracted, peripherals=[], reference_ts_us=ts)
            anomaly = anomaly_scorer.score(extracted)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

            assert posture.posture in ("supine", "sitting", "standing", "exercising", "prone")
            assert np.isfinite(cadence.cadence_hz) and cadence.cadence_hz >= 0.0
            assert np.isfinite(vitals.heart_rate_bpm) and np.isfinite(vitals.respiration_hz) and np.isfinite(vitals.hrv_ms)
            assert vitals.confidence <= RF_ONLY_MAX_CONFIDENCE
            assert np.isfinite(anomaly.anomaly_score) and 0.0 <= anomaly.anomaly_score <= 1.0

    avg_inference_ms = sum(latencies_ms) / len(latencies_ms)
    rss_mb = _get_process_rss_mb()
    print(f"[ARM64 budget] avg_onnx_inference_ms={avg_inference_ms:.2f}, max_ms={max(latencies_ms):.2f}, worker_rss_mb={rss_mb:.2f}")
    assert avg_inference_ms < 50.0, f"avg ONNX inference latency too high: {avg_inference_ms:.2f} ms"
    assert rss_mb < 400.0, f"worker RSS memory exceeds ARM64 budget: {rss_mb:.1f} MB"


def test_ipc_server_hipri_priority_and_req_id_correlation(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(ai_host="127.0.0.1", ai_port=0, models_dir=tmp_path)
        handler = IPCHandler(settings=settings)
        server = IPCServer(handler.handle, host="127.0.0.1", port=0, lo_pri_cap=4)
        await server.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)

            # Send SET_ACTIVE_CREW with req_id=7
            req = make_envelope(
                IPCMsgType.SET_ACTIVE_CREW,
                SetActiveCrewPayload(crew_id="crew_007"),
                crew_id="crew_007",
                req_id=7,
            )
            await write_frame(writer, req.to_json_bytes())
            ack_raw = await read_frame(reader)
            assert ack_raw is not None
            ack_env = parse_envelope_bytes(ack_raw)
            assert ack_env.type == IPCMsgType.CREW_ACK
            assert ack_env.req_id == 7
            assert ack_env.payload["ok"] is True

            # Send PERIPHERAL_SNAPSHOT without MAX30102, then CSI_WINDOW -> confidence <= 0.65
            snap = make_envelope(
                IPCMsgType.PERIPHERAL_SNAPSHOT,
                PeripheralSnapshotPayload(
                    readings=[PeripheralReading(type=Peripheral.SCD40, value=900.0, unit="ppm", timestamp_us=now_us())],
                    timestamp_us=now_us(),
                ),
            )
            await write_frame(writer, snap.to_json_bytes())

            win = make_envelope(
                IPCMsgType.CSI_WINDOW,
                _make_csi_window(seq=100, n_links=12),
                crew_id="crew_007",
            )
            await write_frame(writer, win.to_json_bytes())
            inf_raw = await read_frame(reader)
            assert inf_raw is not None
            inf_env = parse_envelope_bytes(inf_raw)
            assert inf_env.type == IPCMsgType.AI_INFERENCE
            assert inf_env.payload["confidence"] <= RF_ONLY_MAX_CONFIDENCE

            # Send CALIBRATION_STEP and CHAT_CORRELATE_REQ
            cal = make_envelope(
                IPCMsgType.CALIBRATION_STEP,
                CalibrationStepPayload(step_id="s1", action="rest"),
                crew_id="crew_007",
                req_id=8,
            )
            await write_frame(writer, cal.to_json_bytes())
            fb_raw = await read_frame(reader)
            assert fb_raw is not None
            fb_env = parse_envelope_bytes(fb_raw)
            assert fb_env.type == IPCMsgType.CALIBRATION_FEEDBACK
            assert fb_env.req_id == 8

            chat = make_envelope(
                IPCMsgType.CHAT_CORRELATE_REQ,
                ChatCorrelateReqPayload(text="mild headache"),
                crew_id="crew_007",
                req_id=9,
            )
            await write_frame(writer, chat.to_json_bytes())
            resp_raw = await read_frame(reader)
            assert resp_raw is not None
            resp_env = parse_envelope_bytes(resp_raw)
            assert resp_env.type == IPCMsgType.CHAT_CORRELATE_RESP
            assert resp_env.req_id == 9

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

    asyncio.run(_run())


def test_ipc_roundtrip_on_port_5006(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(ai_host="127.0.0.1", ai_port=5006, models_dir=tmp_path)
        handler = IPCHandler(settings=settings)
        server = IPCServer(handler.handle, host="127.0.0.1", port=5006)
        await server.start()
        assert server.bound_port == 5006

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 5006)

            # 1. SET_ACTIVE_CREW -> CREW_ACK
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.SET_ACTIVE_CREW,
                    SetActiveCrewPayload(crew_id="crew_5006"),
                    crew_id="crew_5006",
                    req_id=101,
                ).to_json_bytes(),
            )
            ack = parse_envelope_bytes(await read_frame(reader) or b"")
            assert ack.type == IPCMsgType.CREW_ACK
            assert ack.req_id == 101
            assert ack.payload["ok"] is True

            # 2. PERIPHERAL_SNAPSHOT without MAX30102 + CSI_WINDOW (12 active links) -> AI_INFERENCE (P4 <= 0.65)
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.PERIPHERAL_SNAPSHOT,
                    PeripheralSnapshotPayload(
                        readings=[
                            PeripheralReading(type=Peripheral.SCD40, value=620.0, unit="ppm", timestamp_us=now_us())
                        ],
                        timestamp_us=now_us(),
                    ),
                ).to_json_bytes(),
            )
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.CSI_WINDOW,
                    _make_csi_window(seq=50, n_links=12),
                    crew_id="crew_5006",
                ).to_json_bytes(),
            )
            inf = parse_envelope_bytes(await read_frame(reader) or b"")
            assert inf.type == IPCMsgType.AI_INFERENCE
            assert inf.payload["cycle_seq_first"] == 50
            assert inf.payload["confidence"] <= RF_ONLY_MAX_CONFIDENCE

            # 3. CALIBRATION_STEP -> CALIBRATION_FEEDBACK
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.CALIBRATION_STEP,
                    CalibrationStepPayload(step_id="step_5006", action="rest_supine"),
                    crew_id="crew_5006",
                    req_id=102,
                ).to_json_bytes(),
            )
            cal_fb = parse_envelope_bytes(await read_frame(reader) or b"")
            assert cal_fb.type == IPCMsgType.CALIBRATION_FEEDBACK
            assert cal_fb.req_id == 102
            assert cal_fb.payload["step_id"] == "step_5006"
            assert cal_fb.payload["progress"] > 0

            # 4. CHAT_CORRELATE_REQ -> CHAT_CORRELATE_RESP
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.CHAT_CORRELATE_REQ,
                    ChatCorrelateReqPayload(
                        text="Estou com dor de cabeça",
                        crew_id="crew_5006",
                        last_peripherals=[
                            PeripheralReading(
                                type=Peripheral.SCD40,
                                value=2800.0,
                                unit="ppm",
                                timestamp_us=now_us(),
                            )
                        ],
                    ),
                    crew_id="crew_5006",
                    req_id=103,
                ).to_json_bytes(),
            )
            chat_resp = parse_envelope_bytes(await read_frame(reader) or b"")
            assert chat_resp.type == IPCMsgType.CHAT_CORRELATE_RESP
            assert chat_resp.req_id == 103
            assert "NASA-HRP-CO2" in chat_resp.payload["source_ids"]

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

    asyncio.run(_run())


def test_multi_astronaut_hotswap_astro01_astro02_and_calibration(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(ai_host="127.0.0.1", ai_port=0, models_dir=tmp_path)
        handler = IPCHandler(settings=settings)
        server = IPCServer(handler.handle, host="127.0.0.1", port=0)
        await server.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)

            async def _swap(crew_id: str, req_id: int) -> tuple[dict, float]:
                t0 = time.perf_counter()
                await write_frame(
                    writer,
                    make_envelope(
                        IPCMsgType.SET_ACTIVE_CREW,
                        SetActiveCrewPayload(crew_id=crew_id),
                        crew_id=crew_id,
                        req_id=req_id,
                    ).to_json_bytes(),
                )
                ack = parse_envelope_bytes(await read_frame(reader) or b"")
                dt_ms = (time.perf_counter() - t0) * 1000.0
                assert ack.type == IPCMsgType.CREW_ACK
                assert ack.req_id == req_id
                assert ack.payload["ok"] is True
                return ack.payload, dt_ms

            # Initial swap to ASTRO-01: uncalibrated yet -> baseline_found=False, < 300 ms
            ack1, ms1 = await _swap("ASTRO-01", 1)
            assert ack1["baseline_found"] is False
            assert ms1 < 300.0

            # Stream CSI window then run 3 calibration steps for ASTRO-01
            await write_frame(
                writer,
                make_envelope(IPCMsgType.CSI_WINDOW, _make_csi_window(seq=10, n_links=12), crew_id="ASTRO-01").to_json_bytes(),
            )
            _ = parse_envelope_bytes(await read_frame(reader) or b"")

            for step_idx in range(1, 4):
                await write_frame(
                    writer,
                    make_envelope(
                        IPCMsgType.CALIBRATION_STEP,
                        CalibrationStepPayload(step_id=f"s{step_idx}", action="rest_supine"),
                        crew_id="ASTRO-01",
                        req_id=10 + step_idx,
                    ).to_json_bytes(),
                )
                fb = parse_envelope_bytes(await read_frame(reader) or b"")
                assert fb.type == IPCMsgType.CALIBRATION_FEEDBACK
                assert fb.req_id == 10 + step_idx

            assert (tmp_path / "profiles" / "baseline_ASTRO-01.json").is_file()

            # Hot-swap to ASTRO-02 (< 300 ms, initially baseline_found=False)
            ack2, ms2 = await _swap("ASTRO-02", 2)
            assert ack2["baseline_found"] is False
            assert ms2 < 300.0

            # Swap back to ASTRO-01 -> baseline_found=True (< 300 ms)
            ack3, ms3 = await _swap("ASTRO-01", 3)
            assert ack3["baseline_found"] is True
            assert ms3 < 300.0

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

        # Reloading handler from disk still sees persisted ASTRO-01 baseline
        handler_reloaded = IPCHandler(settings=settings)
        _, found_disk = handler_reloaded.baseline_registry.set_active_crew("ASTRO-01")
        assert found_disk is True

    asyncio.run(_run())


def test_causal_differentiation_headache_co2_vs_sans(tmp_path: Path) -> None:
    correlator = ClinicalCorrelator(db_path=tmp_path / "missing.db")
    ts = now_us()

    # Teste A: "estou com dor de cabeça" + SCD40 CO2 alto -> Hipercapnia + contramedida ambiental CO2
    resp_co2 = correlator.correlate(
        ChatCorrelateReqPayload(text="estou com dor de cabeça"),
        peripherals=[PeripheralReading(type=Peripheral.SCD40, value=2800.0, unit="ppm", timestamp_us=ts)],
        inference=AIInferencePayload(
            cycle_seq_first=1,
            posture="sitting",
            respiration_hz=0.38,
            heart_rate_bpm=92.0,
            hrv_ms=34.0,
            anomaly_score=0.55,
            confidence=0.60,
        ),
        thresholds={
            "co2_ppm": Threshold(metric_name="co2_ppm", yellow_high=1500.0, red_high=3000.0),
        },
    )
    assert resp_co2.differentials is not None
    assert "Hipercapnia" in resp_co2.differentials[0]
    assert "NASA-HRP-CO2" in (resp_co2.source_ids or [])
    assert resp_co2.escalation in (Escalation.CREW, Escalation.STORE_AND_FORWARD)
    cm_co2 = " ".join(resp_co2.countermeasures or []).lower()
    assert "co2" in cm_co2 or "ventilação" in cm_co2 or "cdra" in cm_co2

    # Teste B: "estou com dor de cabeça" + pressão elevada / fluid shift -> SANS/VIIP, Thigh Cuffs + Complexo B + Grade de Amsler
    resp_sans = correlator.correlate(
        ChatCorrelateReqPayload(
            text="estou com dor de cabeça e pressão elevada, provável fluid shift",
            profile=CrewProfile(crew_id="ASTRO-01", name="Cmdr", mission_day=14),
        ),
        peripherals=[
            PeripheralReading(type=Peripheral.SCD40, value=550.0, unit="ppm", timestamp_us=ts),
            PeripheralReading(type=Peripheral.MAX30102, value=98.2, unit="%", timestamp_us=ts),
        ],
        inference=AIInferencePayload(
            cycle_seq_first=2,
            posture="supine",
            respiration_hz=0.22,
            heart_rate_bpm=64.0,
            hrv_ms=55.0,
            anomaly_score=0.48,
            confidence=0.80,
        ),
        thresholds={
            # Also assert Go-style lower-only spo2_pct threshold (yellow_high=0, red_high=0) does not false-trigger RED
            "spo2_pct": Threshold(metric_name="spo2_pct", yellow_high=0.0, red_high=0.0, yellow_low=94.0, red_low=90.0),
        },
    )
    assert resp_sans.differentials is not None
    assert "SANS" in resp_sans.differentials[0]
    assert "NASA-HRP-SANS" in (resp_sans.source_ids or [])
    cm_sans = " ".join(resp_sans.countermeasures or [])
    assert "Thigh Cuffs" in cm_sans
    assert "Complexo B" in cm_sans
    assert resp_sans.disambiguation_question is not None
    assert "Grade de Amsler" in resp_sans.disambiguation_question
    assert resp_sans.escalation != Escalation.STORE_AND_FORWARD

    # Scenario 3: Ambiguous headache without visual info -> Information Gain picks Amsler Grid question
    resp_ambig = correlator.correlate(
        ChatCorrelateReqPayload(
            text="Estou com dor de cabeça",
            profile=CrewProfile(crew_id="c1", name="Cmdr", mission_day=10),
        ),
        peripherals=[PeripheralReading(type=Peripheral.SCD40, value=950.0, unit="ppm", timestamp_us=ts)],
        inference=AIInferencePayload(
            cycle_seq_first=3,
            posture="supine",
            respiration_hz=0.25,
            heart_rate_bpm=70.0,
            hrv_ms=48.0,
            anomaly_score=0.45,
            confidence=0.60,
        ),
    )
    assert resp_ambig.disambiguation_question is not None
    assert "Amsler" in resp_ambig.disambiguation_question


def test_chat_correlate_ignores_zero_peripheral_placeholders(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(models_dir=tmp_path, db_path=tmp_path / "missing.db")
        handler = IPCHandler(settings=settings)
        ts = now_us()

        await handler.handle(
            make_envelope(
                IPCMsgType.SET_ACTIVE_CREW,
                SetActiveCrewPayload(
                    crew_id="ASTRO-01",
                    thresholds={
                        "spo2_pct": Threshold(
                            metric_name="spo2_pct",
                            yellow_high=0.0,
                            red_high=0.0,
                            yellow_low=94.0,
                            red_low=90.0,
                        ),
                        "co2_ppm": Threshold(
                            metric_name="co2_ppm",
                            yellow_high=1000.0,
                            red_high=3500.0,
                        ),
                    },
                ),
                crew_id="ASTRO-01",
                req_id=1,
            )
        )
        await handler.handle(
            make_envelope(
                IPCMsgType.PERIPHERAL_SNAPSHOT,
                PeripheralSnapshotPayload(
                    readings=[
                        PeripheralReading(type=Peripheral.SCD40, value=600.0, unit="ppm", timestamp_us=ts),
                        PeripheralReading(type=Peripheral.MAX30102, value=98.0, unit="%", timestamp_us=ts),
                    ],
                    timestamp_us=ts,
                ),
            )
        )
        resp_env = await handler.handle(
            make_envelope(
                IPCMsgType.CHAT_CORRELATE_REQ,
                ChatCorrelateReqPayload(
                    text="estou com dor de cabeca",
                    crew_id="ASTRO-01",
                    profile=CrewProfile(crew_id="ASTRO-01", name="Cmdr", mission_day=20),
                    last_peripherals=[
                        PeripheralReading(type=Peripheral.SCD40, value=0.0, unit="ppm", timestamp_us=ts),
                        PeripheralReading(type=Peripheral.MAX30102, value=0.0, unit="%", timestamp_us=ts),
                        PeripheralReading(type=Peripheral.BME280, value=0.0, unit="C", timestamp_us=ts),
                    ],
                ),
                crew_id="ASTRO-01",
                req_id=2,
            )
        )
        assert resp_env is not None
        diffs = resp_env.payload.get("differentials") or []
        assert diffs and "Hipóxia" not in diffs[0]
        assert resp_env.payload.get("escalation") != "STORE_AND_FORWARD"

    asyncio.run(_run())


def test_clinical_store_fts5_readonly_and_yaml_fallback(tmp_path: Path) -> None:
    import sqlite3

    # 1. Fallback when DB does not exist
    store_missing = ClinicalStore(db_path=tmp_path / "does_not_exist.db")
    yaml_hits = store_missing.search("blurred_vision headache", concepts=("headache", "blurred_vision"))
    assert len(yaml_hits) >= 1
    assert all(h.source == "yaml_fallback" for h in yaml_hits)

    # 2. Read-only FTS5 BM25 query when DB is populated
    db_file = tmp_path / "clinical.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE VIRTUAL TABLE clinical_protocols_fts USING fts5(protocol_id, name, subsystem, description)"
    )
    conn.execute(
        "INSERT INTO clinical_protocols_fts VALUES (?, ?, ?, ?)",
        (
            "NASA-HRP-SANS",
            "SANS Fluid Shift Protocol",
            "NEURO_OCULAR_SANS",
            "Amsler grid and LBNP countermeasure for headache and blurred vision",
        ),
    )
    conn.commit()
    conn.close()

    store_ro = ClinicalStore(db_path=db_file)
    fts_hits = store_ro.search("Amsler headache", concepts=("headache",))
    assert len(fts_hits) == 1
    assert fts_hits[0].source == "sqlite_fts5"
    assert fts_hits[0].doc_id == "NASA-HRP-SANS"


def test_symptom_extractor_bilingual() -> None:
    ext = SymptomExtractor()
    res = ext.extract("Tenho dor de cabeça, cansaço e visão turva após EVA")
    assert "headache" in res.concepts
    assert "fatigue" in res.concepts
    assert "blurred_vision" in res.concepts
    assert res.eva_context is True


def _apply_real_migrations(db_file: Path) -> Path:
    import sqlite3

    repo_root = Path(__file__).resolve().parents[2]
    mig_dir = repo_root / "database" / "migrations"
    sql_files = sorted(mig_dir.glob("*.sql"))
    assert [p.name for p in sql_files][:2] == [
        "0001_operational_schema.sql",
        "0002_operational_seeds.sql",
    ]

    conn = sqlite3.connect(db_file)
    try:
        for sql_path in sql_files:
            conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return repo_root


def test_clinical_store_real_database_migrations(tmp_path: Path) -> None:
    db_file = tmp_path / "edgespace_real.db"
    _apply_real_migrations(db_file)

    store = ClinicalStore(db_path=db_file)
    queries = (
        "dor de cabeça",
        "dor de cabeca",
        "radiação",
        "radiacao",
        "insônia",
        "insonia",
        "visão turva",
        "visao turva",
        "SANS",
        "CO2",
        "hypoxia",
        "decompression",
    )
    for query in queries:
        hits = store.search(query)
        assert hits, f"expected FTS5 hits for {query!r}"
        assert all(h.source == "sqlite_fts5" for h in hits), f"unexpected fallback hit for {query!r}: {hits}"


def test_baseline_registry_parity_with_sql_seeds(tmp_path: Path) -> None:
    import sqlite3

    db_file = tmp_path / "edgespace_real.db"
    repo_root = _apply_real_migrations(db_file)
    edge_ai_dir = repo_root / "edge-ai"

    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute("SELECT crew_id, baseline_path FROM crew_profiles ORDER BY crew_id").fetchall()
    finally:
        conn.close()

    assert [r[0] for r in rows] == ["crew_001", "crew_002", "crew_003"]

    registry = BaselineRegistry(models_dir=edge_ai_dir / "models")
    results: dict[str, tuple[bool, float]] = {}
    for crew_id, baseline_path in rows:
        resolved = str((edge_ai_dir / baseline_path).resolve()) if baseline_path else None
        _, found = registry.set_active_crew(crew_id, baseline_path=resolved)
        results[crew_id] = (found, registry.last_switch_ms)

    assert results["crew_001"][0] is True and results["crew_001"][1] < 300.0
    assert results["crew_002"][0] is True and results["crew_002"][1] < 300.0
    assert results["crew_003"][0] is False and results["crew_003"][1] < 300.0


def test_golden_cases_end_to_end_with_real_sqlite(tmp_path: Path) -> None:
    import re
    import sqlite3
    from edgespace_ai.correlation.clinical_store import load_yaml_file

    db_file = tmp_path / "edgespace_real.db"
    repo_root = _apply_real_migrations(db_file)

    conn = sqlite3.connect(db_file)
    try:
        crew_thresholds: dict[str, dict[str, Threshold]] = {}
        for crew_id, tj in conn.execute("SELECT crew_id, thresholds_json FROM crew_profiles").fetchall():
            raw = json.loads(tj)
            crew_thresholds[crew_id] = {k: Threshold(**v) for k, v in raw.items()}
    finally:
        conn.close()

    causal_kb = load_yaml_file(repo_root / "edge-ai" / "knowledge-base" / "nasa_causal_graph.yaml")
    cond_meta = {
        c["id"]: (c["name"], c["source_id"])
        for c in causal_kb.get("conditions", [])
        if isinstance(c, dict)
    }

    golden = load_yaml_file(repo_root / "knowledge-base" / "datasets" / "golden_cases" / "golden_cases.yaml")
    cases = golden.get("cases", [])
    assert len(cases) == 4

    correlator = ClinicalCorrelator(db_path=db_file)
    ts = now_us()

    for case in cases:
        inp = case["input"]
        snap = inp.get("sensor_snapshot") or {}
        hist = inp.get("history") or {}
        crew_id = str(hist.get("crew_id") or "crew_001")

        parts = list(inp.get("symptoms") or [])
        if hist.get("spe_alert") or snap.get("radiation_context"):
            parts.append("SPE radiation alert")
        if snap.get("sleep_duration_h") is not None and float(snap["sleep_duration_h"]) < 6.0:
            parts.append(f"sono curto {snap['sleep_duration_h']}h")
        if snap.get("hydration_index") is not None and float(snap["hydration_index"]) < 0.5:
            parts.append("baixa hidratacao")
        text = " ".join(str(p) for p in parts)

        peripherals: list[PeripheralReading] = []
        if "co2_ppm" in snap:
            peripherals.append(PeripheralReading(type=Peripheral.SCD40, value=float(snap["co2_ppm"]), unit="ppm", timestamp_us=ts))
        if "spo2_pct" in snap:
            peripherals.append(PeripheralReading(type=Peripheral.MAX30102, value=float(snap["spo2_pct"]), unit="%", timestamp_us=ts))
        if "temp_c" in snap:
            peripherals.append(PeripheralReading(type=Peripheral.BME280, value=float(snap["temp_c"]), unit="C", timestamp_us=ts))

        inference = AIInferencePayload(
            cycle_seq_first=1,
            posture=str(snap.get("posture", "upright")),
            respiration_hz=float(snap.get("respiration_hz", 0.25)),
            heart_rate_bpm=float(snap.get("heart_rate_bpm", 72.0)),
            hrv_ms=float(snap.get("hrv_ms", 45.0)),
            anomaly_score=float(snap.get("anomaly_score", 0.1)),
            confidence=0.9,
        )
        req = ChatCorrelateReqPayload(
            text=text,
            crew_id=crew_id,
            profile=CrewProfile(crew_id=crew_id, name=crew_id, mission_day=int(snap.get("mission_day", 42))),
            last_peripherals=peripherals,
        )
        resp = correlator.correlate(
            req,
            peripherals=peripherals,
            inference=inference,
            thresholds=crew_thresholds.get(crew_id),
        )

        exp = case["expected"]
        exp_id = exp["top1_hypothesis"]
        exp_name, exp_source_id = cond_meta[exp_id]

        assert resp.differentials, f"{case['id']}: missing differentials"
        assert resp.differentials[0].startswith(exp_name), (
            f"{case['id']}: got {resp.differentials[0]!r}, expected prefix {exp_name!r}"
        )
        assert resp.source_ids and resp.source_ids[0] == exp_source_id, (
            f"{case['id']}: source_ids={resp.source_ids}, expected first={exp_source_id!r}"
        )
        m = re.search(r"P=(\d+\.\d+)", resp.differentials[0])
        assert m is not None, f"{case['id']}: could not parse posterior from {resp.differentials[0]!r}"
        posterior = float(m.group(1))
        assert posterior >= float(exp["min_top1_posterior"]), (
            f"{case['id']}: posterior {posterior} < {exp['min_top1_posterior']}"
        )
        assert resp.escalation.value == exp["escalation"], (
            f"{case['id']}: escalation={resp.escalation.value}, expected={exp['escalation']}"
        )
        assert any("Base clínica (sqlite_fts5)" in ev for ev in (resp.evidence or [])), (
            f"{case['id']}: expected sqlite_fts5 citation in evidence={resp.evidence}"
        )

    correlator = ClinicalCorrelator(db_path=db_file)
    ts = now_us()


