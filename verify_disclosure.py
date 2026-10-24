#!/usr/bin/env python3
"""Verify a Veritas disclosure proof offline: no database, no login.

    python verify_disclosure.py proof.json [--witness witness.jsonl]

A proof (GET /api/disclosure/<revision_id>) discloses ONE ledger revision and shows that it is part of a Merkle batch whose
root was pinned by the external witness. Checks, in order:
  1. the revision's fields really hash to its row_hash (same canonical JSON the database trigger hashes)
  2. the row_hash is a leaf under the stated Merkle root (inclusion path)
  3. the witness record covers this revision and carries the same root, and its own hash link is intact
  4. optionally, that exact record appears in a witness file you trust (--witness)
Other students' marks are not revealed: the path contains only sibling hashes.
"""
import argparse
import hashlib
import json
import sys

import merkle


def row_hash(rev: dict) -> str:
    arr = [rev["prev_hash"], rev["seq"], rev["mark_id"], rev["course_id"], rev["old_value"], rev["new_value"],
           rev["changed_by"], rev["reason"], rev["changed_at_utc"]]
    # jsonb::text layout: ", " between items, ": " inside objects, non-ASCII kept as is
    return hashlib.sha256(json.dumps(arr, ensure_ascii=False, separators=(", ", ": ")).encode("utf-8")).hexdigest()


def witness_line_hash(prev: str, payload: dict) -> str:
    return hashlib.sha256((prev + json.dumps(payload, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def verify(proof: dict, witness_path: str | None = None) -> list[str]:
    """Returns the list of problems; empty means the proof holds."""
    bad = []
    rev, mk, wit = proof["revision"], proof["merkle"], proof.get("witness")
    if row_hash(rev) != rev["row_hash"]:
        bad.append("revision fields do not hash to its row_hash (the disclosed data was altered)")
    if mk["row_hash"] != rev["row_hash"]:
        bad.append("Merkle leaf is not this revision's row_hash")
    if not merkle.verify(mk["row_hash"], [tuple(x) for x in mk["path"]], mk["root"]):
        bad.append("inclusion path does not lead to the stated Merkle root")
    if not wit:
        bad.append("no witness record: the batch was sealed but never anchored outside the database")
    else:
        p = wit["payload"]
        if not (p["course_id"] == rev["course_id"] and p["seq_from"] <= rev["seq"] <= p["seq_to"]):
            bad.append("witness record does not cover this revision")
        if p["merkle_root"] != mk["root"]:
            bad.append("witnessed Merkle root differs from the proof's root")
        if witness_line_hash(wit["prev"], p) != wit["line_hash"]:
            bad.append("witness record's own hash link is broken")
        if witness_path:
            with open(witness_path, encoding="utf-8") as f:
                if not any(json.loads(l).get("line_hash") == wit["line_hash"] for l in f if l.strip()):
                    bad.append("this witness record is not in the witness file you supplied")
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proof"); ap.add_argument("--witness")
    a = ap.parse_args()
    problems = verify(json.load(open(a.proof, encoding="utf-8")), a.witness)
    for m in problems:
        print("INVALID -", m)
    if not problems:
        print("VALID: revision is intact, included in the sealed batch, and pinned by the witness")
    sys.exit(1 if problems else 0)
