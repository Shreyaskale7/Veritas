#!/usr/bin/env python3
"""Accessibility and phone-layout test. Isolated like e2e_test.py: scratch database veritas_a11y, its own API (:8300) and its own
frontend build (:4373). Every screen of every role is scanned with the axe engine (WCAG 2.0/2.1 A and AA) at a desktop and a phone
size, and checked for horizontal page scroll. Dialogs, the slide-out menu and the forced password screen get behaviour checks.
Needs PG* variables, psql, Chrome, npm, `pip install playwright axe-playwright-python httpx`.   Run:  python a11y_test.py"""
import os, shutil, subprocess, sys, time
import httpx
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(HERE, "web", "frontend")
DB, API, WEB = "veritas_a11y", "http://127.0.0.1:8300", "http://127.0.0.1:4373"
PW = "veritas2026"
SIZES = {"desktop": {"width": 1280, "height": 800}, "phone": {"width": 390, "height": 844}}
PAGES = {
    "admin@rvce.example": ["/marks", "/integrity", "/requests", "/alerts", "/directory", "/people", "/manage-courses", "/admin-log", "/certificates", "/revisions", "/notifications", "/account"],
    "iyer@rvce.example": ["/marks", "/requests", "/certificates", "/notifications", "/account"],
    "hegde@rvce.example": ["/marks", "/requests", "/alerts", "/certificates"],
    "asha@rvce.example": ["/marks", "/sgpa", "/certificates", "/revisions", "/notifications", "/account"],
}
problems, checks = [], []


def psql(db, sql=None, file=None):
    r = subprocess.run(["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file]), capture_output=True, text=True, encoding="utf-8")
    if r.returncode: raise RuntimeError(r.stderr)


def wait_http(url, tries=60):
    for _ in range(tries):
        try:
            if httpx.get(url, timeout=2).status_code < 500: return True
        except Exception: time.sleep(1)
    return False


def check(name, ok, detail=""):
    checks.append((name, ok))
    if not ok: problems.append(f"{name}: {detail}")
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail and not ok else ""), flush=True)


COMBOS, OTHERS = {}, {}      # failing colour pairs and other failing targets, aggregated over every scan (for the final report)


def scan(page, label):
    """axe on the current page (WCAG A/AA); returns (violations)."""
    res = Axe().run(page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}})
    out = []
    for v in res.response["violations"]:
        nodes = v["nodes"]
        for n in nodes:
            if v["id"] == "color-contrast":
                d = (n.get("any") or [{}])[0].get("data") or {}
                k = (d.get("fgColor"), d.get("bgColor"), d.get("contrastRatio"), d.get("fontSize"))
                COMBOS.setdefault(k, [0, n["target"][0]])[0] += 1
            else:
                OTHERS.setdefault((v["id"], n["target"][0]), 0); OTHERS[(v["id"], n["target"][0])] += 1
        out.append(f"{v['id']} ({v['impact']}) x{len(nodes)}: {nodes[0]['target'][0] if nodes else ''}  -- {v['help']}")
    check(f"axe  {label}", not out, " | ".join(out[:4]))
    return out


def main():
    psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"); psql("postgres", f"CREATE DATABASE {DB}")
    for f in ("schema.sql", "seed.sql", "app_bootstrap.sql", "demo_data.sql"): psql(DB, file=os.path.join(HERE, f))
    out = os.path.join(FRONT, "dist-a11y")
    subprocess.run("npm run build -- --outDir dist-a11y --emptyOutDir", cwd=FRONT, shell=True, check=True, capture_output=True, env={**os.environ, "VITE_API_BASE": API})
    env = {**os.environ, "DATABASE_URL": f"postgresql://veritas_login:veritas@127.0.0.1:5432/{DB}",
           "ADMIN_DATABASE_URL": f"postgresql://postgres:{os.environ.get('PGPASSWORD', 'postgres')}@127.0.0.1:5432/{DB}",
           "VERITAS_SCHEDULER": "0", "SESSION_SECRET": "a11y", "CORS_ORIGINS": WEB,
           "WITNESS_PATH": os.path.join(HERE, "web", "frontend", "dist-a11y", "witness.jsonl")}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", "8300"], cwd=os.path.join(HERE, "web", "backend"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen("npx vite preview --outDir dist-a11y --port 4373 --host 127.0.0.1 --strictPort", cwd=FRONT, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_http(API + "/api/health") and wait_http(WEB), "servers did not start"
        run()
    finally:
        api.terminate()
        if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(web.pid)], capture_output=True)
        else: web.terminate()
        shutil.rmtree(out, ignore_errors=True)
        psql("postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    if os.environ.get("A11Y_DEBUG"):
        print("FAILING COLOUR PAIRS (fg, bg, ratio, size) -> count, sample:")
        for k, (n, t) in sorted(COMBOS.items(), key=lambda kv: -kv[1][0])[:40]: print("  ", k, n, t)
        print("OTHER FAILURES:")
        for (rule, t), n in sorted(OTHERS.items(), key=lambda kv: -kv[1])[:40]: print("  ", rule, t, n)
    print(f"\n{sum(1 for _, ok in checks if ok)} passed, {len(problems)} failed, {len(checks)} total")
    for p in problems: print("  -", p)
    sys.exit(0 if not problems else 1)


def run():
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="chrome", headless=True)

        def new_ctx(size):
            ctx = br.new_context(viewport=SIZES[size])
            ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("http://127.0.0.1", "data:", "blob:")) else r.abort())
            page = ctx.new_page(); page.set_default_timeout(30000)
            return ctx, page

        def login(page, email, password=PW):
            page.goto(WEB + "/login"); page.fill("#email", email); page.fill("#password", password); page.click("#login-btn")
            page.wait_for_selector("#main, #force-h")

        def settle(page):
            page.wait_for_selector("#main"); page.wait_for_load_state("load"); page.wait_for_timeout(900)

        # --- public pages -----------------------------------------------------------------------------------
        for size in SIZES:
            ctx, page = new_ctx(size)
            for path in ("/login", "/verify"):
                page.goto(WEB + path); page.wait_for_selector("input"); page.wait_for_timeout(600)
                scan(page, f"public {path} [{size}]")
                over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                check(f"fit  public {path} [{size}]", over <= 1, f"{over}px wider than the screen")
            ctx.close()

        # --- every role, every screen, both sizes ------------------------------------------------------------
        for size in SIZES:
            for email, paths in PAGES.items():
                ctx, page = new_ctx(size)
                login(page, email); settle(page)
                for path in paths:
                    page.goto(WEB + path); settle(page)
                    scan(page, f"{email.split('@')[0]} {path} [{size}]")
                    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    check(f"fit  {email.split('@')[0]} {path} [{size}]", over <= 1, f"{over}px wider than the screen")
                ctx.close()

        # --- dialogs: role, focus in, Tab trap, Escape, focus back ---------------------------------------------
        for size in SIZES:
            ctx, page = new_ctx(size)
            login(page, "admin@rvce.example"); page.goto(WEB + "/people"); settle(page)
            opener = page.locator("#add-person-btn"); opener.click()
            page.wait_for_selector("[role=dialog]")
            check(f"dialog has role, name and traps focus [{size}]", page.evaluate(
                "(()=>{const d=document.querySelector('[role=dialog]');return d.getAttribute('aria-modal')==='true'&&!!d.getAttribute('aria-labelledby')&&d.contains(document.activeElement)})()"))
            for _ in range(25): page.keyboard.press("Tab")
            check(f"Tab never leaves the dialog [{size}]", page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)"))
            scan(page, f"dialog Add person [{size}]")
            page.keyboard.press("Escape"); page.wait_for_timeout(400)
            check(f"Escape closes the dialog and focus returns to its button [{size}]",
                  page.locator("[role=dialog]").count() == 0 and page.evaluate("document.activeElement && document.activeElement.id") == "add-person-btn")
            ctx.close()

        # --- phone navigation ---------------------------------------------------------------------------------
        ctx, page = new_ctx("phone")
        login(page, "admin@rvce.example"); settle(page)
        menu = page.locator(".menu-btn")
        hidden = page.evaluate("(()=>{const r=document.querySelector('.sidebar').getBoundingClientRect();return r.right<=0})()")
        check("phone: menu is closed at first and the menu button is visible", hidden and menu.is_visible())
        menu.click(); page.wait_for_timeout(350)
        check("phone: the button opens the navigation (aria-expanded true, links reachable)",
              menu.get_attribute("aria-expanded") == "true" and page.get_by_role("link", name="People").is_visible())
        page.keyboard.press("Escape"); page.wait_for_timeout(350)
        check("phone: Escape closes the navigation", page.evaluate("document.querySelector('.sidebar').getBoundingClientRect().right <= 0"))
        menu.click(); page.wait_for_timeout(300); page.get_by_role("link", name="People").click(); page.wait_for_url("**/people"); page.wait_for_timeout(500)
        check("phone: choosing a link navigates and closes the menu", page.evaluate("document.querySelector('.sidebar').getBoundingClientRect().right <= 0"))
        ctx.close()

        # --- skip link ------------------------------------------------------------------------------------------
        ctx, page = new_ctx("desktop")
        login(page, "asha@rvce.example"); settle(page)
        page.keyboard.press("Tab")
        check("the first Tab stop is the 'Skip to content' link", page.evaluate("document.activeElement.className") == "skip-link")
        ctx.close()

        # --- forced password change screen ---------------------------------------------------------------------
        h = httpx.Client(base_url=API)
        tok = h.post("/api/login", json={"email": "admin@rvce.example", "password": PW}).json()["csrf"]
        h.post("/api/admin/people", json={"name": "Temp User", "email": "temp.user@rvce.example", "role": "student", "password": "Temporary-Pass1", "usn": "1RV24CD077", "branch": "CSE", "semester": 5},
               headers={"X-CSRF-Token": tok})
        for size in SIZES:
            ctx, page = new_ctx(size)
            login(page, "temp.user@rvce.example", "Temporary-Pass1"); page.wait_for_selector("#force-h")
            scan(page, f"forced password change [{size}]")
            over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            check(f"fit  forced password change [{size}]", over <= 1, f"{over}px")
            ctx.close()
        br.close()


if __name__ == "__main__":
    main()
