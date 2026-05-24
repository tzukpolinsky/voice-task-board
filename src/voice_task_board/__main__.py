from __future__ import annotations

import logging
import sys
import struct
import threading
from datetime import datetime
from typing import Any

from voice_task_board.hotkey import HotkeyListener
from voice_task_board.tray import create_tray_icon
from voice_task_board.logging_setup import configure_logging
from voice_task_board.audio import record_while_held
from voice_task_board.paths import recordings_dir
from voice_task_board.config import get_config
from voice_task_board.gemini import GeminiBackend
from voice_task_board.apply_intent import apply, ApplyResult
from voice_task_board.db import get_db
from voice_task_board import webview_app


logger = logging.getLogger(__name__)

_hotkey_listener: HotkeyListener | None = None
_tray_icon: Any = None
_gemini_backend: GeminiBackend | None = None
_recording_lock = threading.Lock()
_recording_active = False


def _get_hotkey_listener() -> HotkeyListener | None:
    return _hotkey_listener


def _save_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, bits_per_sample: int = 16) -> str:
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    subchunk2_size = len(pcm_bytes)

    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + subchunk2_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        subchunk2_size,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    output_path = recordings_dir() / f"{timestamp}.wav"
    with open(output_path, "wb") as f:
        f.write(wav_header + pcm_bytes)
    logger.info(f"Saved recording to {output_path}")
    return str(output_path)


def main() -> int:
    global _hotkey_listener, _tray_icon, _gemini_backend
    
    configure_logging()
    logger.info("Starting Voice Task Board")

    db = get_db()
    config = get_config()

    tasks = db.list_tasks()
    logger.info(f"Loaded {len(tasks)} existing tasks")
    
    if config.gemini_api_key:
        try:
            _gemini_backend = GeminiBackend(config.gemini_api_key)
            logger.info("Gemini backend initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini backend: {e}")

    def on_hotkey_pressed() -> None:
        global _recording_active
        with _recording_lock:
            if _recording_active:
                return  # auto-repeat while held — ignore silently
            _recording_active = True

        def record_in_background() -> None:
            global _recording_active
            try:
                logger.debug("record_in_background started")
                if not config.gemini_api_key:
                    logger.error("Gemini API key not set")
                    if _tray_icon:
                        _tray_icon.notify("Set your Gemini API key in Settings")
                    return

                logger.info("Recording started (hold to record, release to stop)")
                listener = _hotkey_listener
                if listener is None:
                    raise RuntimeError("Hotkey listener not initialized")
                pcm_bytes = record_while_held(listener.is_key_held)
                logger.debug(f"record_while_held returned {len(pcm_bytes)} bytes")

                if not pcm_bytes:
                    logger.info("No speech detected")
                    return

                wav_path = _save_wav(pcm_bytes)
                duration_seconds = len(pcm_bytes) / (16000 * 2)
                logger.info(f"Recording complete: {duration_seconds:.1f}s saved to {wav_path}")

                logger.info("Extracting intent from Gemini")
                if not _gemini_backend:
                    raise RuntimeError("Gemini backend not initialized")
                category_names = db.get_category_names()
                logger.debug(f"Categories passed to Gemini: {category_names}")
                intent = _gemini_backend.extract_intent(pcm_bytes, category_names)
                logger.info(f"Intent: {intent}")

                logger.info("Applying intent to database")
                result = apply(intent, _gemini_backend)
                logger.info(f"Apply result: {result}")

                if result == ApplyResult.CREATED:
                    msg = f"✓ Added: {intent.title}"
                elif result == ApplyResult.DELETED:
                    msg = "✓ Deleted task"
                elif result == ApplyResult.EDITED:
                    msg = "✓ Edited task"
                elif result == ApplyResult.NO_MATCH:
                    msg = "✗ No matching task"
                else:
                    msg = "? Could not understand"
                
                if _tray_icon:
                    _tray_icon.notify(msg)
                    
            except ValueError as e:
                logger.info(f"Input error: {e}")
            except Exception as e:
                logger.exception(f"Recording/intent/apply failed: {e}")
                if _tray_icon:
                    _tray_icon.notify(f"Error: {str(e)[:50]}")
            finally:
                with _recording_lock:
                    _recording_active = False

        thread = threading.Thread(target=record_in_background, daemon=True)
        thread.start()

    _hotkey_listener = HotkeyListener(config.hotkey, on_hotkey_pressed)
    webview_app.set_hotkey_listener(_hotkey_listener)
    _hotkey_listener.start()

    def run_tray() -> None:
        global _tray_icon
        try:
            _tray_icon = create_tray_icon()
            _tray_icon.run()
        except Exception as e:
            logger.exception(f"Tray error: {e}")

    tray_thread = threading.Thread(target=run_tray, name="tray", daemon=False)
    tray_thread.start()

    try:
        window = webview_app.create_window()
        webview_app.start()
    except Exception as e:
        logger.exception(f"WebView error: {e}")
    finally:
        if _hotkey_listener:
            _hotkey_listener.stop()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
