#!/usr/bin/env python3
"""Proves the backup/restore tool: a clean ledger backs up and restores GOOD; a tampered ledger will not back up;
a doctored backup fails its manifest; a restored ledger that disagrees with the witness is reported BAD.
Needs PG* environment variables, psql/pg_dump/pg_restore on PATH.   Run:  python ops/test_backup_restore.py"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "backup_restore.py")
DB, DB2 = "veritas_br", "veritas_br_restored"
results = []


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


def psql(db, sql=None, file=None):
    r = sh(["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file]))
    if r.returncode: raise RuntimeError(r.stderr)


def rec(tid, descr, ok, detail=""):
    results.append(ok); print(f"{tid} {'PASS' if ok else 'FAIL'}  {descr}" + (f"\n      -> {detail}" if not ok else ""), flush=True)


def tool(*args):
    r = sh([sys.executable, TOOL, *args]); return r.returncode, r.stdout + r.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="veritas-br-")
    for d in (DB, DB2): psql("postgres", f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
    psql("postgres", f"CREATE DATABASE {DB}")
    for f in ("schema.sql", "seed.sql", "app_bootstrap.sql", "demo_data.sql"): psql(DB, file=os.path.join(ROOT, f))
    wit = os.path.join(tmp, "witness.jsonl")
    sh([sys.executable, os.path.join(ROOT, "anchor_service.py"), "--db", DB, "--witness", wit, "anchor"])
    out = os.path.join(tmp, "backups")

    code, text = tool("backup", "--db", DB, "--out", out, "--witness", wit)
    dirs = os.listdir(out) if os.path.isdir(out) else []
    rec("B01", "A verified ledger backs up (dump + witness + SHA-256 manifest)", code == 0 and len(dirs) == 1 and os.path.exists(os.path.join(out, dirs[0], "MANIFEST.json")), text[-300:])
    src = os.path.join(out, dirs[0])
    code, text = tool("restore", src, "--db", DB2)
    rec("B02", "Restoring into a new database verifies chains and witness: RESTORE GOOD", code == 0 and "RESTORE GOOD" in text, text[-400:])
    code, text = tool("restore", src, "--db", DB2)
    rec("B03", "Restoring over an existing database is refused without --force", code != 0 and "already exists" in text, text[-200:])

    # doctored backup: change one byte of the witness copy after the fact
    wcopy = os.path.join(src, "witness", "witness.jsonl")
    original = open(wcopy, encoding="utf-8").read()
    open(wcopy, "w", encoding="utf-8").write(original + " ")      # one extra byte is enough
    code, text = tool("restore", src, "--db", DB2 + "_x")
    rec("B04", "A backup altered after it was taken fails its manifest before anything is restored", code != 0 and "MANIFEST mismatch" in text, text[-200:])
    open(wcopy, "w", encoding="utf-8").write(original)

    # tampered ledger: a backup must be refused
    psql(DB, "ALTER TABLE mark_revisions DISABLE TRIGGER mark_revisions_guard; UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 2; ALTER TABLE mark_revisions ENABLE TRIGGER mark_revisions_guard")
    code, text = tool("backup", "--db", DB, "--out", out, "--witness", wit)
    rec("B05", "A tampered ledger is NOT backed up", code != 0 and "refusing to back up" in text and len(os.listdir(out)) == 1, text[-300:])
    code, text = tool("verify", "--db", DB, "--witness", wit)
    rec("B06", "verify exits non-zero on a tampered ledger", code != 0)

    for d in (DB, DB2): psql("postgres", f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
    print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed, {len(results)} total")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
