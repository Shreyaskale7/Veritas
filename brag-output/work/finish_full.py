"""Builds a constant-60fps master from the timestamped CDP frames, speed-ramps it (captions/cards 1x,
mechanical clicking/typing faster) and muxes music -> ../veritas_full_demo.mp4."""
import os, json, shutil, subprocess
import imageio_ffmpeg
import make_brag as mb

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.dirname(HERE)
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS, FAST, MIN_SLOW = 60, 2.4, 1.7
meta = json.load(open(os.path.join(HERE, "events.json")))
frames, events = meta["frames"], meta["events"]
ts0 = frames[0][1]
print("clock check: first frame - T0 = %.3fs, frames=%d" % (ts0 - meta["t0"], len(frames)))

# 1) timestamped frames -> constant 60 fps master (static screens keep their real duration)
lst = os.path.join(HERE, "frames.txt")
last_end = max(t + hold for _, t, hold in events) + 0.6       # the screencast only emits frames when pixels change, so hold the last one to the end
last = last_end - ts0
with open(lst, "w") as f:
    for i, (fn, ts) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else max(last_end, ts + 0.5)
        f.write("file 'frames_cdp/%s'\nduration %.5f\n" % (fn, max(nxt - ts, 0.001)))
    f.write("file 'frames_cdp/%s'\n" % frames[-1][0])
master = os.path.join(HERE, "full_cfr60.mp4")
subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", f"fps={FPS},scale=1920:1080,format=yuv420p",
                "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", master], check=True)

# 2) speed ramp windows (event times are wall-clock; frame timestamps are the same clock)
wins = []
for kind, t, hold in events:
    a = t - ts0
    wins.append((a, a + (hold if kind == "card" else max(hold, MIN_SLOW))))
wins.sort(); merged = []
for a, b in wins:
    if merged and a <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], b)
    else: merged.append([a, b])
end = min(last, merged[-1][1] + 0.4)
segs, cur = [], 0.0
for a, b in merged:
    a, b = max(0, min(a, end)), min(b, end)
    if a > cur + 0.05: segs.append((cur, a, FAST))
    if b > a: segs.append((a, b, 1.0))
    cur = max(cur, b)
if end > cur + 0.05: segs.append((cur, end, FAST))
dur = sum((b - a) / sp for a, b, sp in segs)

parts = [f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{sp},fps={FPS}[v{i}]" for i, (a, b, sp) in enumerate(segs)]
fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,format=yuv420p[v]"
mb.DUR, mb.CUTS, mb.TICKS = dur, [], ()
wav = mb.synth(); shutil.copy(wav, os.path.join(HERE, "audio_full.wav"))
out = os.path.join(OUT, "veritas_full_demo.mp4")
subprocess.run([FF, "-y", "-loglevel", "error", "-i", master, "-i", wav, "-filter_complex", fc, "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-af", "volume=0.55",
                "-movflags", "+faststart", "-t", f"{dur:.2f}", out], check=True)
print("master %.0fs -> final %.1fs @ %dfps" % (last, dur, FPS), os.path.getsize(out) // 1024, "KB")
