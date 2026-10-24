// VITE_API_BASE='' means same-origin (the Docker stack serves /api behind the same host); unset means local development.
const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

// CSRF token handed out by /api/login and /api/me; sent back on every state-changing call.
let csrf = null;

async function raw(method, path, { body, form } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (csrf && method !== 'GET') headers['X-CSRF-Token'] = csrf;
  return fetch(BASE + path, { method, credentials: 'include', headers, body: form || (body ? JSON.stringify(body) : undefined) });
}

async function req(method, path, body) {
  const res = await raw(method, path, { body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  const data = await res.json();
  if (data && data.csrf) csrf = data.csrf;
  return data;
}

// Files (PDF, CSV, JSON proofs) arrive as a blob; open or save them from the browser.
async function fileFrom(path, { download, open } = {}) {
  const res = await raw('GET', path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  const url = URL.createObjectURL(await res.blob());
  if (open) window.open(url, '_blank');
  if (download) {
    const a = document.createElement('a');
    a.href = url; a.download = download; document.body.appendChild(a); a.click(); a.remove();
  }
  return url;
}

export const api = {
  login: (email, password) => req('POST', '/api/login', { email, password }),
  logout: async () => { try { return await req('POST', '/api/logout'); } finally { csrf = null; } },
  me: () => req('GET', '/api/me'),

  marks: () => req('GET', '/api/marks'),
  applyMark: (markId, body) => req('POST', `/api/marks/${markId}/apply`, body),
  sgpa: () => req('GET', '/api/sgpa'),
  importMarks: async (file) => {
    const form = new FormData(); form.append('file', file);
    const res = await raw('POST', '/api/marks/import', { form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Import failed');
    return data;
  },
  exportMarks: () => fileFrom('/api/export/marks.csv', { download: 'marks.csv' }),
  exportLedger: (courseId) => fileFrom(`/api/export/ledger.csv${courseId ? `?course_id=${courseId}` : ''}`, { download: 'ledger.csv' }),

  requests: () => req('GET', '/api/requests'),
  createRequest: (body) => req('POST', '/api/requests', body),
  decideRequest: (id, approve) => req('POST', `/api/requests/${id}/decide`, { approve }),

  revisions: (courseId) => req('GET', `/api/revisions${courseId ? `?course_id=${courseId}` : ''}`),
  downloadProof: async (revisionId) => {
    const data = await req('GET', `/api/disclosure/${revisionId}`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = `veritas-proof-rev${revisionId}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    return data;
  },

  certificates: () => req('GET', '/api/certificates'),
  issueCert: (body) => req('POST', '/api/certificates', body),
  issueTranscript: (body) => req('POST', '/api/transcripts', body),
  openCertPdf: (id) => fileFrom(`/api/certificates/${id}/pdf`, { open: true }),
  revokeCert: (id) => req('POST', `/api/certificates/${id}/revoke`),
  verifyCert: (body) => req('POST', '/api/verify-certificate', body),

  integrity: () => req('GET', '/api/integrity'),
  verifyNow: () => req('POST', '/api/integrity/verify'),
  seal: (courseId) => req('POST', `/api/seal/${courseId}`),
  anchor: () => req('POST', '/api/anchor'),
  proof: (courseId, seq) => req('GET', `/api/proof?course_id=${courseId}&seq=${seq}`),

  alerts: () => req('GET', '/api/alerts'),
  reviewAlert: (id, status) => req('POST', `/api/alerts/${id}/review`, { status }),
  scoreAnomalies: () => req('POST', '/api/anomalies/score'),

  notifications: () => req('GET', '/api/notifications'),
  readNotifications: (ids = null) => req('POST', '/api/notifications/read', { ids }),

  directory: () => req('GET', '/api/directory'),
};
