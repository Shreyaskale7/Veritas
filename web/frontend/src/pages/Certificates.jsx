import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }

function IssueModal({ students, user, onClose, onDone }) {
  const [studentId, setStudentId] = useState('');
  const [type, setType] = useState('');
  const [mode, setMode] = useState('custom');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === 'transcript') await api.issueTranscript({ student_id: parseInt(studentId) });
      else await api.issueCert({ student_id: parseInt(studentId), cert_type: type, content });
      toast('Certificate issued, PDF with QR stored ✓', 'success');
      onDone();
    } catch (err) { toast(err.message, 'error'); }
    finally { setLoading(false); }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Issue Certificate</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            {user.can_approve && (
              <div className="form-group">
                <label className="form-label">Document</label>
                <select id="cert-mode" className="form-input" value={mode} onChange={e => setMode(e.target.value)}>
                  <option value="custom">Custom certificate</option>
                  <option value="transcript">Transcript (built from the ledger's marks)</option>
                </select>
              </div>
            )}
            <div className="form-group">
              <label className="form-label">Student</label>
              <select id="cert-student" className="form-input" value={studentId}
                onChange={e => setStudentId(e.target.value)} required>
                <option value="">Select student…</option>
                {students.map(s => <option key={s.user_id} value={s.user_id}>{s.name} ({s.usn})</option>)}
              </select>
            </div>
            {mode === 'custom' && (<>
            <div className="form-group">
              <label className="form-label">Certificate type</label>
              <input id="cert-type" className="form-input" placeholder="e.g. Transcript, Bonafide, NOC…"
                value={type} onChange={e => setType(e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">Content / notes</label>
              <textarea id="cert-content" className="form-input" rows={4}
                placeholder="Full certificate text…"
                value={content} onChange={e => setContent(e.target.value)} required />
            </div>
            </>)}
            {mode === 'transcript' && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', lineHeight: 1.6 }}>
                The transcript text (every completed course, grade points and SGPA) is generated from the ledger at this moment,
                hashed, issued as a certificate and stored as a PDF with a scan-to-verify QR code.
              </div>
            )}
            <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', lineHeight: 1.5 }}>
              A SHA-256 digest of the content will be stored along with a random salt. The salt + cert ID form the QR payload.
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button id="cert-submit" type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <span className="spinner" /> : '🎓 Issue Certificate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CertDetail({ cert, onClose, onRevoke, canRevoke }) {
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function revoke() {
    if (!confirm('Revoke this certificate? This cannot be undone.')) return;
    setLoading(true);
    try { await onRevoke(cert.cert_id); onClose(); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  const qr = `${cert.cert_id}|${cert.salt}`;

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <div className="modal-title">Certificate Details</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="cert-card" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
              {cert.cert_type}
            </div>
            <div style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 4 }}>Certificate #{cert.cert_id.slice(0, 8)}…</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-2)' }}>Issued {fmt(cert.issued_at)}</div>
            <div style={{ marginTop: 10 }}>
              {cert.status === 'valid'
                ? <span className="badge badge-green">✓ Valid</span>
                : <span className="badge badge-red">✗ Revoked</span>}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Certificate ID</label>
            <div className="font-mono" style={{ color: 'var(--accent)', wordBreak: 'break-all', fontSize: '0.72rem', padding: '8px 12px', background: 'rgba(99,102,241,0.08)', borderRadius: 8 }}>
              {cert.cert_id}
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">QR Payload (cert_id|salt)</label>
            <div className="font-mono" style={{ wordBreak: 'break-all', fontSize: '0.72rem', padding: '8px 12px', background: 'rgba(255,255,255,0.05)', borderRadius: 8, color: 'var(--text-2)' }}>
              {qr}
            </div>
          </div>
          {cert.revoked_at && (
            <div style={{ fontSize: '0.8rem', color: 'var(--danger)' }}>Revoked at: {fmt(cert.revoked_at)}</div>
          )}
        </div>
        <div className="modal-footer">
          {canRevoke && cert.status === 'valid' && (
            <button className="btn btn-danger" onClick={revoke} disabled={loading}>
              {loading ? <span className="spinner" /> : 'Revoke Certificate'}
            </button>
          )}
          {cert.has_pdf && <button className="btn btn-ghost" onClick={() => api.openCertPdf(cert.cert_id).catch(e => toast(e.message, 'error'))}>📄 View PDF</button>}
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

export function Certificates({ user }) {
  const [certs, setCerts] = useState([]);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [issueOpen, setIssueOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const toast = useToast();

  const isFaculty = user.role === 'faculty';
  const canRevoke = isFaculty && user.can_approve;

  async function load() {
    setLoading(true);
    try {
      const [c, dir] = await Promise.all([api.certificates(), (isFaculty || user.role === 'admin') ? api.directory() : Promise.resolve({ students: [] })]);
      setCerts(c);
      setStudents(dir.students || []);
    } catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  const valid = certs.filter(c => c.status === 'valid').length;
  const revoked = certs.filter(c => c.status === 'revoked').length;

  async function handleRevoke(id) {
    await api.revokeCert(id);
    toast('Certificate revoked', 'success');
    load();
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Certificates</div>
          <div className="page-subtitle">Cryptographically hashed, publicly verifiable</div>
        </div>
        {isFaculty && (
          <button id="issue-cert-btn" className="btn btn-primary" onClick={() => setIssueOpen(true)}>
            🎓 Issue Certificate
          </button>
        )}
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Total</div>
            <div className="card-value" style={{ color: 'var(--accent)' }}>{certs.length}</div>
          </div>
          <div className="card">
            <div className="card-title">Valid</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{valid}</div>
          </div>
          <div className="card">
            <div className="card-title">Revoked</div>
            <div className="card-value" style={{ color: 'var(--danger)' }}>{revoked}</div>
          </div>
        </div>

        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : certs.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">🎓</div><div className="empty-state-text">No certificates yet</div></div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
            {certs.map(c => (
              <div key={c.cert_id} className="cert-card" style={{ cursor: 'pointer' }} onClick={() => setDetail(c)}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                  {c.cert_type}
                </div>
                <div style={{ fontWeight: 700, fontSize: '0.9rem', marginBottom: 2 }}>{c.cert_id.slice(0, 18)}…</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-2)', marginBottom: 10 }}>{fmt(c.issued_at)}</div>
                <div className="flex-between">
                  {c.status === 'valid'
                    ? <span className="badge badge-green">✓ Valid</span>
                    : <span className="badge badge-red">✗ Revoked</span>}
                  <span className="text-sm text-muted">View →</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {issueOpen && <IssueModal students={students} user={user} onClose={() => setIssueOpen(false)} onDone={() => { setIssueOpen(false); load(); }} />}
      {detail && <CertDetail cert={detail} onClose={() => setDetail(null)} onRevoke={handleRevoke} canRevoke={canRevoke} />}
    </div>
  );
}
