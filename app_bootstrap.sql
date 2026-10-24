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
