"""SNR-weighted spatial fusion across up to 20 (tx, rx) CSI links with N+1 degradation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .csi_processor import CSIProcessor, DEFAULT_NUM_SUBCARRIERS, iq_to_complex, reshape_cycles
from .window_buffer import BufferedWindow

MAX_CLUSTER_LINKS = 20  # 5 ESP32-S3 nodes -> 5 * 4 directed links


@dataclass
class FusedCSI:
    """Spatially fused multi-link CSI time series and topology quality metrics."""

    amplitude_series: np.ndarray   # shape (T, K)
    phase_series: np.ndarray       # shape (T, K)
    link_weights: dict[tuple[int, int], float]
    active_links_count: int
    mean_snr_db: float
    std_snr_db: float
    degradation_ratio: float       # active_links_count / 20.0
    per_link_motion: np.ndarray    # motion energy per active link
    per_link_corr: float           # mean pairwise temporal correlation across links
    sample_rate_hz: float


class LinkFusion:
    """Fuses multi-link CSI time series weighted by link SNR and quality hints.

    Supports full 20-link operation as well as graceful N+1 degradation (12, 6, or fewer links).
    """

    def __init__(self, max_links: int = MAX_CLUSTER_LINKS) -> None:
        self.max_links = max_links

    def fuse_windows(
        self,
        windows: Sequence[BufferedWindow],
        processor: Optional[CSIProcessor] = None,
        *,
        sample_rate_hz: float = 10.0,
    ) -> Optional[FusedCSI]:
        """Fuse ordered ``BufferedWindow`` snapshots into a single SNR-weighted CSI series."""
        if not windows:
            return None

        proc = processor or CSIProcessor()

        per_link_frames: dict[tuple[int, int], list[np.ndarray]] = defaultdict(list)
        per_link_rssi: dict[tuple[int, int], list[float]] = defaultdict(list)
        per_link_nf: dict[tuple[int, int], list[float]] = defaultdict(list)
        per_link_qual: dict[tuple[int, int], list[float]] = defaultdict(list)

        for win in windows:
            qualities = win.quality_per_link
            cache = getattr(win, "decoded_cache", None)
            for idx, link in enumerate(win.links):
                if not link.iq_samples:
                    continue
                key = (link.tx_node_id, link.rx_node_id)
                frames = cache.get(key) if cache is not None else None
                if frames is None:
                    csi_1d = iq_to_complex(link.iq_samples)
                    frames = reshape_cycles(csi_1d, proc.subcarriers)
                    if frames.shape[0] == 0 or frames.shape[1] == 0:
                        continue
                    if cache is not None:
                        cache[key] = frames
                per_link_frames[key].append(frames)
                per_link_rssi[key].append(float(link.rssi_dbm))
                per_link_nf[key].append(float(link.noise_floor))
                if qualities is not None and idx < len(qualities):
                    per_link_qual[key].append(float(np.clip(qualities[idx], 0.05, 1.0)))

        if not per_link_frames:
            return None

        processed_links: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, float]] = {}
        raw_weights: dict[tuple[int, int], float] = {}
        snr_values: list[float] = []

        for key, frame_chunks in per_link_frames.items():
            target_k = max(chunk.shape[1] for chunk in frame_chunks)
            normalized_chunks = [
                _align_subcarriers(chunk, target_k) for chunk in frame_chunks
            ]
            combined = np.vstack(normalized_chunks)
            mean_rssi = float(np.mean(per_link_rssi[key]))
            mean_nf = float(np.mean(per_link_nf[key]))
            processed = proc.process_complex_frames(
                combined,
                rssi_dbm=mean_rssi,
                noise_floor=mean_nf,
                apply_hampel=True,
            )
            processed_links[key] = (processed.amplitude, processed.phase, processed.snr_db)
            snr_values.append(processed.snr_db)

            qual_factor = float(np.mean(per_link_qual[key])) if per_link_qual[key] else 1.0
            # Positive linear SNR-derived weight (clipped dB range mapped to >= 0.05)
            snr_weight = float(np.clip(processed.snr_db + 5.0, 0.5, 45.0))
            raw_weights[key] = snr_weight * qual_factor

        total_weight = sum(raw_weights.values())
        if total_weight <= 0.0:
            uniform = 1.0 / len(raw_weights)
            norm_weights = {k: uniform for k in raw_weights}
        else:
            norm_weights = {k: w / total_weight for k, w in raw_weights.items()}

        target_t = max(amp.shape[0] for amp, _, _ in processed_links.values())
        target_k = max(amp.shape[1] for amp, _, _ in processed_links.values()) or DEFAULT_NUM_SUBCARRIERS

        fused_amp = np.zeros((target_t, target_k), dtype=np.float64)
        fused_phase = np.zeros((target_t, target_k), dtype=np.float64)
        per_link_motion_list: list[float] = []
        link_envelopes: list[np.ndarray] = []

        for key, (amp, phase, _) in processed_links.items():
            amp_aligned = _align_time_and_subcarriers(amp, target_t, target_k)
            phase_aligned = _align_time_and_subcarriers(phase, target_t, target_k)
            w = norm_weights[key]
            fused_amp += w * amp_aligned
            fused_phase += w * phase_aligned

            if amp_aligned.shape[0] >= 2:
                motion = float(np.mean(np.diff(amp_aligned, axis=0) ** 2))
            else:
                motion = 0.0
            per_link_motion_list.append(motion)
            link_envelopes.append(np.mean(amp_aligned, axis=1))

        per_link_corr = _mean_pairwise_correlation(link_envelopes)
        active_count = len(processed_links)

        return FusedCSI(
            amplitude_series=fused_amp,
            phase_series=fused_phase,
            link_weights=norm_weights,
            active_links_count=active_count,
            mean_snr_db=float(np.mean(snr_values)) if snr_values else 0.0,
            std_snr_db=float(np.std(snr_values)) if len(snr_values) > 1 else 0.0,
            degradation_ratio=float(min(1.0, active_count / float(self.max_links))),
            per_link_motion=np.asarray(per_link_motion_list, dtype=np.float64),
            per_link_corr=per_link_corr,
            sample_rate_hz=sample_rate_hz,
        )


def _align_subcarriers(mat: np.ndarray, target_k: int) -> np.ndarray:
    cur_k = mat.shape[1]
    if cur_k == target_k:
        return mat
    if cur_k > target_k:
        return mat[:, :target_k]
    pad_width = target_k - cur_k
    return np.pad(mat, ((0, 0), (0, pad_width)), mode="edge")


def _align_time_and_subcarriers(mat: np.ndarray, target_t: int, target_k: int) -> np.ndarray:
    aligned = _align_subcarriers(mat, target_k)
    cur_t = aligned.shape[0]
    if cur_t == target_t:
        return aligned
    if cur_t > target_t:
        return aligned[-target_t:, :]
    pad_rows = target_t - cur_t
    return np.pad(aligned, ((pad_rows, 0), (0, 0)), mode="edge")


def _mean_pairwise_correlation(series_list: list[np.ndarray]) -> float:
    if len(series_list) < 2:
        return 1.0 if len(series_list) == 1 else 0.0
    mat = np.vstack(series_list)
    if mat.shape[1] < 3:
        return 0.0
    stds = np.std(mat, axis=1)
    valid = stds > 1e-9
    if np.sum(valid) < 2:
        return 0.0
    corr = np.corrcoef(mat[valid])
    upper = corr[np.triu_indices_from(corr, k=1)]
    finite = upper[np.isfinite(upper)]
    return float(np.mean(finite)) if finite.size > 0 else 0.0
