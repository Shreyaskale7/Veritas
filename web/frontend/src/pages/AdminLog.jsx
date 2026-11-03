import { useEffect, useState } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

const LABEL = {
  create_user: 'Added a person', activate_user: 'Activated a person', deactivate_user: 'Deactivated a person', set_can_approve: 'Changed approver rights',
  reset_password: 'Reset a password', create_course: 'Created a course', set_course_faculty: 'Reassigned course faculty',
  create_assessment: 'Set up an assessment', update_assessment: 'Changed an assessment', enroll: 'Enrolled students',
};

function summary(a) {
  const d = a.detail || {};
  switch (a.action) {
    case 'create_user': return `${d.email} (${d.role})`;
    case 'activate_user': case 'deactivate_user': case 'reset_password': return `person #${d.user_id}`;
    case 'set_can_approve': return `person #${d.user_id} → ${d.can_approve ? 'approver' : 'not approver'}`;
    case 'create_course': return `${d.code} (course #${d.course_id})`;
    case 'set_course_faculty': return `course #${d.course_id}: faculty #${d.from} → #${d.to}`;
    case 'create_assessment': return `course #${d.course_id} ${d.type}: max ${d.max_marks}, freeze ${new Date(d.freeze_at).toLocaleString('en-IN')}`;
    case 'update_assessment': return `course #${d.course_id} ${d.type}: max ${d.old_max_marks} → ${d.max_marks}, freeze ${new Date(d.old_freeze_at).toLocaleString('en-IN')} → ${new Date(d.freeze_at).toLocaleString('en-IN')}`;
    case 'enroll': return `course #${d.course_id}: ${d.marks_created} mark slot(s) for ${(d.students || []).length} student(s)`;
    default: return JSON.stringify(d);
  }
}

export function AdminLog() {
  const [rows, setRows] = useState(null);
  const toast = useToast();
  useEffect(() => { api.adminLog().then(setRows).catch(e => { toast(e.message, 'error'); setRows([]); }); }, []);
  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Admin log</div>
          <div className="page-subtitle">Every administrative change, append-only. Passwords are never recorded.</div>
        </div>
      </div>
      <div className="page-body">
        {rows === null ? <div className="loader-center"><div className="spinner spinner-lg" /></div>
          : rows.length === 0 ? <div className="empty-state"><div className="empty-state-icon">📜</div><div className="empty-state-text">Nothing logged yet</div></div>
          : (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Administrative actions, newest first</caption>
                <thead><tr><th scope="col">When</th><th scope="col">Administrator</th><th scope="col">Action</th><th scope="col">Detail</th></tr></thead>
                <tbody>
                  {rows.map(a => (
                    <tr key={a.action_id}>
                      <td className="text-muted text-sm" style={{ whiteSpace: 'nowrap' }}>{new Date(a.at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'medium' })}</td>
                      <td>{a.admin_name}</td>
                      <td><span className="badge badge-blue">{LABEL[a.action] || a.action}</span></td>
                      <td className="text-sm text-muted">{summary(a)}</td>
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
