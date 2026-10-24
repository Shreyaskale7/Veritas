import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { api } from './api';
import { ToastProvider } from './Toast';
import { Sidebar } from './Sidebar';
import { Login } from './pages/Login';
import { Marks } from './pages/Marks';
import { SGPA } from './pages/SGPA';
import { Certificates } from './pages/Certificates';
import { Requests } from './pages/Requests';
import { Alerts } from './pages/Alerts';
import { Integrity } from './pages/Integrity';
import { Revisions } from './pages/Revisions';
import { Directory } from './pages/Directory';
import { VerifyCert } from './pages/VerifyCert';
import { Notifications } from './pages/Notifications';

function AppShell({ user, onLogin }) {
  if (!user) return <Login onLogin={onLogin} />;

  const isAdmin = user.role === 'admin';
  const isStudent = user.role === 'student';

  return (
    <div className="app-shell">
      <Sidebar user={user} />
      <main className="main">
        <Routes>
          <Route path="/marks" element={<Marks user={user} />} />
          <Route path="/requests" element={<Requests user={user} />} />
          <Route path="/certificates" element={<Certificates user={user} />} />
          <Route path="/verify" element={<VerifyCert />} />
          <Route path="/notifications" element={<Notifications />} />
          {!isStudent && <Route path="/revisions" element={<Revisions user={user} />} />}
          {isStudent && <Route path="/sgpa" element={<SGPA user={user} />} />}
          {isStudent && <Route path="/revisions" element={<Revisions user={user} />} />}
          {(user.can_approve || isAdmin) && <Route path="/alerts" element={<Alerts user={user} />} />}
          {isAdmin && <Route path="/integrity" element={<Integrity user={user} />} />}
          {isAdmin && <Route path="/directory" element={<Directory user={user} />} />}
          {!isStudent && <Route path="/sgpa" element={<SGPA user={user} />} />}
          <Route path="*" element={<Navigate to="/marks" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// The verifier is public: anyone holding a certificate (or scanning its QR code) can use it without an account.
function PublicVerify() {
  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 20px' }}>
      <div className="sidebar-logo" style={{ marginBottom: 24 }}><div className="logo-icon">🔐</div><span>Veritas</span></div>
      <VerifyCert />
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = loading, null = not authed

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="spinner spinner-lg" style={{ margin: '0 auto 16px' }} />
          <div style={{ color: 'var(--text-2)', fontSize: '0.9rem' }}>Loading Veritas…</div>
        </div>
      </div>
    );
  }

  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/marks" replace /> : <Login onLogin={setUser} />} />
          <Route path="/verify" element={user ? <AppShell user={user} onLogin={setUser} /> : <PublicVerify />} />
          <Route path="*" element={
            user
              ? <AppShell user={user} onLogin={setUser} />
              : <Navigate to="/login" replace />
          } />
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
