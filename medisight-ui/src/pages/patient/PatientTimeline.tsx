import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { SeverityPulse } from '../../components/SeverityPulse';
import { useToast } from '../../components/Toast';
import { patientAPI } from '../../lib/api';
import type { SymptomLog } from '../../lib/types';

export default function PatientTimeline() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [symptoms, setSymptoms] = useState<SymptomLog[]>([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    patientAPI.getSymptoms(100)
      .then(setSymptoms)
      .catch(() => toast('Could not load timeline', 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">My Health Timeline</div>
            <div className="topbar-sub">{symptoms.length} events recorded</div>
          </div>
          <div className="topbar-right">
            <button className="btn btn-primary" onClick={() => navigate('/patient/symptoms')}>
              + Log Symptom
            </button>
          </div>
        </div>

        <div className="page">
          <div className="card">
            {loading && (
              <div style={{ textAlign: 'center', padding: 36 }}>
                <div className="spinner spinner-lg" style={{ margin: '0 auto' }} />
              </div>
            )}

            {!loading && symptoms.length === 0 && (
              <div className="empty">
                <div className="empty-icon">◷</div>
                <div className="empty-title">No events yet</div>
                <div className="empty-sub">Your health timeline will appear here as you log symptoms and visit your doctor</div>
                <button className="btn btn-primary btn-sm" style={{ marginTop: 14 }} onClick={() => navigate('/patient/symptoms')}>
                  Log your first symptom
                </button>
              </div>
            )}

            {!loading && symptoms.length > 0 && (
              <div className="timeline-list">
                {symptoms.map(s => (
                  <div key={s.id} className="timeline-item">
                    <div className="timeline-dot dot-symptom">❤</div>
                    <div className="timeline-content">
                      <div className="timeline-title">{s.symptom}</div>
                      <div className="flex-center gap-8" style={{ margin: '5px 0' }}>
                        <SeverityPulse severity={s.severity} />
                        {s.duration && <span className="tag tag-slate">{s.duration}</span>}
                      </div>
                      {s.notes && <div className="timeline-detail">{s.notes}</div>}
                      <div className="timeline-time">{new Date(s.logged_at).toLocaleString()}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
