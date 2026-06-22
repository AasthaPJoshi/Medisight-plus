import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { useToast } from '../../components/Toast';
import { patientAPI } from '../../lib/api';

export default function LogSymptom() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [symptom, setSymptom]   = useState('');
  const [severity, setSeverity] = useState(5);
  const [duration, setDuration] = useState('');
  const [notes, setNotes]       = useState('');
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!symptom.trim()) { toast('Please enter a symptom', 'error'); return; }
    setLoading(true);
    try {
      await patientAPI.logSymptom({ symptom, severity, duration: duration || undefined, notes: notes || undefined });
      toast('Symptom logged', 'success');
      navigate('/patient/dashboard');
    } catch { toast('Failed to save', 'error'); }
    setLoading(false);
  }

  const sevColor = severity <= 3 ? 'var(--green)' : severity <= 6 ? 'var(--amber)' : 'var(--red)';

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Log a Symptom</div>
            <div className="topbar-sub">Help your doctor understand how you are feeling</div>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost" onClick={() => navigate('/patient/dashboard')}>Cancel</button>
          </div>
        </div>

        <div className="page" style={{ maxWidth: 560 }}>
          <form className="card" onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="field-label">What symptom are you experiencing?</label>
              <input
                className="field-input" autoFocus
                placeholder="e.g., chest pain, headache, shortness of breath"
                value={symptom} onChange={e => setSymptom(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label className="field-label">
                Severity: <span style={{ color: sevColor, fontWeight: 700 }}>{severity} / 10</span>
              </label>
              <input
                type="range" min={1} max={10} value={severity}
                className="range-input" style={{ width: '100%', marginTop: 8 }}
                onChange={e => setSeverity(Number(e.target.value))}
              />
              <div className="flex-between" style={{ marginTop: 5 }}>
                {['Mild (1-3)', 'Moderate (4-6)', 'Severe (7-10)'].map(l => (
                  <span key={l} style={{ fontSize: 11, color: 'var(--text-muted)' }}>{l}</span>
                ))}
              </div>
            </div>

            <div className="form-group">
              <label className="field-label">How long have you had this?</label>
              <input className="field-input" placeholder="e.g., 2 days, since this morning" value={duration} onChange={e => setDuration(e.target.value)} />
            </div>

            <div className="form-group">
              <label className="field-label">Additional notes</label>
              <textarea className="field-input" placeholder="Describe triggers, what makes it worse or better..." value={notes} onChange={e => setNotes(e.target.value)} />
            </div>

            <button className="btn btn-primary btn-wide" type="submit" disabled={loading}>
              {loading ? <><span className="spinner" /> Saving...</> : 'Save Symptom'}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
