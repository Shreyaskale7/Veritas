#!/usr/bin/env python3
"""Builds docs/er_diagram.svg, docs/data_dictionary.md, docs/report.html and docs/Veritas_Report.pdf from the REAL schema
(introspected from a database that has schema.sql + app_bootstrap.sql loaded) and from results/bench_results.md.
Needs PG* environment variables, psql on PATH and Chrome.   Run:  python docs/make_docs.py"""
import html, os, re, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DB = "veritas_docs"


def psql(db, sql=None, file=None, rows=False):
    cmd = ["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-AtF", "\t", "-c", sql] if sql else ["-f", file])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode: raise SystemExit(r.stderr)
    return [l.split("\t") for l in r.stdout.splitlines() if l] if rows else r.stdout


def introspect():
    psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"); psql("postgres", f"CREATE DATABASE {DB}")
    for f in ("schema.sql", "seed.sql", "app_bootstrap.sql"): psql(DB, file=os.path.join(ROOT, f))
    tables = [r[0] for r in psql(DB, "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1", rows=True)]
    cols = {t: [] for t in tables}
    for t, c, ty, nul, d in psql(DB, "select table_name, column_name, data_type, is_nullable, coalesce(column_default,'') from information_schema.columns where table_schema='public' order by table_name, ordinal_position", rows=True):
        if t in cols: cols[t].append((c, ty, nul == "YES", d))
    pk, fk, uq, chk = {}, [], {}, {}
    for t, typ, defn in psql(DB, "select conrelid::regclass::text, contype, pg_get_constraintdef(oid) from pg_constraint where connamespace='public'::regnamespace order by 1", rows=True):
        t = t.replace("public.", "")
        if typ == "p": pk[t] = [c.strip() for c in re.search(r"\((.*)\)", defn).group(1).split(",")]
        elif typ == "f":
            m = re.match(r"FOREIGN KEY \((.*?)\) REFERENCES (\w+)\((.*?)\)", defn)
            fk.append((t, [c.strip() for c in m.group(1).split(",")], m.group(2), [c.strip() for c in m.group(3).split(",")]))
        elif typ == "u": uq.setdefault(t, []).append(defn)
        elif typ == "c": chk.setdefault(t, []).append(defn)
    trig = psql(DB, "select event_object_table, count(*) from information_schema.triggers where trigger_schema='public' group by 1 order by 1", rows=True)
    return tables, cols, pk, fk, uq, chk, {a: int(b) for a, b in trig}


# ------------------------------------------------------------------------------ ER diagram
LAYOUT = {  # table -> (column, row) on a 5 x 4 grid
    "institutions": (0, 0), "users": (1, 0), "students": (2, 0), "faculty": (0, 1), "courses": (1, 1), "assessments": (2, 1),
    "marks": (3, 1), "change_requests": (3, 0), "mark_revisions": (3, 2), "merkle_batches": (2, 2), "anchors": (1, 2),
    "anomaly_alerts": (4, 2), "certificates": (0, 3), "certificate_documents": (1, 3), "notifications": (2, 3),
    "integrity_runs": (3, 3), "login_attempts": (4, 3), "app_credentials": (4, 1),
}
W, ROW_H, HEAD, GAP_X, GAP_Y = 236, 17, 26, 60, 38


def er_svg(tables, cols, pk, fk):
    fkcols = {(t, c) for t, cs, _p, _pc in fk for c in cs}
    shown = {}
    for t in tables:
        pcs = pk.get(t, [])
        pick = [c for c in cols[t] if c[0] in pcs] + [c for c in cols[t] if (t, c[0]) in fkcols and c[0] not in pcs]
        rest = [c for c in cols[t] if c not in pick][:3 if len(pick) < 5 else 1]
        shown[t] = pick + rest + ([("…", "", False, "")] if len(cols[t]) > len(pick) + len(rest) else [])
    colh = {}
    pos = {}
    for t in tables:
        c, r = LAYOUT.get(t, (4, 0))
        colh.setdefault(r, {})
    row_height = {r: max(HEAD + ROW_H * len(shown[t]) for t in tables if LAYOUT.get(t, (4, 0))[1] == r) for r in range(4)}
    ys = {0: 30}
    for r in range(1, 4): ys[r] = ys[r - 1] + row_height[r - 1] + GAP_Y
    for t in tables:
        c, r = LAYOUT.get(t, (4, 0))
        pos[t] = (30 + c * (W + GAP_X), ys[r], W, HEAD + ROW_H * len(shown[t]))
    wtot, htot = 30 * 2 + 5 * W + 4 * GAP_X, ys[3] + row_height[3] + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {wtot} {htot}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11.5">',
           '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#6366f1"/></marker></defs>',
           f'<rect width="{wtot}" height="{htot}" fill="#ffffff"/>']

    def edge(a, b):
        ax, ay, aw, ah = pos[a]; bx, by, bw, bh = pos[b]
        cx1, cy1, cx2, cy2 = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
        def clip(x, y, w, h, tx, ty):
            dx, dy = tx - (x + w / 2), ty - (y + h / 2)
            if dx == 0 and dy == 0: return x + w / 2, y + h / 2
            s = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
            return x + w / 2 + dx * s, y + h / 2 + dy * s
        return clip(ax, ay, aw, ah, cx2, cy2), clip(bx, by, bw, bh, cx1, cy1)
    seen = set()
    for child, cs, parent, _pc in fk:
        if child == parent or (child, parent, tuple(cs)) in seen or child not in pos or parent not in pos: continue
        seen.add((child, parent, tuple(cs)))
        (x1, y1), (x2, y2) = edge(child, parent)
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#6366f1" stroke-width="1.3" marker-end="url(#a)" opacity=".75"/>')
        out.append(f'<text x="{x1 + (x2 - x1) * .12:.0f}" y="{y1 + (y2 - y1) * .12 - 3:.0f}" fill="#444" font-size="10">N</text>')
        out.append(f'<text x="{x1 + (x2 - x1) * .88:.0f}" y="{y1 + (y2 - y1) * .88 - 3:.0f}" fill="#444" font-size="10">1</text>')
    for t in tables:
        x, y, w, h = pos[t]
        hue = "#fdf2f8" if t in ("mark_revisions", "merkle_batches", "anchors") else "#eef2ff" if t in ("marks", "change_requests", "assessments", "courses") else "#f8fafc"
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{hue}" stroke="#94a3b8"/>')
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{HEAD}" rx="6" fill="#1e293b"/><rect x="{x}" y="{y + 12}" width="{w}" height="{HEAD - 12}" fill="#1e293b"/>')
        out.append(f'<text x="{x + 10}" y="{y + 18}" fill="#fff" font-weight="700" font-size="13">{t}</text>')
        for i, (c, ty, nul, _d) in enumerate(shown[t]):
            yy = y + HEAD + ROW_H * i + 13
            tag = "PK" if c in pk.get(t, []) else "FK" if (t, c) in fkcols else ""
            bold = ' font-weight="700"' if tag == "PK" else ""
            out.append(f'<text x="{x + 8}" y="{yy}" fill="#6366f1" font-size="9.5" font-weight="700">{tag}</text>')
            out.append(f'<text x="{x + 30}" y="{yy}" fill="#111"{bold}>{html.escape(c)}</text>')
            out.append(f'<text x="{x + w - 8}" y="{yy}" fill="#64748b" text-anchor="end" font-size="10">{html.escape(ty.replace("timestamp with time zone", "timestamptz").replace("character", "char"))}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ------------------------------------------------------------------------------ charts from the measured benchmarks
def bench():
    txt = open(os.path.join(ROOT, "results", "bench_results.md"), encoding="utf-8").read()
    b1 = []
    for m in re.finditer(r"^\| (\d+) \| (\d+) tps / ([\d.]+) ms \| (\d+) tps / ([\d.]+) ms \| (\d+) tps / ([\d.]+) ms \| ([\d.]+)x \|", txt, re.M):
        b1.append(tuple(float(x) for x in m.groups()))
    b3 = [(int(a.replace(",", "")), int(b)) for a, b in re.findall(r"^\| ([\d,]+) \| (\d+) ms \|", txt, re.M)]
    return b1, b3


def bar_chart(b1):
    w, h, ml, mb = 640, 330, 60, 50
    top = max(max(r[1], r[3], r[5]) for r in b1) * 1.1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12"><rect width="{w}" height="{h}" fill="#fff"/>']
    for i in range(5):
        v = top * i / 4; y = h - mb - (h - mb - 30) * i / 4
        out.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{w - 10}" y2="{y:.0f}" stroke="#e2e8f0"/><text x="{ml - 6}" y="{y + 4:.0f}" text-anchor="end" fill="#64748b">{v:.0f}</text>')
    gw = (w - ml - 20) / len(b1); colors = ["#94a3b8", "#6366f1", "#f43f5e"]
    for gi, row in enumerate(b1):
        for k, (idx, col) in enumerate(zip((1, 3, 5), colors)):
            bh = (h - mb - 30) * row[idx] / top; x = ml + gi * gw + 14 + k * (gw - 28) / 3
            out.append(f'<rect x="{x:.0f}" y="{h - mb - bh:.0f}" width="{(gw - 40) / 3:.0f}" height="{bh:.0f}" fill="{col}" rx="2"/>')
        out.append(f'<text x="{ml + gi * gw + gw / 2:.0f}" y="{h - mb + 18}" text-anchor="middle" fill="#111">{int(row[0])} clients</text>')
    for i, (name, col) in enumerate(zip(("no chain", "chain per course (Veritas)", "one global chain"), colors)):
        out.append(f'<rect x="{ml + i * 190}" y="{h - 22}" width="12" height="12" fill="{col}"/><text x="{ml + i * 190 + 18}" y="{h - 12}" fill="#111">{name}</text>')
    out.append(f'<text x="14" y="18" fill="#111" font-weight="700">Throughput (transactions / s), 10 courses, 2 ms simulated work</text></svg>')
    return "\n".join(out)


def line_chart(b3):
    w, h, ml, mb = 640, 260, 60, 44
    xmax, ymax = max(x for x, _ in b3), max(y for _, y in b3) * 1.15
    pts = [(ml + (w - ml - 30) * x / xmax, h - mb - (h - mb - 30) * y / ymax) for x, y in b3]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12"><rect width="{w}" height="{h}" fill="#fff"/>',
           f'<line x1="{ml}" y1="{h - mb}" x2="{w - 20}" y2="{h - mb}" stroke="#94a3b8"/><line x1="{ml}" y1="30" x2="{ml}" y2="{h - mb}" stroke="#94a3b8"/>',
           '<polyline fill="none" stroke="#6366f1" stroke-width="2.5" points="' + " ".join(f"{x:.0f},{y:.0f}" for x, y in pts) + '"/>']
    for (x, y), (n, ms) in zip(pts, b3):
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4" fill="#6366f1"/><text x="{x:.0f}" y="{y - 10:.0f}" text-anchor="middle" fill="#111">{ms} ms</text>')
        out.append(f'<text x="{x:.0f}" y="{h - mb + 18}" text-anchor="middle" fill="#111">{n:,} rows</text>')
    out.append('<text x="14" y="18" fill="#111" font-weight="700">verify_chain time grows roughly linearly with chain length</text></svg>')
    return "\n".join(out)


# ------------------------------------------------------------------------------ data dictionary + report
def dictionary(tables, cols, pk, fk, uq, chk):
    md = ["# Veritas data dictionary", "", f"_Generated from the live schema ({datetime.date.today():%d %b %Y}); regenerate with `python docs/make_docs.py`._", ""]
    for t in tables:
        md += [f"## {t}", "", "| column | type | null | default | key |", "|---|---|---|---|---|"]
        fks = {c: f"{p}.{pc[0]}" for tt, cs, p, pc in fk if tt == t for c, pc in zip(cs, [pc] * len(cs))} if fk else {}
        for c, ty, nul, d in cols[t]:
            key = "PK" if c in pk.get(t, []) else (f"FK to {fks[c]}" if c in fks else "")
            md.append(f"| {c} | {ty} | {'yes' if nul else 'no'} | {d.replace('|', '/')[:40]} | {key} |")
        for u in uq.get(t, []): md.append(f"\n- unique: `{u}`")
        for c in chk.get(t, []): md.append(f"- check: `{c.replace(chr(10), ' ')[:160]}`")
        md.append("")
    return "\n".join(md)


NORMAL = [
    ("users", "BCNF", "Every attribute depends only on user_id; email is a second candidate key. The role selects a disjoint specialisation (students or faculty), enforced by triggers."),
    ("students, faculty", "BCNF", "Specialisations of users keyed by user_id; usn and employee_id are candidate keys."),
    ("courses", "BCNF", "Candidate keys course_id and (course_code, semester); faculty_id is a plain foreign key."),
    ("assessments", "BCNF", "Weak entity keyed by (course_id, type): max_marks and freeze_at depend on the whole key."),
    ("marks", "BCNF", "Associative entity; candidate keys mark_id and (student_id, course_id, assessment_type); (course_id, assessment_type) references assessments."),
    ("change_requests", "3NF", "All attributes depend on request_id. approved_by and decided_at are filled together (check constraint)."),
    ("mark_revisions", "2NF-3NF with one deliberate redundancy", "course_id is determined by mark_id (marks.course_id), which makes it a transitive dependency. It is kept on purpose as the chain key so each course has its own chain and lock; a trigger rejects any row whose course_id differs from the mark's."),
    ("merkle_batches, anchors", "BCNF", "Keyed by batch_id / anchor_id; (course_id, seq_from) is a candidate key of a batch."),
    ("certificates, certificate_documents", "BCNF", "Only sha256(salt || content digest) is stored, never the content; the document is write-once and keyed by cert_id."),
    ("notifications, integrity_runs, login_attempts, institutions", "BCNF", "Operational tables, each depending only on its surrogate key."),
    ("v_course_result, v_student_sgpa", "(views)", "SGPA is derived by a view and never stored, so it can never disagree with the marks (no update anomaly)."),
]
THREATS = [
    ("Edit a mark's value in mark_revisions", "verify_chain: row_hash no longer matches", "T100, P08"),
    ("Edit a row and re-hash only that row", "Next row's prev_hash no longer matches", "T101"),
    ("Delete a middle revision", "Sequence gap", "T102"),
    ("Re-hash the whole chain after changing history", "old_value continuity check; and the external witness root", "T104, P08"),
    ("Edit marks.current_value directly", "verify_marks_current compares with the ledger", "T105"),
    ("Forge a stored Merkle root", "verify_batches recomputes it", "T106"),
    ("Truncate the tail of the chain", "Marks cross-check and batch check; witness reports the missing batch", "T108, T109, P09"),
    ("Rewrite database AND witness together", "Not detectable: the witness must live outside the DBA's control (git remote)", "P11 (documented negative result)"),
    ("Brute-force a login", "Account locks after 5 failures for 15 minutes", "API A03"),
    ("Cross-site request forgery", "State-changing calls need the per-session CSRF token", "API A04"),
    ("Read another student's marks / documents", "Row-level security returns nothing", "T-series, AX06, AX11, API C03"),
    ("Read or alter another institution's data", "Restrictive RLS policies on every table; mixed-institution rows are refused by triggers", "AX18-AX23, API I04-I10"),
    ("Verifier races an anchor and raises a false alarm", "One lock serialises witness writes and checks", "API W05"),
]
TESTS = [("Ledger suite (SQL)", 84), ("Application-layer suite (SQL, incl. multi-institution isolation)", 25), ("Python cross-checks and attacks", 11), ("Concurrency", 3),
         ("API end-to-end (incl. isolation and race checks)", 32), ("Backup / restore", 6), ("Browser end-to-end (Chrome)", 12)]


def report(tables, cols, pk, fk, trig, svg_er, b1, b3):
    ncols = sum(len(v) for v in cols.values())
    e = html.escape
    rows = lambda items: "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in items)
    rel = []
    for t in tables:
        cs = ", ".join((f"<u>{e(c[0])}</u>" if c[0] in pk.get(t, []) else e(c[0])) for c in cols[t])
        rel.append(f"<li><b>{t}</b>({cs})</li>")
    best = max(b1, key=lambda r: r[0]) if b1 else None
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Veritas: report</title><style>
@page {{ size: A4; margin: 16mm 14mm }}
body {{ font: 10.5pt/1.5 'Inter','Segoe UI',Arial,sans-serif; color: #111; }}
h1 {{ font-size: 24pt; margin: 0 0 4px }} h2 {{ font-size: 15pt; margin: 22px 0 6px; border-bottom: 2px solid #6366f1; padding-bottom: 3px; break-after: avoid }}
h3 {{ font-size: 11.5pt; margin: 14px 0 4px }} table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.2pt; break-inside: auto }}
td, th {{ border: 1px solid #cbd5e1; padding: 4px 7px; vertical-align: top; text-align: left }} th {{ background: #1e293b; color: #fff }}
tr {{ break-inside: avoid }} .sub {{ color: #475569 }} svg {{ width: 100%; height: auto; break-inside: avoid }} code {{ background: #eef2ff; padding: 0 3px; border-radius: 3px }}
.cover {{ padding: 60px 0 30px; border-bottom: 4px solid #6366f1 }} .pill {{ display:inline-block; background:#eef2ff; color:#4338ca; border-radius:99px; padding:1px 9px; font-size:9pt; margin:1px }}
ul.rel {{ columns: 2; font-size: 9pt; padding-left: 16px }} .pb {{ break-before: page }}
</style></head><body>
<div class="cover"><h1>Veritas</h1><div style="font-size:14pt">Tamper-evident marks and certificate ledger on PostgreSQL</div>
<div class="sub" style="margin-top:10px">Database Management Systems (CD252IA), RV College of Engineering &nbsp;|&nbsp; generated {datetime.date.today():%d %B %Y}</div></div>

<h2>1. Problem and approach</h2>
<p>Marks and certificates are changed after the fact, quietly. Veritas makes that detectable and mostly impossible <b>inside the database</b>:
the rules live in triggers, constraints and row-level security, so no application bug, direct SQL session or clever client can skip them. Every mark
write is an append-only, hash-chained revision; revisions are sealed into Merkle batches whose roots are pinned in an external witness;
certificates store only a salted hash and verify publicly with a QR code.</p>
<p><span class="pill">{len(tables)} tables</span><span class="pill">{ncols} columns</span><span class="pill">{sum(trig.values())} triggers</span><span class="pill">row-level security</span><span class="pill">hash chain</span><span class="pill">Merkle tree</span><span class="pill">PostgreSQL 16</span><span class="pill">FastAPI</span><span class="pill">React</span></p>

<h2>2. Entity-relationship diagram</h2>
<p class="sub">Generated from the live schema. Arrows point from the referencing table (N) to the referenced table (1). Pink: the tamper-evidence tables; blue: the marks workflow.</p>
{svg_er}

<h2 class="pb">3. Relational schema</h2>
<ul class="rel">{''.join(rel)}</ul>
<p class="sub">Underlined = primary key. The full data dictionary (types, defaults, constraints) is in <code>docs/data_dictionary.md</code>.</p>

<h2>4. Normalisation</h2>
<table><tr><th>Relation</th><th>Normal form</th><th>Reasoning</th></tr>{rows(NORMAL)}</table>

<h2>5. How the database enforces the rules</h2>
<table><tr><th>Rule</th><th>Mechanism</th></tr>{rows([
 ("Revisions are append-only", "BEFORE UPDATE/DELETE/TRUNCATE trigger raises on mark_revisions, merkle_batches, anchors, certificate_documents"),
 ("seq, prev_hash, row_hash come from the database", "BEFORE INSERT trigger on mark_revisions; a row lock on the course serialises that course's chain only"),
 ("Marks change only through apply_change()", "marks_guard trigger checks a transaction-local flag that only the SECURITY DEFINER function sets"),
 ("Only the course faculty writes marks", "Checked in the chain trigger against courses.faculty_id"),
 ("Frozen assessments need an approved request", "Chain trigger: now() >= freeze_at requires an approved change_request that matches the revision"),
 ("Maker is not the checker", "CHECK approved_by <> requested_by plus can_approve test in the update trigger"),
 ("Each role sees only its own data", "Row-level security policies on users, students, marks, revisions, requests, certificates, alerts, notifications, documents"),
 ("Each institution sees only its own data", "RESTRICTIVE policies (AND-ed with the role policies) on all 12 data tables, using owner-run lookup functions so policies never recurse"),
 ("The app connects with least privilege", "Role veritas_app: SELECT on tables it needs, EXECUTE on the write functions only; verify_*, seal_batch, record_anchor are owner-only"),
 ("Certificates never store content", "Only sha256(salt || sha256(content)) is stored; verification returns valid / revoked / unknown"),
 ("Users are told what concerns them", "AFTER triggers write notifications for requests, decisions, mark changes, alerts and certificates"),
])}</table>

<h2 class="pb">6. Tamper detection and threat model</h2>
<p>Leaf = SHA-256('L' + row_hash); node = SHA-256('N' + left + right); the SQL <code>merkle_root()</code> and the Python <code>merkle.py</code> are cross-checked for equality. Row hashes use a canonical JSON array so free text cannot create ambiguity.</p>
<table><tr><th>Attack</th><th>What catches it</th><th>Test</th></tr>{rows(THREATS)}</table>

<h2>7. Concurrency and performance</h2>
<p>A single global chain would serialise every writer. Veritas chains per course, so writers on different courses never wait for each other (concurrency tests C1-C3 prove same-course writers queue and other-course writers do not).</p>
{bar_chart(b1)}
<p>At {int(best[0]) if best else '?'} clients a per-course chain sustains <b>{int(best[3]) if best else '?'} tps</b> against <b>{int(best[5]) if best else '?'} tps</b> for one global chain, <b>{best[7] if best else '?'}x</b> more.</p>
{line_chart(b3)}
<p class="sub">An index on (course_id, seq) turns the "latest revision of a course" lookup from a 6.4 ms sequential scan into a 0.06 ms index scan.</p>

<h2 class="pb">8. Application features</h2>
<table><tr><th>Area</th><th>What it does</th></tr>{rows([
 ("Marks workflow", "Entry, optimistic version check, freeze, change request, checker approval, apply with request id; CSV bulk import and export"),
 ("Integrity", "Seal Merkle batches, anchor roots to a git-backed witness (push to a remote for real separation), inclusion proofs, scheduled verification, alerts to admins by notification, webhook and e-mail"),
 ("Anomaly detection", "IsolationForest plus rules over revision features; alerts explain why they fired and are triaged by a checker; model version is recorded"),
 ("Certificates", "Issue custom certificates or ledger-built transcripts; PDF with scan-to-verify QR stored write-once; public verifier works from the QR alone"),
 ("Selective disclosure", "A student exports a proof of one revision (fields, Merkle path, witness record); verify_disclosure.py checks it offline without revealing other marks"),
 ("Security", "Login throttling, per-session CSRF token, random session secret, optional HTTPS-only cookies; Caddy gives automatic TLS in the Docker stack"),
 ("Operations", "backup_restore.py backs up only a verified ledger and proves each restore; Docker Compose stack; GitHub Actions CI"),
 ("Multi-institution", "Every user and course belongs to an institution. Restrictive row-level-security policies isolate every table per institution; triggers refuse a course, faculty member or student from different institutions; admin dashboards, directory, sealing, anchoring, transcripts, alerts and notifications are scoped; the scheduler verifies each institution separately"),
])}</table>

<h2>9. Test summary</h2>
<table><tr><th>Suite</th><th>Tests</th></tr>{rows(TESTS)}<tr><td><b>Total</b></td><td><b>{sum(n for _, n in TESTS)}</b></td></tr></table>

<h2>10. Limits and future work</h2>
<ul><li>The witness is only outside the administrator's reach if it is pushed to a remote they do not control; on one machine it is tamper-evident, not tamper-proof. The immudb backend is written but untested.</li>
<li>Revisions made after the last anchor are not yet pinned; the scheduler shortens that window (default 15 minutes).</li>
<li>Single sign-on (OIDC) is not implemented; accounts use bcrypt passwords with throttling.</li>
<li>The Docker stack has not been run in the development environment (no Docker daemon).</li>
<li>The witness (one file or git repo) is shared by all institutions; records carry the institution slug and each admin only verifies their own, but the file itself is common.</li></ul>
</body></html>"""


def main():
    tables, cols, pk, fk, uq, chk, trig = introspect()
    b1, b3 = bench()
    svg = er_svg(tables, cols, pk, fk)
    open(os.path.join(HERE, "er_diagram.svg"), "w", encoding="utf-8").write(svg)
    open(os.path.join(HERE, "data_dictionary.md"), "w", encoding="utf-8").write(dictionary(tables, cols, pk, fk, uq, chk))
    page = report(tables, cols, pk, fk, trig, svg, b1, b3)
    path = os.path.join(HERE, "report.html")
    open(path, "w", encoding="utf-8").write(page)
    chrome = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium") if os.path.exists(p)), None)
    if chrome:
        pdf = os.path.join(HERE, "Veritas_Report.pdf")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", "file:///" + path.replace("\\", "/")], capture_output=True, timeout=120)
        print("wrote", pdf, os.path.getsize(pdf) // 1024, "KB" if os.path.exists(pdf) else "(missing)")
    psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    print("wrote er_diagram.svg, data_dictionary.md, report.html;", len(tables), "tables")


if __name__ == "__main__":
    main()
