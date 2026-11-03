import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { api } from './api';
import { useToast } from './Toast';

const NAV = {
  student: [
    { to: '/marks', icon: '📊', label: 'My Marks' },
    { to: '/sgpa', icon: '📈', label: 'SGPA' },
    { to: '/certificates', icon: '🎓', label: 'Certificates' },
    { to: '/revisions', icon: '🔗', label: 'Audit Trail' },
  ],
  faculty: [
    { to: '/marks', icon: '📊', label: 'Marks Entry' },
    { to: '/requests', icon: '📝', label: 'Change Requests' },
    { to: '/certificates', icon: '🎓', label: 'Certificates' },
  ],
  checker: [
    { to: '/marks', icon: '📊', label: 'Marks' },
    { to: '/requests', icon: '✅', label: 'Approve Requests' },
    { to: '/alerts', icon: '⚠️', label: 'Anomaly Alerts' },
    { to: '/certificates', icon: '🎓', label: 'Certificates' },
  ],
  admin: [
    { to: '/marks', icon: '📊', label: 'Marks' },
    { to: '/integrity', icon: '🔐', label: 'Integrity' },
    { to: '/requests', icon: '📝', label: 'Requests' },
    { to: '/alerts', icon: '⚠️', label: 'Alerts' },
    { to: '/people', icon: '👥', label: 'People' },
    { to: '/manage-courses', icon: '📚', label: 'Courses' },
    { to: '/directory', icon: '🗂️', label: 'Directory' },
    { to: '/certificates', icon: '🎓', label: 'Certificates' },
    { to: '/revisions', icon: '🔗', label: 'Ledger' },
    { to: '/admin-log', icon: '📜', label: 'Admin log' },
  ],
};

export function Sidebar({ user }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);          // the slide-out menu on small screens

  useEffect(() => {                                   // keep the badge fresh without a page reload
    let alive = true;
    const poll = () => api.notifications().then(d => alive && setUnread(d.unread)).catch(() => {});
    poll();
    const t = setInterval(poll, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const navKey = user.can_approve && user.role === 'faculty' ? 'checker' : user.role;
  const navItems = NAV[navKey] || NAV.student;

  useEffect(() => {
    if (!open) return;
    const esc = e => e.key === 'Escape' && setOpen(false);
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [open]);

  const initials = user.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

  async function handleLogout() {
    try { await api.logout(); } catch {}
    navigate('/login');
    window.location.reload();
  }

  return (
    <>
    <button className="menu-btn" aria-label="Open menu" aria-expanded={open} aria-controls="sidebar-nav" onClick={() => setOpen(true)}>☰</button>
    <div className={`scrim${open ? ' open' : ''}`} onClick={() => setOpen(false)} aria-hidden="true" />
    <aside id="sidebar-nav" className={`sidebar${open ? ' open' : ''}`} aria-label="Main navigation" onClick={e => e.target.closest('a') && setOpen(false)}>
      <div className="sidebar-logo">
        <div className="logo-icon" aria-hidden="true">🔐</div>
        <span>Veritas</span>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-label">Navigation</div>
        {navItems.map(item => (
          <NavLink key={item.to} to={item.to}
            className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}>
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </div>

      <div className="sidebar-section" style={{ marginTop: 8 }}>
        <div className="sidebar-section-label">Tools</div>
        <NavLink to="/notifications" className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}>
          <span className="nav-icon">🔔</span> Notifications
          {unread > 0 && <span id="unread-badge" className="badge badge-blue" style={{ marginLeft: 'auto' }}>{unread}</span>}
        </NavLink>
        <NavLink to="/account" className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}>
          <span className="nav-icon">👤</span> Account
        </NavLink>
        <NavLink to="/verify" className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}>
          <span className="nav-icon">🔍</span> Verify Certificate
        </NavLink>
      </div>

      <div className="sidebar-footer">
        <div className="user-chip">
          <div className="user-avatar">{initials}</div>
          <div className="user-info" style={{ flex: 1 }}>
            <div className="user-name">{user.name}</div>
            <div className="user-role">{navKey === 'checker' ? 'HOD / Checker' : user.role}</div>
          </div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={handleLogout} title="Sign out" aria-label="Sign out">
            ↩
          </button>
        </div>
      </div>
    </aside>
    </>
  );
}
