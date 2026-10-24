#!/usr/bin/env python3
"""Backup and restore Veritas so that a restore proves itself.

  backup_restore.py backup  [--db veritas] [--out backups]
  backup_restore.py restore  BACKUP_DIR [--db veritas_restored] [--witness PATH_OR_DIR] [--force]
  backup_restore.py verify  [--db veritas] [--witness PATH_OR_DIR]

backup   verifies the live ledger first (a backup of a tampered ledger is worth nothing), then writes
         <out>/veritas-<UTC time>/{db.dump, witness/, MANIFEST.json (SHA-256 of every file)}.
restore  checks the manifest, loads the dump into a NEW database (never over an existing one unless --force),
         then runs verify_all_chains() and compares every batch with the witness. A restore is reported GOOD
         only if both agree, so a backup that was altered after the fact is caught here.
Connection settings come from the usual PG* environment variables (pg_dump / pg_restore / psql must be on PATH).
"""
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import anchor_service as A  # noqa: E402
import merkle  # noqa: E402


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)
    if r.returncode:
        raise SystemExit(f"{cmd[0]} failed: {r.stderr.strip()}")
    return r.stdout


def psql(db, sql):
    return [ln.split("\t") for ln in run(["psql", "-d", db, "-AtqX", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql]).splitlines() if ln]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_witness(path):
    if path and os.path.isdir(path):
        return A.GitWitness(path) if os.path.isdir(os.path.join(path, ".git")) else A.FileWitness(os.path.join(path, "anchors.jsonl"))
    return A.FileWitness(path or "witness.jsonl")


def ledger_report(db, witness_path):
    """(ok, lines): database chains + marks + batches, then every witnessed batch recomputed from the revisions."""
    lines, ok = [], True
    for cid, chain_ok, _seq, problem, marks_ok, batches_ok in psql(db, "select cid, chain_ok, first_bad_seq, problem, marks_ok, batches_ok from verify_all_chains()"):
        good = chain_ok == "t" and marks_ok == "t" and batches_ok == "t"
        ok &= good
        lines.append(f"  course {cid}: chain {chain_ok} marks {marks_ok} batches {batches_ok}" + ("" if good else f"   <-- {problem}"))
    w = open_witness(witness_path)
    wok, wmsg = w.self_check()
    ok &= wok
    lines.append(f"  witness: {wmsg}")
    if hasattr(w, "records"):
        for rec in w.records():
            p = rec["payload"]
            hs = [r[0] for r in psql(db, f"select row_hash from mark_revisions where course_id={p['course_id']} and seq between {p['seq_from']} and {p['seq_to']} order by seq")]
            good = len(hs) == p["seq_to"] - p["seq_from"] + 1 and merkle.root(hs) == p["merkle_root"]
            ok &= good
            if not good:
                lines.append(f"  course {p['course_id']} seq {p['seq_from']}-{p['seq_to']}: does NOT match the witnessed root")
    return ok, lines


def backup(db, out, witness_path):
    ok, lines = ledger_report(db, witness_path)
    print("\n".join(lines))
    if not ok:
        raise SystemExit("refusing to back up: the ledger does not verify (fix or investigate first)")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(out, f"veritas-{stamp}")
    os.makedirs(dest)
    run(["pg_dump", "-Fc", "-d", db, "-f", os.path.join(dest, "db.dump")])
    if witness_path and os.path.exists(witness_path):
        if os.path.isdir(witness_path):
            shutil.copytree(witness_path, os.path.join(dest, "witness"))
        else:
            os.makedirs(os.path.join(dest, "witness")); shutil.copy(witness_path, os.path.join(dest, "witness", os.path.basename(witness_path)))
    files = {}
    for root, _d, names in os.walk(dest):
        for n in names:
            full = os.path.join(root, n)
            files[os.path.relpath(full, dest).replace(os.sep, "/")] = sha256(full)
    json.dump({"created_utc": stamp, "database": db, "files": files}, open(os.path.join(dest, "MANIFEST.json"), "w"), indent=2)
    print(f"backup written to {dest}  ({len(files)} files, manifest signed with SHA-256)")
    return dest


def restore(src, db, witness_path, force):
    man = json.load(open(os.path.join(src, "MANIFEST.json")))
    for rel, want in man["files"].items():
        if sha256(os.path.join(src, rel)) != want:
            raise SystemExit(f"MANIFEST mismatch: {rel} was changed after the backup was taken")
    print(f"manifest ok ({len(man['files'])} files)")
    exists = psql("postgres", f"select 1 from pg_database where datname = '{db}'")
    if exists and not force:
        raise SystemExit(f"database {db} already exists; choose another name or pass --force")
    if exists:
        run(["psql", "-d", "postgres", "-qc", f"DROP DATABASE {db} WITH (FORCE)"])
    run(["psql", "-d", "postgres", "-qc", f"CREATE DATABASE {db}"])
    r = subprocess.run(["pg_restore", "--no-owner", "-d", db, os.path.join(src, "db.dump")], capture_output=True, text=True, encoding="utf-8")
    if r.returncode and "already exists" not in r.stderr:
        raise SystemExit("pg_restore failed: " + r.stderr[:400])
    wdir = witness_path or os.path.join(src, "witness")
    if os.path.isdir(wdir) and not os.path.exists(os.path.join(wdir, "anchors.jsonl")) and os.path.isdir(os.path.join(wdir, "witness")):
        wdir = os.path.join(wdir, "witness")
    if os.path.isdir(wdir):
        files = [f for f in os.listdir(wdir) if f.endswith(".jsonl")]
        wpath = wdir if os.path.exists(os.path.join(wdir, ".git")) else (os.path.join(wdir, files[0]) if files else wdir)
    else:
        wpath = wdir
    ok, lines = ledger_report(db, wpath)
    print("\n".join(lines))
    print("RESTORE GOOD: ledger and witness agree" if ok else "RESTORE BAD: the restored ledger does not match its witness")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["backup", "restore", "verify"])
    ap.add_argument("src", nargs="?")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default="backups")
    ap.add_argument("--witness", default=os.environ.get("WITNESS_PATH", "witness.jsonl"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "backup":
        backup(a.db or "veritas", a.out, a.witness)
    elif a.cmd == "verify":
        ok, lines = ledger_report(a.db or "veritas", a.witness); print("\n".join(lines)); sys.exit(0 if ok else 1)
    else:
        if not a.src:
            raise SystemExit("restore needs the backup directory")
        sys.exit(0 if restore(a.src, a.db or "veritas_restored", a.witness if a.witness != "witness.jsonl" else None, a.force) else 1)
