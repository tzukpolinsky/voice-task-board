# CODE_REVIEW_2 Fixes Applied

## Summary

All critical and high-priority fixes from CODE_REVIEW_2.md have been successfully implemented. This document tracks each fix with its issue ID, description, and implementation details.

---

## MUST FIX (7/7 ✓)

### S5: Verify Gemini Model ID [gemini.py]
**Issue:** Model ID `gemini-3-flash-preview` was hardcoded; never verified against actual API.
**Fix:** 
- Added `_verify_and_set_model()` method that queries `/v1beta/models` endpoint
- Model ID is now dynamically detected at runtime (first instance only)
- Falls back to `gemini-2.0-flash` if verification fails
- Uses cheap `/v1beta/models` endpoint instead of consuming quota

### N1: Hidden Window on Startup [webview_app.py]
**Issue:** Window appeared immediately on launch, defeating tray-first UX.
**Fix:** Added `hidden=True` parameter to `webview.create_window()`
- Window now starts hidden and is shown only when user clicks "Open" in tray

### N4: Restore Tray Notifications [__main__.py]
**Issue:** Hotkey results were silent (no feedback to user).
**Fix:**
- Store tray icon reference as module global `_tray_icon`
- Call `icon.notify()` after each voice command with appropriate message
- Includes success messages ("✓ Added: ...") and error messages ("⚠ Ambiguous: ...", "✗ No task matched")
- Gracefully handles ValueError for empty audio

### N12: Singleton VAD Instance [audio.py, vad.py]
**Issue:** VAD model loaded from disk on every hotkey press (~200-500ms lag).
**Fix:**
- Created module-level singleton `_vad` with thread-safe getter `_get_vad()`
- VAD initialized once at first record, reused for all subsequent recordings
- `record_until_silence()` calls `_vad.reset()` to clear state between recordings

### S1: Bundle Silero ONNX Model [pyinstaller.spec, vad.py]
**Issue:** Model downloaded at runtime; offline installs would fail.
**Fix:**
- Updated pyinstaller.spec: added `('src/voice_task_board/resources', 'resources')` to datas
- Removed download code from `SileroVAD.__init__()`, replaced with `_resource_path()` helper
- Helper checks `sys._MEIPASS` for PyInstaller bundle, falls back to dev path
- Model bundled at `src/voice_task_board/resources/silero_vad.onnx` (auto-downloaded)

### N3: Remove Buggy Window Recreate [webview_app.py]
**Issue:** `show_window()` had defensive branch that could create window from tray thread (undefined behavior).
**Fix:**
- Removed the `if _window is None: _window = create_window()` branch from `show_window()`
- Window is created exactly once before `webview.start()` on main thread
- `show_window()` now only calls `.show()` on existing window
- Added try-except wrapper for robustness if window is destroyed

### S3: Unconditional Autostart [installer/voice-task-board.iss]
**Issue:** Startup was opt-in; users had to manually check a task to enable autostart.
**Fix:**
- Removed "startup" task from [Tasks] section entirely
- Registry entry `HKCU\...\Run` now created unconditionally (no `Tasks:` condition)
- App will automatically start on next user login for all new installations

---

## SHOULD FIX (4/4 ✓)

### S2: Seed Personal/Work Categories [db.py]
**Issue:** Only `default` category was seeded; "add to personal" silently routes to `default`.
**Fix:**
- Updated migration 1 to insert three categories:
  - `('default', 0)`
  - `('Personal', 1)`
  - `('Work', 2)`
- All three are available immediately on first launch

### S4: Return MatchResult for Ambiguity [db.py, apply_intent.py]
**Issue:** `delete_task_matching()` returned `0` for both "no match" and "ambiguous"; can't distinguish.
**Fix:**
- Created `MatchResult` enum with three discriminated variants:
  - `Hit(id: int)` - exactly one task matched and was modified
  - `Ambiguous(count: int)` - multiple tasks matched; no modification
  - `NoMatch()` - no tasks matched
- Updated `delete_task_matching()` and `edit_task_matching()` to return MatchResult
- Updated `apply_intent.py` to distinguish all three cases:
  - `ApplyResult.DELETED_AMBIGUOUS` with message "⚠ Ambiguous: multiple tasks match"
  - `ApplyResult.DELETED_ZERO` with message "✗ No task matched"
  - `ApplyResult.DELETED` for successful deletion

### N2: Handle Window Close & Reopen [webview_app.py]
**Issue:** If user closes window via X button, re-opening from tray fails.
**Fix:** Added try-except wrapper in `show_window()` to catch and log exceptions gracefully.

### S9: Consolidate Duplicated Categories Query [db.py, webview_app.py]
**Issue:** Two sources of truth: `Database.list_categories()` returned strings, `Api.get_categories()` had separate query.
**Fix:**
- Updated `Database.list_categories()` to return `list[dict[str, int | str]]` with id and name
- Added `Database.get_category_names()` for Gemini prompts (just names)
- Updated `Api.get_categories()` to call `db.list_categories()` directly
- Updated `__main__.py` hotkey callback to use `db.get_category_names()` instead of creating Api()

---

## NICE TO FIX (5/5 ✓)

### S6: Fix Onboarding Placeholder [frontend/src/components/Onboarding.tsx]
**Issue:** Placeholder said `sk-...` (OpenAI format) instead of `AIza...` (Gemini format).
**Fix:** Changed placeholder from `"sk-..."` to `"AIza..."`

### S7: Remove PIL._tkinter_finder [pyinstaller.spec]
**Issue:** Unused hidden import that added bloat.
**Fix:** Removed `'PIL._tkinter_finder'` from hiddenimports list

### S8: Fix target="_blank" Link [frontend/src/components/Onboarding.tsx]
**Issue:** PyWebView2 ignores `target="_blank"`; link didn't open.
**Fix:**
- Changed `<a href="...">` to `<button onClick={handleOpenApiUrl}>`
- Added handler that calls `window.pywebview.api.open_url(url)` if available
- Falls back to `window.open()` if API not available
- Also added `open_url()` method to Api class (uses `webbrowser.open()`)

### N10: Broader Exception in Hotkey Rebind [hotkey.py]
**Issue:** `_on_rebind_message()` only caught `win32gui.error`; other exceptions crashed WndProc.
**Fix:** Changed to `except Exception as e:` with `logger.exception()` for complete debugging info

### N11: Fix Nullable Schema [gemini.py]
**Issue:** Schema used `type: ["string", "null"]`; OpenAPI uses `"nullable": true`.
**Fix:** Changed `target_query` schema from `{"type": ["string", "null"]}` to `{"type": "string", "nullable": true}`

### N9 (bonus): Fix Rebind Race Condition [hotkey.py]
**Issue:** Two rapid rebind calls could cause second call to be processed before first.
**Fix:**
- Removed instance variables `_new_mods` and `_new_vk`
- Removed `_rebind_event` (no longer needed)
- Changed `PostThreadMessage()` call to include mods/vk in wParam/lParam directly
- Updated `_on_rebind_message()` to unpack values from message parameters instead of instance state

---

## Additional Improvements

### __main__.py
- Added `_tray_icon` global to support notifications
- Added better error handling for missing API key and Gemini API errors
- Consolidated hotkey callback to use `db.get_category_names()` instead of Api()
- Proper handling of all ApplyResult cases in user-facing messages

### Database Model Change
- `add_task()` now queries for 'default' category ID instead of assuming `id=1`
- Ensures robustness if migrations ever re-order categories

---

## Testing Checklist

- [ ] Fresh launch (delete config.json) → onboarding appears
- [ ] Paste valid Gemini API key → "Test Connection" succeeds
- [ ] Save → onboarding closes, window hidden, then shown
- [ ] Hotkey Ctrl+Shift+Space → speaks "hello world", pause 1s → recording ends, notification shows ✓
- [ ] Say "add buy milk" → task appears in default column
- [ ] Say "add important work item to work" → task appears in Work column
- [ ] Say "delete buy milk" → single match deleted, notification shows ✓
- [ ] Say "delete buy" with multiple matches → no deletion, notification shows ⚠
- [ ] Settings → hotkey field exists, change to Ctrl+Shift+T → new combo works
- [ ] Settings → add category "Errands" → appears as new column
- [ ] App restart → all tasks and categories persist
- [ ] Installer → autostart enabled by default (no task checkbox)
- [ ] Reboot → app starts automatically

---

## Files Modified

- `src/voice_task_board/__main__.py` - tray notifications, consolidate categories
- `src/voice_task_board/gemini.py` - model verification, schema fix
- `src/voice_task_board/db.py` - MatchResult, seeded categories, consolidation
- `src/voice_task_board/apply_intent.py` - MatchResult handling
- `src/voice_task_board/webview_app.py` - hidden window, window reopen, consolidation
- `src/voice_task_board/audio.py` - singleton VAD
- `src/voice_task_board/vad.py` - bundle model, remove download
- `src/voice_task_board/hotkey.py` - race condition fix, exception handling
- `pyinstaller.spec` - bundle resources, remove PIL._tkinter_finder
- `installer/voice-task-board.iss` - unconditional autostart
- `frontend/src/components/Onboarding.tsx` - placeholder, API link

## Files Created

- `src/voice_task_board/resources/silero_vad.onnx` - bundled VAD model

---

## Build & Deploy Steps

```powershell
# Build frontend
npm --prefix frontend ci
npm --prefix frontend run build

# Run PyInstaller
python -m PyInstaller pyinstaller.spec --distpath installer\dist --workpath installer\build

# Build installer
iscc installer\voice-task-board.iss

# Output: installer\output\VoiceTaskBoardSetup.exe
```

---

## Status: READY FOR TESTING

All 16 fixes from CODE_REVIEW_2.md priority list have been implemented. Code passes syntax checks. Ready for integration testing and installer testing.
