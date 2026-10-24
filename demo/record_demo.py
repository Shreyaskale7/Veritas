"""Records a captioned walkthrough of Veritas (app must be running: start.ps1) to demo/veritas_demo.webm."""
import os, sys, time
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:5173"
PW = "veritas2026"

CAPTION_JS = """(t) => {
  let el = document.getElementById('__cap');
  if (!el) { el = document.createElement('div'); el.id = '__cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:80%;z-index:99999;'
      + 'background:rgba(15,23,42,.92);color:#fff;font:600 20px system-ui;padding:14px 24px;border-radius:12px;'
      + 'box-shadow:0 8px 30px rgba(0,0,0,.4);text-align:center';
    document.body.appendChild(el); }
  el.textContent = t; }"""


def cap(page, text, secs=3.0):
    page.evaluate(CAPTION_JS, text)
    time.sleep(secs)


def login(page, email):
    page.goto(URL + "/login")
    page.fill("input >> nth=0", email)
    page.fill("input >> nth=1", PW)
    page.get_by_role("button").filter(has_text="Sign").first.click()
    page.wait_for_url("**/marks", timeout=10000)
    time.sleep(1)


def signout(page):
    page.locator("button").first.click()
    page.wait_for_url("**/login")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                              record_video_dir=os.path.join(HERE, "raw"), record_video_size={"width": 1280, "height": 720})
    page = ctx.new_page()

    page.goto(URL + "/login"); time.sleep(1)
    cap(page, "Veritas: a tamper-evident marks & certificate ledger on PostgreSQL", 3.5)
    login(page, "admin@rvce.example")
    cap(page, "Admin view: every mark, enforced by the database, not the app", 3)

    page.goto(URL + "/revisions"); time.sleep(1)
    cap(page, "Every change is a hash-chained, append-only revision", 3.5)

    page.goto(URL + "/integrity"); time.sleep(1)
    cap(page, "Integrity dashboard: chains, marks and Merkle batches all verify", 3.5)
    cap(page, "Merkle roots are anchored to an external witness the DBA cannot rewrite", 3.5)

    page.goto(URL + "/alerts"); time.sleep(1)
    cap(page, "IsolationForest + rules flag suspicious revisions", 2.5)
    page.get_by_text("Run Anomaly Scorer").first.click(); time.sleep(2)
    cap(page, "Scorer run: suspicious edits surface for a checker to review", 3)

    page.goto(URL + "/directory"); time.sleep(1)
    cap(page, "Directory of students and courses", 2.5)
    signout(page)

    login(page, "iyer@rvce.example")
    cap(page, "Faculty view: can only write marks for their own course", 3)
    signout(page)

    login(page, "asha@rvce.example")
    cap(page, "Student view: row-level security shows only their own marks", 3.5)
    page.goto(URL + "/verify"); time.sleep(1)
    cap(page, "Public certificate verifier returns only valid / revoked / unknown", 3.5)

    cap(page, "84 SQL tests, 11 cross-checks and 3 concurrency tests pass", 3.5)
    path = page.video.path()
    ctx.close(); browser.close()

out = os.path.join(HERE, "veritas_demo.webm")
os.replace(path, out)
print("saved", out, os.path.getsize(out) // 1024, "KB")
