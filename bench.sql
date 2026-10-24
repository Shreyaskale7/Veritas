-- Benchmark harness: same insert path with (a) no chain, (b) one chain per course, (c) one global chain.
CREATE SCHEMA bench;
CREATE TABLE bench.heads (chain_id int PRIMARY KEY);
INSERT INTO bench.heads SELECT g FROM generate_series(0, 10) g;
CREATE TABLE bench.plain (course_id int, mark_id int, new_value numeric(5,2), changed_by int, reason text,
                          changed_at timestamptz, seq int, prev_hash char(64), row_hash char(64));
CREATE TABLE bench.chain_pc (LIKE bench.plain);
ALTER TABLE bench.chain_pc ADD UNIQUE (course_id, seq);
CREATE TABLE bench.chain_gl (LIKE bench.plain);
ALTER TABLE bench.chain_gl ADD UNIQUE (seq);

CREATE FUNCTION bench.trg_pc() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE lr record;
BEGIN
  PERFORM 1 FROM bench.heads WHERE chain_id = NEW.course_id FOR NO KEY UPDATE;
  SELECT seq, row_hash INTO lr FROM bench.chain_pc WHERE course_id = NEW.course_id ORDER BY seq DESC LIMIT 1;
  NEW.seq := coalesce(lr.seq, 0) + 1;
  NEW.prev_hash := coalesce(lr.row_hash, genesis_hash(NEW.course_id));
  NEW.changed_at := clock_timestamp();
  NEW.row_hash := compute_row_hash(NEW.prev_hash, NEW.seq, NEW.mark_id, NEW.course_id, NULL, NEW.new_value, NEW.changed_by, NEW.reason, NEW.changed_at);
  RETURN NEW;
END $$;
CREATE TRIGGER t BEFORE INSERT ON bench.chain_pc FOR EACH ROW EXECUTE FUNCTION bench.trg_pc();

CREATE FUNCTION bench.trg_gl() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE lr record;
BEGIN
  PERFORM 1 FROM bench.heads WHERE chain_id = 0 FOR NO KEY UPDATE;
  SELECT seq, row_hash INTO lr FROM bench.chain_gl ORDER BY seq DESC LIMIT 1;
  NEW.seq := coalesce(lr.seq, 0) + 1;
  NEW.prev_hash := coalesce(lr.row_hash, genesis_hash(0));
  NEW.changed_at := clock_timestamp();
  NEW.row_hash := compute_row_hash(NEW.prev_hash, NEW.seq, NEW.mark_id, NEW.course_id, NULL, NEW.new_value, NEW.changed_by, NEW.reason, NEW.changed_at);
  RETURN NEW;
END $$;
CREATE TRIGGER t BEFORE INSERT ON bench.chain_gl FOR EACH ROW EXECUTE FUNCTION bench.trg_gl();
