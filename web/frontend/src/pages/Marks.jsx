import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(v) { return v == null ? '—' : Number(v).toFixed(2); }
function fmtDate(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }

function ApplyModal({ mark, user, onClose, onDone }) {
  const [value, setValue] = useState(mark.current_value ?? '');
  const [reason, setReason] = useState('');
  const [reqId, setReqId] = useState('');
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.applyMark(mark.mark_id, {
        new_value: parseFloat(value),
        reason,
        expected_version: mark.version,
        request_id: reqId ? parseInt(reqId) : null,
      });
      toast('Mark updated and revision written ✓', 'success');
      onDone();
    } catch (err) {
      toast(err.message, 'error');
    } finally { setLoading(false); }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Edit Mark</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            <div style={{ fontSize: '0.82rem', color: 'var(--text-2)', lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-1)' }}>{mark.student_name}</strong> ({mark.usn})<br />
              {mark.course_code} · {mark.assessment_type} · max {fmt(mark.max_marks)}
            </div>
            <div className="form-group">
              <label className="form-label">New value</label>
              <input id="apply-value" className="form-input" type="number" step="0.5"
                min="0" max={mark.max_marks} value={value}
                onChange={e => setValue(e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">Reason (min 5 chars)</label>
              <textarea id="apply-reason" className="form-input" value={reason}
                onChange={e => setReason(e.target.value)} minLength={5} required />
            </div>
            {mark.frozen && (
              <div className="form-group">
                <label className="form-label">Approved Request ID <span style={{ color: 'var(--danger)' }}>*required (frozen)</span></label>
                <input id="apply-reqid" className="form-input" type="number" value={reqId}
                  onChange={e => setReqId(e.target.value)} required />
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button id="apply-submit" type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <span className="spinner" /> : 'Apply Change'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function RequestModal({ mark, user, onClose, onDone }) {
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.createRequest({ mark_id: mark.mark_id, proposed_value: parseFloat(value), reason });
      toast('Change request submitted ✓', 'success');
      onDone();
    } catch (err) {
      toast(err.message, 'error');
    } finally { setLoading(false); }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Request Mark Change</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            <div style={{ fontSize: '0.82rem', color: 'var(--text-2)', lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-1)' }}>{mark.student_name}</strong> ({mark.usn})<br />
              {mark.course_code} · {mark.assessment_type} · current: {fmt(mark.current_value)}
            </div>
            <div className="form-group">
              <label className="form-label">Proposed value</label>
              <input id="req-value" className="form-input" type="number" step="0.5"
                min="0" max={mark.max_marks} value={value}
                onChange={e => setValue(e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">Reason (min 5 chars)</label>
              <textarea id="req-reason" className="form-input" value={reason}
                onChange={e => setReason(e.target.value)} minLength={5} required />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button id="req-submit" type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <span className="spinner" /> : 'Submit Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function Marks({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [applyMark, setApplyMark] = useState(null);
  const [requestMark, setRequestMark] = useState(null);
  const [importing, setImporting] = useState(false);
  const toast = useToast();

  const isStudent = user.role === 'student';
  const isFaculty = user.role === 'faculty';

  async function load() {
    setLoading(true);
    try { setRows(await api.marks()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function handleImport(e) {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    setImporting(true);
    try {
      const r = await api.importMarks(file);
      toast(`Imported ${r.imported} mark(s)${r.failed ? `, ${r.failed} row(s) failed: ${r.results.filter(x => !x.ok).slice(0, 2).map(x => `line ${x.line}: ${x.error}`).join('; ')}` : ''}`, r.failed ? 'info' : 'success');
      load();
    } catch (err) { toast(err.message, 'error'); }
    finally { setImporting(false); }
  }

  const filtered = rows.filter(r =>
    !filter || JSON.stringify(r).toLowerCase().includes(filter.toLowerCase())
  );

  // Group by course for student view
  const byCourse = isStudent
    ? filtered.reduce((acc, r) => {
        const k = `${r.course_code} — ${r.title}`;
        if (!acc[k]) acc[k] = [];
        acc[k].push(r);
        return acc;
      }, {})
    : null;

  // Stats
  const total = rows.length;
  const entered = rows.filter(r => r.current_value != null).length;
  const frozen = rows.filter(r => r.frozen).length;
  const myFaculty = !isStudent ? [...new Set(rows.filter(r => r.faculty_id === user.user_id).map(r => r.course_code))].length : 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">{isStudent ? 'My Marks' : 'Marks Entry'}</div>
          <div className="page-subtitle">{isStudent ? 'Your academic record — cryptographically secured' : 'Write marks to the tamper-evident ledger'}</div>
        </div>
        <div className="flex-row">
          {isFaculty && (
            <label id="import-btn" className="btn btn-ghost" title="CSV columns: usn, course_code, assessment_type, value, reason" style={{ cursor: 'pointer' }}>
              {importing ? <span className="spinner" /> : '⬆ Import CSV'}
              <input type="file" accept=".csv,text/csv" onChange={handleImport} style={{ display: 'none' }} />
            </label>
          )}
          <button id="export-btn" className="btn btn-ghost" onClick={() => api.exportMarks().catch(e => toast(e.message, 'error'))}>⬇ Export CSV</button>
          <input className="form-input" placeholder="🔍 Filter…" value={filter}
            onChange={e => setFilter(e.target.value)} style={{ width: 220 }} />
        </div>
      </div>

      <div className="page-body">
        {/* Stats */}
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Total marks</div>
            <div className="card-value" style={{ color: 'var(--accent)' }}>{total}</div>
          </div>
          <div className="card">
            <div className="card-title">Entered</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{entered}</div>
            <div className="card-sub">{total ? Math.round(100 * entered / total) : 0}% complete</div>
          </div>
          <div className="card">
            <div className="card-title">Frozen</div>
            <div className="card-value" style={{ color: 'var(--warn)' }}>{frozen}</div>
            <div className="card-sub">assessment locked</div>
          </div>
          {!isStudent && (
            <div className="card">
              <div className="card-title">My courses</div>
              <div className="card-value" style={{ color: 'var(--info)' }}>{myFaculty}</div>
            </div>
          )}
        </div>

        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : isStudent && byCourse ? (
          // Student grouped view
          Object.entries(byCourse).map(([course, items]) => (
            <div key={course} style={{ marginBottom: 24 }}>
              <div className="section-title">
                <span>📚</span> {course}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Assessment</th>
                      <th>Score</th>
                      <th>Max</th>
                      <th>%</th>
                      <th>Status</th>
                      <th>Last updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(r => {
                      const pct = r.current_value != null && r.max_marks ? (100 * r.current_value / r.max_marks).toFixed(1) : null;
                      return (
                        <tr key={r.mark_id}>
                          <td><span className="badge badge-purple">{r.assessment_type}</span></td>
                          <td style={{ fontSize: '1.1rem', fontWeight: 700 }}>{fmt(r.current_value)}</td>
                          <td className="text-muted">{fmt(r.max_marks)}</td>
                          <td>{pct ? <span style={{ color: pct >= 60 ? 'var(--success)' : pct >= 40 ? 'var(--warn)' : 'var(--danger)' }}>{pct}%</span> : '—'}</td>
                          <td>{r.frozen ? <span className="badge badge-amber">🔒 Frozen</span> : <span className="badge badge-green">Open</span>}</td>
                          <td className="text-muted text-sm">{fmtDate(r.updated_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        ) : (
          // Faculty / admin flat view
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Student</th>
                  <th>USN</th>
                  <th>Course</th>
                  <th>Type</th>
                  <th>Value</th>
                  <th>Max</th>
                  <th>Freeze</th>
                  <th>Updated</th>
                  {!isStudent && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => {
                  const canEdit = !isStudent && r.faculty_id === user.user_id;
                  return (
                    <tr key={r.mark_id}>
                      <td style={{ fontWeight: 500 }}>{r.student_name}</td>
                      <td className="font-mono">{r.usn}</td>
                      <td><span className="badge badge-blue">{r.course_code}</span></td>
                      <td><span className="badge badge-purple">{r.assessment_type}</span></td>
                      <td style={{ fontWeight: 700 }}>{fmt(r.current_value)}</td>
                      <td className="text-muted">{fmt(r.max_marks)}</td>
                      <td>{r.frozen ? <span className="badge badge-amber">🔒 Frozen</span> : <span className="badge badge-green">Open</span>}</td>
                      <td className="text-muted text-sm">{fmtDate(r.updated_at)}</td>
                      {!isStudent && (
                        <td>
                          {canEdit && !r.frozen && (
                            <button className="btn btn-primary btn-sm" onClick={() => setApplyMark(r)}>Edit</button>
                          )}
                          {canEdit && r.frozen && (
                            <div className="flex-row">
                              <button className="btn btn-ghost btn-sm" onClick={() => setRequestMark(r)}>Request</button>
                              <button className="btn btn-primary btn-sm" onClick={() => setApplyMark(r)}>Apply</button>
                            </div>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {applyMark && <ApplyModal mark={applyMark} user={user} onClose={() => setApplyMark(null)} onDone={() => { setApplyMark(null); load(); }} />}
      {requestMark && <RequestModal mark={requestMark} user={user} onClose={() => setRequestMark(null)} onDone={() => { setRequestMark(null); load(); }} />}
    </div>
  );
}
