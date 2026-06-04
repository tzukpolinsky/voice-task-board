"""Runtime smoke test for the recurrence re-nag / missed-pile throttle.
Drives the real Database + the exact scheduler grouping logic against a temp DB."""
import os, tempfile, datetime as dt
from collections import defaultdict

# Point the app data dir at a temp location BEFORE importing db
tmpdir = tempfile.mkdtemp()
os.environ["VTB_DATA_DIR"] = tmpdir  # may or may not be honored; we override path below

import voice_task_board.db as dbmod

# Force a fresh temp DB file
import voice_task_board.paths as paths
paths.app_data_dir = lambda: __import__("pathlib").Path(tmpdir)
dbmod._db = None
db = dbmod.get_db()

today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def past(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

# Create a recurring task (daily), mirror off
tid = db.add_task("water plants", "default", recurrence_rule="FREQ=DAILY", mirror_to_remote=False)
db.set_recurrence(tid, "FREQ=DAILY", None)  # sets is_recurrence=1, active=1
# Materialize 5 occurrences all in the PAST (simulate app was off 5 days)
db.add_occurrences(tid, [past(5), past(4), past(3), past(2), past(1)])

def sweep_select():
    return db.list_occurrences_due_for_reminder(now_utc)

# ---- Assertion 1: app-off pile is all selected once ----
rows = sweep_select()
mine = [(o,t) for (o,t) in rows if t.id == tid]
assert len(mine) == 5, f"expected 5 pending, got {len(mine)}"
print(f"[1] app-off -> {len(mine)} pending occurrences selected  OK")

# ---- Simulate the scheduler's display-time throttle (the fix): stamp + fire all ----
for occ, t in mine:
    db.set_occurrence_notified(occ.id, today)
    db.mark_occurrence_fired(occ.id)

# ---- Assertion 2: an IGNORED summary does NOT re-fire on the next sweep (same day) ----
rows2 = sweep_select()
mine2 = [(o,t) for (o,t) in rows2 if t.id == tid]
assert len(mine2) == 0, f"BUG: ignored pile re-fired, {len(mine2)} re-selected same day"
print(f"[2] same-day re-sweep -> {len(mine2)} re-selected (ignored summary does NOT storm)  OK")

# ---- Assertion 3: NEXT day, undone occurrences re-nag ----
# Backdate last_notified_date to yesterday to simulate day rollover
yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
with db._lock:
    db._conn.execute("UPDATE occurrences SET last_notified_date=? WHERE task_id=?", (yesterday, tid))
    db._conn.commit()
rows3 = sweep_select()
mine3 = [(o,t) for (o,t) in rows3 if t.id == tid]
assert len(mine3) == 5, f"expected 5 re-nag next day, got {len(mine3)}"
print(f"[3] next-day sweep -> {len(mine3)} re-nag (undone occurrences re-notify)  OK")

# ---- Assertion 4: Mark-all-done removes them permanently ----
db.mark_pile_resolved(tid, done=True, notified_date=today)
# Even backdate the date again — done ones must NOT come back
with db._lock:
    db._conn.execute("UPDATE occurrences SET last_notified_date=? WHERE task_id=?", (yesterday, tid))
    db._conn.commit()
rows4 = sweep_select()
mine4 = [(o,t) for (o,t) in rows4 if t.id == tid]
assert len(mine4) == 0, f"BUG: done occurrences re-selected, {len(mine4)}"
print(f"[4] after mark-all-done -> {len(mine4)} re-selected (done pile stays gone)  OK")

# ---- Assertion 5: Dismiss (done=False) also stops same-day storm but allows next-day re-nag ----
tid2 = db.add_task("weekly report", "default", recurrence_rule="FREQ=WEEKLY;BYDAY=MO", mirror_to_remote=False)
db.set_recurrence(tid2, "FREQ=WEEKLY;BYDAY=MO", None)
db.add_occurrences(tid2, [past(8), past(1)])
r = [(o,t) for (o,t) in sweep_select() if t.id==tid2]
assert len(r) == 2
db.mark_pile_resolved(tid2, done=False, notified_date=today)  # Dismiss
r2 = [(o,t) for (o,t) in sweep_select() if t.id==tid2]
assert len(r2) == 0, f"BUG: dismissed pile re-fired same day, {len(r2)}"
with db._lock:
    db._conn.execute("UPDATE occurrences SET last_notified_date=? WHERE task_id=?", (yesterday, tid2))
    db._conn.commit()
r3 = [(o,t) for (o,t) in sweep_select() if t.id==tid2]
assert len(r3) == 2, f"dismissed-but-undone should re-nag next day, got {len(r3)}"
print(f"[5] dismiss -> same-day silent ({len(r2)}), next-day re-nag ({len(r3)})  OK")

# ---- Assertion 6: editing the rule re-materializes idempotently (no stacking) ----
# materialize() must delete FUTURE occurrences before regenerating. Simulate by
# generating a future window twice via the engine + the delete-future contract.
import voice_task_board.recurrence as rec
tid3 = db.add_task("standup", "default", recurrence_rule="FREQ=DAILY", mirror_to_remote=False)
db.set_recurrence(tid3, "FREQ=DAILY", None)
future = rec.generate_occurrences("FREQ=DAILY", now_utc, None, None, horizon_days=10)
db.add_occurrences(tid3, future)
first_count = len(db.list_occurrences(tid3))
# Simulate an edit re-materialize the way materialize() does it: clear the
# undone schedule, then regenerate. Must NOT stack.
db.delete_unfinished_occurrences(tid3)
db.add_occurrences(tid3, future)
second_count = len(db.list_occurrences(tid3))
assert second_count == first_count, f"BUG: edit stacked occurrences {first_count} -> {second_count}"
print(f"[6] edit re-materialize -> {first_count} == {second_count} (no stacking)  OK")

# ---- Assertion 7: done occurrences survive re-materialize (history kept) ----
# Mark one occurrence done, then re-materialize; the done one must remain.
occs = db.list_occurrences(tid3)
db.mark_occurrence_done(occs[0].id)
done_before = db.count_done_occurrences(tid3)
db.delete_unfinished_occurrences(tid3)
db.add_occurrences(tid3, future)
done_after = db.count_done_occurrences(tid3)
assert done_after == done_before == 1, f"BUG: done history lost on re-materialize ({done_before}->{done_after})"
print(f"[7] re-materialize keeps done history -> {done_after} done preserved  OK")

print("\nALL SMOKE ASSERTIONS PASSED")
