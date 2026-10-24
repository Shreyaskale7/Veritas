"""Certificates and transcripts: PDF with a scan-to-verify QR code, stored write-once next to the certificate."""
from __future__ import annotations

import hashlib
import io
import os
import textwrap
from datetime import datetime

import qrcode
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from common import me_row, pg_err, uid
from db import admin_conn, app_conn, fetchall, fetchone

router = APIRouter()
PUBLIC_URL = os.environ.get("VERITAS_PUBLIC_URL", "http://127.0.0.1:5173")


def verify_link(cert_id: str, salt: str, digest: str) -> str:
    """What the QR code carries. The digest is a SHA-256 of the document, so it reveals nothing about the text."""
    return f"{PUBLIC_URL}/verify?p={cert_id}|{salt}|{digest}"


def _qr_image(text: str) -> ImageReader:
    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return ImageReader(buf)


def render_pdf(*, cert_id, salt, digest, cert_type, student, usn, issuer, issued_at, content) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFillColor(colors.HexColor("#070b14")); c.rect(0, h - 90, w, 90, stroke=0, fill=1)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 26); c.drawString(40, h - 55, "VERITAS")
    c.setFont("Helvetica", 11); c.setFillColor(colors.HexColor("#8892b0"))
    c.drawString(40, h - 75, "Tamper-evident academic ledger  |  RV College of Engineering")
    c.setFillColor(colors.HexColor("#6366f1")); c.setFont("Helvetica-Bold", 18); c.drawString(40, h - 135, cert_type.upper())
    c.setFillColor(colors.black); c.setFont("Helvetica", 11)
    c.drawString(40, h - 160, f"Issued to: {student} ({usn})")
    c.drawString(40, h - 176, f"Issued by: {issuer}   on {issued_at:%d %b %Y, %H:%M}")
    y = h - 215
    c.setFont("Courier", 10)
    for line in content.splitlines():
        for part in (textwrap.wrap(line, 92) or [""]):
            if y < 250:
                c.showPage(); y = h - 60; c.setFont("Courier", 10)
            c.drawString(40, y, part); y -= 13
    y = min(y - 20, 240)
    c.drawImage(_qr_image(verify_link(cert_id, salt, digest)), 40, 60, 150, 150)
    c.setFont("Helvetica-Bold", 10); c.drawString(205, 195, "Scan to verify")
    c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#444444"))
    c.drawString(205, 180, "The check returns only: valid, revoked or unknown.")
    c.drawString(205, 166, f"Certificate ID: {cert_id}")
    c.drawString(205, 152, f"Document SHA-256: {digest[:32]}")
    c.drawString(205, 140, f"                 {digest[32:]}")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(205, 120, "A revoked or altered document no longer verifies, whatever it looks like on paper.")
    c.showPage(); c.save()
    return buf.getvalue()


def _person(conn, student_id):
    return fetchone(conn, "SELECT u.name, s.usn FROM users u JOIN students s ON s.user_id = u.user_id WHERE u.user_id = %s", (student_id,))


def _issue(conn, user, student_id, cert_type, content):
    """Issue through the database function, build the PDF and store it, all in the caller's transaction."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    row = fetchone(conn, "SELECT out_cert_id, out_salt FROM issue_certificate(%s::int, %s::text, %s::text, %s::int)", (student_id, cert_type, digest, user))
    cert_id, salt = str(row["out_cert_id"]), row["out_salt"]
    stu = _person(conn, student_id)
    me = fetchone(conn, "SELECT name FROM users WHERE user_id = %s", (user,))
    pdf = render_pdf(cert_id=cert_id, salt=salt, digest=digest, cert_type=cert_type, student=stu["name"], usn=stu["usn"],
                     issuer=me["name"], issued_at=datetime.now(), content=content)
    fetchone(conn, "SELECT store_certificate_document(%s::uuid, %s::bytea, %s::int) AS ok", (cert_id, pdf, user))
    return {"out_cert_id": cert_id, "out_salt": salt, "content_digest": digest, "verify_link": verify_link(cert_id, salt, digest)}


class CertIn(BaseModel):
    student_id: int
    cert_type: str
    content: str


class TranscriptIn(BaseModel):
    student_id: int


GP_SQL = """CASE WHEN 100*r.obtained/r.maximum >= 90 THEN 10 WHEN 100*r.obtained/r.maximum >= 80 THEN 9
                 WHEN 100*r.obtained/r.maximum >= 70 THEN 8  WHEN 100*r.obtained/r.maximum >= 60 THEN 7
                 WHEN 100*r.obtained/r.maximum >= 55 THEN 6  WHEN 100*r.obtained/r.maximum >= 50 THEN 5
                 WHEN 100*r.obtained/r.maximum >= 40 THEN 4 ELSE 0 END"""   # same scale as v_student_sgpa


def transcript_text(conn, student_id: int) -> str:
    stu = _person(conn, student_id)
    if not stu:
        raise HTTPException(404, "unknown student")
    rows = fetchall(conn, f"""SELECT r.semester, c.course_code, c.title, r.credits, r.obtained, r.maximum, {GP_SQL} AS gp
                               FROM v_course_result r JOIN courses c ON c.course_id = r.course_id
                              WHERE r.student_id = %s ORDER BY r.semester, c.course_code""", (student_id,))
    if not rows:
        raise HTTPException(400, "no completed courses yet: every assessment of a course must have a mark")
    sg = {r["semester"]: r["sgpa"] for r in fetchall(conn, "SELECT semester, sgpa FROM v_student_sgpa WHERE student_id = %s", (student_id,))}
    out = [f"OFFICIAL TRANSCRIPT", f"Student: {stu['name']} ({stu['usn']})", ""]
    for sem in sorted({r["semester"] for r in rows}):
        out.append(f"Semester {sem}   SGPA {sg.get(sem)}")
        for r in rows:
            if r["semester"] == sem:
                out.append(f"  {r['course_code']:<9}{r['title'][:34]:<36}{r['credits']} cr  {r['obtained']:>6}/{r['maximum']:<6} GP {r['gp']}")
        out.append("")
    out.append("Grade scale: simplified assumption, not the official RVCE scheme.")
    return "\n".join(out)


@router.post("/api/certificates")
def issue_cert(body: CertIn, request: Request):
    user = uid(request)
    with app_conn(user) as conn:
        try:
            res = _issue(conn, user, body.student_id, body.cert_type, body.content)
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return {**res, "content": body.content}


@router.post("/api/transcripts")
def issue_transcript(body: TranscriptIn, request: Request):
    """Builds the transcript from the ledger's current marks and issues it as a certificate of type Transcript."""
    user = uid(request)
    if not me_row(request).get("can_approve"):
        raise HTTPException(403, "transcripts are issued by approving faculty (HOD)")
    with admin_conn() as oc:                    # the transcript covers every course, so read it with the owner connection
        same = fetchone(oc, "SELECT 1 AS ok FROM users WHERE user_id = %s AND institution_id = %s", (body.student_id, me_row(request)["institution_id"]))
        if not same:
            raise HTTPException(404, "unknown student")        # students of other institutions are invisible, not forbidden
        text = transcript_text(oc, body.student_id)
    with app_conn(user) as conn:
        try:
            res = _issue(conn, user, body.student_id, "Transcript", text)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    return {**res, "content": text}


@router.get("/api/certificates/{cert_id}/pdf")
def certificate_pdf(cert_id: str, request: Request):
    with app_conn(uid(request)) as conn:
        try:
            row = fetchone(conn, "SELECT doc FROM certificate_documents WHERE cert_id = %s::uuid", (cert_id,))
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e
    if not row:
        raise HTTPException(404, "no document stored for this certificate")
    return Response(bytes(row["doc"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="veritas-{cert_id[:8]}.pdf"'})
