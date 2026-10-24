-- =====================================================================
-- Tests for the application layer (app_bootstrap.sql): notifications + row-level security, stored certificate
-- documents, run-log / throttle privileges, institutions, and the checker-visibility policy on marks.
-- Run after schema.sql + seed.sql + app_bootstrap.sql, as the DBA role, on a database WITHOUT demo data.
-- =====================================================================
\set ON_ERROR_STOP on
\pset pager off
DROP SCHEMA IF EXISTS ta CASCADE;
CREATE SCHEMA ta;
CREATE TABLE ta.results (n serial, id text, descr text, ok boolean, detail text);
CREATE TABLE ta.state (k text PRIMARY KEY, v text);
CREATE FUNCTION ta.rec(p_id text, p_descr text, p_ok boolean, p_detail text DEFAULT NULL) RETURNS void
LANGUAGE sql AS $$ INSERT INTO ta.results(id, descr, ok, detail) VALUES (p_id, p_descr, coalesce(p_ok, false), p_detail) $$;

-- scalar query as an application user (role veritas_app, veritas.user_id = p_uid; NULL = anonymous)
CREATE FUNCTION ta.q_as(p_uid integer, p_sql text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE res text;
BEGIN
  PERFORM set_config('veritas.user_id', coalesce(p_uid::text, ''), true);
  EXECUTE 'SET LOCAL ROLE veritas_app';
  BEGIN EXECUTE p_sql INTO res;
  EXCEPTION WHEN OTHERS THEN
    EXECUTE 'RESET ROLE'; PERFORM set_config('veritas.user_id', '', true);
    RETURN format('ERROR[%s]: %s', SQLSTATE, SQLERRM);
  END;
  EXECUTE 'RESET ROLE'; PERFORM set_config('veritas.user_id', '', true);
  RETURN res;
END $$;
CREATE FUNCTION ta.try(p_sql text) RETURNS text LANGUAGE plpgsql AS $$
BEGIN EXECUTE p_sql; RETURN 'OK';
EXCEPTION WHEN OTHERS THEN RETURN format('ERROR[%s]: %s', SQLSTATE, SQLERRM); END $$;
CREATE FUNCTION ta.put(p_k text, p_v text) RETURNS void LANGUAGE sql AS $$ INSERT INTO ta.state VALUES (p_k, p_v) ON CONFLICT (k) DO UPDATE SET v = p_v $$;
CREATE FUNCTION ta.get(p_k text) RETURNS text LANGUAGE sql AS $$ SELECT v FROM ta.state WHERE k = p_k $$;

-- seed users: 1 admin, 2 rao, 3 iyer (teaches course 2), 4 hegde (checker), 5 asha, 6 bharat, 7 chitra
-- A. checker visibility, requests and notifications -------------------------------------------------------
DO $$
DECLARE m integer; rid text;
BEGIN
  SELECT m0.mark_id INTO m FROM marks m0 JOIN courses c USING (course_id) WHERE c.faculty_id = 3 AND m0.student_id = 5 ORDER BY m0.mark_id LIMIT 1;
  PERFORM ta.put('mark', m::text);
  PERFORM ta.rec('AX01', 'Before any request, a checker (HOD) sees only the marks of their own course',
    ta.q_as(4, 'select count(*) from marks where course_id not in (select course_id from courses where faculty_id = 4)')::int = 0
    AND ta.q_as(4, 'select count(*) from marks')::int > 0);

  rid := ta.q_as(3, format('select request_change(%s, 47, ''recheck outcome'', 3)::text', m));
  PERFORM ta.put('rid', rid);
  PERFORM ta.rec('AX02', 'A new change request notifies the checker and the admin, not the requester',
    (SELECT count(*) FROM notifications WHERE kind = 'request_filed' AND user_id IN (1, 4)) = 2
    AND NOT EXISTS (SELECT 1 FROM notifications WHERE kind = 'request_filed' AND user_id = 3), rid);

  PERFORM ta.rec('AX03', 'Once a request exists the checker also sees that one mark, and no other foreign mark',
    ta.q_as(4, 'select count(*) from marks where course_id not in (select course_id from courses where faculty_id = 4)')::int = 1
    AND ta.q_as(4, 'select mark_id::text from marks where course_id not in (select course_id from courses where faculty_id = 4)') = m::text);

  PERFORM ta.q_as(4, format('select decide_request(%s, true, 4)::text', rid));
  PERFORM ta.rec('AX04', 'Approving the request notifies the requester',
    (SELECT count(*) FROM notifications WHERE kind = 'request_approved' AND user_id = 3) = 1);

  PERFORM set_config('veritas.user_id', '3', true);   -- seal the maker's identity for require_user()
  PERFORM ta.q_as(3, format('select apply_change(%s, 47, ''approved recheck'', 3, %s, NULL)::text', m, rid));
  PERFORM ta.rec('AX05', 'Applying a mark notifies exactly the student concerned',
    (SELECT count(*) FROM notifications WHERE kind = 'mark_changed' AND user_id = 5) = 1
    AND (SELECT count(*) FROM notifications WHERE kind = 'mark_changed' AND user_id <> 5) = 0);

  PERFORM ta.rec('AX06', 'A user sees only their own notifications',
    ta.q_as(5, 'select count(*) from notifications where user_id <> 5')::int = 0 AND ta.q_as(5, 'select count(*) from notifications')::int = 1);
  PERFORM ta.rec('AX07', 'A user may mark their own notification read, but cannot rewrite its text or touch anyone else''s',
    ta.q_as(5, 'with u as (update notifications set read_at = now() where user_id = 5 returning 1) select count(*)::text from u') = '1'
    AND ta.q_as(5, 'update notifications set message = ''x'' where user_id = 5') LIKE 'ERROR[42501]%'
    AND ta.q_as(5, 'with u as (update notifications set read_at = now() where user_id <> 5 returning 1) select count(*)::text from u') = '0');
END $$;

-- B. certificates: notifications and write-once documents ----------------------------------------------------
DO $$
DECLARE cid text; doc bytea := '\x255044462d312e340a'::bytea; by_other text; by_issuer text;
BEGIN
  cid := ta.q_as(4, 'select out_cert_id::text from issue_certificate(5, ''Bonafide'', repeat(''ab'', 32), 4)');
  PERFORM ta.put('cert', cid);
  PERFORM ta.rec('AX08', 'Issuing a certificate notifies the student', (SELECT count(*) FROM notifications WHERE kind = 'certificate_issued' AND user_id = 5) = 1, cid);

  by_other  := ta.q_as(3, format('select store_certificate_document(%L::uuid, %L::bytea, 3)::text', cid, doc));
  by_issuer := ta.q_as(4, format('select store_certificate_document(%L::uuid, %L::bytea, 4)::text', cid, doc));
  PERFORM ta.rec('AX09', 'Only the issuer can attach a document to a certificate',
    by_other LIKE 'ERROR%only the issuer%' AND by_issuer NOT LIKE 'ERROR%' AND (SELECT count(*) FROM certificate_documents) = 1, by_other || ' / ' || by_issuer);
  PERFORM ta.rec('AX10', 'A document can be attached once and never changed or removed (even by the owner)',
    ta.q_as(4, format('select store_certificate_document(%L::uuid, %L::bytea, 4)::text', cid, doc)) LIKE 'ERROR%'
    AND ta.try('UPDATE certificate_documents SET doc = ''\x00''::bytea') LIKE 'ERROR%append-only%'
    AND ta.try('DELETE FROM certificate_documents') LIKE 'ERROR%append-only%');
  PERFORM ta.rec('AX11', 'The student can read their own certificate document; another student sees none',
    ta.q_as(5, 'select count(*) from certificate_documents')::int = 1 AND ta.q_as(6, 'select count(*) from certificate_documents')::int = 0
    AND ta.q_as(NULL, 'select count(*) from certificate_documents')::int = 0);

  PERFORM ta.q_as(4, format('select revoke_certificate(%L::uuid, 4)::text', cid));
  PERFORM ta.rec('AX12', 'Revoking a certificate notifies the student', (SELECT count(*) FROM notifications WHERE kind = 'certificate_revoked' AND user_id = 5) = 1);
END $$;

-- C. anomaly alerts notify checkers and admins -------------------------------------------------------------
DO $$
DECLARE rev bigint;
BEGIN
  SELECT revision_id INTO rev FROM mark_revisions ORDER BY revision_id LIMIT 1;
  PERFORM record_anomaly_alert(rev, 'test-model', 0.9, '{}');
  PERFORM ta.rec('AX13', 'A new anomaly alert notifies the checker and the admin',
    (SELECT count(*) FROM notifications WHERE kind = 'alert' AND user_id IN (1, 4)) = 2 AND (SELECT count(*) FROM notifications WHERE kind = 'alert' AND user_id NOT IN (1, 4)) = 0);
END $$;

-- D. privileges of operational tables --------------------------------------------------------------------
DO $$ BEGIN
  PERFORM ta.rec('AX14', 'The application role cannot read or write the run log or the login-attempt table',
    ta.q_as(1, 'select count(*) from integrity_runs') LIKE 'ERROR[42501]%' AND ta.q_as(1, 'select count(*) from login_attempts') LIKE 'ERROR[42501]%'
    AND ta.q_as(1, 'insert into integrity_runs(kind, ok) values (''verify'', true)') LIKE 'ERROR[42501]%');
  PERFORM ta.rec('AX15', 'The run log only accepts known job kinds', ta.try('INSERT INTO integrity_runs(kind, ok) VALUES (''whatever'', true)') LIKE 'ERROR[23514]%');
END $$;

-- E. institutions -------------------------------------------------------------------------------------------
DO $$ BEGIN
  PERFORM ta.rec('AX16', 'Every user and course belongs to the default institution',
    (SELECT count(*) FROM users WHERE institution_id <> 1) = 0 AND (SELECT count(*) FROM courses WHERE institution_id <> 1) = 0 AND (SELECT count(*) FROM institutions) = 1);
  PERFORM ta.rec('AX17', 'An institution slug must be lower-case letters, digits and dashes', ta.try('INSERT INTO institutions(slug, name) VALUES (''Bad Slug'', ''x'')') LIKE 'ERROR[23514]%');
END $$;

-- F. a second institution is fully isolated from the first -----------------------------------------------------
DO $$
DECLARE i2 integer; a2 integer; f2 integer; s2 integer; c2 integer; m2 integer; cert2 text; err text;
BEGIN
  INSERT INTO institutions (slug, name) VALUES ('beta', 'Beta Institute') RETURNING institution_id INTO i2;
  INSERT INTO users (name, email, role, institution_id) VALUES ('Beta Admin', 'admin@beta.example', 'admin', i2) RETURNING user_id INTO a2;
  INSERT INTO users (name, email, role, institution_id) VALUES ('Beta HOD', 'hod@beta.example', 'faculty', i2) RETURNING user_id INTO f2;
  INSERT INTO users (name, email, role, institution_id) VALUES ('Beta Student', 'stu@beta.example', 'student', i2) RETURNING user_id INTO s2;
  INSERT INTO faculty (user_id, employee_id, department, can_approve) VALUES (f2, 'B-1', 'CSE', true);
  INSERT INTO students (user_id, usn, branch, semester) VALUES (s2, '1BT24CS001', 'CSE', 3);
  INSERT INTO courses (course_code, title, credits, semester, faculty_id, institution_id) VALUES ('BT101', 'Beta Course', 3, 3, f2, i2) RETURNING course_id INTO c2;
  INSERT INTO assessments (course_id, type, max_marks, freeze_at) VALUES (c2, 'CIE-1', 50, now() + interval '30 days');
  INSERT INTO marks (student_id, course_id, assessment_type) VALUES (s2, c2, 'CIE-1') RETURNING mark_id INTO m2;
  PERFORM ta.q_as(f2, format('select apply_change(%s, 44, ''beta entry'', %s)::text', m2, f2));
  PERFORM ta.q_as(f2, format('select request_change(%s, 45, ''beta recheck'', %s)::text', m2, f2));
  cert2 := ta.q_as(f2, format('select out_cert_id::text from issue_certificate(%s, ''Bonafide'', repeat(''cd'', 32), %s)', s2, f2));

  PERFORM ta.rec('AX18', 'An admin of institution 1 sees no user, student, course, mark or revision of institution 2',
    ta.q_as(1, format('select count(*) from users where user_id in (%s, %s, %s)', a2, f2, s2))::int = 0 AND ta.q_as(1, format('select count(*) from students where user_id = %s', s2))::int = 0
    AND ta.q_as(1, format('select count(*) from courses where course_id = %s', c2))::int = 0 AND ta.q_as(1, format('select count(*) from marks where mark_id = %s', m2))::int = 0
    AND ta.q_as(1, format('select count(*) from mark_revisions where course_id = %s', c2))::int = 0
    AND ta.q_as(1, format('select count(*) from assessments where course_id = %s', c2))::int = 0 AND ta.q_as(1, format('select count(*) from faculty where user_id = %s', f2))::int = 0);
  PERFORM ta.rec('AX19', 'An admin of institution 2 sees only institution 2, and sees all of it',
    ta.q_as(a2, 'select count(*) from users where user_id <= 7')::int = 0
    AND ta.q_as(a2, 'select count(*) from users')::int = 3 AND ta.q_as(a2, 'select count(*) from marks')::int = 1
    AND ta.q_as(a2, 'select count(*) from courses')::int = 1 AND ta.q_as(a2, 'select count(*) from mark_revisions')::int = 1);
  PERFORM ta.rec('AX20', 'Change requests, certificates and certificate documents do not cross institutions',
    ta.q_as(4, format('select count(*) from change_requests where mark_id = %s', m2))::int = 0
    AND ta.q_as(5, format('select count(*) from certificates where student_id = %s', s2))::int = 0
    AND ta.q_as(1, format('select count(*) from certificates where student_id = %s', s2))::int = 0
    AND ta.q_as(s2, 'select count(*) from certificates')::int = 1 AND ta.q_as(f2, 'select count(*) from change_requests')::int = 1);
  PERFORM ta.rec('AX21', 'Notifications about institution 2 reach only institution 2 (the other institution''s checkers hear nothing)',
    (SELECT count(*) FROM notifications WHERE user_id IN (1, 4) AND message LIKE '%BT101%') = 0
    AND (SELECT count(*) FROM notifications WHERE user_id = a2 AND kind = 'request_filed') = 1
    AND (SELECT count(*) FROM notifications WHERE user_id = s2 AND kind = 'mark_changed') = 1
    AND (SELECT count(*) FROM notifications WHERE user_id = 5 AND message LIKE '%BT101%') = 0);
  err := ta.try(format('INSERT INTO courses (course_code, title, credits, semester, faculty_id, institution_id) VALUES (''XX1'', ''Mixed'', 3, 3, 3, %s)', i2));
  PERFORM ta.rec('AX22', 'A course cannot be given a faculty member from another institution', err LIKE 'ERROR%belongs to institution%', err);
  err := ta.try(format('INSERT INTO marks (student_id, course_id, assessment_type) VALUES (5, %s, ''CIE-1'')', c2));
  PERFORM ta.rec('AX23', 'A student cannot hold marks of a course from another institution', err LIKE 'ERROR%cannot hold marks%', err);
  PERFORM ta.rec('AX24', 'Institution 1 is unaffected: its own users still see their data',
    ta.q_as(5, 'select count(*) from marks')::int > 0 AND ta.q_as(1, 'select count(*) from users')::int = 7 AND ta.q_as(4, 'select count(*) from marks')::int > 0);
END $$;

-- G. the base ledger is still clean after all of the above (the app layer never touched it) -------------------
DO $$ BEGIN
  PERFORM ta.rec('AX25', 'All chains still verify after the application-layer activity',
    (SELECT bool_and(chain_ok AND marks_ok AND batches_ok) FROM verify_all_chains()));
END $$;

\echo
\echo ===== APP-LAYER RESULTS =====
SELECT id, CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS result, descr, CASE WHEN ok THEN '' ELSE detail END AS detail FROM ta.results ORDER BY n;
SELECT count(*) FILTER (WHERE ok) AS passed, count(*) FILTER (WHERE NOT ok) AS failed, count(*) AS total FROM ta.results;
