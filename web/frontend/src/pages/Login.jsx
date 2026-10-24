import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../Toast';

export function Login({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.login(email, password);
      const me = await api.me();
      onLogin(me);
      navigate('/marks');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div className="logo-mark">🔐</div>
          <h1>Veritas</h1>
          <p>Tamper-evident academic ledger · RVCE</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Email address</label>
            <input
              id="email"
              className="form-input"
              type="email"
              placeholder="you@rvce.edu.in"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              id="password"
              className="form-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          <button id="login-btn" className="btn btn-primary" type="submit" disabled={loading}
            style={{ width: '100%', justifyContent: 'center', padding: '12px', fontSize: '0.95rem', marginTop: 4 }}>
            {loading ? <span className="spinner" /> : 'Sign in →'}
          </button>
        </form>

        <div style={{ marginTop: 24, padding: 14, background: 'rgba(99,102,241,0.08)', borderRadius: 10, fontSize: '0.78rem', color: 'var(--text-2)' }}>
          <strong style={{ color: 'var(--text-1)' }}>Demo credentials</strong><br />
          Any seed user · Password: <code style={{ color: 'var(--accent)' }}>veritas2026</code>
        </div>
      </div>
    </div>
  );
}
