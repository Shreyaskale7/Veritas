"""Integrity services shared by the API and the scheduler: verify, seal, anchor, proofs, alerting.

All of it runs on the owner connection (verify_*, seal_batch and record_anchor are not granted to the app role).
Functions take an optional institution_id: the API passes the signed-in admin's institution so an admin only ever sees and
acts on their own courses; the scheduler passes each institution in turn.
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import threading
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import anchor_service as A  # noqa: E402
import merkle  # noqa: E402
from db import admin_conn, execute, fetchall, fetchone  # noqa: E402


# Appending to the witness (write file, commit, push) and checking it must not interleave: a check made between the write and
# the commit would see 'uncommitted changes' and raise a false tamper alarm.
_witness_lock = threading.RLock()


def witness():
    """Witness selected by WITNESS_TYPE (file | git | immudb); file witness defaults to <project>/witness.jsonl."""
    env = {"WITNESS_PATH": os.environ.get("WITNESS_PATH", str(ROOT / "witness.jsonl")),
           "WITNESS_GIT_DIR": os.environ.get("WITNESS_GIT_DIR", str(ROOT / "witness-repo"))}
    return A.make_witness(**env)


def institutions() -> list[dict]:
    with admin_conn() as conn:
        return fetchall(conn, "SELECT institution_id, slug FROM institutions ORDER BY institution_id")


def _course_ids(conn, institution_id):
    if institution_id is None:
        return None
    return {r["course_id"] for r in fetchall(conn, "SELECT course_id FROM courses WHERE institution_id = %s", (institution_id,))}


def course_in_institution(course_id: int, institution_id: int) -> bool:
    with admin_conn() as conn:
        return fetchone(conn, "SELECT 1 AS ok FROM courses WHERE course_id = %s AND institution_id = %s", (course_id, institution_id)) is not None


# ---------------------------------------------------------------- run log + alerting
def log_run(kind: str, ok: bool, detail: dict) -> None:
    with admin_conn() as conn:
        execute(conn, "INSERT INTO integrity_runs (kind, ok, detail) VALUES (%s, %s, %s::jsonb)", (kind, ok, json.dumps(detail, default=str)))


def recent_runs(limit: int = 20, institution_slug: str | None = None) -> list[dict]:
    """Verification runs are logged per institution; seal / anchor / score runs carry no institution data."""
    with admin_conn() as conn:
        if institution_slug is None:
            return fetchall(conn, "SELECT run_id, kind, ok, detail, started_at FROM integrity_runs ORDER BY run_id DESC LIMIT %s", (limit,))
        return fetchall(conn, "SELECT run_id, kind, ok, detail, started_at FROM integrity_runs "
                              "WHERE kind <> 'verify' OR detail->>'institution' = %s ORDER BY run_id DESC LIMIT %s", (institution_slug, limit))


def _send_email(subject: str, body: str) -> None:
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("ALERT_EMAIL_TO")
    if not (host and to):
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("ALERT_EMAIL_FROM", "veritas@localhost"), to
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "25")), timeout=10) as s:
        if os.environ.get("SMTP_USER"):
            s.starttls(); s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)


def alert_ops(subject: str, detail: dict, institution_id: int | None = None) -> None:
    """Tell the people who run the system: in-app notification to the admins of the affected institution (all admins when it is
    not specific to one), optional webhook and e-mail."""
    text = f"{subject}: {json.dumps(detail, default=str)[:600]}"
    with admin_conn() as conn:
        execute(conn, "INSERT INTO notifications (user_id, kind, message, link) SELECT user_id, 'integrity_failure', %s, '/integrity' "
                      "FROM users WHERE role = 'admin' AND (%s::int IS NULL OR institution_id = %s::int)", (text, institution_id, institution_id))
    url = os.environ.get("INTEGRITY_WEBHOOK")
    if url:
        try:
            import httpx
            httpx.post(url, json={"event": "integrity_failure", "subject": subject, "detail": detail}, timeout=10)
        except Exception as e:  # alerting must never break the check itself
            print("webhook failed:", e)
    try:
        _send_email(subject, text)
    except Exception as e:
        print("e-mail failed:", e)


# ---------------------------------------------------------------- batches, witness, proofs
def _batches(conn, institution_id=None):
    sql = ("SELECT b.batch_id, b.course_id, b.seq_from, b.seq_to, b.merkle_root, i.slug AS institution "
           "FROM merkle_batches b JOIN courses c ON c.course_id = b.course_id JOIN institutions i ON i.institution_id = c.institution_id")
    if institution_id is not None:
        return fetchall(conn, sql + " WHERE c.institution_id = %s ORDER BY b.batch_id", (institution_id,))
    return fetchall(conn, sql + " ORDER BY b.batch_id")


def _hashes(conn, course, lo, hi):
    return [r["row_hash"] for r in fetchall(conn, "SELECT row_hash FROM mark_revisions WHERE course_id=%s AND seq BETWEEN %s AND %s ORDER BY seq", (course, lo, hi))]


def witness_verify(institution_id: int | None = None):
    """(problems, ok, message). Recomputes each witnessed batch from the revisions, never trusting the stored root.
    With an institution, only the witness records of that institution's courses are examined."""
    w = witness()
    with _witness_lock:
        wok, wmsg = w.self_check()
        try:
            recs = w.records() if hasattr(w, "records") else []
        except NotImplementedError:
            recs = []
    problems = [] if wok else [("witness", wmsg)]
    if not hasattr(w, "records"):
        return problems, wok, wmsg
    with admin_conn() as conn:
        mine = _course_ids(conn, institution_id)
        have = {(b["course_id"], b["seq_from"], b["seq_to"]) for b in _batches(conn)}
        for rec in recs:
            p = rec["payload"]
            if mine is not None and p["course_id"] not in mine:
                continue
            key = (p["course_id"], p["seq_from"], p["seq_to"])
            if key not in have:
                problems.append(("missing", f"course {key[0]}: witnessed batch seq {key[1]}-{key[2]} is absent from the database"))
            hs = _hashes(conn, *key)
            if len(hs) != key[2] - key[1] + 1:
                problems.append(("truncated", f"course {key[0]}: witnessed seq {key[1]}-{key[2]} but the database holds only {len(hs)} revisions"))
            elif merkle.root(hs) != p["merkle_root"]:
                problems.append(("rewritten", f"course {key[0]}: revisions seq {key[1]}-{key[2]} no longer hash to the witnessed Merkle root"))
    return problems, wok and not problems, (wmsg if not problems else f"{len(problems)} problem(s)")


def verify_all(record: bool = True, institution_id: int | None = None) -> dict:
    """Database chains + marks + batches + witness for one institution (or all). Logs the run and alerts on a new failure."""
    with admin_conn() as conn:
        mine = _course_ids(conn, institution_id)
        chains = [c for c in fetchall(conn, "SELECT * FROM verify_all_chains()") if mine is None or c["cid"] in mine]
        slug = fetchone(conn, "SELECT slug FROM institutions WHERE institution_id = %s", (institution_id,))["slug"] if institution_id else None
    problems, wok, wmsg = witness_verify(institution_id)
    bad = [c["cid"] for c in chains if not (c["chain_ok"] and c["marks_ok"] and c["batches_ok"])]
    ok = not bad and wok
    result = {"ok": ok, "chains": chains, "witness_ok": wok, "witness_message": wmsg,
              "witness_problems": [{"kind": k, "message": m} for k, m in problems]}
    if record:
        with admin_conn() as conn:
            row = fetchone(conn, "SELECT ok FROM integrity_runs WHERE kind = 'verify' AND coalesce(detail->>'institution', '') = coalesce(%s, '') ORDER BY run_id DESC LIMIT 1", (slug,))
            was_ok = row["ok"] if row else True
        detail = {"institution": slug, "bad_courses": bad, "witness": wmsg, "problems": result["witness_problems"]}
        log_run("verify", ok, detail)
        if not ok and was_ok:
            alert_ops("Veritas integrity check FAILED", detail, institution_id)
    return result


def seal_all() -> list[int]:
    out = []
    with admin_conn() as conn:
        for c in fetchall(conn, "SELECT course_id FROM courses ORDER BY course_id"):
            row = fetchone(conn, "SELECT seal_batch(%s::int) AS batch_id", (c["course_id"],))
            if row["batch_id"]:
                out.append(row["batch_id"])
    log_run("seal", True, {"batches": out})
    return out


def anchor_all(institution_id: int | None = None) -> int:
    w = witness()
    n = 0
    with _witness_lock, admin_conn() as conn:
        done = {r["batch_id"] for r in fetchall(conn, "SELECT batch_id FROM anchors WHERE anchor_type = %s", (w.kind,))}
        for b in _batches(conn, institution_id):
            if b["batch_id"] in done:
                continue
            ref = w.append({"institution": b["institution"], **{k: b[k] for k in ("course_id", "seq_from", "seq_to", "merkle_root")}})
            execute(conn, "SELECT record_anchor(%s::int, %s::text, %s::text)", (b["batch_id"], w.kind, ref))
            n += 1
    log_run("anchor", True, {"anchored": n, "witness": w.kind})
    return n


def merkle_proof(course_id: int, seq: int) -> dict | None:
    with admin_conn() as conn:
        for b in _batches(conn):
            if b["course_id"] == course_id and b["seq_from"] <= seq <= b["seq_to"]:
                hs = _hashes(conn, course_id, b["seq_from"], b["seq_to"])
                i = seq - b["seq_from"]
                return {"course_id": course_id, "seq": seq, "row_hash": hs[i], "path": merkle.proof(hs, i),
                        "batch_id": b["batch_id"], "merkle_root": b["merkle_root"], "institution": b["institution"]}
    return None
