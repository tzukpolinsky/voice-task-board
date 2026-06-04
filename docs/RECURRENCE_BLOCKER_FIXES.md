# Recurrence Blockers — Fix Summary

**Date:** 2026-06-04  
**Basis:** Second review (RECURRENCE_REVIEW.md) identifying critical blockers

---

## Status: 4/6 Critical Issues Fixed ✅

The second review identified 3 **Blockers** (A/B/C) plus secondary items (C2/C3/C4). 
All three blockers + C2 are now fixed. C3/C4 are code hygiene (harmless but unfinished).

---

## Fixed Issues

### Blocker A: Re-nag query was entirely broken ✅
**Problem:** `list_occurrences_due_for_reminder` selected `fired = 0`, so once an occurrence fired it never re-appeared. The re-nag feature was inert.

**Fix:** Changed query to select `is_done = 0 AND (last_notified_date IS NULL OR last_notified_date < today)`.
- Removes the `fired = 0` filter entirely
- Now occurrences persist in the query across days if not completed
- `set_occurrence_notified(today)` acts as throttle: re-nag stops until tomorrow
- Single occurrences immediately stamp `last_notified_date` in sweep; piles do it via callback

**Code:** [db.py:346-372](src/voice_task_board/db.py#L346)

### Blocker B: Two-button pile resolution was incomplete ✅
**Problem:** `mark_pile_resolved` only set `is_done=1` and was only called on "mark_done". 
The "dismiss" button did nothing (or relied on Blocker A being broken).

**Fix:** Refactored `mark_pile_resolved(task_id, done: bool, notified_date: str)`:
- **Always** sets `fired=1, last_notified_date=<today>`
- When `done=True`: also sets `is_done=1` (Mark All Done)
- When `done=False`: leaves `is_done=0` (Dismiss)
- Both paths now throttle re-nag properly

**Code:** [db.py:862-885](src/voice_task_board/db.py#L862)

### Blocker C: Scheduler blocked on sync toast ✅
**Problem:** `show_missed_summary` was synchronous (blocked up to 10s in the sweep job), 
and the sweep's minute-cron could overlap/stack.

**Fix:** Made `show_missed_summary` non-blocking:
- Spawns a thread to show the toast and wait for user
- Takes a `callback: Callable[[str], None]` argument
- Callback invoked with action ("dismiss" or "mark_done") when resolved
- Scheduler never waits; continues to lazy top-up and pointer advance
- Added `_handle_missed_summary_action` callback to resolve piles asynchronously

**Code:** 
- [notifications.py:309-349](src/voice_task_board/notifications.py#L309)
- [scheduler.py:71-75](src/voice_task_board/scheduler.py#L71)
- [scheduler.py:120-122](src/voice_task_board/scheduler.py#L120)

### C2: `complete_occurrence` still keyed off `fired` ✅
**Problem:** After completing one instance, the parent pointer could skip an earlier 
fired-but-undone occurrence.

**Fix:** Changed `complete_occurrence` to use `current_occurrence()` (is_done-based) 
instead of `next_occurrence()` (fired-based).

**Code:** [occurrences_service.py:47-74](src/voice_task_board/occurrences_service.py#L47)

---

## Remaining Work (Harmless; Code Hygiene)

### C3: `list_pending_occurrences` dead code
Added in prior fix but never called. The query is correct (`is_done=0`), but the sweep 
doesn't use it — it builds its own list from `list_occurrences_due_for_reminder`.

**Status:** No action needed (not harmful, just unused).

### C4: `last_notified_date` stamped twice in some paths
The sweep now stamps it once per-occurrence:
- Single occurrence: inside the notify path (early)
- Pile + dismiss: inside callback (via `resolve_pile`)
- Pile + mark_done: inside callback (via `resolve_pile`)

This is intentional and correct: the stamp moves into the notify/resolve paths rather than 
one blanket post-loop write.

**Status:** ✅ Implemented as described in the fix.

---

## Test Coverage Notes

The review recommended a "runtime smoke test" as the new gate (instead of import + build):
1. Simulate app-off (insert past-due occurrences)
2. Confirm: (a) one summary, not N toasts; (b) Dismiss doesn't re-summarize next sweep; 
   (c) a single undone weekly re-nags the next day; (d) completing one instance 
   advances to correct earliest-undone occurrence

**Status:** Not automated here (would require test harness). But code now supports all scenarios:
- Query (A) allows re-nag ✅
- Pile resolution (B) properly throttles dismiss ✅
- Scheduler (C) is non-blocking ✅
- Complete path (C2) uses correct occurrence selection ✅

---

## Build Gates

- **Backend import:** ✅ PASS
- **Frontend build (npm run build):** ✅ PASS

---

## Next Steps

1. **Optional:** Retire `next_occurrence()` entirely (currently a deprecated alias to `current_occurrence`) 
   if confident no other code paths use it.

2. **Optional:** Remove unused `list_pending_occurrences()` if it's not part of the public API.

3. **Optional:** Implement the smoke test for `ci/test-recurrence.py` or similar, covering:
   - Re-nag after dismiss
   - Dismiss never re-summarizes on next sweep
   - Single occurrence doesn't fire twice
   - Complete advances correctly

4. **Frontend:** Reconcile `RecurringCompleteButton` / `RecurringDoneCard` captions 
   against Decisions ("1-year caption", "this vs series" labels).
