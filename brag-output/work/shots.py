import base64, os, sys
from playwright.sync_api import sync_playwright
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots"); os.makedirs(OUT, exist_ok=True)
URL = "http://127.0.0.1:5173"
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    ctx = br.new_context(viewport={"width": 1500, "height": 900})
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("http://127.0.0.1", "data:", "blob:")) else r.abort())
    page = ctx.new_page(); page.set_default_timeout(30000)
    cdp = ctx.new_cdp_session(page)
    def shot(name):
        page.wait_for_timeout(900)
        open(os.path.join(OUT, name + ".png"), "wb").write(base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "png"})["data"]))
    def login(email):
        page.goto(URL + "/login"); page.fill("#email", email); page.fill("#password", "veritas2026"); page.click("#login-btn")
        page.wait_for_url("**/marks"); page.wait_for_selector("tbody tr, .card")
    def signout():
        page.locator("button").first.click(); page.wait_for_url("**/login"); page.wait_for_timeout(1500); page.wait_for_selector("#email")
    login("admin@rvce.example")
    page.get_by_role("link", name="Integrity").click(); page.wait_for_selector("#verify-now-btn"); page.mouse.wheel(0, 700); shot("integrity_runs")
    page.get_by_role("link", name="Ledger").click(); page.wait_for_selector("text=Verified intact"); shot("ledger")
    page.get_by_role("link", name="Notifications").click(); page.wait_for_selector("text=Notifications"); shot("notifications_admin")
    signout(); login("hegde@rvce.example")
    page.get_by_role("link", name="Anomaly Alerts").click(); page.wait_for_selector("#run-scorer-btn"); shot("alerts")
    page.get_by_role("link", name="Certificates").click(); page.wait_for_selector("#issue-cert-btn"); page.click("#issue-cert-btn")
    page.select_option("#cert-mode", "transcript"); shot("issue_transcript")
    page.get_by_role("button", name="Cancel").click()
    shot("certificates")
    signout(); login("iyer@rvce.example"); page.wait_for_selector("#import-btn"); shot("marks_faculty")
    signout(); login("asha@rvce.example")
    page.get_by_role("link", name="Audit Trail").click(); page.wait_for_selector("text=Share proof"); shot("audit_trail")
    signout()
    page.goto(URL + "/verify"); page.wait_for_selector("#verify-btn"); shot("public_verify")
    br.close()
print(sorted(os.listdir(OUT)))
