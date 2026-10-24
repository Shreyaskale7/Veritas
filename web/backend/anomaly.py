"""Isolation Forest scorer over revision timeline features (SRS FR-7)."""
from __future__ import annotations

import json

import numpy as np
from sklearn.ensemble import IsolationForest

from db import admin_conn, execute, fetchall

FEATURE_SQL = """
SELECT r.revision_id,
       r.new_value - coalesce(r.old_value, 0) AS delta,
       extract(epoch FROM r.changed_at
               - lag(r.changed_at) OVER (PARTITION BY r.course_id ORDER BY r.seq)) AS secs_since_prev,
       CASE WHEN r.changed_at >= a.freeze_at THEN 1 ELSE 0 END AS after_freeze,
       CASE WHEN r.request_id IS NOT NULL THEN 1 ELSE 0 END AS via_request,
       extract(hour FROM r.changed_at) AS hour_of_day,
       CASE WHEN a.max_marks > 0 AND (r.new_value = 0 OR r.new_value = a.max_marks) THEN 1 ELSE 0 END AS boundary
  FROM mark_revisions r
  JOIN marks m ON m.mark_id = r.mark_id
  JOIN assessments a ON a.course_id = m.course_id AND a.type = m.assessment_type
 ORDER BY r.revision_id
"""

COLS = ["delta", "secs_since_prev", "after_freeze", "via_request", "hour_of_day", "boundary"]


def _rule_score(row) -> float:
    s = 0.0
    delta = abs(float(row["delta"] or 0))
    if delta >= 15:
        s += 0.35
    if row["after_freeze"]:
        s += 0.3
    if not row["via_request"] and row["after_freeze"]:
        s += 0.2
    if row["boundary"]:
        s += 0.15
    hour = int(row["hour_of_day"] or 12)
    if hour < 6 or hour >= 22:
        s += 0.2
    secs = row["secs_since_prev"]
    if secs is not None and float(secs) < 5:
        s += 0.15
    return min(s, 1.0)


def score_revisions(contamination: float = 0.15) -> dict:
    with admin_conn() as conn:
        rows = fetchall(conn, FEATURE_SQL)
        if len(rows) < 4:
            return {"scored": 0, "alerted": 0, "note": "need at least 4 revisions"}

        X = np.array(
            [
                [
                    float(r["delta"] or 0),
                    float(r["secs_since_prev"] if r["secs_since_prev"] is not None else 3600),
                    float(r["after_freeze"] or 0),
                    float(r["via_request"] or 0),
                    float(r["hour_of_day"] or 12),
                    float(r["boundary"] or 0),
                ]
                for r in rows
            ],
            dtype=float,
        )
        forest = IsolationForest(contamination=contamination, random_state=7)
        forest.fit(X)
        raw = -forest.score_samples(X)
        lo, hi = float(raw.min()), float(raw.max())
        span = hi - lo if hi > lo else 1.0
        if_norm = (raw - lo) / span

        alerted = 0
        for r, ifs in zip(rows, if_norm):
            rule = _rule_score(r)
            combined = 0.7 * float(ifs) + 0.3 * rule
            if combined < 0.62:
                continue
            top = sorted(
                (
                    (name, abs(float(r[name] or 0) if name != "secs_since_prev" else float(r[name] or 3600)))
                    for name in COLS
                ),
                key=lambda t: t[1],
                reverse=True,
            )[:3]
            execute(
                conn,
                "SELECT record_anomaly_alert(%s::bigint, %s::text, %s::real, %s::text)",
                (
                    r["revision_id"],
                    "isolation_forest+rules/v1",   # model version travels with every alert
                    float(combined),
                    json.dumps({"if": float(ifs), "rule": rule, "top": top}),
                ),
            )
            alerted += 1
        return {"scored": len(rows), "alerted": alerted}
