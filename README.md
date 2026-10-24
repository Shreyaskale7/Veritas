# Veritas: tamper-evident marks and certificate ledger

DBMS (CD252IA), RV College of Engineering. PostgreSQL 15+ does the enforcing; FastAPI and React sit on top.
Marks are written to an append-only, hash-chained ledger; Merkle roots are pinned in an external witness; certificates are salted hashes
that verify publicly from a QR code. Full write-up with ER diagram, normalisation and benchmarks: [docs/Veritas_Report.pdf](docs/Veritas_Report.pdf).

## Run it locally (Windows, portable Postgres in `.pg/`)
```powershell
.\start.ps1          # Postgres :5432, API :8000 (with background scheduler), frontend :5173
```
Open http://127.0.0.1:5173. Demo password for every seed user is `veritas2026`:
`admin@rvce.example`, `rao@` / `iyer@` / `hegde@rvce.example` (faculty; hegde is the HOD/checker), `asha@` / `bharat@` / `chitra@rvce.example` (students).

Fresh database, in this order: `schema.sql`, `seed.sql`, `app_bootstrap.sql`, `demo_data.sql` (`app_bootstrap.sql` is idempotent and
installs the application layer: notifications, run log, stored PDFs, throttling, institutions).
`.pg/` is about 0.9 GB; if this folder is synced by OneDrive, exclude `.pg`, it slows everything down.

## Run it with Docker (HTTPS, production-style)
```bash
cp .env.example .env      # set the passwords and secret; VERITAS_DOMAIN for a real certificate
docker compose up -d --build
psql ... -f ops/create_admin.sql   # first administrator (or VERITAS_DEMO=1 for demo users)
```
Postgres + API + Caddy (automatic TLS, `/api` proxied). The witness is a git repo in a volume; set `WITNESS_GIT_REMOTE` so every anchor is pushed
somewhere the database administrator does not control, which is what makes the witness external. The Docker stack is untested in the development
environment (no Docker daemon there); the files are syntax-checked.

## What it does
| Area | Features |
|---|---|
| Marks | Entry with optimistic version check, freeze, change request, maker-checker approval, apply with request id, CSV import and export |
| Integrity | Seal Merkle batches, anchor to a file or git witness, inclusion proofs, **scheduled** verify / seal+anchor / re-score, failures notify every admin (in-app, webhook, e-mail) |
| Anomalies | IsolationForest plus rules; each alert says why it fired; checkers confirm or dismiss; model version recorded |
| Certificates | Custom certificates and ledger-built **transcripts**; PDF with scan-to-verify **QR**, stored write-once; public verifier works from the QR alone |
| Disclosure | A student exports a proof of one revision; `verify_disclosure.py proof.json` checks it offline without revealing other marks |
| Notifications | Requests, decisions, mark changes, alerts, certificates, integrity failures |
| Security | Row-level security per role **and per institution**, login throttling, per-session CSRF token, random session secret, optional HTTPS-only cookies |
| Operations | `ops/backup_restore.py` (backs up only a verified ledger; every restore proves itself), Docker Compose, GitHub Actions CI |

Configuration (environment): `SESSION_SECRET`, `SESSION_HTTPS=1`, `WITNESS_TYPE=file|git|immudb`, `WITNESS_PATH`, `WITNESS_GIT_DIR`, `WITNESS_GIT_REMOTE`,
`VERITAS_VERIFY_EVERY` / `VERITAS_ANCHOR_EVERY` / `VERITAS_SCORE_EVERY` (seconds, 0 = off), `VERITAS_SCHEDULER=0`, `INTEGRITY_WEBHOOK`, `SMTP_HOST` + `ALERT_EMAIL_TO`,
`LOGIN_MAX_FAILS`, `VERITAS_PUBLIC_URL`, `CORS_ORIGINS`.

## How it works
- `mark_revisions` is append-only and hash-chained per course by a trigger; `apply_change()` is the only write path for marks.
- After `freeze_at`, edits need a request approved by a different faculty checker.
- `seal_batch()` builds Merkle batches (`merkle.py` matches the SQL exactly); `anchor_service.py` copies roots to the witness.
- Row-level security limits each role to its own data; certificates store only `sha256(salt || content digest)`.

## Tests (all pass)
```bash
export PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=postgres      # psql on PATH
bash run_tests.sh              # 84 ledger tests + 25 application-layer tests (scratch databases)
python python_tests.py         # 11 independent cross-checks and attacks
python concurrency_test.py     # 3
python api_tests.py            # 32 API end-to-end tests (own database, own API on :8100)
python ops/test_backup_restore.py   # 6
python e2e_test.py             # 12 browser tests in Chrome (own database, API :8200, build :4273)
```
Every suite builds its own scratch database; none touches the real `veritas` database. Benchmarks: `results/bench_results.md`.
Regenerate the report and diagrams with `python docs/make_docs.py`.

## Videos
`brag-output/veritas_full_demo.mp4` (1:30 walkthrough including CSV import, notifications, scheduled checks, transcripts with QR, offline proofs and a second institution),
`brag-output/brag.mp4` (21 s launch clip), recorded by the scripts in `brag-output/work/`.

## Known limits
- The witness is external only when pushed to a remote the DBA does not control; on one machine it is tamper-evident, not tamper-proof. The immudb backend is untested.
- Revisions after the last anchor are not pinned until the next anchor (the scheduler shortens the window; default 15 minutes).
- No single sign-on; accounts use bcrypt passwords with throttling.
- The witness is one file or git repo shared by all institutions (records carry the institution slug; each admin verifies only their own).
- A transcript PDF is stored when issued; regenerating it later from changed marks would (correctly) not verify.
