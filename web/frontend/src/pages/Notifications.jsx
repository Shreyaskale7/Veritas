import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../Toast';

const ICON = { request_filed: '📝', request_approved: '✅', request_rejected: '⛔', mark_changed: '📊', alert: '⚠️',
  certificate_issued: '🎓', certificate_revoked: '❌', integrity_failure: '🚨' };

function when(d) { return new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }); }

export function Notifications() {
  const [data, setData] = useState({ unread: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const toast = useToast();

  async function load() {
    try { setData(await api.notifications()); }
    catch (e) { toast(e.message, 'error'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function open(n) {
    if (!n.read_at) await api.readNotifications([n.notification_id]).catch(() => {});
    if (n.link) navigate(n.link); else load();
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Notifications</div>
          <div className="page-subtitle">Requests, decisions, mark changes, alerts and certificates that concern you</div>
        </div>
        <button id="read-all-btn" className="btn btn-ghost" disabled={!data.unread}
          onClick={async () => { await api.readNotifications(); load(); }}>Mark all read ({data.unread})</button>
      </div>
      <div className="page-body">
        {loading ? <div className="loader-center"><div className="spinner spinner-lg" /></div>
          : data.items.length === 0 ? <div className="empty-state"><div className="empty-state-icon">🔔</div><div className="empty-state-text">Nothing yet</div></div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {data.items.map(n => (
                <div key={n.notification_id} className="card" onClick={() => open(n)}
                  style={{ cursor: 'pointer', display: 'flex', gap: 14, alignItems: 'center', opacity: n.read_at ? 0.6 : 1,
                    borderLeft: `3px solid ${n.read_at ? 'transparent' : n.kind === 'integrity_failure' ? 'var(--danger)' : 'var(--accent)'}` }}>
                  <div style={{ fontSize: '1.4rem' }}>{ICON[n.kind] || '🔔'}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: n.read_at ? 500 : 700 }}>{n.message}</div>
                    <div className="text-sm text-muted">{when(n.created_at)}</div>
                  </div>
                  {!n.read_at && <span className="badge badge-blue">new</span>}
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
