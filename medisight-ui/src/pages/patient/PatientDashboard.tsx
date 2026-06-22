import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../components/Toast';
import { Sidebar } from '../../components/Sidebar';
import { SeverityPulse } from '../../components/SeverityPulse';
import { patientAPI } from '../../lib/api';
import type { SymptomLog } from '../../lib/types';

export default function PatientDashboard() {
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [symptoms, setSymptoms] = useState<SymptomLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    patientAPI.getSymptoms(10)
      .then(setSymptoms)
      .catch(() => toast('Could not load symptoms', 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  const avg = symptoms.length
    ? (symptoms.reduce((s, x) => s + x.severity, 0) / symptoms.length).toFixed(1)
    : '--';

  const firstName = user?.full_name?.split(' ')[0] ?? 'there';

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        {/* Topbar */}
        <div className="topbar">
          <div>
            <div className="topbar-title">Good day, {firstName}</div>
            <div className="topbar-sub">Here is your health overview</div>
          </div>
          <div className="topbar-right">
            <button className="btn btn-primary" onClick={() => navigate('/patient/symptoms')}>
              + Log Symptom
            </button>
          </div>
        </div>

        <div className="page">
          {/* Stats */}
          <div className="stats-row mb-20">
            <div className="stat-card">
              <div className="stat-label">Symptoms Logged</div>
              <div className="stat-value">{symptoms.length}</div>
              <div className="stat-meta positive">This session</div>
              <div className="stat-icon">📋</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Avg Severity</div>
              <div className="stat-value"
                style={{ color: Number(avg) <= 3 ? 'var(--green)' : Number(avg) <= 6 ? 'var(--amber)' : 'var(--red)' }}>
                {avg}
              </div>
              <div className="stat-meta">Out of 10</div>
              <div className="stat-icon">📊</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Last Logged</div>
              <div className="stat-value" style={{ fontSize: 17 }}>
                {symptoms[0]
                  ? new Date(symptoms[0].logged_at).toLocaleDateString('en', { month: 'short', day: 'numeric' })
                  : '--'}
              </div>
              <div className="stat-icon">📅</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Status</div>
              <div className="stat-value" style={{ fontSize: 17, color: 'var(--teal)' }}>Active</div>
              <div className="stat-meta positive">Monitoring</div>
              <div className="stat-icon">✓</div>
            </div>
          </div>

          <div className="grid-2">
            {/* Recent symptoms */}
            <div className="card">
              <div className="card-header">
                <div>
                  <div className="card-title">Recent Symptoms</div>
                  <div className="card-sub">Your latest logged entries</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => navigate('/patient/timeline')}>
                  View all
                </button>
              </div>

              {loading && <div style={{ textAlign: 'center', padding: 24 }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}

              {!loading && symptoms.length === 0 && (
                <div className="empty">
                  <div className="empty-icon">📋</div>
                  <div className="empty-title">No symptoms logged yet</div>
                  <div className="empty-sub">Start tracking your health</div>
                  <button className="btn btn-primary btn-sm" style={{ marginTop: 12 }} onClick={() => navigate('/patient/symptoms')}>
                    Log first symptom
                  </button>
                </div>
              )}

              {symptoms.slice(0, 5).map(s => (
                <div key={s.id} className="code-card" style={{ marginBottom: 7 }}>
                  <SeverityPulse severity={s.severity} showNumber={false} />
                  <div className="code-info">
                    <div className="code-code" style={{ fontFamily: 'inherit', fontSize: 13.5 }}>{s.symptom}</div>
                    <div className="code-desc">{s.duration ?? 'Duration not specified'}</div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: s.severity <= 3 ? 'var(--green)' : s.severity <= 6 ? 'var(--amber)' : 'var(--red)', lineHeight: 1 }}>
                      {s.severity}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>/10</div>
                  </div>
                </div>
              ))}

              <button
                className="btn btn-primary btn-sm"
                style={{ marginTop: 12 }}
                onClick={() => navigate('/patient/symptoms')}
              >
                + Log New Symptom
              </button>
            </div>

            {/* How it works */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">How MediSight+ works</div>
              </div>
              {[
                ['1', '📝', 'Log your symptoms', 'Record what you feel with severity ratings so your doctor has accurate, timestamped data.'],
                ['2', '👨‍⚕️', 'Doctor reviews with AI', 'Your doctor sees your timeline and gets AI-assisted clinical suggestions from PubMed literature.'],
                ['3', '📋', 'Get your care plan', 'Receive a plain-English summary of your visit and follow-up instructions from your doctor.'],
              ].map(([n, icon, title, desc]) => (
                <div key={n} className="flex" style={{ gap: 12, marginBottom: 16 }}>
                  <div style={{
                    width: 27, height: 27, flexShrink: 0,
                    background: 'var(--teal-glow)', border: '1px solid var(--teal-border)',
                    borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 800, color: 'var(--teal)',
                  }}>{n}</div>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>
                      {icon} {title}
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>{desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
