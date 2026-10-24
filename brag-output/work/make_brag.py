"""Renders brag.mp4 for Veritas. Needs the app running (start.ps1). Frames are pure functions of t."""
import os, sys, subprocess, shutil, wave, time
import numpy as np
from playwright.sync_api import sync_playwright
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)
FR = os.path.join(HERE, "frames")
FPS, W, H = 30, 1920, 1080
DUR = 21.5
URL = "http://127.0.0.1:5173"
FF = imageio_ffmpeg.get_ffmpeg_exe()
CUTS = [2.5, 5.5, 9.5, 14.0, 18.0]          # scene boundaries (dip-to-black here)
TICKS = (9.8, 10.5, 11.2, 12.3)
POSTER_T = 5.0                               # settled reveal frame

CARD_HTML = """<!doctype html><meta charset=utf-8>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@500&display=swap" rel=stylesheet>
<style>
:root{--bg:#070b14;--t1:#f0f4ff;--t2:#8892b0;--acc:#6366f1;--ok:#10b981;--bad:#f43f5e}
*{box-sizing:border-box;margin:0}
body{width:1920px;height:1080px;background:var(--bg);color:var(--t1);font-family:Inter,system-ui,sans-serif;overflow:hidden;position:relative}
.glow{position:absolute;inset:0;background:radial-gradient(900px 600px at 50% 55%,rgba(99,102,241,.22),transparent 70%)}
.abs{position:absolute;left:0;right:0;text-align:center}
.big{font-size:150px;font-weight:800;letter-spacing:-4px}
.mid{font-size:64px;font-weight:600;color:var(--t1)}
.sub{font-size:34px;color:var(--t2);font-weight:400}
.mono{font-family:'JetBrains Mono',monospace}
.term{position:absolute;left:300px;right:300px;top:250px;background:#0b0f1c;border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:50px 60px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.term .l{font-size:40px;margin:26px 0;display:flex;gap:24px;align-items:baseline;white-space:nowrap}
.tick{color:var(--ok);font-weight:800}
.hl{color:var(--acc)}
</style>
<body><div class=glow></div>
<div id=s1><div class="abs big" id=a1 style="top:380px">Marks get changed.</div>
 <div class="abs big" id=a2 style="top:550px;color:var(--bad)">Quietly.</div></div>
<div id=s2><div class=abs id=logo style="top:250px"><svg width=150 height=150 viewBox="0 0 24 24" fill=none stroke="#6366f1" stroke-width=1.6 stroke-linecap=round stroke-linejoin=round><path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg></div>
 <div class="abs big" id=b1 style="top:420px">Veritas</div>
 <div class="abs mid" id=b2 style="top:650px">Marks nobody can quietly rewrite.</div></div>
<div id=s4><div class=term>
 <div class="mono sub" style="font-size:28px;margin-bottom:10px">verify_chain( course )</div>
 <div class="l" id=t1><span class=tick>&#10003;</span><span>Edit a row's value &rarr; <span class=hl>seq 3</span> named as broken</span></div>
 <div class="l" id=t2><span class=tick>&#10003;</span><span>Delete a middle row &rarr; <span class=hl>sequence gap</span> at seq 4</span></div>
 <div class="l" id=t3><span class=tick>&#10003;</span><span>Re-hash the whole chain &rarr; caught by <span class=hl>old_value</span></span></div>
 <div class="l" id=t4 style="margin-top:46px;font-size:54px;font-weight:800;color:var(--ok)">84 / 84 tests pass</div>
</div></div>
<div id=s6><div class=abs id=c0 style="top:230px"><svg width=110 height=110 viewBox="0 0 24 24" fill=none stroke="#6366f1" stroke-width=1.6 stroke-linecap=round stroke-linejoin=round><path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg></div>
 <div class="abs big" id=c1 style="top:370px">Veritas</div>
 <div class="abs mid" id=c2 style="top:610px">Tamper-evident marks &amp; certificates</div>
 <div class="abs sub" id=c3 style="top:730px">PostgreSQL &nbsp;&middot;&nbsp; FastAPI &nbsp;&middot;&nbsp; React</div>
 <div class="abs sub mono" id=c4 style="top:830px;font-size:26px">RVCE &middot; DBMS (CD252IA)</div></div>
<div id=dip style="position:absolute;inset:0;background:#000;opacity:0;pointer-events:none;z-index:50"></div>
<script>
const cl=(x,a=0,b=1)=>Math.min(b,Math.max(a,x));
const ease=x=>1-Math.pow(1-cl(x),3);
const $=id=>document.getElementById(id);
function show(id,t0,t1,rise=24){const e=$(id);const p=ease((T-t0)/0.45);const o=t1==null?1:1-cl((T-t1)/0.25);
  e.style.opacity=cl(p)*o;e.style.transform=`translateY(${(1-p)*rise}px)`}
let T=0;
const CUTS=__CUTS__;
function setT(t){T=t;
 const on=(a,b)=>t>=a&&t<b;
 $('s1').style.display=on(0,2.5)?'block':'none';
 $('s2').style.display=on(2.5,5.5)?'block':'none';
 $('s4').style.display=on(9.5,14.0)?'block':'none';
 $('s6').style.display=t>=18.0?'block':'none';
 show('a1',0.1,null);show('a2',1.2,null);
 show('logo',2.7,null);show('b1',3.0,null);show('b2',3.7,null);
 [['t1',9.8],['t2',10.5],['t3',11.2],['t4',12.3]].forEach(([id,s])=>show(id,s,null,14));
 show('c0',18.2,null);show('c1',18.3,null);show('c2',18.9,null);show('c3',19.4,null);show('c4',19.8,null);
 let d=0;for(const c of CUTS){d=Math.max(d,1-cl(Math.abs(t-c)/0.18))}
 if(t<0.15)d=Math.max(d,1-t/0.15); if(t>__END__-0.8)d=Math.max(d,cl((t-(__END__-0.8))/0.8));
 $('dip').style.opacity=t===__POSTER__?0:d;
}
</script>"""

APP_OVERLAY = """
(()=>{ if(window.__ov) return;
 const d=document.createElement('div'); d.id='__ov';
 d.innerHTML=`<div id=__cap></div><div id=__dip></div>`;
 document.body.appendChild(d);
 const s=document.createElement('style'); s.textContent=`
  #__cap{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:99998;background:rgba(7,11,20,.94);color:#f0f4ff;
   font:700 46px Inter,system-ui,sans-serif;padding:26px 46px;border-radius:22px;border:1px solid rgba(99,102,241,.55);
   box-shadow:0 20px 70px rgba(0,0,0,.65),0 0 60px rgba(99,102,241,.25);white-space:nowrap;opacity:0}
  #__dip{position:fixed;inset:0;background:#000;z-index:99999;opacity:0;pointer-events:none}`;
 document.head.appendChild(s); window.__ov=1;})()
"""

APP_SET = """([t,cap,t0,t1,cuts,end,scrollTo,s0,s1])=>{
 const cl=(x,a=0,b=1)=>Math.min(b,Math.max(a,x)); const ease=x=>1-Math.pow(1-cl(x),3);
 const c=document.getElementById('__cap'); c.textContent=cap;
 const p=ease((t-t0)/0.45), o=1-cl((t-t1)/0.25);
 c.style.opacity=cl(p)*o; c.style.transform=`translateX(-50%) translateY(${(1-p)*26}px)`;
 let d=0; for(const k of cuts) d=Math.max(d,1-cl(Math.abs(t-k)/0.18));
 document.getElementById('__dip').style.opacity=d;
 const el=[document.querySelector('main'),document.scrollingElement].find(e=>e&&e.scrollHeight>e.clientHeight+5);
 if(el&&scrollTo) el.scrollTop=scrollTo*cl((t-s0)/(s1-s0));
}"""


def synth():
    sr = 44100
    n = int(DUR * sr)
    t = np.arange(n) / sr
    L = np.zeros(n); R = np.zeros(n)
    hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    chords = [(57, [57, 60, 64]), (53, [53, 57, 60]), (48, [48, 52, 55]), (55, [55, 59, 62])] * 2   # Am F C G
    seg = DUR / len(chords)
    rng = np.random.default_rng(7)
    for i, (root, notes) in enumerate(chords):
        a, b = int(i * seg * sr), min(n, int((i + 1) * seg * sr + 0.5 * sr))
        tt = t[a:b] - i * seg
        env = np.minimum(1, tt / 0.5) * np.exp(-np.maximum(0, tt - seg) * 4)
        pad = np.zeros_like(tt)
        for m in notes:
            for det in (-0.07, 0.07):
                f = hz(m + 12) * 2 ** (det / 12)
                pad += np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt) + 0.12 * np.sin(6 * np.pi * f * tt)
        bass = np.sin(2 * np.pi * hz(root - 12) * tt) * 1.4
        sig = (pad * 0.045 + bass * 0.11) * env
        L[a:b] += sig; R[a:b] += sig * 0.96
        # soft arpeggio plucks (eighths), panned a little
        step = seg / 8
        for k in range(8):
            m = notes[k % 3] + 24 + (12 if k % 4 == 3 else 0)
            s0 = int((i * seg + k * step) * sr)
            m_len = int(0.7 * sr)
            if s0 + m_len > n: continue
            x = np.arange(m_len) / sr
            pl = (np.sin(2 * np.pi * hz(m) * x) + 0.25 * np.sin(4 * np.pi * hz(m) * x)) * np.exp(-x * 7) * 0.05
            pan = 0.35 + 0.3 * (k % 2)
            L[s0:s0 + m_len] += pl * (1 - pan); R[s0:s0 + m_len] += pl * pan * 1.4
    # cut accents: soft low swell + blip in key (E5) at every scene cut
    for c in CUTS:
        s0 = int((c - 0.05) * sr); ln = int(1.0 * sr); x = np.arange(ln) / sr
        blip = np.sin(2 * np.pi * hz(76) * x) * np.exp(-x * 5) * 0.06 + np.sin(2 * np.pi * hz(64) * x) * np.exp(-x * 3) * 0.05
        L[s0:s0 + ln] += blip; R[s0:s0 + ln] += blip
    # quiet typing ticks for the terminal lines
    for c in TICKS:
        s0 = int(c * sr); ln = int(0.05 * sr)
        tick = rng.standard_normal(ln) * np.exp(-np.arange(ln) / sr * 120) * 0.012
        tick = np.convolve(tick, np.ones(6) / 6, mode="same")
        L[s0:s0 + ln] += tick; R[s0:s0 + ln] += tick
    # shared space: feedback delay
    for sig in (L, R):
        d = int(0.31 * sr)
        for j in range(d, n):
            sig[j] += sig[j - d] * 0.28
    st = np.stack([L, R], 1)
    st *= np.minimum(1, t / 0.3)[:, None] * np.clip((DUR - t) / 1.4, 0, 1)[:, None]
    st = np.tanh(st * 1.3)
    st *= 0.89 / np.abs(st).max()
    path = os.path.join(HERE, "audio.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return path


def scene_of(t):
    return "card" if (t < 5.5 or 9.5 <= t < 14.0 or t >= 18.0) else ("rev" if t < 9.5 else "int")


def main():
    shutil.rmtree(FR, ignore_errors=True); os.makedirs(FR)
    html = CARD_HTML.replace("__CUTS__", str(CUTS)).replace("__END__", str(DUR)).replace("__POSTER__", str(POSTER_T))
    N = int(DUR * FPS)
    only = {int(x) for x in sys.argv[1].split(',')} if len(sys.argv) > 1 else None
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
        card = ctx.new_page(); card.set_content(html); card.evaluate("document.fonts.ready"); time.sleep(1.5)
        app = ctx.new_page()
        app.goto(URL + "/login"); app.fill("input >> nth=0", "admin@rvce.example"); app.fill("input >> nth=1", "veritas2026")
        app.locator("#login-btn").click(); app.wait_for_url("**/marks", timeout=15000)
        pages = {}
        for name, path in (("rev", "/revisions"), ("int", "/integrity")):
            pg = ctx.new_page(); pg.goto(URL + path); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
            pg.evaluate(APP_OVERLAY); pages[name] = pg
        cfg = {"rev": ("Every edit is a hash-chained revision", 5.8, 9.4, 700, 5.5, 9.5),
               "int": ("Every chain re-verified. Roots anchored outside the database.", 14.3, 17.9, 0, 14.0, 18.0)}
        for i in range(N):
            if only is not None and i not in only: continue
            t = i / FPS
            sc = scene_of(t)
            if sc == "card":
                card.evaluate("t=>setT(t)", t); pg = card
            else:
                cap, t0, t1, scroll, s0, s1 = cfg[sc]; pg = pages[sc]
                pg.evaluate(APP_SET, [t, cap, t0, t1, CUTS, DUR, scroll, s0, s1])
            pg.screenshot(path=os.path.join(FR, f"{i:05d}.jpg"), type="jpeg", quality=93)
            if i % 60 == 0: print("frame", i, "/", N, sc, flush=True)
        # poster: settled reveal frame
        card.evaluate("t=>setT(t)", POSTER_T)
        card.screenshot(path=os.path.join(OUT, "brag.jpg"), type="jpeg", quality=95)
        b.close()
    if only is None:
        shutil.copy(os.path.join(OUT, "brag.jpg"), os.path.join(FR, "00000.jpg"))   # poster as frame 0
        wav = synth()
        subprocess.run([FF, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FR, "%05d.jpg"), "-i", wav,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", str(DUR), os.path.join(OUT, "brag.mp4")], check=True)
        print("done", os.path.getsize(os.path.join(OUT, "brag.mp4")) // 1024, "KB")


if __name__ == "__main__":
    main()
