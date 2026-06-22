import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { SeverityPulse } from '../../components/SeverityPulse';
import { useToast } from '../../components/Toast';
import { useAuth } from '../../context/AuthContext';
import { doctorAPI } from '../../lib/api';
import type { Patient } from '../../lib/types';

export default function ClinicDashboard() {
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate  = useNavigate();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    doctorAPI.getPatients()
      .then(setPatients)
      .catch(() => toast('Could not load patients', 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  const lastName = user?.full_name?.split(' ').slice(-1)[0] ?? 'Doctor';

  return (
    <div className="app-shell">
      <Sidebar patientCount={patients.length} />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Clinical Dashboard</div>
            <div className="topbar-sub">Dr. {lastName}</div>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost" onClick={() => { setLoading(true); doctorAPI.getPatients().then(setPatients).finally(() => setLoading(false)); }}>
              Refresh
            </button>
            <button className="btn btn-primary" onClick={() => navigate('/clinic/ai')}>✦ AI Assistant</button>
          </div>
        </div>

        <div className="page">
          <div className="stats-row mb-20">
            <div className="stat-card">
              <div className="stat-label">Assigned Patients</div>
              <div className="stat-value">{patients.length}</div>
              <div className="stat-icon">◎</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Knowledge Base</div>
              <div className="stat-value" style={{ color: 'var(--teal)', fontSize: 18 }}>450</div>
              <div className="stat-meta positive">PubMed vectors</div>
              <div className="stat-icon">✦</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">RAG Pipeline</div>
              <div className="stat-value" style={{ fontSize: 16, color: 'var(--teal)' }}>Ready</div>
              <div className="stat-meta positive">5-node LangGraph</div>
              <div className="stat-icon">◈</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Code Sets</div>
              <div className="stat-value" style={{ fontSize: 16 }}>3</div>
              <div className="stat-meta">ICD-10, CPT, HCPCS</div>
              <div className="stat-icon">💳</div>
            </div>
          </div>

          <div className="grid-2">
            {/* Patient list */}
            <div className="card">
              <div className="card-header">
                <div>
                  <div className="card-title">Assigned Patients</div>
                  <div className="card-sub">Click a row to open encounter workspace</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => navigate('/clinic/patients')}>View all</button>
              </div>

              {loading && <div style={{ textAlign: 'center', padding: 24 }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}

              {!loading && patients.length === 0 && (
                <div className="empty">
                  <div className="empty-icon">◎</div>
                  <div className="empty-title">No patients assigned</div>
                  <div className="empty-sub">Assign patients via the API: POST /doctors/patients/{`{id}`}/assign</div>
                </div>
              )}

              {!loading && patients.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Patient</th><th>Latest Symptom</th><th>Severity</th></tr>
                    </thead>
                    <tbody>
                      {patients.slice(0, 6).map(p => (
                        <tr key={p.id} onClick={() => navigate('/clinic/encounter', { state: { patientId: p.id } })}>
                          <td className="td-primary">{p.full_name}</td>
                          <td>{p.latest_symptom ?? 'None logged'}</td>
                          <td>
                            {p.latest_severity
                              ? <SeverityPulse severity={p.latest_severity} />
                              : <span className="tag tag-slate">No data</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Quick actions */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">Quick Actions</div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[
                  { icon: '✦', label: 'AI Clinical Query', sub: 'Query 450 PubMed vectors', path: '/clinic/ai', color: 'var(--teal)' },
                  { icon: '✎', label: 'New Clinical Note', sub: 'Write and lock an encounter note', path: '/clinic/encounter', color: 'var(--text-primary)' },
                  { icon: '◎', label: 'Patient List', sub: `${patients.length} assigned patients`, path: '/clinic/patients', color: 'var(--text-primary)' },
                ].map(item => (
                  <div
                    key={item.path}
                    className="code-card"
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(item.path)}
                  >
                    <span style={{ fontSize: 20, color: item.color, width: 28, textAlign: 'center', flexShrink: 0 }}>{item.icon}</span>
                    <div className="code-info">
                      <div className="code-code" style={{ fontFamily: 'inherit', fontSize: 13.5, color: item.color }}>{item.label}</div>
                      <div className="code-desc">{item.sub}</div>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>›</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
