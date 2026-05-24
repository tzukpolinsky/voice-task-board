# Code Review — Voice Task Board (post-build)

Review of the implemented code against `docs/BUILD_PLAN.md`. Issues are ordered by severity; each has a file:line reference, what's wrong, why it matters, and how to fix.

**Verdict:** the app **will not work end-to-end as written**. There are at least 5 fatal bugs that prevent the core voice pipeline from producing a working result, plus another 5 that will hit on first interaction with the UI or installer. Fix the Critical and High items before any further work.

---

## Critical (will not work at all)

### C1. Gemini REST payload uses snake_case — API ignores config
[src/voice_task_board/gemini.py:40-69](src/voice_task_board/gemini.py#L40-L69)

The request body uses `generation_config`, `response_mime_type`, `response_schema`, `inline_data`, `mime_type`. The Gemini REST API uses **camelCase**: `generationConfig`, `responseMimeType`, `responseSchema`, `inlineData`, `mimeType`.

**Effect:** Gemini will silently ignore the response schema and MIME type, return free-form text (often with prose/markdown around the JSON), and `json.loads(text)` will throw. Audio may still be processed via `inline_data` (Google accepts both casings for *some* fields but not consistently), but structured output is dead.

**Fix:** Rename every key in the request body to camelCase.

### C2. Silero VAD call is missing required inputs and parses output wrong
[src/voice_task_board/vad.py:33-38](src/voice_task_board/vad.py#L33-L38)

```python
input_data = {self._session.get_inputs()[0].name: frame_float32}
output = self._session.run(None, input_data)
confidence = float(output[0][0][1])
```

Three bugs in 5 lines:
1. **Missing inputs.** Silero v5 ONNX requires `input`, `state` (shape `[2,1,128]`, persisted across calls), and `sr` (int64). The code passes only one input. ONNX Runtime will raise `InvalidArgument: Missing Input: state` on the first call.
2. **Wrong frame shape.** Silero expects `[batch=1, samples=512]`. The code passes `[512]`.
3. **Wrong output indexing.** Silero outputs a scalar speech probability, shape `[1,1]`. `output[0][0][1]` is an IndexError; should be `output[0][0][0]` (or `.item()`).

**Effect:** First hotkey press throws and aborts recording. Has never worked.

**Fix:** Carry recurrent state as an instance attribute, reshape frame to `[1,512]`, pass `sr` as `np.array(16000, dtype=np.int64)`, and read `output[0].item()`.

### C3. PyWebView window never displays
[src/voice_task_board/webview_app.py:105-126](src/voice_task_board/webview_app.py#L105-L126), [src/voice_task_board/__main__.py:96-101](src/voice_task_board/__main__.py#L96-L101)

`start_window()` calls `webview.create_window(...)` but **never calls `webview.start()`**. `webview.start()` is the function that actually creates the OS window and runs the GUI event loop. Without it, `create_window` just registers a window object that never opens.

Compounding this: `webview.start()` *must* run on the main thread, but the main thread is owned by `icon.run()` (pystray's event loop). Calling `start_window()` from the tray menu callback runs in the pystray thread, which can't drive a webview.

**Effect:** "Open" menu item does nothing visible. The entire UI is unreachable.

**Fix:** Invert the threading model. Main thread runs `webview.start(...)` with the window hidden. pystray runs in a daemon thread. "Open" menu calls `_window.show()` on the existing window. (Or `_window.minimize()`/`restore()` to toggle.)

### C4. Frontend path is wrong (3 vs 2 `.parent` calls)
[src/voice_task_board/webview_app.py:108](src/voice_task_board/webview_app.py#L108)

```python
html_path = Path(__file__).parent.parent / "frontend" / "dist" / "index.html"
```

`__file__` is `<root>/src/voice_task_board/webview_app.py`.  
`parent.parent` is `<root>/src/`, so the computed path is `<root>/src/frontend/dist/index.html` — a path that doesn't exist. The real frontend is at `<root>/frontend/dist/index.html`.

**Effect:** Even after fixing C3, the `if not html_path.exists()` guard fires, logs an error, and returns. Window still never shows.

**Fix:** `Path(__file__).parent.parent.parent / "frontend" / "dist" / "index.html"`. After PyInstaller bundling, this path is wrong anyway — see I3.

### C5. Hotkey is hard-coded; config changes are ignored
[src/voice_task_board/hotkey.py:50](src/voice_task_board/hotkey.py#L50)

```python
win32gui.RegisterHotKey(self._hwnd, HOTKEY_ID, win32con.MOD_CONTROL | win32con.MOD_SHIFT, 0x20)
```

The hotkey is literally `Ctrl+Shift+Space` in code. `config.hotkey` is loaded, saved, displayed in Settings, and edited by the user — but never parsed or applied. Even a restart won't change the actual binding.

Additionally, the Settings UI saves changes via [webview_app.py:76-83](src/voice_task_board/webview_app.py#L76-L83), but there is no IPC to the running `HotkeyListener` to unregister and re-register. Phase 6 acceptance ("change hotkey → old combo no longer triggers, new combo does") cannot pass.

**Fix:** Parse `config.hotkey` into mods + vk (small lookup table). `HotkeyListener.rebind(new_combo)` posts a custom thread message that unregisters and re-registers. `Api.set_hotkey` calls it.

---

## High (broken UX even after Critical fixes)

### H1. Kanban columns can never show any tasks
[frontend/src/components/Board.tsx:80-88](frontend/src/components/Board.tsx#L80-L88), [frontend/src/components/Column.tsx:13](frontend/src/components/Column.tsx#L13)

`Board` passes `categoryId={idx}` (the array index of the category in `list_categories()`). `Column` then filters tasks with `t.category_id === categoryId`. But `t.category_id` is the **SQLite row ID** of the category (1, 2, 3, possibly with gaps after deletions), not an index.

**Effect:** For the seeded `default` category at row id 1 with index 0, the filter is `1 === 0` — false. **No tasks ever appear in any column.**

**Fix:** Add a `getCategoriesWithIds()` API method that returns `[{id, name}]`. Use `category.id` in the column key and filter.

### H2. Drag-and-drop was never implemented
[frontend/package.json:11-14](frontend/package.json#L11-L14), [frontend/src/components/TaskCard.tsx](frontend/src/components/TaskCard.tsx)

`@dnd-kit/core` is not in dependencies. `TaskCard` has `cursor: 'grab'` styling but no drag handlers. There is no `onDrop` anywhere. Phase 5 acceptance ("Drag a task from one column to another → DB row updates") is not implemented.

**Fix:** Add `@dnd-kit/core` + `@dnd-kit/sortable`, wire `DndContext` in Board, wire droppable Columns and draggable TaskCards, call `move_task` on drop end.

### H3. Settings.tsx has no "remove category" — and `move_task` API uses wrong id type
[frontend/src/components/Settings.tsx:157-195](frontend/src/components/Settings.tsx#L157-L195), [src/voice_task_board/webview_app.py:54-61](src/voice_task_board/webview_app.py#L54-L61)

Spec required "category list with add/remove". Only Add is implemented; categories are rendered as static labels.

Separately, `move_task(task_id, category_id)` is exposed but unreachable because (a) DnD isn't wired and (b) the frontend doesn't know category row IDs (see H1).

### H4. UI bypasses the DB lock — data races guaranteed
[src/voice_task_board/webview_app.py:38-67](src/voice_task_board/webview_app.py#L38-L67)

`add_category`, `delete_category`, `move_task`, `delete_task` all do `db._conn.cursor()` and commit directly, **bypassing `db._lock`**. The recording thread holds the lock through `add_task`/`delete_task_matching`/etc. The JS API thread does not.

**Effect:** A voice command running concurrently with a UI drag or settings edit can race on `_conn`. SQLite under `check_same_thread=False` without external locking risks `database is locked` errors or interleaved transactions.

**Fix:** Move every UI-side mutation into proper `Database` methods that take `self._lock`. The `Api` class should never touch `db._conn` directly.

### H5. Migrations are not atomic — a crash mid-run permanently breaks the DB
[src/voice_task_board/db.py:64-75](src/voice_task_board/db.py#L64-L75)

```python
cursor.executescript(migration_sql)
cursor.execute(f"PRAGMA user_version = {version}")
self._conn.commit()
```

`executescript` issues an implicit COMMIT before running, then runs the script outside any transaction. If the process dies after `executescript` finishes but before the PRAGMA update, the tables exist but `user_version` stays at 0. Next launch will try to re-CREATE the same tables and crash with "table categories already exists." DB is then unusable.

**Fix:** Use `conn.execute("BEGIN")` then `for stmt in migration.split(';'): cursor.execute(stmt)` then `PRAGMA user_version = X` then `COMMIT`. Or use `conn:` context-manager transactions and skip `executescript`.

### H6. Foreign keys are off — `delete_category` will orphan tasks
[src/voice_task_board/db.py:60](src/voice_task_board/db.py#L60), [src/voice_task_board/webview_app.py:48-52](src/voice_task_board/webview_app.py#L48-L52)

SQLite defaults to `PRAGMA foreign_keys = OFF`. The `REFERENCES categories(id)` constraint in the schema is decorative only. `delete_category` succeeds even when tasks reference the deleted category, leaving zombie `category_id` values that violate the implied invariant and break `list_tasks`'s INNER JOIN.

**Fix:** On every connection, run `PRAGMA foreign_keys = ON` immediately after `connect()`.

### H7. No "no-speech" timeout — silent press records for 30 seconds
[src/voice_task_board/audio.py:40-56](src/voice_task_board/audio.py#L40-L56)

The trailing-silence counter only starts after `speech_detected = True`. If the user presses the hotkey and never speaks, `speech_detected` stays False, `silence_frames` is never incremented, and the loop runs to the `_MAX_FRAMES` cap (~30s). Phase 2 acceptance ("Press hotkey, stay silent → recording ends after ~1s") fails.

**Fix:** Add a "no speech seen" frame counter; abort after ~3s if `speech_detected` is still False.

### H8. Build script uses a non-existent PyInstaller flag and a wrong --specpath
[build.ps1:17](build.ps1#L17)

```powershell
.\.venv\Scripts\pyinstaller.exe pyinstaller.spec --distpath installer\dist --buildpath installer\build --specpath installer
```

- `--buildpath` is **not** a PyInstaller flag. The correct flag is `--workpath`. PyInstaller will error on unknown option.
- `--specpath` controls **where to *generate* a spec file**, not where to find an existing one. Passing both an explicit spec file (`pyinstaller.spec`) and `--specpath installer` is contradictory.

**Effect:** `build.ps1` fails immediately on step 2.

**Fix:** `pyinstaller pyinstaller.spec --distpath installer\dist --workpath installer\build`.

---

## Medium

### M1. Installer's startup task is opt-in but the spec requires opt-out
[installer/voice-task-board.iss:30](installer/voice-task-board.iss#L30), [installer/voice-task-board.iss:45](installer/voice-task-board.iss#L45)

```ini
Name: "startup"; Description: "Run at startup"; ... Flags: unchecked
```

The user explicitly required the app to run on startup by default. The current installer hides startup behind an unchecked checkbox, and the `HKCU\...\Run` registry entry only fires when that checkbox is checked.

**Fix:** Remove `Flags: unchecked` from the startup task, or drop the task gate and always write the registry value.

### M2. Silero VAD model isn't bundled — installer-built app needs internet on first run
[pyinstaller.spec:6-8](pyinstaller.spec#L6-L8), [src/voice_task_board/vad.py:22-31](src/voice_task_board/vad.py#L22-L31)

The PyInstaller `datas` includes only `frontend/dist`. `silero_vad.onnx` is downloaded by `vad.py` on first use. For an installer-shipped binary on an offline-first-launch machine, the download will fail and recording will throw. BUILD_PLAN.md Phase 7 explicitly said to bundle.

**Fix:** Download `silero_vad.onnx` once during build, place it at a known path, add it to `datas`, and have `SileroVAD` prefer the bundled copy.

### M3. Type hints reference symbols that may not exist
[src/voice_task_board/audio.py:31](src/voice_task_board/audio.py#L31)

`sd.CallbackTimeData` is not a real sounddevice attribute. The callback's `time` parameter is a `CData` struct without an exported type alias. mypy is silenced for `sounddevice` ([pyproject.toml:37](pyproject.toml#L37)), so this slips through static checks, but anyone reading the code is misled.

**Fix:** Type it as `Any` with a comment, or drop the annotation.

### M4. `webview.api.WebView` is not a real type
[src/voice_task_board/webview_app.py:102](src/voice_task_board/webview_app.py#L102)

The pywebview Window object is `webview.Window`, not `webview.api.WebView`. Works at runtime only because `from __future__ import annotations` makes it a string. mypy is set strict but ignored for missing imports; if anyone fixes that, this will error.

### M5. `pywebview>=5.0` may not exist on PyPI
[pyproject.toml:18](pyproject.toml#L18)

Latest released `pywebview` series at the time of writing is 5.x but the floor `>=5.0` was set without verification. If 5.0 specifically was never published the resolver may pick something unexpected, or `pip install` will fail. Worth verifying with `pip index versions pywebview`.

### M6. `test_gemini_key` burns a real API call (and free-tier quota) per Test
[src/voice_task_board/webview_app.py:85-93](src/voice_task_board/webview_app.py#L85-L93)

Each click of "Test Connection" sends a real multimodal request (1s of silence). On free tier, that consumes one of the daily allotment. Onboarding users who click Test repeatedly can hit RPD limits and think their key is bad.

**Fix:** Use a tiny text-only `models/{model}:countTokens` call (cheap, no quota burn) to verify auth, or just GET `models` list.

### M7. WAV is encoded twice
[src/voice_task_board/__main__.py:23-50](src/voice_task_board/__main__.py#L23-L50), [src/voice_task_board/gemini.py:104-126](src/voice_task_board/gemini.py#L104-L126)

Identical WAV-header construction lives in both `__main__._save_wav` and `GeminiBackend._wrap_pcm_as_wav`. The same 44-byte header is built twice per voice command. Not a bug, but ripe for one when the two diverge.

**Fix:** Move WAV wrapping into a single helper in `audio.py` and import it from both sites.

### M8. Onboarding placeholder suggests OpenAI keys
[frontend/src/components/Onboarding.tsx:80](frontend/src/components/Onboarding.tsx#L80)

`placeholder="sk-..."` is the OpenAI key format. Gemini keys start with `AIza...`. Misleading.

### M9. `frontend` and `node_modules` aren't gitignored
Project layout shows `frontend/node_modules/...` returned by Glob. `.gitignore` (120 bytes) likely doesn't cover it. Will explode the repo on first commit.

---

## Low / cosmetic

### L1. Singleton `Database` swallows env var on rerun
[src/voice_task_board/config.py:30-35](src/voice_task_board/config.py#L30-L35)

`Config._load` reads `GEMINI_API_KEY` only when no config file exists, then writes an empty file. After the first run, env-var-supplied keys are lost. Surprise behavior for devs who set the env var.

### L2. `idx_tasks_title` cannot help `LIKE '%...%'` searches
[src/voice_task_board/db.py:47](src/voice_task_board/db.py#L47)

A B-tree index can't accelerate leading-wildcard `LIKE`. The index is wasted disk and write cost. Not a bug, but a misleading "we have search performance" signal.

### L3. `PIL._tkinter_finder` hidden import is unused
[pyinstaller.spec:11](pyinstaller.spec#L11)

`ImageTk` is never imported. Drop it.

### L4. AppId GUID has a stray brace
[installer/voice-task-board.iss:7](installer/voice-task-board.iss#L7)

`AppId={{3F4F3D3C-3B3A-3938-3736-353433323130}` — Inno parses `{{` as a literal `{`, so AppId ends up `{<guid>}`, but the asymmetry (`{{` open, `}` close) reads as a typo. Use `{{<guid>}}` for clarity.

### L5. `target="_blank"` doesn't work in WebView2
[frontend/src/components/Onboarding.tsx:69](frontend/src/components/Onboarding.tsx#L69)

PyWebView's WebView2 has no popup window support. The "aistudio.google.com" link will either open in the same view (losing the onboarding state) or do nothing. Use `webview.api` to open in the default browser.

### L6. `icon.notify` is unreliable on Windows
Throughout `__main__.py`. pystray's `notify` uses balloon tips which Windows 10/11 often suppresses or routes oddly. Consider `winrt.windows.ui.notifications` toasts for important user feedback.

### L7. `Api` is instantiated twice
[src/voice_task_board/webview_app.py:118-123](src/voice_task_board/webview_app.py#L118-L123)

`js_api=Api()` and then `_window.expose(Api())` create two distinct instances. The methods are stateless so it works, but it's a footgun if anyone adds instance state.

---

## Inconsistencies between code and BUILD_PLAN.md

1. **Drag-and-drop** required by Phase 5 — not implemented (H2).
2. **Bundle vs download Silero** — plan says bundle in Phase 7; code downloads at runtime (M2).
3. **Hotkey rebinding at runtime** required by Phase 6 — not implemented (C5).
4. **Remove category** required by Phase 6 — not implemented (H3).
5. **Acceptance "stay silent → ends after ~1s"** for Phase 2 — fails because no-speech timeout missing (H7).
6. **Pre-seed Personal/Work categories** implied by Phase 4 acceptance — only `default` is seeded; "add buy milk to personal" will route to `default` silently.
7. **`delete_task_matching` ambiguity signal** — current return type `int` cannot distinguish "deleted 0" from "ambiguous, did nothing" (matches the original BUILD_PLAN.md flaw I called out earlier — the implementation faithfully reproduced the ambiguous spec).

---

## Recommended fix order

1. **C2** (VAD) and **C1** (Gemini camelCase) — without these, nothing works. ~1 hour combined.
2. **C3 + C4** (PyWebView lifecycle and path) — without these, the UI is unreachable. ~2 hours.
3. **H7** (no-speech timeout) — small fix, big UX impact. ~15 minutes.
4. **H4 + H5 + H6** (DB safety: locking, atomic migrations, foreign keys) — before any user data accumulates. ~1 hour.
5. **H1** (category id mismatch) — UI shows nothing without it. ~30 minutes.
6. **H8** (build script flags) — needed to ship. ~5 minutes.
7. **C5** (hotkey rebind) and **H2** (drag-drop) and **H3** (category remove) — feature-complete vs. plan. ~3-4 hours combined.
8. **M1-M9** — sweep before first release.

Total to get a working v1: ~6-9 hours of focused work.
