"""Helpers shared by main.py and the feature routers."""
from __future__ import annotations

from fastapi import HTTPException, Request

from db import app_conn, fetchone


def uid(request: Request) -> int:
    user = request.session.get("user_id")
    if not user:
        raise HTTPException(401, "sign in required")
    return int(user)


def me_row(request: Request):
    with app_conn(uid(request)) as conn:
        row = fetchone(
            conn,
            """
            SELECT u.user_id, u.name, u.role, u.institution_id,
                   s.usn, s.branch, s.semester,
                   f.employee_id, f.department, f.can_approve
              FROM users u
              LEFT JOIN students s ON s.user_id = u.user_id
              LEFT JOIN faculty f ON f.user_id = u.user_id
             WHERE u.user_id = %s
            """,
            (uid(request),),
        )
    if not row:
        raise HTTPException(401, "unknown user")
    return row


def pg_err(e: Exception) -> str:
    return str(e).split("CONTEXT:")[0].strip()
