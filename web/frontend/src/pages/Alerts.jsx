import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }
function fmtv(v) { return v == null ? '—' : Number(v).toFixed(2); }

const FEATURE_TEXT = {
  delta: v => `Large change of ${Number(v).toFixed(1)} marks`,
  secs_since_prev: v => `Edited ${Number(v) < 3600 ? Math.round(v) + ' s' : 'long'} after the previous revision of this course`,
  after_freeze: () => 'Made after the assessment was frozen',
  via_request: () => 'Applied through an approved change request',
  hour_of_day: v => `Made at ${String(Math.round(v)).padStart(2, '0')}:00, outside normal working hours`,
  boundary: () => 'New value is exactly 0 or the maximum',
};

const STATUS_COLOR = { open: 'badge-amber', confirmed: 'badge-red', dismissed: 'badge-gray' };

function ScoreBar({ score }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.8 ? 'var(--danger)' : score >= 0.65 ? 'var(--warn)' : 'var(--success)';
  return (
    <div className="flex-row" style={{ gap: 8 }}>
      <div className="score-bar-wrap">
        <div className="score-bar" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span style={{ fontSize: '0.8rem', fontWeight: 700, color }}>{pct}%</span>
    </div>
  );
}

export function Alerts({ user }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [reviewing, setReviewing] = useState(null);
  const [courseFilter, setCourseFilter] = useState('');
  const toast = useToast();

  async function load() {
    setLoading(true);
    try { setAlerts(await api.alerts()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function runScorer() {
    setScoring(true);
    try {
      const res = await api.scoreAnomalies();
      toast(`Scored ${res.scored} revisions, raised ${res.alerted} new alert(s)${res.note ? ` — ${res.note}` : ''}`, 'info');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setScoring(false); }
  }

  async function handleReview(id, status) {
    setReviewing(id);
    try {
      await api.reviewAlert(id, status);
      toast(`Alert ${status} ✓`, 'success');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setReviewing(null); }
  }

  const courseCodes = [...new Set(alerts.map(a => a.course_code).filter(Boolean))];
  const shown = alerts.filter(a => !courseFilter || a.course_code === courseFilter);
  const open = shown.filter(a => a.status === 'open');
  const closed = shown.filter(a => a.status !== 'open');

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Anomaly Alerts</div>
          <div className="page-subtitle">ML-detected suspicious mark revisions (IsolationForest + rules)</div>
        </div>
        <div className="flex-row">
          <select id="alert-course" className="form-input" value={courseFilter} onChange={e => setCourseFilter(e.target.value)} style={{ width: 170 }}>
            <option value="">All courses</option>
            {courseCodes.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <button id="run-scorer-btn" className="btn btn-primary" onClick={runScorer} disabled={scoring}>
            {scoring ? <><span className="spinner" /> Scoring…</> : '🤖 Run Anomaly Scorer'}
          </button>
        </div>
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Open alerts</div>
            <div className="card-value" style={{ color: open.length > 0 ? 'var(--danger)' : 'var(--success)' }}>
              {open.length}
            </div>
          </div>
          <div className="card">
            <div className="card-title">Confirmed</div>
            <div className="card-value" style={{ color: 'var(--danger)' }}>
              {alerts.filter(a => a.status === 'confirmed').length}
            </div>
          </div>
          <div className="card">
            <div className="card-title">Dismissed</div>
            <div className="card-value" style={{ color: 'var(--text-2)' }}>
              {alerts.filter(a => a.status === 'dismissed').length}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : alerts.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">✅</div>
            <div className="empty-state-text">No anomaly alerts — click "Run Anomaly Scorer" to analyse revisions</div>
          </div>
        ) : (
          <>
            {open.length > 0 && (
              <div className="mb-6">
                <div className="section-title">⚠️ Open Alerts</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {open.map(a => {
                    let features = {};
                    try { features = JSON.parse(a.top_features || '{}'); } catch {}
                    return (
                      <div key={a.alert_id} className="card" style={{ borderLeft: '3px solid var(--danger)' }}>
                        <div className="flex-between mb-4">
                          <div className="flex-row">
                            <span className="dot dot-red" />
                            <span style={{ fontWeight: 700 }}>Alert #{a.alert_id}</span>
                            <span className="badge badge-gray text-sm">{a.model_name}</span>
                          </div>
                          <span className="text-sm text-muted">{fmt(a.created_at)}</span>
                        </div>

                        <div className="grid-2" style={{ marginBottom: 14 }}>
                          <div>
                            <div className="text-sm text-muted mb-1">Anomaly Score</div>
                            <ScoreBar score={a.score} />
                          </div>
                          <div>
                            <div className="text-sm text-muted mb-1">Revision</div>
                            <div style={{ fontSize: '0.85rem' }}>
                              {a.course_code || `Course ${a.course_id}`} · Seq #{a.seq} · Mark #{a.mark_id}{a.usn ? ` · ${a.usn}` : ''}
                            </div>
                          </div>
                        </div>

                        <div style={{ marginBottom: 12 }}>
                          <div className="text-sm text-muted mb-1">Mark change</div>
                          <div style={{ fontWeight: 600 }}>
                            <span style={{ color: 'var(--text-2)' }}>{fmtv(a.old_value)}</span>
                            <span style={{ color: 'var(--text-3)', margin: '0 6px' }}>→</span>
                            <span style={{ color: a.new_value > (a.old_value || 0) ? 'var(--success)' : 'var(--danger)', fontSize: '1.05rem' }}>{fmtv(a.new_value)}</span>
                          </div>
                          {a.reason && <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', marginTop: 4 }}>"{a.reason}"</div>}
                        </div>

                        {features.top && (
                          <div style={{ marginBottom: 12 }}>
                            <div className="text-sm text-muted mb-1">Why it was flagged</div>
                            <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.84rem', lineHeight: 1.7 }}>
                              {features.top.map(([name, val]) => <li key={name}>{(FEATURE_TEXT[name] || (() => name))(val)}</li>)}
                            </ul>
                            {features.if != null && (
                              <div className="text-sm text-muted" style={{ marginTop: 4 }}>
                                Model score {(features.if * 100).toFixed(0)}% · rule score {(features.rule * 100).toFixed(0)}%
                              </div>
                            )}
                          </div>
                        )}
                        {features.top && (
                          <div style={{ marginBottom: 14 }}>
                            <div className="text-sm text-muted mb-1">Top contributing features</div>
                            <div className="flex-row" style={{ flexWrap: 'wrap' }}>
                              {features.top.map(([name, val]) => (
                                <span key={name} className="badge badge-amber">{name}: {typeof val === 'number' ? val.toFixed(2) : val}</span>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="flex-row">
                          <button id={`confirm-${a.alert_id}`} className="btn btn-danger btn-sm"
                            disabled={reviewing === a.alert_id}
                            onClick={() => handleReview(a.alert_id, 'confirmed')}>
                            {reviewing === a.alert_id ? <span className="spinner" /> : '⚠ Confirm Tampering'}
                          </button>
                          <button id={`dismiss-${a.alert_id}`} className="btn btn-ghost btn-sm"
                            disabled={reviewing === a.alert_id}
                            onClick={() => handleReview(a.alert_id, 'dismissed')}>
                            Dismiss
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {closed.length > 0 && (
              <div>
                <div className="section-title">📋 Reviewed Alerts</div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>#</th><th>Model</th><th>Score</th><th>Course/Seq</th><th>Change</th><th>Status</th><th>Reviewed</th></tr>
                    </thead>
                    <tbody>
                      {closed.map(a => (
                        <tr key={a.alert_id}>
                          <td className="font-mono text-muted">{a.alert_id}</td>
                          <td className="text-sm text-muted">{a.model_name}</td>
                          <td style={{ width: 120 }}><ScoreBar score={a.score} /></td>
                          <td><span className="badge badge-blue">C{a.course_id}</span> #{a.seq}</td>
                          <td><span className="text-muted">{fmtv(a.old_value)}</span> → <strong>{fmtv(a.new_value)}</strong></td>
                          <td><span className={`badge ${STATUS_COLOR[a.status]}`}>{a.status}</span></td>
                          <td className="text-muted text-sm">{fmt(a.reviewed_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
