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
