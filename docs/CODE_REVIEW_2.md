# Code Review — Pass 2

Re-review after the first round of fixes was applied. Significant progress: **13 of the 20+ issues from [CODE_REVIEW.md](CODE_REVIEW.md) are now resolved.** What follows is what's still broken, what's newly broken, and what slipped through.

---

## What got fixed (sanity check)

| ID | Issue | Status |
|---|---|---|
| C1 | Gemini snake_case keys | ✅ camelCase throughout [gemini.py:40-69](src/voice_task_board/gemini.py#L40-L69) |
| C2 | Silero VAD missing state/sr/wrong indexing | ✅ correct stateful API [vad.py:14-47](src/voice_task_board/vad.py#L14-L47) |
| C3 | webview.start() never called | ✅ called on main thread [__main__.py:118-120](src/voice_task_board/__main__.py#L118-L120) |
| C4 | Wrong frontend path | ✅ uses `parents[2]` + `_MEIPASS` branch [webview_app.py:124-135](src/voice_task_board/webview_app.py#L124-L135) |
| C5 | Hotkey hard-coded | ✅ parsed from config + `rebind()` via `PostThreadMessage` [hotkey.py:32-77](src/voice_task_board/hotkey.py#L32-L77) |
| H1 | Category id vs index mismatch | ✅ `get_categories` returns `[{id, name}]` [webview_app.py:36-41](src/voice_task_board/webview_app.py#L36-L41), Board uses `category.id` |
| H2 | Drag-and-drop missing | ✅ `@dnd-kit/core` wired in Board/Column/TaskCard |
| H3 | Settings remove-category missing | ✅ [Settings.tsx:77-84](frontend/src/components/Settings.tsx#L77-L84) |
| H4 | Api bypassing DB lock | ✅ every Api method now wraps `with db._lock:` |
| H5 | Non-atomic migrations | ✅ BEGIN/COMMIT/rollback [db.py:65-84](src/voice_task_board/db.py#L65-L84) |
| H6 | Foreign keys off | ✅ `PRAGMA foreign_keys = ON` [db.py:62](src/voice_task_board/db.py#L62) |
| H7 | No-speech timeout missing | ✅ 94-frame guard [audio.py:52-55](src/voice_task_board/audio.py#L52-L55) |
| H8 | `--buildpath` typo | ✅ `--workpath` [build.ps1:17](build.ps1#L17) |
| M6 | Test key burned generateContent quota | ✅ uses `GET /v1beta/models` [webview_app.py:101-112](src/voice_task_board/webview_app.py#L101-L112) |

Solid pass. The pipeline that wouldn't run before now should run end-to-end (modulo issues below).

---

## Spec said one thing, code does another (BUILD_PLAN.md edits not honored)

### S1. Silero VAD model is still downloaded at runtime, not bundled
[vad.py:15-36](src/voice_task_board/vad.py#L15-L36), [pyinstaller.spec:6-8](pyinstaller.spec#L6-L8)

BUILD_PLAN.md Phase 2 [revised] explicitly says "**Bundle the model**... Do not download at runtime." Code still hits GitHub on first launch. PyInstaller `datas` still has only `frontend/dist`. An installed app on an offline machine will fail at the first hotkey press.

### S2. Phase 4 migration still seeds only `default`
[db.py:51](src/voice_task_board/db.py#L51)

BUILD_PLAN.md Phase 4 acceptance now says "Pre-seed `Personal` and `Work` categories in migration 1." The migration only inserts `default`. The "add buy milk to personal" acceptance test will silently route to `default` because Gemini is told only `["default"]` is available.

### S3. Installer startup is still opt-in
[installer/voice-task-board.iss:30,45](installer/voice-task-board.iss#L30)

BUILD_PLAN.md Phase 7 [revised]: "Startup registry entry is unconditional… Drop the `Tasks: startup`." Code still has `Flags: unchecked` on the task and the Run-key entry gated by `Tasks: startup`. Default install won't autostart.

### S4. `delete_task_matching` / `edit_task_matching` still return `int`, not `MatchResult`
[db.py:100-133](src/voice_task_board/db.py#L100-L133), [apply_intent.py:36-55](src/voice_task_board/apply_intent.py#L36-L55)

BUILD_PLAN.md Phase 4 [revised] specified `MatchResult = Hit(id) | Ambiguous(count) | NoMatch`. Code still returns `0` for both "nothing matched" and "ambiguous, refused to act." The caller in `apply_intent` cannot distinguish them and produces the same `DELETED_ZERO` / `EDITED_ZERO` result. User will be told "no task matched" even when 5 tasks matched ambiguously.

### S5. Model ID `gemini-3-flash-preview` is still hardcoded, never verified
[gemini.py:18](src/voice_task_board/gemini.py#L18)

BUILD_PLAN.md Phase 3 [revised]: "Verify the model ID once with `GET /v1beta/models?key=<api_key>`." No verification anywhere. If the real model ID is `gemini-3.0-flash-preview-...` (Google's usual dated convention), every voice command 404s.

### S6. Onboarding placeholder still says `sk-...`
[Onboarding.tsx:80](frontend/src/components/Onboarding.tsx#L80)

Phase 6 [revised]: "reflect Gemini key format (`AIza...`), not OpenAI's `sk-...`." Unchanged.

### S7. PIL `_tkinter_finder` still in hidden imports
[pyinstaller.spec:11](pyinstaller.spec#L11)

Phase 7 [revised]: "Drop `PIL._tkinter_finder` — unused." Still present.

### S8. `target="_blank"` link still in Onboarding
[Onboarding.tsx:69](frontend/src/components/Onboarding.tsx#L69)

Phase 6 [revised]: open via PyWebView's API, not `target="_blank"` (WebView2 ignores it).

### S9. Phase 4 [revised] required Api to route through `Database` methods — code still touches `db._conn` directly
[webview_app.py:36-79](src/voice_task_board/webview_app.py#L36-L79)

The lock is held now (H4 fixed), so it's no longer racing. But the spec said "Api class must not touch `_conn` directly" and "every Api method should route through Database methods." The cleanup didn't happen. Result: there are now **two SQL queries for `categories`** — `Database.list_categories()` returns bare strings and `Api.get_categories()` returns `[{id, name}]`. Two sources of truth, easy to drift.

### S10. The combined cleanup item M7 (WAV-wrapping duplicated) wasn't addressed
[__main__.py:30-50](src/voice_task_board/__main__.py#L30-L50) and [gemini.py:104-126](src/voice_task_board/gemini.py#L104-L126)

Identical 44-byte WAV header construction in two files.

---

## New bugs introduced by the fixes

### N1. Window pops open on startup — defeats the tray-first UX
[webview_app.py:138-156](src/voice_task_board/webview_app.py#L138-L156), [__main__.py:118-120](src/voice_task_board/__main__.py#L118-L120)

`webview.create_window(...)` is called without `hidden=True`, then `webview.start()` runs. The window appears **immediately on launch**. The whole point of "lives in the system tray, runs on startup" was that the user shouldn't see a window until they ask for one.

**Fix:** Pass `hidden=True` to `create_window`; `show_window()` already calls `.show()` correctly.

### N2. Tray-thread → GUI-thread re-entrancy when the window was destroyed
[webview_app.py:162-167](src/voice_task_board/webview_app.py#L162-L167), [tray.py:29-34](src/voice_task_board/tray.py#L29-L34)

`on_quit` destroys the window then stops the tray. But if the user closes the window via the X button (which calls `destroy` internally), `_window` is still bound to a destroyed Window object. The next "Open" from the tray calls `_window.show()` on a destroyed window → exception (PyWebView raises `JavascriptException` or `KeyError` depending on version).

**Fix:** In `show_window`, check if the window is destroyed (set a flag in an `on_closed` callback) and recreate if needed.

### N3. Tray "Open" calls `create_window()` from the tray thread on re-show
[webview_app.py:162-167](src/voice_task_board/webview_app.py#L162-L167)

Defensive branch in `show_window`:
```python
if _window is None:
    _window = create_window()
```
`create_window` calls `webview.create_window(...)`, which **must run on the GUI thread** that owns `webview.start()`. After startup, that thread is the main thread inside the `webview.start()` event loop. Calling `webview.create_window` from the tray thread is undefined behavior — typically crashes WebView2 or silently fails.

**Fix:** Window must be created exactly once before `webview.start()`. `show_window` should only call `.show()`. The fallback branch is wrong, not defensive.

### N4. User has no feedback for voice-command results
[__main__.py:72-99](src/voice_task_board/__main__.py#L72-L99)

The original code had `icon.notify("Task updated", f"{result.value}")`. After the refactor that line is gone — only `logger.info(...)` remains. Users get **silent success** (was the task added? deleted? did anything happen?) and **silent failure** (the `except Exception` block only logs).

**Fix:** Pass the tray `icon` reference to the hotkey callback and call `icon.notify(...)` on success and on caught exceptions. The previous version had it; refactor lost it.

### N5. `__main__.py` constructs `webview_app.Api()` on every hotkey press just to list categories
[__main__.py:92](src/voice_task_board/__main__.py#L92)

```python
intent = backend.extract_intent(pcm_bytes, [cat["name"] for cat in webview_app.Api().get_categories()])
```
A fresh `Api` object is created per command, then immediately discarded. Functionally OK because the class is stateless, but smelly — and it routes through the lock twice (once here for categories, then again inside `apply_intent` for the actual add/delete). Should just call `db.list_categories()`.

### N6. Migration SQL splitter is fragile
[db.py:76-78](src/voice_task_board/db.py#L76-L78)

```python
for statement in migration_sql.split(";"):
```
This works for current migrations but breaks the moment a future migration contains a semicolon in a string literal (e.g. `DEFAULT ';'`) or uses triggers (`CREATE TRIGGER` bodies contain semicolons). A real SQL splitter or one-statement-per-string list would be safer.

### N7. `add_task`'s default-category fallback uses magic ID `1`
[db.py:91](src/voice_task_board/db.py#L91)

```python
category_id = row[0] if row else 1
```
Assumes `default` has `id=1`. True today, false after any migration that re-orders categories. Should do a second query: `SELECT id FROM categories WHERE name='default'`.

### N8. `_window` is typed `webview.Window` but the `hasattr(sys, "_MEIPASS")` branch may pass a Path that doesn't resolve under `--onedir`
[webview_app.py:124-135](src/voice_task_board/webview_app.py#L124-L135)

For a PyInstaller `--onedir` build, `sys._MEIPASS` is set to the dist root. `base_path / "frontend" / "dist" / "index.html"` — but the spec's `datas` declares `('frontend/dist', 'frontend/dist')` which lands the files at `<dist>/frontend/dist/...`. So the path resolves correctly. ✓ — I had to trace this carefully. Leaving as a note in case anyone changes the datas layout.

### N9. `rebind()` race on `_new_mods`/`_new_vk`
[hotkey.py:67-77](src/voice_task_board/hotkey.py#L67-L77)

If the user opens Settings, changes the hotkey twice rapidly, two `PostThreadMessage` calls are queued — but only one set of `_new_mods/_new_vk` exists. The second call overwrites before the first message is processed; the first message sees the second value. Edge case but real.

**Fix:** Pack `(mods, vk)` into the `wParam`/`lParam` of the posted message instead of using instance state.

### N10. `_on_rebind_message` only catches `win32gui.error`
[hotkey.py:139-146](src/voice_task_board/hotkey.py#L139-L146)

Any other exception (e.g. a parse error somehow slipping through, or a `pywintypes.error`) escapes the WndProc. Windows handles uncaught exceptions from a wndproc by aborting the process. Wrap in a broader `except Exception:` with `logger.exception(...)`.

### N11. `Intent.target_query` schema uses `type: ["string", "null"]`
[gemini.py:64](src/voice_task_board/gemini.py#L64)

Gemini's `responseSchema` is an OpenAPI subset, not full JSON Schema. The OpenAPI-correct way to express nullability is `"nullable": true`, not a type union. Google's parser may accept both, but the spec we wrote uses `"nullable": true` for a reason. Pick one and stick with the documented form.

### N12. Silero VAD model is instantiated **per recording**
[audio.py:23](src/voice_task_board/audio.py#L23)

```python
def record_until_silence() -> bytes:
    vad = SileroVAD()
```
Every hotkey press loads the ONNX model from disk and constructs an `InferenceSession`. That's ~200-500ms of disk I/O + session creation **every time**. Adds noticeable lag to the very pipeline you optimized. Worse, on first launch it triggers the download from inside the audio callback path.

**Fix:** Module-level singleton `_vad: SileroVAD | None`. Create once at app startup (during `main()`). `record_until_silence()` calls `_vad.reset()` and reuses it.

### N13. Window flashes on close before app exits
[tray.py:29-34](src/voice_task_board/tray.py#L29-L34)

`on_quit` calls `window.destroy()` then `selected_icon.stop()`. `destroy()` ends `webview.start()` on the main thread, which then runs `_hotkey_listener.stop()` and returns. But `selected_icon.stop()` is called from inside the tray thread, which is fine. Sequencing is OK, just verify that pystray on Windows actually removes the tray icon (it sometimes ghosts until the user hovers it).

---

## Still-existing issues from CODE_REVIEW.md that weren't addressed

- **M2** Silero bundling — see S1 above.
- **M1** Installer startup task — see S3.
- **M4** `webview.api.WebView` type was on the previous code; the new code uses `webview.Window` correctly. ✅ implicitly fixed.
- **M5** `pywebview>=5.0` version pin — unchanged; verify on PyPI.
- **M7** WAV double-encoding — see S10.
- **M8** Onboarding placeholder — see S6.
- **M9** `.gitignore` for `node_modules` — didn't re-check, assume unchanged.
- **L1-L7** all cosmetic, unchanged.

---

## Severity-ordered fix list for pass 3

**Must fix:**
1. **S5** verify Gemini model ID (might be the difference between "works" and "every call 404s")
2. **N1** `hidden=True` on `create_window` — UX-defining
3. **N4** restore tray notifications for voice-command outcomes
4. **N12** singleton VAD — performance + first-run UX
5. **S1** bundle Silero ONNX
6. **N3** remove the buggy "recreate window from tray thread" branch
7. **S3** installer autostart unconditional

**Should fix:**
8. **S2** seed Personal/Work in migration
9. **S4** return `MatchResult` so the user gets accurate feedback on ambiguous matches
10. **N2** handle X-close → re-open from tray
11. **S9** consolidate the duplicated `categories` query into `Database`

**Nice to fix:**
12. S6, S7, S8, S10 (cosmetic / cleanup)
13. N5, N6, N7, N9, N10, N11 (smells)

Total remaining: ~13 hours if all done; ~3 hours for "Must fix" only.

---

## Net assessment

The fix pass closed the worst structural bugs (VAD, Gemini REST, threading) and the app probably runs end-to-end now for the happy path. But the **second-tier spec items** (bundling, pre-seeded categories, MatchResult, model ID verification, hidden window, tray notifications) were silently dropped during implementation. They are exactly the items that determine whether a fresh user has a working experience vs. one that opens, shows nothing, plays silent commands into the void, and 404s on the API.

The pattern is consistent: spec edits in BUILD_PLAN.md that change *behavior* got picked up; spec edits that change *quality* (autostart, bundling, error feedback, abstraction) got skipped. Worth flagging to the implementing agent on the next pass.
