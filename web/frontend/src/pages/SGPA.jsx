import { useState, useEffect } from 'react';
import { api } from '../api';
import { useToast } from '../Toast';
import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts';

const GRADE_COLOR = { 10: '#10b981', 9: '#34d399', 8: '#6366f1', 7: '#818cf8', 6: '#f59e0b', 5: '#fb923c', 4: '#f87171', 0: '#f43f5e' };

function gradeLabel(gp) {
  return { 10: 'O', 9: 'A+', 8: 'A', 7: 'B+', 6: 'B', 5: 'C', 4: 'P', 0: 'F' }[gp] || gp;
}

export function SGPA({ user }) {
  const [rows, setRows] = useState([]);
  const [marks, setMarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    Promise.all([api.sgpa(), api.marks()])
      .then(([s, m]) => { setRows(s); setMarks(m); })
      .catch(e => toast(e.message, 'error'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loader-center"><div className="spinner spinner-lg" /></div>;

  const latest = rows[rows.length - 1];
  const best = rows.reduce((a, b) => (!a || b.sgpa > a.sgpa ? b : a), null);

  const chartData = rows.map(r => ({ sem: `Sem ${r.semester}`, sgpa: parseFloat(r.sgpa) }));

  // Course breakdown for radar (per-course % obtained)
  const radarData = [...new Set(marks.map(m => m.course_code))].map(code => {
    const ms = marks.filter(m => m.course_code === code);
    const obtained = ms.reduce((s, m) => s + (m.current_value || 0), 0);
    const max = ms.reduce((s, m) => s + (m.max_marks || 0), 0);
    return { course: code, score: max ? Math.round(100 * obtained / max) : 0 };
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">SGPA & Performance</div>
          <div className="page-subtitle">Grade point analysis across all semesters</div>
        </div>
      </div>

      <div className="page-body">
        <div className="stats-grid">
          <div className="card">
            <div className="card-title">Current SGPA</div>
            <div className="card-value" style={{ color: 'var(--accent)', fontSize: '2.5rem' }}>{latest?.sgpa ?? '—'}</div>
            <div className="card-sub">Semester {latest?.semester}</div>
          </div>
          <div className="card">
            <div className="card-title">Best SGPA</div>
            <div className="card-value" style={{ color: 'var(--success)' }}>{best?.sgpa ?? '—'}</div>
            <div className="card-sub">Semester {best?.semester}</div>
          </div>
          <div className="card">
            <div className="card-title">Avg SGPA</div>
            <div className="card-value" style={{ color: 'var(--info)' }}>
              {rows.length ? (rows.reduce((s, r) => s + parseFloat(r.sgpa), 0) / rows.length).toFixed(2) : '—'}
            </div>
            <div className="card-sub">across {rows.length} semester(s)</div>
          </div>
        </div>

        <div className="grid-2 mb-6">
          {/* Bar chart */}
          <div className="card">
            <div className="section-title">📊 SGPA Trend</div>
            {chartData.length === 0
              ? <div className="empty-state"><div className="empty-state-text">No SGPA data yet</div></div>
              : <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} barSize={36}>
                    <XAxis dataKey="sem" tick={{ fill: '#8892b0', fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 10]} tick={{ fill: '#8892b0', fontSize: 12 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: '#111627', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#f0f4ff' }}
                      cursor={{ fill: 'rgba(99,102,241,0.1)' }}
                    />
                    <Bar dataKey="sgpa" radius={[6, 6, 0, 0]}>
                      {chartData.map((entry, i) => (
                        <Cell key={i} fill={entry.sgpa >= 8 ? '#10b981' : entry.sgpa >= 6 ? '#6366f1' : '#f59e0b'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
            }
          </div>

          {/* Radar */}
          <div className="card">
            <div className="section-title">🎯 Course Performance (%)</div>
            {radarData.length === 0
              ? <div className="empty-state"><div className="empty-state-text">No marks data yet</div></div>
              : <ResponsiveContainer width="100%" height={220}>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="rgba(255,255,255,0.08)" />
                    <PolarAngleAxis dataKey="course" tick={{ fill: '#8892b0', fontSize: 11 }} />
                    <Radar name="%" dataKey="score" stroke="#6366f1" fill="#6366f1" fillOpacity={0.2} />
                  </RadarChart>
                </ResponsiveContainer>
            }
          </div>
        </div>

        {/* Semester breakdown */}
        <div className="section-title">📋 Semester Breakdown</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Semester</th><th>SGPA</th><th>Grade</th><th>Performance</th></tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const gp = Math.round(parseFloat(r.sgpa));
                const pct = Math.round((parseFloat(r.sgpa) / 10) * 100);
                return (
                  <tr key={r.semester}>
                    <td style={{ fontWeight: 600 }}>Semester {r.semester}</td>
                    <td style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--accent)' }}>{r.sgpa}</td>
                    <td><span className="badge" style={{ background: 'rgba(99,102,241,0.15)', color: GRADE_COLOR[gp] || '#6366f1' }}>{gradeLabel(gp)}</span></td>
                    <td style={{ width: '40%' }}>
                      <div className="flex-row">
                        <div className="score-bar-wrap">
                          <div className="score-bar" style={{ width: `${pct}%`, background: GRADE_COLOR[gp] || 'var(--accent)' }} />
                        </div>
                        <span className="text-muted text-sm">{pct}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-2)', padding: '40px' }}>No complete semesters yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
