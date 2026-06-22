/**
 * PAGE: Landing Page  /
 * Public-facing product overview. No auth required.
 * Routes visitors to the correct portal login.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function LandingPage() {
  const navigate = useNavigate();

  const roles = [
    {
      icon: '🧑',
      title: 'For Patients',
      desc: 'Log symptoms with severity scoring, view your health timeline, and read doctor summaries in plain language.',
      features: ['Symptom severity tracker', 'Chronological health timeline', 'Plain-English visit summaries', 'Follow-up instructions'],
      cta: 'Patient portal',
      path: '/patient/login',
      tag: 'tag-teal',
    },
    {
      icon: '👨‍⚕️',
      title: 'For Clinicians',
      desc: 'AI-assisted differential diagnoses from 450+ PubMed abstracts with cited sources, inline while you write notes.',
      features: ['LangGraph 5-node RAG pipeline', 'PubMed citation engine', 'Drug interaction checks', 'Billing code preview'],
      cta: 'Clinic portal',
      path: '/clinic/login',
      tag: 'tag-teal',
    },
    {
      icon: '💼',
      title: 'For Billing Teams',
      desc: 'AI-suggested ICD-10, CPT, and HCPCS codes from locked clinical notes, with denial risk detection before submission.',
      features: ['ICD-10-CM auto-suggestion', 'CPT from CMS MPFS', 'HCPCS Level II J-codes', 'Denial risk flagging'],
      cta: 'Billing portal',
      path: '/billing/login',
      tag: 'tag-teal',
    },
  ];

  const features = [
    { icon: '✦', title: 'Agentic RAG Pipeline', desc: 'LangGraph 5-node system: classify, expand, retrieve, judge, generate. Hallucination guardrail at N4.' },
    { icon: '🏥', title: 'Clinical Knowledge Base', desc: '417 PubMed abstracts, 450 Pinecone vectors, BM25 hybrid retrieval with RRF fusion.' },
    { icon: '💳', title: 'Claims Intelligence', desc: 'ICD-10-CM, CPT/MPFS, and HCPCS Level II from free CMS datasets. Denial risk before submission.' },
    { icon: '🔒', title: 'Governed Workflows', desc: 'JWT role-based access. Patient, doctor, and billing staff each see only their portal.' },
    { icon: '📊', title: 'LLMOps Ready', desc: 'Langfuse tracing, Ragas CI eval gate, Prometheus metrics, Grafana dashboard.' },
    { icon: '⚡', title: 'Production Stack', desc: 'FastAPI + PostgreSQL + Pinecone + Redis + Railway + Vercel. Claude Haiku and Sonnet.' },
  ];

  return (
    <div className="landing">
      {/* Nav */}
      <nav className="landing-nav">
        <div className="landing-nav-logo">Medi<span>Sight</span>+</div>
        <div className="landing-nav-links">
          <a href="#features">Features</a>
          <a href="#portals">Portals</a>
        </div>
        <button className="btn btn-primary btn-sm" style={{ marginLeft: 16 }} onClick={() => navigate('/login')}>
          Sign in
        </button>
      </nav>

      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-eyebrow">
          <span className="ai-dot" />
          Clinical AI Platform
        </div>
        <h1 className="landing-h1">
          Patient care meets<br /><span>claims intelligence</span>
        </h1>
        <p className="landing-lead">
          From symptom logging to locked notes to ICD-10 billing codes.
          MediSight+ is one governed platform for patients, clinicians, and billing teams.
        </p>
        <div className="landing-actions">
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/login')}>
            Get started
          </button>
          <button className="btn btn-ghost btn-lg" onClick={() => navigate('/clinic/login')}>
            Clinic demo
          </button>
        </div>

        {/* Stack tags */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 7, marginTop: 36 }}>
          {['LangGraph', 'Pinecone', 'Claude API', 'FastAPI', 'ICD-10-CM', 'CPT/MPFS', 'HCPCS', 'BM25 + RRF'].map(t => (
            <span key={t} className="tag tag-slate">{t}</span>
          ))}
        </div>
      </section>

      {/* Role cards */}
      <section id="portals" className="landing-section" style={{ paddingTop: 56 }}>
        <h2 className="landing-section-title">Three portals, one platform</h2>
        <p className="landing-section-sub">Each role enters through a dedicated portal with context-appropriate tools and permissions.</p>
        <div className="role-cards">
          {roles.map(r => (
            <div key={r.title} className="role-card">
              <div className="role-card-icon">{r.icon}</div>
              <div className="role-card-title">{r.title}</div>
              <div className="role-card-desc">{r.desc}</div>
              <ul style={{ listStyle: 'none', marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 5 }}>
                {r.features.map(f => (
                  <li key={f} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--text-secondary)' }}>
                    <span style={{ color: 'var(--teal)', fontSize: 11 }}>✓</span> {f}
                  </li>
                ))}
              </ul>
              <button className="btn btn-primary btn-sm" onClick={() => navigate(r.path)}>
                {r.cta} &rarr;
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section id="features" className="landing-section" style={{ background: 'rgba(17,32,64,0.4)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
        <h2 className="landing-section-title">Built for production</h2>
        <p className="landing-section-sub">Every layer is real. Every data source is free and publicly documented.</p>
        <div className="feature-grid">
          {features.map(f => (
            <div key={f.title} className="feature-item">
              <div className="feature-item-icon">{f.icon}</div>
              <div className="feature-item-title">{f.title}</div>
              <div className="feature-item-desc">{f.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div>MediSight+ by Aastha Joshi</div>
        <div style={{ display: 'flex', gap: 16 }}>
          <span className="tag tag-teal">MS Information Systems, SDSU</span>
          <span className="tag tag-slate">FastAPI + LangGraph + Claude</span>
        </div>
      </footer>
    </div>
  );
}
