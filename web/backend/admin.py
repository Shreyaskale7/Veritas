"""Administration API: people, courses, assessments, enrolment, audit log. Administrators only, confined to their own institution.

Reads come from the owner connection filtered by the administrator's institution (they need e-mail addresses, which the application
role may not read); every change goes through a SECURITY DEFINER database function that re-checks everything and logs the action.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from common import me_row, pg_err, uid
from db import admin_conn, app_conn, fetchall, fetchone

router = APIRouter(prefix="/api/admin")


def _admin(request: Request) -> dict:
    who = me_row(request)
    if who["role"] != "admin":
        raise HTTPException(403, "administrators only")
    return who


def temp_password() -> str:
    """A readable one-time password that satisfies the database rule (>= 10 characters, a letter and a digit)."""
    letters = string.ascii_letters
    chars = [secrets.choice(letters), secrets.choice(string.digits)] + [secrets.choice(letters + string.digits) for _ in range(10)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _call(user: int, sql: str, params: tuple):
    with app_conn(user) as conn:
        try:
            return fetchone(conn, sql, params)
        except Exception as e:
            raise HTTPException(400, pg_err(e)) from e


# ------------------------------------------------------------------------------ people
@router.get("/people")
def people(request: Request):
    inst = _admin(request)["institution_id"]
    with admin_conn() as conn:
        return fetchall(conn, """
            SELECT u.user_id, u.name, u.email, u.role, u.active, u.created_at,
                   s.usn, s.branch, s.semester, f.employee_id, f.department, f.can_approve,
                   coalesce(c.must_change, false) AS must_change
              FROM users u
              LEFT JOIN students s ON s.user_id = u.user_id
              LEFT JOIN faculty f ON f.user_id = u.user_id
              LEFT JOIN app_credentials c ON c.user_id = u.user_id
             WHERE u.institution_id = %s
             ORDER BY u.role, u.name""", (inst,))


class PersonIn(BaseModel):
    name: str = Field(min_length=1)
    email: str
    role: str
    password: str | None = None            # left empty, a temporary one is generated and shown once
    usn: str | None = None
    branch: str | None = None
    semester: int | None = None
    employee_id: str | None = None
    department: str | None = None
    can_approve: bool = False


@router.post("/people")
def create_person(body: PersonIn, request: Request):
    user = _admin(request)["user_id"]
    pw = body.password or temp_password()
    row = _call(user, "SELECT admin_create_user(%s::int, %s::text, %s::text, %s::text, %s::text, %s::text, %s::text, %s::int, %s::text, %s::text, %s::boolean) AS user_id",
                (user, body.name, body.email, body.role, pw, body.usn, body.branch, body.semester, body.employee_id, body.department, body.can_approve))
    return {"user_id": row["user_id"], "temporary_password": None if body.password else pw}


class ActiveIn(BaseModel):
    active: bool


@router.post("/people/{person_id}/active")
def set_active(person_id: int, body: ActiveIn, request: Request):
    user = _admin(request)["user_id"]
    _call(user, "SELECT admin_set_active(%s::int, %s::int, %s::boolean) AS ok", (user, person_id, body.active))
    return {"ok": True}


class ApproverIn(BaseModel):
    can_approve: bool


@router.post("/people/{person_id}/approver")
def set_approver(person_id: int, body: ApproverIn, request: Request):
    user = _admin(request)["user_id"]
    _call(user, "SELECT admin_set_can_approve(%s::int, %s::int, %s::boolean) AS ok", (user, person_id, body.can_approve))
    return {"ok": True}


class ResetIn(BaseModel):
    password: str | None = None


@router.post("/people/{person_id}/reset-password")
def reset_password(person_id: int, body: ResetIn, request: Request):
    user = _admin(request)["user_id"]
    pw = body.password or temp_password()
    _call(user, "SELECT admin_reset_password(%s::int, %s::int, %s::text) AS ok", (user, person_id, pw))
    return {"temporary_password": None if body.password else pw}


# ------------------------------------------------------------------------------ courses
@router.get("/courses")
def courses(request: Request):
    inst = _admin(request)["institution_id"]
    with admin_conn() as conn:
        cs = fetchall(conn, """
            SELECT c.course_id, c.course_code, c.title, c.credits, c.semester, c.faculty_id, u.name AS faculty_name,
                   (SELECT count(DISTINCT m.student_id) FROM marks m WHERE m.course_id = c.course_id) AS enrolled
              FROM courses c JOIN users u ON u.user_id = c.faculty_id
             WHERE c.institution_id = %s ORDER BY c.course_code, c.semester""", (inst,))
        ass = fetchall(conn, """
            SELECT a.course_id, a.type, a.max_marks, a.freeze_at, (a.freeze_at <= now()) AS frozen,
                   (SELECT count(*) FROM marks m WHERE m.course_id = a.course_id AND m.assessment_type = a.type AND m.current_value IS NOT NULL) AS marks_entered
              FROM assessments a JOIN courses c ON c.course_id = a.course_id WHERE c.institution_id = %s ORDER BY a.course_id, a.type""", (inst,))
        faculty = fetchall(conn, "SELECT user_id, name FROM users WHERE institution_id = %s AND role = 'faculty' AND active ORDER BY name", (inst,))
        students = fetchall(conn, "SELECT u.user_id, u.name, s.usn FROM users u JOIN students s ON s.user_id = u.user_id "
                                  "WHERE u.institution_id = %s AND u.active ORDER BY s.usn", (inst,))
        enrolled = fetchall(conn, "SELECT DISTINCT m.course_id, m.student_id FROM marks m JOIN courses c ON c.course_id = m.course_id WHERE c.institution_id = %s", (inst,))
    by_course = {}
    for a in ass:
        by_course.setdefault(a["course_id"], []).append(a)
    enr = {}
    for e in enrolled:
        enr.setdefault(e["course_id"], []).append(e["student_id"])
    for c in cs:
        c["assessments"] = by_course.get(c["course_id"], [])
        c["student_ids"] = enr.get(c["course_id"], [])
    return {"courses": cs, "faculty": faculty, "students": students}


class CourseIn(BaseModel):
    course_code: str
    title: str
    credits: int
    semester: int
    faculty_id: int


@router.post("/courses")
def create_course(body: CourseIn, request: Request):
    user = _admin(request)["user_id"]
    return _call(user, "SELECT admin_create_course(%s::int, %s::text, %s::text, %s::int, %s::int, %s::int) AS course_id",
                 (user, body.course_code, body.title, body.credits, body.semester, body.faculty_id))


class FacultyIn(BaseModel):
    faculty_id: int


@router.post("/courses/{course_id}/faculty")
def set_course_faculty(course_id: int, body: FacultyIn, request: Request):
    user = _admin(request)["user_id"]
    _call(user, "SELECT admin_set_course_faculty(%s::int, %s::int, %s::int) AS ok", (user, course_id, body.faculty_id))
    return {"ok": True}


class AssessmentIn(BaseModel):
    type: str
    max_marks: float
    freeze_at: datetime


@router.post("/courses/{course_id}/assessments")
def set_assessment(course_id: int, body: AssessmentIn, request: Request):
    user = _admin(request)["user_id"]
    _call(user, "SELECT admin_set_assessment(%s::int, %s::int, %s::text, %s::numeric, %s::timestamptz) AS ok",
          (user, course_id, body.type, body.max_marks, body.freeze_at))
    return {"ok": True}


class EnrollIn(BaseModel):
    student_ids: list[int]


@router.post("/courses/{course_id}/enroll")
def enroll(course_id: int, body: EnrollIn, request: Request):
    user = _admin(request)["user_id"]
    row = _call(user, "SELECT admin_enroll(%s::int, %s::int, %s::int[]) AS created", (user, course_id, body.student_ids))
    return {"marks_created": row["created"]}


# ------------------------------------------------------------------------------ audit log
@router.get("/log")
def log(request: Request):
    user = _admin(request)["user_id"]
    with app_conn(user) as conn:                  # row-level security: administrators see only their own institution's log
        return fetchall(conn, """
            SELECT a.action_id, a.at, a.action, a.detail, u.name AS admin_name
              FROM admin_actions a JOIN users u ON u.user_id = a.admin_id
             ORDER BY a.action_id DESC LIMIT 300""")
