"""Records the full Veritas walkthrough (live app, real clicks) to work/full_raw.webm. Run reset_demo.ps1 first."""
import os, sys, time, shutil, subprocess, tempfile
import httpx
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:5173"
PW = "veritas2026"
HERE_ROOT = os.path.dirname(os.path.dirname(HERE))
WITNESS_FILE = os.path.join(HERE, "demo_witness.jsonl")
IMPORT_CSV = os.path.join(tempfile.gettempdir(), "veritas_class_marks.csv")


def proof_card(output):
    lines = "".join('<div class="l mono" style="font-size:30px;margin:12px 0">%s</div>' % o for o in output.splitlines())
    return CARD_CSS + """<div class="c mid a" style="top:90px">A student proves one mark, offline</div>
      <div class="a" style="position:absolute;left:230px;right:230px;top:240px;background:#0b0f1c;border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:44px 54px;animation-delay:.4s">
        <div class="mono" style="font-size:28px;color:#8892b0;margin-bottom:22px">$ python verify_disclosure.py proof.json --witness witness.jsonl</div>
        <div class="mono" style="font-size:34px;color:#10b981;font-weight:700;line-height:1.5">""" + lines + """</div></div>
      <div class="c sub a" style="top:690px;animation-delay:1.2s">No database, no login. Only that revision is revealed, nothing about any other mark.</div>"""

INIT = """(()=>{const mk=()=>{ if(document.getElementById('__cap')||!document.body) return;
 const s=document.createElement('style'); s.textContent=`
 #__cap{position:fixed;left:50%;bottom:44px;transform:translateX(-50%) translateY(20px);z-index:99998;background:rgba(7,11,20,.95);color:#f0f4ff;
  font:700 38px Inter,system-ui,sans-serif;padding:20px 38px;border-radius:20px;border:1px solid rgba(99,102,241,.6);
  box-shadow:0 20px 70px rgba(0,0,0,.65),0 0 50px rgba(99,102,241,.25);white-space:nowrap;opacity:0;transition:opacity .35s,transform .35s;pointer-events:none}
 #__cap.on{opacity:1;transform:translateX(-50%) translateY(0)}
 #__cur{position:fixed;left:960px;top:540px;width:30px;height:30px;z-index:99999;pointer-events:none;transition:left .22s cubic-bezier(.4,0,.2,1),top .22s cubic-bezier(.4,0,.2,1)}
 #__cur svg{filter:drop-shadow(0 2px 4px rgba(0,0,0,.7))}
 #__cur i{position:absolute;left:-14px;top:-14px;width:30px;height:30px;border-radius:50%;border:3px solid #6366f1;opacity:0}
 #__cur.rip i{animation:rp .45s ease-out}
 @keyframes rp{0%{opacity:.9;transform:scale(.3)}100%{opacity:0;transform:scale(1.6)}}`;
 document.head.appendChild(s);
 const c=document.createElement('div'); c.id='__cap'; document.body.appendChild(c);
 const k=document.createElement('div'); k.id='__cur';
 k.innerHTML='<i></i><svg width="30" height="30" viewBox="0 0 24 24"><path d="M3 2l7 18 2.6-7.4L20 10z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>'; document.body.appendChild(k);
 try{ const t=sessionStorage.getItem('__cap'); if(t){c.textContent=t;c.classList.add('on')}
  const p=sessionStorage.getItem('__cur'); if(p){const [x,y]=p.split(',');k.style.left=x+'px';k.style.top=y+'px'} }catch(e){} };
 if(document.body) mk(); else document.addEventListener('DOMContentLoaded',mk);})()"""

SETCAP = """t=>{const c=document.getElementById('__cap'); if(!c) return; c.textContent=t; c.classList.toggle('on',!!t);
 try{sessionStorage.setItem('__cap',t)}catch(e){}}"""
MOVE = """([x,y])=>{const k=document.getElementById('__cur'); if(!k) return; k.style.left=x+'px'; k.style.top=y+'px';
 try{sessionStorage.setItem('__cur',x+','+y)}catch(e){}}"""
RIP = "()=>{const k=document.getElementById('__cur'); if(!k) return; k.classList.remove('rip'); void k.offsetWidth; k.classList.add('rip')}"

CARD_CSS = """<meta charset=utf-8><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@500&display=swap" rel=stylesheet>
<style>:root{--bg:#070b14;--t1:#f0f4ff;--t2:#8892b0;--acc:#6366f1;--ok:#10b981;--bad:#f43f5e;--warn:#f59e0b}
*{box-sizing:border-box;margin:0}body{width:1920px;height:1080px;background:var(--bg);color:var(--t1);font-family:Inter,system-ui,sans-serif;overflow:hidden;position:relative}
.glow{position:absolute;inset:0;background:radial-gradient(900px 600px at 50% 55%,rgba(99,102,241,.22),transparent 70%)}
.c{position:absolute;left:0;right:0;text-align:center}.big{font-size:150px;font-weight:800;letter-spacing:-4px}.mid{font-size:60px;font-weight:600}.sub{font-size:34px;color:var(--t2)}
.mono{font-family:'JetBrains Mono',monospace}
@keyframes up{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:none}}
.a{opacity:0;animation:up .5s ease-out forwards}
.box{position:absolute;width:480px;height:300px;border-radius:24px;background:#0b0f1c;border:1px solid rgba(255,255,255,.12);padding:36px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.box h3{font-size:50px;font-weight:800;margin-bottom:16px}.box p{font-size:28px;color:var(--t2);line-height:1.45}
.arrow{position:absolute;top:350px;font-size:90px;color:var(--acc);font-weight:800}
.li{font-size:44px;margin:30px 0;display:flex;gap:26px;align-items:baseline}.li b{color:var(--ok)}.hl{color:var(--acc)}
</style><div class=glow></div>"""

SHIELD = '<svg width=130 height=130 viewBox="0 0 24 24" fill=none stroke="#6366f1" stroke-width=1.6 stroke-linecap=round stroke-linejoin=round><path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>'

CARDS = {
 "title": CARD_CSS + f"""<div class="c a" style="top:200px">{SHIELD}</div><div class="c big a" style="top:360px;animation-delay:.2s">Veritas</div>
  <div class="c mid a" style="top:610px;animation-delay:.7s">Full walkthrough: every component</div>
  <div class="c sub a" style="top:720px;animation-delay:1.2s">Marks, requests, ledger, integrity, alerts, certificates</div>""",
 "arch": CARD_CSS + """<div class="c mid a" style="top:90px">How the pieces fit</div>
  <div class="box a" style="left:110px;top:300px;animation-delay:.3s"><h3>React UI</h3><p>Role-based pages: marks, requests, ledger, certificates</p></div>
  <div class="arrow a" style="left:610px;animation-delay:.6s">&rarr;</div>
  <div class="box a" style="left:720px;top:300px;animation-delay:.9s"><h3>FastAPI</h3><p>Sets the signed-in user, calls database functions</p></div>
  <div class="arrow a" style="left:1220px;animation-delay:1.2s">&rarr;</div>
  <div class="box a" style="left:1330px;top:300px;animation-delay:1.5s;border-color:#6366f1"><h3 style="color:#6366f1">PostgreSQL</h3><p>Triggers, row-level security, hash chain, Merkle batches</p></div>
  <div class="c sub a" style="top:690px;animation-delay:2.2s">+ external witness for Merkle roots &nbsp;&middot;&nbsp; IsolationForest anomaly scorer</div>""",
 "db": CARD_CSS + """<div class="c mid a" style="top:80px">Under the hood: the database enforces it</div>
  <div style="position:absolute;left:330px;top:210px">
  <div class="li a" style="animation-delay:.3s"><b>&#10003;</b><span>Ledger tables are <span class=hl>append-only</span></span></div>
  <div class="li a" style="animation-delay:.9s"><b>&#10003;</b><span>Marks change only via <span class=hl>apply_change()</span></span></div>
  <div class="li a" style="animation-delay:1.5s"><b>&#10003;</b><span>Maker &ne; checker, enforced by a <span class=hl>trigger</span></span></div>
  <div class="li a" style="animation-delay:2.1s"><b>&#10003;</b><span><span class=hl>Row-level security</span> per role and per institution</span></div>
  <div class="li a" style="animation-delay:2.7s"><b>&#10003;</b><span>109 SQL &middot; 11 cross-checks &middot; 3 concurrency &middot; 32 API &middot; 12 browser tests pass</span></div>
  <div class="li a" style="animation-delay:3.3s"><b>&#10003;</b><span>Per-course chains: <span class=hl>6.8&times;</span> a global chain at 16 clients</span></div></div>""",
 "outro": CARD_CSS + f"""<div class="c a" style="top:260px">{SHIELD}</div><div class="c big a" style="top:410px;animation-delay:.2s">Veritas</div>
  <div class="c mid a" style="top:650px;animation-delay:.6s">Tamper-evident marks &amp; certificates</div>
  <div class="c sub mono a" style="top:760px;animation-delay:1s;font-size:28px">PostgreSQL &middot; FastAPI &middot; React &nbsp;|&nbsp; RVCE DBMS (CD252IA)</div>""",
}


T0 = time.time()


def run():

    raw = os.path.join(HERE, "raw_full"); shutil.rmtree(raw, ignore_errors=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1920, "height": 1080})
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        EV = []
        FR = os.path.join(HERE, "frames_cdp"); shutil.rmtree(FR, ignore_errors=True); os.makedirs(FR)
        FRAMES = []
        cdp = ctx.new_cdp_session(page)
        def on_frame(ev):
            import base64
            n = len(FRAMES); fn = "%06d.jpg" % n
            with open(os.path.join(FR, fn), "wb") as fh: fh.write(base64.b64decode(ev["data"]))
            FRAMES.append((fn, ev["metadata"]["timestamp"]))
            cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        cdp.on("Page.screencastFrame", on_frame)
        T0 = time.time()
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        page.set_default_timeout(15000)
        page.on('dialog', lambda d: d.accept())

        def hold(s):
            if s > 0: page.wait_for_timeout(int(s * 1000))   # keeps Playwright's loop running so screencast frames are delivered and acked
        def cap(t, s=0.0):
            if t: EV.append(('cap', time.time(), s))
            print('STEP %.1f' % (time.time()-T0), t, flush=True); page.evaluate(SETCAP, t); hold(s)
        def card(name, s):
            EV.append(('card', time.time(), s)); print('CARD %.1f' % (time.time()-T0), name, flush=True)
            page.set_content(CARDS[name]); page.evaluate("document.fonts.ready"); hold(s)
        def move(loc):
            loc.scroll_into_view_if_needed(); bx = loc.bounding_box()
            page.evaluate(MOVE, [bx["x"] + bx["width"] / 2 + 6, bx["y"] + bx["height"] / 2 + 6]); hold(0.24)
        def click(loc):
            move(loc); page.evaluate(RIP); loc.click(); hold(0.12)
        def type_in(loc, text, delay=9):
            click(loc); page.keyboard.press("Control+A"); page.keyboard.type(text, delay=delay); hold(0.03)
        def login(email):
            print('LOGIN %.1f' % (time.time()-T0), email, flush=True)
            page.goto(URL + "/login"); page.wait_for_selector("#email"); hold(0.4)
            page.fill("#email", email); page.fill("#password", PW)
            click(page.locator("#login-btn")); page.wait_for_url("**/marks"); page.wait_for_selector("tbody tr, .card"); hold(0.3)
        def signout():
            page.evaluate(SETCAP, ""); click(page.locator("button").first); page.wait_for_url("**/login"); hold(0.3)
        def nav(label):
            print('NAV %.1f' % (time.time()-T0), label, flush=True)
            click(page.get_by_role("link", name=label)); hold(0.7)
        def set_filter(t):
            f = page.get_by_placeholder("Filter"); click(f); page.keyboard.press("Control+A"); page.keyboard.type(t, delay=9); hold(0.35)
        def row(*texts):
            r = page.locator("tbody tr")
            for t in texts: r = r.filter(has_text=t)
            return r.first

        try:
            # ---- title + architecture
            card("title", 2.4)
            card("arch", 4.6)

            # ---- faculty: sign in, enter a mark, bulk import, request a change on a frozen mark
            page.goto(URL + "/login"); page.wait_for_selector("#email"); hold(0.4)
            cap("Sign in: the password is checked inside Postgres", 0.0)
            type_in(page.locator("#email"), "iyer@rvce.example"); type_in(page.locator("#password"), PW)
            click(page.locator("#login-btn")); page.wait_for_url("**/marks"); page.wait_for_selector("tbody tr"); hold(0.6)
            cap("Faculty edit only their own course's marks", 0.0)
            set_filter("Asha")
            click(row("CD251TA", "CIE-2").get_by_role("button", name="Edit"))
            type_in(page.locator("#apply-value"), "41"); type_in(page.locator("#apply-reason"), "entered from answer scripts")
            cap("apply_change() writes the mark and its ledger row together", 0.0); hold(1.1)
            click(page.locator("#apply-submit")); hold(1.4)
            set_filter("")
            open(IMPORT_CSV, "w").write("usn,course_code,assessment_type,value,reason\n1RV24CD002,CD251TA,CIE-2,33,bulk entry\n1RV24CD003,CD251TA,CIE-2,36,bulk entry\n")
            cap("A whole class loads from CSV, row by row, through the same function", 0.0)
            move(page.locator("#import-btn")); page.evaluate(RIP)
            page.locator("#import-btn input[type=file]").set_input_files(IMPORT_CSV); hold(2.0)
            set_filter("Asha")
            cap("Frozen assessment: changes now need an approved request", 0.0)
            click(row("CD251TA", "CIE-1").get_by_role("button", name="Request"))
            type_in(page.locator("#req-value"), "38"); type_in(page.locator("#req-reason"), "re-evaluation after paper recheck")
            hold(0.4); click(page.locator("#req-submit")); hold(1.4)

            # ---- checker: notified, approves; maker applies
            page.evaluate(SETCAP, ""); signout(); login("hegde@rvce.example")
            cap("The checker is told at once", 0.0)
            nav("Notifications"); hold(1.4)
            nav("Approve Requests")
            cap("A trigger blocks self-approval: a different checker decides", 0.0); hold(1.2)
            click(page.locator("[id^=approve-]").first); hold(1.4)
            page.evaluate(SETCAP, ""); signout(); login("iyer@rvce.example")
            set_filter("Asha")
            click(row("CD251TA", "CIE-1").get_by_role("button", name="Apply"))
            type_in(page.locator("#apply-value"), "38"); type_in(page.locator("#apply-reason"), "re-evaluation after paper recheck")
            type_in(page.locator("#apply-reqid"), "1")
            cap("Applied through the approved request, in one atomic write", 0.0); hold(1.3)
            click(page.locator("#apply-submit")); hold(1.5)

            # ---- admin: integrity with scheduler log, ledger, alerts
            page.evaluate(SETCAP, ""); signout(); login("admin@rvce.example")
            nav("Integrity")
            cap("Integrity: chains, marks and Merkle batches, re-checked", 2.2)
            click(page.locator("#seal-2")); hold(0.8)
            cap("Seal: new revisions become one Merkle batch", 1.8)
            click(page.locator("#anchor-btn")); hold(0.8)
            cap("Anchor: roots are pinned in the external witness", 2.0)
            click(page.locator("#verify-now-btn")); hold(1.0)
            page.evaluate("()=>{const m=document.querySelector('main')||document.scrollingElement; m.scrollTo({top:m.scrollHeight,behavior:'smooth'})}"); hold(0.8)
            cap("Scheduled checks log every run; a failure alerts the admins", 2.6)
            page.evaluate("()=>{const m=document.querySelector('main')||document.scrollingElement; m.scrollTo({top:380,behavior:'smooth'})}"); hold(0.6)
            click(page.get_by_role("button", name="Proof").first); hold(0.6)
            cap("Inclusion proof: one row checked against the witnessed root", 2.4)
            click(page.get_by_role("button", name="Close")); hold(0.3)
            nav("Ledger")
            cap("The Ledger badge comes from a real verification", 2.0)
            nav("Alerts")
            click(page.locator("#run-scorer-btn")); hold(2.4)
            if page.locator("[id^=confirm-]").count():
                cap("Each alert says why it fired; a checker rules on it", 2.4)
                click(page.locator("[id^=confirm-]").first); hold(1.4)

            # ---- certificates: transcript with PDF + QR, scanned by a logged-out visitor
            page.evaluate(SETCAP, ""); signout(); login("hegde@rvce.example")
            nav("Certificates")
            click(page.locator("#issue-cert-btn")); hold(0.3)
            page.select_option("#cert-mode", "transcript"); page.select_option("#cert-student", label="Asha Nair (1RV24CD001)")
            cap("Transcript: built from the ledger's marks, hashed, stored as a PDF", 2.4)
            click(page.locator("#cert-submit")); hold(1.5)
            click(page.locator(".cert-card").first); hold(0.6)
            cap("The PDF carries a QR code that verifies it", 2.2)
            click(page.get_by_role("button", name="Close")); hold(0.3)
            h = httpx.Client(base_url="http://127.0.0.1:8000"); tok = h.post("/api/login", json={"email": "hegde@rvce.example", "password": PW}).json()["csrf"]
            sid = next(x["user_id"] for x in h.get("/api/directory").json()["students"] if x["usn"] == "1RV24CD002")
            link = h.post("/api/certificates", json={"student_id": sid, "cert_type": "NOC", "content": "No objection certificate."}, headers={"X-CSRF-Token": tok}).json()["verify_link"]
            page.evaluate(SETCAP, ""); signout()
            page.goto(link); page.get_by_text("Certificate is VALID").wait_for(); hold(0.4)
            cap("Scanning the QR as a visitor verifies it with no login", 2.8)

            # ---- student: share a proof of one revision, verified offline
            login("asha@rvce.example")
            nav("Audit Trail")
            cap("A student can prove a single revision without exposing the rest", 2.4)
            proof_path = os.path.join(tempfile.gettempdir(), "veritas_demo_proof.json")
            with page.expect_download() as dl:
                click(page.get_by_role("button", name="Share proof").first)
            dl.value.save_as(proof_path)
            res = subprocess.run([sys.executable, os.path.join(HERE_ROOT, "verify_disclosure.py"), proof_path, "--witness", WITNESS_FILE], capture_output=True, text=True, encoding="utf-8")
            CARDS["proof"] = proof_card(res.stdout.strip() or res.stderr.strip())
            card("proof", 4.0)

            # ---- a second institution sees only its own data
            page.goto(URL + "/marks"); page.wait_for_selector("tbody tr, .card"); signout()      # back to the app (the card replaced the page), then out
            login("admin@beta.example")
            nav("Integrity")
            cap("A second institution's admin sees only that institution", 3.0)

            card("db", 6.6)
            card("outro", 2.0)
        except Exception:
            page.screenshot(path=os.path.join(HERE,'fail.png')); print('FAILED at url', page.url, flush=True); ctx.close(); b.close(); raise
        hold(0.6); cdp.send("Page.stopScreencast"); hold(0.3)
        ctx.close(); b.close()
    import json
    json.dump({"events": EV, "frames": FRAMES, "t0": T0}, open(os.path.join(HERE, "events.json"), "w"))
    print("saved", len(FRAMES), "frames; first ts - T0 = %.3f" % (FRAMES[0][1] - T0), "last ts - T0 = %.1f" % (FRAMES[-1][1] - T0))
    return
    out = os.path.join(HERE, "full_raw.webm"); shutil.copy(path, out)
    print("saved", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    run()
