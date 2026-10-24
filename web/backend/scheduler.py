"""Background jobs, started with the API: verify chains, seal + anchor new revisions, re-score anomalies.

Intervals (seconds) come from VERITAS_VERIFY_EVERY / VERITAS_ANCHOR_EVERY / VERITAS_SCORE_EVERY; 0 disables a job.
VERITAS_SCHEDULER=0 turns the whole thing off (used for recordings and tests that need a still database).
"""
from __future__ import annotations

import os
import threading
import time
import traceback

import integrity
from anomaly import score_revisions

JOBS = {
    "verify": (int(os.environ.get("VERITAS_VERIFY_EVERY", "300")), lambda: [integrity.verify_all(institution_id=i["institution_id"]) for i in integrity.institutions()]),
    "anchor": (int(os.environ.get("VERITAS_ANCHOR_EVERY", "900")), lambda: (integrity.seal_all(), integrity.anchor_all())),
    "score": (int(os.environ.get("VERITAS_SCORE_EVERY", "1800")), lambda: _score()),
}
_stop = threading.Event()
_thread: threading.Thread | None = None


def _score():
    r = score_revisions()
    integrity.log_run("score", True, r)
    return r


def _loop():
    due = {name: time.time() + min(every, 20) for name, (every, _) in JOBS.items() if every > 0}   # first run shortly after start
    while not _stop.wait(1.0):
        now = time.time()
        for name, t in list(due.items()):
            if now < t:
                continue
            every, fn = JOBS[name]
            try:
                fn()
            except Exception as e:  # a failing job must be visible, and must not kill the loop
                traceback.print_exc()
                try:
                    integrity.log_run(name if name != "anchor" else "anchor", False, {"error": str(e)[:500]})
                except Exception:
                    pass
            due[name] = time.time() + every


def start() -> bool:
    global _thread
    if os.environ.get("VERITAS_SCHEDULER", "1") == "0" or _thread:
        return False
    _thread = threading.Thread(target=_loop, name="veritas-scheduler", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
