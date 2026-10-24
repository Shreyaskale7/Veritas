from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import anchor_service as A  # noqa: E402
import certs  # noqa: E402
import features  # noqa: E402
import integrity  # noqa: E402
import scheduler  # noqa: E402
from anomaly import score_revisions  # noqa: E402
from common import me_row, pg_err, uid  # noqa: E402
from db import admin_conn, app_conn, execute, fetchall, fetchone  # noqa: E402
from security import check_login_allowed, client_ip, csrf_guard, new_csrf, record_login  # noqa: E402

app = FastAPI(title="Veritas", dependencies=[Depends(csrf_guard)])
# No hardcoded fallback secret: without SESSION_SECRET a random one is used, so sessions end when the API restarts.
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax",
                   https_only=os.environ.get("SESSION_HTTPS") == "1")  # set SESSION_HTTPS=1 behind TLS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(certs.router)
app.include_router(features.router)


@app.on_event("startup")
def _start_background_jobs():
    scheduler.start()


class LoginIn(BaseModel):
    email: str
    password: str


class ApplyIn(BaseModel):
    new_value: float
    reason: str = Field(min_length=5)
    expected_version: int | None = None
    request_id: int | None = None


class RequestIn(BaseModel):
    mark_id: int
    proposed_value: float
    reason: str = Field(min_length=5)


class DecideIn(BaseModel):
    approve: bool


class VerifyIn(BaseModel):
    cert_id: str
    salt: str
    content: str | None = None          # the full text, or ...
    content_digest: str | None = None   # ... just its SHA-256 (what the QR code carries)


class ReviewIn(BaseModel):
    status: str


def _admin_only(request: Request):
    who = me_row(request)
    if who["role"] != "admin":
        raise HTTPException(403, "admin only")
    return who


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    ip = client_ip(request)
    check_login_allowed(body.email, ip)
    with admin_conn() as conn:
        row = fetchone(
            conn,
            """
            SELECT u.user_id, u.name, u.role
              FROM users u
              JOIN app_credentials c ON c.user_id = u.user_id
             WHERE lower(u.email) = lower(%s)
               AND c.password_hash = crypt(%s, c.password_hash)
            """,
            (body.email.strip(), body.password),
        )
    record_login(body.email, ip, bool(row))
    if not row:
        raise HTTPException(401, "invalid email or password")
    request.session.clear()
    request.session["user_id"] = row["user_id"]
    return {**row, "csrf": new_csrf(request)}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return {**me_row(request), "csrf": new_csrf(request)}


@app.get("/api/marks")
def marks(request: Request):
    with app_conn(uid(request)) as conn:
        return fetchall(
            conn,
            """
            SELECT m.mark_id, m.student_id, st.usn, st.user_id AS student_user,
                   u.name AS student_name, m.course_id, c.course_code, c.title,
                   m.assessment_type, m.current_value, a.max_marks, m.version,
                   m.updated_at, a.freeze_at, (now() >= a.freeze_at) AS frozen,
                   c.faculty_id
              FROM marks m
              JOIN students st ON st.user_id = m.student_id
              JOIN users u ON u.user_id = st.user_id
              JOIN courses c ON c.course_id = m.course_id
              JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type
             ORDER BY c.course_code, m.assessment_type, st.usn
            """,
        )


@app.get("/api/sgpa")
def sgpa(request: Request):
    with app_conn(uid(request)) as conn:
        return fetchall(conn, "SELECT student_id, semester, sgpa FROM v_student_sgpa ORDER BY semester")


@app.get("/api/revisions")
def revisions(request: Request, course_id: int | None = None):
    sql = """
      SELECT r.revision_id, r.course_id, r.seq, r.mark_id, r.old_value, r.new_value,
             r.reason, r.changed_by, r.changed_at, r.request_id, r.row_hash, r.prev_hash
        FROM mark_revisions r
    """
    params: tuple = ()
    if course_id is not None:
        sql += " WHERE r.course_id = %s"
        params = (course_id,)
    sql += " ORDER BY r.course_id, r.seq"
    with app_conn(uid(request)) as conn:
        return fetchall(conn, sql, params)


@app.post("/api/marks/{mark_id}/apply")
def apply_mark(mark_id: int, body: ApplyIn, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            row = fetchone(
                conn,
                "SELECT apply_change(%s::int, %s::numeric, %s::text, %s::int, %s::int, %s::int) AS revision_id",
                (mark_id, body.new_value, body.reason, user, body.request_id, body.expected_version),
            )
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return row


@app.get("/api/requests")
def list_requests(request: Request):
    with app_conn(uid(request)) as conn:
        return fetchall(
            conn,
            """
            SELECT cr.*, m.student_id, m.course_id, m.assessment_type, m.current_value
              FROM change_requests cr
              JOIN marks m ON m.mark_id = cr.mark_id
             ORDER BY cr.requested_at DESC
            """,
        )


@app.post("/api/requests")
def create_request(body: RequestIn, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            row = fetchone(
                conn,
                "SELECT request_change(%s::int, %s::numeric, %s::text, %s::int) AS request_id",
                (body.mark_id, body.proposed_value, body.reason, user),
            )
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return row


@app.post("/api/requests/{request_id}/decide")
def decide(request_id: int, body: DecideIn, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            execute(conn, "SELECT decide_request(%s::int, %s::boolean, %s::int)", (request_id, body.approve, user))
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return {"ok": True}


@app.get("/api/certificates")
def certificates(request: Request):
    with app_conn(uid(request)) as conn:
        return fetchall(
            conn,
            """
            SELECT c.cert_id, c.student_id, c.issued_by, c.cert_type, c.status, c.issued_at, c.revoked_at, c.salt,
                   EXISTS (SELECT 1 FROM certificate_documents d WHERE d.cert_id = c.cert_id) AS has_pdf
              FROM certificates c
             ORDER BY c.issued_at DESC
            """,
        )


@app.post("/api/certificates/{cert_id}/revoke")
def revoke_cert(cert_id: str, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            execute(conn, "SELECT revoke_certificate(%s::uuid, %s::int)", (cert_id, user))
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return {"ok": True}


@app.post("/api/verify-certificate")
def verify_cert_public(body: VerifyIn):
    if body.content_digest:
        digest = body.content_digest.strip().lower()
    elif body.content is not None:
        digest = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
    else:
        raise HTTPException(400, "send the certificate content or its content_digest")
    with app_conn(None) as conn:
        try:
            row = fetchone(
                conn,
                "SELECT verify_certificate(%s::uuid, %s::text, %s::text) AS status",
                (body.cert_id, body.salt, digest),
            )
        except Exception:                                   # malformed id: nothing to verify
            return {"status": "unknown", "content_digest": digest}
    return {"status": row["status"] if row else "unknown", "content_digest": digest}


# ------------------------------------------------------------------------ integrity (admin)
@app.get("/api/integrity")
def integrity_view(request: Request):
    inst = _admin_only(request)["institution_id"]               # an admin sees only their own institution
    with admin_conn() as conn:
        slug = fetchone(conn, "SELECT slug FROM institutions WHERE institution_id = %s", (inst,))["slug"]
        courses = fetchall(conn, "SELECT course_id, course_code, title FROM courses WHERE institution_id = %s ORDER BY course_id", (inst,))
        batches = fetchall(
            conn,
            "SELECT b.batch_id, b.course_id, b.seq_from, b.seq_to, b.merkle_root, b.created_at FROM merkle_batches b "
            "JOIN courses c ON c.course_id = b.course_id WHERE c.institution_id = %s ORDER BY b.batch_id", (inst,),
        )
        anchors = fetchall(conn, "SELECT a.* FROM anchors a JOIN merkle_batches b ON b.batch_id = a.batch_id "
                                 "JOIN courses c ON c.course_id = b.course_id WHERE c.institution_id = %s ORDER BY a.anchor_id", (inst,))
    res = integrity.verify_all(record=False, institution_id=inst)
    return {"chains": res["chains"], "courses": courses, "batches": batches, "anchors": anchors,
            "witness_ok": res["witness_ok"], "witness_message": res["witness_message"],
            "witness_problems": res["witness_problems"],
            "witness_type": integrity.witness().kind, "runs": integrity.recent_runs(8, slug),
            "scheduler": {n: e for n, (e, _) in scheduler.JOBS.items()} if os.environ.get("VERITAS_SCHEDULER", "1") != "0" else None}


@app.post("/api/integrity/verify")
def integrity_verify_now(request: Request):
    return integrity.verify_all(record=True, institution_id=_admin_only(request)["institution_id"])


@app.post("/api/seal/{course_id}")
def seal(course_id: int, request: Request):
    if not integrity.course_in_institution(course_id, _admin_only(request)["institution_id"]):
        raise HTTPException(404, "no such course in your institution")
    with admin_conn() as conn:
        try:
            row = fetchone(conn, "SELECT seal_batch(%s::int) AS batch_id", (course_id,))
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return row


@app.post("/api/anchor")
def anchor(request: Request):
    inst = _admin_only(request)["institution_id"]
    return {"anchored": integrity.anchor_all(institution_id=inst), "witness": integrity.witness().kind}


@app.get("/api/proof")
def proof(request: Request, course_id: int, seq: int):
    if not integrity.course_in_institution(course_id, _admin_only(request)["institution_id"]):
        raise HTTPException(404, "no such course in your institution")
    p = integrity.merkle_proof(course_id, seq)
    if not p:
        raise HTTPException(404, "revision is not in any sealed batch yet")
    w = integrity.witness()
    return {**p, "valid": A.check_proof(p, w) if hasattr(w, "records") else None}


# ------------------------------------------------------------------------ anomalies
@app.get("/api/alerts")
def alerts(request: Request):
    with app_conn(uid(request)) as conn:
        return fetchall(
            conn,
            """
            SELECT a.*, r.course_id, r.seq, r.mark_id, r.old_value, r.new_value, r.reason,
                   c.course_code, st.usn
              FROM anomaly_alerts a
              JOIN mark_revisions r ON r.revision_id = a.revision_id
              JOIN courses c ON c.course_id = r.course_id
              LEFT JOIN marks m ON m.mark_id = r.mark_id
              LEFT JOIN students st ON st.user_id = m.student_id
             ORDER BY a.created_at DESC
            """,
        )


@app.post("/api/alerts/{alert_id}/review")
def review(alert_id: int, body: ReviewIn, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            execute(conn, "SELECT review_alert(%s::int, %s::text, %s::int)", (alert_id, body.status, user))
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return {"ok": True}


@app.post("/api/anomalies/score")
def run_scorer(request: Request):
    who = me_row(request)
    if who["role"] != "admin" and not who.get("can_approve"):
        raise HTTPException(403, "checker or admin only")
    return score_revisions()


@app.get("/api/directory")
def directory(request: Request):
    who = me_row(request)
    if who["role"] == "student":
        raise HTTPException(403, "faculty and admin only")
    with admin_conn() as conn:
        students = fetchall(
            conn,
            "SELECT s.user_id, u.name, s.usn, s.branch, s.semester FROM students s JOIN users u ON u.user_id = s.user_id "
            "WHERE u.institution_id = %s ORDER BY s.usn", (who["institution_id"],),
        )
        courses = fetchall(
            conn,
            "SELECT course_id, course_code, title, credits, semester, faculty_id FROM courses WHERE institution_id = %s ORDER BY course_id",
            (who["institution_id"],),
        )
    return {"students": students, "courses": courses}
