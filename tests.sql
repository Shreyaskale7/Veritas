-- =====================================================================
-- Veritas functional test suite. Run after schema.sql + seed.sql, as the DBA role.
-- Every case records PASS/FAIL in t.results; the report is printed at the end.
-- =====================================================================
\set ON_ERROR_STOP on
\pset pager off
DROP SCHEMA IF EXISTS t CASCADE;
CREATE SCHEMA t;
CREATE TABLE t.results (n serial, id text, descr text, ok boolean, detail text);

CREATE FUNCTION t.rec(p_id text, p_descr text, p_ok boolean, p_detail text DEFAULT NULL) RETURNS void
LANGUAGE sql AS $$ INSERT INTO t.results(id, descr, ok, detail) VALUES (p_id, p_descr, coalesce(p_ok, false), p_detail) $$;

-- statement as DBA; returns 'OK' or 'ERROR[sqlstate]: message'
CREATE FUNCTION t.try(p_sql text) RETURNS text LANGUAGE plpgsql AS $$
BEGIN EXECUTE p_sql; RETURN 'OK';
EXCEPTION WHEN OTHERS THEN RETURN format('ERROR[%s]: %s', SQLSTATE, SQLERRM); END $$;

-- scalar query as an application user (role veritas_app, veritas.user_id = p_uid; NULL = anonymous)
CREATE FUNCTION t.q_as(p_uid integer, p_sql text) RETURNS text LANGUAGE plpgsql AS $$
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
-- statement (no result) as an application user
CREATE FUNCTION t.x_as(p_uid integer, p_sql text) RETURNS text LANGUAGE plpgsql AS $$
BEGIN
  PERFORM set_config('veritas.user_id', coalesce(p_uid::text, ''), true);
  EXECUTE 'SET LOCAL ROLE veritas_app';
  BEGIN EXECUTE p_sql;
  EXCEPTION WHEN OTHERS THEN
    EXECUTE 'RESET ROLE'; PERFORM set_config('veritas.user_id', '', true);
    RETURN format('ERROR[%s]: %s', SQLSTATE, SQLERRM);
  END;
  EXECUTE 'RESET ROLE'; PERFORM set_config('veritas.user_id', '', true);
  RETURN 'OK';
END $$;

CREATE FUNCTION t.mid(p_student int, p_course int, p_type text) RETURNS int LANGUAGE sql STABLE AS $$
  SELECT mark_id FROM marks WHERE student_id = p_student AND course_id = p_course AND assessment_type = p_type $$;

-- apply a mark as faculty p_by; returns revision id or error text
CREATE FUNCTION t.put(p_student int, p_course int, p_type text, p_val numeric, p_by int, p_reason text DEFAULT 'initial entry') RETURNS text
LANGUAGE sql AS $$
  SELECT t.q_as(p_by, format('select apply_change(%s, %s, %L, %s)', t.mid(p_student, p_course, p_type), p_val, p_reason, p_by)) $$;

-- run a tamper statement with triggers bypassed (DBA / superuser), probe the result, then roll the tamper back
CREATE FUNCTION t.tamper(p_tamper text, p_probe text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE res text;
BEGIN
  BEGIN
    EXECUTE 'SET LOCAL session_replication_role = replica';
    EXECUTE p_tamper;
    EXECUTE 'SET LOCAL session_replication_role = origin';
    EXECUTE p_probe INTO res;
    RAISE EXCEPTION 'undo tamper' USING ERRCODE = 'VT999';
  EXCEPTION WHEN SQLSTATE 'VT999' THEN NULL; END;
  RETURN res;
END $$;

-- attacker helpers: recompute hashes / batch roots from a given point (needs replica role)
CREATE FUNCTION t.rewrite_chain(p_course int, p_from int) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r mark_revisions%ROWTYPE; prev text; prev_id bigint;
BEGIN
  SELECT row_hash, revision_id INTO prev, prev_id FROM mark_revisions WHERE course_id = p_course AND seq = p_from - 1;
  IF prev IS NULL THEN prev := genesis_hash(p_course); END IF;
  FOR r IN SELECT * FROM mark_revisions WHERE course_id = p_course AND seq >= p_from ORDER BY seq LOOP
    UPDATE mark_revisions
       SET prev_hash = prev, prev_revision_id = prev_id,
           row_hash = compute_row_hash(prev, r.seq, r.mark_id, r.course_id, r.old_value, r.new_value, r.changed_by, r.reason, r.changed_at)
     WHERE revision_id = r.revision_id RETURNING row_hash, revision_id INTO prev, prev_id;
  END LOOP;
END $$;
CREATE FUNCTION t.rewrite_batches(p_course int) RETURNS void LANGUAGE sql AS $$
  UPDATE merkle_batches b SET merkle_root = (SELECT merkle_root(array_agg(r.row_hash::text ORDER BY r.seq))
        FROM mark_revisions r WHERE r.course_id = b.course_id AND r.seq BETWEEN b.seq_from AND b.seq_to)
   WHERE b.course_id = p_course $$;

-- ---------------------------------------------------------------------
-- A. Schema constraints and specialization
-- ---------------------------------------------------------------------
DO $$ BEGIN
  PERFORM t.rec('T01','Seed data loaded: 7 users, 3 courses, 27 marks rows',
    (SELECT count(*) FROM users) = 7 AND (SELECT count(*) FROM courses) = 3 AND (SELECT count(*) FROM marks) = 27);
  PERFORM t.rec('T02','A faculty user cannot also be inserted as a student (disjoint specialization)',
    t.try($q$ INSERT INTO students VALUES (2,'1RV24CD999','CSE',5) $q$) LIKE 'ERROR%cannot be a student%', t.try($q$ INSERT INTO students VALUES (2,'1RV24CD999','CSE',5) $q$));
  PERFORM t.rec('T03','Duplicate USN is rejected',
    t.try($q$ INSERT INTO users(name,email,role) VALUES ('X','x@x','student') $q$) = 'OK'
    AND t.try($q$ INSERT INTO students SELECT max(user_id),'1RV24CD001','CSE',5 FROM users $q$) LIKE 'ERROR[23505]%');
  PERFORM t.rec('T04','Role of a specialised user cannot be changed',
    t.try($q$ UPDATE users SET role='faculty' WHERE user_id=5 $q$) LIKE 'ERROR%cannot change once specialised%');
  PERFORM t.rec('T05','Assessment with non-positive max_marks is rejected',
    t.try($q$ INSERT INTO assessments VALUES (1,'SEE',0,now()) $q$) LIKE 'ERROR[23%');
END $$;
-- remove the throwaway user created in T03
DELETE FROM users WHERE email = 'x@x';

-- ---------------------------------------------------------------------
-- B. Hash chain basics (course 1 = Dr. Rao, course 2 = Prof. Iyer)
-- ---------------------------------------------------------------------
DO $$
DECLARE r1 text; before_cnt int; before_val numeric; res text;
BEGIN
  r1 := t.put(5,1,'CIE-1',38, 2);
  PERFORM t.rec('T10','First revision of a course: seq 1, no predecessor, genesis prev_hash, old_value NULL',
    (SELECT seq = 1 AND prev_revision_id IS NULL AND prev_hash = genesis_hash(1) AND old_value IS NULL
       FROM mark_revisions WHERE course_id = 1), r1);
  PERFORM t.put(5,1,'CIE-1',40, 2,'entry error corrected before freeze');   -- seq 2
  PERFORM t.put(5,1,'CIE-2',44, 2);                                          -- seq 3
  PERFORM t.put(5,1,'SEE',80, 2);                                            -- seq 4
  PERFORM t.put(6,1,'CIE-1',30, 2);                                          -- seq 5
  PERFORM t.put(6,1,'CIE-2',33, 2);                                          -- seq 6
  PERFORM t.put(7,1,'CIE-1',20, 2);                                          -- seq 7
  PERFORM t.rec('T11','Course 1 has contiguous seq 1..7 and each prev_hash equals the previous row_hash',
    (SELECT count(*) = 7 AND bool_and(seq = rn AND prev_hash = coalesce(lag_hash, genesis_hash(1)))
       FROM (SELECT seq, prev_hash, row_number() OVER (ORDER BY seq) AS rn,
                    lag(row_hash) OVER (ORDER BY seq) AS lag_hash FROM mark_revisions WHERE course_id = 1) x));
  PERFORM t.rec('T12','verify_chain accepts the untouched course-1 chain (7 rows)',
    (SELECT ok AND checked_rows = 7 FROM verify_chain(1)));
  PERFORM t.rec('T13','A pre-freeze correction records old_value = the previous value (38 -> 40)',
    (SELECT old_value = 38 AND new_value = 40 FROM mark_revisions WHERE course_id = 1 AND seq = 2));

  PERFORM t.put(5,2,'CIE-1',45, 3);  PERFORM t.put(5,2,'CIE-2',40, 3);
  PERFORM t.put(5,2,'SEE',70, 3);    PERFORM t.put(6,2,'CIE-1',25, 3);
  PERFORM t.rec('T14','Chains are per course: course 2 starts at seq 1 with its own genesis hash and verifies',
    (SELECT min(seq) = 1 AND max(seq) = 4 AND bool_or(seq = 1 AND prev_hash = genesis_hash(2)) FROM mark_revisions WHERE course_id = 2)
    AND (SELECT ok FROM verify_chain(2)) AND genesis_hash(1) <> genesis_hash(2));

  SELECT count(*) INTO before_cnt FROM mark_revisions;
  res := t.put(5,1,'CIE-2',60, 2);
  PERFORM t.rec('T15','Value above max_marks is rejected', res LIKE 'ERROR%outside 0..50%', res);
  res := t.put(5,1,'CIE-2',-3, 2);
  PERFORM t.rec('T16','Negative value is rejected', res LIKE 'ERROR%', res);
  res := t.put(5,1,'CIE-2',44, 2);
  PERFORM t.rec('T17','Writing the same value again is rejected as a no-op', res LIKE 'ERROR%no change%', res);
  SELECT current_value INTO before_val FROM marks WHERE mark_id = t.mid(5,1,'CIE-2');
  PERFORM t.rec('T18','Failed writes leave no partial state: revision count and mark value unchanged',
    (SELECT count(*) FROM mark_revisions) = before_cnt AND before_val = 44);
  res := t.put(5,1,'SEE',81, 3);
  PERFORM t.rec('T19','Faculty who does not teach the course cannot write its marks', res LIKE 'ERROR%only the course faculty%', res);
  res := t.q_as(2, format('select apply_change(%s, 50, ''x'', 3)', t.mid(5,1,'CIE-2')));
  PERFORM t.rec('T20','Acting user must equal the signed-in user (cannot write as someone else)', res LIKE 'ERROR%does not match the signed-in user%', res);
  res := t.q_as(NULL, format('select apply_change(%s, 50, ''x'', 2)', t.mid(5,1,'CIE-2')));
  PERFORM t.rec('T21','Anonymous session cannot write marks', res LIKE 'ERROR%', res);
END $$;

-- ---------------------------------------------------------------------
-- C. Append-only enforcement
-- ---------------------------------------------------------------------
DO $$ BEGIN
  PERFORM t.rec('T30','UPDATE on mark_revisions is blocked (even for the owner)',
    t.try($q$ UPDATE mark_revisions SET new_value = 1 WHERE course_id = 1 AND seq = 1 $q$) LIKE 'ERROR%append-only%');
  PERFORM t.rec('T31','DELETE on mark_revisions is blocked',
    t.try($q$ DELETE FROM mark_revisions WHERE course_id = 1 AND seq = 7 $q$) LIKE 'ERROR%append-only%');
  PERFORM t.rec('T32','TRUNCATE on mark_revisions is blocked: plain form by the foreign keys, CASCADE form by the guard trigger',
    t.try($q$ TRUNCATE mark_revisions $q$) LIKE 'ERROR%'
    AND t.try($q$ TRUNCATE mark_revisions CASCADE $q$) LIKE 'ERROR%append-only%',
    t.try($q$ TRUNCATE mark_revisions CASCADE $q$));
  PERFORM t.rec('T33','Application role has no UPDATE/DELETE/INSERT privilege on mark_revisions',
    t.x_as(2,$q$ UPDATE mark_revisions SET new_value = 1 $q$) LIKE 'ERROR[42501]%'
    AND t.x_as(2,$q$ DELETE FROM mark_revisions $q$) LIKE 'ERROR[42501]%'
    AND t.x_as(2,$q$ INSERT INTO mark_revisions(mark_id,course_id,new_value,changed_by,reason) VALUES (1,1,5,2,'x') $q$) LIKE 'ERROR[42501]%');
  PERFORM t.rec('T34','Direct UPDATE of marks.current_value is blocked for the owner (must use apply_change)',
    t.try($q$ UPDATE marks SET current_value = 99 WHERE mark_id = 1 $q$) LIKE 'ERROR%only be changed through apply_change%');
  PERFORM t.rec('T35','Application role cannot UPDATE marks directly',
    t.x_as(2,$q$ UPDATE marks SET current_value = 99 $q$) LIKE 'ERROR[42501]%');
  PERFORM t.rec('T36','DELETE on marks is blocked',
    t.try($q$ DELETE FROM marks WHERE mark_id = 1 $q$) LIKE 'ERROR%append-only%');
END $$;

-- ---------------------------------------------------------------------
-- D. Freeze, maker-checker, optimistic versioning
-- ---------------------------------------------------------------------
-- HOD (user 4) teaches course 3 and is also a checker
SELECT t.put(5,3,'CIE-1',35,4);
-- the CIE-1 deadline of course 1 passes (committed before the next block, so it applies to later transactions)
UPDATE assessments SET freeze_at = now() WHERE course_id = 1 AND type = 'CIE-1';

DO $$
DECLARE res text; rq1 int; rq2 int; rq3 int; mid1 int := t.mid(5,1,'CIE-1'); rev text;
BEGIN
  res := t.put(5,1,'CIE-1',42,2,'late edit without approval');
  PERFORM t.rec('T40','After the freeze deadline a direct edit is rejected', res LIKE 'ERROR%frozen%', res);

  res := t.q_as(3, format('select request_change(%s, 42, ''re-evaluation of script'', 3)', mid1));
  PERFORM t.rec('T41','Only the course faculty can raise a change request', res LIKE 'ERROR%only the course faculty%', res);
  res := t.q_as(2, format('select request_change(%s, 60, ''re-evaluation of script'', 2)', mid1));
  PERFORM t.rec('T42','Request above max_marks is rejected', res LIKE 'ERROR%exceeds max%', res);
  res := t.q_as(2, format('select request_change(%s, 42, ''ok'', 2)', mid1));
  PERFORM t.rec('T43','Request without a meaningful reason is rejected (min 5 characters)', res LIKE 'ERROR[23514]%', res);

  rq1 := t.q_as(2, format('select request_change(%s, 42, ''re-evaluation of script after student query'', 2)', mid1))::int;
  PERFORM t.rec('T44','Valid request is created as pending', (SELECT status = 'pending' AND approved_by IS NULL FROM change_requests WHERE request_id = rq1));

  res := t.q_as(2, format('select apply_change(%s, 42, ''x'', 2, %s)', mid1, rq1));
  PERFORM t.rec('T45','A pending (undecided) request does not authorise a revision', res LIKE 'ERROR%does not authorise%', res);
  res := t.q_as(3, format('select decide_request(%s, true, 3)', rq1));
  PERFORM t.rec('T46','Faculty without can_approve cannot decide a request', res LIKE 'ERROR%not allowed to approve%', res);
  res := t.q_as(2, format('select decide_request(%s, true, 2)', rq1));
  PERFORM t.rec('T47','The requester cannot approve their own request', res LIKE 'ERROR%', res);

  PERFORM t.q_as(4, format('select decide_request(%s, true, 4)', rq1));
  PERFORM t.rec('T48','HOD approval recorded: approved_by = 4 and decided_at set',
    (SELECT status = 'approved' AND approved_by = 4 AND decided_at IS NOT NULL FROM change_requests WHERE request_id = rq1));
  res := t.q_as(2, format('select apply_change(%s, 43, ''x'', 2, %s)', mid1, rq1));
  PERFORM t.rec('T49','An approved request authorises only the exact proposed value (43 <> 42 rejected)', res LIKE 'ERROR%does not authorise%', res);

  rev := t.q_as(2, format('select apply_change(%s, 42, ''applying approved re-evaluation'', 2, %s)', mid1, rq1));
  PERFORM t.rec('T50','Approved request applies: revision links the request, mark updated, request becomes applied',
    (SELECT r.request_id = rq1 AND r.old_value = 40 AND r.new_value = 42 FROM mark_revisions r WHERE r.revision_id = rev::bigint)
    AND (SELECT current_value = 42 AND version = 3 FROM marks WHERE mark_id = mid1)
    AND (SELECT status = 'applied' FROM change_requests WHERE request_id = rq1), rev);
  res := t.q_as(2, format('select apply_change(%s, 41, ''reuse'', 2, %s)', mid1, rq1));
  PERFORM t.rec('T51','A used request cannot be reused', res LIKE 'ERROR%does not authorise%', res);

  rq2 := t.q_as(2, format('select request_change(%s, 10, ''wrong script was attached to student'', 2)', t.mid(6,1,'CIE-1')))::int;
  PERFORM t.q_as(4, format('select decide_request(%s, false, 4)', rq2));
  PERFORM t.rec('T52','Rejected request is stored with the deciding checker',
    (SELECT status = 'rejected' AND approved_by = 4 FROM change_requests WHERE request_id = rq2));
  res := t.q_as(2, format('select apply_change(%s, 10, ''x'', 2, %s)', t.mid(6,1,'CIE-1'), rq2));
  PERFORM t.rec('T53','A rejected request cannot be applied', res LIKE 'ERROR%does not authorise%', res);
  res := t.q_as(4, format('select decide_request(%s, true, 4)', rq2));
  PERFORM t.rec('T54','A decided request cannot be decided again', res LIKE 'ERROR%not pending%', res);
  PERFORM t.rec('T55','Illegal status transitions are blocked (rejected -> approved, approved -> applied outside apply_change)',
    t.try(format('UPDATE change_requests SET status = ''approved'' WHERE request_id = %s', rq2)) LIKE 'ERROR%'
    AND t.try(format('UPDATE change_requests SET status = ''applied'' WHERE request_id = %s', rq2)) LIKE 'ERROR%');

  -- HOD raises a request on his own course and tries to approve it himself
  rq3 := t.q_as(4, format('select request_change(%s, 33, ''recheck of rubric totals'', 4)', t.mid(5,3,'CIE-1')))::int;
  res := t.q_as(4, format('select decide_request(%s, true, 4)', rq3));
  PERFORM t.rec('T56','Even a checker cannot approve his own request (checker_differs constraint)', res LIKE 'ERROR[23514]%checker_differs%', res);

  res := t.q_as(3, format('select apply_change(%s, 50, ''x'', 3, null, 0)', t.mid(6,2,'CIE-1')));
  PERFORM t.rec('T57','Optimistic versioning: stale expected_version raises a serialization failure (40001)',
    res LIKE 'ERROR[40001]%version conflict%', res);
  res := t.q_as(3, format('select apply_change(%s, 26, ''fresh read'', 3, null, 1)', t.mid(6,2,'CIE-1')));
  PERFORM t.rec('T58','Optimistic versioning: correct expected_version succeeds', res ~ '^[0-9]+$', res);
END $$;

-- ---------------------------------------------------------------------
-- E. Row-level security
-- ---------------------------------------------------------------------
DO $$
DECLARE own_revs int; BEGIN
  PERFORM t.rec('T60','Student sees only own marks rows (9 of 27)', t.q_as(5,'select count(*) from marks') = '9');
  PERFORM t.rec('T61','Student sees no other student''s marks', t.q_as(5,'select count(*) from marks where student_id <> 5') = '0');
  PERFORM t.rec('T62','Faculty sees only marks of the courses taught (course 1 -> 9 rows)', t.q_as(2,'select count(*) from marks') = '9');
  PERFORM t.rec('T63','Admin sees all marks (27)', t.q_as(1,'select count(*) from marks') = '27');
  SELECT count(*) INTO own_revs FROM mark_revisions r JOIN marks m USING (mark_id) WHERE m.student_id = 5;
  PERFORM t.rec('T64','Student sees own revisions (with hashes) and none of other students''',
    t.q_as(5,'select count(*) from mark_revisions')::int = own_revs AND own_revs > 0
    AND t.q_as(6,'select count(*) from mark_revisions r join marks m using (mark_id) where m.student_id = 5') = '0');
  PERFORM t.rec('T65','Change requests: student 0, non-checker faculty 0, requester 2 (own), HOD sees all',
    t.q_as(5,'select count(*) from change_requests') = '0'
    AND t.q_as(3,'select count(*) from change_requests') = '0'
    AND t.q_as(2,'select count(*) from change_requests')::int = (SELECT count(*) FROM change_requests WHERE requested_by = 2)
    AND t.q_as(4,'select count(*) from change_requests')::int = (SELECT count(*) FROM change_requests));
  PERFORM t.rec('T66','Users e-mail column is not readable by the application role',
    t.q_as(5,'select email from users limit 1') LIKE 'ERROR[42501]%');
  PERFORM t.rec('T67','A student sees only their own users row', t.q_as(5,'select count(*) from users') = '1');
  PERFORM t.rec('T68','Students cannot read anomaly alerts', t.q_as(5,'select count(*) from anomaly_alerts') = '0');
  PERFORM t.rec('T69','Application role cannot write to marks or users directly',
    t.x_as(5,'insert into marks(student_id,course_id,assessment_type) values (5,1,''SEE'')') LIKE 'ERROR[42501]%'
    AND t.x_as(5,'update users set name = ''x''') LIKE 'ERROR[42501]%');
END $$;

-- ---------------------------------------------------------------------
-- F. Certificates
-- ---------------------------------------------------------------------
DO $$
DECLARE d text := encode(digest('Marks card, semester 5, Asha Nair','sha256'),'hex');
        issued text; cid uuid; salt text; res text;
BEGIN
  issued := t.q_as(2, format('select out_cert_id::text || '','' || out_salt from issue_certificate(5, ''Marks card'', %L, 2)', d));
  cid := split_part(issued, ',', 1)::uuid;  salt := split_part(issued, ',', 2);
  PERFORM t.rec('T70','Certificate issued by faculty with a random 128-bit salt', length(salt) = 32, issued);
  PERFORM t.rec('T71','Public check with the right salt and digest returns valid (anonymous session)',
    t.q_as(NULL, format('select verify_certificate(%L, %L, %L)', cid, salt, d)) = 'valid');
  PERFORM t.rec('T72','Wrong salt, wrong digest or unknown id all return unknown',
    t.q_as(NULL, format('select verify_certificate(%L, %L, %L)', cid, repeat('0',32), d)) = 'unknown'
    AND t.q_as(NULL, format('select verify_certificate(%L, %L, %L)', cid, salt, repeat('0',64))) = 'unknown'
    AND t.q_as(NULL, format('select verify_certificate(%L, %L, %L)', gen_random_uuid(), salt, d)) = 'unknown');
  PERFORM t.rec('T73','Stored doc_hash is salted: it differs from the plain SHA-256 of the content',
    (SELECT doc_hash <> encode(digest(d,'sha256'),'hex') FROM certificates WHERE cert_id = cid));
  PERFORM t.rec('T74','The public check returns a bare status string and nothing else',
    (SELECT pg_get_function_result(oid) = 'text' FROM pg_proc WHERE proname = 'verify_certificate'));
  res := t.q_as(5, format('select out_cert_id from issue_certificate(5, ''Marks card'', %L, 5)', d));
  PERFORM t.rec('T75','A student cannot issue certificates', res LIKE 'ERROR%', res);
  res := t.q_as(2, format('select revoke_certificate(%L, 2)', cid));
  PERFORM t.rec('T76','Only an approving faculty member can revoke', res LIKE 'ERROR%only an approving faculty%', res);
  PERFORM t.q_as(4, format('select revoke_certificate(%L, 4)', cid));
  PERFORM t.rec('T77','After revocation the public check returns revoked',
    t.q_as(NULL, format('select verify_certificate(%L, %L, %L)', cid, salt, d)) = 'revoked');
  PERFORM t.rec('T78','A revoked certificate cannot be reinstated or deleted',
    t.try(format('UPDATE certificates SET status = ''valid'', revoked_at = NULL WHERE cert_id = %L', cid)) LIKE 'ERROR%cannot be reinstated%'
    AND t.try(format('DELETE FROM certificates WHERE cert_id = %L', cid)) LIKE 'ERROR%append-only%');
  PERFORM t.rec('T79','Another student cannot read the certificate row (RLS)',
    t.q_as(6, 'select count(*) from certificates') = '0' AND t.q_as(5, 'select count(*) from certificates') = '1');
END $$;

-- ---------------------------------------------------------------------
-- G. Derived data and views
-- ---------------------------------------------------------------------
DO $$ BEGIN
  PERFORM t.rec('T80','SGPA is derived in a view: Asha = (9*4 + 8*3)/7 = 8.57 (course 3 incomplete, excluded)',
    (SELECT sgpa = 8.57 FROM v_student_sgpa WHERE student_id = 5), (SELECT sgpa::text FROM v_student_sgpa WHERE student_id = 5));
  PERFORM t.rec('T81','SGPA view is filtered by RLS: Bharat cannot see Asha''s SGPA',
    t.q_as(6,'select count(*) from v_student_sgpa where student_id = 5') = '0');
  PERFORM t.rec('T82','v_revision_timeline: LAG gives NULL for seq 1 and a gap for later rows; after_freeze set only for the late edit',
    (SELECT secs_since_prev IS NULL FROM v_revision_timeline WHERE course_id = 1 AND seq = 1)
    AND (SELECT secs_since_prev IS NOT NULL FROM v_revision_timeline WHERE course_id = 1 AND seq = 2)
    AND (SELECT count(*) FROM v_revision_timeline WHERE course_id = 1 AND after_freeze) = 1
    AND (SELECT via_request AND after_freeze FROM v_revision_timeline WHERE course_id = 1 AND seq = 8));
END $$;

-- ---------------------------------------------------------------------
-- H. Merkle batches
-- ---------------------------------------------------------------------
SELECT t.put(7,1,'CIE-2',25,2);   -- course 1, seq 9
DO $$
DECLARE b1 int; b2 int; BEGIN
  PERFORM t.rec('T90','Course 1 has 9 revisions and verifies', (SELECT ok AND checked_rows = 9 FROM verify_chain(1)));
  b1 := seal_batch(1);
  PERFORM t.rec('T91','seal_batch seals seq 1..9 into batch 1; stored root equals the root recomputed from the chain',
    (SELECT seq_from = 1 AND seq_to = 9 FROM merkle_batches WHERE batch_id = b1)
    AND NOT EXISTS (SELECT 1 FROM verify_batches(1)));
  PERFORM t.rec('T92','seal_batch with nothing new returns NULL', seal_batch(1) IS NULL);
  PERFORM record_anchor(b1, 'file', 'test-anchor');
  PERFORM t.rec('T37','merkle_batches and anchors are append-only as well (UPDATE and DELETE blocked)',
    t.try($q$ UPDATE merkle_batches SET merkle_root = repeat('0',64) $q$) LIKE 'ERROR%append-only%'
    AND t.try($q$ DELETE FROM merkle_batches $q$) LIKE 'ERROR%append-only%'
    AND t.try($q$ UPDATE anchors SET anchor_ref = 'x' $q$) LIKE 'ERROR%append-only%'
    AND t.try($q$ DELETE FROM anchors $q$) LIKE 'ERROR%append-only%');
  PERFORM t.rec('T93','merkle_root is deterministic and order-sensitive',
    merkle_root(ARRAY['a','b','c']) = merkle_root(ARRAY['a','b','c']) AND merkle_root(ARRAY['a','b','c']) <> merkle_root(ARRAY['b','a','c']));
  PERFORM t.rec('T94','Application role cannot seal batches or run verification',
    t.q_as(1,'select seal_batch(1)') LIKE 'ERROR[42501]%' AND t.q_as(1,'select * from verify_chain(1)') LIKE 'ERROR[42501]%');
END $$;
SELECT t.put(6,2,'CIE-2',22,3);   -- course 2: add one more, seal both courses
SELECT seal_batch(1), seal_batch(2), seal_batch(3);
SELECT t.put(7,1,'SEE',55,2);     -- course 1, seq 10: second batch
SELECT seal_batch(1);

-- ---------------------------------------------------------------------
-- I. Tamper detection (each attack runs as DBA with triggers bypassed, then is rolled back)
-- ---------------------------------------------------------------------
DO $$
DECLARE res text; probe text := $p$ select ok::text || '|' || coalesce(bad_seq::text,'-') || '|' || coalesce(problem,'-') from verify_chain(1) $p$;
BEGIN
  res := t.tamper($q$ UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3 $q$, probe);
  PERFORM t.rec('T100','Edit a row''s value: verify_chain names that row (seq 3) as broken', res LIKE 'false|3|row_hash%', res);

  res := t.tamper($q$ UPDATE mark_revisions SET new_value = 99, row_hash = compute_row_hash(prev_hash,seq,mark_id,course_id,old_value,99,changed_by,reason,changed_at)
                      WHERE course_id = 1 AND seq = 3 $q$, probe);
  PERFORM t.rec('T101','Edit a row and re-hash only that row: detected at the NEXT row (seq 4), whose prev_hash no longer matches', res LIKE 'false|4|prev_hash%', res);

  res := t.tamper($q$ DELETE FROM mark_revisions WHERE course_id = 1 AND seq = 4 $q$, probe);
  PERFORM t.rec('T102','Delete a middle row: reported as a sequence gap at seq 4', res LIKE 'false|4|sequence gap%', res);

  res := t.tamper($q$ UPDATE mark_revisions SET reason = 'edited reason' WHERE course_id = 1 AND seq = 5 $q$, probe);
  PERFORM t.rec('T103','Edit the free-text reason: detected', res LIKE 'false|5|row_hash%', res);

  res := t.tamper($q$ UPDATE mark_revisions SET new_value = 39 WHERE course_id = 1 AND seq = 2; SELECT t.rewrite_chain(1, 2) $q$, probe);
  PERFORM t.rec('T104','Attacker re-hashes the whole chain after changing seq 2, but a later revision of the same mark (seq 8) still records old_value 40: caught by the old_value continuity check',
    res LIKE 'false|8|old_value%', res);

  res := t.tamper($q$ UPDATE marks SET current_value = 50 WHERE mark_id = (SELECT mark_id FROM marks WHERE student_id=6 AND course_id=1 AND assessment_type='CIE-1') $q$,
                  $p$ select bad_mark_id::text || '|' || stored_value || '|' || ledger_value from verify_marks_current(1) $p$);
  PERFORM t.rec('T105','Edit marks.current_value directly (bypassing the ledger): verify_marks_current flags the mark', res LIKE '%|50.00|30.00', res);

  res := t.tamper($q$ UPDATE merkle_batches SET merkle_root = repeat('0',64) WHERE batch_id = 1 $q$,
                  $p$ select string_agg(bad_batch_id::text, ',') from verify_batches(1) $p$);
  PERFORM t.rec('T106','Forge a stored Merkle root: verify_batches flags the batch', res = '1', res);

  PERFORM t.rec('T107','verify_all_chains reports the tampered course and keeps the untouched courses green',
    t.tamper($q$ UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3 $q$,
             $p$ select string_agg(cid::text || ':' || (chain_ok AND marks_ok AND batches_ok)::text, ',' ORDER BY cid) from verify_all_chains() $p$)
    = '1:false,2:true,3:true');

  res := t.tamper($q$ DELETE FROM mark_revisions WHERE course_id = 1 AND seq = 10 $q$, probe);
  PERFORM t.rec('T108','Truncate the tail (delete the last row): verify_chain ALONE cannot see it (known limitation of any hash chain)', res = 'true|-|-', res);
  res := t.tamper($q$ DELETE FROM mark_revisions WHERE course_id = 1 AND seq = 10 $q$,
                  $p$ select (select count(*) from verify_marks_current(1))::text || ',' || (select count(*) from verify_batches(1))::text $p$);
  PERFORM t.rec('T109','...but the same truncation is flagged by the marks cross-check and the batch check (1 mark and 1 batch inconsistent)', res = '1,1', res);
END $$;
-- T57-style guard: a broken chain must never be sealed
DO $$
DECLARE res text; BEGIN
  PERFORM t.q_as(NULL,'select 1');
  BEGIN
    EXECUTE 'SET LOCAL session_replication_role = replica';
    UPDATE mark_revisions SET new_value = 99 WHERE course_id = 1 AND seq = 3;
    EXECUTE 'SET LOCAL session_replication_role = origin';
    -- add an unsealed revision so seal_batch has work to do
    PERFORM set_config('veritas.user_id','2',true);
    PERFORM apply_change(t.mid(5,1,'SEE'), 81, 'late fix', 2);
    res := t.try('select seal_batch(1)');
    RAISE EXCEPTION 'undo' USING ERRCODE = 'VT999';
  EXCEPTION WHEN SQLSTATE 'VT999' THEN NULL; END;
  PERFORM t.rec('T110','seal_batch refuses to seal a course whose chain does not verify', res LIKE 'ERROR%refusing to seal%', res);
END $$;

-- ---------------------------------------------------------------------
-- J. Final state is still clean (all tampering was rolled back)
-- ---------------------------------------------------------------------
DO $$ BEGIN
  PERFORM t.rec('T120','After all attack tests, every course verifies again (no tamper leaked)',
    (SELECT bool_and(chain_ok AND marks_ok AND batches_ok) FROM verify_all_chains()));
END $$;

\echo
\echo ===== RESULTS =====
SELECT id, CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS result, descr, CASE WHEN ok THEN '' ELSE detail END AS detail
  FROM t.results ORDER BY n;
SELECT count(*) FILTER (WHERE ok) AS passed, count(*) FILTER (WHERE NOT ok) AS failed, count(*) AS total FROM t.results;
