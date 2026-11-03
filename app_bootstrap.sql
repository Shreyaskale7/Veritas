-- Application layer on top of schema.sql. Safe to re-run.
-- Demo password for every seed user: veritas2026

CREATE TABLE IF NOT EXISTS app_credentials (
  user_id        integer PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
  password_hash  text NOT NULL
);

INSERT INTO app_credentials (user_id, password_hash)
SELECT u.user_id, crypt('veritas2026', gen_salt('bf'))
  FROM users u
 WHERE NOT EXISTS (SELECT 1 FROM app_credentials c WHERE c.user_id = u.user_id);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veritas_login') THEN
    CREATE ROLE veritas_login LOGIN PASSWORD 'veritas' NOSUPERUSER;
  END IF;
END $$;
GRANT veritas_app TO veritas_login;

CREATE OR REPLACE FUNCTION review_alert(p_alert_id integer, p_status text, p_by integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  IF NOT (app_role() = 'admin' OR app_is_checker()) THEN
    RAISE EXCEPTION 'only a checker or admin can review alerts';
  END IF;
  IF p_status NOT IN ('confirmed','dismissed') THEN
    RAISE EXCEPTION 'status must be confirmed or dismissed';
  END IF;
  UPDATE anomaly_alerts
     SET status = p_status, reviewed_by = p_by, reviewed_at = now()
   WHERE alert_id = p_alert_id AND status = 'open';
  IF NOT FOUND THEN RAISE EXCEPTION 'alert % is not open', p_alert_id; END IF;
END $$;

GRANT EXECUTE ON FUNCTION review_alert(integer, text, integer) TO veritas_app;

CREATE OR REPLACE FUNCTION record_anomaly_alert(
  p_revision_id bigint, p_model text, p_score real, p_features text)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO anomaly_alerts (revision_id, model_name, score, top_features)
  SELECT p_revision_id, p_model, p_score, p_features
   WHERE NOT EXISTS (
     SELECT 1 FROM anomaly_alerts a
      WHERE a.revision_id = p_revision_id AND a.model_name = p_model AND a.status = 'open')
  RETURNING alert_id
$$;
-- no grant to veritas_app: scorer uses the owner connection

-- =====================================================================
-- Application extensions (idempotent): institutions, notifications, run log,
-- stored certificate documents, login throttling.
-- =====================================================================

-- Institutions (foundation for multi-institution deployments; every existing row belongs to institution 1)
CREATE TABLE IF NOT EXISTS institutions (
  institution_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug            text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]+$'),
  name            text NOT NULL
);
INSERT INTO institutions (slug, name) SELECT 'rvce', 'RV College of Engineering'
 WHERE NOT EXISTS (SELECT 1 FROM institutions);
ALTER TABLE users   ADD COLUMN IF NOT EXISTS institution_id integer NOT NULL DEFAULT 1 REFERENCES institutions(institution_id);
ALTER TABLE courses ADD COLUMN IF NOT EXISTS institution_id integer NOT NULL DEFAULT 1 REFERENCES institutions(institution_id);
GRANT SELECT ON institutions TO veritas_app;
GRANT SELECT (institution_id) ON users TO veritas_app;      -- users has column-level grants; /api/me needs to know the caller's institution

-- Log of scheduled/manual integrity work (verify / seal / anchor / score). Owner connection only.
CREATE TABLE IF NOT EXISTS integrity_runs (
  run_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind        text        NOT NULL CHECK (kind IN ('verify','seal','anchor','score')),
  ok          boolean     NOT NULL,
  detail      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  started_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS integrity_runs_recent ON integrity_runs (started_at DESC);

-- In-app notifications
CREATE TABLE IF NOT EXISTS notifications (
  notification_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id          integer     NOT NULL REFERENCES users(user_id),
  kind             text        NOT NULL,
  message          text        NOT NULL,
  link             text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  read_at          timestamptz
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id, created_at DESC);
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS notifications_own ON notifications;
CREATE POLICY notifications_own ON notifications FOR SELECT TO veritas_app USING (user_id = app_user_id());
DROP POLICY IF EXISTS notifications_mark_read ON notifications;
CREATE POLICY notifications_mark_read ON notifications FOR UPDATE TO veritas_app
  USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
GRANT SELECT ON notifications TO veritas_app;
GRANT UPDATE (read_at) ON notifications TO veritas_app;

CREATE OR REPLACE FUNCTION notify_user(p_user integer, p_kind text, p_msg text, p_link text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO notifications (user_id, kind, message, link) VALUES (p_user, p_kind, p_msg, p_link)
$$;

-- Checkers and admins of ONE institution (the one the event belongs to) are told; other institutions never are.
DROP FUNCTION IF EXISTS notify_checkers(integer, text, text, text);
CREATE OR REPLACE FUNCTION notify_checkers(p_except integer, p_inst integer, p_kind text, p_msg text, p_link text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO notifications (user_id, kind, message, link)
  SELECT u.user_id, p_kind, p_msg, p_link
    FROM users u
   WHERE u.user_id IS DISTINCT FROM p_except
     AND u.institution_id = p_inst
     AND (u.role = 'admin' OR EXISTS (SELECT 1 FROM faculty f WHERE f.user_id = u.user_id AND f.can_approve))
$$;

CREATE OR REPLACE FUNCTION trg_notify_request() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
DECLARE d text; inst integer;
BEGIN
  SELECT format('%s %s (%s)', c.course_code, m.assessment_type, s.usn), c.institution_id INTO d, inst
    FROM marks m JOIN courses c ON c.course_id = m.course_id JOIN students s ON s.user_id = m.student_id
   WHERE m.mark_id = NEW.mark_id;
  IF TG_OP = 'INSERT' THEN
    PERFORM notify_checkers(NEW.requested_by, inst, 'request_filed',
      format('Change request #%s awaits a decision: %s to %s', NEW.request_id, d, NEW.proposed_value), '/requests');
  ELSIF NEW.status IS DISTINCT FROM OLD.status AND NEW.status IN ('approved','rejected') THEN
    PERFORM notify_user(NEW.requested_by, 'request_' || NEW.status,
      format('Your change request #%s (%s) was %s', NEW.request_id, d, NEW.status), '/marks');
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS notify_request_ins ON change_requests;
CREATE TRIGGER notify_request_ins AFTER INSERT ON change_requests FOR EACH ROW EXECUTE FUNCTION trg_notify_request();
DROP TRIGGER IF EXISTS notify_request_upd ON change_requests;
CREATE TRIGGER notify_request_upd AFTER UPDATE OF status ON change_requests FOR EACH ROW EXECUTE FUNCTION trg_notify_request();

CREATE OR REPLACE FUNCTION trg_notify_revision() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
DECLARE d text; st integer;
BEGIN
  SELECT format('%s %s', c.course_code, m.assessment_type), m.student_id INTO d, st
    FROM marks m JOIN courses c ON c.course_id = m.course_id WHERE m.mark_id = NEW.mark_id;
  PERFORM notify_user(st, 'mark_changed',
    CASE WHEN NEW.old_value IS NULL THEN format('Your %s mark was entered: %s', d, NEW.new_value)
         ELSE format('Your %s mark changed from %s to %s', d, NEW.old_value, NEW.new_value) END, '/revisions');
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS notify_revision ON mark_revisions;
CREATE TRIGGER notify_revision AFTER INSERT ON mark_revisions FOR EACH ROW EXECUTE FUNCTION trg_notify_revision();

CREATE OR REPLACE FUNCTION trg_notify_alert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
DECLARE inst integer;
BEGIN
  SELECT c.institution_id INTO inst FROM mark_revisions r JOIN courses c ON c.course_id = r.course_id WHERE r.revision_id = NEW.revision_id;
  PERFORM notify_checkers(NULL, inst, 'alert', format('Anomaly alert #%s: revision %s scored %s', NEW.alert_id, NEW.revision_id, round(NEW.score::numeric, 2)), '/alerts');
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS notify_alert ON anomaly_alerts;
CREATE TRIGGER notify_alert AFTER INSERT ON anomaly_alerts FOR EACH ROW EXECUTE FUNCTION trg_notify_alert();

CREATE OR REPLACE FUNCTION trg_notify_cert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    PERFORM notify_user(NEW.student_id, 'certificate_issued', format('A %s certificate was issued to you', NEW.cert_type), '/certificates');
  ELSIF NEW.status = 'revoked' AND OLD.status <> 'revoked' THEN
    PERFORM notify_user(NEW.student_id, 'certificate_revoked', format('Your %s certificate was revoked', NEW.cert_type), '/certificates');
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS notify_cert_ins ON certificates;
CREATE TRIGGER notify_cert_ins AFTER INSERT ON certificates FOR EACH ROW EXECUTE FUNCTION trg_notify_cert();
DROP TRIGGER IF EXISTS notify_cert_upd ON certificates;
CREATE TRIGGER notify_cert_upd AFTER UPDATE OF status ON certificates FOR EACH ROW EXECUTE FUNCTION trg_notify_cert();

-- Stored certificate documents (PDF with QR). Written once by the issuer, never changed.
CREATE TABLE IF NOT EXISTS certificate_documents (
  cert_id     uuid PRIMARY KEY REFERENCES certificates(cert_id),
  mime        text        NOT NULL DEFAULT 'application/pdf',
  doc         bytea       NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS certificate_documents_guard ON certificate_documents;
CREATE TRIGGER certificate_documents_guard BEFORE UPDATE OR DELETE ON certificate_documents
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
ALTER TABLE certificate_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS certificate_documents_read ON certificate_documents;
CREATE POLICY certificate_documents_read ON certificate_documents FOR SELECT TO veritas_app
  USING (EXISTS (SELECT 1 FROM certificates c WHERE c.cert_id = certificate_documents.cert_id));
GRANT SELECT ON certificate_documents TO veritas_app;

CREATE OR REPLACE FUNCTION store_certificate_document(p_cert uuid, p_doc bytea, p_by integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  IF NOT EXISTS (SELECT 1 FROM certificates WHERE cert_id = p_cert AND issued_by = p_by) THEN
    RAISE EXCEPTION 'only the issuer can attach a document to certificate %', p_cert;
  END IF;
  INSERT INTO certificate_documents (cert_id, doc) VALUES (p_cert, p_doc);
END $$;
GRANT EXECUTE ON FUNCTION store_certificate_document(uuid, bytea, integer) TO veritas_app;

-- Login throttling (owner connection only)
CREATE TABLE IF NOT EXISTS login_attempts (
  attempt_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email       text        NOT NULL,
  ip          text,
  ok          boolean     NOT NULL,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS login_attempts_recent ON login_attempts (lower(email), at DESC);

-- =====================================================================
-- Multi-institution isolation. Every user and course carries an institution; an application user sees ONLY rows of their own
-- institution. RESTRICTIVE policies are AND-ed with the role-based policies above, so they can only remove access.
-- Owner connections (scheduler, verification) and the SECURITY DEFINER write functions are unaffected.
-- =====================================================================
CREATE OR REPLACE FUNCTION app_institution() RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
  SELECT institution_id FROM users WHERE user_id = app_user_id()
$$;
GRANT EXECUTE ON FUNCTION app_institution() TO veritas_app;

-- Institution lookups run as the table owner so the policies below never recurse through each other's row-level security.
CREATE OR REPLACE FUNCTION user_institution(p_user integer) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ SELECT institution_id FROM users WHERE user_id = p_user $$;
CREATE OR REPLACE FUNCTION course_institution(p_course integer) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ SELECT institution_id FROM courses WHERE course_id = p_course $$;
CREATE OR REPLACE FUNCTION mark_institution(p_mark integer) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ SELECT c.institution_id FROM marks m JOIN courses c ON c.course_id = m.course_id WHERE m.mark_id = p_mark $$;
CREATE OR REPLACE FUNCTION revision_institution(p_rev bigint) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ SELECT c.institution_id FROM mark_revisions r JOIN courses c ON c.course_id = r.course_id WHERE r.revision_id = p_rev $$;
CREATE OR REPLACE FUNCTION batch_institution(p_batch integer) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ SELECT c.institution_id FROM merkle_batches b JOIN courses c ON c.course_id = b.course_id WHERE b.batch_id = p_batch $$;
GRANT EXECUTE ON FUNCTION user_institution(integer), course_institution(integer), mark_institution(integer),
                          revision_institution(bigint), batch_institution(integer) TO veritas_app;

-- Tables that had no row-level security until now need a permissive base policy before the restrictive one can apply.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['faculty', 'courses', 'assessments', 'merkle_batches', 'anchors'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS base_read ON %I', t);
    EXECUTE format('CREATE POLICY base_read ON %I FOR SELECT TO veritas_app USING (true)', t);
  END LOOP;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
      ('users',            'institution_id = app_institution()'),
      ('courses',          'institution_id = app_institution()'),
      ('students',         'user_institution(user_id) = app_institution()'),
      ('faculty',          'user_institution(user_id) = app_institution()'),
      ('assessments',      'course_institution(course_id) = app_institution()'),
      ('marks',            'course_institution(course_id) = app_institution()'),
      ('mark_revisions',   'course_institution(course_id) = app_institution()'),
      ('merkle_batches',   'course_institution(course_id) = app_institution()'),
      ('change_requests',  'mark_institution(mark_id) = app_institution()'),
      ('certificates',     'user_institution(student_id) = app_institution()'),
      ('anomaly_alerts',   'revision_institution(revision_id) = app_institution()'),
      ('anchors',          'batch_institution(batch_id) = app_institution()')) AS v(t, cond) LOOP
    EXECUTE format('DROP POLICY IF EXISTS inst_%1$s ON %1$I', r.t);
    EXECUTE format('CREATE POLICY inst_%1$s ON %1$I AS RESTRICTIVE FOR SELECT TO veritas_app USING (%2$s)', r.t, r.cond);
  END LOOP;
END $$;

-- A course, its faculty member and its students must belong to the same institution (the database refuses mixed data).
CREATE OR REPLACE FUNCTION trg_same_institution() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a integer; b integer;
BEGIN
  IF TG_TABLE_NAME = 'courses' THEN
    SELECT institution_id INTO a FROM users WHERE user_id = NEW.faculty_id;
    IF NEW.institution_id IS DISTINCT FROM a THEN
      RAISE EXCEPTION 'course % belongs to institution % but its faculty member to %', NEW.course_code, NEW.institution_id, a;
    END IF;
  ELSE                                                    -- marks: the student must be of the course's institution
    SELECT institution_id INTO a FROM courses WHERE course_id = NEW.course_id;
    SELECT institution_id INTO b FROM users WHERE user_id = NEW.student_id;
    IF a IS DISTINCT FROM b THEN
      RAISE EXCEPTION 'student % (institution %) cannot hold marks of a course of institution %', NEW.student_id, b, a;
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS courses_same_institution ON courses;
CREATE TRIGGER courses_same_institution BEFORE INSERT OR UPDATE OF faculty_id, institution_id ON courses FOR EACH ROW EXECUTE FUNCTION trg_same_institution();
DROP TRIGGER IF EXISTS marks_same_institution ON marks;
CREATE TRIGGER marks_same_institution BEFORE INSERT ON marks FOR EACH ROW EXECUTE FUNCTION trg_same_institution();

-- =====================================================================
-- Administration and accounts: people, courses, assessments, enrolment, passwords, email preference, admin audit log.
-- Every change goes through a SECURITY DEFINER function that checks the caller (require_user), requires the administrator role,
-- is confined to the administrator's own institution, and writes an append-only audit row. No password is ever logged.
-- =====================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS active       boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notify boolean NOT NULL DEFAULT true;
ALTER TABLE app_credentials ADD COLUMN IF NOT EXISTS must_change boolean NOT NULL DEFAULT false;
ALTER TABLE notifications   ADD COLUMN IF NOT EXISTS emailed_at  timestamptz;
GRANT SELECT (active, email_notify) ON users TO veritas_app;

CREATE TABLE IF NOT EXISTS admin_actions (
  action_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admin_id        integer     NOT NULL REFERENCES users(user_id),
  institution_id  integer     NOT NULL REFERENCES institutions(institution_id),
  action          text        NOT NULL,
  detail          jsonb       NOT NULL DEFAULT '{}'::jsonb,
  at              timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS admin_actions_guard ON admin_actions;
CREATE TRIGGER admin_actions_guard BEFORE UPDATE OR DELETE ON admin_actions FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
DROP TRIGGER IF EXISTS admin_actions_guard_t ON admin_actions;
CREATE TRIGGER admin_actions_guard_t BEFORE TRUNCATE ON admin_actions FOR EACH STATEMENT EXECUTE FUNCTION trg_block_modify();
ALTER TABLE admin_actions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS admin_actions_read ON admin_actions;
CREATE POLICY admin_actions_read ON admin_actions FOR SELECT TO veritas_app
  USING (app_role() = 'admin' AND institution_id = app_institution());
GRANT SELECT ON admin_actions TO veritas_app;

-- Password rule shared by every way a password can be set.
CREATE OR REPLACE FUNCTION check_password(p text) RETURNS void LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p IS NULL OR length(p) < 10 THEN RAISE EXCEPTION 'password must be at least 10 characters'; END IF;
  IF p !~ '[A-Za-z]' OR p !~ '[0-9]' THEN RAISE EXCEPTION 'password must contain a letter and a digit'; END IF;
END $$;

-- The administrator's institution, or an exception. Inactive accounts never act.
CREATE OR REPLACE FUNCTION require_admin(p_by integer) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer;
BEGIN
  PERFORM require_user(p_by);
  SELECT institution_id INTO inst FROM users WHERE user_id = p_by AND role = 'admin' AND active;
  IF inst IS NULL THEN RAISE EXCEPTION 'administrators only'; END IF;
  RETURN inst;
END $$;

CREATE OR REPLACE FUNCTION admin_log(p_by integer, p_inst integer, p_action text, p_detail jsonb)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO admin_actions (admin_id, institution_id, action, detail) VALUES (p_by, p_inst, p_action, coalesce(p_detail, '{}'::jsonb))
$$;

-- a person of the caller's institution, or an exception (other institutions are indistinguishable from "no such user")
CREATE OR REPLACE FUNCTION admin_target(p_inst integer, p_user integer) RETURNS users LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE u users%ROWTYPE;
BEGIN
  SELECT * INTO u FROM users WHERE user_id = p_user AND institution_id = p_inst;
  IF NOT FOUND THEN RAISE EXCEPTION 'no such person in your institution'; END IF;
  RETURN u;
END $$;

CREATE OR REPLACE FUNCTION admin_create_user(p_by integer, p_name text, p_email text, p_role text, p_password text,
    p_usn text DEFAULT NULL, p_branch text DEFAULT NULL, p_semester integer DEFAULT NULL,
    p_employee_id text DEFAULT NULL, p_department text DEFAULT NULL, p_can_approve boolean DEFAULT false)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; uid integer;
BEGIN
  inst := require_admin(p_by);
  IF coalesce(btrim(p_name), '') = '' THEN RAISE EXCEPTION 'name is required'; END IF;
  IF p_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' THEN RAISE EXCEPTION 'a valid e-mail address is required'; END IF;
  IF p_role NOT IN ('student', 'faculty', 'admin') THEN RAISE EXCEPTION 'role must be student, faculty or admin'; END IF;
  PERFORM check_password(p_password);
  IF p_role = 'student' AND (coalesce(p_usn, '') = '' OR coalesce(p_branch, '') = '' OR p_semester IS NULL) THEN
    RAISE EXCEPTION 'a student needs usn, branch and semester'; END IF;
  IF p_role = 'faculty' AND (coalesce(p_employee_id, '') = '' OR coalesce(p_department, '') = '') THEN
    RAISE EXCEPTION 'faculty need an employee id and a department'; END IF;
  BEGIN
    INSERT INTO users (name, email, role, institution_id) VALUES (btrim(p_name), lower(btrim(p_email)), p_role, inst) RETURNING user_id INTO uid;
    IF p_role = 'student' THEN INSERT INTO students (user_id, usn, branch, semester) VALUES (uid, btrim(p_usn), p_branch, p_semester);
    ELSIF p_role = 'faculty' THEN INSERT INTO faculty (user_id, employee_id, department, can_approve) VALUES (uid, btrim(p_employee_id), p_department, coalesce(p_can_approve, false));
    END IF;
  EXCEPTION WHEN unique_violation THEN
    RAISE EXCEPTION 'that e-mail, USN or employee id is already registered';
  WHEN check_violation THEN
    RAISE EXCEPTION 'a value is out of range (semester must be 1-8)';
  END;
  INSERT INTO app_credentials (user_id, password_hash, must_change) VALUES (uid, crypt(p_password, gen_salt('bf')), true);
  PERFORM admin_log(p_by, inst, 'create_user', jsonb_build_object('user_id', uid, 'email', lower(btrim(p_email)), 'role', p_role));
  RETURN uid;
END $$;

CREATE OR REPLACE FUNCTION admin_set_active(p_by integer, p_user integer, p_active boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; t users%ROWTYPE;
BEGIN
  inst := require_admin(p_by);
  t := admin_target(inst, p_user);
  IF NOT p_active AND p_user = p_by THEN RAISE EXCEPTION 'you cannot deactivate your own account'; END IF;
  IF NOT p_active AND t.role = 'admin' AND NOT EXISTS (SELECT 1 FROM users WHERE institution_id = inst AND role = 'admin' AND active AND user_id <> p_user) THEN
    RAISE EXCEPTION 'the last active administrator cannot be deactivated'; END IF;
  UPDATE users SET active = p_active WHERE user_id = p_user;
  PERFORM admin_log(p_by, inst, CASE WHEN p_active THEN 'activate_user' ELSE 'deactivate_user' END, jsonb_build_object('user_id', p_user));
END $$;

CREATE OR REPLACE FUNCTION admin_set_can_approve(p_by integer, p_user integer, p_flag boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; t users%ROWTYPE;
BEGIN
  inst := require_admin(p_by);
  t := admin_target(inst, p_user);
  IF t.role <> 'faculty' THEN RAISE EXCEPTION 'only faculty can be approvers'; END IF;
  UPDATE faculty SET can_approve = p_flag WHERE user_id = p_user;
  PERFORM admin_log(p_by, inst, 'set_can_approve', jsonb_build_object('user_id', p_user, 'can_approve', p_flag));
END $$;

CREATE OR REPLACE FUNCTION admin_reset_password(p_by integer, p_user integer, p_new text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer;
BEGIN
  inst := require_admin(p_by);
  PERFORM admin_target(inst, p_user);
  PERFORM check_password(p_new);
  INSERT INTO app_credentials (user_id, password_hash, must_change) VALUES (p_user, crypt(p_new, gen_salt('bf')), true)
  ON CONFLICT (user_id) DO UPDATE SET password_hash = EXCLUDED.password_hash, must_change = true;
  PERFORM admin_log(p_by, inst, 'reset_password', jsonb_build_object('user_id', p_user));
END $$;

-- Any signed-in user changes their own password; the old one must be right, the new one must obey the rule and differ.
CREATE OR REPLACE FUNCTION change_password(p_by integer, p_old text, p_new text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  IF NOT EXISTS (SELECT 1 FROM app_credentials WHERE user_id = p_by AND password_hash = crypt(p_old, password_hash)) THEN
    RAISE EXCEPTION 'the current password is wrong'; END IF;
  PERFORM check_password(p_new);
  IF p_new = p_old THEN RAISE EXCEPTION 'the new password must differ from the old one'; END IF;
  UPDATE app_credentials SET password_hash = crypt(p_new, gen_salt('bf')), must_change = false WHERE user_id = p_by;
END $$;

CREATE OR REPLACE FUNCTION set_email_notify(p_by integer, p_flag boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  UPDATE users SET email_notify = p_flag WHERE user_id = p_by;
END $$;

CREATE OR REPLACE FUNCTION admin_create_course(p_by integer, p_code text, p_title text, p_credits integer, p_semester integer, p_faculty integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; t users%ROWTYPE; cid integer;
BEGIN
  inst := require_admin(p_by);
  t := admin_target(inst, p_faculty);
  IF t.role <> 'faculty' OR NOT t.active THEN RAISE EXCEPTION 'the course needs an active faculty member'; END IF;
  IF coalesce(btrim(p_code), '') = '' OR coalesce(btrim(p_title), '') = '' THEN RAISE EXCEPTION 'course code and title are required'; END IF;
  BEGIN
    INSERT INTO courses (course_code, title, credits, semester, faculty_id, institution_id)
    VALUES (btrim(p_code), btrim(p_title), p_credits, p_semester, p_faculty, inst) RETURNING course_id INTO cid;
  EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION 'course % already exists for semester %', p_code, p_semester;
            WHEN check_violation THEN RAISE EXCEPTION 'credits must be 1-6 and semester 1-8';
  END;
  PERFORM admin_log(p_by, inst, 'create_course', jsonb_build_object('course_id', cid, 'code', btrim(p_code), 'faculty_id', p_faculty));
  RETURN cid;
END $$;

CREATE OR REPLACE FUNCTION admin_set_course_faculty(p_by integer, p_course integer, p_faculty integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; t users%ROWTYPE; old integer;
BEGIN
  inst := require_admin(p_by);
  SELECT faculty_id INTO old FROM courses WHERE course_id = p_course AND institution_id = inst;
  IF NOT FOUND THEN RAISE EXCEPTION 'no such course in your institution'; END IF;
  t := admin_target(inst, p_faculty);
  IF t.role <> 'faculty' OR NOT t.active THEN RAISE EXCEPTION 'the course needs an active faculty member'; END IF;
  UPDATE courses SET faculty_id = p_faculty WHERE course_id = p_course;
  PERFORM admin_log(p_by, inst, 'set_course_faculty', jsonb_build_object('course_id', p_course, 'from', old, 'to', p_faculty));
END $$;

-- Creates or updates one assessment of a course (max marks and freeze time). Past marks must still fit the new maximum.
CREATE OR REPLACE FUNCTION admin_set_assessment(p_by integer, p_course integer, p_type text, p_max numeric, p_freeze timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; old assessments%ROWTYPE;
BEGIN
  inst := require_admin(p_by);
  IF NOT EXISTS (SELECT 1 FROM courses WHERE course_id = p_course AND institution_id = inst) THEN RAISE EXCEPTION 'no such course in your institution'; END IF;
  IF p_type NOT IN ('CIE-1', 'CIE-2', 'SEE') THEN RAISE EXCEPTION 'assessment type must be CIE-1, CIE-2 or SEE'; END IF;
  IF p_max IS NULL OR p_max <= 0 OR p_freeze IS NULL THEN RAISE EXCEPTION 'max marks (> 0) and a freeze time are required'; END IF;
  SELECT * INTO old FROM assessments WHERE course_id = p_course AND type = p_type;
  IF FOUND AND EXISTS (SELECT 1 FROM marks WHERE course_id = p_course AND assessment_type = p_type AND current_value > p_max) THEN
    RAISE EXCEPTION 'existing marks exceed the new maximum of %', p_max; END IF;
  INSERT INTO assessments (course_id, type, max_marks, freeze_at) VALUES (p_course, p_type, p_max, p_freeze)
  ON CONFLICT (course_id, type) DO UPDATE SET max_marks = EXCLUDED.max_marks, freeze_at = EXCLUDED.freeze_at;
  PERFORM admin_log(p_by, inst, CASE WHEN old.course_id IS NULL THEN 'create_assessment' ELSE 'update_assessment' END,
    jsonb_build_object('course_id', p_course, 'type', p_type, 'max_marks', p_max, 'freeze_at', p_freeze,
                       'old_max_marks', old.max_marks, 'old_freeze_at', old.freeze_at));
END $$;

-- One empty mark per assessment for every listed student (already enrolled students are skipped). Returns the marks created.
CREATE OR REPLACE FUNCTION admin_enroll(p_by integer, p_course integer, p_students integer[])
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE inst integer; s integer; n integer := 0; k integer;
BEGIN
  inst := require_admin(p_by);
  IF NOT EXISTS (SELECT 1 FROM courses WHERE course_id = p_course AND institution_id = inst) THEN RAISE EXCEPTION 'no such course in your institution'; END IF;
  IF NOT EXISTS (SELECT 1 FROM assessments WHERE course_id = p_course) THEN RAISE EXCEPTION 'add at least one assessment before enrolling students'; END IF;
  FOREACH s IN ARRAY coalesce(p_students, ARRAY[]::integer[]) LOOP
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = s AND institution_id = inst AND role = 'student' AND active) THEN
      RAISE EXCEPTION 'student % is not an active student of your institution', s; END IF;
    INSERT INTO marks (student_id, course_id, assessment_type)
    SELECT s, p_course, a.type FROM assessments a WHERE a.course_id = p_course
    ON CONFLICT (student_id, course_id, assessment_type) DO NOTHING;
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  END LOOP;
  PERFORM admin_log(p_by, inst, 'enroll', jsonb_build_object('course_id', p_course, 'students', p_students, 'marks_created', n));
  RETURN n;
END $$;

GRANT EXECUTE ON FUNCTION admin_create_user(integer, text, text, text, text, text, text, integer, text, text, boolean),
  admin_set_active(integer, integer, boolean), admin_set_can_approve(integer, integer, boolean), admin_reset_password(integer, integer, text),
  change_password(integer, text, text), set_email_notify(integer, boolean), admin_create_course(integer, text, text, integer, integer, integer),
  admin_set_course_faculty(integer, integer, integer), admin_set_assessment(integer, integer, text, numeric, timestamptz),
  admin_enroll(integer, integer, integer[]) TO veritas_app;
