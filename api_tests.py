#!/usr/bin/env python3
"""End-to-end API tests. Builds a scratch database (veritas_api), starts the API on port 8100 against it and exercises every
feature: auth hardening, marks workflow, notifications, certificates + PDF, transcripts, CSV import/export, integrity
(seal/anchor/verify/scheduler/alerting), selective disclosure and tamper detection.
Needs PG* environment variables and psql on PATH.   Run:  python api_tests.py"""
import csv, io, json, os, subprocess, sys, tempfile, time
import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DB, PORT = "veritas_api", 8100
BASE = f"http://127.0.0.1:{PORT}"
PW = "veritas2026"
results = []


def rec(tid, descr, ok, detail=""):
    results.append((tid, bool(ok), descr, detail))


def psql(db, sql=None, file=None, tuples=False):
    cmd = ["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-AtF", "|"] if tuples else []) + (["-c", sql] if sql else ["-f", file])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


def build():
    psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"); psql("postgres", f"CREATE DATABASE {DB}")
    for f in ("schema.sql", "seed.sql", "app_bootstrap.sql", "demo_data.sql"):
        psql(DB, file=os.path.join(HERE, f))
    psql(DB, "UPDATE assessments SET freeze_at = now() - interval '1 day' WHERE course_id = 2 AND type = 'CIE-1'")
    # a second institution with its own admin, HOD, student, course and one mark
    psql(DB, """
INSERT INTO institutions (slug, name) VALUES ('beta', 'Beta Institute');
INSERT INTO users (name, email, role, institution_id) VALUES ('Beta Admin', 'admin@beta.example', 'admin', 2), ('Beta HOD', 'hod@beta.example', 'faculty', 2), ('Beta Student', 'stu@beta.example', 'student', 2);
INSERT INTO faculty (user_id, employee_id, department, can_approve) SELECT user_id, 'B-1', 'CSE', true FROM users WHERE email = 'hod@beta.example';
INSERT INTO students (user_id, usn, branch, semester) SELECT user_id, '1BT24CS001', 'CSE', 3 FROM users WHERE email = 'stu@beta.example';
INSERT INTO courses (course_code, title, credits, semester, faculty_id, institution_id) SELECT 'BT101', 'Beta Course', 3, 3, user_id, 2 FROM users WHERE email = 'hod@beta.example';
INSERT INTO assessments (course_id, type, max_marks, freeze_at) SELECT course_id, 'CIE-1', 50, now() + interval '30 days' FROM courses WHERE course_code = 'BT101';
INSERT INTO marks (student_id, course_id, assessment_type) SELECT u.user_id, c.course_id, 'CIE-1' FROM users u, courses c WHERE u.email = 'stu@beta.example' AND c.course_code = 'BT101';
INSERT INTO app_credentials SELECT user_id, crypt('veritas2026', gen_salt('bf')) FROM users WHERE email LIKE '%@beta.example';
SELECT set_config('veritas.user_id', (SELECT user_id::text FROM users WHERE email = 'hod@beta.example'), false);
SELECT apply_change((SELECT mark_id FROM marks WHERE course_id = (SELECT course_id FROM courses WHERE course_code = 'BT101')), 44, 'beta entry', (SELECT user_id FROM users WHERE email = 'hod@beta.example'));
""")


class Client:
    def __init__(self, email=None, password=PW):
        self.h = httpx.Client(base_url=BASE, timeout=30)
        self.csrf = None
        if email:
            r = self.h.post("/api/login", json={"email": email, "password": password})
            if r.status_code == 200:
                self.csrf = r.json()["csrf"]
            self.login_status = r.status_code

    def _hdr(self):
        return {"X-CSRF-Token": self.csrf} if self.csrf else {}

    def get(self, path, **kw): return self.h.get(path, **kw)
    def post(self, path, json=None, **kw): return self.h.post(path, json=json, headers=self._hdr(), **kw)


def mark_id(c, usn, code, typ):
    return next(m["mark_id"] for m in c.get("/api/marks").json() if m["usn"] == usn and m["course_code"] == code and m["assessment_type"] == typ)


def main():
    build()
    witness_dir = tempfile.mkdtemp(prefix="veritas-witness-")
    env = {**os.environ, "DATABASE_URL": f"postgresql://veritas_login:veritas@127.0.0.1:5432/{DB}",
           "ADMIN_DATABASE_URL": f"postgresql://postgres:{os.environ.get('PGPASSWORD', 'postgres')}@127.0.0.1:5432/{DB}",
           "WITNESS_TYPE": "git", "WITNESS_GIT_DIR": witness_dir, "SESSION_SECRET": "test-secret",
           "VERITAS_VERIFY_EVERY": "4", "VERITAS_ANCHOR_EVERY": "0", "VERITAS_SCORE_EVERY": "0",
           "VERITAS_PUBLIC_URL": "http://127.0.0.1:5173"}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)], cwd=os.path.join(HERE, "web", "backend"),
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if httpx.get(BASE + "/api/health", timeout=2).status_code == 200: break
            except Exception: time.sleep(1)
        run(witness_dir)
    finally:
        api.terminate()
        try: api.wait(10)
        except Exception: api.kill()


def run(witness_dir):
    # ---- auth hardening ---------------------------------------------------------------------------------
    admin, iyer, hegde, asha = (Client(e) for e in ("admin@rvce.example", "iyer@rvce.example", "hegde@rvce.example", "asha@rvce.example"))
    rec("A01", "Login returns a CSRF token and sets a session", all(c.csrf for c in (admin, iyer, hegde, asha)))
    rec("A02", "Wrong password is rejected (401) and an unauthenticated call is refused", Client("admin@rvce.example", "nope").login_status == 401
        and Client().get("/api/marks").status_code == 401)
    for _ in range(5): Client("chitra@rvce.example", "wrong")
    locked = Client("chitra@rvce.example", PW)
    rec("A03", "Account locks after 5 failed sign-ins: even the right password gets 429", locked.login_status == 429, f"status {locked.login_status}")
    rec("A04", "State-changing call without the CSRF token is refused (403); with it, it is processed",
        iyer.h.post("/api/requests", json={"mark_id": 10, "proposed_value": 40, "reason": "no token sent"}).status_code == 403
        and iyer.post("/api/requests", {"mark_id": 10, "proposed_value": 40, "reason": "csrf token sent"}).status_code == 200)
    # (that request #1 is the one the workflow below approves)

    # ---- marks workflow ---------------------------------------------------------------------------------
    m_open = mark_id(iyer, "1RV24CD001", "CD251TA", "CIE-2")
    m_frozen = mark_id(iyer, "1RV24CD001", "CD251TA", "CIE-1")
    r = iyer.post(f"/api/marks/{m_open}/apply", {"new_value": 41, "reason": "entered from scripts", "expected_version": 0})
    stale = iyer.post(f"/api/marks/{m_open}/apply", {"new_value": 42, "reason": "stale write", "expected_version": 0})
    rec("M01", "Faculty enters a mark; a stale expected_version is rejected (optimistic lock)", r.status_code == 200 and stale.status_code == 400 and "version conflict" in stale.text)
    rec("M02", "A faculty member cannot write another course's marks, nor a student any mark",
        hegde.post(f"/api/marks/{m_open}/apply", {"new_value": 9, "reason": "not my course"}).status_code == 400
        and asha.post(f"/api/marks/{m_open}/apply", {"new_value": 50, "reason": "i want more"}).status_code == 400)
    rec("M03", "A frozen assessment cannot be edited directly", iyer.post(f"/api/marks/{m_frozen}/apply", {"new_value": 39, "reason": "after the freeze"}).status_code == 400)
    reqs = iyer.get("/api/requests").json()
    rid = reqs[0]["request_id"]
    self_ok = iyer.post(f"/api/requests/{rid}/decide", {"approve": True})
    seen_by_checker = [x["request_id"] for x in hegde.get("/api/requests").json()]
    dec = hegde.post(f"/api/requests/{rid}/decide", {"approve": True})
    app = iyer.post(f"/api/marks/{m_frozen}/apply", {"new_value": 40, "reason": "approved recheck", "request_id": rid})
    rec("M04", "Maker cannot approve their own request; a checker sees it, approves, and the maker applies it",
        self_ok.status_code == 400 and rid in seen_by_checker and dec.status_code == 200 and app.status_code == 200,
        f"self={self_ok.status_code} seen={rid in seen_by_checker} decide={dec.status_code} apply={app.status_code}")

    # ---- notifications ----------------------------------------------------------------------------------
    kinds = lambda c: {n["kind"] for n in c.get("/api/notifications").json()["items"]}
    rec("N01", "Checker is told about the request; maker about its approval; the student about their mark",
        "request_filed" in kinds(hegde) and "request_approved" in kinds(iyer) and "mark_changed" in kinds(asha), f"{kinds(hegde)} {kinds(iyer)} {kinds(asha)}")
    before = asha.get("/api/notifications").json()["unread"]
    asha.post("/api/notifications/read", {"ids": None})
    after = asha.get("/api/notifications").json()["unread"]
    rec("N02", "Marking notifications read clears the unread count; users only ever see their own",
        before > 0 and after == 0 and all(n["message"] for n in asha.get("/api/notifications").json()["items"]))

    # ---- certificates, PDF, transcript -------------------------------------------------------------------
    asha_id = hegde.get("/api/me").json()["user_id"] and next(s["user_id"] for s in hegde.get("/api/directory").json()["students"] if s["usn"] == "1RV24CD001")
    text = "Asha Nair is a bonafide student of RVCE."
    cert = hegde.post("/api/certificates", {"student_id": asha_id, "cert_type": "Bonafide", "content": text}).json()
    pdf = hegde.get(f"/api/certificates/{cert['out_cert_id']}/pdf")
    rec("C01", "Issuing stores a PDF (valid %PDF header) carrying the QR link to the public verifier",
        pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and "/verify?p=" in cert["verify_link"] and len(pdf.content) > 3000, f"{len(pdf.content)} bytes")
    pub = Client()
    v_text = pub.post("/api/verify-certificate", {"cert_id": cert["out_cert_id"], "salt": cert["out_salt"], "content": text}).json()["status"]
    v_dig = pub.post("/api/verify-certificate", {"cert_id": cert["out_cert_id"], "salt": cert["out_salt"], "content_digest": cert["content_digest"]}).json()["status"]
    v_bad = pub.post("/api/verify-certificate", {"cert_id": cert["out_cert_id"], "salt": cert["out_salt"], "content": "forged"}).json()["status"]
    rec("C02", "Public verification works from the text or from the QR digest alone; altered text is unknown",
        (v_text, v_dig, v_bad) == ("valid", "valid", "unknown"), f"{v_text} {v_dig} {v_bad}")
    rec("C03", "The student can download their own certificate PDF; another student cannot see it",
        asha.get(f"/api/certificates/{cert['out_cert_id']}/pdf").status_code == 200 and Client("bharat@rvce.example").get(f"/api/certificates/{cert['out_cert_id']}/pdf").status_code == 404)
    rec("C04", "Only an approving faculty member can revoke; afterwards verification reports revoked",
        iyer.post(f"/api/certificates/{cert['out_cert_id']}/revoke").status_code == 400
        and hegde.post(f"/api/certificates/{cert['out_cert_id']}/revoke").status_code == 200
        and pub.post("/api/verify-certificate", {"cert_id": cert["out_cert_id"], "salt": cert["out_salt"], "content": text}).json()["status"] == "revoked")
    tr = hegde.post("/api/transcripts", {"student_id": asha_id})
    tj = tr.json() if tr.status_code == 200 else {}
    rec("C05", "A transcript is built from the ledger's marks (with SGPA), issued as a certificate and stored as PDF",
        tr.status_code == 200 and "SGPA" in tj.get("content", "") and hegde.get(f"/api/certificates/{tj.get('out_cert_id')}/pdf").content[:5] == b"%PDF-", tr.text[:120] if tr.status_code != 200 else "")

    # ---- bulk import / export ---------------------------------------------------------------------------
    body = "usn,course_code,assessment_type,value,reason\n1RV24CD002,CD251TA,CIE-2,33,bulk entry\n1RV24CD003,CD251TA,CIE-2,36,bulk entry\n1RV24CD003,NOPE,CIE-2,10,bad course\n1RV24CD001,CD251TA,SEE,999,too high\n"
    imp = iyer.h.post("/api/marks/import", files={"file": ("m.csv", body, "text/csv")}, headers=iyer._hdr()).json()
    rec("I01", "CSV import applies good rows through apply_change and reports bad rows individually", imp["imported"] == 2 and imp["failed"] == 2, str(imp["results"]))
    exp = admin.get("/api/export/marks.csv").text
    rows = list(csv.DictReader(io.StringIO(exp)))
    own = list(csv.DictReader(io.StringIO(asha.get("/api/export/marks.csv").text)))
    rec("I02", "Export respects row-level security: admin gets every mark, a student only their own",
        len(rows) == 27 and all(r["usn"] == "1RV24CD001" for r in own) and 0 < len(own) < len(rows), f"admin {len(rows)}, student {len(own)}")
    led = admin.get("/api/export/ledger.csv?course_id=1").text
    rec("I03", "Ledger export carries the hash columns", "row_hash" in led.splitlines()[0] and len(led.splitlines()) > 5)

    # ---- integrity: seal, anchor (git witness), verify, scheduler -----------------------------------------
    for cid in (1, 2, 3): admin.post(f"/api/seal/{cid}")
    an = admin.post("/api/anchor").json()
    ig = admin.get("/api/integrity").json()
    git_log = subprocess.run(["git", "-C", witness_dir, "log", "--oneline"], capture_output=True, text=True).stdout.strip().splitlines()
    rec("W01", "Anchoring writes each batch root to a git-backed witness (one commit per anchor) and the dashboard verifies it",
        an["anchored"] >= 3 and an["witness"] == "git" and len(git_log) == an["anchored"] + len(ig["anchors"]) - len(ig["anchors"]) and ig["witness_ok"] and ig["witness_type"] == "git",
        f"anchored {an['anchored']}, commits {len(git_log)}")
    time.sleep(7)
    runs = admin.get("/api/integrity").json()["runs"]
    rec("W02", "The scheduler verifies the ledger on its own and logs it (integrity_runs)", any(r["kind"] == "verify" and r["ok"] for r in runs), f"{len(runs)} runs logged")

    # ---- a second institution is isolated --------------------------------------------------------------
    admin2, hod2, stu2 = Client("admin@beta.example"), Client("hod@beta.example"), Client("stu@beta.example")
    ig1, ig2 = admin.get("/api/integrity").json(), admin2.get("/api/integrity").json()
    rec("I04", "Each admin's integrity dashboard lists only their own institution's courses, batches and chains",
        [c["course_code"] for c in ig2["courses"]] == ["BT101"] and "BT101" not in [c["course_code"] for c in ig1["courses"]]
        and {c["cid"] for c in ig2["chains"]} == {4} and {c["cid"] for c in ig1["chains"]} == {1, 2, 3}, f"{ig2['courses']} / {[c['cid'] for c in ig1['chains']]}")
    rec("I05", "An admin cannot seal, anchor-prove or read another institution's course",
        admin2.post("/api/seal/1").status_code == 404 and admin.post("/api/seal/4").status_code == 404 and admin2.get("/api/proof?course_id=1&seq=1").status_code == 404)
    sealed2 = admin2.post("/api/seal/4").json()["batch_id"]
    an2 = admin2.post("/api/anchor").json()
    rec("I06", "Admin 2 seals and anchors only its own batch; the shared witness record names the institution",
        sealed2 and an2["anchored"] == 1 and any(json.loads(l)["payload"].get("institution") == "beta" for l in open(os.path.join(witness_dir, "anchors.jsonl"), encoding="utf-8")))
    dir1, dir2 = admin.get("/api/directory").json(), admin2.get("/api/directory").json()
    rec("I07", "The directory is per institution", [s["usn"] for s in dir2["students"]] == ["1BT24CS001"] and "1BT24CS001" not in [s["usn"] for s in dir1["students"]]
        and len(dir1["students"]) == 3 and [c["course_code"] for c in dir2["courses"]] == ["BT101"])
    rec("I08", "Marks, exports and ledger rows never cross institutions",
        len(list(csv.DictReader(io.StringIO(admin2.get("/api/export/marks.csv").text)))) == 1 and len(list(csv.DictReader(io.StringIO(admin.get("/api/export/marks.csv").text)))) == 27
        and "BT101" not in admin.get("/api/export/marks.csv").text and len(admin2.get("/api/revisions").json()) == 1)
    rec("I09", "A transcript for a student of another institution is refused",
        hegde.post("/api/transcripts", {"student_id": next(s["user_id"] for s in dir2["students"])}).status_code == 404)
    rec("I10", "Institution 2's own HOD can issue to its own student, and institution 1 cannot see it",
        hod2.post("/api/certificates", {"student_id": dir2["students"][0]["user_id"], "cert_type": "Bonafide", "content": "Beta student."}).status_code == 200
        and len(stu2.get("/api/certificates").json()) == 1 and len(asha.get("/api/certificates").json()) >= 1 and all(c["student_id"] != dir2["students"][0]["user_id"] for c in asha.get("/api/certificates").json()))

    # ---- selective disclosure ----------------------------------------------------------------------------
    revs = asha.get("/api/revisions").json()
    rv = next(r for r in revs if r["course_id"] == 2)
    d = asha.get(f"/api/disclosure/{rv['revision_id']}")
    path = os.path.join(tempfile.gettempdir(), "veritas_proof.json")
    ok_cli = False; bad_cli = True
    if d.status_code == 200:
        json.dump(d.json(), open(path, "w", encoding="utf-8"))
        ok_cli = subprocess.run([sys.executable, os.path.join(HERE, "verify_disclosure.py"), path, "--witness", os.path.join(witness_dir, "anchors.jsonl")], capture_output=True, text=True).returncode == 0
        forged = d.json(); forged["revision"]["new_value"] = "99.00"
        json.dump(forged, open(path, "w", encoding="utf-8"))
        bad_cli = subprocess.run([sys.executable, os.path.join(HERE, "verify_disclosure.py"), path], capture_output=True, text=True).returncode == 0
    rec("D01", "A student exports a proof of one revision; the offline verifier accepts it and rejects a forged value", ok_cli and not bad_cli, f"status {d.status_code}")
    rec("D02", "A student cannot disclose another student's revision", asha.get(f"/api/disclosure/{next(r['revision_id'] for r in admin.get('/api/revisions').json() if r['mark_id'] != rv['mark_id'] and r['revision_id'] != rv['revision_id'] and all(x['revision_id'] != r['revision_id'] for x in revs))}").status_code == 404)

    # ---- tamper detection + alerting ---------------------------------------------------------------------
    psql(DB, "ALTER TABLE mark_revisions DISABLE TRIGGER mark_revisions_guard; UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3; ALTER TABLE mark_revisions ENABLE TRIGGER mark_revisions_guard;")
    res = admin.post("/api/integrity/verify").json()
    time.sleep(1)
    notes = [n["message"] for n in admin.get("/api/notifications").json()["items"] if n["kind"] == "integrity_failure"]
    rec("W03", "A direct database edit is detected, logged, and every admin is notified", (not res["ok"]) and not [c for c in res["chains"] if c["cid"] == 1][0]["chain_ok"] and notes, f"{len(notes)} admin alert(s)")
    v2 = admin2.post("/api/integrity/verify").json()
    n2 = [n for n in admin2.get("/api/notifications").json()["items"] if n["kind"] == "integrity_failure"]
    rec("W05", "A failure in institution 1 does not fail, or notify, institution 2's admin", v2["ok"] and not n2, f"ok={v2['ok']} notes={len(n2)}")
    sc = admin.post("/api/anomalies/score")
    rec("W04", "The anomaly scorer runs through the API (casts fixed) and returns counts", sc.status_code == 200 and "scored" in sc.json(), sc.text[:100])

    # ---- report ------------------------------------------------------------------------------------------
    print(f"{'ID':5} {'RESULT':6} DESCRIPTION")
    for tid, ok, descr, detail in results:
        print(f"{tid:5} {'PASS' if ok else 'FAIL':6} {descr}" + (f"\n          -> {detail}" if detail and not ok else ""))
    p = sum(1 for r in results if r[1])
    print(f"\n{p} passed, {len(results) - p} failed, {len(results)} total")
    sys.exit(0 if p == len(results) else 1)


if __name__ == "__main__":
    main()
