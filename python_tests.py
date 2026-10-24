#!/usr/bin/env python3
"""Cross-checks that the SQL side cannot do about itself: independent hash recomputation,
Merkle agreement, inclusion proofs, and attacks that only the external witness can catch.
Run:  python3 python_tests.py     (needs PG* environment variables; rebuilds databases veritas_py, atk1..atk3)"""
import datetime, hashlib, json, math, os, random, shutil, subprocess, sys, tempfile
import merkle, anchor_service as A

HERE = os.path.dirname(os.path.abspath(__file__))
results = []


def rec(tid, descr, ok, detail=""):
    results.append((tid, bool(ok), descr, detail))


def sh(db, sql=None, file=None, check=True):
    cmd = ["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise RuntimeError(r.stderr)
    return r


def q(db, sql):
    return A.psql(db, sql)


def build(db, template=None):
    sh("postgres", f"DROP DATABASE IF EXISTS {db}")
    if template:
        sh("postgres", f"CREATE DATABASE {db} TEMPLATE {template}")
        return
    sh("postgres", f"CREATE DATABASE {db}")
    for f in ("schema.sql", "seed.sql", "demo_data.sql"):
        sh(db, file=os.path.join(HERE, f))


# ---- independent re-implementation of the row hash -------------------------------------------
def py_row_hash(prev, seq, mark, course, old, new, by, reason, at_us):
    sec, us = divmod(at_us, 1_000_000)
    ts = datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".%06dZ" % us
    arr = [prev, seq, mark, course, old, new, by, reason, ts]
    text = json.dumps(arr, ensure_ascii=False, separators=(", ", ": "))      # same layout as jsonb::text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


build("veritas_py")

# P01 / P02 ------------------------------------------------------------------------------------
rows = q("veritas_py", "select course_id, seq, mark_id, prev_hash, row_hash, coalesce(old_value::text,'~NULL~'), new_value::text, "
                       "changed_by, reason, (extract(epoch from changed_at)*1000000)::bigint from mark_revisions order by course_id, seq")
bad = []
for c, s, m, ph, rh, old, new, by, reason, us in rows:
    old = None if old == "~NULL~" else old
    if py_row_hash(ph, int(s), int(m), int(c), old, new, int(by), reason, int(us)) != rh:
        bad.append((c, s))
rec("P01", f"Python recomputes row_hash for all {len(rows)} revisions identically to the SQL trigger "
           f"(includes a reason containing | \" \\ and non-ASCII)", not bad and len(rows) > 0, str(bad))
rec("P02", "Python genesis hash equals genesis_hash(course) for every course",
    all(hashlib.sha256(f"veritas-genesis:{c}".encode()).hexdigest() == q("veritas_py", f"select genesis_hash({c})")[0][0] for c in (1, 2, 3)))

# P03 -----------------------------------------------------------------------------------------
random.seed(7)
mism = []
for n in list(range(1, 10)) + [16, 17, 33]:
    leaves = [hashlib.sha256(str(random.random()).encode()).hexdigest() for _ in range(n)]
    sql_root = q("veritas_py", "select merkle_root(ARRAY[%s]::text[])" % ",".join("'%s'" % x for x in leaves))[0][0]
    if sql_root != merkle.root(leaves):
        mism.append(n)
rec("P03", "SQL merkle_root() equals the Python implementation for 1-9, 16, 17 and 33 leaves", not mism, str(mism))

# P04 -----------------------------------------------------------------------------------------
bs = A.batches("veritas_py")
ok_all, longest, forged_rejected, n_proofs = True, 0, True, 0
for b in bs:
    hashes = [r[0] for r in q("veritas_py", f"select row_hash from mark_revisions where course_id={b['course_id']} and seq between {b['seq_from']} and {b['seq_to']} order by seq")]
    for i, h in enumerate(hashes):
        p = merkle.proof(hashes, i)
        n_proofs += 1
        longest = max(longest, len(p))
        ok_all &= merkle.verify(h, p, b["merkle_root"]) and len(p) <= math.ceil(math.log2(max(len(hashes), 2)))
        forged_rejected &= not merkle.verify(hashlib.sha256(b"forged").hexdigest(), p, b["merkle_root"])
        if len(hashes) > 1:
            other = hashes[(i + 1) % len(hashes)]
            forged_rejected &= not merkle.verify(other, p, b["merkle_root"])
rec("P04", f"Inclusion proofs: all {n_proofs} leaves of {len(bs)} batches verify against the stored root (longest path {longest}); "
           f"a forged leaf or another leaf's hash is rejected", ok_all and forged_rejected and n_proofs > 0)

# P05 -----------------------------------------------------------------------------------------
tmp = tempfile.mkdtemp()
wpath = os.path.join(tmp, "witness.jsonl")
w = A.FileWitness(wpath)
n1 = A.anchor("veritas_py", w); n2 = A.anchor("veritas_py", w)
anchors_in_db = int(q("veritas_py", "select count(*) from anchors")[0][0])
rec("P05", "Anchoring writes each batch root to the witness once (second run anchors nothing) and records the reference in ANCHORS",
    n1 == len(bs) and n2 == 0 and anchors_in_db == len(bs), f"anchored {n1} then {n2}; anchors rows {anchors_in_db}")
rec("P06", "Clean database agrees with the witness (verify returns no problems)", A.verify("veritas_py", w) == [], str(A.verify("veritas_py", w)))
pr = A.make_proof("veritas_py", 1, 4)
rec("P07", "A single revision can be proven against the witnessed root alone (verifier does not need the database)",
    A.check_proof(pr, w) and not A.check_proof({**pr, "row_hash": "0" * 64}, w))

INTERNAL = "select bool_and(chain_ok and marks_ok and batches_ok) from verify_all_chains()"
TOOLS = os.path.join(HERE, "attacker_tools.sql")

# P08: full rewrite -------------------------------------------------------------------------------
build("atk1", "veritas_py"); sh("atk1", file=TOOLS)
sh("atk1", """SET session_replication_role = replica;
  UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3;
  UPDATE marks SET current_value = 99 WHERE mark_id = (SELECT mark_id FROM mark_revisions WHERE course_id = 1 AND seq = 3);
  SELECT atk.rewrite_chain(1, 3); SELECT atk.rewrite_batches(1);""")
internal = q("atk1", INTERNAL)[0][0]
probs = A.verify("atk1", w)
rec("P08", "Smart attacker (edits a mark, re-hashes the chain, fixes marks and Merkle roots): every database-internal check passes, "
           "but the external witness exposes it", internal == "t" and any(k == "rewritten" for k, _ in probs),
    f"internal checks ok={internal}; witness says: {probs[0][1] if probs else 'nothing'}")

# P09: tail truncation --------------------------------------------------------------------------
build("atk2", "veritas_py")
sh("atk2", """SET session_replication_role = replica;
  DELETE FROM anchors WHERE batch_id IN (SELECT batch_id FROM merkle_batches WHERE course_id = 1 AND seq_from = 11);
  DELETE FROM merkle_batches WHERE course_id = 1 AND seq_from = 11;
  UPDATE marks SET current_value = 70, version = version - 1 WHERE mark_id = (SELECT mark_id FROM mark_revisions WHERE course_id = 1 AND seq = 11);
  UPDATE marks SET current_value = 85, version = version - 1 WHERE mark_id = (SELECT mark_id FROM mark_revisions WHERE course_id = 1 AND seq = 12);
  DELETE FROM mark_revisions WHERE course_id = 1 AND seq IN (11, 12);""")
internal = q("atk2", INTERNAL)[0][0]
probs = A.verify("atk2", w)
rec("P09", "Truncation attack (last revisions, their marks, their batch and anchor row all removed): internal checks pass, witness reports missing batch",
    internal == "t" and any(k == "missing" for k, _ in probs), f"internal ok={internal}; {[m for _, m in probs][:2]}")

# P10: witness file tamper ------------------------------------------------------------------------
w2path = os.path.join(tmp, "witness_tampered.jsonl"); shutil.copy(wpath, w2path)
lines = open(w2path).read().splitlines(); d = json.loads(lines[0]); d["payload"]["merkle_root"] = "f" * 64
lines[0] = json.dumps(d, sort_keys=True); open(w2path, "w").write("\n".join(lines) + "\n")
okw, msg = A.FileWitness(w2path).self_check()
rec("P10", "Editing one line of the witness file breaks its own hash links", not okw, msg)

# P11: attacker also controls the witness ------------------------------------------------------------
build("atk3", "veritas_py"); sh("atk3", file=TOOLS)
sh("atk3", """SET session_replication_role = replica;
  UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3;
  UPDATE marks SET current_value = 99 WHERE mark_id = (SELECT mark_id FROM mark_revisions WHERE course_id = 1 AND seq = 3);
  SELECT atk.rewrite_chain(1, 3); SELECT atk.rewrite_batches(1);""")
w3path = os.path.join(tmp, "witness_forged.jsonl")
fw = A.FileWitness(w3path)
for b in A.batches("atk3"):
    fw.append({k: b[k] for k in ("course_id", "seq_from", "seq_to", "merkle_root")})
rec("P11", "NEGATIVE RESULT (documents the trust assumption): if the attacker can also rewrite the witness, nothing is detected. "
           "The witness must live outside the DBA's control", A.verify("atk3", fw) == [])

for db in ("atk1", "atk2", "atk3"):
    sh("postgres", f"DROP DATABASE IF EXISTS {db}")
shutil.rmtree(tmp)

print("%-5s %-6s %s" % ("ID", "RESULT", "DESCRIPTION"))
for tid, ok, descr, detail in results:
    print("%-5s %-6s %s%s" % (tid, "PASS" if ok else "FAIL", descr, ("\n          -> " + detail) if detail and not ok else ""))
print("\n%d passed, %d failed, %d total" % (sum(r[1] for r in results), sum(not r[1] for r in results), len(results)))
sys.exit(0 if all(r[1] for r in results) else 1)
