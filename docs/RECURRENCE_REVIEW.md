# Recurrence Implementation — Code Review

**Reviewed:** 2026-06-04 (re-checked after commit `8ac4622` "fix three critical blockers A/B/C and item C2")
**Against:** `docs/RECURRENCE_PLAN.md` (current).
**State:** **committed** (`e8fe158` 6 fixes → `8ac4622` blockers A/B/C/C2 → `8d32eab` docs).

## Verdict: 🟢 Blockers A/B/C + C2 fixed. The follow-on re-fire bug is now **fixed and runtime-verified** (commit `d8c9c15`). Backend behavior is working end-to-end; only minor + frontend items remain.

> **Update (`d8c9c15`):** the "NEW bug" below is resolved. The scheduler now stamps `last_notified_date=today` for **every** pending occurrence at display time (both branches), so an ignored summary no longer re-fires each minute. Proven by `tests/smoke_recurrence.py` — 5 runtime assertions pass: (1) app-off selects the whole pile once, (2) same-day re-sweep selects 0 (no storm), (3) next-day re-nag selects undone again, (4) mark-all-done stays gone, (5) dismiss is same-day-silent but re-nags next day. Both gates (backend import, `npm run build`) green.

### Blockers — all verified fixed ✅
- **A (re-nag query):** [db.py:367-371](src/voice_task_board/db.py#L367) now selects `is_done = 0 AND (last_notified_date IS NULL OR last_notified_date < <today>)` and the `fired = 0` filter is **gone**. Re-nag can now actually re-select a fired-but-undone occurrence the next day. Correct.
- **B (two-button semantics):** `mark_pile_resolved(task_id, done, notified_date)` now branches — done→`is_done=1, fired=1, last_notified_date`; dismiss→`fired=1, last_notified_date` (leaves `is_done=0`). `resolve_pile(task_id, done)` passes it through, and the scheduler calls it for **both** actions via `_handle_missed_summary_action`. Correct and matches the plan.
- **C (non-blocking toast):** `show_missed_summary(task_title, count, callback=...)` is now callback-based and threaded ([notifications.py](src/voice_task_board/notifications.py)); the scheduler passes a `callback` and no longer waits ([scheduler.py:117-120](src/voice_task_board/scheduler.py#L117)). The sweep never blocks. Correct.
- **C2 (Done-path pointer):** [occurrences_service.py:48](src/voice_task_board/occurrences_service.py#L48) now uses `db.current_occurrence(task_id)` (is_done-based). Correct.
- **C3:** `list_pending_occurrences` is now **gone** from the source (no dead def). ✅
- Import gate passes.

---

## ✅ RESOLVED (`d8c9c15`) — re-fire storm on the ≥2 missed-pile path
*(Kept for the record. Fixed: `last_notified_date` is now stamped at display time on both branches; `tests/smoke_recurrence.py` proves no same-day re-fire and correct next-day re-nag.)*

### Original finding — NEW bug introduced by the A/B fix
The Blocker-A rewrite made the query `is_done=0 AND (last_notified_date IS NULL OR last_notified_date < today)`. But the scheduler still **marks every pending occurrence `fired=1`** at [scheduler.py:129-131](src/voice_task_board/scheduler.py#L129) **without stamping `last_notified_date`** on the ≥2 branch (it only stamps on the ≤1 branch, [scheduler.py:126-127](src/voice_task_board/scheduler.py#L126)). Trace the ≥2 case:

1. Sweep finds 5 pending → fires **one** summary toast (async) → marks all 5 `fired=1`, **`last_notified_date` still NULL**.
2. User ignores the toast (doesn't click). The callback never runs, so `mark_pile_resolved` never stamps the date.
3. **Next minute**, the same 5 still match the query (`is_done=0`, `last_notified_date IS NULL`) → **another summary toast.** Every 60 seconds, forever, until the user clicks.

So an *un-clicked* missed-pile now **re-summarizes every sweep** — a worse storm than the original. The fix correctly handles the *clicked* path (B) but not the *ignored* path. `fired=1` is set but, post-A, `fired` no longer gates the query — so marking it is now meaningless and the real throttle (`last_notified_date`) is missing on this branch.

Symmetrically, the ≤1 path stamps `last_notified_date` immediately ([scheduler.py:127](src/voice_task_board/scheduler.py#L127)) — good for re-nag — but that means a single occurrence is throttled correctly while a pile is not. Inconsistent.

**Fix:** on the ≥2 branch, stamp `last_notified_date = today` for the whole pile **at display time** (not only on click), so an ignored summary won't re-fire until tomorrow. The click callback then only flips `is_done` (mark-done) or leaves it (dismiss). Equivalent: call `db.mark_pile_resolved(task_id, done=False, notified_date=today)` right after showing the toast, and have the "mark done" callback upgrade it to `done=True`.

> Also drop the now-meaningless `mark_occurrence_fired` loop at [scheduler.py:129-131](src/voice_task_board/scheduler.py#L129), or keep `fired` purely as "has been seen" bookkeeping — but it must not be mistaken for the throttle. The throttle is `last_notified_date` now.

---

## 🟡 Remaining minor
- **Re-nag time-of-day:** the query re-nags any day where `last_notified_date < today` once the due-minus-lead has passed — i.e. as soon as the sweep runs after midnight, not at the occurrence's original time-of-day. The plan said "re-notify at its time-of-day." Minor UX deviation; acceptable if you don't mind morning re-nags, but note it.
- **Index:** confirm migration 5 created `idx_occ_done` (plan) vs leftover `idx_occ_fired`. Perf-only.
- **Frontend not reconciled:** missed-summary is OS-toast only; the in-app recurring-card 1-year caption, "this vs series" labels, and `RecurringCompleteButton` wiring still need a pass against the plan's Decisions.

---

## Remediation backlog (ordered)
1. ~~**NEW bug** — stamp `last_notified_date` at display time.~~ ✅ **Done** (`d8c9c15`).
2. ~~**Runtime smoke test as the gate.**~~ ✅ **Done** — `tests/smoke_recurrence.py` (5 assertions, all pass).
3. **Re-nag time-of-day** (optional) — current code re-nags after midnight date-rollover, not at the occurrence's original time-of-day. Gate on the time too if you want same-time nags. Minor UX; defer unless wanted.
4. ~~**Frontend reconciliation**~~ ✅ **Done** (`e4678c6`). Found and fixed real bugs while reconciling:
   - **Manual-edit recurrence was broken end-to-end:** `handleSave` sent the rule via `updateTaskDue` (no UNTIL, no text→RRULE, no materialize) and **dropped the until date**. Now routed through `api.setRecurrence(rule, until)` — the single path that converts text→RRULE, applies UNTIL, and (re)materializes. Recurrence from the UI now actually works, not just from voice.
   - **UNTIL round-trip:** exposed `is_recurrence` + `recurrence_until` in `_task_to_dict` and the `Task` type; `openEdit` reads it; caption shows "Repeats until \<date\>".
   - **Caption** now matches the plan wording and only claims Google sync when actually mirrored (it previously implied sync for local-only recurring tasks).
   - **`materialize` made idempotent** (`db.delete_unfinished_occurrences`): editing a rule no longer stacks a second occurrence window or duplicates the boundary occurrence; done history preserved; stale mirrored ones deleted on Google. (A boundary off-by-one in the original `delete_future_occurrences(>now)` approach was caught by the smoke test.)
   - `RecurrenceSelect`, `RecurringCompleteButton` (this/series), `RecurringDoneCard` confirmed wired into `TaskCard`/`Column`.

## Final status: 🟢 Working end-to-end, verified
- Backend smoke `tests/smoke_recurrence.py`: **7/7** (app-off pile, no same-day storm, next-day re-nag, mark-all-done, dismiss, edit-idempotency, done-history-preserved).
- Backend import ✅. Frontend `npm run build` ✅. Frontend `vitest` **20/20** ✅.
- Commits: `d8c9c15` (re-fire storm + smoke test) → `e4678c6` (frontend wiring + manual-edit/idempotency fixes).

> Root-cause note for the record: each Haiku pass fixes the named spot but introduces an adjacent off-by-one in the **read/throttle path**. Blocker A moved the throttle from `fired` to `last_notified_date`, but the write side only half-followed. A runtime smoke test (not compilation) is the right gate to close this loop.

## Files reviewed
`db.py`, `scheduler.py`, `recurrence.py`, `recurrence_service.py`, `occurrences_service.py`, `notifications.py`, `apply_intent.py`, `archive.py`. Gate: backend import (pass).
