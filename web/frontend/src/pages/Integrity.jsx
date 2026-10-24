import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

function fmt(d) { return d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }

function ProofModal({ course, seq, onClose }) {
  const [proof, setProof] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api.proof(course, seq)
      .then(setProof)
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 580 }}>
        <div className="modal-header">
          <div className="modal-title">Inclusion Proof — Course {course}, Seq #{seq}</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {loading ? <div className="loader-center"><div className="spinner" /></div> : !proof ? (
            <div className="empty-state"><div className="empty-state-text">Not yet in a sealed batch</div></div>
          ) : (
            <>
              <div className="form-group">
                <label className="form-label">Row Hash (leaf)</label>
                <div className="font-mono" style={{ wordBreak: 'break-all', padding: '8px 12px', background: 'rgba(99,102,241,0.08)', borderRadius: 8, color: 'var(--accent)', fontSize: '0.7rem' }}>
                  {proof.row_hash}
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Merkle Path ({proof.path?.length ?? 0} steps)</label>
                {proof.path?.length === 0
                  ? <div className="text-muted text-sm">Single-leaf batch — no siblings needed</div>
                  : proof.path?.map(([side, hash], i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                      <span className="badge badge-purple">{side}</span>
                      <span className="font-mono" style={{ fontSize: '0.68rem', color: 'var(--text-2)', wordBreak: 'break-all' }}>{hash}</span>
                    </div>
                  ))
                }
              </div>
              <div style={{ padding: '10px 14px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 8, fontSize: '0.8rem', color: 'var(--success)' }}>
                ✓ This proof can be verified against the witnessed Merkle root without database access
              </div>
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

export function Integrity({ user }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sealing, setSealing] = useState(null);
  const [anchoring, setAnchoring] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [proofTarget, setProofTarget] = useState(null);
  const toast = useToast();

  async function load() {
    setLoading(true);
    try { setData(await api.integrity()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function doSeal(courseId) {
    setSealing(courseId);
    try {
      const r = await api.seal(courseId);
      toast(r.batch_id ? `Sealed → batch #${r.batch_id}` : 'Nothing new to seal', 'success');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setSealing(null); }
  }

  async function doAnchor() {
    setAnchoring(true);
    try {
      const r = await api.anchor();
      toast(`Anchored ${r.anchored} batch(es) to the ${r.witness} witness`, 'success');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setAnchoring(false); }
  }

  async function verifyNow() {
    setVerifying(true);
    try {
      const r = await api.verifyNow();
      toast(r.ok ? 'Verified: every chain, batch and the witness agree' : 'Verification FAILED: see the banner and your notifications', r.ok ? 'success' : 'error');
      load();
    } catch (e) { toast(e.message, 'error'); }
    finally { setVerifying(false); }
  }

  const allOk = data?.chains?.every(c => c.chain_ok && c.marks_ok && c.batches_ok);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Integrity Dashboard</div>
          <div className="page-subtitle">Chain verification, Merkle batches, and external witness anchoring</div>
        </div>
        <div className="flex-row">
          <button id="verify-now-btn" className="btn btn-ghost" onClick={verifyNow} disabled={verifying}>
            {verifying ? <span className="spinner" /> : '✔ Verify now'}
          </button>
          <button id="anchor-btn" className="btn btn-ghost" onClick={doAnchor} disabled={anchoring}>
            {anchoring ? <span className="spinner" /> : '⚓ Anchor All'}
          </button>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : !data ? null : (
          <>
            {/* Overall health banner */}
            <div className="card mb-6" style={{
              borderLeft: `3px solid ${allOk ? 'var(--success)' : 'var(--danger)'}`,
              background: allOk ? 'rgba(16,185,129,0.05)' : 'rgba(244,63,94,0.05)',
            }}>
              <div className="flex-between">
                <div className="flex-row">
                  <span className={`dot ${allOk ? 'dot-green' : 'dot-red'}`} />
                  <span style={{ fontWeight: 700, fontSize: '1rem' }}>
                    {allOk ? 'All chains intact — ledger is authentic' : '⚠ Chain integrity failure detected'}
                  </span>
                </div>
                <div className="flex-row">
                  {data.witness_ok
                    ? <span className="badge badge-green">✓ Witness intact ({data.witness_type})</span>
                    : <span className="badge badge-red">✗ Witness tampered</span>}
                </div>
              </div>
              {data.witness_message && (
                <div className="text-sm text-muted" style={{ marginTop: 8 }}>{data.witness_message}</div>
              )}
              {data.witness_problems?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  {data.witness_problems.map((p, i) => (
                    <div key={i} style={{ color: 'var(--danger)', fontSize: '0.82rem' }}>⚠ [{p.kind}] {p.message}</div>
                  ))}
                </div>
              )}
            </div>

            {/* Chain health per course */}
            <div className="section-title mb-4">🔗 Per-Course Chain Health</div>
            <div className="integrity-grid mb-6">
              {(data.chains || []).map(c => {
                const ok = c.chain_ok && c.marks_ok && c.batches_ok;
                const course = data.courses?.find(x => x.course_id === c.cid);
                return (
                  <div key={c.cid} className={`integrity-card ${ok ? 'ok' : 'fail'}`}>
                    <div className="flex-between mb-1">
                      <span className="badge badge-blue">{course?.course_code || `Course ${c.cid}`}</span>
                      <span className={`dot ${ok ? 'dot-green' : 'dot-red'}`} />
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', marginBottom: 10 }}>{course?.title}</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
                      <div className="flex-row text-sm">
                        <span>{c.chain_ok ? '✓' : '✗'}</span>
                        <span style={{ color: c.chain_ok ? 'var(--success)' : 'var(--danger)' }}>Chain</span>
                      </div>
                      <div className="flex-row text-sm">
                        <span>{c.marks_ok ? '✓' : '✗'}</span>
                        <span style={{ color: c.marks_ok ? 'var(--success)' : 'var(--danger)' }}>Marks sync</span>
                      </div>
                      <div className="flex-row text-sm">
                        <span>{c.batches_ok ? '✓' : '✗'}</span>
                        <span style={{ color: c.batches_ok ? 'var(--success)' : 'var(--danger)' }}>Merkle batches</span>
                      </div>
                    </div>
                    {!c.chain_ok && c.first_bad_seq && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--danger)', marginBottom: 10 }}>First bad seq: #{c.first_bad_seq}</div>
                    )}
                    <button id={`seal-${c.cid}`} className="btn btn-ghost btn-sm" style={{ width: '100%' }}
                      disabled={sealing === c.cid} onClick={() => doSeal(c.cid)}>
                      {sealing === c.cid ? <span className="spinner" /> : '🔒 Seal Batch'}
                    </button>
                  </div>
                );
              })}
            </div>

            {/* Merkle batches */}
            <div className="section-title mb-4">📦 Merkle Batches</div>
            <div className="table-wrap mb-6">
              <table>
                <thead>
                  <tr><th>Batch</th><th>Course</th><th>Seq range</th><th>Merkle root</th><th>Created</th><th>Proof</th></tr>
                </thead>
                <tbody>
                  {(data.batches || []).map(b => (
                    <tr key={b.batch_id}>
                      <td className="font-mono text-muted">#{b.batch_id}</td>
                      <td><span className="badge badge-blue">#{b.course_id}</span></td>
                      <td>{b.seq_from} – {b.seq_to}</td>
                      <td className="font-mono" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--accent)', fontSize: '0.68rem' }}>{b.merkle_root}</td>
                      <td className="text-muted text-sm">{fmt(b.created_at)}</td>
                      <td>
                        <button className="btn btn-ghost btn-sm"
                          onClick={() => setProofTarget({ course: b.course_id, seq: b.seq_from })}>
                          Proof →
                        </button>
                      </td>
                    </tr>
                  ))}
                  {(!data.batches || data.batches.length === 0) && (
                    <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-2)', padding: '30px' }}>No sealed batches yet — use "Seal Batch" above</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Scheduled checks */}
            <div className="section-title mb-4">⏱ Automatic checks</div>
            <div className="text-sm text-muted mb-4">
              {data.scheduler
                ? `Background jobs run on their own: verify every ${data.scheduler.verify}s, seal + anchor every ${data.scheduler.anchor}s, re-score anomalies every ${data.scheduler.score}s (0 = off). A new failure notifies the admins of the affected institution.`
                : 'The background scheduler is switched off (VERITAS_SCHEDULER=0).'}
            </div>
            <div className="table-wrap mb-6">
              <table>
                <thead><tr><th>Run</th><th>Job</th><th>Result</th><th>When</th><th>Detail</th></tr></thead>
                <tbody>
                  {(data.runs || []).length === 0 && <tr><td colSpan={5} className="text-muted">No runs yet</td></tr>}
                  {(data.runs || []).map(r => (
                    <tr key={r.run_id}>
                      <td className="font-mono text-muted">#{r.run_id}</td>
                      <td><span className="badge badge-blue">{r.kind}</span></td>
                      <td>{r.ok ? <span className="badge badge-green">ok</span> : <span className="badge badge-red">failed</span>}</td>
                      <td className="text-muted text-sm">{new Date(r.started_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'medium' })}</td>
                      <td className="font-mono text-muted" style={{ fontSize: '0.7rem', maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{JSON.stringify(r.detail)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Anchors */}
            <div className="section-title mb-4">⚓ External Witness Anchors</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Anchor</th><th>Batch</th><th>Type</th><th>Reference</th><th>Anchored at</th></tr>
                </thead>
                <tbody>
                  {(data.anchors || []).map(a => (
                    <tr key={a.anchor_id}>
                      <td className="font-mono text-muted">#{a.anchor_id}</td>
                      <td><span className="badge badge-blue">#{a.batch_id}</span></td>
                      <td><span className="badge badge-purple">{a.anchor_type}</span></td>
                      <td className="font-mono text-muted" style={{ fontSize: '0.72rem', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.anchor_ref}</td>
                      <td className="text-muted text-sm">{fmt(a.anchored_at)}</td>
                    </tr>
                  ))}
                  {(!data.anchors || data.anchors.length === 0) && (
                    <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-2)', padding: '30px' }}>No anchors yet — click "Anchor All"</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {proofTarget && (
        <ProofModal course={proofTarget.course} seq={proofTarget.seq} onClose={() => setProofTarget(null)} />
      )}
    </div>
  );
}
