#!/usr/bin/env python3
"""External anchoring and verification for Veritas.

The database stores Merkle batches. This service copies each batch root into a WITNESS that the
database administrator does not control, and later checks the database against it.

Witness backends
  FileWitness     tested. Append-only JSON-lines file; each line is hash-linked to the previous one, so
                  editing or removing a line is detectable. Stand-in for a separate trust domain.
  ImmudbWitness   NOT run in this project's sandbox (no immudb server available). Written against the
                  immudb-py calls verifiedSet / verifiedGet. Check it against your immudb version.

Usage:  anchor_service.py --db veritas [--type git] --witness /path/witness.jsonl  anchor | verify | proof COURSE SEQ
Connection settings come from the usual PG* environment variables.
"""
import argparse, hashlib, json, os, subprocess, sys
import merkle

GENESIS = "0" * 64


def psql(db, sql):
    r = subprocess.run(["psql", "-d", db, "-AtX", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    return [ln.split("\t") for ln in r.stdout.splitlines() if ln != ""]


class FileWitness:
    kind = "file"

    def __init__(self, path):
        self.path = path

    def records(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    @staticmethod
    def _line_hash(prev, payload):
        return hashlib.sha256((prev + json.dumps(payload, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()

    def append(self, payload):
        recs = self.records()
        prev = recs[-1]["line_hash"] if recs else GENESIS
        rec = {"i": len(recs) + 1, "payload": payload, "prev": prev, "line_hash": self._line_hash(prev, payload)}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return f"witness#{rec['i']}"

    def self_check(self):
        """Returns (ok, message): the witness file must be internally hash-linked."""
        prev = GENESIS
        for n, rec in enumerate(self.records(), 1):
            if rec["i"] != n or rec["prev"] != prev or rec["line_hash"] != self._line_hash(prev, rec["payload"]):
                return False, f"witness line {n} is inconsistent"
            prev = rec["line_hash"]
        return True, "witness file intact"


class GitWitness(FileWitness):
    """Hash-linked witness file kept in its own git repository: one commit per anchor.
    Set `remote` (WITNESS_GIT_REMOTE) and every anchor is also pushed there, which is what puts the
    witness outside the database administrator's trust domain. Without a remote it is still a
    tamper-evident history (git log + the line hash chain), but on the same machine."""
    kind = "git"

    def __init__(self, repo, remote=None):
        self.repo, self.remote = repo, remote
        super().__init__(os.path.join(repo, "anchors.jsonl"))
        os.makedirs(repo, exist_ok=True)
        if not os.path.isdir(os.path.join(repo, ".git")):
            self._git("init", "-q")
            self._git("config", "user.name", "veritas-witness")
            self._git("config", "user.email", "witness@veritas.local")
            if remote:
                self._git("remote", "add", "origin", remote)

    def _git(self, *args, check=True):
        r = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, encoding="utf-8")
        if check and r.returncode:
            raise RuntimeError("git " + " ".join(args) + ": " + r.stderr.strip())
        return r

    def append(self, payload):
        ref = super().append(payload)
        self._git("add", "anchors.jsonl")
        self._git("commit", "-q", "-m", f"anchor {ref}: course {payload['course_id']} seq {payload['seq_from']}-{payload['seq_to']}")
        sha = self._git("rev-parse", "--short", "HEAD").stdout.strip()
        if self.remote:
            self._git("push", "-q", "origin", "HEAD")
        return f"git:{sha}:{ref}"

    def self_check(self):
        ok, msg = super().self_check()
        if not ok:
            return ok, msg
        if self._git("status", "--porcelain", "anchors.jsonl", check=False).stdout.strip():
            return False, "anchors.jsonl has uncommitted changes (edited outside the witness)"
        commits = self._git("rev-list", "--count", "HEAD", check=False).stdout.strip() or "0"
        if int(commits) != len(self.records()):
            return False, f"git history has {commits} commits but the file has {len(self.records())} anchors"
        return True, "git witness intact"


def make_witness(kind=None, **env):
    """Witness chosen by WITNESS_TYPE (file | git | immudb); defaults to file."""
    e = {**os.environ, **env}
    kind = kind or e.get("WITNESS_TYPE", "file")
    if kind == "git":
        return GitWitness(e.get("WITNESS_GIT_DIR", "witness-repo"), e.get("WITNESS_GIT_REMOTE") or None)
    if kind == "immudb":
        return ImmudbWitness(e.get("IMMUDB_URL", "localhost:3322"), e.get("IMMUDB_USER", "immudb"), e.get("IMMUDB_PASSWORD", "immudb"))
    return FileWitness(e.get("WITNESS_PATH", "witness.jsonl"))


class ImmudbWitness:
    """Untested here. One key per batch: veritas/<course>/<seq_from>-<seq_to> -> merkle_root."""
    kind = "immudb"

    def __init__(self, url="localhost:3322", user="immudb", password="immudb"):
        from immudb import ImmudbClient          # pip install immudb-py
        self.c = ImmudbClient(url)
        self.c.login(user, password)

    def append(self, payload):
        key = f"veritas/{payload['course_id']}/{payload['seq_from']}-{payload['seq_to']}".encode()
        res = self.c.verifiedSet(key, payload["merkle_root"].encode())
        return f"immudb:tx{res.id}"

    def records(self):
        raise NotImplementedError("use verifiedGet per batch key")

    def self_check(self):
        return True, "immudb verifies its own proofs on every verifiedGet"


def batches(db):
    rows = psql(db, "select batch_id, course_id, seq_from, seq_to, merkle_root from merkle_batches order by batch_id")
    return [dict(batch_id=int(a), course_id=int(b), seq_from=int(c), seq_to=int(d), merkle_root=e) for a, b, c, d, e in rows]


def anchor(db, w):
    done = {int(r[0]) for r in psql(db, "select batch_id from anchors where anchor_type = '%s'" % w.kind)}
    n = 0
    for b in batches(db):
        if b["batch_id"] in done:
            continue
        ref = w.append({k: b[k] for k in ("course_id", "seq_from", "seq_to", "merkle_root")})
        psql(db, "select record_anchor(%d, '%s', '%s')" % (b["batch_id"], w.kind, ref))
        n += 1
    return n


def verify(db, w):
    """Compare the database with the witness. Returns a list of problems (empty = consistent)."""
    problems = []
    ok, msg = w.self_check()
    if not ok:
        problems.append(("witness", msg))
    seen = {}
    for rec in w.records():
        p = rec["payload"]
        seen[(p["course_id"], p["seq_from"], p["seq_to"])] = p["merkle_root"]
    db_batches = {(b["course_id"], b["seq_from"], b["seq_to"]): b for b in batches(db)}
    for (course, lo, hi), wroot in sorted(seen.items()):
        if (course, lo, hi) not in db_batches:
            problems.append(("missing", f"course {course}: witnessed batch seq {lo}-{hi} is absent from the database"))
        # do not trust the stored root: recompute from the revisions themselves
        hashes = [r[0] for r in psql(db, "select row_hash from mark_revisions where course_id=%d and seq between %d and %d order by seq" % (course, lo, hi))]
        if len(hashes) != hi - lo + 1:
            problems.append(("truncated", f"course {course}: witnessed seq {lo}-{hi} but the database holds only {len(hashes)} of {hi-lo+1} revisions"))
        elif merkle.root(hashes) != wroot:
            problems.append(("rewritten", f"course {course}: revisions seq {lo}-{hi} no longer hash to the witnessed Merkle root"))
    return problems


def make_proof(db, course, seq):
    for b in batches(db):
        if b["course_id"] == course and b["seq_from"] <= seq <= b["seq_to"]:
            hashes = [r[0] for r in psql(db, "select row_hash from mark_revisions where course_id=%d and seq between %d and %d order by seq" % (course, b["seq_from"], b["seq_to"]))]
            i = seq - b["seq_from"]
            return {"course_id": course, "seq": seq, "row_hash": hashes[i], "path": merkle.proof(hashes, i)}
    raise LookupError("revision is not in any sealed batch yet")


def check_proof(proof, w):
    """A verifier needs only the proof and the witnessed root, not the database."""
    for rec in w.records():
        p = rec["payload"]
        if p["course_id"] == proof["course_id"] and p["seq_from"] <= proof["seq"] <= p["seq_to"]:
            return merkle.verify(proof["row_hash"], [tuple(x) for x in proof["path"]], p["merkle_root"])
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="veritas")
    ap.add_argument("--witness", default="witness.jsonl", help="file witness path (or the git repo directory with --type git)")
    ap.add_argument("--type", choices=["file", "git"], default="file")
    ap.add_argument("cmd", choices=["anchor", "verify", "proof"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    w = make_witness("git", WITNESS_GIT_DIR=a.witness) if a.type == "git" else FileWitness(a.witness)
    if a.cmd == "anchor":
        print("anchored", anchor(a.db, w), "new batch(es)")
    elif a.cmd == "verify":
        probs = verify(a.db, w)
        for kind, msg in probs:
            print("MISMATCH", kind, "-", msg)
        print("OK: database agrees with the witness" if not probs else f"{len(probs)} problem(s)")
        sys.exit(1 if probs else 0)
    else:
        p = make_proof(a.db, int(a.args[0]), int(a.args[1]))
        print(json.dumps(p), "->", "valid" if check_proof(p, w) else "INVALID")
