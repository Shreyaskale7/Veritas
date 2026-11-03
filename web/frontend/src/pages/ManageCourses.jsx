import { useEffect, useState } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

const TYPES = ['CIE-1', 'CIE-2', 'SEE'];

// <input type="datetime-local"> works in local time without a zone; the server wants an absolute instant.
const toLocalInput = iso => { const d = new Date(iso); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
const toIso = local => new Date(local).toISOString();

function Modal({ title, onClose, children, footer }) {
  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </div>
    </div>
  );
}

function AddCourse({ faculty, onClose, onDone }) {
  const [f, setF] = useState({ course_code: '', title: '', credits: 3, semester: 5, faculty_id: '' });
  const [loading, setLoading] = useState(false);
  const toast = useToast();
  const set = k => e => setF({ ...f, [k]: e.target.value });
  async function submit(e) {
    e.preventDefault(); setLoading(true);
    try { await api.adminCreateCourse({ ...f, credits: +f.credits, semester: +f.semester, faculty_id: +f.faculty_id }); toast('Course created', 'success'); onDone(); }
    catch (err) { toast(err.message, 'error'); } finally { setLoading(false); }
  }
  return (
    <form onSubmit={submit}>
      <Modal title="Add course" onClose={onClose} footer={<>
        <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button id="c-submit" type="submit" className="btn btn-primary" disabled={loading}>{loading ? <span className="spinner" /> : 'Create course'}</button></>}>
        <div className="grid-2">
          <div className="form-group"><label className="form-label" htmlFor="c-code">Course code</label><input id="c-code" className="form-input" value={f.course_code} onChange={set('course_code')} required /></div>
          <div className="form-group"><label className="form-label" htmlFor="c-sem">Semester (1-8)</label><input id="c-sem" className="form-input" type="number" min="1" max="8" value={f.semester} onChange={set('semester')} required /></div>
        </div>
        <div className="form-group"><label className="form-label" htmlFor="c-title">Title</label><input id="c-title" className="form-input" value={f.title} onChange={set('title')} required /></div>
        <div className="grid-2">
          <div className="form-group"><label className="form-label" htmlFor="c-credits">Credits (1-6)</label><input id="c-credits" className="form-input" type="number" min="1" max="6" value={f.credits} onChange={set('credits')} required /></div>
          <div className="form-group"><label className="form-label" htmlFor="c-fac">Faculty</label>
            <select id="c-fac" className="form-input" value={f.faculty_id} onChange={set('faculty_id')} required>
              <option value="">Select faculty…</option>{faculty.map(x => <option key={x.user_id} value={x.user_id}>{x.name}</option>)}
            </select></div>
        </div>
      </Modal>
    </form>
  );
}

function Enroll({ course, students, onClose, onDone }) {
  const [picked, setPicked] = useState([]);
  const [loading, setLoading] = useState(false);
  const toast = useToast();
  const already = new Set(course.student_ids);
  const toggle = id => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  async function submit() {
    setLoading(true);
    try { const r = await api.adminEnroll(course.course_id, picked); toast(`${r.marks_created} mark slot(s) created`, 'success'); onDone(); }
    catch (err) { toast(err.message, 'error'); } finally { setLoading(false); }
  }
  return (
    <Modal title={`Enrol students in ${course.course_code}`} onClose={onClose} footer={<>
      <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
      <button id="enroll-submit" className="btn btn-primary" disabled={loading || !picked.length} onClick={submit}>{loading ? <span className="spinner" /> : `Enrol ${picked.length || ''}`}</button></>}>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="text-sm text-muted" style={{ marginBottom: 8 }}>Each student gets one empty mark per assessment of this course.</legend>
        <div style={{ maxHeight: 300, overflow: 'auto' }}>
          {students.map(s => (
            <label key={s.user_id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', opacity: already.has(s.user_id) ? 0.5 : 1 }}>
              <input type="checkbox" disabled={already.has(s.user_id)} checked={already.has(s.user_id) || picked.includes(s.user_id)} onChange={() => toggle(s.user_id)} />
              <span>{s.name} <span className="font-mono text-muted">{s.usn}</span>{already.has(s.user_id) && ' (enrolled)'}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </Modal>
  );
}

function AssessmentRow({ course, type, a, onSaved }) {
  const [max, setMax] = useState(a ? a.max_marks : 50);
  const [freeze, setFreeze] = useState(a ? toLocalInput(a.freeze_at) : '');
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  async function save() {
    if (!freeze) { toast('Choose a freeze date and time', 'error'); return; }
    setSaving(true);
    try { await api.adminSetAssessment(course.course_id, { type, max_marks: +max, freeze_at: toIso(freeze) }); toast(`${type} saved`, 'success'); onSaved(); }
    catch (err) { toast(err.message, 'error'); } finally { setSaving(false); }
  }
  const id = `${course.course_id}-${type}`;
  return (
    <tr>
      <th scope="row" style={{ fontWeight: 600 }}><span className="badge badge-purple">{type}</span></th>
      <td><label className="sr-only" htmlFor={`max-${id}`}>Max marks for {type}</label><input id={`max-${id}`} className="form-input" type="number" min="1" step="0.5" value={max} onChange={e => setMax(e.target.value)} style={{ width: 90 }} /></td>
      <td><label className="sr-only" htmlFor={`fr-${id}`}>Freeze time for {type}</label><input id={`fr-${id}`} className="form-input" type="datetime-local" value={freeze} onChange={e => setFreeze(e.target.value)} /></td>
      <td>{a ? (a.frozen ? <span className="badge badge-amber">🔒 Frozen</span> : <span className="badge badge-green">Open</span>) : <span className="badge badge-gray">Not set up</span>}</td>
      <td className="text-sm text-muted">{a ? `${a.marks_entered} entered` : '—'}</td>
      <td><button id={`save-${id}`} className="btn btn-ghost btn-sm" disabled={saving} onClick={save}>{a ? 'Save' : 'Add'}</button></td>
    </tr>
  );
}

export function ManageCourses() {
  const [data, setData] = useState({ courses: [], faculty: [], students: [] });
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [enrolling, setEnrolling] = useState(null);
  const toast = useToast();

  async function load() {
    try { setData(await api.adminCourses()); }
    catch (e) { toast(e.message, 'error'); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function reassign(course, facultyId) {
    if (+facultyId === course.faculty_id) return;
    try { await api.adminSetCourseFaculty(course.course_id, +facultyId); toast('Faculty reassigned', 'success'); load(); }
    catch (e) { toast(e.message, 'error'); load(); }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Courses</div>
          <div className="page-subtitle">Create courses, set marks and freeze dates, assign faculty, enrol students</div>
        </div>
        <button id="add-course-btn" className="btn btn-primary" onClick={() => setAdding(true)}>+ Add course</button>
      </div>
      <div className="page-body">
        {loading ? <div className="loader-center"><div className="spinner spinner-lg" /></div>
          : data.courses.length === 0 ? <div className="empty-state"><div className="empty-state-icon">📚</div><div className="empty-state-text">No courses yet</div></div>
          : data.courses.map(c => (
            <section key={c.course_id} className="card mb-6" aria-labelledby={`course-${c.course_id}`}>
              <div className="flex-between" style={{ flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
                <div>
                  <h2 id={`course-${c.course_id}`} style={{ fontSize: '1.05rem', margin: 0 }}>
                    <span className="badge badge-blue" style={{ marginRight: 8 }}>{c.course_code}</span>{c.title}
                  </h2>
                  <div className="text-sm text-muted" style={{ marginTop: 4 }}>Semester {c.semester} · {c.credits} credits · {c.enrolled} student(s) enrolled</div>
                </div>
                <div className="flex-row" style={{ flexWrap: 'wrap' }}>
                  <label className="text-sm text-muted" htmlFor={`fac-${c.course_id}`}>Faculty</label>
                  <select id={`fac-${c.course_id}`} className="form-input" value={c.faculty_id} onChange={e => reassign(c, e.target.value)} style={{ width: 200 }}>
                    {!data.faculty.some(f => f.user_id === c.faculty_id) && <option value={c.faculty_id}>{c.faculty_name} (inactive)</option>}
                    {data.faculty.map(f => <option key={f.user_id} value={f.user_id}>{f.name}</option>)}
                  </select>
                  <button id={`enroll-${c.course_id}`} className="btn btn-ghost btn-sm" onClick={() => setEnrolling(c)}>Enrol students</button>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">Assessments of {c.course_code}</caption>
                  <thead><tr><th scope="col">Assessment</th><th scope="col">Max marks</th><th scope="col">Freeze at</th><th scope="col">State</th><th scope="col">Marks</th><th scope="col"><span className="sr-only">Save</span></th></tr></thead>
                  <tbody>
                    {TYPES.map(t => <AssessmentRow key={`${t}-${c.assessments.find(a => a.type === t)?.freeze_at}-${c.assessments.find(a => a.type === t)?.max_marks}`}
                      course={c} type={t} a={c.assessments.find(a => a.type === t)} onSaved={load} />)}
                  </tbody>
                </table>
              </div>
              <p className="text-sm text-muted" style={{ marginTop: 8 }}>
                After the freeze time, marks change only through a request approved by a different checker. Moving a freeze date is logged.
              </p>
            </section>
          ))}
      </div>
      {adding && <AddCourse faculty={data.faculty} onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); }} />}
      {enrolling && <Enroll course={enrolling} students={data.students} onClose={() => setEnrolling(null)} onDone={() => { setEnrolling(null); load(); }} />}
    </div>
  );
}
