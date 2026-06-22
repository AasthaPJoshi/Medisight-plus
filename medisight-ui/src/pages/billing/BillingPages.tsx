import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../../components/Sidebar';
import { CodeCard } from '../../components/CodeCard';
import { useToast } from '../../components/Toast';
import { billingAPI } from '../../lib/api';
import type { BillingEncounter, ICD10Code, CPTCode, HCPCSCode } from '../../lib/types';

// ── BILLING DASHBOARD ─────────────────────────────────────────────────────────
export function BillingDashboard() {
  const { toast } = useToast();
  const navigate  = useNavigate();
  const [encounters, setEncounters] = useState<BillingEncounter[]>([]);
  const [loading, setLoading]       = useState(true);

  useEffect(() => {
    billingAPI.getEncounters()
      .then(setEncounters)
      .catch(() => toast('Could not load encounters', 'error'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  const pending  = encounters.filter(e => e.status === 'pending_review').length;
  const approved = encounters.filter(e => e.status === 'approved').length;
  const flagged  = encounters.filter(e => (e as { has_high_risk_flags?: boolean }).has_high_risk_flags).length;

  return (
    <div className="app-shell">
      <Sidebar pendingCount={pending} />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Billing Dashboard</div>
            <div className="topbar-sub">ICD-10 / CPT / HCPCS Claims Intelligence</div>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost" onClick={() => { setLoading(true); billingAPI.getEncounters().then(setEncounters).finally(() => setLoading(false)); }}>
              Refresh
            </button>
          </div>
        </div>
        <div className="page">
          <div className="stats-row mb-20">
            <div className="stat-card">
              <div className="stat-label">Total Encounters</div>
              <div className="stat-value">{encounters.length}</div>
              <div className="stat-icon">📋</div>
            </div>
            <div className="stat-card" style={{ borderColor: pending ? 'rgba(245,158,11,0.4)' : 'var(--border)' }}>
              <div className="stat-label">Pending Review</div>
              <div className="stat-value" style={{ color: pending ? 'var(--amber)' : 'var(--text-primary)' }}>{pending}</div>
              <div className="stat-meta" style={{ color: pending ? 'var(--amber)' : 'var(--text-muted)' }}>{pending ? 'Needs attention' : 'All clear'}</div>
              <div className="stat-icon">⏳</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Approved</div>
              <div className="stat-value" style={{ color: 'var(--green)' }}>{approved}</div>
              <div className="stat-icon">✓</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">High Risk Flags</div>
              <div className="stat-value" style={{ color: flagged ? 'var(--red)' : 'var(--text-primary)' }}>{flagged}</div>
              <div className="stat-icon">⚠</div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Encounter Queue</div>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate('/billing/encounters')}>View all</button>
            </div>
            {loading && <div style={{ textAlign: 'center', padding: 24 }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}
            {!loading && encounters.length === 0 && (
              <div className="empty">
                <div className="empty-icon">💼</div>
                <div className="empty-title">No encounters yet</div>
                <div className="empty-sub">Billing encounters are created when a doctor locks a clinical note</div>
              </div>
            )}
            {!loading && encounters.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Encounter</th><th>Status</th><th>Codes</th><th>Risk</th><th></th></tr>
                  </thead>
                  <tbody>
                    {encounters.slice(0, 8).map(e => (
                      <tr key={e.id} onClick={() => navigate('/billing/encounters', { state: { encounterId: e.id } })}>
                        <td className="td-primary">Encounter #{e.id}</td>
                        <td>
                          <span className={`tag ${e.status === 'approved' ? 'tag-green' : e.status === 'pending_review' ? 'tag-amber' : 'tag-slate'}`}>
                            {e.status.replace('_', ' ')}
                          </span>
                        </td>
                        <td>{(e as { total_code_suggestions?: number }).total_code_suggestions ?? 0} codes</td>
                        <td>
                          {(e as { has_high_risk_flags?: boolean }).has_high_risk_flags
                            ? <span className="tag tag-red">High risk</span>
                            : <span className="tag tag-green">Low risk</span>}
                        </td>
                        <td><button className="btn btn-ghost btn-sm">Review</button></td>
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

// ── BILLING ENCOUNTERS (approval workspace) ───────────────────────────────────
export function BillingEncounters() {
  const { toast } = useToast();
  const location  = useNavigate();
  const [encounters, setEncounters]     = useState<BillingEncounter[]>([]);
  const [selected, setSelected]         = useState<BillingEncounter | null>(null);
  const [approving, setApproving]       = useState(false);
  const [loadingList, setLoadingList]   = useState(true);

  useEffect(() => {
    billingAPI.getEncounters()
      .then(data => {
        setEncounters(data);
        // Auto-select first pending
        const first = data.find(e => e.status === 'pending_review');
        if (first) loadEncounter(first.id);
      })
      .catch(() => toast('Could not load encounters', 'error'))
      .finally(() => setLoadingList(false));
  }, []); // eslint-disable-line

  async function loadEncounter(id: number) {
    try {
      const e = await billingAPI.getEncounter(id);
      setSelected(e);
    } catch { toast('Could not load encounter', 'error'); }
  }

  async function approveAll() {
    if (!selected) return;
    setApproving(true);
    const ids = (selected.code_suggestions ?? []).map(cs => cs.id);
    try {
      await billingAPI.approveEncounter(selected.id, ids);
      toast('All codes approved', 'success');
      await loadEncounter(selected.id);
      const updated = await billingAPI.getEncounters();
      setEncounters(updated);
    } catch { toast('Approval failed', 'error'); }
    setApproving(false);
  }

  async function approveOne(id: number) {
    if (!selected) return;
    try {
      await billingAPI.approveEncounter(selected.id, [id]);
      await loadEncounter(selected.id);
      toast('Code approved', 'success');
    } catch { toast('Failed', 'error'); }
  }

  async function removeOne(id: number) {
    if (!selected) return;
    try {
      await billingAPI.approveEncounter(selected.id, [], [id]);
      await loadEncounter(selected.id);
      toast('Code removed', 'success');
    } catch { toast('Failed', 'error'); }
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Billing Encounters</div>
            <div className="topbar-sub">Review AI-suggested codes before claim submission</div>
          </div>
        </div>
        <div className="page" style={{ padding: 0 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', height: 'calc(100vh - 58px)', overflow: 'hidden' }}>
            {/* Queue */}
            <div style={{ borderRight: '1px solid var(--border)', padding: 16, overflowY: 'auto', background: 'rgba(10,22,40,0.5)' }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.5px', fontWeight: 600, marginBottom: 12 }}>
                Encounter Queue
              </div>
              {loadingList && <div className="spinner" style={{ margin: '16px auto' }} />}
              {encounters.map(e => (
                <div
                  key={e.id}
                  className={`code-card ${selected?.id === e.id ? 'approved' : ''}`}
                  style={{ cursor: 'pointer', marginBottom: 7 }}
                  onClick={() => loadEncounter(e.id)}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Encounter #{e.id}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {(e as { total_code_suggestions?: number }).total_code_suggestions ?? 0} codes
                    </div>
                  </div>
                  <span className={`tag ${e.status === 'approved' ? 'tag-green' : e.status === 'pending_review' ? 'tag-amber' : 'tag-slate'}`} style={{ fontSize: 10 }}>
                    {e.status.replace('_', ' ')}
                  </span>
                </div>
              ))}
              {!loadingList && encounters.length === 0 && (
                <div className="empty" style={{ padding: '20px 0' }}>
                  <div className="empty-icon" style={{ fontSize: 24 }}>💼</div>
                  <div className="empty-title" style={{ fontSize: 13 }}>No encounters</div>
                </div>
              )}
            </div>

            {/* Detail */}
            <div style={{ overflowY: 'auto', padding: 20 }}>
              {!selected ? (
                <div className="empty" style={{ paddingTop: 80 }}>
                  <div className="empty-icon">◎</div>
                  <div className="empty-title">Select an encounter</div>
                  <div className="empty-sub">Click an encounter from the queue to review its AI-suggested billing codes</div>
                </div>
              ) : (
                <>
                  <div className="flex-between mb-20">
                    <div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>Encounter #{selected.id}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Note #{selected.note_id}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 10 }}>
                      <span className={`tag ${selected.status === 'approved' ? 'tag-green' : 'tag-amber'}`}>
                        {selected.status.replace('_', ' ')}
                      </span>
                      {selected.status !== 'approved' && (
                        <button className="btn btn-primary" onClick={approveAll} disabled={approving}>
                          {approving ? <><span className="spinner" /> Approving...</> : 'Approve All Codes'}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Parsed note data */}
                  {selected.parsed_note_data && (
                    <div className="card mb-20">
                      <div className="card-title" style={{ marginBottom: 12 }}>Parsed Clinical Note</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        {Object.entries(selected.parsed_note_data)
                          .filter(([, v]) => v && (Array.isArray(v) ? v.length > 0 : true))
                          .map(([k, v]) => (
                            <div key={k} style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 7, border: '1px solid var(--border)' }}>
                              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 3 }}>
                                {k.replace(/_/g, ' ')}
                              </div>
                              <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
                                {Array.isArray(v) ? v.join(', ') : String(v)}
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}

                  {/* Code suggestions */}
                  <div className="card">
                    <div className="card-header">
                      <div className="card-title">AI Suggested Codes</div>
                      <span className="tag tag-slate">{selected.code_suggestions?.length ?? 0} codes</span>
                    </div>
                    {!selected.code_suggestions?.length && (
                      <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '12px 0' }}>
                        No codes suggested yet. Trigger billing AI via POST /rag/note-analysis/{selected.note_id}
                      </div>
                    )}
                    {selected.code_suggestions?.map(cs => (
                      <CodeCard
                        key={cs.id}
                        code={cs}
                        showActions={selected.status !== 'approved'}
                        onApprove={() => approveOne(cs.id)}
                        onRemove={() => removeOne(cs.id)}
                      />
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

// ── CODE LOOKUP ───────────────────────────────────────────────────────────────
export function CodeLookup() {
  const { toast }    = useToast();
  const [query, setQuery]         = useState('');
  const [type, setType]           = useState<'icd10' | 'cpt' | 'hcpcs'>('icd10');
  const [results, setResults]     = useState<(ICD10Code | CPTCode | HCPCSCode)[]>([]);
  const [loading, setLoading]     = useState(false);
  const [searched, setSearched]   = useState(false);

  async function doSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      let data: (ICD10Code | CPTCode | HCPCSCode)[] = [];
      if (type === 'icd10') data = await billingAPI.lookupICD10(query);
      else if (type === 'cpt') data = await billingAPI.lookupCPT(query);
      else data = await billingAPI.lookupHCPCS(query);
      setResults(data);
      if (data.length === 0) toast('No codes found. Try a different term.', 'info');
    } catch { toast('Lookup failed', 'error'); }
    setLoading(false);
  }

  const typePill: Record<string, string> = { icd10: 'pill-icd10', cpt: 'pill-cpt', hcpcs: 'pill-hcpcs' };

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div>
            <div className="topbar-title">Billing Code Lookup</div>
            <div className="topbar-sub">Search ICD-10-CM, CPT/MPFS, and HCPCS Level II</div>
          </div>
        </div>
        <div className="page">
          <form className="card mb-20" onSubmit={doSearch}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
              <div style={{ flex: 1 }}>
                <label className="field-label">Search term</label>
                <input
                  className="field-input"
                  placeholder="e.g., diabetes, office visit, insulin, chest pain"
                  value={query} onChange={e => setQuery(e.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <label className="field-label">Code type</label>
                <select className="field-input" style={{ width: 140 }} value={type} onChange={e => setType(e.target.value as typeof type)}>
                  <option value="icd10">ICD-10-CM</option>
                  <option value="cpt">CPT / MPFS</option>
                  <option value="hcpcs">HCPCS Level II</option>
                </select>
              </div>
              <button className="btn btn-primary" type="submit" disabled={loading} style={{ padding: '10px 22px' }}>
                {loading ? <span className="spinner" /> : 'Search'}
              </button>
            </div>
          </form>

          {!searched && (
            <div className="card card-dashed">
              <div className="empty">
                <div className="empty-icon">⊕</div>
                <div className="empty-title">Search for billing codes</div>
                <div className="empty-sub">
                  ICD-10-CM: diagnosis codes (CMS FY2026 free dataset)<br />
                  CPT: procedure codes from CMS Medicare Physician Fee Schedule<br />
                  HCPCS Level II: drugs (J-codes), supplies (A-codes), DME (E-codes)
                </div>
              </div>
            </div>
          )}

          {searched && results.length > 0 && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">{type.toUpperCase()} Results</div>
                <span className="tag tag-slate">{results.length} codes</span>
              </div>
              {results.map(c => (
                <div key={c.code} className="code-card">
                  <div className={`code-type-pill ${typePill[type]}`}>{type.toUpperCase()}</div>
                  <div className="code-info">
                    <div className="code-code">{c.code}</div>
                    <div className="code-desc">{c.description}</div>
                  </div>
                  {(c as CPTCode).payment_amount && (
                    <span style={{ fontSize: 12, color: 'var(--green)', fontWeight: 600, flexShrink: 0 }}>
                      ${(c as CPTCode).payment_amount!.toFixed(2)}
                    </span>
                  )}
                  {(c as CPTCode).rvu != null && (
                    <span className="tag tag-slate">{(c as CPTCode).rvu} RVU</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ── AUDIT LOG ─────────────────────────────────────────────────────────────────
export function AuditLog() {
  const { toast } = useToast();
  const [encounters, setEncounters] = useState<BillingEncounter[]>([]);

  useEffect(() => {
    billingAPI.getEncounters()
      .then(setEncounters)
      .catch(() => toast('Could not load audit data', 'error'));
  }, []); // eslint-disable-line

  const allEvents = encounters.flatMap(e =>
    (e.audit_log ?? []).map(entry => ({ ...entry, encounter_id: e.id }))
  ).sort((a, b) => {
    const at = (a as { timestamp?: string }).timestamp ?? '';
    const bt = (b as { timestamp?: string }).timestamp ?? '';
    return bt.localeCompare(at);
  });

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="topbar">
          <div className="topbar-title">Audit Log</div>
        </div>
        <div className="page">
          <div className="card">
            {allEvents.length === 0 && (
              <div className="empty">
                <div className="empty-icon">◈</div>
                <div className="empty-title">No audit events</div>
                <div className="empty-sub">Audit events are recorded when billing encounters are created and approved</div>
              </div>
            )}
            {allEvents.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Encounter</th><th>Action</th><th>Details</th><th>Timestamp</th></tr>
                  </thead>
                  <tbody>
                    {allEvents.map((ev, i) => {
                      const e = ev as { encounter_id: number; action?: string; details?: string; timestamp?: string; triggered_by?: string; approved_by?: string };
                      return (
                        <tr key={i}>
                          <td className="td-primary">#{e.encounter_id}</td>
                          <td><span className="tag tag-slate">{e.action}</span></td>
                          <td>{e.details ?? e.triggered_by ?? e.approved_by ?? ''}</td>
                          <td>{e.timestamp ? new Date(e.timestamp).toLocaleString() : ''}</td>
                        </tr>
                      );
                    })}
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
