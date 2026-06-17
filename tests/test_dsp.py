import numpy as np
from voice_task_board import dsp


def _tone(freq_hz, rate, seconds=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def _peak_freq(pcm, rate):
    spec = np.abs(np.fft.rfft(pcm))
    return np.fft.rfftfreq(len(pcm), 1 / rate)[int(np.argmax(spec))]


def test_resample_preserves_in_band_tone():
    out = dsp.resample(_tone(1000, 48000), 48000, 16000)
    assert abs(_peak_freq(out, 16000) - 1000) < 30


def test_resample_rejects_out_of_band_alias():
    # 7 kHz exists at 48k but is above the 8 kHz Nyquist of 16k; a proper
    # resampler attenuates it instead of aliasing it back into the speech band.
    out = dsp.resample(_tone(7000, 48000), 48000, 16000)
    in_band = np.abs(np.fft.rfft(out))[ (np.fft.rfftfreq(len(out), 1/16000) < 4000) ]
    assert float(np.max(in_band)) < 0.1 * len(out)


def test_resample_noop_same_rate():
    x = _tone(1000, 16000)
    out = dsp.resample(x, 16000, 16000)
    assert np.allclose(out, x)


def test_resample_empty():
    assert dsp.resample(np.zeros(0, np.float32), 48000, 16000).size == 0


def test_normalize_peak_hits_target():
    quiet = (_tone(440, 16000) * 0.05).astype(np.float32)
    out = dsp.normalize_peak(quiet, target_dbfs=-1.0)
    expected_peak = 10 ** (-1.0 / 20)
    assert abs(float(np.max(np.abs(out))) - expected_peak) < 1e-3


def test_normalize_peak_silence_safe():
    out = dsp.normalize_peak(np.zeros(1000, np.float32))
    assert np.all(np.isfinite(out)) and float(np.max(np.abs(out))) == 0.0


def test_normalize_peak_empty():
    assert dsp.normalize_peak(np.zeros(0, np.float32)).size == 0


def _thd(pcm, rate, fundamental):
    spec = np.abs(np.fft.rfft(pcm))
    freqs = np.fft.rfftfreq(len(pcm), 1 / rate)
    fund_bin = int(np.argmin(np.abs(freqs - fundamental)))
    fund = spec[fund_bin]
    harmonics = spec.sum() - fund
    return harmonics / (fund + 1e-9)


def test_soft_limit_respects_ceiling():
    hot = (_tone(440, 16000) * 1.5).astype(np.float32)
    out = dsp.soft_limit(hot, ceiling=0.999)
    assert float(np.max(np.abs(out))) <= 0.999 + 1e-6


def test_soft_limit_lower_distortion_than_hard_clip():
    hot = (_tone(440, 16000) * 1.5).astype(np.float32)
    soft = dsp.soft_limit(hot, ceiling=0.999)
    hard = np.clip(hot, -0.999, 0.999)
    assert _thd(soft, 16000, 440) < _thd(hard, 16000, 440)


def test_preprocess_outputs_16k_mono_float32():
    stereo = np.stack([_tone(440, 48000), _tone(660, 48000)], axis=1).astype(np.float32)
    out = dsp.preprocess(stereo, 48000)
    assert out.dtype == np.float32 and out.ndim == 1
    assert np.all(np.isfinite(out))
    assert float(np.max(np.abs(out))) <= 0.999 + 1e-6
    # ~1/3 the samples after 48k→16k
    assert abs(out.size - stereo.shape[0] / 3) < 50


def test_preprocess_empty():
    assert dsp.preprocess(np.zeros(0, np.float32), 48000).size == 0
