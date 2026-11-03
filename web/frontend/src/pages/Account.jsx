import { useState } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

// Shared by the Account page and the forced first-sign-in screen.
export function PasswordForm({ onDone, forced }) {
  const [oldPw, setOld] = useState('');
  const [newPw, setNew] = useState('');
  const [again, setAgain] = useState('');
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function submit(e) {
    e.preventDefault();
    if (newPw !== again) { toast('The new passwords do not match', 'error'); return; }
    setLoading(true);
    try {
      await api.changePassword(oldPw, newPw);
      toast('Password changed', 'success');
      setOld(''); setNew(''); setAgain('');
      onDone?.();
    } catch (err) { toast(err.message, 'error'); }
    finally { setLoading(false); }
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="form-group">
        <label className="form-label" htmlFor="old-pw">{forced ? 'Temporary password' : 'Current password'}</label>
        <input id="old-pw" className="form-input" type="password" autoComplete="current-password" value={oldPw} onChange={e => setOld(e.target.value)} required />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="new-pw">New password</label>
        <input id="new-pw" className="form-input" type="password" autoComplete="new-password" value={newPw} onChange={e => setNew(e.target.value)} required aria-describedby="pw-rule" />
        <div id="pw-rule" className="text-sm text-muted" style={{ marginTop: 4 }}>At least 10 characters, with a letter and a digit, and different from the old one.</div>
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="again-pw">Repeat the new password</label>
        <input id="again-pw" className="form-input" type="password" autoComplete="new-password" value={again} onChange={e => setAgain(e.target.value)} required />
      </div>
      <button id="pw-submit" type="submit" className="btn btn-primary" disabled={loading} style={{ alignSelf: 'flex-start' }}>
        {loading ? <span className="spinner" /> : 'Change password'}
      </button>
    </form>
  );
}

export function Account({ user, onRefresh }) {
  const [notify, setNotify] = useState(user.email_notify !== false);
  const toast = useToast();

  async function toggle(e) {
    const v = e.target.checked;
    setNotify(v);
    try { await api.setEmailNotify(v); toast(v ? 'E-mail notifications on' : 'E-mail notifications off', 'success'); }
    catch (err) { setNotify(!v); toast(err.message, 'error'); }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Account</div>
          <div className="page-subtitle">{user.name} · {user.role === 'faculty' && user.can_approve ? 'HOD / checker' : user.role}</div>
        </div>
      </div>
      <div className="page-body" style={{ maxWidth: 560 }}>
        <section className="card mb-6" aria-labelledby="pw-h">
          <h2 id="pw-h" className="section-title" style={{ marginTop: 0 }}>Change password</h2>
          <PasswordForm onDone={onRefresh} />
        </section>
        <section className="card" aria-labelledby="mail-h">
          <h2 id="mail-h" className="section-title" style={{ marginTop: 0 }}>Notifications</h2>
          <label style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: '0.92rem' }}>
            <input id="email-notify" type="checkbox" checked={notify} onChange={toggle} />
            E-mail me when something needs my attention (when the server is set up to send mail)
          </label>
          <p className="text-sm text-muted" style={{ marginTop: 8 }}>In-app notifications are always on.</p>
        </section>
      </div>
    </div>
  );
}

export function ForcePasswordChange({ user, onDone, onSignOut }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <main className="card" style={{ width: '100%', maxWidth: 440 }} aria-labelledby="force-h">
        <h1 id="force-h" style={{ fontSize: '1.3rem', marginBottom: 6 }}>Choose a new password</h1>
        <p className="text-sm text-muted" style={{ marginBottom: 18, lineHeight: 1.6 }}>
          Hello {user.name}. You signed in with a temporary password; pick your own to continue.
        </p>
        <PasswordForm forced onDone={onDone} />
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 14 }} onClick={onSignOut}>Sign out</button>
      </main>
    </div>
  );
}
