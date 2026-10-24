#!/usr/bin/env python3
"""Benchmarks. Rebuilds database veritas_bench. Numbers are from whatever machine runs this."""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = "veritas_bench"
SECS = int(os.environ.get("BENCH_SECS", "8"))


def psql(sql=None, file=None, db=DB, extra=()):
    cmd = ["psql", "-d", db, "-qAtX", "-v", "ON_ERROR_STOP=1", *extra] + (["-c", sql] if sql else ["-f", file])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stderr)
    return r.stdout


def ms(sql):
    out = subprocess.run(["psql", "-d", DB, "-qAtX", "-c", "\\timing on", "-c", sql], capture_output=True, text=True).stdout
    return float(re.findall(r"Time: ([\d.]+) ms", out)[-1])


psql("DROP DATABASE IF EXISTS " + DB, db="postgres"); psql("CREATE DATABASE " + DB, db="postgres")
for f in ("schema.sql", "seed.sql", "bench.sql"):
    psql(file=os.path.join(HERE, f))

ncpu = os.cpu_count()
out = [f"Machine: {ncpu} CPU core(s). Each pgbench transaction = one insert + 2 ms of simulated application work, "
       f"so locks are held realistically. {SECS} s per cell. 10 courses, clients pick a course at random.\n",
       "### B1  Throughput (transactions/s) and average latency (ms)\n",
       "| clients | no chain | chain per course | one global chain | per-course vs global |", "|---|---|---|---|---|"]
for clients in (1, 4, 8, 16):
    cell = {}
    for v in ("plain", "chain_pc", "chain_gl"):
        psql(f"TRUNCATE bench.{v}")
        r = subprocess.run(["pgbench", "-n", "-c", str(clients), "-j", str(min(clients, ncpu)), "-T", str(SECS), "-f", os.path.join(HERE, f"bench_{v}.pgb"), DB],
                           capture_output=True, text=True)
        tps = float(re.search(r"tps = ([\d.]+)", r.stdout).group(1)); lat = float(re.search(r"latency average = ([\d.]+)", r.stdout).group(1))
        cell[v] = (tps, lat)
    f = lambda v: f"{cell[v][0]:.0f} tps / {cell[v][1]:.1f} ms"
    out.append(f"| {clients} | {f('plain')} | {f('chain_pc')} | {f('chain_gl')} | {cell['chain_pc'][0] / cell['chain_gl'][0]:.1f}x |")

# integrity check of what the benchmark wrote (chain_pc must be contiguous per course)
bad = psql("select count(*) from (select course_id, count(*) n, max(seq) m from bench.chain_pc group by 1) x where n <> m")
out += ["", f"Check after the 16-client run: per-course chains with a gap or duplicate = {bad.strip()} (expected 0).", ""]

# B2 single-client trigger overhead (no sleep)
out += ["### B2  Trigger overhead, single client, no simulated work (inserts/s)\n", "| variant | inserts/s |", "|---|---|"]
for v in ("plain", "chain_pc"):
    psql(f"TRUNCATE bench.{v}")
    open("/tmp/_b2.pgb", "w").write(f"\\set c random(1,10)\nINSERT INTO bench.{v} (course_id, mark_id, new_value, changed_by, reason) VALUES (:c, :c, 10, 2, 'bench');\n")
    r = subprocess.run(["pgbench", "-n", "-c", "1", "-T", str(SECS), "-f", "/tmp/_b2.pgb", DB], capture_output=True, text=True)
    tps2 = float(re.search(r"tps = ([\d.]+)", r.stdout).group(1))
    out.append("| %s | %.0f |" % ("no chain" if v == "plain" else "hash-chain trigger", tps2))
os.remove("/tmp/_b2.pgb")

# B3 verification time and index effect, through the real write path (apply_change)
out += ["", "### B3  verify_chain time vs chain length (real schema, rows written through apply_change)\n", "| revisions in course 1 | verify_chain | per 1,000 rows |", "|---|---|---|"]
total = 0
for target in (1000, 5000, 20000):
    need = target - total
    psql("""DO $$ DECLARE i int; m int[]; base int; BEGIN
      SELECT array_agg(mark_id ORDER BY mark_id) INTO m FROM marks WHERE course_id = 1;
      SELECT count(*) INTO base FROM mark_revisions WHERE course_id = 1;
      PERFORM set_config('veritas.user_id','2',true);
      FOR i IN base+1..base+%d LOOP
        PERFORM apply_change(m[1 + (i-1) %% 9], ((i-1) / 9) %% 49 + 1, 'bulk', 2);
      END LOOP; END $$;""" % need)
    total = target
    t = ms("select * from verify_chain(1)")
    out.append(f"| {target:,} | {t:,.0f} ms | {t / target * 1000:.1f} ms |")
ok = psql("select ok from verify_chain(1)").strip()
out += ["", f"verify_chain on the bulk-loaded chain reports ok = {ok}.", "", "### B4  Effect of the (course_id, seq) unique index on the 'latest revision of a course' lookup used by the trigger\n"]
psql("CREATE TABLE bench.noidx AS SELECT * FROM mark_revisions; ANALYZE bench.noidx; ANALYZE mark_revisions;")
q = "SELECT seq, row_hash FROM %s WHERE course_id = 1 ORDER BY seq DESC LIMIT 1"
for label, tbl in (("with index", "mark_revisions"), ("without index (copy of the table)", "bench.noidx")):
    plan = psql("EXPLAIN (ANALYZE, TIMING OFF) " + q % tbl)
    node = [l.strip() for l in plan.splitlines() if "Scan" in l][0].split("  (")[0]
    ex = re.search(r"Execution Time: ([\d.]+)", plan).group(1)
    out.append(f"- {label}: `{node}`, execution {ex} ms")
print("\n".join(out))
