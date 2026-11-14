"""Offline realistic CSI dataset generator and ONNX model builder for Edge Space AI.

Synthesizes multi-link complex CSI time series through the exact runtime DSP pipeline
(``CSIProcessor`` + SNR-weighted link fusion matching ``LinkFusion`` + ``FeatureExtractor``),
trains all 5 models (including 20-70% link dropout scenarios), exports them to
``edge-ai/models/*.onnx``, and writes ``edge-ai/models/profiles/baseline_default.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
import onnxruntime as ort
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from edgespace_ai.dsp.csi_processor import CSIProcessor, DEFAULT_NUM_SUBCARRIERS
from edgespace_ai.dsp.feature_extractor import FEATURE_DIM, FeatureExtractor
from edgespace_ai.dsp.link_fusion import FusedCSI, MAX_CLUSTER_LINKS

POSTURE_CLASSES = ("supine", "sitting", "standing", "exercising", "prone")


def _synthesize_fused_csi(
    *,
    rng: np.random.Generator,
    n_cycles: int,
    n_subcarriers: int,
    fs_hz: float,
    n_active_links: int,
    amp_base: float,
    resp_hz: float,
    cardiac_hz: float,
    hrv_ms: float,
    resp_depth: float,
    cardiac_depth: float,
    cadence_hz: float,
    cadence_depth: float,
    noise_sigma: float,
    snr_mean_db: float,
    subband_tilt: float,
    phase_jit: float,
    processor: CSIProcessor,
) -> FusedCSI:
    """Simulate ``n_active_links`` CSI links through ``CSIProcessor`` and fuse by SNR."""
    t = np.arange(n_cycles, dtype=np.float64) / fs_hz
    k = np.arange(n_subcarriers, dtype=np.float64)
    sub_shape = 1.0 + subband_tilt * np.linspace(-0.5, 0.5, n_subcarriers, dtype=np.float64)

    # Slight inter-beat interval modulation reflecting target HRV
    ibi_jitter = (hrv_ms / 1000.0) * 0.22 * np.sin(2.0 * np.pi * max(0.08, resp_hz * 0.8) * t)
    cardiac_phase = 2.0 * np.pi * cardiac_hz * (t + ibi_jitter)

    base_resp_wave = resp_depth * np.sin(2.0 * np.pi * resp_hz * t + rng.uniform(0.0, 2.0 * np.pi))
    base_card_wave = cardiac_depth * np.sin(cardiac_phase + rng.uniform(0.0, 2.0 * np.pi))
    base_cad_wave = (
        cadence_depth * np.sin(2.0 * np.pi * cadence_hz * t + rng.uniform(0.0, 2.0 * np.pi))
        if cadence_hz > 0.05 and cadence_depth > 0.0
        else np.zeros_like(t)
    )
    uncorrelated_links = bool(rng.random() < 0.45)

    processed_links: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, float]] = {}
    link_snrs: list[float] = []
    raw_weights: dict[tuple[int, int], float] = {}

    pair_idx = 0
    for tx in range(5):
        for rx in range(5):
            if tx == rx:
                continue
            if pair_idx >= n_active_links:
                break
            key = (tx, rx)
            pair_idx += 1

            link_gain = float(rng.uniform(0.90, 1.12))
            resp_w = float(rng.uniform(0.65, 1.25))
            card_w = float(rng.uniform(0.65, 1.25))
            cad_w = float(rng.uniform(0.75, 1.25))

            if uncorrelated_links:
                phi_r = float(rng.uniform(0.0, 2.0 * np.pi))
                phi_c = float(rng.uniform(0.0, 2.0 * np.pi))
                resp_wave = resp_depth * np.sin(2.0 * np.pi * resp_hz * t + phi_r)
                card_wave = cardiac_depth * np.sin(cardiac_phase + phi_c)
            else:
                resp_wave = base_resp_wave
                card_wave = base_card_wave

            amp_t = (
                amp_base * link_gain
                + resp_w * resp_wave
                + card_w * card_wave
                + cad_w * base_cad_wave
            )
            env_tk = amp_t[:, None] * sub_shape[None, :]

            # Linear STO/CFO per-cycle phase progression + subtle micro-Doppler
            sto_slope = float(rng.uniform(0.03, 0.12))
            cfo_t = rng.normal(0.0, 0.25, size=n_cycles)
            phase_tk = (
                sto_slope * k[None, :]
                + cfo_t[:, None]
                + phase_jit * np.sin(2.0 * np.pi * resp_hz * t)[:, None]
                + rng.normal(0.0, noise_sigma * 0.8, size=(n_cycles, n_subcarriers))
            )

            real_noise = rng.normal(0.0, noise_sigma, size=(n_cycles, n_subcarriers))
            complex_frames = (env_tk + real_noise) * np.exp(1j * phase_tk)

            link_snr = float(np.clip(snr_mean_db + rng.normal(0.0, 4.0), 8.0, 50.0))
            nf = -92.0
            rssi = float(nf + link_snr)
            proc = processor.process_complex_frames(
                complex_frames,
                rssi_dbm=rssi,
                noise_floor=nf,
                apply_hampel=True,
            )
            processed_links[key] = (proc.amplitude, proc.phase, proc.snr_db)
            link_snrs.append(proc.snr_db)
            raw_weights[key] = float(max(1e-3, 10.0 ** (min(proc.snr_db, 40.0) / 20.0)))
        if pair_idx >= n_active_links:
            break

    weight_sum = sum(raw_weights.values()) or 1.0
    link_weights = {key: w / weight_sum for key, w in raw_weights.items()}

    fused_amp = np.zeros((n_cycles, n_subcarriers), dtype=np.float64)
    fused_phase = np.zeros((n_cycles, n_subcarriers), dtype=np.float64)
    link_amp_1d: list[np.ndarray] = []
    link_motions: list[float] = []

    for key, (amp, phase, _) in processed_links.items():
        w = link_weights[key]
        fused_amp += w * amp
        fused_phase += w * phase
        series_1d = np.mean(amp, axis=1)
        link_amp_1d.append(series_1d)
        diff = np.diff(series_1d)
        link_motions.append(float(np.mean(diff ** 2)) if diff.size > 0 else 0.0)

    per_link_corr = 0.0
    if len(link_amp_1d) >= 2:
        mat = np.vstack(link_amp_1d)
        mat_c = mat - np.mean(mat, axis=1, keepdims=True)
        norms = np.linalg.norm(mat_c, axis=1)
        valid = norms > 1e-12
        if np.sum(valid) >= 2:
            normed = mat_c[valid] / norms[valid, None]
            corr_matrix = normed @ normed.T
            upper_idx = np.triu_indices_from(corr_matrix, k=1)
            per_link_corr = float(np.clip(np.mean(corr_matrix[upper_idx]), -1.0, 1.0))

    snr_arr = np.asarray(link_snrs, dtype=np.float64)
    return FusedCSI(
        amplitude_series=fused_amp,
        phase_series=fused_phase,
        link_weights=link_weights,
        active_links_count=len(processed_links),
        mean_snr_db=float(np.mean(snr_arr)),
        std_snr_db=float(np.std(snr_arr)),
        degradation_ratio=float(len(processed_links) / float(MAX_CLUSTER_LINKS)),
        per_link_motion=np.asarray(link_motions, dtype=np.float64),
        per_link_corr=per_link_corr,
        sample_rate_hz=fs_hz,
    )


def generate_synthetic_dataset(
    n_samples: int = 900,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate realistic 64-feature CSI vectors through the live DSP pipeline.

    Covers both subtle RF modulation (e.g., Central ``-mock-cluster=inproc``) and
    stronger motion/exercise modulation across 6..20 active links.
    Returns ``(X, y_posture, y_cadence, y_vitals, nominal_mask)``.
    """
    rng = np.random.default_rng(seed)
    processor = CSIProcessor(subcarriers=DEFAULT_NUM_SUBCARRIERS)
    extractor = FeatureExtractor()

    X = np.zeros((n_samples, FEATURE_DIM), dtype=np.float32)
    y_posture = np.empty(n_samples, dtype=object)
    y_cadence = np.zeros((n_samples, 1), dtype=np.float32)
    y_vitals = np.zeros((n_samples, 3), dtype=np.float32)
    nominal_mask = np.zeros(n_samples, dtype=bool)

    link_choices = (20, 16, 14, 12, 8, 6)
    link_probs = (0.30, 0.20, 0.15, 0.20, 0.08, 0.07)
    cycle_choices = (20, 25, 40, 50)

    for i in range(n_samples):
        posture_idx = i % len(POSTURE_CLASSES)
        posture = POSTURE_CLASSES[posture_idx]
        y_posture[i] = posture

        n_active_links = int(rng.choice(link_choices, p=link_probs))
        n_cycles = int(rng.choice(cycle_choices))
        fs_hz = float(rng.uniform(9.5, 10.5))
        snr_mean_db = float(rng.uniform(16.0, 48.0))

        # Span subtle mock-cluster/resting amplitudes (~0.002-0.01) up to stronger test/HW (~0.03-0.16)
        regime_subtle = rng.random() < 0.55

        if posture in ("supine", "prone"):
            resp_hz = float(rng.uniform(0.16, 0.34))
            hr_bpm = float(rng.uniform(52.0, 78.0))
            hrv_ms = float(rng.uniform(38.0, 88.0))
            cadence_hz = 0.0
            cadence_depth = 0.0
            amp_base = float(rng.uniform(0.85, 1.25)) if posture == "supine" else float(rng.uniform(0.80, 1.12))
            subband_tilt = float(rng.uniform(-0.08, 0.08))
            resp_depth = float(rng.uniform(0.0008, 0.012)) if regime_subtle else float(rng.uniform(0.03, 0.16))
            cardiac_depth = float(rng.uniform(0.0015, 0.007)) if regime_subtle else float(rng.uniform(0.012, 0.040))
            noise_sigma = float(resp_depth * rng.uniform(0.15, 0.55) + (0.0005 if regime_subtle else 0.0015))
            phase_jit = float(rng.uniform(0.0002, 0.015)) if regime_subtle else float(rng.uniform(0.005, 0.04))
            nominal_mask[i] = True
        elif posture == "sitting":
            resp_hz = float(rng.uniform(0.20, 0.36))
            hr_bpm = float(rng.uniform(62.0, 88.0))
            hrv_ms = float(rng.uniform(30.0, 72.0))
            cadence_hz = float(rng.uniform(0.0, 0.15))
            cadence_depth = float(rng.uniform(0.0005, 0.010))
            amp_base = float(rng.uniform(0.86, 1.40))
            subband_tilt = float(rng.uniform(-0.10, 0.12))
            resp_depth = float(rng.uniform(0.0010, 0.014)) if regime_subtle else float(rng.uniform(0.03, 0.14))
            cardiac_depth = float(rng.uniform(0.0018, 0.008)) if regime_subtle else float(rng.uniform(0.012, 0.042))
            noise_sigma = float(resp_depth * rng.uniform(0.15, 0.65) + (0.0008 if regime_subtle else 0.0025))
            phase_jit = float(rng.uniform(0.0002, 0.02)) if regime_subtle else float(rng.uniform(0.005, 0.06))
            nominal_mask[i] = True
        elif posture == "standing":
            resp_hz = float(rng.uniform(0.22, 0.38))
            hr_bpm = float(rng.uniform(70.0, 98.0))
            hrv_ms = float(rng.uniform(24.0, 62.0))
            cadence_hz = float(rng.uniform(0.10, 0.45))
            cadence_depth = float(rng.uniform(0.008, 0.035))
            amp_base = float(rng.uniform(1.20, 1.60))
            subband_tilt = float(rng.uniform(0.04, 0.18))
            resp_depth = float(rng.uniform(0.008, 0.025)) if regime_subtle else float(rng.uniform(0.03, 0.12))
            cardiac_depth = float(rng.uniform(0.004, 0.015)) if regime_subtle else float(rng.uniform(0.015, 0.045))
            noise_sigma = float(0.008 + 0.015 * (20 - n_active_links) / 14.0)
            phase_jit = float(rng.uniform(0.01, 0.08))
            nominal_mask[i] = True
        else:  # exercising
            resp_hz = float(rng.uniform(0.35, 0.60))
            hr_bpm = float(rng.uniform(112.0, 172.0))
            hrv_ms = float(rng.uniform(12.0, 34.0))
            cadence_hz = float(rng.uniform(1.05, 2.55))
            cadence_depth = float(rng.uniform(0.16, 0.42))
            amp_base = float(rng.uniform(1.55, 2.15))
            subband_tilt = float(rng.uniform(-0.22, 0.22))
            resp_depth = float(rng.uniform(0.05, 0.15))
            cardiac_depth = float(rng.uniform(0.02, 0.05))
            noise_sigma = float(rng.uniform(0.03, 0.09))
            phase_jit = float(rng.uniform(0.08, 0.25))
            nominal_mask[i] = False

        fused = _synthesize_fused_csi(
            rng=rng,
            n_cycles=n_cycles,
            n_subcarriers=DEFAULT_NUM_SUBCARRIERS,
            fs_hz=fs_hz,
            n_active_links=n_active_links,
            amp_base=amp_base,
            resp_hz=resp_hz,
            cardiac_hz=hr_bpm / 60.0,
            hrv_ms=hrv_ms,
            resp_depth=resp_depth,
            cardiac_depth=cardiac_depth,
            cadence_hz=cadence_hz,
            cadence_depth=cadence_depth,
            noise_sigma=noise_sigma,
            snr_mean_db=snr_mean_db,
            subband_tilt=subband_tilt,
            phase_jit=phase_jit,
            processor=processor,
        )
        extracted = extractor.extract(fused)
        X[i] = extracted.vector
        y_cadence[i, 0] = cadence_hz
        y_vitals[i, 0] = resp_hz
        y_vitals[i, 1] = hr_bpm
        y_vitals[i, 2] = hrv_ms

    return X, y_posture, y_cadence, y_vitals, nominal_mask


def _export_skl_onnx(model: object, out_path: Path, *, options: dict | None = None, opset: dict | None = None) -> None:
    initial_type = [("float_input", FloatTensorType([None, FEATURE_DIM]))]
    onnx_model = convert_sklearn(
        model,
        initial_types=initial_type,
        options=options,
        target_opset=opset or {"": 15, "ai.onnx.ml": 3},
    )
    out_path.write_bytes(onnx_model.SerializeToString())


def _export_mlp_onnx(
    mlp: MLPRegressor,
    out_path: Path,
    *,
    scaler: Optional[StandardScaler] = None,
    out_scaler: Optional[StandardScaler] = None,
    opset_version: int = 15,
) -> None:
    """Export an sklearn StandardScaler + MLPRegressor directly with exact [N, out_dim] shape."""
    out_dim = mlp.coefs_[-1].shape[1]
    inits = []
    nodes = []
    curr = "float_input"

    if scaler is not None:
        mean_arr = np.asarray(scaler.mean_, dtype=np.float32)
        scale_arr = np.where(np.asarray(scaler.scale_, dtype=np.float32) > 1e-9, scaler.scale_, 1.0).astype(np.float32)
        inits.append(numpy_helper.from_array(mean_arr, name="scaler_mean"))
        inits.append(numpy_helper.from_array(scale_arr, name="scaler_scale"))
        nodes.append(helper.make_node("Sub", [curr, "scaler_mean"], ["centered"]))
        nodes.append(helper.make_node("Div", ["centered", "scaler_scale"], ["scaled"]))
        curr = "scaled"

    n_layers = len(mlp.coefs_)
    for idx, (w, b) in enumerate(zip(mlp.coefs_, mlp.intercepts_)):
        is_last = idx == (n_layers - 1)
        w_arr = np.asarray(w, dtype=np.float32)
        b_arr = np.asarray(b, dtype=np.float32)
        if is_last and out_scaler is not None:
            y_scale = np.where(np.asarray(out_scaler.scale_, dtype=np.float32) > 1e-9, out_scaler.scale_, 1.0).astype(np.float32)
            y_mean = np.asarray(out_scaler.mean_, dtype=np.float32)
            w_arr = (w_arr * y_scale[None, :]).astype(np.float32)
            b_arr = (b_arr * y_scale + y_mean).astype(np.float32)

        w_name = f"W_{idx}"
        b_name = f"b_{idx}"
        inits.append(numpy_helper.from_array(w_arr, name=w_name))
        inits.append(numpy_helper.from_array(b_arr, name=b_name))

        mm_out = f"mm_{idx}"
        add_out = "variable" if is_last else f"pre_act_{idx}"
        nodes.append(helper.make_node("MatMul", [curr, w_name], [mm_out]))
        nodes.append(helper.make_node("Add", [mm_out, b_name], [add_out]))

        if not is_last:
            act_out = f"act_{idx}"
            if mlp.activation == "tanh":
                nodes.append(helper.make_node("Tanh", [add_out], [act_out]))
            elif mlp.activation == "logistic":
                nodes.append(helper.make_node("Sigmoid", [add_out], [act_out]))
            else:
                nodes.append(helper.make_node("Relu", [add_out], [act_out]))
            curr = act_out
        else:
            curr = add_out

    graph = helper.make_graph(
        nodes=nodes,
        name=out_path.stem,
        inputs=[helper.make_tensor_value_info("float_input", TensorProto.FLOAT, [None, FEATURE_DIM])],
        outputs=[helper.make_tensor_value_info("variable", TensorProto.FLOAT, [None, out_dim])],
        initializer=inits,
    )
    model_def = helper.make_model(graph, opset_imports=[helper.make_opsetid("", opset_version)])
    model_def.ir_version = 8
    onnx.checker.check_model(model_def)
    out_path.write_bytes(model_def.SerializeToString())


def _verify_onnx(
    path: Path,
    X_sample: np.ndarray,
    sk_model: Optional[object] = None,
    *,
    y_scaler: Optional[StandardScaler] = None,
    atol: float = 1e-2,
) -> None:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {in_name: X_sample.astype(np.float32)})
    assert len(outputs) >= 1
    if sk_model is not None and hasattr(sk_model, "predict"):
        ref = np.asarray(sk_model.predict(X_sample), dtype=np.float32)
        if y_scaler is not None:
            ref = np.asarray(y_scaler.inverse_transform(ref), dtype=np.float32)
        got = np.asarray(outputs[0], dtype=np.float32)
        if ref.ndim == 1 and got.ndim == 2 and got.shape[1] == 1:
            ref = ref.reshape(-1, 1)
        if np.issubdtype(ref.dtype, np.number) and np.issubdtype(got.dtype, np.number):
            assert got.shape == ref.shape, f"shape mismatch {got.shape} != {ref.shape}"
            assert np.allclose(got, ref, atol=atol, rtol=1e-3), f"value mismatch on {path.name}"
    print(f"verified {path.name}: outputs={[np.asarray(o).shape for o in outputs]}")


def build_all_models(models_dir: Path, seed: int = 42) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir = models_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    X, y_posture, y_cadence, y_vitals, nominal_mask = generate_synthetic_dataset(
        n_samples=600,
        seed=seed,
    )
    print(f"generated {X.shape[0]} DSP feature vectors in {time.perf_counter() - t_start:.2f}s")
    X_probe = X[:4]

    # 1. posture_cls.onnx
    rf_posture = RandomForestClassifier(n_estimators=40, max_depth=10, random_state=seed)
    posture_pipe = Pipeline([("scaler", StandardScaler()), ("clf", rf_posture)])
    posture_pipe.fit(X, y_posture)
    posture_path = models_dir / "posture_cls.onnx"
    _export_skl_onnx(posture_pipe, posture_path, options={id(rf_posture): {"zipmap": False}})
    _verify_onnx(posture_path, X_probe)

    # 2. exercise_cadence.onnx
    cad_scaler = StandardScaler()
    X_cad_scaled = cad_scaler.fit_transform(X)
    cad_mlp = MLPRegressor(
        hidden_layer_sizes=(32, 16),
        max_iter=1200,
        early_stopping=True,
        learning_rate_init=2e-3,
        random_state=seed,
    )
    cad_mlp.fit(X_cad_scaled, y_cadence.ravel())
    cadence_pipe = Pipeline([("scaler", cad_scaler), ("reg", cad_mlp)])
    cadence_path = models_dir / "exercise_cadence.onnx"
    _export_mlp_onnx(cad_mlp, cadence_path, scaler=cad_scaler)
    _verify_onnx(cadence_path, X_probe, cadence_pipe)

    # 3. vitals_reg.onnx (exact [N, 3] output: resp_hz, hr_bpm, hrv_ms)
    vit_scaler = StandardScaler()
    X_vit_scaled = vit_scaler.fit_transform(X)
    vit_y_scaler = StandardScaler()
    y_vit_scaled = vit_y_scaler.fit_transform(y_vitals)
    vit_mlp = MLPRegressor(
        hidden_layer_sizes=(64, 32),
        max_iter=1500,
        early_stopping=True,
        learning_rate_init=2e-3,
        random_state=seed,
    )
    vit_mlp.fit(X_vit_scaled, y_vit_scaled)
    vitals_pipe = Pipeline([("scaler", vit_scaler), ("reg", vit_mlp)])
    vitals_path = models_dir / "vitals_reg.onnx"
    _export_mlp_onnx(vit_mlp, vitals_path, scaler=vit_scaler, out_scaler=vit_y_scaler)
    _verify_onnx(vitals_path, X_probe, vitals_pipe, y_scaler=vit_y_scaler, atol=5e-2)

    # 4. baseline_ae_default.onnx (operates in z-score normalized space, exact [N, 64] output)
    X_nom = X[nominal_mask]
    nom_mean = np.mean(X_nom, axis=0).astype(np.float32)
    nom_std = np.maximum(np.std(X_nom, axis=0), 1e-3).astype(np.float32)
    X_nom_norm = np.clip((X_nom - nom_mean) / nom_std, -6.0, 6.0).astype(np.float32)

    ae_model = MLPRegressor(
        hidden_layer_sizes=(32, 16, 32),
        max_iter=1500,
        early_stopping=True,
        learning_rate_init=2e-3,
        random_state=seed,
    )
    ae_model.fit(X_nom_norm, X_nom_norm)
    ae_path = models_dir / "baseline_ae_default.onnx"
    _export_mlp_onnx(ae_model, ae_path, scaler=None)
    _verify_onnx(ae_path, X_nom_norm[:4], ae_model)

    # 5. isolation_forest.onnx
    iforest_pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("iforest", IsolationForest(n_estimators=64, contamination=0.05, random_state=seed)),
        ]
    )
    iforest_pipe.fit(X_nom)
    iforest_path = models_dir / "isolation_forest.onnx"
    _export_skl_onnx(iforest_pipe, iforest_path, opset={"": 15, "ai.onnx.ml": 3})
    _verify_onnx(iforest_path, X_probe, iforest_pipe)

    # Persist default baseline stats JSON alongside ONNX models
    default_profile = {
        "crew_id": "default",
        "mean": [float(v) for v in nom_mean.tolist()],
        "std": [float(v) for v in nom_std.tolist()],
        "threshold": 0.75,
        "sample_count": int(X_nom.shape[0]),
        "updated_at_us": time.time_ns() // 1000,
        "model_path": str(ae_path.name),
    }
    (profiles_dir / "baseline_default.json").write_text(
        json.dumps(default_profile, indent=2),
        encoding="utf-8",
    )
    print(f"wrote default baseline profile: {profiles_dir / 'baseline_default.json'}")


def main() -> None:
    default_models_dir = Path(__file__).resolve().parent.parent / "models"
    parser = argparse.ArgumentParser(description="Train and export Edge Space AI ONNX models.")
    parser.add_argument("--models-dir", type=Path, default=default_models_dir)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    build_all_models(args.models_dir, seed=args.seed)


if __name__ == "__main__":
    main()
