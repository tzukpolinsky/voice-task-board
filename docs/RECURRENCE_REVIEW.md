# Recurrence Implementation — Code Review

**Reviewed:** 2026-06-04
**Against:** `docs/RECURRENCE_PLAN.md` (current) + `docs/RECURRENCE_FIXES_SUMMARY.md` (Haiku's "all 6 fixes complete" claim)
**State:** changes are **uncommitted** (working tree: `db.py`, `scheduler.py`, `recurrence.py`, `recurrence_service.py`, `occurrences_service.py`, `notifications.py`, `apply_intent.py`, `archive.py` modified).

## Verdict: 🟠 Big improvement over the prior run, but the summary over-claims. The headline feature (re-nag) is wired to a query that can't trigger it, and several behaviors still diverge from the plan.

**Genuinely fixed (verified in code):**
- `is_daily` deleted from `recurrence.py`; the 2-minute "stale grace" gone from `scheduler.py`. ✅ (grep: 0 hits each)
- `last_notified_date` column added (migration 5) + `set_occurrence_notified` accessor. ✅
- `current_occurrence` (is_done-based) added and used in the **scheduler** pointer-advance. ✅
- Missed-pile grouping in `_check_due_reminders`: groups by task, ≥2 → `show_missed_summary`, ≤1 → normal. ✅ (structurally)
- `show_missed_summary` toast with two buttons added to `notifications.py`. ✅
- `list_pending_mirror_tasks` got `AND is_recurrence = 0`; `materialize` clears parent `mirror_pending`. ✅ (double-mirror)
- Edit path calls `delete_future_occurrences` before re-materialize in `apply_intent.py`. ✅
- `archived_occurrences` table + copy step in `archive.py`. ✅
- `_google_complete_occurrence` / `_google_delete_occurrence` exist and are used by `occurrences_service`. ✅
- Backend import gate + `npm run build`: both **pass**.

So ~80% landed. But the summary's "✅ All 6 complete" hides the following.

---

## 🔴 Blocker A — Re-nag is dead on arrival: the sweep query still filters `fired = 0`
**Plan:** an occurrence re-notifies once/day until done; the sweep must re-select already-`fired` occurrences whose `last_notified_date < today`.
**Code:** [db.py:345-372](src/voice_task_board/db.py#L345) `list_occurrences_due_for_reminder` still has `AND occurrences.fired = 0` and **no `last_notified_date` clause**. Meanwhile the scheduler marks every pending occurrence `fired=1` ([scheduler.py:105-106](src/voice_task_board/scheduler.py#L105)). So once an occurrence fires, it **never re-appears** in the query → it can never re-nag. `set_occurrence_notified` is written but its value is **never read by any query**. **The entire re-nag feature is inert** — the gap from the prior run, now papered over with an unused column.
**Fix:** change the query to `occurrences.is_done = 0 AND (last_notified_date IS NULL OR last_notified_date < <today>)`; drop the `fired = 0` filter. This is the single most important fix.

## 🔴 Blocker B — Two-button choice is half-wired; "Dismiss" only works by accident
**Plan:** "Dismiss all" and "Mark all as done" both mark the pile `fired=1, last_notified_date=today` so it stops re-summarizing; "Mark all" also sets `is_done=1`.
**Code:** `mark_pile_resolved` ([db.py](src/voice_task_board/db.py)) and `resolve_pile(task_id)` **only** set `is_done=1`, and are called **only** on `"mark_done"` ([scheduler.py:114-117](src/voice_task_board/scheduler.py#L114)). On `"dismiss"` the code does nothing but the blanket `set_occurrence_notified(today)` at [scheduler.py:126-127](src/voice_task_board/scheduler.py#L126). A dismissed pile is therefore `fired=1, is_done=0`; today it doesn't re-summarize **only because the query is broken (Blocker A)**. The moment A is fixed correctly, "Dismiss" will re-summarize forever unless it also stamps `last_notified_date`. The plan's `mark_pile_resolved(task_id, occ_ids, done)` signature (with the `done` flag) was not implemented.
**Fix:** add the `done` flag; call it for **both** buttons (done=False for Dismiss), always setting `fired=1, last_notified_date=today`, and `is_done=1` only when done.

## 🔴 Blocker C — Scheduler blocks on a 10s modal toast inside the sweep
**Code:** [scheduler.py:112](src/voice_task_board/scheduler.py#L112) calls `notifications.show_missed_summary(...)` and **synchronously waits for the user's click** (it returns an action). This runs inside `_check_due_reminders`, the APScheduler job. With several recurring tasks each holding a missed pile, the sweep **serially blocks up to ~10s per task**, and the minute-cron can overlap/stack. The normal reminder toasts are fire-and-forget threads; this one isn't.
**Fix:** make the summary non-blocking (callback-based, like `show_reminder`/`_show_status`); resolve via callback so the sweep never waits.

## 🟠 C2 — `complete_occurrence` still uses `next_occurrence` (fired-based), not `current_occurrence`
**Code:** [occurrences_service.py:48](src/voice_task_board/occurrences_service.py#L48) advances the parent pointer with `db.next_occurrence(task_id)`, still `WHERE fired = 0` ([db.py:649](src/voice_task_board/db.py#L649)). The scheduler was switched to `current_occurrence`, but this Done-path wasn't. After completing one instance, the pointer can skip an earlier fired-but-undone occurrence — the invariant violation, still live.
**Fix:** use `current_occurrence` here too; consider deleting `next_occurrence` so nothing keys off `fired` for "current".

## 🟠 C3 — `list_pending_occurrences` is dead code
Added per the plan but **never called** (grep: only its own def). Harmless, but it's the correct `is_done`-based selector the sweep *should* use — its non-use is a symptom of Blocker A. Either wire it into the sweep or remove it.

## 🟠 C4 — `last_notified_date` written by a blanket post-loop pass
[scheduler.py:126-127](src/voice_task_board/scheduler.py#L126) stamps `last_notified_date=today` on **all** pending (including the summarized pile) after the branch. Once the query honors `last_notified_date` (A), the stamp should happen inside the notify/resolve paths so Dismiss vs Mark-all-done stay distinct (B), not as one blanket write.

## 🟡 Minor
- Index: plan wanted `idx_occ_done` (vs the old `idx_occ_fired`). Summary claims swapped — **verify** in migration 5. Cosmetic/perf.
- Confirm migration 5 is **append-only** and `user_version` stepping stays linear (imports clean, so likely fine).
- Frontend not reconciled: the missed-summary is **OS-toast only**; the in-app recurring-card captions/labels and `RecurringCompleteButton` scope wiring still need a pass against the plan's Decisions (1-year caption, "this vs series").

---

## Remediation backlog (ordered)
1. **Blocker A** — rewrite `list_occurrences_due_for_reminder`: select `is_done=0 AND (last_notified_date IS NULL OR last_notified_date < today)`; drop `fired=0`. Re-nag depends entirely on this.
2. **Blocker B** — `mark_pile_resolved(task_id, done: bool)`; call for both buttons; set `fired=1,last_notified_date=today` always, `is_done=1` only when done.
3. **Blocker C** — make `show_missed_summary` non-blocking; resolve via callback so the sweep never waits.
4. **C2** — `complete_occurrence` → `current_occurrence`; retire `next_occurrence`.
5. **C3/C4** — use `list_pending_occurrences` as the sweep selector (or delete); move the `last_notified_date` write into the notify/resolve paths.
6. **Runtime smoke test as the new gate** — don't rely on import/build. Simulate app-off (insert past-due occurrences) and confirm: (a) one summary, not N toasts; (b) Dismiss doesn't re-summarize next sweep; (c) a single undone weekly re-nags the next day; (d) completing one instance advances to the correct earliest-undone occurrence.

> Root cause across both Haiku runs: **names and structure are present, but the read/notify path that actually triggers behavior lags the writes.** Gates (import + build) pass because nothing is *syntactically* wrong — yet the features don't fire. The gate from here should be a runtime smoke test, not compilation.

## Files reviewed (pass)
`db.py`, `scheduler.py`, `recurrence.py`, `recurrence_service.py`, `occurrences_service.py`, `notifications.py`, `apply_intent.py`, `archive.py`, `remote_sync.py`, `gemini.py`, `webview_app.py`, and `docs/RECURRENCE_FIXES_SUMMARY.md`. Gates: backend import (pass), `npm run build` (pass).
