# Veritas brag plan

**What it is:** a marks and certificate ledger where PostgreSQL itself refuses to let a grade be changed quietly.
**For:** exam sections and faculty who need marks nobody can rewrite after the fact.
**Angle:** "Marks get changed. Quietly." -> Veritas makes the quiet part impossible. Tone: `polished` with a dry hook.
**Hook (0-2.5s):** "Marks get changed." / "Quietly."
**Identity:** bg #070b14, accent #6366f1, success #10b981, danger #f43f5e, Inter. Real app pages are used live.
**Format:** landscape 1920x1080, 30fps, 21.5s.

| # | Time | Scene | Source |
|---|---|---|---|
| 1 | 0-2.5 | Hook cards | designed |
| 2 | 2.5-5.5 | Reveal: Veritas + one-line claim | designed |
| 3 | 5.5-9.5 | Ledger: every edit is a hash-chained revision | LIVE app /revisions |
| 4 | 9.5-14.0 | Tamper attempts caught (real test names) | designed from tests.sql results |
| 5 | 14.0-18.0 | Integrity dashboard, all chains verified | LIVE app /integrity |
| 6 | 18.0-21.5 | Outro: stack + course | designed |

No invented numbers: "84 tests" and the attack cases come from results/sql_tests.tsv; 3 chains / 15 revisions are what the live app shows.
