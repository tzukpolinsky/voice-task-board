# Notifications & External Reminders — Plan

Status: design, not yet implemented.
Scope: how the task board surfaces reminders locally and, optionally, mirrors tasks into Google Tasks or Microsoft To Do.

---

## 1. Product principles

- The **task board is the source of truth.** External Tasks systems are a one-way mirror the board maintains.
- **Day-to-day small tasks** are the target use case. Most tasks should *not* leave the local app.
- **Calendar events are explicitly out of scope.** Mirroring uses Tasks / To-Do objects only, because events clutter the calendar grid and lose the "nag until done" property of tasks.
- **Local notifications and remote notifications are independent.** The user is responsible for managing notification overload across surfaces; we do not try to deduplicate across them.
- **No two-way sync.** The one narrow exception (remote completion → local) is explicitly rejected — staleness is accepted.

---

## 2. Triggers (what fires a reminder)

In scope for v1:

- **Time-based** — task has a due datetime; reminder fires at that moment minus the lead time.
- **Lead-time** — default 30 minutes before due. The AI may infer a different lead time from natural language in the utterance; there are no reserved voice phrases.
- **Recurring** — handled as "spawn next on notification fire" (see §6), not as RRULE.

Out of scope: location/context triggers, external-event triggers (incoming email, etc.).

---

## 3. Surfaces (where a reminder appears)

- **Local Windows toast** via the tray app. Always fires for local tasks. Supports dismiss and snooze (local only).
- **Remote Tasks system** (Google Tasks *or* Microsoft To Do, user picks one in settings). Fires through whatever notification path that provider owns — phone app, web, etc. The board does not configure or touch the remote notification settings.

A task is **either** local-only **or** mirrored. Mirrored tasks still fire the local toast — local snooze does not affect the remote.

---

## 4. AI classification

The existing Gemini-based voice→task pipeline is extended to emit, in addition to current fields:

- `due_at`: ISO 8601 datetime, or date-only, or null.
- `lead_time_minutes`: integer, default 30, overridable by voice phrase.
- `mirror_to_remote`: boolean.
- `category`: existing field.

Classification rules baked into the prompt:

1. If no day **and** no time → `due_at = null`, `mirror_to_remote = false`. Never mirrored.
2. If day only (no time) → `due_at = date`, mirrored task is **full-day**.
3. If day **and** specific time → `due_at = datetime`, mirrored task is **timed**.
4. `mirror_to_remote = true` when the AI judges from the natural-language utterance that the user wants the task to follow them outside the app. **There are no reserved voice trigger phrases** — the whole point is free-form language. The AI infers intent end-to-end.
5. Asymmetry note: Google Tasks does not reliably honor specific-time notifications. Accepted as-is. A timed task mirrored to Google will still appear with the right time on the task, but Google's notification will behave like an all-day "due today" ping.

We will **not** split classification across multiple AI calls in v1. If accuracy is poor in practice, revisit then — no eval harness is built up front.

---

## 5. Confirmation UX

After the voice pipeline finishes processing, a **confirmation toast** appears summarizing the parsed task (title, due, mirrored y/n) with three actions:

- **✓ Accept** — commit the task (and mirror, if flagged).
- **Edit** — open the task in the board for correction before commit.
- **Cancel** — discard.

The toast **auto-accepts after 10 seconds** if the user does nothing. Auto-accept applies uniformly — mirrored and local tasks are treated the same. The 10-second window is intentionally generous so the user can catch and intercept a bad mirror before it hits the remote provider.

Latency budget: the user does not see the toast until the full classify pipeline (STT → Gemini → parse) completes. The remote mirror call is **not** made until accept (or auto-accept) fires. No optimistic UI in v1.

---

## 6. Recurring tasks

- A recurring task is stored with a `recurrence_rule` (e.g., "weekday 9am", "every Monday").
- Only **one instance exists at a time.**
- The next instance is spawned at **notification time** (when the toast fires), not on completion. This avoids the "user forgets to complete → recurrence dies" failure mode.
- If the user marks the current instance done before the next fires, the spawn-on-fire still produces the next one on schedule.
- Recurring tasks **can** be mirrored if classification flags them. Behavior of mirroring across spawned instances (mirror every instance vs. only the first) is **deferred** — to be decided when the recurring + mirror combination is first exercised in practice.

---

## 7. Lifecycle (mirrored tasks)

The board owns the remote object it created. Mapping is stored as `external_id` + `external_provider` on the task row.

| Local action | Remote action |
|---|---|
| Create mirrored task (via AI classification at creation) | POST new remote task |
| Toggle "mirror" ON for an existing local-only task (UI button on the task) | POST new remote task, store `external_id` |
| Toggle "mirror" OFF for an existing mirrored task (same UI button) | DELETE remote task, clear `external_id` |
| Edit title / due / lead-time of a mirrored task | PATCH remote task |
| Mark done | PATCH remote task `status = completed` (not delete) |
| Delete task | DELETE remote task (with first-time confirmation dialog) |
| Move to Done tab | same as "mark done" above |

The per-task mirror toggle is a small button/icon on the task card in the board. It is the manual counterpart to the AI's automatic classification — the user can always override either direction.

**No two-way sync.** Changes made directly in Google/Microsoft are not pulled back. Acceptance of staleness is explicit.

**Drift detection** is performed on app start only. For each mirrored task with `status != completed` locally, compare the remote `updated` timestamp to what we last stored. If different, show a small "⚠ remote differs" badge on the task in the UI. No automatic resolution.

---

## 8. Done tab and archive

Per category, the UI has two tabs:

- **Open** (default) — current active tasks.
- **Done** — completed tasks for this category.

The Done tab shows **all** done tasks (no UI-side hiding).

Tasks that were mirrored show a small "was mirrored" indicator in the Done tab so the user understands why no remote object exists to look up (the remote was marked complete, not deleted, but it lives in the user's Google/Microsoft account and is not re-fetched here).

A separate **archive SQLite DB** holds tasks older than 30 days. Move semantics:

- The current data pipeline already reads tasks for edit/delete operations.
- A background thread, triggered as part of that existing pipeline pass, evaluates each row's age and moves rows older than 30 days from the live DB to the archive DB.
- Archive DB is a separate file (`archive.db`) for portability and to keep the live DB small.
- The Done tab queries live DB first; if the user scrolls or requests "show older," it queries the archive DB on demand.
- Archived rows retain their `external_id` but are not actively synced or drift-checked.

---

## 9. Offline / failure / auth

- **First-run flow.** After the user enters their Gemini API key on the start page, suggest connecting Google or Microsoft. Not modal — dismissable. A persistent banner remains on the board until the user either connects or explicitly dismisses-forever.
- **OAuth pop-up.** When the user initiates connection (from start page, settings, or banner), a pop-up window handles the OAuth flow.
- **Mirror call fails (network, transient API error).** The mirror request is queued. A small counter UI shows pending mirror operations. Retried in background.
- **Token expired / revoked.** The OAuth pop-up is re-opened to reconnect. Pending queue continues to accumulate during the disconnected window and drains on reconnect.
- **Voice command says "mirror" but no provider connected.** Local task is still created. The user is told the mirror was skipped (in the post-processing toast).

---

## 10. Time zones

- Store every `due_at` as **UTC + IANA zone string** (e.g., `Asia/Jerusalem`). Use `zoneinfo` from stdlib.
- Render in the **stored zone** in the UI, always — even if the user's current system zone differs (travel case). The displayed time is the time the task was created against. No prompts or auto-conversion on system-zone change.
- Schedule against UTC internally.
- For recurring rules ("every weekday 9am"), store as **wall-clock + zone**, compute the next UTC fire time at spawn. This preserves "9am stays 9am" across DST.
- No detection or prompting on system-zone change (out of scope).

---

## 11. Data model deltas

Additions to the task row:

- `due_at_utc: datetime | null`
- `due_tz: string | null` (IANA)
- `lead_time_minutes: int` (default 30)
- `is_full_day: bool`
- `recurrence_rule: string | null`
- `mirror_to_remote: bool`
- `external_provider: "google" | "microsoft" | null`
- `external_id: string | null`
- `external_updated_at: datetime | null` (for drift detection)
- `mirror_pending: bool` (in retry queue)

Settings table additions:

- `remote_provider: "google" | "microsoft" | null`
- OAuth tokens (encrypted at rest).
- `connect_banner_dismissed: bool`

---

## 12. Out of scope for v1

- Calendar event mirroring (rejected — clutter).
- Two-way sync of any field (including completion).
- Voice verbs to add/remove the mirror flag on existing tasks (deferred until requested).
- Per-task quiet hours (user's responsibility).
- Snooze affecting the remote notification.
- Multi-provider connections at the same time.
- Automated eval harness for the classification prompt.
- Periodic / pre-fire drift checks (app start only).

---

## 13. Open implementation questions (to resolve at build time, not now)

- Library for Windows toasts that supports actionable buttons (dismiss / snooze 10m) on Windows 11.
- Local scheduler choice (APScheduler vs. custom asyncio loop).
- Encryption-at-rest scheme for OAuth tokens.
- OAuth client registration (Google Cloud project + Microsoft Entra app) — who owns the client IDs in distribution.
