# Voice Task Board — Build Plan (Gemini Backend, v1)

> Companion to [PLAN.md](PLAN.md). This document is the **executable** build plan, written so a less-capable agent (e.g. Haiku) can follow it step-by-step.
>
> Each phase has: **Goal**, **Files to create/edit**, **Dependencies**, **Acceptance criteria**, and **Stop condition** (when to ask for human review before continuing).
>
> **Revision history.** Initial pass produced a working scaffold but ~20 bugs documented in [CODE_REVIEW.md](CODE_REVIEW.md). Spec sections marked **[revised]** were tightened to prevent those bugs in future re-implementations. Most fixes are concrete code snippets or exact API names — do not deviate.

---

## Conventions

- All paths are relative to repo root: `c:\Users\rsolomon\voice-task-board\`
- Python 3.11+ assumed. Use a virtual env in `.venv/`.
- Windows-only. Do not write cross-platform abstractions.
- Use `httpx` (not `requests`) for HTTP.
- Use `pydantic` v2 for data models.
- Type-hint everything. Run `mypy` clean.
- No comments unless explaining a non-obvious *why*.
- Do **not** create new files outside the paths specified in each phase.
- If a step fails, **stop and report** — do not invent a workaround.

---

## Phase 0 — Project scaffolding

**Goal:** create the project skeleton and verify the dev environment.

**Files to create:**

```
voice-task-board/
├── .venv/                       (created by venv command, gitignored)
├── .gitignore
├── pyproject.toml
├── README.md                    (one paragraph, no install instructions yet)
├── src/
│   └── voice_task_board/
│       ├── __init__.py
│       ├── __main__.py          (entry point — prints "ok" for now)
│       ├── config.py            (empty for now)
│       └── logging_setup.py     (configures stdlib logging to %APPDATA%/VoiceTaskBoard/app.log)
└── frontend/                    (empty for now)
```

**Dependencies (pyproject.toml):**

```toml
[project]
name = "voice-task-board"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pywin32>=306",
  "pystray>=0.19",
  "Pillow>=10.0",
  "sounddevice>=0.4.6",
  "numpy>=1.26",
  "onnxruntime>=1.17",
  "httpx>=0.27",
  "pydantic>=2.5",
  "pywebview>=5.0",
]

[project.optional-dependencies]
dev = ["mypy", "ruff", "pyinstaller>=6.5"]
```

**Commands:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m voice_task_board
```

**Acceptance:** `python -m voice_task_board` prints `ok` and exits 0. `mypy src` is clean.

**Stop condition:** After Phase 0, stop and report.

---

## Phase 1 — Tray icon + global hotkey **[revised]**

**Goal:** App runs in system tray. Pressing the configured hotkey (default `Ctrl+Shift+Space`) logs "hotkey pressed" and shows a tray notification. **The hotkey must be re-bindable at runtime; do not hard-code it.**

**Files to create/edit:**

- `src/voice_task_board/tray.py` — pystray icon, menu with "Open" and "Quit" items. Icon = simple 64x64 PNG generated in code (filled circle, no external file).
- `src/voice_task_board/hotkey.py` — `HotkeyListener` class with:
  - Constructor takes initial combo string (e.g. `"ctrl+shift+space"`) and a callback.
  - `start()`, `stop()`, and `rebind(new_combo: str)` methods.
  - `rebind` works while running by posting a custom thread message that triggers `UnregisterHotKey` + parse-new-combo + `RegisterHotKey` inside the listener thread.
  - Combo parser: small lookup tables for modifier names → `MOD_*` flags and key names → virtual key codes. Support: `ctrl`, `shift`, `alt`, `win`; letters `a-z`, digits `0-9`, `space`, `enter`, `f1-f12`. Raise `ValueError` on unknown tokens.
- `src/voice_task_board/__main__.py` — constructs `HotkeyListener(config.hotkey, on_hotkey_pressed)`.

**Hotkey implementation notes:**
- Use `win32con.WM_HOTKEY` in a `PumpMessages` loop.
- Create the hidden window with `win32gui.CreateWindow` to receive the message.
- `RegisterHotKey(hwnd, 1, mods, vk)` where `mods, vk` are derived from the parsed config string.
- Unregister on shutdown and on every rebind.
- For `rebind`, send a custom `WM_APP + 1` message via `win32api.PostMessage(hwnd, ...)`; the WndProc dispatch table handles it by calling `UnregisterHotKey` then `RegisterHotKey` with the new combo.

**Acceptance:**
- Tray icon visible after launch.
- Pressing `Ctrl+Shift+Space` from any window shows a tray notification within 100ms.
- "Quit" from tray menu exits cleanly with no orphan threads.

**Stop condition:** After Phase 1, stop and report.

---

## Phase 2 — Audio capture + VAD endpointing

**Goal:** Hotkey starts recording. Recording ends after ~1s of trailing silence (Silero VAD) or 30s hard cap. Result saved as 16kHz mono 16-bit PCM WAV to `%APPDATA%/VoiceTaskBoard/recordings/<timestamp>.wav`.

**Files to create:**

- `src/voice_task_board/audio.py` **[revised]**:
  - `record_until_silence() -> bytes` — returns raw PCM bytes (16kHz mono int16, little-endian).
  - Internals: use `sounddevice.InputStream` with `samplerate=16000, channels=1, dtype='int16'`, callback fills a queue.
  - Frame size: 512 samples (32ms at 16kHz) — matches Silero VAD input.
  - Trailing-silence threshold: 32 consecutive silent frames (~1s) **after first speech**.
  - **No-speech timeout (required):** if no speech is ever detected within 94 frames (~3s) of the hotkey press, stop immediately and return empty PCM. Caller must handle empty bytes gracefully (skip Gemini, no tray spam).
  - Hard cap: 938 frames (~30s).
  - Pre-roll: keep last 16 frames (~500ms) before VAD first detects speech, prepend to output.
  - Do **not** type-annotate the `time` parameter of the sounddevice callback as `sd.CallbackTimeData` — that symbol does not exist. Use `Any`.

- `src/voice_task_board/vad.py` **[revised — full ONNX contract spelled out, prior implementation was broken]**:
  - Wraps Silero VAD v5 ONNX model. **Bundle the model** with the app (place at `src/voice_task_board/resources/silero_vad.onnx`, added to PyInstaller `datas` in Phase 7). Do **not** download at runtime.
  - **Stateful API.** Silero VAD requires three ONNX inputs every call: `input`, `state`, `sr`. Maintain `state` between calls inside the `SileroVAD` instance.

  Exact required implementation:

  ```python
  class SileroVAD:
      def __init__(self) -> None:
          model_path = _resource_path("silero_vad.onnx")
          self._session = rt.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
          self._state = np.zeros((2, 1, 128), dtype=np.float32)
          self._sr = np.array(16000, dtype=np.int64)

      def reset(self) -> None:
          self._state = np.zeros((2, 1, 128), dtype=np.float32)

      def is_speech(self, frame_int16: np.ndarray) -> bool:
          # frame_int16 must be shape (512,)
          audio = (frame_int16.astype(np.float32) / 32768.0).reshape(1, 512)
          outputs = self._session.run(None, {
              "input": audio,
              "state": self._state,
              "sr": self._sr,
          })
          prob = float(outputs[0].item())   # scalar speech probability
          self._state = outputs[1]
          return prob > 0.5
  ```

  - Call `reset()` at the start of every `record_until_silence()` so previous-utterance state does not bleed into a new recording.
  - `_resource_path` returns the bundled file path in dev (relative to `__file__`) or in the PyInstaller bundle (`sys._MEIPASS`).

- `src/voice_task_board/paths.py`:
  - Helpers: `app_data_dir()`, `recordings_dir()`, `models_dir()`. All under `%APPDATA%/VoiceTaskBoard/`. Create directories if missing.

**Edit:** `__main__.py` — hotkey callback now calls `record_until_silence()`, saves WAV, logs duration and file path.

**Acceptance:**
- Press hotkey, speak "hello world", pause 1 second. Recording ends. WAV file exists with reasonable size (~30-80KB for 2-3s).
- Press hotkey, stay silent. Recording ends after ~3s (no-speech timeout) and returns empty PCM; caller logs "no speech" and does not call Gemini.
- Press hotkey, talk continuously for 35s. Recording cuts at 30s.

**Stop condition:** After Phase 2, stop and report. Include the file path of one example recording in the report.

---

## Phase 3 — Gemini integration

**Goal:** Send recorded audio + system prompt to Gemini 3 Flash Preview. Receive validated JSON intent.

**Files to create:**

- `src/voice_task_board/gemini.py` **[revised — REST field names are camelCase; prior pass used snake_case and the schema was silently ignored]**:
  - `class GeminiBackend`
  - Constructor takes `api_key: str`.
  - Method `extract_intent(pcm_bytes: bytes, categories: list[str]) -> Intent`. **If `pcm_bytes` is empty, raise `ValueError("empty audio")` immediately** (do not call the API).
  - HTTP POST to `https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key=<api_key>`.
  - **Verify the model ID once** with `GET /v1beta/models?key=<api_key>` before locking it in code. If `gemini-3-flash-preview` is not in the list, use whatever exact ID Google publishes for "Gemini 3 Flash Preview" at build time.
  - Request body: multimodal `contents` with one `inlineData` part (audio/wav, base64-encoded WAV — wrap PCM in WAV header), one `text` part with the system prompt.
  - **All REST keys must be camelCase**: `inlineData`, `mimeType`, `generationConfig`, `responseMimeType`, `responseSchema`. Snake_case is silently ignored by the API.

  Exact request body shape:

  ```json
  {
    "contents": [{
      "parts": [
        {"inlineData": {"mimeType": "audio/wav", "data": "<base64>"}},
        {"text": "<system prompt>"}
      ]
    }],
    "generationConfig": {
      "responseMimeType": "application/json",
      "responseSchema": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["add", "edit", "delete", "unknown"]},
          "title": {"type": "string"},
          "category": {"type": "string"},
          "target_query": {"type": "string", "nullable": true}
        },
        "required": ["action", "title", "category"]
      }
    }
  }
  ```

  - Do **not** use pydantic's `model_json_schema()` directly — it emits `$defs`, `title`, `additionalProperties` which Gemini rejects. Use the hand-written schema above.
  - Parse response → `Intent` pydantic model.

- `src/voice_task_board/intent.py`:
  ```python
  from pydantic import BaseModel
  from typing import Literal

  class Intent(BaseModel):
      action: Literal["add", "edit", "delete", "unknown"]
      title: str
      category: str
      target_query: str | None = None  # for edit/delete: what the user said to identify the task
  ```

- `src/voice_task_board/config.py` (replace empty):
  - Loads/saves a JSON config at `%APPDATA%/VoiceTaskBoard/config.json`.
  - Fields: `gemini_api_key: str | None`, `hotkey: str = "ctrl+shift+space"`.
  - For Phase 3, the API key is read from env var `GEMINI_API_KEY` if config file missing. Settings UI comes in Phase 6.

**System prompt template (in gemini.py):**

```
You are a voice task assistant. The user just spoke a task command.
The audio may be in English or Hebrew (or mixed). Preserve the user's original language in `title`.

Existing categories: {categories_json}

Listen to the audio and extract:
- action: "add" | "edit" | "delete" | "unknown"
- title: the task description in the user's original language
- category: best-matching category from the list above, or "default" if none fit
- target_query: for edit/delete, the text the user used to identify which task; null otherwise

Return strict JSON matching the schema. Do not include explanations.
```

**Edit:** `__main__.py` — after recording, call `GeminiBackend.extract_intent(pcm, db.list_categories())` and log the Intent. (DB is initialized in this phase even though full CRUD lands in Phase 4 — just enough to seed and list categories.)

**Acceptance:**
- With `GEMINI_API_KEY` set, press hotkey, say "add buy milk". Log shows `Intent(action='add', title='buy milk', category='default', target_query=None)` (only `default` is seeded at this point).
- Hebrew: say "תוסיף לקנות חלב". Log shows valid Intent with Hebrew title preserved.
- Invalid API key: HTTP 4xx surfaces a clear log line and tray notification, app does not crash.
- Empty audio (no speech): `extract_intent` raises `ValueError`; `__main__` logs "no speech" and does not show an error toast.

**Stop condition:** After Phase 3, stop and report. Include three example intents from real voice commands.

---

## Phase 4 — SQLite + intent application

**Goal:** Apply the Intent to a local SQLite DB. Tasks persist across restarts.

**Files to create:**

- `src/voice_task_board/db.py`:
  - SQLite file at `%APPDATA%/VoiceTaskBoard/tasks.db`.
  - On startup: open connection, run migrations.
  - Migrations as ordered list `MIGRATIONS: list[str]`, indexed by `PRAGMA user_version`.
  - Initial schema (migration 1):
    ```sql
    CREATE TABLE categories (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      sort_order INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE tasks (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      category_id INTEGER NOT NULL REFERENCES categories(id),
      status TEXT NOT NULL DEFAULT 'open',
      data TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX idx_tasks_title ON tasks(title);
    CREATE INDEX idx_tasks_category ON tasks(category_id);
    CREATE INDEX idx_tasks_status ON tasks(status);

    INSERT INTO categories (name, sort_order) VALUES ('default', 0);
    ```
  - **Connection setup:** open with `sqlite3.connect(path, check_same_thread=False)`, then **immediately** run `PRAGMA foreign_keys = ON` on the connection. Use a single connection guarded by a `threading.Lock`; every public method (including UI-facing ones) must take the lock.
  - **Atomic migrations [revised]:** do **not** use `executescript`. For each pending migration, run `conn.execute("BEGIN")` then execute each statement individually then `PRAGMA user_version = N` then `COMMIT`. A crash mid-migration must leave `user_version` unchanged so the next start retries.
  - Functions (all hold `self._lock`):
    - `add_task(title, category_name) -> int`
    - `delete_task_matching(query) -> MatchResult` (see below)
    - `edit_task_matching(query, new_title) -> MatchResult`
    - `list_tasks() -> list[Task]`, `list_categories() -> list[Category]` where `Category` has `id` and `name`
    - `add_category(name) -> int`, `delete_category(id) -> None`, `move_task(task_id, category_id) -> None`, `delete_task(task_id) -> None`
  - `MatchResult` is a discriminated dataclass: `Hit(id)` | `Ambiguous(count)` | `NoMatch`. Callers must distinguish these three; the previous `int` return type cannot.
  - Matching for edit/delete: case-insensitive `LIKE %query%` on `title`. `Ambiguous` returns without mutating.

- `src/voice_task_board/apply_intent.py`:
  - `apply(intent: Intent) -> ApplyResult`.
  - Routes by `intent.action`.
  - Resolves category by name (case-insensitive); if not found, falls back to `default`.
  - Returns an enum: `CREATED | DELETED | EDITED | NOT_FOUND | AMBIGUOUS | UNKNOWN`.

**Edit:** `__main__.py` — pipeline now: hotkey → record → Gemini → apply → tray notification with the result.

**Acceptance:**
- Pre-seed `Personal` and `Work` categories in migration 1 (in addition to `default`). Otherwise the next test routes to `default` silently.
- "add buy milk to personal" → row exists in `tasks` table, joined `category_name` is `Personal`.
- "delete buy milk" → row removed (`MatchResult.Hit`).
- "delete x" with no matching task → `MatchResult.NoMatch` → tray says "no task matched".
- "delete the task" with 3 matching → `MatchResult.Ambiguous(3)` → no rows deleted, tray says "ambiguous: 3 tasks match".
- Restart app → previous tasks still visible (via `list_tasks()` log on startup).
- Delete a category that still has tasks → operation rejected by foreign-key constraint (`PRAGMA foreign_keys = ON`).

**Stop condition:** After Phase 4, stop and report.

---

## Phase 5 — React UI **[revised]**

**Goal:** PyWebView window shows the task board. Kanban-style columns per category. Updates live when voice commands change the DB. Drag-and-drop between columns is required.

### Critical: threading model

PyWebView's `webview.start()` **must run on the main thread and blocks**. The original Phase 1/5 ordering (pystray on main thread, webview launched from tray callback) does **not** work. Restructure as:

1. **Main thread:** create a single hidden webview window, register pystray on a background thread, then call `webview.start()` (blocks until window closed).
2. **Tray "Open"** calls `window.show()` on the existing window (or `restore()` if minimized). It does **not** create a new window.
3. **Tray "Quit"** calls `window.destroy()` which ends `webview.start()`, then the main thread stops the tray icon and joins the hotkey listener.

This is a Phase 5 restructure of Phase 1's `__main__.py`.

### Files to create

- `frontend/` — Vite + React + TypeScript project.
  - `package.json` (must include `@dnd-kit/core` and `@dnd-kit/sortable`), `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/components/Board.tsx`, `src/components/Column.tsx`, `src/components/TaskCard.tsx`, `src/api.ts`.
  - Build output: `frontend/dist/`.
  - Vite config: `base: './'` (so relative paths work when loaded via file:// inside PyWebView).
- `src/voice_task_board/webview_app.py`:
  - `class Api` — exposed to JS via PyWebView's `js_api`. Methods:
    - `get_tasks() -> list[dict]` — each task includes `category_id` (DB id, not array index).
    - `get_categories() -> list[dict]` — each category is `{"id": int, "name": str}`. **Never return bare strings**; the UI needs the id for filtering and drag-drop.
    - `add_category(name) -> int`, `delete_category(id) -> None`
    - `move_task(task_id, category_id) -> None`, `delete_task(task_id) -> None`
    - All methods route through `Database` methods that hold `db._lock`. **Never touch `db._conn` directly from `Api`.**
  - `start_window()` is called from `__main__` on the **main thread**:
    ```python
    window = webview.create_window("Voice Task Board", url=index_html_url, js_api=Api(), hidden=False)
    webview.start()  # blocks
    ```
  - `index_html_url` resolution must work in both dev and PyInstaller bundle: use `sys._MEIPASS` if present, else `Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"`. Convert to a `file:///` URL.
- `src/voice_task_board/tray.py` — "Open" menu calls `window.show()` on the already-created window passed in by `__main__`.

### React side

- On mount, call `get_tasks()` and `get_categories()` (which returns `[{id, name}]`).
- Poll every 500ms.
- `Board` renders one `Column` per category, passing `categoryId={category.id}` (the **DB id**, not the array index).
- `Column` filters with `tasks.filter(t => t.category_id === categoryId)`.
- Drag-and-drop with `@dnd-kit/core` (`DndContext`, `useDroppable` on Column, `useDraggable` on TaskCard). On drop, call `move_task(task.id, dropTarget.categoryId)`.

**Edit:** `__main__.py` — after each voice command applies, no extra work needed; UI polls.

**Acceptance:**
- Tray "Open" launches a window showing all tasks grouped by category.
- Voice command "add file the report to work" → task appears in the Work column within 500ms.
- Drag a task from one column to another → DB row's `category_id` updates, persists across restart.

**Stop condition:** After Phase 5, stop and report. Include a screenshot path (save to `docs/screenshots/phase5.png`).

---

## Phase 6 — Settings & onboarding **[revised]**

**Goal:** First-run onboarding asks for the Gemini API key. Settings panel in the UI lets the user change it later, change the hotkey, manage categories (**add and remove both required**).

**Files to create/edit:**

- `frontend/src/components/Settings.tsx` — modal with:
  - API key input (password field, masked) + Test button.
  - Hotkey input.
  - Category list with **both Add and Remove** buttons. Remove calls `Api.delete_category(id)`. The default category cannot be removed (server enforces).
- `frontend/src/components/Onboarding.tsx` — full-screen on first run if `config.gemini_api_key` is missing. Includes link to `https://aistudio.google.com/apikey` and a "Test connection" button that calls `Api.test_gemini_key(key)`.
  - Placeholder text should reflect Gemini key format (`AIza...`), not OpenAI's `sk-...`.
  - The link should open in the user's default browser via PyWebView's `webview.api`, not `target="_blank"` (which WebView2 ignores).
- `src/voice_task_board/webview_app.py` — extend `Api` with `get_config()`, `save_config(...)`, `test_gemini_key(key)`, `set_hotkey(combo)`.
  - **`test_gemini_key` must use a cheap endpoint**, not a real generateContent call. Use `GET /v1beta/models?key=<key>` and check for 200 + non-empty list. Avoids burning free-tier quota on every Test click.
  - `set_hotkey(combo)` validates the combo by parsing it, calls `config.save()`, **and** calls `hotkey_listener.rebind(combo)` so the change is live without a restart.
- `src/voice_task_board/hotkey.py` — `rebind(new_combo)` method (already specified in Phase 1 [revised]).

**Acceptance:**
- Fresh launch (delete `config.json`) → onboarding appears. Pasting a valid key + clicking Test → green check. Save → onboarding closes, voice commands work.
- Settings → change hotkey to `Ctrl+Shift+T` → old combo no longer triggers, new combo does.
- Settings → add category "Errands" → appears as new column, voice command "add buy milk to errands" routes there.

**Stop condition:** After Phase 6, stop and report.

---

## Phase 7 — Packaging

**Goal:** A single `VoiceTaskBoardSetup.exe` that installs the app, registers it for startup, and runs.

**Files to create:**

- `pyinstaller.spec` **[revised]** — onedir build. Entry: `src/voice_task_board/__main__.py`.
  - `datas` must include both `frontend/dist` **and** `src/voice_task_board/resources/silero_vad.onnx`. Bundle the VAD model; do not rely on runtime download.
  - Hidden imports: `pystray._win32`. (Drop `PIL._tkinter_finder` — unused.)
  - Verify `certifi` is bundled (needed for httpx HTTPS to Gemini). PyInstaller usually picks it up; if not, add explicitly.
- `installer/voice-task-board.iss` **[revised]**:
  - Installs to `{userpf}\VoiceTaskBoard\` (per-user, no admin needed).
  - Adds shortcut to Start Menu.
  - **Startup registry entry is unconditional**, not gated behind an unchecked task. User explicitly required "runs on startup." Drop the `Tasks: startup` task and write the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value directly with `Flags: uninsdeletevalue`.
  - AppId GUID: use balanced `{{...}}` braces.
- `build.ps1` **[revised]** — script that runs:
  1. `npm --prefix frontend ci && npm --prefix frontend run build`
  2. `pyinstaller pyinstaller.spec --distpath installer\dist --workpath installer\build` (the correct flag is `--workpath`, **not** `--buildpath`; do not pass `--specpath` when an explicit spec is supplied)
  3. `iscc installer\voice-task-board.iss`

  Output: `installer\output\VoiceTaskBoardSetup.exe`.

**Acceptance:**
- `.\build.ps1` produces `VoiceTaskBoardSetup.exe`.
- Running the installer on a clean Windows 11 machine: app installs, starts immediately, runs in tray. Voice commands work after API key paste.
- Reboot → app autostarts.
- Uninstall → app removed, autostart entry removed.

**Stop condition:** After Phase 7, stop and report. Include the installer path and a brief description of what was tested.

---

## Cross-cutting requirements

These apply to every phase. Re-check before marking any phase complete.

### Error handling
- Network errors (Phase 3+): catch, log, tray notification "API error: <short reason>". Never crash.
- Missing API key: tray notification "Set your Gemini API key in Settings". Never crash.
- Audio device missing: tray notification, log, do not retry indefinitely.
- DB locked: retry 3x with 100ms backoff, then surface.

### Logging
- Stdlib logging only. Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`.
- File handler: `%APPDATA%/VoiceTaskBoard/app.log`, rotating at 5MB, keep 3 backups.
- Console handler: WARNING+ only.
- No `print()` calls anywhere.

### Threading model **[revised]**
- **Main thread: PyWebView.** `webview.start()` blocks here. Everything else is background.
- **Tray:** runs in a background thread (`pystray.Icon.run_detached()` or a manually-spawned thread that calls `icon.run()`).
- **Hotkey listener:** dedicated thread with Win32 message pump. Supports runtime rebind via posted messages.
- **Recording + Gemini + DB apply:** spawned per hotkey press as a daemon thread; sequential within that thread. Wrap the whole thread body in `try/except` with `logger.exception(...)` — uncaught exceptions in a thread are silently lost otherwise.
- **DB:** single connection opened with `check_same_thread=False`, **`PRAGMA foreign_keys = ON`** issued immediately, all access through `Database` methods that hold `self._lock`. The `Api` class **must not** touch `_conn` directly.

### What NOT to do
- Do not add unit tests in v1 unless the user asks. This is a personal-use app; manual acceptance is sufficient.
- Do not write a CI config.
- Do not add a license file unless asked.
- Do not auto-update or telemetry.
- Do not refactor across phase boundaries — each phase builds on the last as-is.
- Do not introduce abstractions for "future flexibility" (e.g. backend protocol). v1 is Gemini-only. Pluggable backend deferred to v2.

---

## Phase summary checklist

- [ ] Phase 0 — Project scaffolding
- [ ] Phase 1 — Tray + hotkey
- [ ] Phase 2 — Audio capture + VAD
- [ ] Phase 3 — Gemini integration
- [ ] Phase 4 — SQLite + intent application
- [ ] Phase 5 — React UI
- [ ] Phase 6 — Settings & onboarding
- [ ] Phase 7 — Packaging

Each phase has a hard stop. The implementing agent must report and wait for "continue" before starting the next.
