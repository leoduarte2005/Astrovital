"""Fixed 64-feature extractor using Butterworth bandpass filters and FFT/Welch PSD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal, stats

from .link_fusion import FusedCSI

FEATURE_DIM = 64

FEATURE_NAMES: tuple[str, ...] = (
    # 0..11: Global amplitude & phase stats (12)
    "amp_mean",
    "amp_std",
    "amp_median",
    "amp_iqr",
    "amp_skew",
    "amp_kurtosis",
    "phase_mean",
    "phase_std",
    "phase_median",
    "phase_iqr",
    "phase_time_diff_mean",
    "phase_sub_diff_mean",
    # 12..21: Respiration band 0.1-0.5 Hz (10)
    "resp_rms",
    "resp_ptp",
    "resp_zcr",
    "resp_dom_freq_hz",
    "resp_peak_power",
    "resp_centroid_hz",
    "resp_spectral_entropy",
    "resp_band_snr",
    "resp_phase_dom_freq_hz",
    "resp_phase_peak_power",
    # 22..31: Cardiac band 0.8-2.5 Hz (10)
    "cardiac_rms",
    "cardiac_ptp",
    "cardiac_dom_freq_hz",
    "cardiac_peak_power",
    "cardiac_centroid_hz",
    "cardiac_spectral_entropy",
    "cardiac_band_snr",
    "cardiac_rmssd_proxy",
    "cardiac_sdnn_proxy",
    "cardiac_phase_dom_freq_hz",
    # 32..41: Motion energy & Doppler variance (10)
    "motion_total_energy",
    "motion_max_delta",
    "motion_hf_energy",
    "doppler_bandwidth_hz",
    "doppler_phase_variance",
    "cadence_peak_freq_hz",
    "cadence_peak_power",
    "link_motion_mean",
    "link_motion_std",
    "link_motion_max",
    # 42..53: Subcarrier bands & spatial link topology (12)
    "subband_0_energy",
    "subband_1_energy",
    "subband_2_energy",
    "subband_3_energy",
    "subband_4_energy",
    "subband_5_energy",
    "subband_6_energy",
    "subband_7_energy",
    "active_links_ratio",
    "mean_snr_db",
    "std_snr_db",
    "spatial_link_corr",
    # 54..63: Cross-band & multi-cycle dynamics (10)
    "resp_cardiac_power_ratio",
    "motion_total_ratio",
    "amp_temporal_slope",
    "phase_temporal_slope",
    "spectral_flatness",
    "crest_factor",
    "amp_p10",
    "amp_p90",
    "phase_std_p10",
    "phase_std_p90",
)

assert len(FEATURE_NAMES) == FEATURE_DIM


@dataclass
class ExtractedFeatures:
    """Fixed 64-element float32 feature vector plus DSP physical estimates."""

    vector: np.ndarray       # shape (64,), float32
    resp_hz_est: float
    hr_bpm_est: float
    hrv_ms_est: float
    motion_energy: float
    cadence_hz_est: float


class FeatureExtractor:
    """Extracts the 64-feature physiological/motion vector from fused CSI series."""

    RESP_BAND = (0.1, 0.5)
    CARDIAC_BAND = (0.8, 2.5)
    CADENCE_BAND = (0.5, 3.0)

    def extract(self, fused: FusedCSI) -> ExtractedFeatures:
        """Compute the fixed 64-feature vector from a ``FusedCSI`` object."""
        amp = np.asarray(fused.amplitude_series, dtype=np.float64)
        phase = np.asarray(fused.phase_series, dtype=np.float64)
        fs = float(max(2.0, fused.sample_rate_hz))

        # Collapse subcarriers into 1D time signals (variance-weighted or mean across subcarriers)
        amp_1d = np.mean(amp, axis=1) if amp.size > 0 else np.zeros(1, dtype=np.float64)
        phase_1d = np.std(phase, axis=1) if phase.size > 0 else np.zeros(1, dtype=np.float64)

        # Detrend DC component for spectral analysis
        amp_ac = amp_1d - np.mean(amp_1d)
        phase_ac = phase_1d - np.mean(phase_1d)

        # 1. Global amplitude & phase statistics (12)
        amp_q75, amp_q25 = np.percentile(amp, [75, 25]) if amp.size > 0 else (0.0, 0.0)
        phase_q75, phase_q25 = np.percentile(phase, [75, 25]) if phase.size > 0 else (0.0, 0.0)

        amp_skew = float(stats.skew(amp.ravel(), bias=False)) if amp.size >= 3 and np.std(amp) > 1e-9 else 0.0
        amp_kurt = float(stats.kurtosis(amp.ravel(), bias=False)) if amp.size >= 4 and np.std(amp) > 1e-9 else 0.0

        phase_t_diff = float(np.mean(np.abs(np.diff(phase, axis=0)))) if phase.shape[0] >= 2 else 0.0
        phase_k_diff = float(np.mean(np.abs(np.diff(phase, axis=1)))) if phase.shape[1] >= 2 else 0.0

        global_feats = [
            float(np.mean(amp)),
            float(np.std(amp)),
            float(np.median(amp)),
            float(amp_q75 - amp_q25),
            amp_skew,
            amp_kurt,
            float(np.mean(phase)),
            float(np.std(phase)),
            float(np.median(phase)),
            float(phase_q75 - phase_q25),
            phase_t_diff,
            phase_k_diff,
        ]

        # 2. Respiration band (0.1 - 0.5 Hz) (10)
        resp_sig = _bandpass_filter(amp_ac, self.RESP_BAND[0], self.RESP_BAND[1], fs)
        resp_phase_sig = _bandpass_filter(phase_ac, self.RESP_BAND[0], self.RESP_BAND[1], fs)
        freqs, psd_amp = _compute_psd(amp_ac, fs)
        freqs_p, psd_phase = _compute_psd(phase_ac, fs)

        resp_stats = _band_spectral_stats(freqs, psd_amp, *self.RESP_BAND, default_freq=0.25)
        resp_phase_stats = _band_spectral_stats(freqs_p, psd_phase, *self.RESP_BAND, default_freq=0.25)
        resp_feats = [
            float(np.sqrt(np.mean(resp_sig ** 2))),
            float(np.ptp(resp_sig)) if resp_sig.size > 0 else 0.0,
            _zero_crossing_rate(resp_sig, fs),
            resp_stats["dom_freq"],
            resp_stats["peak_power"],
            resp_stats["centroid"],
            resp_stats["entropy"],
            resp_stats["band_snr"],
            resp_phase_stats["dom_freq"],
            resp_phase_stats["peak_power"],
        ]

        # 3. Cardiac band (0.8 - 2.5 Hz) (10)
        cardiac_sig = _bandpass_filter(amp_ac, self.CARDIAC_BAND[0], self.CARDIAC_BAND[1], fs)
        cardiac_stats = _band_spectral_stats(freqs, psd_amp, *self.CARDIAC_BAND, default_freq=1.15)
        cardiac_phase_stats = _band_spectral_stats(freqs_p, psd_phase, *self.CARDIAC_BAND, default_freq=1.15)
        rmssd_ms, sdnn_ms = _estimate_hrv_proxies(cardiac_sig, fs)

        cardiac_feats = [
            float(np.sqrt(np.mean(cardiac_sig ** 2))),
            float(np.ptp(cardiac_sig)) if cardiac_sig.size > 0 else 0.0,
            cardiac_stats["dom_freq"],
            cardiac_stats["peak_power"],
            cardiac_stats["centroid"],
            cardiac_stats["entropy"],
            cardiac_stats["band_snr"],
            rmssd_ms,
            sdnn_ms,
            cardiac_phase_stats["dom_freq"],
        ]

        # 4. Motion energy & Doppler variance (10)
        amp_diff = np.diff(amp, axis=0) if amp.shape[0] >= 2 else np.zeros((1, amp.shape[1]))
        motion_total_energy = float(np.mean(amp_diff ** 2))
        motion_max_delta = float(np.max(np.abs(amp_diff))) if amp_diff.size > 0 else 0.0

        hf_mask = freqs > 2.5
        motion_hf_energy = float(np.sum(psd_amp[hf_mask])) if np.any(hf_mask) else 0.0

        _, psd_diff = _compute_psd(np.mean(amp_diff, axis=1), fs)
        doppler_bw = _spectral_bandwidth(freqs, psd_diff)
        phase_diff = np.diff(phase, axis=0) if phase.shape[0] >= 2 else np.zeros((1, phase.shape[1]))
        doppler_phase_var = float(np.var(phase_diff))

        cadence_stats = _band_spectral_stats(freqs, psd_amp, *self.CADENCE_BAND, default_freq=0.0)
        link_motion = fused.per_link_motion if fused.per_link_motion.size > 0 else np.zeros(1)

        motion_feats = [
            motion_total_energy,
            motion_max_delta,
            motion_hf_energy,
            doppler_bw,
            doppler_phase_var,
            cadence_stats["dom_freq"],
            cadence_stats["peak_power"],
            float(np.mean(link_motion)),
            float(np.std(link_motion)),
            float(np.max(link_motion)),
        ]

        # 5. Subcarrier bands (8) & spatial topology (4) -> 12
        sub_energies = _subcarrier_band_energies(amp, n_bands=8)
        topo_feats = [
            float(fused.degradation_ratio),
            float(fused.mean_snr_db),
            float(fused.std_snr_db),
            float(fused.per_link_corr),
        ]

        # 6. Cross-band & multi-cycle dynamics (10)
        total_psd = float(np.sum(psd_amp)) + 1e-12
        resp_cardiac_ratio = resp_stats["band_power"] / (cardiac_stats["band_power"] + 1e-12)
        motion_total_ratio = motion_total_energy / (float(np.mean(amp ** 2)) + 1e-12)

        amp_slope = _linear_slope(amp_1d)
        phase_slope = _linear_slope(phase_1d)
        spec_flatness = _spectral_flatness(psd_amp)
        rms_amp = float(np.sqrt(np.mean(amp_ac ** 2))) + 1e-12
        crest_factor = float(np.max(np.abs(amp_ac))) / rms_amp if amp_ac.size > 0 else 0.0

        amp_p10, amp_p90 = np.percentile(amp, [10, 90]) if amp.size > 0 else (0.0, 0.0)
        phase_std_t = np.std(phase, axis=1) if phase.size > 0 else np.zeros(1)
        phase_p10, phase_p90 = np.percentile(phase_std_t, [10, 90])

        dynamics_feats = [
            float(resp_cardiac_ratio),
            float(motion_total_ratio),
            amp_slope,
            phase_slope,
            spec_flatness,
            crest_factor,
            float(amp_p10),
            float(amp_p90),
            float(phase_p10),
            float(phase_p90),
        ]

        raw_vector = np.asarray(
            global_feats
            + resp_feats
            + cardiac_feats
            + motion_feats
            + sub_energies
            + topo_feats
            + dynamics_feats,
            dtype=np.float32,
        )
        vector = np.nan_to_num(raw_vector, nan=0.0, posinf=0.0, neginf=0.0)

        return ExtractedFeatures(
            vector=vector,
            resp_hz_est=float(np.clip(resp_stats["dom_freq"], 0.1, 0.5)),
            hr_bpm_est=float(np.clip(cardiac_stats["dom_freq"] * 60.0, 48.0, 150.0)),
            hrv_ms_est=float(np.clip(rmssd_ms, 10.0, 150.0)),
            motion_energy=motion_total_energy,
            cadence_hz_est=float(cadence_stats["dom_freq"]),
        )


def _bandpass_filter(x: np.ndarray, low_hz: float, high_hz: float, fs_hz: float, order: int = 2) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if arr.size < 4:
        return arr.copy()

    nyq = 0.5 * fs_hz
    low = max(1e-3, min(low_hz / nyq, 0.90))
    high = max(low + 1e-3, min(high_hz / nyq, 0.95))
    if low >= high:
        return arr.copy()

    sos = signal.butter(order, [low, high], btype="bandpass", output="sos")
    padlen = 3 * (2 * len(sos) + 1)
    if arr.size > padlen:
        return signal.sosfiltfilt(sos, arr)
    return signal.sosfilt(sos, arr)


def _compute_psd(x: np.ndarray, fs_hz: float) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(x, dtype=np.float64)
    n = arr.size
    if n < 4:
        return np.array([0.0, fs_hz * 0.5]), np.zeros(2, dtype=np.float64)

    nfft = max(64, int(2 ** np.ceil(np.log2(max(n, 32)))))
    nperseg = min(n, 64)
    freqs, psd = signal.welch(
        arr,
        fs=fs_hz,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        nfft=nfft,
        detrend="constant",
    )
    return freqs, np.maximum(psd, 0.0)


def _band_spectral_stats(
    freqs: np.ndarray,
    psd: np.ndarray,
    low_hz: float,
    high_hz: float,
    *,
    default_freq: float,
) -> dict[str, float]:
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not np.any(mask):
        return {
            "dom_freq": default_freq,
            "peak_power": 0.0,
            "band_power": 0.0,
            "centroid": default_freq,
            "entropy": 0.0,
            "band_snr": 0.0,
        }

    band_freqs = freqs[mask]
    band_psd = psd[mask]
    band_power = float(np.sum(band_psd))
    if band_power <= 1e-15:
        return {
            "dom_freq": default_freq,
            "peak_power": 0.0,
            "band_power": 0.0,
            "centroid": default_freq,
            "entropy": 0.0,
            "band_snr": 0.0,
        }

    peak_idx = int(np.argmax(band_psd))
    dom_freq = float(band_freqs[peak_idx])
    peak_power = float(band_psd[peak_idx])
    centroid = float(np.sum(band_freqs * band_psd) / band_power)

    prob = band_psd / band_power
    prob_nz = prob[prob > 1e-15]
    entropy = float(-np.sum(prob_nz * np.log2(prob_nz)) / max(1.0, np.log2(len(band_psd))))

    total_power = float(np.sum(psd))
    noise_power = max(1e-15, total_power - band_power)
    band_snr = float(10.0 * np.log10(max(band_power, 1e-15) / noise_power))

    return {
        "dom_freq": dom_freq,
        "peak_power": peak_power,
        "band_power": band_power,
        "centroid": centroid,
        "entropy": entropy,
        "band_snr": band_snr,
    }


def _zero_crossing_rate(x: np.ndarray, fs_hz: float) -> float:
    if x.size < 2:
        return 0.0
    crossings = np.sum(np.diff(np.signbit(x)))
    duration_s = max(1e-6, (x.size - 1) / fs_hz)
    return float(crossings / duration_s)


def _estimate_hrv_proxies(cardiac_sig: np.ndarray, fs_hz: float) -> tuple[float, float]:
    if cardiac_sig.size < 6:
        return 42.0, 38.0
    min_dist = max(1, int(0.35 * fs_hz))
    peaks, _ = signal.find_peaks(cardiac_sig, distance=min_dist)
    if peaks.size < 3:
        return 42.0, 38.0

    # Sub-sample parabolic interpolation reduces 100 ms quantization at fs=10 Hz.
    refined = peaks.astype(np.float64)
    n = cardiac_sig.size
    for idx, p in enumerate(peaks):
        if 0 < p < n - 1:
            y0, y1, y2 = cardiac_sig[p - 1], cardiac_sig[p], cardiac_sig[p + 1]
            denom = 2.0 * (y0 - 2.0 * y1 + y2)
            if abs(denom) > 1e-12:
                delta = float(np.clip((y0 - y2) / denom, -0.5, 0.5))
                refined[idx] = float(p) + delta

    ibi_ms = np.diff(refined) * (1000.0 / fs_hz)
    sdnn = float(np.std(ibi_ms))
    rmssd = float(np.sqrt(np.mean(np.diff(ibi_ms) ** 2))) if ibi_ms.size >= 2 else sdnn
    return float(np.clip(rmssd, 5.0, 200.0)), float(np.clip(sdnn, 5.0, 200.0))


def _spectral_bandwidth(freqs: np.ndarray, psd: np.ndarray) -> float:
    total = float(np.sum(psd))
    if total <= 1e-15:
        return 0.0
    centroid = float(np.sum(freqs * psd) / total)
    return float(np.sqrt(np.sum(((freqs - centroid) ** 2) * psd) / total))


def _subcarrier_band_energies(amp: np.ndarray, n_bands: int = 8) -> list[float]:
    if amp.size == 0:
        return [0.0] * n_bands
    sub_energy = np.mean(amp ** 2, axis=0)
    chunks = np.array_split(sub_energy, n_bands)
    return [float(np.mean(c)) if c.size > 0 else 0.0 for c in chunks]


def _linear_slope(y: np.ndarray) -> float:
    if y.size < 2:
        return 0.0
    x = np.arange(y.size, dtype=np.float64)
    x_c = x - np.mean(x)
    denom = float(np.dot(x_c, x_c))
    if denom <= 0.0:
        return 0.0
    return float(np.dot(x_c, y - np.mean(y)) / denom)


def _spectral_flatness(psd: np.ndarray) -> float:
    pos = psd[psd > 1e-15]
    if pos.size == 0:
        return 0.0
    geo_mean = float(np.exp(np.mean(np.log(pos))))
    arith_mean = float(np.mean(pos))
    return float(geo_mean / max(arith_mean, 1e-15))
