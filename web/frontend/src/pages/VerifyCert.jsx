import { useEffect, useState } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

export function VerifyCert() {
  const [certId, setCertId] = useState('');
  const [salt, setSalt] = useState('');
  const [content, setContent] = useState('');
  const [digest, setDigest] = useState('');   // from a scanned QR: cert_id|salt|sha256(content)
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function check(id, sl, body) {
    setLoading(true);
    setResult(null);
    try {
      setResult(await api.verifyCert({ cert_id: id.trim(), salt: sl.trim(), ...body }));
    } catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }

  function handleSubmit(e) {
    e.preventDefault();
    check(certId, salt, content ? { content } : digest ? { content_digest: digest } : { content });
  }

  // Scan-to-verify: the QR on a Veritas PDF opens /verify?p=cert_id|salt|digest, which checks itself.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get('p');
    if (!p) return;
    const [id, sl, dg] = p.split('|');
    if (id && sl && dg) { setCertId(id); setSalt(sl); setDigest(dg); check(id, sl, { content_digest: dg }); }
  }, []);

  function handleQrPaste(raw) {
    // QR encodes "cert_id|salt"
    const parts = raw.trim().split('|');
    if (parts.length >= 2) {
      setCertId(parts[0].replace(/^.*[?&]p=/, ''));
      setSalt(parts[1]);
      setDigest(parts[2] || '');
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">🔍 Verify Certificate</div>
          <div className="page-subtitle">Public verifier — no login required. Confirm authenticity of any Veritas certificate.</div>
        </div>
      </div>

      <div className="page-body">
        <div style={{ maxWidth: 600 }}>
          <div className="card mb-6" style={{ borderLeft: '3px solid var(--accent)', background: 'rgba(99,102,241,0.05)' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.7 }}>
              <strong style={{ color: 'var(--text-1)' }}>How it works:</strong> Scanning the QR code on a Veritas certificate opens this page and checks it
              automatically. By hand, enter the
              <code style={{ color: 'var(--accent)', margin: '0 4px' }}>cert_id|salt</code>
              from the certificate together with its text — we compute
              <code style={{ color: 'var(--accent)', margin: '0 4px' }}>sha256(salt || sha256(content))</code>
              and check it against the stored hash. The database returns only valid/revoked/unknown — no personal data.
            </div>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="form-group">
                <label className="form-label">QR raw payload (paste to auto-fill)</label>
                <input className="form-input font-mono" placeholder="uuid|hex-salt"
                  onChange={e => handleQrPaste(e.target.value)} />
              </div>
              <div className="divider" style={{ margin: '0' }} />
              <div className="form-group">
                <label className="form-label">Certificate ID (UUID)</label>
                <input id="verify-cert-id" className="form-input font-mono" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={certId} onChange={e => setCertId(e.target.value)} required />
              </div>
              <div className="form-group">
                <label className="form-label">Salt (from QR code)</label>
                <input id="verify-salt" className="form-input font-mono" placeholder="32-char hex"
                  value={salt} onChange={e => setSalt(e.target.value)} required />
              </div>
              <div className="form-group">
                <label className="form-label">Certificate content (full text){digest ? ' — optional, the QR already carries its digest' : ''}</label>
                <textarea id="verify-content" className="form-input" rows={5}
                  placeholder="Paste the full certificate text here…"
                  value={content} onChange={e => setContent(e.target.value)} required />
              </div>
              <button id="verify-btn" type="submit" className="btn btn-primary" disabled={loading}
                style={{ alignSelf: 'flex-start' }}>
                {loading ? <span className="spinner" /> : '🔍 Verify Certificate'}
              </button>
            </div>
          </form>

          {result && (
            <div className="card mt-4" style={{
              borderLeft: `3px solid ${result.status === 'valid' ? 'var(--success)' : result.status === 'revoked' ? 'var(--danger)' : 'var(--warn)'}`,
              background: result.status === 'valid' ? 'rgba(16,185,129,0.05)' : result.status === 'revoked' ? 'rgba(244,63,94,0.05)' : 'rgba(245,158,11,0.05)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                <div style={{ fontSize: '2.5rem' }}>
                  {result.status === 'valid' ? '✅' : result.status === 'revoked' ? '❌' : '⚠️'}
                </div>
                <div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 800,
                    color: result.status === 'valid' ? 'var(--success)' : result.status === 'revoked' ? 'var(--danger)' : 'var(--warn)' }}>
                    {result.status === 'valid' ? 'Certificate is VALID' :
                     result.status === 'revoked' ? 'Certificate has been REVOKED' :
                     'Certificate UNKNOWN or content mismatch'}
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-2)', marginTop: 3 }}>
                    {result.status === 'valid' ? 'The content matches the stored cryptographic hash. This certificate is authentic.' :
                     result.status === 'revoked' ? 'This certificate was revoked. It is no longer valid.' :
                     'No matching certificate found — the cert ID, salt, or content may be incorrect.'}
                  </div>
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Content digest (SHA-256)</label>
                <div className="font-mono" style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: 8, wordBreak: 'break-all', fontSize: '0.7rem', color: 'var(--text-2)' }}>
                  {result.content_digest}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
