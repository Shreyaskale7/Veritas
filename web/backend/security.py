"""Login throttling (persisted, so a restart does not reset it) and CSRF protection for the JSON API."""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request

from db import admin_conn, execute, fetchone

MAX_FAILS = int(os.environ.get("LOGIN_MAX_FAILS", "5"))          # per account within the window
MAX_FAILS_IP = int(os.environ.get("LOGIN_MAX_FAILS_IP", "30"))   # per client address within the window
WINDOW_MIN = int(os.environ.get("LOGIN_LOCK_MINUTES", "15"))
CSRF_EXEMPT = {"/api/login", "/api/verify-certificate"}          # no session yet / public read-only check


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def check_login_allowed(email: str, ip: str) -> None:
    """Locks an account after MAX_FAILS failures since its last success; locks an address on MAX_FAILS_IP."""
    with admin_conn() as conn:
        by_email = fetchone(conn, """
            SELECT count(*) AS n FROM login_attempts
             WHERE lower(email) = lower(%s) AND NOT ok AND at > now() - make_interval(mins => %s)
               AND at > coalesce((SELECT max(at) FROM login_attempts WHERE lower(email) = lower(%s) AND ok), '-infinity')""",
                            (email, WINDOW_MIN, email))["n"]
        by_ip = fetchone(conn, "SELECT count(*) AS n FROM login_attempts WHERE ip = %s AND NOT ok AND at > now() - make_interval(mins => %s)",
                         (ip, WINDOW_MIN))["n"]
    if by_email >= MAX_FAILS or by_ip >= MAX_FAILS_IP:
        raise HTTPException(429, f"too many failed sign-ins; try again in {WINDOW_MIN} minutes")


def record_login(email: str, ip: str, ok: bool) -> None:
    with admin_conn() as conn:
        execute(conn, "INSERT INTO login_attempts (email, ip, ok) VALUES (%s, %s, %s)", (email.strip().lower(), ip, ok))


def new_csrf(request: Request) -> str:
    token = request.session.get("csrf") or secrets.token_urlsafe(24)
    request.session["csrf"] = token
    return token


async def csrf_guard(request: Request) -> None:
    """Global dependency: state-changing calls from a signed-in session must echo the session's CSRF token."""
    if request.method in ("GET", "HEAD", "OPTIONS") or request.url.path in CSRF_EXEMPT:
        return
    if not request.session.get("user_id"):
        return                                   # not signed in: the endpoint itself answers 401
    sent, want = request.headers.get("x-csrf-token"), request.session.get("csrf")
    if not want or not sent or not secrets.compare_digest(sent, want):
        raise HTTPException(403, "missing or invalid CSRF token")
