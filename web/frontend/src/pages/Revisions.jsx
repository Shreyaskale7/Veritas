import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }
function fmtv(v) { return v == null ? '—' : Number(v).toFixed(2); }

export function Revisions({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [courseFilter, setCourseFilter] = useState('');
  const [courses, setCourses] = useState([]);
  const [health, setHealth] = useState({});   // course_id -> true/false, admins only (it comes from a real verification)
  const toast = useToast();

  async function load(cid) {
    setLoading(true);
    try { setRows(await api.revisions(cid || null)); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    if (user.role === 'admin' || user.role === 'faculty') {
      api.directory().then(d => setCourses(d.courses || [])).catch(() => {});
    }
    if (user.role === 'admin') {
      api.integrity().then(d => setHealth(Object.fromEntries(d.chains.map(c => [c.cid, c.chain_ok && c.marks_ok && c.batches_ok])))).catch(() => {});
    }
    load(null);
  }, []);

  function handleCourseChange(v) {
    setCourseFilter(v);
    load(v);
  }

  // Group by course for the chain viz
  const byCourse = rows.reduce((acc, r) => {
    if (!acc[r.course_id]) acc[r.course_id] = [];
    acc[r.course_id].push(r);
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Ledger / Audit Trail</div>
          <div className="page-subtitle">Append-only, hash-chained revision history</div>
        </div>
        {courses.length > 0 && (
          <select className="form-input" value={courseFilter}
            onChange={e => handleCourseChange(e.target.value)} style={{ width: 220 }}>
            <option value="">All courses</option>
            {courses.map(c => <option key={c.course_id} value={c.course_id}>{c.course_code} — {c.title}</option>)}
          </select>
        )}
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Total revisions</div>
            <div className="card-value" style={{ color: 'var(--accent)' }}>{rows.length}</div>
          </div>
          <div className="card">
            <div className="card-title">Courses</div>
            <div className="card-value" style={{ color: 'var(--info)' }}>{Object.keys(byCourse).length}</div>
          </div>
          <div className="card">
            <div className="card-title">Via request</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{rows.filter(r => r.request_id).length}</div>
          </div>
        </div>

        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : rows.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">🔗</div><div className="empty-state-text">No revisions yet</div></div>
        ) : (
          <>
            {/* Chain visualization */}
            {Object.entries(byCourse).map(([cid, revs]) => (
              <div key={cid} style={{ marginBottom: 28 }}>
                <div className="section-title">
                  <span>🔗</span> Course {cid} chain — {revs.length} revision(s)
                  {health[cid] === true && <span className="badge badge-green" style={{ marginLeft: 8 }}>Verified intact</span>}
                  {health[cid] === false && <span className="badge badge-red" style={{ marginLeft: 8 }}>CHAIN BROKEN</span>}
                  {health[cid] === undefined && <span className="badge badge-gray" style={{ marginLeft: 8 }}>Hash-chained</span>}
                </div>
                <div className="chain-row">
                  {revs.slice(0, 8).map((r, i) => (
                    <div key={r.revision_id} style={{ display: 'flex', alignItems: 'center' }}>
                      <div className="chain-block">
                        <div className="chain-block-seq">#{r.seq}</div>
                        <div style={{ fontSize: '0.72rem', fontWeight: 600, marginTop: 2 }}>
                          {fmtv(r.old_value)} → <span style={{ color: 'var(--accent)' }}>{fmtv(r.new_value)}</span>
                        </div>
                        <div className="chain-block-hash" title={r.row_hash}>{r.row_hash.slice(0, 16)}…</div>
                        {r.request_id && <div style={{ marginTop: 4 }}><span className="badge badge-green" style={{ fontSize: '0.65rem' }}>via request</span></div>}
                      </div>
                      {i < revs.slice(0, 8).length - 1 && <div className="chain-arrow">→</div>}
                    </div>
                  ))}
                  {revs.length > 8 && (
                    <div className="chain-arrow" style={{ fontSize: '0.8rem', color: 'var(--text-3)' }}>+{revs.length - 8} more</div>
                  )}
                </div>
              </div>
            ))}

            {/* Full table */}
            <div className="section-title">📋 Full Revision Log</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Seq</th><th>Course</th><th>Mark</th>
                    <th>Old → New</th><th>Reason</th>
                    <th>Via request</th><th>Changed at</th>
                    <th>Row hash</th><th>Proof</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.revision_id}>
                      <td style={{ fontWeight: 700, color: 'var(--accent)' }}>#{r.seq}</td>
                      <td><span className="badge badge-blue">#{r.course_id}</span></td>
                      <td className="font-mono text-muted">#{r.mark_id}</td>
                      <td>
                        <span className="text-muted">{fmtv(r.old_value)}</span>
                        <span className="text-muted" style={{ margin: '0 4px' }}>→</span>
                        <strong style={{ color: 'var(--accent)' }}>{fmtv(r.new_value)}</strong>
                      </td>
                      <td style={{ maxWidth: 200 }}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem', color: 'var(--text-2)' }}>{r.reason}</div>
                      </td>
                      <td>{r.request_id ? <span className="badge badge-green">#{r.request_id}</span> : <span className="text-muted">—</span>}</td>
                      <td className="text-muted text-sm">{fmt(r.changed_at)}</td>
                      <td className="font-mono" style={{ fontSize: '0.65rem', color: 'var(--text-3)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.row_hash}>{r.row_hash.slice(0, 16)}…</td>
                      <td>
                        <button className="btn btn-ghost btn-sm" title="Download a proof of just this revision, checkable offline"
                          onClick={() => api.downloadProof(r.revision_id).then(() => toast('Proof saved. Check it with verify_disclosure.py', 'success')).catch(e => toast(e.message, 'error'))}>
                          Share proof
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
