import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { SeverityPulse } from '../../components/SeverityPulse';
import { AIPanel } from '../../components/AIPanel';
import { useToast } from '../../components/Toast';
import { doctorAPI, ragAPI } from '../../lib/api';
import type { Patient, RAGResult } from '../../lib/types';

// ── PATIENT LIST ──────────────────────────────────────────────────────────────
export function PatientList() {
  const { toast } = useToast();
  const navigate  = useNavigate();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [search, setSearch]     = useState('');
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    doctorAPI.getPatients()
      .then(setPatients)
      .catch(() => toast('Could not load patients', 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  const filtered = patients.filter(p =>
    p.full_name.toLowerCase().includes(search.toLowerCase()) ||
    (p.latest_symptom ?? '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="app-shell">
      <Sidebar patientCount={patients.length} />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Patients</div>
            <div className="topbar-sub">{patients.length} assigned</div>
          </div>
          <div className="topbar-right">
            <div className="search-bar" style={{ width: 240 }}>
              <span className="search-icon">⊕</span>
              <input placeholder="Search patients..." value={search} onChange={e => setSearch(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="page">
          <div className="card">
            {loading && <div style={{ textAlign: 'center', padding: 28 }}><div className="spinner spinner-lg" style={{ margin: '0 auto' }} /></div>}
            {!loading && filtered.length === 0 && (
              <div className="empty">
                <div className="empty-icon">◎</div>
                <div className="empty-title">{search ? 'No patients found' : 'No patients assigned'}</div>
                <div className="empty-sub">Assign via API: POST /doctors/patients/{`{id}`}/assign</div>
              </div>
            )}
            {!loading && filtered.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Name</th><th>Email</th><th>Latest Symptom</th><th>Severity</th><th></th></tr>
                  </thead>
                  <tbody>
                    {filtered.map(p => (
                      <tr key={p.id} onClick={() => navigate('/clinic/encounter', { state: { patientId: p.id } })}>
                        <td className="td-primary">{p.full_name}</td>
                        <td>{p.email}</td>
                        <td>{p.latest_symptom ?? 'None logged'}</td>
                        <td>
                          {p.latest_severity
                            ? <SeverityPulse severity={p.latest_severity} />
                            : <span className="tag tag-slate">No data</span>}
                        </td>
                        <td>
                          <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); navigate('/clinic/encounter', { state: { patientId: p.id } }); }}>
                            Open encounter
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ── AI ASSISTANT ──────────────────────────────────────────────────────────────
export function AIAssistant() {
  const { toast }  = useToast();
  const [query, setQuery]     = useState('');
  const [result, setResult]   = useState<RAGResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function runQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const r = await ragAPI.query(query);
      setResult(r);
    } catch { toast('AI query failed', 'error'); }
    setLoading(false);
  }

  const suggestions = [
    'Differential diagnosis for chest pain and fever',
    'Management of type 2 diabetes with hypertension',
    'Drug interactions for warfarin and amoxicillin',
    'Pneumonia clinical presentation and treatment',
  ];

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">AI Clinical Assistant</div>
            <div className="topbar-sub">LangGraph 5-node RAG over 417 PubMed abstracts</div>
          </div>
          <div className="topbar-right">
            <span className="tag tag-teal">450 vectors</span>
            <span className="tag tag-teal">BM25 + Pinecone</span>
          </div>
        </div>
        <div className="page">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
            <div>
              <form className="card mb-20" onSubmit={runQuery}>
                <div className="form-group" style={{ marginBottom: 12 }}>
                  <label className="field-label">Clinical Query</label>
                  <textarea
                    className="field-input"
                    style={{ minHeight: 110 }}
                    placeholder="Ask a clinical question based on the patient's presentation..."
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    autoFocus
                  />
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  <button className="btn btn-primary" type="submit" disabled={loading || !query.trim()} style={{ flex: 1, justifyContent: 'center' }}>
                    {loading ? <><span className="spinner" /> Querying...</> : '✦ Query Knowledge Base'}
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => { setQuery(''); setResult(null); }}>Clear</button>
                </div>
              </form>

              <AIPanel result={result} loading={loading} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Suggestions */}
              <div className="card">
                <div className="card-title" style={{ marginBottom: 12 }}>Sample Queries</div>
                {suggestions.map(s => (
                  <div
                    key={s}
                    className="code-card"
                    style={{ cursor: 'pointer', marginBottom: 6 }}
                    onClick={() => setQuery(s)}
                  >
                    <span style={{ color: 'var(--teal)', fontSize: 12 }}>✦</span>
                    <div className="code-desc" style={{ fontSize: 12 }}>{s}</div>
                  </div>
                ))}
              </div>

              {/* KB Stats */}
              <div className="card">
                <div className="card-title" style={{ marginBottom: 12 }}>Knowledge Base</div>
                {[
                  ['PubMed abstracts', '417'],
                  ['Pinecone vectors', '450'],
                  ['Medical topics', '15'],
                  ['Embedding model', 'MiniLM-L6'],
                  ['Retrieval', 'BM25 + Pinecone RRF'],
                ].map(([k, v]) => (
                  <div key={k} className="flex-between" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                    <span style={{ color: 'var(--teal)', fontWeight: 600 }}>{v}</span>
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
