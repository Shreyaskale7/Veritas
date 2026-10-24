"""(Re)builds veritas_demo and its template veritas_demo_tpl: base data + a second institution ('beta') with its own admin, HOD, student."""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def psql(db, sql=None, file=None):
    r = subprocess.run(["psql", "-d", db, "-qX", "-v", "ON_ERROR_STOP=1"] + (["-c", sql] if sql else ["-f", file]), capture_output=True, text=True, encoding="utf-8")
    if r.returncode: raise SystemExit(r.stderr)
for d in ("veritas_demo", "veritas_demo_tpl"): psql("postgres", f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
psql("postgres", "CREATE DATABASE veritas_demo")
for f in ("schema.sql", "seed.sql", "app_bootstrap.sql", "demo_data.sql"): psql("veritas_demo", file=os.path.join(ROOT, f))
psql("veritas_demo", "UPDATE assessments SET freeze_at = now() - interval '1 day' WHERE course_id = 2 AND type = 'CIE-1'")
psql("veritas_demo", """
INSERT INTO institutions (slug, name) VALUES ('beta', 'Beta Institute of Technology');
INSERT INTO users (name, email, role, institution_id) VALUES ('Beta Admin', 'admin@beta.example', 'admin', 2), ('Dr. Beta HOD', 'hod@beta.example', 'faculty', 2), ('Beta Student', 'stu@beta.example', 'student', 2);
INSERT INTO faculty (user_id, employee_id, department, can_approve) SELECT user_id, 'B-1', 'CSE', true FROM users WHERE email = 'hod@beta.example';
INSERT INTO students (user_id, usn, branch, semester) SELECT user_id, '1BT24CS001', 'CSE', 3 FROM users WHERE email = 'stu@beta.example';
INSERT INTO courses (course_code, title, credits, semester, faculty_id, institution_id) SELECT 'BT101', 'Beta Engineering Mathematics', 3, 3, user_id, 2 FROM users WHERE email = 'hod@beta.example';
INSERT INTO assessments (course_id, type, max_marks, freeze_at) SELECT course_id, 'CIE-1', 50, now() + interval '90 days' FROM courses WHERE course_code = 'BT101';
INSERT INTO marks (student_id, course_id, assessment_type) SELECT u.user_id, c.course_id, 'CIE-1' FROM users u, courses c WHERE u.email = 'stu@beta.example' AND c.course_code = 'BT101';
INSERT INTO app_credentials SELECT user_id, crypt('veritas2026', gen_salt('bf')) FROM users WHERE email LIKE '%@beta.example';
SELECT set_config('veritas.user_id', (SELECT user_id::text FROM users WHERE email = 'hod@beta.example'), false);
SELECT apply_change((SELECT mark_id FROM marks WHERE course_id = (SELECT course_id FROM courses WHERE course_code = 'BT101')), 44, 'beta entry', (SELECT user_id FROM users WHERE email = 'hod@beta.example'));
""")
psql("postgres", "CREATE DATABASE veritas_demo_tpl TEMPLATE veritas_demo")
print("demo database + template ready")
