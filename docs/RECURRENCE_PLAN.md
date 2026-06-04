# Recurrence Implementation Plan (for Haiku)

**Status:** Plan only — no code written yet.
**Goal:** Real recurring tasks with a materialized 1-year window of occurrences, lazy top-up on each fire, Google **Tasks** mirroring of every occurrence, a searchable Repeat dropdown, an UNTIL/stop date, a Calendar-style Done prompt, and an aggregating Done card.
**Scope:** Python backend (`src/voice_task_board/`) + React frontend (`frontend/`). No Google **Calendar** — **Google Tasks only**.

---

## 0. How to use this document (READ FIRST — implementation rules)

Execute **one numbered step at a time, top to bottom.** Do not batch, do not skip.

1. **Never invent values, names, or behavior.** Everything you need is written here. If something required is missing, **STOP and ask** — do not guess.
2. **Exact find/replace.** When a step quotes current code, match it literally (quotes, spaces, indentation). If you can't find it, **STOP** — do not edit a different line.
3. **Do not touch logic outside the step.** Leave unrelated handlers, hooks, dnd-kit, OAuth, and audio code alone. Preserve UTF-8 + CRLF line endings.
4. **GATE after every phase** (commands in §3). Backend gate = `python -m pytest` (or the import check given). Frontend gate = `cd frontend && npm run build`. Red gate → fix only what the error names, or revert the phase. Never proceed on red.
5. **One commit per phase**, message `recurrence: phase N — <title>`.
6. If a step references a new DB column/table, it was created in **Phase 1**; it exists before any code reads it.

> Mental model: this is mechanical assembly. All design decisions are already made below.

---

## 1. Decisions (all locked — do not revisit)

| Topic | Decision |
|---|---|
| Google target | **Google Tasks** only. NOT Calendar. Each occurrence = one separate Google Task with its own id. |
| Materialization | At create/edit, generate **1 year** of occurrence rows (`now` → `now + 365d`), capped by UNTIL if set. |
| Lazy top-up | On each fire, after marking the occurrence fired, append exactly **one** new occurrence at the back of the window (keeps ~1yr ahead). Skip if past UNTIL. |
| Recurrence engine | `dateutil.rrule` parsing an **RRULE string** (iCal). Store the RRULE on the parent task. |
| AI role | A **second AI call**, at **create/edit only** (never in scheduler), converts repeat free-text → RRULE string. Dropdown presets map to RRULE directly (no AI). |
| `time` in RRULE | Local-only. Google Tasks `due` is **date-only** (time is discarded by Google) — only the local scheduler uses the time. |
| Toasts — bulk | Creating the year of occurrences and pushing them to Google = **silent**. |
| Toasts — creation summary | **One** status toast **after** the background sync finishes. Wording branches on UNTIL: open-ended → "Repeating task synced — N occurrences for the next year." Bounded → "Repeating task synced — N occurrences until \<date\>." |
| Toasts — live reminder | An occurrence due *now* toasts once, normally (existing `show_reminder`). |
| **Re-nag (unresolved occurrence)** | A passed occurrence that is **not done** re-notifies **once per day at its time-of-day** until it is marked done or the next occurrence's time arrives (i.e. it is superseded). This is the same mechanism for daily and non-daily — daily simply has no gap to re-nag across, because the next day is already its own occurrence. Tracked via `occurrences.last_notified_date`. |
| **Missed-pile collapse (catch-up)** | Per task per sweep, if **2 or more** of its occurrences are pending-notify at once (e.g. app was off), do **not** fire multiple toasts. Fire **one** summary toast: *"You missed N recurrences for \<TASK\>"* with two buttons: **"Dismiss all"** and **"Mark all as done"**. Either button marks the whole pile `fired=1` (Mark-all also sets `is_done=1`) so it stops re-summarizing; we resume on the next future occurrence. **1** pending → normal single reminder (which may re-nag per the row above). This rule replaces any daily-vs-non-daily branch. |
| Done prompt | Completing a recurring occurrence shows a Calendar-style choice: **This occurrence** (mark done, advance series) vs **Whole series** (end series: mark inactive, purge future occurrences). |
| Done board | Recurring series shows **one** aggregating card (continuously, as soon as ≥1 occurrence done): "Done N×, last <date>", expandable to per-occurrence history (done vs skipped). NOT one card per completion. |
| Occurrence states | Per occurrence: `fired` (passed/seen by the sweep at least once), `is_done` (completed), `last_notified_date` (last day we toasted it, for re-nag). future=`fired 0`, skipped/pending=`fired 1,is_done 0`, done=`is_done 1`. |
| **Next-occurrence invariant** | The "current/active" occurrence (what the board card + parent pointer target) = earliest occurrence with **`is_done = 0`** whose time hasn't been superseded. Notification eligibility is governed by `is_done` + `last_notified_date`, **NOT** by `fired` alone — because a `fired` occurrence may legitimately re-nag. NEVER skip an occurrence from "current" just because `fired=1`. |
| Parent task = recurring → no parent-level reminder/mirror | A recurring parent must be **excluded** from the legacy non-recurring reminder query (`list_tasks_due_for_reminder`) and from the parent mirror queue (`list_pending_mirror_tasks`/`retry_pending`). Otherwise it double-fires every minute and double-mirrors (parent + per-occurrence). Recurring tasks are driven **only** by the occurrences table. |
| Stale mirrored skipped occurrences on Google | **Leave them.** Do not auto-complete/delete on Google. User manages their own Google list. |
| Rate limiting | All Google Tasks API calls go through a shared throttle: **≥ 500 ms between calls (~2/sec)** + exponential backoff on HTTP 429 (`0.5→1→2→4s`). Daily limit is 50,000/day (not a concern). |

---

## 2. Current-state facts (verified — context, not actions)

- **DB**: `src/voice_task_board/db.py`. SQLite, manual migration list `MIGRATIONS` keyed by `PRAGMA user_version`. Current max version = **3**. `Task` dataclass + `_row_to_task`. Parent task already has `recurrence_rule TEXT` (free text today), `reminder_fired`, `external_id`, `mirror_to_remote`, `status` ('open'/'done').
- **Scheduler**: `scheduler.py`. APScheduler cron every minute → `_check_due_reminders` → `db.list_tasks_due_for_reminder(now)` → `set_reminder_fired` + `_notify_callback(task)` + `_maybe_spawn_next_recurrence(task)`. The broken parser is `_next_due_from_rule` (substring matching) — **to be replaced**.
- **Mirror**: `remote_sync.py`. Google **Tasks** API (`GOOGLE_BASE = .../tasks/v1`). `_google_create/_update/_complete/_delete`, public `mirror_create/update/complete/delete(task_id)` each spawn a daemon thread. `due` is RFC3339 but Google keeps date only. Failed pushes set `mirror_pending`; `retry_pending()` drains.
- **AI**: `gemini.py` `GeminiBackend`. `extract_intent(audio)` → `FirstPassIntent` (already has `recurrence_rule: str|None` free text). `_post_and_extract_text` posts to `_endpoint` with a `responseSchema`. Prompts loaded via `load_prompt(name)` from `resources/prompts/`. `apply_intent.py` turns intent → `db.add_task(...)`.
- **API bridge**: `webview_app.py` exposes `Api` methods (snake_case) to JS via pywebview. Frontend calls them through `frontend/src/api.ts` (`window.pywebview.api.<method>`). Relevant existing: `create_task`, `update_task_due`, `complete_task`, `delete_task`, `set_mirror`, `get_archived_tasks`, `get_pending_mirror_count`.
- **Frontend**: `TaskCard.tsx` (edit form already restyled), `Column.tsx` (Open/Done tabs; Done renders `DoneCard`), `types/domain.ts` (`Task` has `recurrence_rule`). Toast UI = `ErrorToast`/`ToastContext` (frontend), but reminders are **OS toasts** from `notifications.py`.
- **Dependency**: `python-dateutil` — **must verify it's installed** (Phase 0). `rrule` is the engine.

---

## 3. GATE commands

**Backend gate** (run from repo root):
```
python -c "import voice_task_board.db, voice_task_board.scheduler, voice_task_board.recurrence, voice_task_board.remote_sync, voice_task_board.webview_app"
python -m pytest -q   # if tests exist; otherwise the import line above is the gate
```
**Frontend gate**:
```
cd frontend && npm run build
```

---

## 4. Data model (target)

New table `occurrences` (in the live `tasks.db`, added via a new migration appended to `MIGRATIONS`):

```sql
CREATE TABLE occurrences (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  due_at_utc TEXT NOT NULL,        -- local wall-clock datetime string, same convention as tasks.due_at_utc
  fired INTEGER NOT NULL DEFAULT 0,        -- the sweep has seen this occurrence's time pass at least once
  is_done INTEGER NOT NULL DEFAULT 0,      -- completed by the user
  last_notified_date TEXT,                 -- YYYY-MM-DD of the last day we toasted it (re-nag throttle); null = never
  external_id TEXT,                -- this occurrence's Google Task id (nullable until pushed)
  mirror_pending INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_occ_task ON occurrences(task_id);
CREATE INDEX idx_occ_due ON occurrences(due_at_utc);
CREATE INDEX idx_occ_done ON occurrences(is_done);
```

New columns on `tasks` (same migration):
```sql
ALTER TABLE tasks ADD COLUMN is_recurrence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN recurrence_until TEXT;          -- ISO date/datetime, null = open-ended
ALTER TABLE tasks ADD COLUMN recurrence_active INTEGER NOT NULL DEFAULT 1;  -- 0 = series ended
```

**Field meanings & invariants:**
- `tasks.recurrence_rule` now stores an **RRULE string** (e.g. `FREQ=WEEKLY;BYDAY=MO`), not prose. (Legacy free-text rows: treated as inert — see §6 Phase 6 migration note.)
- The parent task's `due_at_utc` mirrors the **current active occurrence** (earliest `is_done=0`) so the board card shows the right next date. The parent's `external_id` is **not** used for recurring tasks (each occurrence carries its own); the parent is excluded from the legacy reminder + mirror queues (see Decisions table).
- **Current/active occurrence = `SELECT ... WHERE task_id=? AND is_done=0 ORDER BY due_at_utc LIMIT 1`.** `fired` does **not** exclude an occurrence from being current — a fired-but-not-done occurrence is still the active one (that's what re-nags).
- `last_notified_date` is the re-nag throttle: an occurrence may toast at most once per calendar day.

---

## 5. RRULE conventions (the only formats the app produces/consumes)

The AI and the dropdown emit a constrained RRULE subset. `dateutil.rrule.rrulestr` parses all of these:

| Meaning | RRULE | Dropdown label |
|---|---|---|
| Every day | `FREQ=DAILY` | "Every day" |
| Every weekday | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` | "Every weekday" |
| Weekly on a day | `FREQ=WEEKLY;BYDAY=MO` | "Every Monday" … (7) |
| Every N days | `FREQ=DAILY;INTERVAL=16` | (AI/custom only) |
| Every N weeks on a day | `FREQ=WEEKLY;INTERVAL=2;BYDAY=SU` | (AI/custom only) |
| Monthly | `FREQ=MONTHLY` | "Every month" |
| Nth weekday of month | `FREQ=MONTHLY;BYDAY=1FR` | (AI/custom only) |
| Yearly | `FREQ=YEARLY` | "Every year" |
| None | (empty / null) | "Does not repeat" |

Time-of-day is **not** encoded in the RRULE; it comes from the task's `due_at_utc` time component (local). UNTIL is stored separately in `tasks.recurrence_until`, NOT inside the RRULE string (keeps the dropdown and AI output clean; the generator applies it).

---

## 6. Phased execution

### Phase 0 — Dependency check
0.1 Confirm `python-dateutil` is importable: `python -c "import dateutil.rrule"`. If it fails, add `python-dateutil` to `pyproject.toml` dependencies and install.
0.2 Backend gate (import line). Commit: `recurrence: phase 0 — deps`.

---

### Phase 1 — DB migration + occurrence accessors (atomic) ⭐
**Goal:** schema + the DB methods later phases call. No behavior change yet.

1.1 In `db.py`, append **one** new string to the `MIGRATIONS` list (becomes version 4) containing the `occurrences` CREATE + indexes + the three `ALTER TABLE tasks` statements from §4. **Append only — never edit existing migration entries.**
1.2 Add an `Occurrence` dataclass (fields per §4 table) near `Task`.
1.3 Add `Task` dataclass fields `is_recurrence: bool = False`, `recurrence_until: str | None = None`, `recurrence_active: bool = True`, and read them in `_row_to_task` (extend every `SELECT tasks....` column list that builds a Task — there are 5: `list_tasks`, `list_tasks_due_for_reminder`, `list_mirrored_open_tasks`, `list_pending_mirror_tasks`, `get_task`). Append the 3 columns at the end of each SELECT and to `_row_to_task` indices.
1.4 Add DB methods (all `with self._lock`):
   - `add_occurrences(task_id, due_list: list[str]) -> None` — bulk insert occurrence rows (`fired=0,is_done=0,last_notified_date=NULL`).
   - `current_occurrence(task_id) -> Occurrence | None` — earliest `is_done=0` (the active one; see §4 invariant). **Not** keyed off `fired`.
   - `last_materialized_due(task_id) -> str | None` — max `due_at_utc`.
   - `list_occurrences(task_id) -> list[Occurrence]` — all, ordered by due.
   - `mark_occurrence_fired(occ_id) -> None`.
   - `mark_occurrence_done(occ_id) -> None` (sets `is_done=1`).
   - `set_occurrence_notified(occ_id, date_str) -> None` — set `fired=1, last_notified_date=date_str`.
   - `set_occurrence_external(occ_id, external_id, mirror_pending) -> None`.
   - `list_unpushed_occurrences(task_id) -> list[Occurrence]` — `external_id IS NULL` (for mirror).
   - `delete_future_occurrences(task_id, after_utc) -> list[str]` — delete `due_at_utc > after_utc`, **return the deleted external_ids** (non-null) so the caller can delete them on Google.
   - `end_series(task_id) -> None` — `recurrence_active=0`.
   - `mark_pile_resolved(task_id, occ_ids: list[int], done: bool) -> None` — set the given occurrences `fired=1, last_notified_date=today`, and if `done` also `is_done=1` (the "Dismiss all"/"Mark all as done" actions).
   - `count_done_occurrences(task_id) -> int` and `last_done_due(task_id) -> str | None` (for the Done card).
1.5 Backend gate. Commit: `recurrence: phase 1 — schema + occurrence accessors`.

> Why atomic: the migration + the Task field reads must ship together or `_row_to_task` breaks.

---

### Phase 2 — Recurrence engine module
**Goal:** pure, deterministic date math. No DB, no network.

2.1 Create `src/voice_task_board/recurrence.py` with:
   - `generate_occurrences(rrule_str: str, start_utc: str, tz: str | None, until_utc: str | None, horizon_days: int = 365) -> list[str]`
     Uses `dateutil.rrule.rrulestr`. `dtstart` = parsed `start_utc` (apply tz via zoneinfo for correctness, but **return the same wall-clock string format** as `tasks.due_at_utc`, i.e. `"%Y-%m-%dT%H:%M:%S"`). Window end = `min(start + horizon_days, until_utc)`. Returns the list of occurrence datetime strings (including the first/start). Cap result length defensively (e.g. ≤ 1000) to avoid pathological rules.
   - `next_after(rrule_str, after_utc, tz, until_utc) -> str | None` — the single next datetime strictly after `after_utc`, or None if past `until`. Used by lazy top-up.

> Note: there is **no** `is_daily` helper. The earlier daily-vs-non-daily catch-up branch was removed — the missed-pile collapse (≥2 → one summary) and per-day re-nag handle daily and non-daily identically (see Decisions table).
2.2 Backend gate. Commit: `recurrence: phase 2 — engine`.

---

### Phase 3 — Second AI call: repeat-text → RRULE
**Goal:** convert prose/edited text to an RRULE at create/edit only.

3.1 Add prompt file `resources/prompts/recurrence_to_rrule.txt`: instruct the model to convert a short natural-language repeat phrase + the current datetime into **either** an RRULE string from the §5 subset **or** the literal `NONE`. Output JSON `{"rrule": "FREQ=...", "until": "YYYY-MM-DD"|null}` (model may extract "for the next month" → an until date). Keep it strict; give the §5 table as examples.
3.2 In `gemini.py` add `GeminiBackend.text_to_rrule(text: str) -> tuple[str | None, str | None]` returning `(rrule_or_None, until_or_None)`, using `_post_and_extract_text` with a JSON `responseSchema` `{rrule: string|nullable, until: string|nullable}`. Map `"NONE"`/empty → `(None, None)`.
3.3 Backend gate. Commit: `recurrence: phase 3 — text→rrule AI`.

> The speech `extract_intent` still returns `recurrence_rule` as free text (unchanged). The conversion to RRULE happens in Phase 5 when the task is materialized, by calling `text_to_rrule` once.

---

### Phase 4 — Throttled Google Tasks client
**Goal:** every Google call rate-limited + backoff; per-occurrence push/delete.

4.1 In `remote_sync.py` add a module-level throttle: a `threading.Lock` + last-call timestamp ensuring **≥ 0.5 s** between any two outbound Google calls; wrap `_google_create/_update/_complete/_delete/_get_updated` so they pass through it. Add exponential backoff (`0.5,1,2,4` s) on `httpx.HTTPStatusError` where `resp.status_code == 429`.
4.2 Add occurrence-level helpers:
   - `push_occurrence(occ_id)` — build a Google Task body from the parent task (title/notes) + the occurrence's date; POST; store id via `db.set_occurrence_external(occ_id, ext_id, mirror_pending=False)`. On failure set `mirror_pending=1`.
   - `delete_occurrence_external(external_id)` — throttled DELETE; ignore 404.
   - `push_occurrences_for_task(task_id)` — loop `db.list_unpushed_occurrences`, `push_occurrence` each (throttle handles pacing), all on **one** background daemon thread. When the loop finishes, call the provided "done" callback (used for the summary toast).
4.3 Backend gate. Commit: `recurrence: phase 4 — throttled per-occurrence mirror`.

---

### Phase 5 — Materialization at create/edit
**Goal:** when a recurring task is created/edited, build the window + push (silently) + summary toast.

5.1 Add `recurrence_service.py` (orchestrator) with `materialize(task_id)`:
   - Load task. If `recurrence_rule` is free text (from speech) and not yet an RRULE, call `gemini.text_to_rrule` once → store RRULE in `tasks.recurrence_rule` and `until` in `tasks.recurrence_until` (via a new `db.set_recurrence(task_id, rrule, until)` setter; also sets `is_recurrence=1`, `recurrence_active=1`). If result is `(None,_)` → mark `is_recurrence=0` and return (not recurring).
   - **Suppress parent-level mirror:** clear the parent's `mirror_pending` (`db.set_mirror_pending(task_id, False)`) so `retry_pending` never creates a standalone parent Google task. The parent's `mirror_to_remote` flag is kept (it means "mirror this series"), but mirroring happens per-occurrence only. (See Decisions table: parent excluded from `list_pending_mirror_tasks` — done in Phase 1's query or here.)
   - `gen = recurrence.generate_occurrences(rrule, task.due_at_utc or now, task.due_tz, until)`.
   - `db.add_occurrences(task_id, gen)`.
   - Set parent `due_at_utc` to the **first** occurrence (so the board card shows the right next date).
   - If `task.mirror_to_remote`: spawn `remote_sync.push_occurrences_for_task(task_id)` with a callback that, on completion, fires **one** summary toast via `notifications.show_status(...)`. Wording branches on UNTIL: open-ended → `"Repeating task synced — {n} occurrences for the next year"`; bounded → `"Repeating task synced — {n} occurrences until {until_date}"`. (Silent during; one toast after.)
5.2 Call `materialize(task_id)` from `apply_intent.py` after `db.add_task(...)` when `first.recurrence_rule` is set, and from the edit branch after `update_task_due` when a recurrence rule is present. Also call it from the manual API path (Phase 8) — keep it one function.

> Re-materialize on edit: if the task already had occurrences, first `db.delete_future_occurrences(task_id, now)` (and delete their Google ids) before generating the new window, so an edited rule doesn't leave stale future occurrences. Past/done occurrences are kept (history).
5.3 Backend gate. Commit: `recurrence: phase 5 — materialize on create/edit`.

---

### Phase 6 — Scheduler: per-occurrence notify + re-nag + missed-pile collapse + lazy top-up + active guard
**Goal:** replace the broken spawn logic with the occurrence model.

6.1 **Exclude recurring parents from the legacy query (the double-fire fix).** In `db.list_tasks_due_for_reminder`, add `AND tasks.is_recurrence = 0` to the WHERE clause. (Recurring parents have a `due_at_utc` set to their first occurrence and would otherwise match this query and re-fire every minute, since their `reminder_fired` is never set.) Likewise add `AND tasks.is_recurrence = 0` to `list_pending_mirror_tasks` so `retry_pending` never mirrors a recurring parent as a standalone Google task (the double-mirror fix).

6.2 Add `db.list_pending_occurrences(now_utc)` — join occurrences→tasks, returning `(occurrence, task)` for rows where:
   `tasks.recurrence_active=1 AND tasks.status='open' AND occurrences.is_done=0 AND datetime(occ.due_at_utc, '-' || tasks.lead_time_minutes || ' minutes') <= now AND (occurrences.last_notified_date IS NULL OR occurrences.last_notified_date < <today>)`.
   "Pending-notify" = its time (minus lead) has arrived, it isn't done, and we haven't already toasted it today. Ordered by `task_id, due_at_utc`.

6.3 Rewrite `_check_due_reminders` in `scheduler.py`:
   - **Non-recurring path: unchanged.** Keep the existing `list_tasks_due_for_reminder` → `set_reminder_fired` → `_notify_callback` block exactly as-is (now naturally excludes recurring parents via 6.1).
   - **Recurring path:** fetch `list_pending_occurrences(now)` and **group by `task_id`**. For each task's pending list:
     - **If ≥ 2 pending (missed-pile):** fire **one** summary toast via a new `notifications.show_missed_summary(task_title, n, on_choice)` (two buttons "Dismiss all" / "Mark all as done"). The button callback calls `recurrence_service.resolve_pile(task_id, occ_ids, done=<True if "mark all">)`, which does `db.mark_pile_resolved(...)`. **Do not** call the normal reminder for these. (If the toaster is unavailable, default to "Dismiss all" semantics: mark the pile `fired=1, last_notified_date=today`, not done.)
     - **If exactly 1 pending:** the normal case (live reminder or a single daily re-nag). `db.set_occurrence_notified(occ.id, today)` and `_notify_callback(task)` (existing `show_reminder`). This same row re-appears tomorrow if still not done (re-nag), until done or superseded by a newer pending occurrence.
   - **Lazy top-up + active guard (run once per task that had any pending):** if `task.recurrence_active` and the last materialized due is within the horizon and not past `until`: `nxt = recurrence.next_after(rule, db.last_materialized_due(task_id), task.due_tz, until)`; if `nxt`: `db.add_occurrences(task_id,[nxt])`, and if `task.mirror_to_remote`, `remote_sync.push_occurrence(new_occ_id)` (silent).
   - **Advance parent pointer:** set parent `due_at_utc` = `db.current_occurrence(task_id).due_at_utc` (earliest `is_done=0`) so the board card shows the right next date.

6.4 **Delete** `_maybe_spawn_next_recurrence` and `_next_due_from_rule` (replaced).
6.5 Legacy note: existing rows with free-text `recurrence_rule` and no occurrences are inert (they have `is_recurrence=0`, so they won't match the occurrence query and are excluded from the legacy query only if `is_recurrence=1` — since they're `0`, they keep their old single-reminder behavior harmlessly). Do not migrate historical data.
6.6 Backend gate. Commit: `recurrence: phase 6 — scheduler occurrence model`.

---

### Phase 7 — Done semantics (this vs series) + completion mirroring
**Goal:** completing a recurring occurrence behaves like Calendar.

7.1 Add `recurrence_service` methods:
   - `complete_occurrence(occ_id)` → `db.mark_occurrence_done`; mirror: if the occurrence has `external_id`, `remote_sync` complete that Google task; then advance parent `due_at_utc` to `db.current_occurrence(task_id)` (earliest `is_done=0`). Series stays open (board card remains, showing the next due).
   - `end_series(task_id)` → `db.end_series` (active=0) + `db.delete_future_occurrences(task_id, now)` → for each returned external_id, `remote_sync.delete_occurrence_external`. Then `db.complete_task(task_id)` so the parent leaves the Open board.
   - `resolve_pile(task_id, occ_ids, done: bool)` → `db.mark_pile_resolved(task_id, occ_ids, done)`. Called by the missed-summary toast buttons (Phase 6.3). If `done`, also complete each occurrence's Google task where `external_id` is set (best-effort, throttled).
7.2 Add `notifications.show_missed_summary(task_title, n, on_choice)` modeled on `show_confirmation_toast`: title "You missed N recurrences", body the task title, two buttons "Dismiss all" (`arguments="dismiss"`) and "Mark all as done" (`arguments="done"`); on activation call `on_choice("dismiss"|"done")`. Reuse the existing toaster retain/release machinery.
7.3 Backend gate. Commit: `recurrence: phase 7 — done semantics + missed summary`.

---

### Phase 8 — API bridge methods
**Goal:** expose new operations to the frontend.

8.1 In `webview_app.py` `Api`, add:
   - `complete_occurrence_choice(task_id: int, scope: str) -> None` — `scope` ∈ `{"instance","series"}`. `"instance"` → complete current occurrence (`next_occurrence` → `complete_occurrence`). `"series"` → `end_series`.
   - `get_occurrences(task_id: int) -> list[dict]` — for the Done card history (due, fired, is_done).
   - `set_recurrence(task_id, repeat_text: str, until: str | None) -> None` — manual edit path: store text, call `recurrence_service.materialize`. (Wraps the AI+generate.)
8.2 Mirror these in `frontend/src/api.ts`: `completeOccurrenceChoice(taskId, scope)`, `getOccurrences(taskId)`, `setRecurrence(taskId, repeatText, until)`.
8.3 Backend + frontend gates. Commit: `recurrence: phase 8 — api bridge`.

---

### Phase 9 — Frontend: Repeat dropdown (searchable)
**Goal:** replace the free-text Repeat input in `TaskCard.tsx` edit mode with a searchable combobox of §5 presets, plus a custom free-text option (sent through the AI on save).

9.1 Add a small `RecurrenceSelect` component: an input that filters a static preset list (§5 labels) as you type; selecting a preset sets a hidden RRULE/label; typing a custom phrase and confirming keeps it as free text flagged "custom". Use the `.recurrence-select` / `.recurrence-list` / `.recurrence-option` CSS (add to `index.css`, dark-themed, matching `.task-edit-*`).
9.2 Add an UNTIL control: an optional "until" date input (`.task-edit-input--inline`) shown when a repeat is selected ("Repeat until (optional)").
9.3 On save: if preset → pass its RRULE via `setRecurrence` (until from the date input); if custom text → pass the text (backend AI converts). Keep the existing `updateTaskDue` call for due/lead/full-day.
9.4 Frontend gate. Commit: `recurrence: phase 9 — repeat dropdown`.

---

### Phase 10 — Frontend: recurring card affordances
**Goal:** the board card communicates recurrence + the 1-year limit, and Done is Calendar-style.

10.1 On a recurring task card (when `task.is_recurrence`): show a small "repeats" badge + a permanent caption: **"Synced to Google ~1 year ahead. Repeats beyond a year won't appear on your phone until then."** (always visible, muted text).
10.2 Replace the single Done action for recurring tasks with a tiny popover/dialog: **"Done with this one"** vs **"End the whole series"** → call `completeOccurrenceChoice(taskId, "instance" | "series")`.
10.3 Frontend gate. Commit: `recurrence: phase 10 — recurring card UI`.

---

### Phase 11 — Frontend: aggregating Done card
**Goal:** one Done-tab card per recurring series with history.

11.1 In `Column.tsx` Done tab: group done/in-progress recurring series into one `RecurringDoneCard` (do not list each completed occurrence). Show "Done N× · last <date>" using `getOccurrences(task_id)`; an expand button reveals the per-occurrence list with done (✓) vs skipped (·) markers (state from `fired`+`is_done` per §4).
11.2 Frontend gate. Commit: `recurrence: phase 11 — aggregating done card`.

---

### Phase 12 — Archive: preserve occurrence history
**Goal:** an ended recurring series' per-occurrence history survives the 30-day archive sweep (otherwise `ON DELETE CASCADE` drops it when `archive.py` deletes the parent).

12.1 In `archive.py`: add an `archived_occurrences` table (new entry in `ARCHIVE_MIGRATIONS`, append-only) mirroring the occurrence columns + `task_id`. In `_sweep`, before deleting each archived parent task from the live DB, copy its `occurrences` rows into `archived_occurrences`. (The live cascade then deletes the originals as today.)
12.2 Extend `list_archived` (or add `list_archived_occurrences(task_id)`) so the Done/archive UI can still show the history for an archived series.
12.3 Backend gate. Commit: `recurrence: phase 12 — archive occurrence history`.

---

### Phase 13 — QA
13.1 Backend import gate + `npm run build` clean.
13.2 **Manual checklist** (run the app):
   - [ ] Create "every monday at 09:00" by voice → becomes RRULE, ~52 occurrences materialized, board shows next Monday, one summary toast after sync ("…for the next year").
   - [ ] Create "every day" with mirror on → 365 occurrences, silent push (no toast storm), one summary toast at end; Google list fills gradually; **no** standalone parent Google task created.
   - [ ] "every monday for the next month" → UNTIL set, ~4 occurrences only, no top-up past the month; summary toast says "…until \<date\>".
   - [ ] Manual edit via dropdown: pick "Every weekday", set until date → future occurrences re-materialize, stale ones (and their Google tasks) removed.
   - [ ] Fire a due recurring occurrence → single toast; one new occurrence appended at the back; parent card shows next due.
   - [ ] **Double-fire check:** a recurring task does NOT re-toast every minute (legacy query excludes it).
   - [ ] **Re-nag:** a non-daily occurrence left undone re-toasts once the next day at its time, until done or superseded.
   - [ ] **Missed-pile:** app off across ≥2 occurrences → ONE "You missed N…" toast with "Dismiss all" / "Mark all as done"; choosing either stops further summaries; "Mark all as done" marks them done (and completes their Google tasks).
   - [ ] Done → "this one": instance completes, series continues, next due shown, Google task for that occurrence completed.
   - [ ] Done → "whole series": future occurrences gone locally, their Google tasks deleted, parent leaves Open board.
   - [ ] Done tab shows ONE aggregating card with correct N and expandable history (done ✓ vs skipped ·).
   - [ ] Skipped-but-passed occurrence: not counted as done, doesn't block "current", left on Google.
   - [ ] Archive: end a series, fast-forward 30 days (or temporarily lower the cutoff) → parent archived, occurrence history preserved in `archived_occurrences`.
   - [ ] Toggle light/dark: dropdown + caption readable in both.
13.3 Commit: `recurrence: phase 13 — QA`.

---

## 7. Risk & rollback
- All changes in `src/voice_task_board/` + `frontend/`. No OAuth/audio changes.
- Each phase builds independently; revert a phase with `git revert <commit>`.
- Live-DB migration is **append-only** (new `user_version` 4); archive-DB migration likewise append-only (Phase 12). Never edits prior migrations. Rolling back code does **not** roll back the DB, but the new table/columns are inert if unused.
- Highest-risk phases: **1** (schema + the 5 SELECT column edits — get `_row_to_task` indices right), **6** (scheduler rewrite — keep the non-recurring path byte-for-byte, only add the recurring branch + the `is_recurrence=0` guards), and the two double-X guards (double-fire 6.1, double-mirror 6.1/5.1) which are the subtle correctness fixes.

---

## 8. Open items deferred (NOT in this plan — revisit later)
- Migrating existing free-text `recurrence_rule` rows to RRULE — intentionally skipped (legacy rows inert, `is_recurrence=0`).
- Google **Calendar** (native RRULE, one event) — explicitly rejected in favor of Tasks.

> Note: the "re-notify next day for un-approved/undone occurrences" idea (the Calendar-style nudge) is **no longer deferred** — it is folded into the **Re-nag** + **Missed-pile collapse** decisions (§1) and implemented in Phase 6.
