from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

DST_RATE = 16000


def resample(pcm: np.ndarray, src_rate: int, dst_rate: int = DST_RATE) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.float32)
    if pcm.size == 0 or src_rate == dst_rate:
        return pcm
    try:
        import soxr
        return np.asarray(soxr.resample(pcm, src_rate, dst_rate, quality="VHQ"), dtype=np.float32)
    except Exception as e:  # soxr missing or failed → polyphase fallback
        logger.warning("soxr unavailable (%r); falling back to scipy.resample_poly", e)
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(src_rate), int(dst_rate))
        up, down = dst_rate // g, src_rate // g
        return resample_poly(pcm, up, down).astype(np.float32)


def normalize_peak(pcm: np.ndarray, target_dbfs: float = -1.0) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.float32)
    if pcm.size == 0:
        return pcm
    peak = float(np.max(np.abs(pcm)))
    if peak <= 0.0:
        return pcm
    target = 10 ** (target_dbfs / 20)
    return (pcm * (target / peak)).astype(np.float32)


def soft_limit(pcm: np.ndarray, ceiling: float = 0.999) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.float32)
    if pcm.size == 0:
        return pcm
    # tanh soft knee: ~linear for small signals (tanh(x)≈x), and since tanh
    # asymptotes to ±1 the output magnitude is always < ceiling. This is why the
    # scaling is `ceiling * tanh(pcm)` and NOT `tanh(pcm)*ceiling/tanh(1)` — the
    # latter overshoots the ceiling for inputs >1.0.
    return (ceiling * np.tanh(pcm)).astype(np.float32)
