import os
import pytest


def _resolve_api_key():
    # If GEMINI_API_KEY is explicitly set in the environment (even to empty),
    # honour it exclusively — an empty value means "force no key / skip".
    if "GEMINI_API_KEY" in os.environ:
        return os.environ["GEMINI_API_KEY"] or None
    try:
        from voice_task_board.config import get_config
        cfg = get_config()
        return getattr(cfg, "gemini_api_key", None)
    except Exception:
        return None


@pytest.fixture(scope="session")
def gemini_backend():
    key = _resolve_api_key()
    if not key:
        pytest.skip("No Gemini API key (set GEMINI_API_KEY or configure the app)")
    from voice_task_board.gemini import GeminiBackend
    return GeminiBackend(key)
