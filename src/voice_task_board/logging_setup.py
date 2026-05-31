from __future__ import annotations

import faulthandler
import logging
import os
import socket
import sys
from datetime import datetime
from pathlib import Path


_faulthandler_file: object | None = None  # held to keep the FD open for the process lifetime


def _app_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data is None:
        app_data = str(Path.home() / "AppData" / "Roaming")
    return Path(app_data) / "VoiceTaskBoard"


def _is_dev() -> bool:
    if os.environ.get("VTB_DEV") == "1":
        return True
    return not getattr(sys, "frozen", False)


_NOISY_LOGGERS = (
    "httpcore", "httpx", "urllib3", "PIL", "PIL.Image", "PIL.PngImagePlugin",
    "asyncio", "google", "google.auth", "google_genai", "matplotlib",
)


def _enable_faulthandler() -> None:
    """Dump Python tracebacks of every thread on native crash (segfault, AV).

    Native crashes (e.g. WebView2/pythonnet access violations) bypass Python's
    exception machinery, so logger.exception never runs. faulthandler installs
    OS signal/SEH handlers that flush thread stacks to a file *before* the
    process dies, turning silent crashes into a starting point for diagnosis.

    The file is in APPDATA so it survives across runs; we keep a handle to it
    for the lifetime of the process (closing it would unregister the handler).
    """
    global _faulthandler_file
    if faulthandler.is_enabled():
        return
    log_dir = _app_data_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _faulthandler_file = open(log_dir / "faulthandler.log", "a", encoding="utf-8", buffering=1)
        _faulthandler_file.write(f"\n=== faulthandler armed at {datetime.now().isoformat()} ===\n")
        _faulthandler_file.flush()
        faulthandler.enable(file=_faulthandler_file, all_threads=True)
    except OSError:
        # Fall back to stderr; better than nothing.
        faulthandler.enable(all_threads=True)


def configure_logging() -> None:
    _enable_faulthandler()

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if _is_dev():
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        root_logger.debug("Logging configured: dev mode (console)")
    else:
        log_dir = _app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        for old_log in log_dir.glob("*.log"):
            try:
                old_log.unlink()
            except OSError:
                pass

        # One-shot cleanup of dirs from older versions that are no longer used.
        import shutil
        for stale in ("recordings", "models"):
            stale_path = _app_data_dir() / stale
            if stale_path.exists():
                try:
                    shutil.rmtree(stale_path)
                except OSError:
                    pass

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        hostname = socket.gethostname()
        log_path = log_dir / f"{timestamp}_{hostname}.log"

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.info(f"Logging configured: prod mode -> {log_path}")
