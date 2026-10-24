-- =====================================================================
-- Veritas: tamper-evident marks and certificate ledger
-- DBMS (CD252IA), RV College of Engineering
-- Target: PostgreSQL 15+ (tested on 16.15). Run as the owner/DBA role.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veritas_app') THEN
    CREATE ROLE veritas_app NOLOGIN;      -- role the web/API layer connects as
  END IF;
END $$;

-- ---------------------------------------------------------------------
-- 1. Core tables
-- ---------------------------------------------------------------------

CREATE TABLE users (
  user_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL,
  email       text        NOT NULL UNIQUE,
  role        text        NOT NULL CHECK (role IN ('student','faculty','admin')),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE students (                       -- specialization of USERS
  user_id   integer  PRIMARY KEY REFERENCES users(user_id),
  usn       text     NOT NULL UNIQUE,
  branch    text     NOT NULL,
  semester  smallint NOT NULL CHECK (semester BETWEEN 1 AND 8)
);

CREATE TABLE faculty (                        -- specialization of USERS
  user_id      integer PRIMARY KEY REFERENCES users(user_id),
  employee_id  text    NOT NULL UNIQUE,
  department   text    NOT NULL,
  can_approve  boolean NOT NULL DEFAULT false   -- may act as checker (e.g. HOD)
);

CREATE TABLE courses (
  course_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  course_code  text     NOT NULL,
  title        text     NOT NULL,
  credits      smallint NOT NULL CHECK (credits BETWEEN 1 AND 6),
  semester     smallint NOT NULL CHECK (semester BETWEEN 1 AND 8),
  faculty_id   integer  NOT NULL REFERENCES faculty(user_id),
  UNIQUE (course_code, semester)
);

CREATE TABLE assessments (                    -- weak entity of COURSES
  course_id   integer       NOT NULL REFERENCES courses(course_id),
  type        text          NOT NULL CHECK (type IN ('CIE-1','CIE-2','SEE')),
  max_marks   numeric(5,2)  NOT NULL CHECK (max_marks > 0),
  freeze_at   timestamptz   NOT NULL,
  PRIMARY KEY (course_id, type)
);

CREATE TABLE marks (                          -- associative entity STUDENTS x ASSESSMENTS
  mark_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id       integer      NOT NULL REFERENCES students(user_id),
  course_id        integer      NOT NULL,
  assessment_type  text         NOT NULL,
  current_value    numeric(5,2) CHECK (current_value >= 0),
  version          integer      NOT NULL DEFAULT 0,
  updated_at       timestamptz,
  FOREIGN KEY (course_id, assessment_type) REFERENCES assessments(course_id, type),
  UNIQUE (student_id, course_id, assessment_type)
);

CREATE TABLE change_requests (
  request_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  mark_id         integer      NOT NULL REFERENCES marks(mark_id),
  requested_by    integer      NOT NULL REFERENCES faculty(user_id),
  approved_by     integer      REFERENCES faculty(user_id),   -- the deciding checker (also set on rejection)
  proposed_value  numeric(5,2) NOT NULL CHECK (proposed_value >= 0),
  reason          text         NOT NULL CHECK (length(btrim(reason)) >= 5),
  status          text         NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected','applied')),
  requested_at    timestamptz  NOT NULL DEFAULT now(),
  decided_at      timestamptz,
  CONSTRAINT checker_differs CHECK (approved_by IS NULL OR approved_by <> requested_by),
  CONSTRAINT decision_complete CHECK (
    (status = 'pending'  AND approved_by IS NULL     AND decided_at IS NULL) OR
    (status <> 'pending' AND approved_by IS NOT NULL AND decided_at IS NOT NULL))
);

CREATE TABLE mark_revisions (                 -- append-only, hash-chained per course
  revision_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  mark_id           integer      NOT NULL REFERENCES marks(mark_id),
  course_id         integer      NOT NULL REFERENCES courses(course_id),  -- chain key (controlled denormalisation)
  seq               integer      NOT NULL CHECK (seq >= 1),
  request_id        integer      REFERENCES change_requests(request_id),
  prev_revision_id  bigint       REFERENCES mark_revisions(revision_id),  -- recursive link
  old_value         numeric(5,2),
  new_value         numeric(5,2) NOT NULL,
  changed_by        integer      NOT NULL REFERENCES faculty(user_id),
  reason            text         NOT NULL,
  changed_at        timestamptz  NOT NULL,
  prev_hash         char(64)     NOT NULL,
  row_hash          char(64)     NOT NULL,
  UNIQUE (course_id, seq)
);
CREATE UNIQUE INDEX mark_revisions_request_once ON mark_revisions(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX mark_revisions_mark_idx ON mark_revisions(mark_id);

CREATE TABLE merkle_batches (
  batch_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  course_id    integer     NOT NULL REFERENCES courses(course_id),
  seq_from     integer     NOT NULL,
  seq_to       integer     NOT NULL,
  merkle_root  char(64)    NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (seq_to >= seq_from),
  UNIQUE (course_id, seq_from)
);

CREATE TABLE anchors (
  anchor_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_id     integer     NOT NULL REFERENCES merkle_batches(batch_id),
  anchor_type  text        NOT NULL CHECK (anchor_type IN ('immudb','git','file')),
  anchor_ref   text        NOT NULL,
  anchored_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE certificates (
  cert_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id  integer     NOT NULL REFERENCES students(user_id),
  issued_by   integer     NOT NULL REFERENCES faculty(user_id),
  cert_type   text        NOT NULL,
  doc_hash    char(64)    NOT NULL,        -- sha256(salt || content digest)
  salt        char(32)    NOT NULL,
  status      text        NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','revoked')),
  issued_at   timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz,
  CHECK ((status = 'valid') = (revoked_at IS NULL))
);

CREATE TABLE anomaly_alerts (
  alert_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  revision_id  bigint      NOT NULL REFERENCES mark_revisions(revision_id),
  reviewed_by  integer     REFERENCES faculty(user_id),
  model_name   text        NOT NULL,
  score        real        NOT NULL,
  top_features text,
  status       text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','confirmed','dismissed')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  reviewed_at  timestamptz
);

CREATE INDEX marks_student_idx          ON marks(student_id);
CREATE INDEX change_requests_mark_idx   ON change_requests(mark_id);
CREATE INDEX anomaly_alerts_revision_idx ON anomaly_alerts(revision_id);
CREATE INDEX anchors_batch_idx          ON anchors(batch_id);

-- ---------------------------------------------------------------------
-- 2. Helpers
-- ---------------------------------------------------------------------

-- Identity of the signed-in user, set by the API layer per transaction:
--   SELECT set_config('veritas.user_id', '<id>', true);
-- (On Supabase this would be derived from auth.uid().)
CREATE FUNCTION app_user_id() RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('veritas.user_id', true), '')::integer
$$;

CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
  SELECT role FROM users WHERE user_id = app_user_id()
$$;

CREATE FUNCTION app_is_checker() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = public, pg_temp AS $$
  SELECT coalesce((SELECT can_approve FROM faculty WHERE user_id = app_user_id()), false)
$$;

-- Canonical row hash. The input is a JSON array in a fixed field order, so a
-- free-text reason containing '|' or quotes cannot make two different rows
-- produce the same byte string. Timestamps are fixed-format UTC text.
CREATE FUNCTION compute_row_hash(p_prev text, p_seq integer, p_mark integer, p_course integer,
                                 p_old numeric, p_new numeric, p_by integer,
                                 p_reason text, p_at timestamptz)
RETURNS text LANGUAGE sql STABLE AS $$
  SELECT encode(digest(jsonb_build_array(
           p_prev, p_seq, p_mark, p_course,
           p_old::numeric(5,2)::text, p_new::numeric(5,2)::text,
           p_by, p_reason,
           to_char(p_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
         )::text, 'sha256'), 'hex')
$$;

CREATE FUNCTION genesis_hash(p_course integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest('veritas-genesis:' || p_course::text, 'sha256'), 'hex')
$$;

-- ---------------------------------------------------------------------
-- 3. Integrity triggers
-- ---------------------------------------------------------------------

-- 3a. Specialization is disjoint: row must match users.role
CREATE FUNCTION trg_check_role() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r text;
BEGIN
  SELECT role INTO r FROM users WHERE user_id = NEW.user_id;
  IF r IS DISTINCT FROM TG_ARGV[0] THEN
    RAISE EXCEPTION 'user % has role %, cannot be a %', NEW.user_id, r, TG_ARGV[0];
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER students_role BEFORE INSERT OR UPDATE ON students
  FOR EACH ROW EXECUTE FUNCTION trg_check_role('student');
CREATE TRIGGER faculty_role BEFORE INSERT OR UPDATE ON faculty
  FOR EACH ROW EXECUTE FUNCTION trg_check_role('faculty');

CREATE FUNCTION trg_users_role_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role <> OLD.role AND (EXISTS (SELECT 1 FROM students WHERE user_id = OLD.user_id)
                            OR EXISTS (SELECT 1 FROM faculty  WHERE user_id = OLD.user_id)) THEN
    RAISE EXCEPTION 'role of user % cannot change once specialised', OLD.user_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER users_role_fixed BEFORE UPDATE OF role ON users
  FOR EACH ROW EXECUTE FUNCTION trg_users_role_fixed();

-- 3b. Append-only tables
CREATE FUNCTION trg_block_modify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'table % is append-only (% blocked)', TG_TABLE_NAME, TG_OP;
END $$;
CREATE TRIGGER mark_revisions_guard BEFORE UPDATE OR DELETE ON mark_revisions
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER mark_revisions_guard_t BEFORE TRUNCATE ON mark_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER merkle_batches_guard BEFORE UPDATE OR DELETE ON merkle_batches
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER merkle_batches_guard_t BEFORE TRUNCATE ON merkle_batches
  FOR EACH STATEMENT EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER anchors_guard BEFORE UPDATE OR DELETE ON anchors
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER anchors_guard_t BEFORE TRUNCATE ON anchors
  FOR EACH STATEMENT EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER change_requests_nodelete BEFORE DELETE ON change_requests
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER marks_nodelete BEFORE DELETE ON marks
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();
CREATE TRIGGER certificates_nodelete BEFORE DELETE ON certificates
  FOR EACH ROW EXECUTE FUNCTION trg_block_modify();

-- 3c. MARKS.current_value may only change inside apply_change()
CREATE FUNCTION trg_marks_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.current_value IS DISTINCT FROM OLD.current_value
      OR NEW.version <> OLD.version
      OR NEW.student_id <> OLD.student_id
      OR NEW.course_id <> OLD.course_id
      OR NEW.assessment_type <> OLD.assessment_type)
     AND coalesce(current_setting('veritas.apply', true), '') <> 'on' THEN
    RAISE EXCEPTION 'marks may only be changed through apply_change()';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER marks_guard BEFORE UPDATE ON marks
  FOR EACH ROW EXECUTE FUNCTION trg_marks_guard();

-- 3d. Change requests: who may request, who may decide, allowed transitions
CREATE FUNCTION trg_cr_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fid integer; mx numeric; cur numeric;
BEGIN
  SELECT c.faculty_id, a.max_marks, m.current_value INTO fid, mx, cur
    FROM marks m
    JOIN courses c     ON c.course_id = m.course_id
    JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type
   WHERE m.mark_id = NEW.mark_id;
  IF fid IS DISTINCT FROM NEW.requested_by THEN
    RAISE EXCEPTION 'only the course faculty can request a change to this mark';
  END IF;
  IF NEW.status <> 'pending' THEN RAISE EXCEPTION 'new requests must be pending'; END IF;
  IF NEW.proposed_value > mx THEN
    RAISE EXCEPTION 'proposed value % exceeds max marks %', NEW.proposed_value, mx;
  END IF;
  IF NEW.proposed_value IS NOT DISTINCT FROM cur THEN
    RAISE EXCEPTION 'proposed value equals the current value';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER cr_insert BEFORE INSERT ON change_requests
  FOR EACH ROW EXECUTE FUNCTION trg_cr_insert();

CREATE FUNCTION trg_cr_update() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ok boolean;
BEGIN
  IF NEW.mark_id <> OLD.mark_id OR NEW.requested_by <> OLD.requested_by
     OR NEW.proposed_value <> OLD.proposed_value OR NEW.reason <> OLD.reason
     OR NEW.requested_at <> OLD.requested_at THEN
    RAISE EXCEPTION 'change request content is immutable';
  END IF;
  IF OLD.status <> 'pending'
     AND (NEW.approved_by IS DISTINCT FROM OLD.approved_by
          OR NEW.decided_at IS DISTINCT FROM OLD.decided_at) THEN
    RAISE EXCEPTION 'a decided request cannot be re-decided';
  END IF;
  IF NEW.status <> OLD.status THEN
    IF OLD.status = 'pending' AND NEW.status IN ('approved','rejected') THEN
      SELECT can_approve INTO ok FROM faculty WHERE user_id = NEW.approved_by;
      IF NOT coalesce(ok, false) THEN
        RAISE EXCEPTION 'faculty % is not allowed to approve', NEW.approved_by;
      END IF;
    ELSIF OLD.status = 'approved' AND NEW.status = 'applied' THEN
      IF coalesce(current_setting('veritas.apply', true), '') <> 'on' THEN
        RAISE EXCEPTION 'requests become applied only through apply_change()';
      END IF;
    ELSE
      RAISE EXCEPTION 'illegal status change % -> %', OLD.status, NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER cr_update BEFORE UPDATE ON change_requests
  FOR EACH ROW EXECUTE FUNCTION trg_cr_update();

-- 3e. THE CHAIN: every revision gets seq, links and hash from the database
CREATE FUNCTION trg_revision_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  c courses%ROWTYPE; m marks%ROWTYPE; a assessments%ROWTYPE;
  r change_requests%ROWTYPE; lr mark_revisions%ROWTYPE;
BEGIN
  -- Serialise writers of THIS course's chain. Other courses are not blocked.
  SELECT * INTO c FROM courses WHERE course_id = NEW.course_id FOR NO KEY UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown course %', NEW.course_id; END IF;

  SELECT * INTO m FROM marks WHERE mark_id = NEW.mark_id;
  IF NOT FOUND OR m.course_id <> NEW.course_id THEN
    RAISE EXCEPTION 'course_id % does not match mark %', NEW.course_id, NEW.mark_id;
  END IF;
  SELECT * INTO a FROM assessments WHERE course_id = m.course_id AND type = m.assessment_type;

  IF NEW.changed_by <> c.faculty_id THEN
    RAISE EXCEPTION 'only the course faculty (%) can write marks for course %', c.faculty_id, c.course_id;
  END IF;
  IF NEW.new_value < 0 OR NEW.new_value > a.max_marks THEN
    RAISE EXCEPTION 'value % outside 0..% for %', NEW.new_value, a.max_marks, a.type;
  END IF;

  -- Freeze rule and maker-checker rule
  IF now() >= a.freeze_at AND NEW.request_id IS NULL THEN
    RAISE EXCEPTION 'assessment is frozen: an approved change request is required';
  END IF;
  IF NEW.request_id IS NOT NULL THEN
    SELECT * INTO r FROM change_requests WHERE request_id = NEW.request_id FOR UPDATE;
    IF NOT FOUND OR r.mark_id <> NEW.mark_id OR r.status <> 'approved'
       OR r.proposed_value <> NEW.new_value OR r.requested_by <> NEW.changed_by THEN
      RAISE EXCEPTION 'change request % does not authorise this revision', NEW.request_id;
    END IF;
  END IF;

  NEW.old_value := m.current_value;

  SELECT * INTO lr FROM mark_revisions WHERE course_id = NEW.course_id ORDER BY seq DESC LIMIT 1;
  IF FOUND THEN
    NEW.seq := lr.seq + 1;  NEW.prev_revision_id := lr.revision_id;  NEW.prev_hash := lr.row_hash;
  ELSE
    NEW.seq := 1;           NEW.prev_revision_id := NULL;            NEW.prev_hash := genesis_hash(NEW.course_id);
  END IF;
  NEW.changed_at := clock_timestamp();
  NEW.row_hash := compute_row_hash(NEW.prev_hash, NEW.seq, NEW.mark_id, NEW.course_id,
                                   NEW.old_value, NEW.new_value, NEW.changed_by,
                                   NEW.reason, NEW.changed_at);
  RETURN NEW;
END $$;
CREATE TRIGGER revision_chain BEFORE INSERT ON mark_revisions
  FOR EACH ROW EXECUTE FUNCTION trg_revision_before_insert();

-- 3f. Certificates: only valid -> revoked, nothing else may change
CREATE FUNCTION trg_cert_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.cert_id <> OLD.cert_id OR NEW.student_id <> OLD.student_id OR NEW.issued_by <> OLD.issued_by
     OR NEW.cert_type <> OLD.cert_type OR NEW.doc_hash <> OLD.doc_hash OR NEW.salt <> OLD.salt
     OR NEW.issued_at <> OLD.issued_at THEN
    RAISE EXCEPTION 'certificate content is immutable';
  END IF;
  IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
    RAISE EXCEPTION 'a revoked certificate cannot be reinstated';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER cert_update BEFORE UPDATE ON certificates
  FOR EACH ROW EXECUTE FUNCTION trg_cert_update();

-- ---------------------------------------------------------------------
-- 4. Transactional write API (the only way the app role changes data)
-- ---------------------------------------------------------------------

CREATE FUNCTION require_user(p_by integer) RETURNS void LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF app_user_id() IS NULL OR app_user_id() <> p_by THEN
    RAISE EXCEPTION 'acting user % does not match the signed-in user %', p_by, app_user_id();
  END IF;
END $$;

-- Writes a mark. The revision (chain row) and the mark update commit together or not at all.
CREATE FUNCTION apply_change(p_mark_id integer, p_new numeric, p_reason text, p_by integer,
                             p_request_id integer DEFAULT NULL,
                             p_expected_version integer DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE m marks%ROWTYPE; rid bigint;
BEGIN
  PERFORM require_user(p_by);
  SELECT * INTO m FROM marks WHERE mark_id = p_mark_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown mark %', p_mark_id; END IF;
  IF p_expected_version IS NOT NULL AND m.version <> p_expected_version THEN
    RAISE EXCEPTION 'version conflict on mark %: expected %, found %', p_mark_id, p_expected_version, m.version
      USING ERRCODE = '40001';
  END IF;
  IF m.current_value IS NOT DISTINCT FROM p_new THEN
    RAISE EXCEPTION 'no change: mark % already has value %', p_mark_id, p_new;
  END IF;

  PERFORM set_config('veritas.apply', 'on', true);
  INSERT INTO mark_revisions (mark_id, course_id, request_id, new_value, changed_by, reason)
  VALUES (p_mark_id, m.course_id, p_request_id, p_new, p_by, p_reason)
  RETURNING revision_id INTO rid;
  UPDATE marks SET current_value = p_new, version = version + 1, updated_at = now()
   WHERE mark_id = p_mark_id;
  IF p_request_id IS NOT NULL THEN
    UPDATE change_requests SET status = 'applied' WHERE request_id = p_request_id;
  END IF;
  PERFORM set_config('veritas.apply', 'off', true);
  RETURN rid;
END $$;

CREATE FUNCTION request_change(p_mark_id integer, p_proposed numeric, p_reason text, p_by integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE rid integer;
BEGIN
  PERFORM require_user(p_by);
  INSERT INTO change_requests (mark_id, requested_by, proposed_value, reason)
  VALUES (p_mark_id, p_by, p_proposed, p_reason) RETURNING request_id INTO rid;
  RETURN rid;
END $$;

CREATE FUNCTION decide_request(p_request_id integer, p_approve boolean, p_by integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  UPDATE change_requests
     SET status = CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END,
         approved_by = p_by, decided_at = now()
   WHERE request_id = p_request_id AND status = 'pending';
  IF NOT FOUND THEN RAISE EXCEPTION 'request % is not pending', p_request_id; END IF;
END $$;

-- Certificates. content_digest = hex SHA-256 of the certificate document, computed by the caller.
-- Only sha256(salt || content_digest) is stored; the salt travels with the QR code.
CREATE FUNCTION issue_certificate(p_student_id integer, p_type text, p_content_digest text, p_by integer)
RETURNS TABLE (out_cert_id uuid, out_salt text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE s text; id uuid;
BEGIN
  PERFORM require_user(p_by);
  IF NOT EXISTS (SELECT 1 FROM faculty WHERE user_id = p_by) THEN
    RAISE EXCEPTION 'only faculty can issue certificates';
  END IF;
  s := encode(gen_random_bytes(16), 'hex');
  INSERT INTO certificates (student_id, issued_by, cert_type, doc_hash, salt)
  VALUES (p_student_id, p_by, p_type, encode(digest(s || p_content_digest, 'sha256'), 'hex'), s)
  RETURNING cert_id INTO id;
  RETURN QUERY SELECT id, s;
END $$;

CREATE FUNCTION revoke_certificate(p_cert_id uuid, p_by integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM require_user(p_by);
  IF NOT EXISTS (SELECT 1 FROM faculty WHERE user_id = p_by AND can_approve) THEN
    RAISE EXCEPTION 'only an approving faculty member can revoke certificates';
  END IF;
  UPDATE certificates SET status = 'revoked', revoked_at = now()
   WHERE cert_id = p_cert_id AND status = 'valid';
  IF NOT FOUND THEN RAISE EXCEPTION 'certificate % is not valid', p_cert_id; END IF;
END $$;

-- Public check: returns only 'valid', 'revoked' or 'unknown'. No personal data.
CREATE FUNCTION verify_certificate(p_cert_id uuid, p_salt text, p_content_digest text)
RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce((SELECT status FROM certificates
                    WHERE cert_id = p_cert_id
                      AND doc_hash = encode(digest(p_salt || p_content_digest, 'sha256'), 'hex')),
                  'unknown')
$$;

-- ---------------------------------------------------------------------
-- 5. Merkle batches
-- ---------------------------------------------------------------------

-- Leaf = sha256('L' || row_hash); inner node = sha256('N' || left || right) over hex text.
-- A node without a sibling is promoted unchanged. Prefixes stop a leaf being passed off as a node.
CREATE FUNCTION merkle_root(p_leaves text[]) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE lvl text[]; nxt text[]; i integer; n integer;
BEGIN
  IF p_leaves IS NULL OR cardinality(p_leaves) = 0 THEN
    RAISE EXCEPTION 'merkle_root needs at least one leaf';
  END IF;
  lvl := ARRAY(SELECT encode(digest('L' || x, 'sha256'), 'hex')
                 FROM unnest(p_leaves) WITH ORDINALITY AS t(x, o) ORDER BY o);
  WHILE cardinality(lvl) > 1 LOOP
    nxt := '{}'; n := cardinality(lvl); i := 1;
    WHILE i <= n LOOP
      IF i < n THEN nxt := nxt || encode(digest('N' || lvl[i] || lvl[i+1], 'sha256'), 'hex');
      ELSE          nxt := nxt || lvl[i];
      END IF;
      i := i + 2;
    END LOOP;
    lvl := nxt;
  END LOOP;
  RETURN lvl[1];
END $$;

-- 6. Verification (admin / scheduled job; not granted to the app role)

CREATE FUNCTION verify_chain(p_course_id integer)
RETURNS TABLE (ok boolean, checked_rows integer, bad_seq integer, problem text)
LANGUAGE plpgsql STABLE AS $$
DECLARE r mark_revisions%ROWTYPE; prev text; prev_id bigint; expect integer := 1; n integer := 0;
  lastv jsonb := '{}'::jsonb;   -- latest new_value seen per mark
BEGIN
  prev := genesis_hash(p_course_id);
  FOR r IN SELECT * FROM mark_revisions WHERE course_id = p_course_id ORDER BY seq LOOP
    IF r.seq <> expect THEN
      RETURN QUERY SELECT false, n, expect, format('sequence gap: expected %s, found %s', expect, r.seq); RETURN;
    ELSIF r.prev_hash <> prev THEN
      RETURN QUERY SELECT false, n, r.seq, 'prev_hash does not match the previous row'; RETURN;
    ELSIF r.prev_revision_id IS DISTINCT FROM prev_id THEN
      RETURN QUERY SELECT false, n, r.seq, 'prev_revision_id link is broken'; RETURN;
    ELSIF r.row_hash <> compute_row_hash(r.prev_hash, r.seq, r.mark_id, r.course_id, r.old_value,
                                         r.new_value, r.changed_by, r.reason, r.changed_at) THEN
      RETURN QUERY SELECT false, n, r.seq, 'row_hash does not match row content'; RETURN;
    ELSIF r.old_value::text IS DISTINCT FROM (lastv ->> r.mark_id::text) THEN
      RETURN QUERY SELECT false, n, r.seq, 'old_value does not continue from the previous revision of this mark'; RETURN;
    END IF;
    lastv := lastv || jsonb_build_object(r.mark_id::text, r.new_value::text);
    prev := r.row_hash; prev_id := r.revision_id; expect := expect + 1; n := n + 1;
  END LOOP;
  RETURN QUERY SELECT true, n, NULL::integer, NULL::text;
END $$;

-- Marks whose stored value disagrees with the latest revision (catches edits made straight to MARKS)
CREATE FUNCTION verify_marks_current(p_course_id integer)
RETURNS TABLE (bad_mark_id integer, stored_value numeric, ledger_value numeric)
LANGUAGE sql STABLE AS $$
  SELECT m.mark_id, m.current_value, lv.new_value
    FROM marks m
    LEFT JOIN LATERAL (SELECT r.new_value FROM mark_revisions r
                        WHERE r.mark_id = m.mark_id ORDER BY r.seq DESC LIMIT 1) lv ON true
   WHERE m.course_id = p_course_id
     AND m.current_value IS DISTINCT FROM lv.new_value
$$;

-- Batches whose stored root differs from the root recomputed from the chain
CREATE FUNCTION verify_batches(p_course_id integer)
RETURNS TABLE (bad_batch_id integer, stored_root text, recomputed_root text)
LANGUAGE sql STABLE AS $$
  SELECT b.batch_id, b.merkle_root::text, x.root
    FROM merkle_batches b
    CROSS JOIN LATERAL (
      SELECT CASE WHEN count(*) = b.seq_to - b.seq_from + 1
                  THEN merkle_root(array_agg(r.row_hash::text ORDER BY r.seq)) END AS root
        FROM mark_revisions r
       WHERE r.course_id = b.course_id AND r.seq BETWEEN b.seq_from AND b.seq_to) x
   WHERE b.course_id = p_course_id AND b.merkle_root IS DISTINCT FROM x.root
$$;

CREATE FUNCTION verify_all_chains()
RETURNS TABLE (cid integer, chain_ok boolean, first_bad_seq integer, problem text,
               marks_ok boolean, batches_ok boolean)
LANGUAGE plpgsql AS $$
DECLARE c record; vc record;
BEGIN
  FOR c IN SELECT course_id FROM courses ORDER BY course_id LOOP
    SELECT * INTO vc FROM verify_chain(c.course_id);
    cid := c.course_id; chain_ok := vc.ok; first_bad_seq := vc.bad_seq; problem := vc.problem;
    marks_ok   := NOT EXISTS (SELECT 1 FROM verify_marks_current(c.course_id));
    batches_ok := NOT EXISTS (SELECT 1 FROM verify_batches(c.course_id));
    IF NOT (chain_ok AND marks_ok AND batches_ok) THEN
      PERFORM pg_notify('veritas_integrity',
        json_build_object('course_id', cid, 'chain_ok', chain_ok, 'first_bad_seq', first_bad_seq,
                          'marks_ok', marks_ok, 'batches_ok', batches_ok)::text);
    END IF;
    RETURN NEXT;
  END LOOP;
END $$;
-- Scheduling (Supabase / pg_cron):
--   SELECT cron.schedule('veritas-verify', '*/15 * * * *', 'SELECT * FROM verify_all_chains()');

-- Seals every not-yet-batched revision of a course into one Merkle batch.
-- Refuses to seal a chain that does not verify, so a tampered chain is never anchored.
CREATE FUNCTION seal_batch(p_course_id integer)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE last_to integer; top integer; v record; root text; bid integer;
BEGIN
  PERFORM 1 FROM courses WHERE course_id = p_course_id FOR NO KEY UPDATE;
  SELECT * INTO v FROM verify_chain(p_course_id);
  IF NOT v.ok THEN
    RAISE EXCEPTION 'refusing to seal course %: chain broken at seq % (%)', p_course_id, v.bad_seq, v.problem;
  END IF;
  SELECT coalesce(max(seq_to), 0) INTO last_to FROM merkle_batches WHERE course_id = p_course_id;
  SELECT max(seq) INTO top FROM mark_revisions WHERE course_id = p_course_id;
  IF top IS NULL OR top <= last_to THEN RETURN NULL; END IF;
  root := merkle_root(ARRAY(SELECT row_hash::text FROM mark_revisions
                             WHERE course_id = p_course_id AND seq > last_to ORDER BY seq));
  INSERT INTO merkle_batches (course_id, seq_from, seq_to, merkle_root)
  VALUES (p_course_id, last_to + 1, top, root) RETURNING batch_id INTO bid;
  RETURN bid;
END $$;

CREATE FUNCTION record_anchor(p_batch_id integer, p_type text, p_ref text)
RETURNS integer LANGUAGE sql AS $$
  INSERT INTO anchors (batch_id, anchor_type, anchor_ref) VALUES (p_batch_id, p_type, p_ref)
  RETURNING anchor_id
$$;

-- ---------------------------------------------------------------------
-- 7. Views (security_invoker: row-level security applies to the caller)
-- ---------------------------------------------------------------------

CREATE VIEW v_course_result WITH (security_invoker = true) AS
SELECT m.student_id, c.course_id, c.semester, c.credits,
       sum(m.current_value)  AS obtained,
       sum(a.max_marks)      AS maximum
  FROM marks m
  JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type
  JOIN courses c     ON c.course_id = m.course_id
 GROUP BY m.student_id, c.course_id, c.semester, c.credits
HAVING count(m.current_value) = count(*)
   AND count(*) = (SELECT count(*) FROM assessments a2 WHERE a2.course_id = c.course_id);

-- SGPA is derived, never stored. Grade scale below is a simplified assumption, not the official RVCE scheme.
CREATE VIEW v_student_sgpa WITH (security_invoker = true) AS
SELECT student_id, semester,
       round(sum(gp * credits)::numeric / sum(credits), 2) AS sgpa
  FROM (SELECT r.*, CASE WHEN 100*obtained/maximum >= 90 THEN 10
                         WHEN 100*obtained/maximum >= 80 THEN 9
                         WHEN 100*obtained/maximum >= 70 THEN 8
                         WHEN 100*obtained/maximum >= 60 THEN 7
                         WHEN 100*obtained/maximum >= 55 THEN 6
                         WHEN 100*obtained/maximum >= 50 THEN 5
                         WHEN 100*obtained/maximum >= 40 THEN 4 ELSE 0 END AS gp
          FROM v_course_result r) g
 GROUP BY student_id, semester;

-- Per-revision features for the anomaly model (window function LAG)
CREATE VIEW v_revision_timeline WITH (security_invoker = true) AS
SELECT r.revision_id, r.course_id, r.seq, r.mark_id, r.changed_by, r.changed_at,
       r.old_value, r.new_value,
       r.new_value - coalesce(r.old_value, 0)                       AS delta,
       extract(epoch FROM r.changed_at
               - lag(r.changed_at) OVER (PARTITION BY r.course_id ORDER BY r.seq)) AS secs_since_prev,
       (r.changed_at >= a.freeze_at)                                 AS after_freeze,
       (r.request_id IS NOT NULL)                                    AS via_request,
       r.row_hash
  FROM mark_revisions r
  JOIN marks m       ON m.mark_id = r.mark_id
  JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type;

-- ---------------------------------------------------------------------
-- 8. Row-level security and privileges
-- ---------------------------------------------------------------------

ALTER TABLE users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE students       ENABLE ROW LEVEL SECURITY;
ALTER TABLE marks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE mark_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE certificates   ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomaly_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_read ON users FOR SELECT TO veritas_app
  USING (app_role() = 'admin' OR user_id = app_user_id() OR app_role() = 'faculty');
CREATE POLICY students_read ON students FOR SELECT TO veritas_app
  USING (app_role() IN ('admin','faculty') OR user_id = app_user_id());
CREATE POLICY marks_read ON marks FOR SELECT TO veritas_app
  USING (app_role() = 'admin' OR student_id = app_user_id()
         OR EXISTS (SELECT 1 FROM courses c WHERE c.course_id = marks.course_id AND c.faculty_id = app_user_id())
         OR (app_is_checker() AND EXISTS (SELECT 1 FROM change_requests cr WHERE cr.mark_id = marks.mark_id)));
CREATE POLICY revisions_read ON mark_revisions FOR SELECT TO veritas_app
  USING (app_role() = 'admin'
         OR EXISTS (SELECT 1 FROM courses c WHERE c.course_id = mark_revisions.course_id AND c.faculty_id = app_user_id())
         OR EXISTS (SELECT 1 FROM marks m WHERE m.mark_id = mark_revisions.mark_id AND m.student_id = app_user_id()));
CREATE POLICY requests_read ON change_requests FOR SELECT TO veritas_app
  USING (app_role() = 'admin' OR requested_by = app_user_id() OR app_is_checker());
CREATE POLICY certificates_read ON certificates FOR SELECT TO veritas_app
  USING (app_role() = 'admin' OR student_id = app_user_id() OR issued_by = app_user_id());
CREATE POLICY alerts_read ON anomaly_alerts FOR SELECT TO veritas_app
  USING (app_role() = 'admin' OR app_is_checker());

REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM PUBLIC, veritas_app;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO veritas_app;
GRANT SELECT ON students, courses, assessments, marks, mark_revisions, change_requests,
                certificates, merkle_batches, anchors, anomaly_alerts,
                v_course_result, v_student_sgpa, v_revision_timeline TO veritas_app;
GRANT SELECT (user_id, name, role, created_at) ON users TO veritas_app;   -- email stays private
GRANT SELECT (user_id, employee_id, department, can_approve) ON faculty TO veritas_app;
GRANT EXECUTE ON FUNCTION app_user_id(), app_role(), app_is_checker(), compute_row_hash(text,integer,integer,integer,numeric,numeric,integer,text,timestamptz),
                          apply_change(integer,numeric,text,integer,integer,integer),
                          request_change(integer,numeric,text,integer),
                          decide_request(integer,boolean,integer),
                          issue_certificate(integer,text,text,integer),
                          revoke_certificate(uuid,integer),
                          verify_certificate(uuid,text,text),
                          require_user(integer)
      TO veritas_app;
-- verify_*, seal_batch, record_anchor, merkle_root: admin/service role only (no grant)
