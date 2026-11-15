"""Single-link CSI DSP pipeline: I/Q decoding, phase unwrap, STO/CFO removal, and Hampel filter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..ipc.protocol import IQSample

DEFAULT_NUM_SUBCARRIERS = 56


@dataclass
class ProcessedCSI:
    """Sanitized amplitude and phase matrices for one CSI link."""

    amplitude: np.ndarray  # shape (T, K), float64
    phase: np.ndarray      # shape (T, K), float64
    snr_db: float


def iq_to_complex(iq_samples: Sequence[IQSample | tuple[float, float]] | np.ndarray) -> np.ndarray:
    """Convert a sequence of IQSample or (real, imag) pairs into a 1D complex128 array."""
    if isinstance(iq_samples, np.ndarray):
        if np.iscomplexobj(iq_samples):
            return np.asarray(iq_samples, dtype=np.complex128)
        arr = np.asarray(iq_samples, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 2:
            return arr[:, 0] + 1j * arr[:, 1]
        raise ValueError(f"unsupported ndarray shape for IQ conversion: {arr.shape}")

    if not iq_samples:
        return np.empty(0, dtype=np.complex128)

    first = iq_samples[0]
    if isinstance(first, IQSample):
        real = np.fromiter((s.real for s in iq_samples), dtype=np.float64, count=len(iq_samples))
        imag = np.fromiter((s.imag for s in iq_samples), dtype=np.float64, count=len(iq_samples))
    else:
        real = np.fromiter((float(s[0]) for s in iq_samples), dtype=np.float64, count=len(iq_samples))
        imag = np.fromiter((float(s[1]) for s in iq_samples), dtype=np.float64, count=len(iq_samples))
    return real + 1j * imag


def reshape_cycles(csi_1d: np.ndarray, subcarriers: int = DEFAULT_NUM_SUBCARRIERS) -> np.ndarray:
    """Reshape flattened multi-cycle I/Q samples into (n_cycles, n_subcarriers)."""
    if csi_1d.ndim == 2:
        return csi_1d
    n = csi_1d.size
    if n == 0:
        return np.empty((0, subcarriers), dtype=np.complex128)
    if subcarriers > 0 and n >= subcarriers and n % subcarriers == 0:
        return csi_1d.reshape(n // subcarriers, subcarriers)
    return csi_1d.reshape(1, n)


def compute_amplitude(csi_complex: np.ndarray) -> np.ndarray:
    """Compute CSI subcarrier amplitudes |H(f, t)|."""
    return np.abs(csi_complex)


def sanitize_phase(csi_complex: np.ndarray) -> np.ndarray:
    """Unwrap phase across subcarriers and remove linear STO/CFO trend per frame."""
    if csi_complex.size == 0:
        return np.empty_like(csi_complex, dtype=np.float64)

    raw_phase = np.angle(csi_complex)
    unwrapped = np.unwrap(raw_phase, axis=-1)

    n_sub = unwrapped.shape[-1]
    if n_sub < 2:
        return unwrapped - np.mean(unwrapped, axis=-1, keepdims=True)

    k = np.arange(n_sub, dtype=np.float64)
    k_centered = k - np.mean(k)
    denom = float(np.dot(k_centered, k_centered))

    phi_mean = np.mean(unwrapped, axis=-1, keepdims=True)
    if denom <= 0.0:
        return unwrapped - phi_mean

    slope = np.sum((unwrapped - phi_mean) * k_centered, axis=-1, keepdims=True) / denom
    linear_fit = slope * k_centered + phi_mean
    return unwrapped - linear_fit


def hampel_filter(values: np.ndarray, window_size: int = 5, n_sigmas: float = 3.0) -> np.ndarray:
    """Apply Hampel outlier filter along time axis (axis=0)."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim == 0 or arr.shape[0] < 3:
        return arr.copy()

    half_win = max(1, window_size // 2)
    win = 2 * half_win + 1
    filtered = arr.copy()
    n_t = arr.shape[0]
    mad_scale = 1.4826

    # Vectorized interior window calculation (exact match to sliding bounds).
    if n_t >= win:
        windows = np.lib.stride_tricks.sliding_window_view(arr, win, axis=0)
        mid = slice(half_win, n_t - half_win)
        med = np.partition(windows, half_win, axis=-1)[..., half_win]
        mad = np.partition(np.abs(windows - med[..., None]), half_win, axis=-1)[..., half_win]
        threshold = n_sigmas * mad_scale * mad
        center = arr[mid]
        diff = np.abs(center - med)
        outliers = (mad > 1e-12) & (diff > threshold)
        if np.any(outliers):
            filtered[mid] = np.where(outliers, med, center)

        edge_indices = list(range(half_win)) + list(range(n_t - half_win, n_t))
    else:
        edge_indices = list(range(n_t))

    for idx in edge_indices:
        start = max(0, idx - half_win)
        end = min(n_t, idx + half_win + 1)
        window = arr[start:end]
        med = np.median(window, axis=0)
        mad = np.median(np.abs(window - med), axis=0)
        threshold = n_sigmas * mad_scale * mad
        diff = np.abs(arr[idx] - med)
        outliers = (mad > 1e-12) & (diff > threshold)
        if np.any(outliers):
            filtered[idx] = np.where(outliers, med, arr[idx])

    return filtered


def estimate_link_snr_db(rssi_dbm: int | float, noise_floor: float, amplitude: np.ndarray) -> float:
    """Estimate SNR (dB) from RSSI & noise_floor with amplitude fallback."""
    if noise_floor != 0.0 and np.isfinite(noise_floor):
        snr = float(rssi_dbm) - float(noise_floor)
    elif rssi_dbm != 0:
        snr = float(rssi_dbm) + 95.0
    elif amplitude.size > 0:
        mean_pow = float(np.mean(amplitude ** 2))
        snr = 10.0 * np.log10(max(mean_pow, 1e-9)) + 30.0
    else:
        snr = 0.0
    return float(np.clip(snr, -10.0, 50.0))


class CSIProcessor:
    """Processes raw I/Q samples for a single (tx, rx) CSI link."""

    def __init__(
        self,
        *,
        subcarriers: int = DEFAULT_NUM_SUBCARRIERS,
        hampel_window: int = 5,
        hampel_sigmas: float = 3.0,
    ) -> None:
        self.subcarriers = subcarriers
        self.hampel_window = hampel_window
        self.hampel_sigmas = hampel_sigmas

    def process_complex_frames(
        self,
        csi_frames: np.ndarray,
        *,
        rssi_dbm: int | float = -50,
        noise_floor: float = -92.0,
        apply_hampel: bool = True,
    ) -> ProcessedCSI:
        """Process a 2D complex matrix of shape (T, K) into sanitized amplitude & phase."""
        frames = np.asarray(csi_frames, dtype=np.complex128)
        if frames.ndim == 1:
            frames = reshape_cycles(frames, self.subcarriers)

        amp = compute_amplitude(frames)
        phase = sanitize_phase(frames)

        if apply_hampel and amp.shape[0] >= 3:
            amp = hampel_filter(amp, window_size=self.hampel_window, n_sigmas=self.hampel_sigmas)
            phase = hampel_filter(phase, window_size=self.hampel_window, n_sigmas=self.hampel_sigmas)

        snr_db = estimate_link_snr_db(rssi_dbm, noise_floor, amp)
        return ProcessedCSI(amplitude=amp, phase=phase, snr_db=snr_db)

    def process_iq(
        self,
        iq_samples: Sequence[IQSample | tuple[float, float]] | np.ndarray,
        *,
        rssi_dbm: int | float = -50,
        noise_floor: float = -92.0,
        apply_hampel: bool = True,
    ) -> ProcessedCSI:
        """Decode I/Q samples and run the full single-link sanitization pipeline."""
        csi_1d = iq_to_complex(iq_samples)
        frames = reshape_cycles(csi_1d, self.subcarriers)
        return self.process_complex_frames(
            frames,
            rssi_dbm=rssi_dbm,
            noise_floor=noise_floor,
            apply_hampel=apply_hampel,
        )
