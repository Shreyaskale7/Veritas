-- Tools a DBA-level attacker would use. Loaded ONLY into throwaway attack databases, never into production.
CREATE SCHEMA IF NOT EXISTS atk;
CREATE OR REPLACE FUNCTION atk.rewrite_chain(p_course int, p_from int) RETURNS void LANGUAGE plpgsql AS $$
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
CREATE OR REPLACE FUNCTION atk.rewrite_batches(p_course int) RETURNS void LANGUAGE sql AS $$
  UPDATE merkle_batches b SET merkle_root = (SELECT merkle_root(array_agg(r.row_hash::text ORDER BY r.seq))
        FROM mark_revisions r WHERE r.course_id = b.course_id AND r.seq BETWEEN b.seq_from AND b.seq_to)
   WHERE b.course_id = p_course $$;
