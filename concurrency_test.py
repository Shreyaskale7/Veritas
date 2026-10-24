#!/usr/bin/env python3
"""T-C1..C3: lock behaviour of the per-course chain. Rebuilds database veritas_cc."""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def psql(db, sql=None, file=None):
    cmd = ["psql", "-d", db, "-qAtX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file])
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


psql("postgres", "DROP DATABASE IF EXISTS veritas_cc"); psql("postgres", "CREATE DATABASE veritas_cc")
for f in ("schema.sql", "seed.sql"):
    assert psql("veritas_cc", file=os.path.join(HERE, f)).returncode == 0


def mark(s, c, t):
    return f"(select mark_id from marks where student_id={s} and course_id={c} and assessment_type='{t}')"


def job(uid, mid_expr, val, hold):
    sql = (f"BEGIN; select set_config('veritas.user_id','{uid}',true); select apply_change({mid_expr},{val},'concurrency test',{uid}); "
           + (f"select pg_sleep({hold}); " if hold else "") + "COMMIT;")
    t0 = time.time()
    p = subprocess.Popen(["psql", "-d", "veritas_cc", "-qAtX", "-v", "ON_ERROR_STOP=1", "-c", sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p, t0


HOLD = 3.0
a, ta = job(2, mark(5, 1, "CIE-1"), 30, HOLD)        # course 1, holds its transaction open for 3 s
time.sleep(0.8)
b, tb = job(2, mark(6, 1, "CIE-1"), 31, 0)           # course 1 again: must wait for A
c, tc = job(3, mark(5, 2, "CIE-1"), 32, 0)           # course 2: must not wait
c.communicate(); dc = time.time() - tc
b.communicate(); db_ = time.time() - tb
a.communicate(); da = time.time() - ta

order = psql("veritas_cc", "select course_id||':'||seq||':'||mark_id from mark_revisions order by changed_at").stdout.split()
chain = psql("veritas_cc", "select string_agg(course_id||':'||ok::text, ',' order by course_id) from (select 1 as course_id, ok from verify_chain(1) union all select 2, ok from verify_chain(2)) x").stdout.strip()

rows = [
    ("C1", "Writer on the SAME course waits for an open transaction on that course's chain (A holds 3.0 s, B started 0.8 s later)",
     db_ >= 2.0, f"B finished after {db_:.2f} s (A: {da:.2f} s)"),
    ("C2", "Writer on a DIFFERENT course is not blocked by it", dc < 0.6 * HOLD and dc < da - 1.0, f"C finished after {dc:.2f} s while A was still open (A: {da:.2f} s)"),   # relative to the hold, so slow process start-up does not flake it,
    ("C3", "After the race both chains are contiguous and verify (no duplicated or skipped seq)", chain == "1:true,2:true", f"{chain}; commit order {order}"),
]
for i, (tid, d, ok, det) in enumerate(rows):
    print(f"{tid}  {'PASS' if ok else 'FAIL'}  {d}\n        -> {det}")
sys.exit(0 if all(r[2] for r in rows) else 1)
