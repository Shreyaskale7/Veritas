"""E-mail for notifications. Every in-app notification is also mailed when SMTP_HOST is set, unless the person opted out.

Runs from the scheduler. A notification is marked emailed only after the server accepted it, so a mail outage retries on the next
round; anything older than a day is never mailed (switching SMTP on does not flood people with history).
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from db import admin_conn, execute, fetchall

SUBJECTS = {
    "request_filed": "A change request needs your decision",
    "request_approved": "Your change request was approved",
    "request_rejected": "Your change request was rejected",
    "mark_changed": "A mark of yours was entered or changed",
    "alert": "Anomaly alert",
    "certificate_issued": "A certificate was issued to you",
    "certificate_revoked": "A certificate of yours was revoked",
    "integrity_failure": "Veritas integrity check failed",
}


def configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send_pending(limit: int = 50) -> int:
    """Mails the pending notifications; returns how many were sent."""
    if not configured():
        return 0
    with admin_conn() as conn:
        rows = fetchall(conn, """
            SELECT n.notification_id, n.kind, n.message, n.link, u.email, u.name
              FROM notifications n JOIN users u ON u.user_id = n.user_id
             WHERE n.emailed_at IS NULL AND u.email_notify AND u.active AND n.created_at > now() - interval '1 day'
             ORDER BY n.notification_id LIMIT %s""", (limit,))
    if not rows:
        return 0
    base = os.environ.get("VERITAS_PUBLIC_URL", "http://127.0.0.1:5173")
    sent = []
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "25")), timeout=15) as s:
        if os.environ.get("SMTP_USER"):
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        for r in rows:
            msg = EmailMessage()
            msg["Subject"] = "Veritas: " + SUBJECTS.get(r["kind"], "Notification")
            msg["From"] = os.environ.get("ALERT_EMAIL_FROM", "veritas@localhost")
            msg["To"] = r["email"]
            msg.set_content(f"Hello {r['name']},\n\n{r['message']}\n\n{base}{r['link'] or ''}\n\n"
                            "You can turn these e-mails off on your Account page.\n")
            try:
                s.send_message(msg)
                sent.append(r["notification_id"])
            except smtplib.SMTPException as e:           # leave it unmarked: tried again next round
                print("mail failed for", r["email"], e)
    if sent:
        with admin_conn() as conn:
            execute(conn, "UPDATE notifications SET emailed_at = now() WHERE notification_id = ANY(%s)", (sent,))
    return len(sent)
