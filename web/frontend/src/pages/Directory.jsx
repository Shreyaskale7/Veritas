import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';

export function Directory({ user }) {
  const [students, setStudents] = useState([]);
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('students');
  const [filter, setFilter] = useState('');
  const toast = useToast();

  useEffect(() => {
    api.directory()
      .then(d => { setStudents(d.students || []); setCourses(d.courses || []); })
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false));
  }, []);

  const filteredStudents = students.filter(s =>
    !filter || `${s.name} ${s.usn} ${s.branch}`.toLowerCase().includes(filter.toLowerCase()));
  const filteredCourses = courses.filter(c =>
    !filter || `${c.course_code} ${c.title}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Directory</div>
          <div className="page-subtitle">Students and courses registered in the system</div>
        </div>
        <input className="form-input" placeholder="🔍 Filter…" value={filter}
          onChange={e => setFilter(e.target.value)} style={{ width: 220 }} />
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Students</div>
            <div className="card-value" style={{ color: 'var(--accent)' }}>{students.length}</div>
          </div>
          <div className="card">
            <div className="card-title">Courses</div>
            <div className="card-value" style={{ color: 'var(--info)' }}>{courses.length}</div>
          </div>
          <div className="card">
            <div className="card-title">Branches</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{[...new Set(students.map(s => s.branch))].length}</div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex-row mb-4">
          {['students', 'courses'].map(t => (
            <button key={t} id={`tab-${t}`}
              className={`btn ${tab === t ? 'btn-primary' : 'btn-ghost'}`}
              style={{ textTransform: 'capitalize' }}
              onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>

        {loading ? (
          <div className="loader-center"><div className="spinner spinner-lg" /></div>
        ) : tab === 'students' ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Name</th><th>USN</th><th>Branch</th><th>Semester</th></tr>
              </thead>
              <tbody>
                {filteredStudents.map(s => (
                  <tr key={s.user_id}>
                    <td style={{ fontWeight: 500 }}>{s.name}</td>
                    <td className="font-mono">{s.usn}</td>
                    <td><span className="badge badge-blue">{s.branch}</span></td>
                    <td><span className="badge badge-purple">Sem {s.semester}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Code</th><th>Title</th><th>Credits</th><th>Semester</th><th>Faculty ID</th></tr>
              </thead>
              <tbody>
                {filteredCourses.map(c => (
                  <tr key={c.course_id}>
                    <td><span className="badge badge-blue">{c.course_code}</span></td>
                    <td style={{ fontWeight: 500 }}>{c.title}</td>
                    <td>{c.credits}</td>
                    <td><span className="badge badge-purple">Sem {c.semester}</span></td>
                    <td className="font-mono text-muted">#{c.faculty_id}</td>
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
