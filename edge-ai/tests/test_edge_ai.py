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


def _sql_settings(tmp_path: Path, **kwargs):
    db_file=Path(kwargs.get('db_path') or tmp_path/'worker.db')
    if not db_file.exists():_apply_real_migrations(db_file)
    kwargs['db_path']=db_file
    return Settings(**kwargs)


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
    db_file = tmp_path / "adapt.db"
    _apply_real_migrations(db_file)

    # BaselineRegistry now requires db_path
    with pytest.raises(ValueError):
        BaselineRegistry(models_dir=tmp_path)

    registry = BaselineRegistry(models_dir=tmp_path, db_path=db_file)
    cal = CalibrationEngine(registry, target_steps=2)

    t0 = time.perf_counter()
    b0, found = registry.set_active_crew("crew_001")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # Single rule: SYNTHETIC_SEED + samples + baseline_path -> calibrated (crew_001/002).
    assert found is True
    assert b0.sample_count == 164  # preserved, not zeroed
    assert elapsed_ms < 300.0
    # crew_003: SYNTHETIC_SEED without baseline_path -> calibration pending.
    _, found3 = registry.set_active_crew("crew_003")
    assert found3 is False
    registry.set_active_crew("crew_001")
    assert b0.per_posture_stats
    assert b0.normalize_vital("heart_rate_bpm", 72.0, posture="sitting") is not None

    vec = np.ones(FEATURE_DIM, dtype=np.float32) * 2.5
    res1 = cal.process_step(
        crew_id="crew_001",
        step_id="step_1",
        action="rest_supine",
        latest_features=vec,
    )
    assert res1.progress == 50
    res2 = cal.process_step(
        crew_id="crew_001",
        step_id="step_2",
        action="rest_supine",
        latest_features=vec * 1.1,
    )
    assert res2.progress == 100
    # EMA continues from the persisted SYNTHETIC_SEED sample_count (164 + 2 steps).
    assert res2.baseline.sample_count == 166
    assert "supine" in res2.baseline.per_posture_stats
    assert "mean" in res2.baseline.per_posture_stats["supine"]
    norm_vec = res2.baseline.normalize(vec, posture="supine")
    assert norm_vec.shape == (FEATURE_DIM,)
    assert not (tmp_path / "profiles").exists()


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
        settings = _sql_settings(tmp_path, ai_host="127.0.0.1", ai_port=0, models_dir=tmp_path)
        handler = IPCHandler(settings=settings)
        server = IPCServer(handler.handle, host="127.0.0.1", port=0, lo_pri_cap=4)
        await server.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)

            # Send SET_ACTIVE_CREW with req_id=7
            req = make_envelope(
                IPCMsgType.SET_ACTIVE_CREW,
                SetActiveCrewPayload(crew_id="crew_001"),
                crew_id="crew_001",
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
                crew_id="crew_001",
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
                crew_id="crew_001",
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
                crew_id="crew_001",
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
    import socket

    def _port_free(p: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False
        finally:
            s.close()

    async def _run() -> None:
        port = 5006 if _port_free(5006) else 0
        settings = _sql_settings(tmp_path, ai_host="127.0.0.1", ai_port=port, models_dir=tmp_path)
        handler = IPCHandler(settings=settings)
        server = IPCServer(handler.handle, host="127.0.0.1", port=port)
        await server.start()
        if port == 5006:
            assert server.bound_port == 5006

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)

            # 1. SET_ACTIVE_CREW -> CREW_ACK
            await write_frame(
                writer,
                make_envelope(
                    IPCMsgType.SET_ACTIVE_CREW,
                    SetActiveCrewPayload(
                        crew_id="crew_001",
                        thresholds={
                            "co2_ppm": Threshold(metric_name="co2_ppm", yellow_high=1500.0, red_high=3000.0),
                        },
                    ),
                    crew_id="crew_001",
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
                    crew_id="crew_001",
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
                    crew_id="crew_001",
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
                        crew_id="crew_001",
                        last_peripherals=[
                            PeripheralReading(
                                type=Peripheral.SCD40,
                                value=2800.0,
                                unit="ppm",
                                timestamp_us=now_us(),
                            )
                        ],
                    ),
                    crew_id="crew_001",
                    req_id=103,
                ).to_json_bytes(),
            )
            chat_resp = parse_envelope_bytes(await read_frame(reader) or b"")
            assert chat_resp.type == IPCMsgType.CHAT_CORRELATE_RESP
            assert chat_resp.req_id == 103
            assert "NASA-EVA" in chat_resp.payload["source_ids"]

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

    asyncio.run(_run())


def test_multi_astronaut_hotswap_astro01_astro02_and_calibration(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _sql_settings(tmp_path, ai_host="127.0.0.1", ai_port=0, models_dir=tmp_path)
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

            # Initial swap to crew_001: SYNTHETIC_SEED + baseline_path -> baseline_found=True, < 300 ms
            ack1, ms1 = await _swap("crew_001", 1)
            assert ack1["baseline_found"] is True
            assert ms1 < 300.0

            # Stream CSI window then run 3 calibration steps for crew_001
            await write_frame(
                writer,
                make_envelope(IPCMsgType.CSI_WINDOW, _make_csi_window(seq=10, n_links=12), crew_id="crew_001").to_json_bytes(),
            )
            _ = parse_envelope_bytes(await read_frame(reader) or b"")

            for step_idx in range(1, 4):
                await write_frame(
                    writer,
                    make_envelope(
                        IPCMsgType.CALIBRATION_STEP,
                        CalibrationStepPayload(step_id=f"s{step_idx}", action="rest_supine"),
                        crew_id="crew_001",
                        req_id=10 + step_idx,
                    ).to_json_bytes(),
                )
                fb = parse_envelope_bytes(await read_frame(reader) or b"")
                assert fb.type == IPCMsgType.CALIBRATION_FEEDBACK
                assert fb.req_id == 10 + step_idx

            assert not (tmp_path / "profiles").exists()

            # Hot-swap to crew_002 (< 300 ms, SYNTHETIC_SEED + baseline_path -> True)
            ack2, ms2 = await _swap("crew_002", 2)
            assert ack2["baseline_found"] is True
            assert ms2 < 300.0

            # crew_003 has no baseline_path -> calibration pending
            ack4, ms4 = await _swap("crew_003", 4)
            assert ack4["baseline_found"] is False
            assert ms4 < 300.0

            # Swap back to crew_001 -> baseline_found=True (< 300 ms)
            ack3, ms3 = await _swap("crew_001", 3)
            assert ack3["baseline_found"] is True
            assert ms3 < 300.0

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

        # Reloading handler from disk still sees persisted crew_001 baseline
        handler_reloaded = IPCHandler(settings=settings)
        _, found_disk = handler_reloaded.baseline_registry.set_active_crew("crew_001")
        assert found_disk is True

    asyncio.run(_run())


def test_causal_differentiation_headache_co2_vs_sans(tmp_path: Path) -> None:
    import sqlite3

    db_file = tmp_path / "clinical.db"
    _apply_real_migrations(db_file)
    with sqlite3.connect(db_file) as c:
        c.execute("DELETE FROM mission_context_events")
        c.execute("DELETE FROM telemetry_daily_rollups")
        c.execute("DELETE FROM nutrition_hydration_logs")
        c.commit()
    correlator = ClinicalCorrelator(db_path=db_file)
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
    assert "NASA-EVA" in (resp_co2.source_ids or [])
    assert resp_co2.escalation in (Escalation.CREW, Escalation.STORE_AND_FORWARD)
    cm_co2 = " ".join(resp_co2.countermeasures or []).lower()
    assert "co2" in cm_co2 or "ventilação" in cm_co2 or "cdra" in cm_co2

    # Teste B: "estou com dor de cabeça" + pressão elevada / fluid shift -> SANS/VIIP, Thigh Cuffs + Complexo B + Grade de Amsler
    resp_sans = correlator.correlate(
        ChatCorrelateReqPayload(
            text="estou com dor de cabeça e pressão elevada, provável fluid shift",
            profile=CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=14),
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
    assert "NASA-SANS" in (resp_sans.source_ids or [])
    cm_sans = " ".join(resp_sans.countermeasures or [])
    assert "Aplicar Thigh Cuffs" not in cm_sans
    assert "Administrar" not in cm_sans
    assert resp_sans.disambiguation_question is not None
    assert "Amsler" in resp_sans.disambiguation_question
    assert resp_sans.escalation != Escalation.STORE_AND_FORWARD

    # Scenario 3: Ambiguous headache without visual info -> Information Gain picks Amsler Grid question
    resp_ambig = correlator.correlate(
        ChatCorrelateReqPayload(
            text="Estou com dor de cabeça",
            profile=CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=10),
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
        settings = _sql_settings(tmp_path, models_dir=tmp_path, db_path=tmp_path / "missing.db")
        handler = IPCHandler(settings=settings)
        ts = now_us()

        await handler.handle(
            make_envelope(
                IPCMsgType.SET_ACTIVE_CREW,
                SetActiveCrewPayload(
                    crew_id="crew_001",
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
                crew_id="crew_001",
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
                    crew_id="crew_001",
                    profile=CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=20),
                    last_peripherals=[
                        PeripheralReading(type=Peripheral.SCD40, value=0.0, unit="ppm", timestamp_us=ts),
                        PeripheralReading(type=Peripheral.MAX30102, value=0.0, unit="%", timestamp_us=ts),
                        PeripheralReading(type=Peripheral.BME280, value=0.0, unit="C", timestamp_us=ts),
                    ],
                ),
                crew_id="crew_001",
                req_id=2,
            )
        )
        assert resp_env is not None
        diffs = resp_env.payload.get("differentials") or []
        assert diffs and "Hipóxia" not in diffs[0]
        assert resp_env.payload.get("escalation") != "STORE_AND_FORWARD"

    asyncio.run(_run())


def test_clinical_store_fts5_readonly_and_fusion(tmp_path: Path) -> None:
    import sqlite3

    # 1. Explicit missing DB fails cleanly without YAML fallback
    store_missing = ClinicalStore(db_path=tmp_path / "does_not_exist.db")
    with pytest.raises(FileNotFoundError):
        store_missing.search("blurred_vision headache", concepts=("headache", "blurred_vision"))

    # 2. Read-only FTS5 BM25 query fusing clinical_reports_fts + protocols_fts
    db_file = tmp_path / "clinical.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE clinical_reports (report_id TEXT PRIMARY KEY, source_id TEXT, category TEXT, payload_json TEXT)")
    conn.execute("INSERT INTO clinical_reports VALUES ('rep_sans', 'NASA-SANS', 'PHYSIOLOGICAL', '{}')")
    conn.execute("CREATE VIRTUAL TABLE clinical_reports_fts USING fts5(report_id, source_id, title, problem, content_text)")
    conn.execute("INSERT INTO clinical_reports_fts VALUES ('rep_sans', 'NASA-SANS', 'SANS Visual Report', 'headache', 'Amsler grid screening')")
    conn.execute("CREATE VIRTUAL TABLE protocols_fts USING fts5(protocol_id, name, subsystem, description)")
    conn.execute(
        "INSERT INTO protocols_fts VALUES (?, ?, ?, ?)",
        (
            "amsler_grid",
            "Amsler Grid Check",
            "NEURO_OCULAR_SANS",
            "Amsler grid countermeasure for headache and blurred vision",
        ),
    )
    conn.commit()
    conn.close()

    store_ro = ClinicalStore(db_path=db_file)
    fts_hits = store_ro.search("Amsler headache", concepts=("headache",), limit=5)
    assert len(fts_hits) == 2
    assert all(h.source == "sqlite_fts5" for h in fts_hits)
    assert {h.doc_id for h in fts_hits} == {"rep_sans", "amsler_grid"}


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

    registry = BaselineRegistry(models_dir=edge_ai_dir / "models", db_path=db_file)
    results: dict[str, tuple[bool, float]] = {}
    for crew_id, baseline_path in rows:
        resolved = str((edge_ai_dir / baseline_path).resolve()) if baseline_path else None
        b, found = registry.set_active_crew(crew_id, baseline_path=resolved)
        assert b.per_posture_stats
        assert b.sample_count == 164
        results[crew_id] = (found, registry.last_switch_ms)

    # Single calibration rule (mirrors store.IsCalibrated in Go).
    assert results["crew_001"][0] is True
    assert results["crew_002"][0] is True
    assert results["crew_003"][0] is False
    assert results["crew_001"][1] < 300.0
    assert results["crew_002"][1] < 300.0
    assert results["crew_003"][1] < 300.0


def test_golden_cases_end_to_end_with_real_sqlite(tmp_path: Path) -> None:
    import sqlite3
    db_file=tmp_path/'golden.db'
    repo_root=_apply_real_migrations(db_file)
    suite=json.loads((repo_root/'knowledge-base/datasets/golden_cases/golden_cases.yaml').read_text())
    assert len(suite['cases'])>=16
    correlator=ClinicalCorrelator(db_path=db_file)
    assert len(correlator.causal_graph.conditions)>=19
    with sqlite3.connect(db_file) as c:
        c.execute('DELETE FROM mission_context_events')
        c.execute('DELETE FROM telemetry_daily_rollups')
        c.execute('DELETE FROM nutrition_hydration_logs')
        c.commit()
        for case in suite['cases']:
            c.execute('DELETE FROM self_exams')
            c.execute('INSERT INTO self_exams(ts_us,crew_id,exam_type,result,observations) VALUES (?,?,?,?,?)',(now_us(),case['crew_id'],'structured_fixture',json.dumps(case['metrics']),'SYNTHETIC'))
            c.commit()
            result=correlator.correlate(ChatCorrelateReqPayload(text='Revisar registros estruturados',crew_id=case['crew_id']))
            assert set(result.matched_condition_ids or [])==set(case['expected_conditions']),case['case_id']
            assert result.max_severity==case['expected_max_severity'],case['case_id']
            assert set(case['expected_blocked_actions'])<=set(result.blocked_actions or []),case['case_id']
            assert result.model_status=='ENGINEERING_TEST_ONLY'


def test_abdominal_pain_dor_de_barriga_correlation(tmp_path: Path) -> None:
    db_file = tmp_path / "abdo.db"
    _apply_real_migrations(db_file)
    correlator = ClinicalCorrelator(db_path=db_file)
    ts = now_us()

    # Garante extração correta de sintomas GI e ausência de cefaleia
    ext = SymptomExtractor()
    extracted = ext.extract("estou com dor de barriga")
    assert "abdominal_pain" in extracted.concepts
    assert "headache" not in extracted.concepts

    # Mesmo em decúbito (supine), dia 14 e CO2 nominal (cenário que antes enviesava SANS),
    # "estou com dor de barriga" deve priorizar condição GI e nunca retornar headache/SANS no topo.
    resp = correlator.correlate(
        ChatCorrelateReqPayload(
            text="estou com dor de barriga",
            crew_id="crew_001",
            profile=CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=14),
        ),
        peripherals=[
            PeripheralReading(type=Peripheral.SCD40, value=620.0, unit="ppm", timestamp_us=ts),
            PeripheralReading(type=Peripheral.MAX30102, value=98.0, unit="%", timestamp_us=ts),
            PeripheralReading(type=Peripheral.BME280, value=31.0, unit="%", timestamp_us=ts),
        ],
        inference=AIInferencePayload(
            cycle_seq_first=10,
            posture="supine",
            respiration_hz=0.23,
            heart_rate_bpm=72.0,
            hrv_ms=48.0,
            anomaly_score=0.42,
            confidence=0.80,
        ),
    )

    ev_joined = " ".join(resp.evidence or []).lower()
    assert "headache" not in ev_joined
    assert "abdominal_pain" in ev_joined

    assert resp.differentials is not None and len(resp.differentials) >= 1
    assert not resp.differentials[0].startswith("SANS")
    assert "gastrointestinais" in resp.differentials[0].lower() or "gi_motility" in resp.differentials[0].lower()
    assert "NASA-MICROBIOME" in (resp.source_ids or [])

    cm_text = " ".join(resp.countermeasures or []).lower()
    assert cm_text and ("protocolo" in cm_text or "contexto" in cm_text or "hidrata" in cm_text)

    assert resp.disambiguation_question is not None
    q_low = resp.disambiguation_question.lower()
    assert "alimentar" in q_low or "medicamento" in q_low or "tripulante" in q_low or "estufamento" in q_low


def test_symptom_extractor_no_headache_fallback_and_nominal_clarification(tmp_path: Path) -> None:
    ext = SymptomExtractor()
    # "dor" isolado não deve casar headache; texto desconhecido retorna vazio
    assert ext.extract("estou com dor").concepts == ()
    assert ext.extract("preciso de ajuda").concepts == ()
    assert "gi_slowdown" in ext.extract("estufamento e prisao de ventre").concepts
    assert "flank_pain" in ext.extract("dor no flanco e pedra no rim").concepts
    assert "nausea" in ext.extract("muito enjoo e vomito").concepts

    # Sem sintomas e sensores nominais -> não força hipótese P > 0.50; pede detalhamento
    db_file = tmp_path / "nominal.db"
    _apply_real_migrations(db_file)
    correlator = ClinicalCorrelator(db_path=db_file)
    ts = now_us()
    resp = correlator.correlate(
        ChatCorrelateReqPayload(
            text="não estou me sentindo muito bem",
            crew_id="crew_001",
            profile=CrewProfile(crew_id="crew_001", name="Cmdr", mission_day=14),
        ),
        peripherals=[
            PeripheralReading(type=Peripheral.SCD40, value=600.0, unit="ppm", timestamp_us=ts),
            PeripheralReading(type=Peripheral.MAX30102, value=98.5, unit="%", timestamp_us=ts),
        ],
        inference=AIInferencePayload(
            cycle_seq_first=11,
            posture="supine",
            respiration_hz=0.22,
            heart_rate_bpm=68.0,
            hrv_ms=52.0,
            anomaly_score=0.15,
            confidence=0.85,
        ),
    )
    assert resp.differentials is None
    assert "headache" not in " ".join(resp.evidence or []).lower()
    assert resp.disambiguation_question is not None
    assert "detalhar" in resp.disambiguation_question.lower() or "detalhe" in resp.text.lower()


def test_clinical_repo_lookback_longitudinal_and_rollup_compare(tmp_path: Path) -> None:
    import sqlite3
    from edgespace_ai.clinical import ClinicalRepository

    db_file = tmp_path / "repo_v2.db"
    _apply_real_migrations(db_file)
    now = now_us()
    with sqlite3.connect(db_file) as c:
        c.execute("DELETE FROM mission_context_events")
        c.execute(
            "INSERT INTO mission_context_events(event_id, crew_id, event_type, ts_us, end_us, lookback_hours, severity, details_json, data_class) VALUES (?,?,?,?,?,?,?,?,?)",
            ("eva-36h", "crew_001", "EVA", now - 37 * 3600_000_000, now - 36 * 3600_000_000, 72.0, "INFO", "{}", "REAL"),
        )
        c.execute(
            "INSERT INTO mission_context_events(event_id, crew_id, event_type, ts_us, end_us, lookback_hours, severity, details_json, data_class) VALUES (?,?,?,?,?,?,?,?,?)",
            ("ex-5h-expired", "crew_001", "EXERCISE_ARED", now - 6 * 3600_000_000, now - 5 * 3600_000_000, 2.0, "INFO", "{}", "REAL"),
        )
        c.execute(
            "INSERT INTO mission_context_events(event_id, crew_id, event_type, ts_us, end_us, lookback_hours, severity, details_json, data_class) VALUES (?,?,?,?,?,?,?,?,?)",
            ("spe-40h", None, "RADIATION_SPE_ALERT", now - 40 * 3600_000_000, now - 40 * 3600_000_000, 72.0, "YELLOW", "{}", "REAL"),
        )
        c.commit()

    with ClinicalRepository(db_file) as repo:
        cm = repo.context_metrics("crew_001")
        assert cm["eva_recent_72h"] == 1
        assert cm["eva_recent_24h"] == 0
        assert cm["spe_alert"] == 1
        assert cm["exercise_recent"] == 0

        long_row = repo.longitudinal("crew_001")
        assert long_row and "deep_sleep_3d_avg_h" in long_row
        assert repo.compare(None, "LT", 5.0, rule_scope="ROLLUP_3D", metric="deep_sleep_3d_avg_h", longitudinal=long_row) is True


def test_causal_graph_requires_db_and_symptom_weights(tmp_path: Path) -> None:
    from edgespace_ai.correlation.causal_graph import CausalGraph

    with pytest.raises(ValueError):
        CausalGraph()

    yg = CausalGraph(allow_yaml_for_tests=True)
    assert yg.conditions

    db_file = tmp_path / "cg.db"
    _apply_real_migrations(db_file)
    g = CausalGraph(db_path=db_file)
    hyp = next(c for c in g.conditions if c.id == "HYPERCAPNIA")
    assert hyp.symptoms["headache"] == pytest.approx(0.9)


def test_disambiguator_prioritizes_top2_competitors() -> None:
    from edgespace_ai.correlation.causal_graph import CausalCondition, DisambiguationQuestion, HypothesisPosterior
    from edgespace_ai.correlation.disambiguator import Disambiguator

    q_other = DisambiguationQuestion(
        id="Q_OTHER", prompt="Unrelated?", positive_concepts=("fever",),
        yes_likelihood=0.95, no_likelihood=0.05, owner_condition_id="C1", target_differential_ids=("C9",),
    )
    q_top2 = DisambiguationQuestion(
        id="Q_TOP2", prompt="Target top2?", positive_concepts=("headache",),
        yes_likelihood=0.80, no_likelihood=0.20, owner_condition_id="C1", target_differential_ids=("C2",),
    )
    c1 = CausalCondition("C1", "Cond1", "S1", "SUB", 0.3, Escalation.LOCAL, {"headache": 0.8}, (), (), (), (q_other, q_top2))
    c2 = CausalCondition("C2", "Cond2", "S2", "SUB", 0.3, Escalation.LOCAL, {"dizziness": 0.8}, (), (), (), ())
    choice = Disambiguator().select_question([
        HypothesisPosterior(c1, 0.52, ("headache",), ()),
        HypothesisPosterior(c2, 0.48, ("dizziness",), ()),
    ])
    assert choice is not None and choice.question.id == "Q_TOP2"


def test_correlator_permanent_facts_and_allergy_contraindications(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    import sqlite3

    caplog.set_level(logging.DEBUG)
    db_file = tmp_path / "mem.db"
    _apply_real_migrations(db_file)
    with sqlite3.connect(db_file) as c:
        c.execute(
            "INSERT INTO causal_contraindications(condition_id, blocked_action, guard_metric, guard_op, guard_value, rationale) VALUES (?,?,?,?,?,?)",
            ("HYPERCAPNIA", "CHECK_VENTILATION", "allergy_sulfa", "EQ", 1.0, "Alergia a sulfa registrada"),
        )
        c.commit()

    correlator = ClinicalCorrelator(db_path=db_file)
    resp = correlator.correlate(
        ChatCorrelateReqPayload(
            text="Sou alérgico a sulfa, tomo melatonina, já tive enjoo espacial, CO2 me dá dor de cabeça e dormi mal",
            crew_id="crew_001",
        ),
        peripherals=[PeripheralReading(type=Peripheral.SCD40, value=3800.0, unit="ppm", timestamp_us=now_us())],
    )
    updates = {u["fact_type"]: u for u in (resp.memory_updates or [])}
    for ftype in ("ALLERGY", "MEDICATION", "CONDITION_HISTORY", "SENSITIVITY", "SLEEP_NOTE"):
        assert ftype in updates and 0.0 < updates[ftype]["confidence"] <= 1.0
    assert resp.blocked_actions and "CHECK_VENTILATION" in resp.blocked_actions
    assert not any("yaml_fallback" in r.message.lower() or "fallback" in r.message.lower() for r in caplog.records)
