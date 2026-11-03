import { useEffect, useState } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

const ROLE_BADGE = { admin: 'badge-purple', faculty: 'badge-blue', student: 'badge-green' };

function PasswordResult({ title, email, password, onClose }) {
  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>
            Give this one-time password to <strong>{email}</strong>. It is shown only now and is never stored or logged;
            they must choose their own password at first sign-in.
          </p>
          <div id="temp-password" className="font-mono" style={{ fontSize: '1.3rem', padding: '14px 16px', margin: '12px 0', background: 'rgba(99,102,241,0.1)', borderRadius: 8, letterSpacing: '0.05em', userSelect: 'all' }}>
            {password}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={() => navigator.clipboard?.writeText(password)}>Copy</button>
          <button className="btn btn-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

function AddPersonModal({ onClose, onDone }) {
  const [role, setRole] = useState('student');
  const [f, setF] = useState({ name: '', email: '', password: '', usn: '', branch: '', semester: '', employee_id: '', department: '', can_approve: false });
  const [loading, setLoading] = useState(false);
  const toast = useToast();
  const set = k => e => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const body = { name: f.name, email: f.email, role, password: f.password || null };
      if (role === 'student') Object.assign(body, { usn: f.usn, branch: f.branch, semester: parseInt(f.semester) || null });
      if (role === 'faculty') Object.assign(body, { employee_id: f.employee_id, department: f.department, can_approve: f.can_approve });
      const r = await api.adminCreatePerson(body);
      onDone(r.temporary_password, f.email);
    } catch (err) { toast(err.message, 'error'); }
    finally { setLoading(false); }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Add person</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            <div className="form-group">
              <label className="form-label" htmlFor="p-role">Role</label>
              <select id="p-role" className="form-input" value={role} onChange={e => setRole(e.target.value)}>
                <option value="student">Student</option>
                <option value="faculty">Faculty</option>
                <option value="admin">Administrator</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="p-name">Full name</label>
              <input id="p-name" className="form-input" value={f.name} onChange={set('name')} required />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="p-email">E-mail address</label>
              <input id="p-email" className="form-input" type="email" value={f.email} onChange={set('email')} required />
            </div>
            {role === 'student' && (<>
              <div className="form-group">
                <label className="form-label" htmlFor="p-usn">USN</label>
                <input id="p-usn" className="form-input" value={f.usn} onChange={set('usn')} required />
              </div>
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label" htmlFor="p-branch">Branch</label>
                  <input id="p-branch" className="form-input" value={f.branch} onChange={set('branch')} required />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="p-sem">Semester (1-8)</label>
                  <input id="p-sem" className="form-input" type="number" min="1" max="8" value={f.semester} onChange={set('semester')} required />
                </div>
              </div>
            </>)}
            {role === 'faculty' && (<>
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label" htmlFor="p-emp">Employee id</label>
                  <input id="p-emp" className="form-input" value={f.employee_id} onChange={set('employee_id')} required />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="p-dept">Department</label>
                  <input id="p-dept" className="form-input" value={f.department} onChange={set('department')} required />
                </div>
              </div>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: '0.88rem', marginBottom: 12 }}>
                <input id="p-approve" type="checkbox" checked={f.can_approve} onChange={set('can_approve')} />
                Can approve change requests (HOD / checker)
              </label>
            </>)}
            <div className="form-group">
              <label className="form-label" htmlFor="p-pass">Temporary password</label>
              <input id="p-pass" className="form-input" type="text" autoComplete="off" value={f.password} onChange={set('password')}
                placeholder="Leave empty to generate one" aria-describedby="p-pass-help" />
              <div id="p-pass-help" className="text-sm text-muted" style={{ marginTop: 4 }}>At least 10 characters with a letter and a digit. They must change it at first sign-in.</div>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button id="p-submit" type="submit" className="btn btn-primary" disabled={loading}>{loading ? <span className="spinner" /> : 'Add person'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function People({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [role, setRole] = useState('');
  const [adding, setAdding] = useState(false);
  const [shown, setShown] = useState(null);     // { title, email, password }
  const toast = useToast();

  async function load() {
    try { setRows(await api.adminPeople()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function act(fn, ok) {
    try { const r = await fn(); if (ok) toast(ok, 'success'); await load(); return r; }
    catch (e) { toast(e.message, 'error'); }
  }

  async function reset(p) {
    if (!confirm(`Reset the password of ${p.name}? Their current password stops working immediately.`)) return;
    const r = await act(() => api.adminResetPassword(p.user_id), null);
    if (r?.temporary_password) setShown({ title: 'Password reset', email: p.email, password: r.temporary_password });
  }

  const f = filter.toLowerCase();
  const list = rows.filter(p => (!role || p.role === role) && (!f || `${p.name} ${p.email} ${p.usn || ''} ${p.employee_id || ''}`.toLowerCase().includes(f)));

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">People</div>
          <div className="page-subtitle">Students, faculty and administrators of your institution</div>
        </div>
        <div className="flex-row">
          <input className="form-input" placeholder="Filter…" aria-label="Filter people" value={filter} onChange={e => setFilter(e.target.value)} style={{ width: 200 }} />
          <select className="form-input" aria-label="Filter by role" value={role} onChange={e => setRole(e.target.value)} style={{ width: 140 }}>
            <option value="">All roles</option><option value="student">Students</option><option value="faculty">Faculty</option><option value="admin">Admins</option>
          </select>
          <button id="add-person-btn" className="btn btn-primary" onClick={() => setAdding(true)}>+ Add person</button>
        </div>
      </div>
      <div className="page-body">
        <div className="stats-grid">
          <div className="card"><div className="card-title">Students</div><div className="card-value" style={{ color: 'var(--success)' }}>{rows.filter(r => r.role === 'student').length}</div></div>
          <div className="card"><div className="card-title">Faculty</div><div className="card-value" style={{ color: 'var(--info)' }}>{rows.filter(r => r.role === 'faculty').length}</div></div>
          <div className="card"><div className="card-title">Inactive</div><div className="card-value" style={{ color: 'var(--warn)' }}>{rows.filter(r => !r.active).length}</div></div>
        </div>
        {loading ? <div className="loader-center"><div className="spinner spinner-lg" /></div> : (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">People of your institution</caption>
              <thead><tr><th scope="col">Name</th><th scope="col">E-mail</th><th scope="col">Role</th><th scope="col">Details</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
              <tbody>
                {list.map(p => (
                  <tr key={p.user_id}>
                    <td style={{ fontWeight: 600 }}>{p.name}</td>
                    <td className="text-muted">{p.email}</td>
                    <td><span className={`badge ${ROLE_BADGE[p.role]}`}>{p.role}{p.role === 'faculty' && p.can_approve ? ' · approver' : ''}</span></td>
                    <td className="text-sm text-muted">{p.role === 'student' ? `${p.usn} · ${p.branch} · sem ${p.semester}` : p.role === 'faculty' ? `${p.employee_id} · ${p.department}` : '—'}</td>
                    <td>
                      {p.active ? <span className="badge badge-green">Active</span> : <span className="badge badge-red">Inactive</span>}
                      {p.must_change && <span className="badge badge-amber" style={{ marginLeft: 6 }}>Temporary password</span>}
                    </td>
                    <td>
                      <div className="flex-row" style={{ flexWrap: 'wrap' }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => reset(p)} aria-label={`Reset password of ${p.name}`}>Reset password</button>
                        {p.role === 'faculty' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => act(() => api.adminSetApprover(p.user_id, !p.can_approve), p.can_approve ? 'Approver rights removed' : 'Approver rights granted')}
                            aria-label={`${p.can_approve ? 'Remove' : 'Grant'} approver rights for ${p.name}`}>{p.can_approve ? 'Remove approver' : 'Make approver'}</button>
                        )}
                        <button className={`btn btn-sm ${p.active ? 'btn-danger' : 'btn-primary'}`} disabled={p.user_id === user.user_id}
                          onClick={() => act(() => api.adminSetActive(p.user_id, !p.active), p.active ? 'Deactivated' : 'Activated')}
                          aria-label={`${p.active ? 'Deactivate' : 'Activate'} ${p.name}`}>{p.active ? 'Deactivate' : 'Activate'}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {adding && <AddPersonModal onClose={() => setAdding(false)} onDone={(pw, email) => { setAdding(false); load(); toast('Person added', 'success'); if (pw) setShown({ title: 'Person added', email, password: pw }); }} />}
      {shown && <PasswordResult {...shown} onClose={() => setShown(null)} />}
    </div>
  );
}
