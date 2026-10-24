import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }
function fmtv(v) { return v == null ? '—' : Number(v).toFixed(2); }

const STATUS_BADGE = {
  pending: 'badge-amber',
  approved: 'badge-green',
  rejected: 'badge-red',
  applied: 'badge-blue',
};

export function Requests({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState(null);
  const toast = useToast();

  const isChecker = user.can_approve;
  const isAdmin = user.role === 'admin';

  async function load() {
    setLoading(true);
    try { setRows(await api.requests()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function decide(id, approve) {
    setDeciding(id);
    try {
      await api.decideRequest(id, approve);
      toast(approve ? 'Request approved ✓' : 'Request rejected', approve ? 'success' : 'info');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setDeciding(null); }
  }

  const pending = rows.filter(r => r.status === 'pending');
  const decided = rows.filter(r => r.status !== 'pending');

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">{isChecker || isAdmin ? 'Approve Change Requests' : 'Change Requests'}</div>
          <div className="page-subtitle">Maker-checker workflow for frozen mark edits</div>
        </div>
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Pending</div>
            <div className="card-value" style={{ color: 'var(--warn)' }}>{pending.length}</div>
          </div>
          <div className="card">
            <div className="card-title">Approved</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{rows.filter(r => r.status === 'approved').length}</div>
          </div>
          <div className="card">
            <div className="card-title">Applied</div>
            <div className="card-value" style={{ color: 'var(--info)' }}>{rows.filter(r => r.status === 'applied').length}</div>
          </div>
          <div className="card">
            <div className="card-title">Rejected</div>
            <div className="card-value" style={{ color: 'var(--danger)' }}>{rows.filter(r => r.status === 'rejected').length}</div>
          </div>
        </div>

        {/* Pending section */}
        {(isChecker || isAdmin) && pending.length > 0 && (
          <div className="mb-6">
            <div className="section-title">⏳ Awaiting Decision</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {pending.map(r => (
                <div key={r.request_id} className="card" style={{ borderLeft: '3px solid var(--warn)' }}>
                  <div className="flex-between mb-4">
                    <div>
                      <span className="badge badge-amber" style={{ marginRight: 8 }}>Pending</span>
                      <span style={{ fontWeight: 600 }}>Request #{r.request_id}</span>
                    </div>
                    <span className="text-sm text-muted">{fmt(r.requested_at)}</span>
                  </div>
                  <div className="grid-2" style={{ marginBottom: 12 }}>
                    <div>
                      <div className="text-sm text-muted">Course / Type</div>
                      <div style={{ fontWeight: 600 }}>
                        <span className="badge badge-blue" style={{ marginRight: 6 }}>Course {r.course_id}</span>
                        <span className="badge badge-purple">{r.assessment_type}</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted">Value change</div>
                      <div style={{ fontWeight: 600 }}>
                        <span style={{ color: 'var(--text-2)' }}>{fmtv(r.current_value)}</span>
                        <span style={{ color: 'var(--text-3)', margin: '0 6px' }}>→</span>
                        <span style={{ color: 'var(--accent)', fontSize: '1.05rem' }}>{fmtv(r.proposed_value)}</span>
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: '0.83rem', color: 'var(--text-2)', marginBottom: 14, padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
                    <strong style={{ color: 'var(--text-1)' }}>Reason:</strong> {r.reason}
                  </div>
                  {(isChecker || isAdmin) && r.requested_by !== user.user_id && (
                    <div className="flex-row">
                      <button id={`approve-${r.request_id}`} className="btn btn-success btn-sm" disabled={deciding === r.request_id}
                        onClick={() => decide(r.request_id, true)}>
                        {deciding === r.request_id ? <span className="spinner" /> : '✓ Approve'}
                      </button>
                      <button id={`reject-${r.request_id}`} className="btn btn-danger btn-sm" disabled={deciding === r.request_id}
                        onClick={() => decide(r.request_id, false)}>
                        ✗ Reject
                      </button>
                    </div>
                  )}
                  {r.requested_by === user.user_id && (
                    <div className="text-sm text-muted">You submitted this request — awaiting another checker</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* History table */}
        <div className="section-title">📋 All Requests</div>
        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : rows.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">📝</div><div className="empty-state-text">No requests yet</div></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Course</th>
                  <th>Type</th>
                  <th>Current → Proposed</th>
                  <th>Reason</th>
                  <th>Status</th>
                  <th>Requested</th>
                  <th>Decided</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.request_id}>
                    <td className="font-mono text-muted">{r.request_id}</td>
                    <td><span className="badge badge-blue">#{r.course_id}</span></td>
                    <td><span className="badge badge-purple">{r.assessment_type}</span></td>
                    <td>
                      <span className="text-muted">{fmtv(r.current_value)}</span>
                      <span className="text-muted" style={{ margin: '0 4px' }}>→</span>
                      <strong style={{ color: 'var(--accent)' }}>{fmtv(r.proposed_value)}</strong>
                    </td>
                    <td style={{ maxWidth: 220 }}><div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-2)', fontSize: '0.82rem' }}>{r.reason}</div></td>
                    <td><span className={`badge ${STATUS_BADGE[r.status] || 'badge-gray'}`}>{r.status}</span></td>
                    <td className="text-muted text-sm">{fmt(r.requested_at)}</td>
                    <td className="text-muted text-sm">{fmt(r.decided_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
