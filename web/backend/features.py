"""Bulk CSV import/export, notifications, and selective-disclosure proofs."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import integrity
from common import me_row, pg_err, uid
from db import admin_conn, app_conn, execute, fetchall, fetchone

router = APIRouter()
MAX_IMPORT_ROWS = 2000


def _csv(rows: list[dict], cols: list[str], name: str) -> Response:
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ export (row-level security decides what the caller may see)
@router.get("/api/export/marks.csv")
def export_marks(request: Request):
    with app_conn(uid(request)) as conn:
        rows = fetchall(conn, """SELECT s.usn, c.course_code, m.assessment_type, m.current_value AS value, a.max_marks, m.version, m.updated_at
                                   FROM marks m JOIN students s ON s.user_id = m.student_id JOIN courses c ON c.course_id = m.course_id
                                   JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type
                                  ORDER BY c.course_code, m.assessment_type, s.usn""")
    return _csv(rows, ["usn", "course_code", "assessment_type", "value", "max_marks", "version", "updated_at"], "marks.csv")


@router.get("/api/export/ledger.csv")
def export_ledger(request: Request, course_id: int | None = None):
    sql = """SELECT r.course_id, r.seq, r.mark_id, r.old_value, r.new_value, r.changed_by, r.reason, r.changed_at, r.request_id, r.prev_hash, r.row_hash
               FROM mark_revisions r"""
    params: tuple = ()
    if course_id is not None:
        sql += " WHERE r.course_id = %s"; params = (course_id,)
    with app_conn(uid(request)) as conn:
        rows = fetchall(conn, sql + " ORDER BY r.course_id, r.seq", params)
    return _csv(rows, ["course_id", "seq", "mark_id", "old_value", "new_value", "changed_by", "reason", "changed_at", "request_id", "prev_hash", "row_hash"], "ledger.csv")


# ------------------------------------------------------------------ bulk import through apply_change()
@router.post("/api/marks/import")
async def import_marks(request: Request, file: UploadFile = File(...)):
    """CSV columns: usn, course_code, assessment_type, value, reason. Each row goes through apply_change() as the signed-in
    user in its own transaction, so one bad row never blocks the rest and every accepted row is chained in the ledger."""
    user = uid(request)
    me = me_row(request)
    if me["role"] == "student":
        raise HTTPException(403, "faculty only")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    need = {"usn", "course_code", "assessment_type", "value", "reason"}
    if not reader.fieldnames or not need <= {h.strip().lower() for h in reader.fieldnames}:
        raise HTTPException(400, "CSV needs the columns: usn, course_code, assessment_type, value, reason")
    results, ok = [], 0
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_IMPORT_ROWS:
            results.append({"line": n, "ok": False, "error": f"stopped after {MAX_IMPORT_ROWS} rows"}); break
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        try:
            value = float(row["value"])
            with app_conn(user) as conn:
                m = fetchone(conn, """SELECT m.mark_id, m.version FROM marks m JOIN students s ON s.user_id = m.student_id
                                       JOIN courses c ON c.course_id = m.course_id
                                      WHERE s.usn = %s AND c.course_code = %s AND m.assessment_type = %s""",
                             (row["usn"], row["course_code"], row["assessment_type"]))
                if not m:
                    raise ValueError("no such mark (check usn / course / assessment, and that the mark is visible to you)")
                rid = fetchone(conn, "SELECT apply_change(%s::int, %s::numeric, %s::text, %s::int, NULL::int, %s::int) AS rid",
                               (m["mark_id"], value, row["reason"] or "bulk import", user, m["version"]))["rid"]
            results.append({"line": n, "ok": True, "revision_id": rid}); ok += 1
        except Exception as e:
            results.append({"line": n, "ok": False, "error": pg_err(e)})
    return {"imported": ok, "failed": len(results) - ok, "results": results}


# ------------------------------------------------------------------ notifications
@router.get("/api/notifications")
def notifications(request: Request, unread: bool = False):
    with app_conn(uid(request)) as conn:
        rows = fetchall(conn, "SELECT notification_id, kind, message, link, created_at, read_at FROM notifications "
                              + ("WHERE read_at IS NULL " if unread else "") + "ORDER BY created_at DESC, notification_id DESC LIMIT 100")
        n = fetchone(conn, "SELECT count(*) AS n FROM notifications WHERE read_at IS NULL")["n"]
    return {"unread": n, "items": rows}


class ReadIn(BaseModel):
    ids: list[int] | None = None   # None = everything


@router.post("/api/notifications/read")
def mark_read(body: ReadIn, request: Request):
    with app_conn(uid(request)) as conn:
        if body.ids is None:
            execute(conn, "UPDATE notifications SET read_at = now() WHERE read_at IS NULL")
        else:
            execute(conn, "UPDATE notifications SET read_at = now() WHERE read_at IS NULL AND notification_id = ANY(%s)", (body.ids,))
    return {"ok": True}


# ------------------------------------------------------------------ selective disclosure of one revision
@router.get("/api/disclosure/{revision_id}")
def disclosure(revision_id: int, request: Request):
    """A self-contained proof that ONE ledger revision exists and was witnessed: the revision's own fields, its Merkle path
    to a sealed batch root, and the witness record that pins that root. Nothing about other marks is revealed
    (sibling hashes only). Verify offline with verify_disclosure.py."""
    with app_conn(uid(request)) as conn:                      # row-level security: you can only disclose what you can see
        rev = fetchone(conn, """SELECT r.revision_id, r.course_id, r.seq, r.mark_id, r.old_value, r.new_value, r.changed_by, r.reason,
                                       r.changed_at, to_char(r.changed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS changed_at_utc,
                                       r.prev_hash, r.row_hash FROM mark_revisions r WHERE r.revision_id = %s""", (revision_id,))
    if not rev:
        raise HTTPException(404, "revision not found or not visible to you")
    proof = integrity.merkle_proof(rev["course_id"], rev["seq"])
    if not proof:
        raise HTTPException(409, "this revision is not in a sealed batch yet; ask an admin to seal and anchor")
    w = integrity.witness()
    rec = None
    if hasattr(w, "records"):
        for r in w.records():
            p = r["payload"]
            if p["course_id"] == rev["course_id"] and p["seq_from"] <= rev["seq"] <= p["seq_to"]:
                rec = r
                break
    return {"version": 1,
            "revision": {k: (str(v) if k in ("old_value", "new_value") and v is not None else v) for k, v in rev.items()},
            "merkle": {"row_hash": proof["row_hash"], "path": proof["path"], "root": proof["merkle_root"], "batch_id": proof["batch_id"]},
            "witness": rec}
