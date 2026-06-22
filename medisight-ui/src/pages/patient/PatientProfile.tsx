import React, { useState } from 'react';
import { Sidebar } from '../../components/Sidebar';
import { useToast } from '../../components/Toast';
import { useAuth } from '../../context/AuthContext';
import { patientAPI } from '../../lib/api';

export default function PatientProfile() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [dob, setDob]             = useState('');
  const [gender, setGender]       = useState('');
  const [blood, setBlood]         = useState('');
  const [allergies, setAllergies] = useState('');
  const [meds, setMeds]           = useState('');
  const [loading, setLoading]     = useState(false);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await patientAPI.updateProfile({
        date_of_birth: dob || null,
        gender: gender || null,
        blood_type: blood || null,
        allergies: allergies || null,
        current_medications: meds ? meds.split(',').map(m => m.trim()).filter(Boolean) : null,
      });
      toast('Profile saved', 'success');
    } catch { toast('Save failed', 'error'); }
    setLoading(false);
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div className="topbar-title">My Profile</div>
        </div>
        <div className="page" style={{ maxWidth: 540 }}>
          <form className="card" onSubmit={handleSave}>
            {/* User header */}
            <div className="flex-center gap-14" style={{ marginBottom: 22, paddingBottom: 18, borderBottom: '1px solid var(--border)' }}>
              <div className="sidebar-avatar" style={{ width: 46, height: 46, fontSize: 18 }}>
                {(user?.full_name ?? 'U')[0]}
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>{user?.full_name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{user?.email}</div>
                <span className="tag tag-teal">Patient</span>
              </div>
            </div>

            <div className="form-group">
              <label className="field-label">Date of Birth</label>
              <input className="field-input" type="text" placeholder="YYYY-MM-DD" value={dob} onChange={e => setDob(e.target.value)} />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label className="field-label">Gender</label>
                <select className="field-input" value={gender} onChange={e => setGender(e.target.value)}>
                  <option value="">Select</option>
                  {['Male', 'Female', 'Non-binary', 'Prefer not to say'].map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label className="field-label">Blood Type</label>
                <select className="field-input" value={blood} onChange={e => setBlood(e.target.value)}>
                  <option value="">Select</option>
                  {['A+','A-','B+','B-','AB+','AB-','O+','O-'].map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
            </div>

            <div className="form-group">
              <label className="field-label">Known Allergies</label>
              <input className="field-input" placeholder="e.g., Penicillin, Sulfa drugs, Latex" value={allergies} onChange={e => setAllergies(e.target.value)} />
            </div>

            <div className="form-group">
              <label className="field-label">Current Medications (comma-separated)</label>
              <input className="field-input" placeholder="e.g., Metformin 500mg, Lisinopril 10mg" value={meds} onChange={e => setMeds(e.target.value)} />
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <><span className="spinner" /> Saving...</> : 'Save Profile'}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
