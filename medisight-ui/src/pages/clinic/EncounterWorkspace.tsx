/**
 * PAGE: Encounter Workspace  /clinic/encounter
 * The core doctor screen. Three-panel layout:
 * Left: patient context (symptoms, meds, allergies)
 * Center: note editor + lock CTA
 * Right: AI suggestion panel + drug check + billing preview
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { AIPanel } from '../../components/AIPanel';
import { CodeCard } from '../../components/CodeCard';
import { SeverityPulse } from '../../components/SeverityPulse';
import { useToast } from '../../components/Toast';
import { doctorAPI, ragAPI } from '../../lib/api';
import type { Patient, SymptomLog, RAGResult, NoteAnalysisResult } from '../../lib/types';

export default function EncounterWorkspace() {
  const { toast }   = useToast();
  const navigate    = useNavigate();
  const location    = useLocation();
  const initPatient = (location.state as { patientId?: number })?.patientId;

  // Patient
  const [patientId, setPatientId]   = useState<number>(initPatient ?? 1);
  const [patient, setPatient]       = useState<Patient | null>(null);
  const [symptoms, setSymptoms]     = useState<SymptomLog[]>([]);
  const [patientLoading, setPL]     = useState(false);

  // Note
  const [noteText, setNoteText]     = useState('');
  const [noteId, setNoteId]         = useState<number | null>(null);
  const [noteLocked, setNoteLocked] = useState(false);
  const [followUp, setFollowUp]     = useState('');
  const [noteLoading, setNL]        = useState(false);

  // AI
  const [ragQuery, setRagQuery]     = useState('');
  const [ragResult, setRagResult]   = useState<RAGResult | null>(null);
  const [ragLoading, setRL]         = useState(false);

  // Billing preview
  const [analysis, setAnalysis]     = useState<NoteAnalysisResult | null>(null);

  function loadPatient(id: number) {
    setPL(true);
    doctorAPI.getPatient(id)
      .then(data => {
        setPatient(data.patient as unknown as Patient);
        setSymptoms(data.symptoms as unknown as SymptomLog[]);
      })
      .catch(() => toast('Patient not found', 'error'))
      .finally(() => setPL(false));
  }

  useEffect(() => {
    if (initPatient) loadPatient(initPatient);
  }, [initPatient]); // eslint-disable-line

  async function saveNote() {
    if (!noteText.trim()) { toast('Write a note first', 'error'); return; }
    setNL(true);
    try {
      const n = noteId
        ? await doctorAPI.updateNote(noteId, patientId, noteText)
        : await doctorAPI.createNote(patientId, noteText);
      setNoteId(n.id);
      toast(`Note #${n.id} saved`, 'success');
    } catch (err: unknown) {
      toast((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed', 'error');
    }
    setNL(false);
  }

  async function lockNote() {
    if (!noteId) { toast('Save the note first', 'error'); return; }
    setNL(true);
    try {
      await doctorAPI.lockNote(noteId, followUp || undefined);
      setNoteLocked(true);
      toast(`Note #${noteId} locked. Running billing AI...`, 'info');
      // Auto-trigger billing analysis
      const res = await ragAPI.analyzeNote(noteId);
      setAnalysis(res);
      toast(`Billing analysis done: ${res.billing_codes.length} codes suggested`, 'success');
    } catch (err: unknown) {
      toast((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Lock failed', 'error');
    }
    setNL(false);
  }

  const runRag = useCallback(async () => {
    if (!ragQuery.trim()) return;
    setRL(true);
    setRagResult(null);
    try {
      const r = await ragAPI.query(ragQuery, patientId || undefined);
      setRagResult(r);
    } catch { toast('AI query failed. Check if RAG pipeline is running.', 'error'); }
    setRL(false);
  }, [ragQuery, patientId, toast]);

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main" style={{ display: 'flex', flexDirection: 'column' }}>
        {/* Topbar */}
        <div className="topbar">
          <div>
            <div className="topbar-title">Encounter Workspace</div>
            <div className="topbar-sub">
              {patient ? `${patient.full_name} · Patient #${patient.id}` : 'Select a patient to begin'}
            </div>
          </div>
          <div className="topbar-right">
            {noteLocked && <span className="tag tag-amber">Note locked</span>}
            {noteId && !noteLocked && <span className="tag tag-teal">Draft #{noteId}</span>}
            <button className="btn btn-ghost" onClick={() => navigate('/clinic/dashboard')}>Back</button>
          </div>
        </div>

        {/* 3-panel workspace */}
        <div className="workspace">
          {/* LEFT: Patient context */}
          <div className="ws-panel ws-left">
            <div className="ws-section-label">Patient Context</div>

            <div className="form-group" style={{ marginBottom: 12 }}>
              <label className="field-label">Patient ID</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  className="field-input" type="number"
                  value={patientId}
                  onChange={e => setPatientId(Number(e.target.value))}
                  style={{ flex: 1 }}
                />
                <button className="btn btn-ghost btn-sm" onClick={() => loadPatient(patientId)} disabled={patientLoading}>
                  {patientLoading ? <span className="spinner" /> : 'Load'}
                </button>
              </div>
            </div>

            {patient && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
                  {patient.full_name}
                </div>
                {[
                  ['DOB', patient.date_of_birth],
                  ['Gender', patient.gender],
                  ['Blood', patient.blood_type],
                ].filter(([, v]) => v).map(([k, v]) => (
                  <div key={k} className="flex-between" style={{ padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                    <span style={{ color: 'var(--text-primary)' }}>{v}</span>
                  </div>
                ))}
                {patient.allergies && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 4 }}>Allergies</div>
                    <span className="tag tag-red" style={{ fontSize: 11 }}>{patient.allergies}</span>
                  </div>
                )}
              </div>
            )}

            <div className="divider" />

            <div className="ws-section-label">Recent Symptoms</div>
            {symptoms.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>
                {patient ? 'No symptoms logged' : 'Load a patient to see symptoms'}
              </div>
            )}
            {symptoms.slice(0, 6).map(s => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                <SeverityPulse severity={s.severity} size="sm" showNumber={false} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.symptom}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {s.duration ?? 'No duration'} · {s.severity}/10
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* CENTER: Note editor */}
          <div className="ws-panel ws-center">
            {noteLocked && (
              <div className="note-locked-banner">
                🔒 This note is locked and part of the official record
              </div>
            )}
            {noteId && !noteLocked && (
              <div className="note-draft-banner">
                ✎ Draft note #{noteId} — not yet locked
              </div>
            )}

            <div className="ws-section-label" style={{ marginBottom: 10 }}>Clinical Note</div>

            <textarea
              className="field-input"
              style={{ minHeight: 260, marginBottom: 14, fontSize: 13.5, lineHeight: 1.7 }}
              placeholder={`Patient presents with...\n\nChief complaint:\nHistory:\nExamination:\nAssessment:\nPlan:\nMedications prescribed:`}
              value={noteText}
              onChange={e => setNoteText(e.target.value)}
              disabled={noteLocked}
            />

            {!noteLocked && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
                <button className="btn btn-ghost" onClick={saveNote} disabled={noteLoading} style={{ flex: 1, justifyContent: 'center' }}>
                  {noteLoading ? <><span className="spinner" /> Saving...</> : noteId ? 'Update Note' : 'Save Draft'}
                </button>
              </div>
            )}

            {noteId && !noteLocked && (
              <>
                <div className="divider" />
                <div className="ws-section-label">Follow-up Instructions</div>
                <textarea
                  className="field-input"
                  style={{ minHeight: 80, marginBottom: 12 }}
                  placeholder="Return in 1 week if symptoms persist. Seek ER if fever above 39C..."
                  value={followUp}
                  onChange={e => setFollowUp(e.target.value)}
                />
                <button
                  className="btn btn-amber btn-wide"
                  onClick={lockNote}
                  disabled={noteLoading}
                >
                  {noteLoading ? <><span className="spinner" /> Processing...</> : '🔒 Lock Note + Trigger Billing AI'}
                </button>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', marginTop: 6 }}>
                  Locking is irreversible and triggers ICD-10/CPT/HCPCS code suggestion
                </div>
              </>
            )}

            {/* Billing preview after analysis */}
            {analysis && (
              <>
                <div className="divider" />
                <div className="ws-section-label">Billing AI Results</div>
                <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                  {analysis.message}
                </div>
                {analysis.billing_codes.slice(0, 4).map((c, i) => (
                  <CodeCard key={i} code={c as { code_type: string; code: string; description: string; confidence?: number; denial_risk?: string }} />
                ))}
                <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={() => navigate('/billing/encounters')}>
                  Review in Billing Portal
                </button>
              </>
            )}
          </div>

          {/* RIGHT: AI panel */}
          <div className="ws-panel ws-right">
            <div className="ws-section-label" style={{ marginBottom: 10 }}>AI Clinical Assistant</div>

            <div style={{ marginBottom: 12 }}>
              <textarea
                className="field-input"
                style={{ minHeight: 88, fontSize: 12.5, marginBottom: 8 }}
                placeholder="Differential for chest pain and fever&#10;Drug interactions for amoxicillin&#10;Management of type 2 diabetes..."
                value={ragQuery}
                onChange={e => setRagQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && e.ctrlKey && runRag()}
              />
              <button
                className="btn btn-primary btn-wide btn-sm"
                onClick={runRag}
                disabled={ragLoading || !ragQuery.trim()}
              >
                {ragLoading ? <><span className="spinner" /> Querying PubMed...</> : '✦ Query Knowledge Base'}
              </button>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 5, textAlign: 'center' }}>
                Ctrl+Enter to query
              </div>
            </div>

            <AIPanel result={ragResult} loading={ragLoading} />

            <div className="divider" />

            {/* Pipeline info */}
            <div className="ws-section-label">Pipeline</div>
            {['N1 Classify', 'N2 Expand', 'N3 Retrieve', 'N4 Judge', 'N5 Generate'].map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'center', marginBottom: 6 }}>
                <div style={{ width: 22, height: 22, background: 'var(--teal-glow)', border: '1px solid var(--teal-border)', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 800, color: 'var(--teal)', flexShrink: 0 }}>
                  {i + 1}
                </div>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
