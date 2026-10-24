Machine: 2 CPU core(s). Each pgbench transaction = one insert + 2 ms of simulated application work, so locks are held realistically. 8 s per cell. 10 courses, clients pick a course at random.

### B1  Throughput (transactions/s) and average latency (ms)

| clients | no chain | chain per course | one global chain | per-course vs global |
|---|---|---|---|---|
| 1 | 321 tps / 3.1 ms | 301 tps / 3.3 ms | 295 tps / 3.4 ms | 1.0x |
| 4 | 1287 tps / 3.1 ms | 1013 tps / 4.0 ms | 315 tps / 12.7 ms | 3.2x |
| 8 | 2329 tps / 3.4 ms | 1602 tps / 5.0 ms | 315 tps / 25.4 ms | 5.1x |
| 16 | 4315 tps / 3.7 ms | 2057 tps / 7.8 ms | 301 tps / 53.1 ms | 6.8x |

Check after the 16-client run: per-course chains with a gap or duplicate = 0 (expected 0).

### B2  Trigger overhead, single client, no simulated work (inserts/s)

| variant | inserts/s |
|---|---|
| no chain | 2935 |
| hash-chain trigger | 2101 |

### B3  verify_chain time vs chain length (real schema, rows written through apply_change)

| revisions in course 1 | verify_chain | per 1,000 rows |
|---|---|---|
| 1,000 | 20 ms | 19.9 ms |
| 5,000 | 71 ms | 14.1 ms |
| 20,000 | 214 ms | 10.7 ms |

verify_chain on the bulk-loaded chain reports ok = t.

### B4  Effect of the (course_id, seq) unique index on the 'latest revision of a course' lookup used by the trigger

- with index: `->  Index Scan Backward using mark_revisions_course_id_seq_key on mark_revisions`, execution 0.063 ms
- without index (copy of the table): `->  Seq Scan on noidx`, execution 6.424 ms
