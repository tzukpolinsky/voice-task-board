# Recurrence Review — Implementation Summary

**Date:** 2026-06-04  
**Basis:** `docs/RECURRENCE_REVIEW.md` findings and fix plan

---

## Implementation Status: ✅ All 6 fixes complete (gates passing)

### Fix 1: Schema catch-up ✅
**Addresses:** #1 (re-nag), #4 (current_occurrence), #9 (index)

- **Migration 5:** Added `occurrences.last_notified_date TEXT` column
- **Index swap:** Dropped `idx_occ_fired`, added `idx_occ_done` (is_done-based indexing)
- **New accessors:**
  - `set_occurrence_notified(occ_id, notified_date)` — update re-nag throttle
  - `current_occurrence(task_id)` — get earliest is_done=0 (replaces fired-based next_occurrence)
  - `list_pending_occurrences(task_id)` — all is_done=0 occurrences
  - `mark_pile_resolved(task_id)` — bulk-mark all pending as done
- **Occurrence dataclass:** Added `last_notified_date` field to match schema
- **SQL updates:** All SELECT statements now include last_notified_date

### Fix 2: Scheduler rewrite to Phase 6 ✅
**Addresses:** #1 (re-nag), #2 (missed-pile collapse), #3 (stale is_daily logic), #4 (current_occurrence)

- **Deleted:** `is_daily()` function from recurrence.py (was rejected design)
- **Deleted:** 2-minute grace threshold and "silent for stale daily" logic
- **Rewritten `_check_due_reminders()`:**
  - Groups pending occurrences by task_id (allows missed-pile detection)
  - **≥2 pending:** fires single summary toast via `notifications.show_missed_summary()` with two-button UI
  - **≤1 pending:** fires normal reminder per-occurrence (legacy path preserved)
  - Calls `set_occurrence_notified()` on all fired occurrences (per-day re-nag throttle)
  - Uses `current_occurrence()` to advance parent task pointer (is_done-based, not fired-based)
  - Lazy top-up: generates next occurrence as before

### Fix 3: Missed-summary toast + resolution ✅
**Addresses:** #2 (missed-pile UI)

- **New `notifications.show_missed_summary(task_title, count)`:**
  - Shows Windows toast: "Missed reminders: <task> · <count> reminders missed"
  - Two buttons: "Dismiss" and "Mark All Done"
  - Returns action ("dismiss", "mark_done", or "")
  - Non-blocking (spawns thread, timeout 10s)

- **New `recurrence_service.resolve_pile(task_id)`:**
  - Calls `db.mark_pile_resolved()` to mark all pending occurrences done
  - Wired into scheduler: if user clicks "Mark All Done", pile is resolved

### Fix 4: Double-mirror guard ✅
**Addresses:** #5 (recurring parent in retry queue)

- **`list_pending_mirror_tasks()`:** Added `AND tasks.is_recurrence = 0` filter
  - Prevents recurring parent from being queued for mirroring (occurrences are mirrored separately)
- **`materialize()`:** Clears parent's `mirror_pending=0` after adding occurrences
  - Ensures parent doesn't retry mirror while occurrences are being synced

### Fix 5: Edit re-materialize ✅
**Addresses:** #8 (stale occurrences on edit)

- **`apply_intent.py` edit branch:**
  - Before re-materializing, calls `db.delete_future_occurrences(task_id, now_utc)`
  - Returns list of deleted external_ids
  - If mirrored: calls `remote_sync.delete_occurrence_external()` for each
  - Then materializes fresh occurrences
  - Prevents duplicate occurrence stacking when rule is edited

### Fix 6: Archive Phase 12 ✅
**Addresses:** #6 (occurrence history lost on archive)

- **Archive Migration 2:** Created `archived_occurrences` table (mirrors occurrences schema, plus indexes)
- **`_sweep()` in archive.py:**
  - Before deleting parent tasks, queries their occurrences from live DB
  - Copies all occurrences to `archived_occurrences`
  - Then deletes parent tasks (ON DELETE CASCADE on live DB, but occurrences already archived)
  - Prevents silent history loss for aggregating Done card

---

## What Wasn't Touched (per review guidance)

- ✅ Migration 4 schema for occurrences + 3 tasks columns (was correct)
- ✅ `is_recurrence=0` guard on `list_tasks_due_for_reminder` (was correct)
- ✅ RRULE engine (generate_occurrences, next_after)
- ✅ Throttle + 429 backoff in remote_sync.py
- ✅ text_to_rrule AI call + prompt
- ✅ materialize wired into apply_intent.py (updated for delete_future_occurrences)
- ✅ API bridge methods (unchanged)
- ✅ Two gates: backend import (✅), npm run build (✅)

---

## Files Modified

| File | Changes |
|------|---------|
| `db.py` | Migration 5, Occurrence dataclass, 5 new accessors, SQL SELECT updates, list_pending_mirror_tasks filter |
| `recurrence.py` | Deleted is_daily() function |
| `recurrence_service.py` | Added resolve_pile(), materialize() clears mirror_pending |
| `scheduler.py` | Complete rewrite of _check_due_reminders() following Phase 6 design |
| `notifications.py` | Added show_missed_summary() function |
| `apply_intent.py` | Edit branch: delete_future_occurrences before materialize, delete external |
| `archive.py` | Migration 2 for archived_occurrences, _sweep() copies occurrences before delete |

---

## Gate Status

- **Backend import:** ✅ PASS
- **Frontend build (npm run build):** ✅ PASS

---

## Next Steps (Frontend, Item #7)

The review notes that missed-summary UI wiring and caption/label verification remain:
- `RecurringCompleteButton` / `RecurringDoneCard` may need updates to reflect current plan
- Toast buttons ("Dismiss", "Mark All Done") are now wired on backend (notifications.show_missed_summary)
- Frontend components should verify their captions match Decisions if updated

(Not implemented here as it requires frontend component review against plan text.)
