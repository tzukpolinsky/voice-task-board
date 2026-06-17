import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from jiwer import wer

from voice_task_board import dsp
from voice_task_board.audio import _downmix_to_mono, _resample_float32, _float32_to_int16

TESTS = Path(__file__).parent
CATEGORIES = ["Personal", "Work"]  # constant; satisfies API, irrelevant to WER


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s]", " ", text)        # strip punctuation/commas (Unicode-safe)
    return re.sub(r"\s+", " ", text).strip().lower()


def _load_clips():
    manifest = json.loads((TESTS / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        pcm, rate = sf.read(TESTS / entry["file"], dtype="float32", always_2d=False)
        yield entry["file"], pcm, int(rate), entry["transcript"]


def _baseline_int16(pcm, rate):
    mono = _downmix_to_mono(pcm)
    return _float32_to_int16(_resample_float32(mono, rate, 16000)).tobytes()


def _processed_int16(pcm, rate):
    return _float32_to_int16(dsp.preprocess(pcm, rate)).tobytes()


@pytest.mark.live
def test_processed_not_worse_than_baseline(gemini_backend):
    rows, base_wers, proc_wers = [], [], []
    for name, pcm, rate, truth in _load_clips():
        ref = _normalize(truth)
        b = _normalize(gemini_backend.extract_intent(_baseline_int16(pcm, rate), CATEGORIES).transcription)
        p = _normalize(gemini_backend.extract_intent(_processed_int16(pcm, rate), CATEGORIES).transcription)
        bw, pw = wer(ref, b), wer(ref, p)
        base_wers.append(bw); proc_wers.append(pw)
        rows.append((name, round(bw, 3), round(pw, 3)))

    print("\nclip                                baseline  processed")
    for name, bw, pw in rows:
        print(f"{name:<34} {bw:>8} {pw:>9}")
    agg_base = sum(base_wers) / len(base_wers)
    agg_proc = sum(proc_wers) / len(proc_wers)
    print(f"{'AGGREGATE':<34} {agg_base:>8.3f} {agg_proc:>9.3f}")

    # Contract: processing must not regress overall (small tolerance for model nondeterminism).
    assert agg_proc <= agg_base + 0.02
