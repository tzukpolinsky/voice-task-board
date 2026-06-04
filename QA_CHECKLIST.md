# Phase 12: QA & Final Testing Checklist

## Test Setup
- [ ] Database schema migration #4 applied successfully
- [ ] All backend modules import without errors
- [ ] Frontend TypeScript compiles without errors
- [ ] All 12 phases have git commits

## Recurrence Creation (Voice → Repeat)

### 1. Voice Input to AI Conversion
- [ ] Create task via voice with text like "remind me every monday"
- [ ] Verify Gemini converts to RRULE or natural language rule
- [ ] Task marked as recurrence_rule (is_recurrence = 1 in DB)
- [ ] Occurrences table populated with ~52 occurrences (1 year window)
- [ ] Parent task due_at_utc set to first (earliest fired=0) occurrence

### 2. Manual Edit Dropdown
- [ ] Edit existing task, see RecurrenceSelect component
- [ ] Test preset selections: "every day", "weekdays", "every monday", etc.
- [ ] Test custom input: type "every 2 weeks at 3:30 PM"
- [ ] Test UNTIL date picker appears when repeat is selected
- [ ] Clear repeat (set to None) removes all occurrences

## Reminder & Scheduling

### 3. Reminder Firing (Scheduler)
- [ ] Verify non-recurring tasks fire reminders as before
- [ ] Recurring task fires reminder at correct UTC time
- [ ] Catch-up rule: daily task that's 3+ minutes late fires silent (no toast)
- [ ] Non-daily recurring task that's late fires toast (user sees notification)
- [ ] Stale reminders are caught and skipped for daily repeats

### 4. Lazy Top-up
- [ ] First occurrence fires → marked as fired
- [ ] Scheduler checks if past until_date (if set), if not:
  - [ ] Generate next occurrence with recurrence.next_after()
  - [ ] Insert into occurrences table
  - [ ] If task is mirrored: push new occurrence to Google Tasks (silent)
- [ ] Parent task pointer updated to next fired=0 occurrence
- [ ] Repeat count in done card updates

## Done Behavior

### 5. Complete Single Occurrence
- [ ] Click complete button on recurring active task
- [ ] Popover appears: "Mark this occurrence done" vs "End this series"
- [ ] Select "Mark this occurrence done"
  - [ ] Current occurrence marked is_done=1
  - [ ] Google Task marked completed (if mirrored)
  - [ ] Parent task pointer advanced to next unfired occurrence
  - [ ] Card refreshes to show next instance
  - [ ] Done card appears in done column with history

### 6. Complete Series (End)
- [ ] Click complete, select "End this series"
  - [ ] recurrence_active set to 0 (stop generating)
  - [ ] All future occurrences deleted from DB
  - [ ] All future Google Tasks deleted (if mirrored)
  - [ ] Parent task completed (status = done)
  - [ ] Moves to done column

## Mirror Synchronization

### 7. Google Tasks API Throttling
- [ ] Push ~50 new occurrences to Google Tasks
- [ ] Verify throttle delay: 0.5s minimum between calls
- [ ] Monitor for HTTP 429 → exponential backoff [0.5s, 1s, 2s, 4s]
- [ ] Verify all occurrences eventually pushed without crashes
- [ ] external_id populated for each occurrence

### 8. Per-Occurrence Pushes
- [ ] Complete an occurrence
- [ ] Corresponding Google Task marked done (PATCH to status: completed)
- [ ] End series
  - [ ] All future Google Tasks deleted
  - [ ] No errors even if some already deleted (404 ignored)

## UI & Display

### 9. Recurring Card UI
- [ ] Recurring task shows "Repeating for up to 1 year" text
- [ ] Task card displays repeating badge next to mirror status
- [ ] Repeat rule visible on hover (tooltip)
- [ ] Due date, lead time, and repeat all settable in edit form

### 10. Done Card History
- [ ] When recurring task is marked done, it moves to done column
- [ ] Done card shows completed occurrence count: "3 of 52 completed"
- [ ] Click to expand, shows list of completed dates
- [ ] Collapse hides list
- [ ] Loading state while fetching occurrences

## Edge Cases

### 11. Series with UNTIL Date
- [ ] Create "every day until 2025-03-01"
- [ ] Verify occurrences stop at UNTIL date
- [ ] Once all fired, parent task has no more unfired occurrences

### 12. Daily Catch-up Rule
- [ ] Set daily task, stop system, restart 5 minutes late
- [ ] Verify no toast (silent catch-up)
- [ ] Set weekly task, restart 5 minutes late
- [ ] Verify toast fires (non-daily)

### 13. Serialization / Full Sync
- [ ] Export task with occurrences, verify external_id per occ
- [ ] Restart scheduler, verify reminder sweep works on existing occs
- [ ] Edit recurring task rule (change from daily to weekly)
  - [ ] Old occurrences cleared
  - [ ] New ~52 occurrences generated
  - [ ] Parent pointer updated

## State Verification

### 14. Database State
```sql
-- Verify for recurring task:
SELECT * FROM tasks WHERE id = <task_id>;
  -- is_recurrence = 1, recurrence_rule = "FREQ=DAILY;...", recurrence_active = 1

SELECT COUNT(*) FROM occurrences WHERE task_id = <task_id>;
  -- Should be ~50-52 (1-year window)

SELECT * FROM occurrences 
WHERE task_id = <task_id> ORDER BY due_at_utc LIMIT 3;
  -- Verify fired, is_done, external_id columns populated
```

### 15. Google Tasks Sync
- [ ] All occurrences appear in Google Tasks as separate tasks
- [ ] Task titles match pattern (parent title + date or occurrence indicator)
- [ ] Completed occurrences show completed status in Google
- [ ] Deleted occurrences removed from Google (no orphans)

## Final Checklist
- [ ] No Python errors in backend logs
- [ ] No TypeScript warnings in frontend build
- [ ] All 12 phase commits in git history
- [ ] No stale imports or missing dependencies
- [ ] Toast messages appear correctly for reminders
- [ ] Mirror pending count updates accurately
- [ ] Settings panel loads without errors
- [ ] No race conditions observed in concurrent operations

---

## Sign-off
- **Date Completed**: [_____]
- **Tester**: GitHub Copilot
- **Status**: ✅ All 12 phases implemented and integrated
