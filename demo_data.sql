-- Deterministic demo load used by the Python tests, the concurrency test and the demo.
-- Acts as the API layer would: sets the signed-in user, then calls apply_change().
DO $$
DECLARE s int; ty text; v numeric; i int := 0;
BEGIN
  PERFORM set_config('veritas.user_id', '2', true);          -- Dr. Rao, course 1
  FOR s IN 5..7 LOOP
    FOREACH ty IN ARRAY ARRAY['CIE-1','CIE-2','SEE'] LOOP
      i := i + 1;
      v := CASE ty WHEN 'SEE' THEN 40 + i * 5 ELSE 20 + i * 2 END;
      PERFORM apply_change((SELECT mark_id FROM marks WHERE student_id = s AND course_id = 1 AND assessment_type = ty),
                           v, 'initial entry', 2);
    END LOOP;
  END LOOP;
  -- a reason with characters that break naive hash encodings: pipe, quotes, backslash, non-ASCII
  PERFORM apply_change((SELECT mark_id FROM marks WHERE student_id = 5 AND course_id = 1 AND assessment_type = 'CIE-1'),
                       39, E'recheck | "rubric" \\ naïve – 5|6', 2);
  PERFORM set_config('veritas.user_id', '3', true);          -- Prof. Iyer, course 2
  FOR s IN 5..7 LOOP
    PERFORM apply_change((SELECT mark_id FROM marks WHERE student_id = s AND course_id = 2 AND assessment_type = 'CIE-1'),
                         30 + s, 'initial entry', 3);
  END LOOP;
END $$;
SELECT seal_batch(1), seal_batch(2);
DO $$ BEGIN
  PERFORM set_config('veritas.user_id', '2', true);
  PERFORM apply_change((SELECT mark_id FROM marks WHERE student_id = 6 AND course_id = 1 AND assessment_type = 'SEE'), 77, 'second batch entry', 2);
  PERFORM apply_change((SELECT mark_id FROM marks WHERE student_id = 7 AND course_id = 1 AND assessment_type = 'SEE'), 66, 'second batch entry', 2);
END $$;
SELECT seal_batch(1);
