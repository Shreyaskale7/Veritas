#!/usr/bin/env python3
"""Browser end-to-end test (Chrome via Playwright). Fully isolated from the live stack:
scratch database veritas_e2e, its own API on :8200, and its own frontend build (VITE_API_BASE=:8200) served on :4273.
Needs PG* environment variables, psql on PATH, Chrome, npm.   Run:  python e2e_test.py"""
import json, os, shutil, subprocess, sys, tempfile, time
import httpx
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(HERE, "web", "frontend")
DB, API, WEB = "veritas_e2e", "http://127.0.0.1:8200", "http://127.0.0.1:4273"
PW = "veritas2026"
results = []


def rec(tid, descr, ok, detail=""):
    results.append((tid, bool(ok), descr, detail))
    print(f"{tid:5} {'PASS' if ok else 'FAIL':5} {descr}" + (f"  -> {detail}" if detail and not ok else ""), flush=True)


def psql(db, sql=None, file=None):
    cmd = ["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode: raise RuntimeError(r.stderr)


def wait_http(url, tries=60):
    for _ in range(tries):
        try:
            if httpx.get(url, timeout=2).status_code < 500: return True
        except Exception: time.sleep(1)
    return False


def main():
    psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"); psql("postgres", f"CREATE DATABASE {DB}")
    for f in ("schema.sql", "seed.sql", "app_bootstrap.sql", "demo_data.sql"): psql(DB, file=os.path.join(HERE, f))
    psql(DB, "UPDATE assessments SET freeze_at = now() - interval '1 day' WHERE course_id = 2 AND type = 'CIE-1'")
    out = os.path.join(FRONT, "dist-e2e")
    subprocess.run("npm run build -- --outDir dist-e2e --emptyOutDir", cwd=FRONT, shell=True, check=True, capture_output=True,
                   env={**os.environ, "VITE_API_BASE": API})
    wit = tempfile.mkdtemp(prefix="veritas-e2e-witness-")
    env = {**os.environ, "DATABASE_URL": f"postgresql://veritas_login:veritas@127.0.0.1:5432/{DB}",
           "ADMIN_DATABASE_URL": f"postgresql://postgres:{os.environ.get('PGPASSWORD', 'postgres')}@127.0.0.1:5432/{DB}",
           "WITNESS_TYPE": "git", "WITNESS_GIT_DIR": wit, "VERITAS_SCHEDULER": "0", "SESSION_SECRET": "e2e",
           "CORS_ORIGINS": WEB, "VERITAS_PUBLIC_URL": WEB}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", "8200"], cwd=os.path.join(HERE, "web", "backend"),
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen("npx vite preview --outDir dist-e2e --port 4273 --host 127.0.0.1 --strictPort", cwd=FRONT, shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_http(API + "/api/health") and wait_http(WEB), "servers did not start"
        run(wit)
    finally:
        api.terminate()
        if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(web.pid)], capture_output=True)
        else: web.terminate()
        shutil.rmtree(out, ignore_errors=True)
    p = sum(1 for r in results if r[1])
    print(f"\n{p} passed, {len(results) - p} failed, {len(results)} total")
    sys.exit(0 if p == len(results) else 1)


def run(wit):
    try:
        _run(wit)
    except Exception:
        try:
            PAGE.screenshot(path=os.path.join(HERE, 'e2e_fail.png')); print('console:', LOGS[-12:], 'url:', PAGE.url)
        except Exception: pass
        print('FAILED; see e2e_fail.png'); raise


def _run(wit):
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="chrome", headless=True)
        ctx = br.new_context(viewport={"width": 1600, "height": 950}, accept_downloads=True)
        # hermetic: the app @imports Google Fonts; a slow external network must not stall the test (fonts fall back to system ones)
        ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(("http://127.0.0.1", "http://localhost", "data:", "blob:")) else route.abort())
        page = ctx.new_page(); page.set_default_timeout(30000)
        page.on("dialog", lambda d: d.accept())
        logs = []
        globals()['PAGE'], globals()['LOGS'] = page, logs
        page.on("console", lambda m: logs.append(m.type + ": " + m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: logs.append("pageerror: " + str(e)[:300]))
        page.on("response", lambda r: logs.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        page.on("requestfailed", lambda r: logs.append("requestfailed: " + r.url + " " + str(r.failure)))

        def dump():
            import base64                       # raw DevTools capture: page.screenshot() waits for web fonts, which we block here
            try:
                data = ctx.new_cdp_session(page).send("Page.captureScreenshot", {"format": "png"})["data"]
                open(os.path.join(HERE, 'e2e_fail.png'), "wb").write(base64.b64decode(data))
            except Exception as e:
                print("screenshot failed:", e)
            print('console:', logs[-12:], 'url:', page.url)
            try: print('visible text:', ' | '.join(page.locator('body').inner_text(timeout=3000)[:400].splitlines()))
            except Exception: pass
        def login(email):
            try:
                page.goto(WEB + "/login"); page.fill("#email", email); page.fill("#password", PW)
                page.click("#login-btn")
                page.wait_for_url("**/marks"); page.wait_for_selector("tbody tr, .card")
            except Exception:
                print("login failed for", email); dump(); raise
        def signout():
            page.locator("button").first.click(); page.wait_for_url("**/login"); page.wait_for_timeout(1200); page.wait_for_load_state("load"); page.wait_for_selector("#email")   # the app reloads itself after sign-out: let it finish
        def toast(text):
            try:
                page.locator(".toast", has_text=text).first.wait_for()
            except Exception:
                print("expected toast:", text, "| toasts on screen:", page.locator(".toast").all_inner_texts()); dump(); raise
        def row(*t):
            r = page.locator("tbody tr")
            for x in t: r = r.filter(has_text=x)
            return r.first

        try:
            # --- faculty: enter a mark, then bulk import ------------------------------------------------------
            login("iyer@rvce.example")
            page.get_by_placeholder("Filter").fill("Asha")
            row("CD251TA", "CIE-2").get_by_role("button", name="Edit").click()
            page.fill("#apply-value", "41"); page.fill("#apply-reason", "entered from answer scripts"); page.click("#apply-submit")
            toast("Mark updated"); rec("U01", "Faculty enters a mark through the UI (toast confirms the ledger write)", True)
            csv_path = os.path.join(tempfile.gettempdir(), "veritas_import.csv")
            open(csv_path, "w").write("usn,course_code,assessment_type,value,reason\n1RV24CD002,CD251TA,CIE-2,33,bulk entry\n1RV24CD003,CD251TA,CIE-2,36,bulk entry\n1RV24CD003,NOPE,CIE-2,1,bad course\n")
            page.get_by_placeholder("Filter").fill("")
            page.locator("#import-btn input[type=file]").set_input_files(csv_path)
            toast("Imported 2 mark(s)"); rec("U02", "CSV import: 2 rows applied, the bad row reported", page.locator(".toast", has_text="1 row(s) failed").count() > 0)
            with page.expect_download() as dl:
                page.click("#export-btn")
            rec("U03", "Marks export downloads a CSV", dl.value.suggested_filename == "marks.csv")

            # --- frozen mark: request -> checker approves -> apply with request id ------------------------------
            page.get_by_placeholder("Filter").fill("Asha")
            row("CD251TA", "CIE-1").get_by_role("button", name="Request").click()
            page.fill("#req-value", "38"); page.fill("#req-reason", "re-evaluation after paper recheck"); page.click("#req-submit")
            toast("Change request submitted"); signout()
            login("hegde@rvce.example")
            page.get_by_role("link", name="Notifications").click()
            page.locator(".card", has_text="awaits a decision").first.wait_for()
            rec("U04", "The checker's notification page shows the new change request", True)
            page.get_by_role("link", name="Approve Requests").click(); page.locator("[id^=approve-]").first.click(); toast("pproved")
            rec("U05", "Checker sees the request in the UI (row-level-security fix) and approves it", True)
            signout(); login("iyer@rvce.example")
            page.get_by_placeholder("Filter").fill("Asha")
            row("CD251TA", "CIE-1").get_by_role("button", name="Apply").click()
            page.fill("#apply-value", "38"); page.fill("#apply-reason", "approved recheck"); page.fill("#apply-reqid", "1"); page.click("#apply-submit")
            toast("Mark updated"); rec("U06", "The maker applies the approved request from the UI", True)
            signout()

            # --- certificates: transcript with PDF, then public scan-to-verify -------------------------------
            login("hegde@rvce.example")
            page.get_by_role("link", name="Certificates").click(); page.click("#issue-cert-btn")
            page.select_option("#cert-mode", "transcript"); page.select_option("#cert-student", label="Asha Nair (1RV24CD001)")
            page.click("#cert-submit"); toast("PDF with QR stored")
            page.locator(".cert-card").first.click()
            page.get_by_role("button", name="View PDF").wait_for()
            rec("U07", "A transcript is issued from the ledger and its PDF is available in the certificate dialog", True)
            page.get_by_role("button", name="Close").click(); signout()
            # a public visitor scans the QR link (made through the API so we can read the link)
            h = httpx.Client(base_url=API); r = h.post("/api/login", json={"email": "hegde@rvce.example", "password": PW}); tok = r.json()["csrf"]
            sid = next(s["user_id"] for s in h.get("/api/directory").json()["students"] if s["usn"] == "1RV24CD002")
            link = h.post("/api/certificates", json={"student_id": sid, "cert_type": "NOC", "content": "No objection."}, headers={"X-CSRF-Token": tok}).json()["verify_link"]
            pub = ctx.new_page(); pub.goto(link); pub.get_by_text("Certificate is VALID").wait_for()
            pub.close(); page.bring_to_front()   # a lingering second tab would leave the main one in the background, where Chrome pauses animation frames
            rec("U08", "Scanning the QR link as a logged-out visitor verifies the certificate automatically", True)

            # --- admin: integrity ------------------------------------------------------------------------------
            login("admin@rvce.example")
            page.get_by_role("link", name="Integrity").click()
            for cid in (1, 2, 3): page.click(f"#seal-{cid}")
            page.click("#anchor-btn"); toast("Anchored")
            page.click("#verify-now-btn"); toast("Verified")
            page.get_by_text("Witness intact (git)").wait_for()
            rec("U09", "Admin seals, anchors to the git witness and verifies; the dashboard shows the run log", page.locator("td", has_text="verify").count() > 0)
            page.get_by_role("link", name="Ledger").click(); page.get_by_text("Verified intact").first.wait_for()
            rec("U10", "The Ledger's 'Verified intact' badge comes from a real verification", True)
            signout()

            # --- student: share a proof and verify it offline ---------------------------------------------------
            login("asha@rvce.example")
            page.get_by_role("link", name="Audit Trail").click()
            with page.expect_download() as dl2:
                page.get_by_role("button", name="Share proof").first.click()
            proof = os.path.join(tempfile.gettempdir(), "veritas_ui_proof.json"); dl2.value.save_as(proof)
            v = subprocess.run([sys.executable, os.path.join(HERE, "verify_disclosure.py"), proof, "--witness", os.path.join(wit, "anchors.jsonl")], capture_output=True, text=True)
            rec("U11", "A student downloads a proof of one revision and the offline verifier accepts it", v.returncode == 0, v.stdout + v.stderr)
            page.get_by_role("link", name="Notifications").click(); page.locator("#read-all-btn").click()
            page.wait_for_function("document.querySelector('#unread-badge') === null")
            rec("U12", "Notification badge clears after 'mark all read'", True)
        except Exception:
            dump(); raise
        br.close()


if __name__ == "__main__":
    main()
