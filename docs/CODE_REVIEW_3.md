# Code Review — Pass 3 (Status report)

Re-review after Haiku's claimed fixes in [FIXES_APPLIED.md](FIXES_APPLIED.md). Trust-but-verify pass: I read every changed file and ran two sanity checks against the live code.

**Headline: ~95% there.** The app should now run end-to-end on the happy path. Remaining issues are quality/polish (3 high-ish, ~8 minor). One claim in FIXES_APPLIED.md is overstated, and a couple of items the doc says are fixed are *technically* fixed but with caveats worth flagging.

---

## Verified-fixed (matches the claims)

I confirmed each of these by reading the actual code, not by trusting the doc:

| ID | Verification |
|---|---|
| **S5** Model ID verified | `_verify_and_set_model` in [gemini.py:25-54](src/voice_task_board/gemini.py#L25-L54) hits `/v1beta/models`, picks first "flash"+"preview" match, falls back to `gemini-2.0-flash`. |
| **N1** Window hidden on startup | `hidden=True` at [webview_app.py:155](src/voice_task_board/webview_app.py#L155). ✓ |
| **N4** Tray notifications restored | All 8 `ApplyResult` cases handled with distinct messages in [__main__.py:104-122](src/voice_task_board/__main__.py#L104-L122). |
| **N12** VAD singleton | `_vad` module-level + `_get_vad()` double-checked locking at [audio.py:21-32](src/voice_task_board/audio.py#L21-L32). ✓ |
| **S1** Silero bundled | File exists at `src/voice_task_board/resources/silero_vad.onnx` (2.3MB, verified on disk). Spec includes it via `('src/voice_task_board/resources', 'resources')`. `vad.py` no longer downloads. ✓ |
| **N3** Removed buggy "recreate from tray thread" branch | [webview_app.py:168-174](src/voice_task_board/webview_app.py#L168-L174) — `show_window` just calls `.show()`, no recreate. ✓ |
| **S3** Autostart unconditional | Registry entry at [voice-task-board.iss:44](installer/voice-task-board.iss#L44) has no `Tasks:` gate. `Tasks: startup` removed. ✓ |
| **S2** Personal/Work seeded | [db.py:67-68](src/voice_task_board/db.py#L67-L68) inserts both. ✓ |
| **S4** MatchResult discriminated type | I instantiated `MatchResult.Hit(id=42)`, `MatchResult.NoMatch()`, and `isinstance` checks all work at runtime. `apply_intent.py` correctly distinguishes all three cases. ✓ |
| **N2** Window close+reopen | try/except in `show_window` swallows destroyed-window errors. Survives but doesn't recreate (see open issue O2). |
| **S9** Categories consolidated | `Database.list_categories()` now returns `[{id, name}]`, `get_category_names()` for prompts. `Api.get_categories` delegates. ✓ |
| **S6** Placeholder `AIza...` | [Onboarding.tsx:101](frontend/src/components/Onboarding.tsx#L101) ✓ |
| **S7** PIL hidden import removed | [pyinstaller.spec:10-14](pyinstaller.spec#L10-L14) ✓ |
| **S8** Onboarding link opens via API | Button with `handleOpenApiUrl` + `Api.open_url` using `webbrowser.open`. ✓ |
| **N9** Rebind race | mods/vk now packed into wParam/lParam at [hotkey.py:73](src/voice_task_board/hotkey.py#L73), unpacked in handler. ✓ |
| **N10** Broader exception in WndProc | `except Exception as e:` with `logger.exception` at [hotkey.py:132-141](src/voice_task_board/hotkey.py#L132-L141). ✓ |
| **N11** Nullable schema | `{"type": "string", "nullable": True}` at [gemini.py:99](src/voice_task_board/gemini.py#L99). ✓ |
| **add_task fallback** | Now queries for default by name, not assuming id=1. [db.py:111-113](src/voice_task_board/db.py#L111-L113). ✓ |

---

## Remaining issues

### High-ish

#### R1. Model verification runs on the first hotkey press, adding latency to the most-noticed command
[gemini.py:23](src/voice_task_board/gemini.py#L23), [__main__.py:94](src/voice_task_board/__main__.py#L94)

`GeminiBackend(api_key)` is constructed inside the hotkey callback, and `__init__` calls `_verify_and_set_model` which makes an HTTP round-trip. So the very first voice command after launch takes an extra ~500–1500ms before any audio is sent. UX-defining moment.

**Fix:** Construct `GeminiBackend` once at app startup, after the API key is known (right after `get_config()` in `main()`). Reuse the instance.

#### R2. Model-picker heuristic may select the wrong model
[gemini.py:43-47](src/voice_task_board/gemini.py#L43-L47)

```python
candidates = [m for m in model_ids if "flash" in m.lower() and "preview" in m.lower()]
if candidates:
    GeminiBackend._model = candidates[0]
```

Google's `/v1beta/models` list typically includes things like `gemini-2.5-flash-preview-09-2025`, `gemini-3.0-flash-preview-12-2025`, `gemini-3.1-flash-preview-...`, and TTS/Live variants. **First match wins** — that could be a TTS-flash-preview, an older 2.5 preview, or anything else. There's no version preference and no exclusion of audio-only/TTS variants.

**Fix:** Add scoring: prefer higher version numbers (`3.x > 2.x`), exclude `tts`/`live`/`lite` substrings, prefer `instruct`/`generate` variants. Or: explicitly look for the exact model ID first, fall back to scored heuristic.

#### R3. `_tray_icon: any = None` — uses `builtins.any` (function), not `typing.Any`
[__main__.py:24](src/voice_task_board/__main__.py#L24)

```python
_tray_icon: any = None
```

`any` is the built-in. Works at runtime because of `from __future__ import annotations` (stringified), but the type is **literally wrong** — it annotates the variable as the `any` function. Mypy in strict mode catches it.

**Fix:** `from typing import Any` (already imported elsewhere in the codebase) → `_tray_icon: Any = None`. Three-character fix.

### Medium

#### R4. Window closes via X button → tray "Open" silently does nothing
[webview_app.py:168-174](src/voice_task_board/webview_app.py#L168-L174)

The try/except for N2 only logs the error. If a user closes the window via the X button, `_window` is destroyed; subsequent "Open" calls log a warning and the window doesn't reappear. FIXES_APPLIED.md called this "handled," but "handled" here means "doesn't crash." User-facing: the Open button stops working.

**Fix:** On window-close, instead of letting it destroy, hook PyWebView's `closed` event to call `.hide()` instead. Or subscribe to `events.closed` and re-create the window. Simplest: just call `.hide()` from a close handler, never destroy until app exit.

#### R5. `api.ts` declares `set_hotkey` that the Python `Api` no longer has
[frontend/src/api.ts:14](frontend/src/api.ts#L14)

```ts
set_hotkey: (combo: string) => Promise<void>
```

Python `Api` only has `save_config(...)`, which handles both fields. `set_hotkey` was never re-added. Currently unused (nothing calls it), but it's a stale declaration in a public interface.

**Fix:** Remove the line from `api.ts`.

#### R6. `_verify_and_set_model` duplicates the `/models` call that `test_gemini_key` already made
[webview_app.py:98-109](src/voice_task_board/webview_app.py#L98-L109), [gemini.py:30-36](src/voice_task_board/gemini.py#L30-L36)

During onboarding: user clicks Test → `Api.test_gemini_key` hits `/models` (success). User saves, presses hotkey, `GeminiBackend.__init__` hits `/models` *again*. Two identical calls. Each one burns a free-tier request.

**Fix:** Have `test_gemini_key` set `GeminiBackend._model` directly when it succeeds, so the lazy verification on first command is a no-op.

#### R7. `Api.delete_category` doesn't surface foreign-key errors
[webview_app.py:51-59](src/voice_task_board/webview_app.py#L51-L59), [Settings.tsx:77-84](frontend/src/components/Settings.tsx#L77-L84)

`PRAGMA foreign_keys = ON` is now correctly set, so `DELETE FROM categories WHERE id=?` raises `sqlite3.IntegrityError` if any task references it. The exception bubbles to JS as a generic error, frontend does `console.error`, user sees nothing — the category appears not to be deletable but no message explains why.

**Fix:** Catch `IntegrityError` in `Api.delete_category`, return a structured `{ok: false, reason: "category_in_use"}`; frontend shows a toast/alert.

#### R8. `Api.{add_category, delete_category, move_task, delete_task}` still write SQL inline
[webview_app.py:40-76](src/voice_task_board/webview_app.py#L40-L76)

S9 was partially done — `get_categories` now delegates to `Database.list_categories`. But the four mutation methods still grab `db._lock` + `db._conn` directly and write SQL. The spec said "every Api method should route through Database methods." Two query sites for the same operations means two places to keep in sync.

**Fix:** Add `Database.add_category(name)`, `delete_category(id)`, `move_task(task_id, category_id)`, `delete_task(task_id)` methods. Have `Api` just call them.

### Cosmetic

- **R9.** `installer/voice-task-board.iss:7` — `AppId={{3F4F3D3C-...}` still has unbalanced braces (open `{{`, close single `}`). Inno parses it as `{<guid>}` due to `{{` being a literal `{`, but it reads wrong. Use `{{<guid>}}`.
- **R10.** WAV-header construction is still duplicated in `__main__.py` and `gemini.py` (M7/S10). Not a bug, just smell.
- **R11.** Migration splitter uses naive `split(";")` — still fragile if a future migration uses triggers or string literals with semicolons. Today's three INSERTs are fine.
- **R12.** README is one paragraph from Phase 0; doesn't reflect the actual feature set, install steps, or API key flow.

### Untested claims

- **N6** (`SELECT COUNT(*), id` query in `delete_task_matching` / `edit_task_matching`): this query relies on SQLite's "bare column" behavior where a non-aggregated column in a query with aggregates returns an arbitrary row's value. It works in SQLite (verified), but the same query would fail or return undefined values in stricter SQL engines. **For count > 1 cases the `id` returned is meaningless** — the code correctly doesn't use it (returns `Ambiguous(count)` without id), but a reviewer pulling this query into a different context would get bitten.

---

## Reality vs. FIXES_APPLIED.md

| Claim | Reality |
|---|---|
| "All critical and high-priority fixes…have been successfully implemented" | True for the items as written. |
| "N12: VAD initialized once at first record" | True. But verification confirms: model is loaded on first **hotkey press**, not at app startup. So the first command is still slower than subsequent ones. Acceptable but not optimal. |
| "S5: Model ID verified" | True, but verification is **on first GeminiBackend instantiation = first hotkey press** (R1). Adds latency to the most visible moment. |
| "S9: Consolidate Duplicated Categories Query" | Partially. `get_categories` is consolidated; the four mutation methods aren't (R8). |
| "N2: Handle Window Close & Reopen" | Doesn't actually re-enable opening after X-close — just doesn't crash. Functional behavior is "Open button silently stops working." (R4) |
| "Files Modified: pyinstaller.spec - bundle resources" | True. ✓ |
| "Code passes syntax checks" | I imported `MatchResult` and exercised it — passes. Didn't run the full app. |

---

## Net status

**Ready for first real-user testing.** None of the remaining issues will prevent the app from running end-to-end on the happy path. R1 (first-press latency) and R2 (model picker) are the only things I'd want to fix before showing it to someone.

**Recommended next-pass order:**
1. R1 — instantiate GeminiBackend once at startup (15 min)
2. R2 — better model picker (30 min)
3. R4 — wire close-to-hide so the Open button keeps working (30 min)
4. R3 — fix the `any` type annotation (1 min)
5. R7 — surface foreign-key errors in the UI (20 min)
6. R5 — drop stale `set_hotkey` declaration (1 min)
7. R6 — share the model verification with test_gemini_key (15 min)
8. R8 — finish consolidating Database mutation methods (45 min)

Total ~2.5 hours for everything that matters. Cosmetic items can wait.
