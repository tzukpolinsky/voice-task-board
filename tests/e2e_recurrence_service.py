"""Deeper verification: fresh DB migration + full service-layer flow."""
import os, tempfile, pathlib, datetime as dt
tmpdir = tempfile.mkdtemp()
import voice_task_board.paths as paths
paths.app_data_dir = lambda: pathlib.Path(tmpdir)
import voice_task_board.db as dbmod
dbmod._db = None
db = dbmod.get_db()

# 1. Fresh migration ran to latest version
with db._lock:
    v = db._conn.execute("PRAGMA user_version").fetchone()[0]
print(f"[mig] fresh DB user_version = {v}")
assert v >= 5, f"expected >=5, got {v}"
# occurrences table + new columns exist
cols = [r[1] for r in db._conn.execute("PRAGMA table_info(occurrences)").fetchall()]
assert "last_notified_date" in cols, "last_notified_date missing"
tcols = [r[1] for r in db._conn.execute("PRAGMA table_info(tasks)").fetchall()]
for c in ("is_recurrence","recurrence_until","recurrence_active"):
    assert c in tcols, f"{c} missing from tasks"
print(f"[mig] occurrences cols ok, tasks recurrence cols ok")

# 2. current_occurrence is is_done-based (not fired)
tid = db.add_task("svc test", "default", recurrence_rule="FREQ=DAILY")
db.set_recurrence(tid, "FREQ=DAILY", None)
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
def past(d): return (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S")
db.add_occurrences(tid, [past(2), past(1), now])
occs = db.list_occurrences(tid)
# Fire the earliest (simulate it was notified, still undone)
db.mark_occurrence_fired(occs[0].id)
cur = db.current_occurrence(tid)
assert cur.id == occs[0].id, f"current must be earliest UNDONE (fired irrelevant), got {cur.id} vs {occs[0].id}"
print(f"[inv] current_occurrence ignores fired, returns earliest undone  OK")

# 3. complete_occurrence (service) advances correctly + keeps history
import voice_task_board.occurrences_service as svc
svc.complete_occurrence(occs[0].id)
assert db.count_done_occurrences(tid) == 1
cur2 = db.current_occurrence(tid)
assert cur2.id == occs[1].id, "after completing one, current advances to next undone"
print(f"[svc] complete_occurrence advances to next undone, history=1  OK")

# 4. end_series: marks inactive, deletes future, parent done
svc.end_series(tid)
t = db.get_task(tid)
assert t.recurrence_active == 0, "series not marked inactive"
assert t.status == "done", "parent not completed"
# future occurrences gone, done one kept
remaining = db.list_occurrences(tid)
assert all(o.is_done == 1 for o in remaining), f"future occurrences not purged: {[(o.id,o.is_done) for o in remaining]}"
print(f"[svc] end_series: inactive + parent done + future purged, kept {len(remaining)} done  OK")

# 5. resolve_pile dismiss vs done
tid2 = db.add_task("pile", "default", recurrence_rule="FREQ=WEEKLY;BYDAY=MO")
db.set_recurrence(tid2, "FREQ=WEEKLY;BYDAY=MO", None)
db.add_occurrences(tid2, [past(8), past(1)])
import voice_task_board.recurrence_service as rsvc
rsvc.resolve_pile(tid2, done=False)  # dismiss
assert db.count_done_occurrences(tid2) == 0, "dismiss must NOT mark done"
rsvc.resolve_pile(tid2, done=True)   # mark all done
assert db.count_done_occurrences(tid2) == 2, "mark-all-done must complete all"
print(f"[svc] resolve_pile dismiss(0 done) -> done(2 done)  OK")

print("\nE2E SERVICE VERIFICATION PASSED")
