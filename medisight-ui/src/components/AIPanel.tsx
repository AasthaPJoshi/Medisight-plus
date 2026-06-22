/**
 * COMPONENT: AIPanel
 * Displays the LangGraph RAG pipeline output:
 * - Live/loading state with pipeline step indicator
 * - Cited answer with PMID references highlighted
 * - Clickable PubMed source list
 */

import React from 'react';
import type { RAGResult } from '../lib/types';

interface Props {
  result: RAGResult | null;
  loading: boolean;
  emptyMsg?: string;
}

function formatAnswer(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(
      /\[Source: (PMID:\d+)\]/g,
      '<span class="tag tag-teal" style="font-family:monospace;font-size:10px;margin:0 2px">$1</span>'
    )
    .replace(/### (.*?)(<br>|$)/g, '<div style="font-size:13.5px;font-weight:700;color:var(--text-primary);margin:12px 0 4px">$1</div>')
    .replace(/## (.*?)(<br>|$)/g,  '<div style="font-size:14px;font-weight:800;color:var(--text-primary);margin:14px 0 6px">$1</div>');
}

const PIPELINE_STEPS = [
  'N1: Classify query',
  'N2: Expand with synonyms',
  'N3: BM25 + Pinecone retrieve',
  'N4: Sufficiency check',
  'N5: Generate cited response',
];

export function AIPanel({ result, loading, emptyMsg }: Props) {
  if (loading) {
    return (
      <div className="ai-panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <div className="spinner" />
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              Running RAG pipeline...
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              5-node LangGraph agentic search
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {PIPELINE_STEPS.map((step, i) => (
            <div
              key={i}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                fontSize: 12, color: 'var(--text-muted)',
                animation: `fadeIn ${0.2 + i * 0.15}s ease both`,
              }}
            >
              <div className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5, opacity: 0.5 }} />
              {step}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="card card-dashed">
        <div className="empty">
          <div className="empty-icon">✦</div>
          <div className="empty-title">AI Assistant ready</div>
          <div className="empty-sub">
            {emptyMsg ?? 'Ask a clinical question. The 5-node LangGraph pipeline retrieves PubMed literature and generates a cited response.'}
          </div>
        </div>
      </div>
    );
  }

  if (result.insufficient_context) {
    return (
      <div className="ai-panel">
        <div className="flex-center gap-8" style={{ marginBottom: 10 }}>
          <span className="ai-label">
            <span className="ai-dot" />
            AI Response
          </span>
          <span className="tag tag-amber">Insufficient context</span>
        </div>
        <div className="ai-body" style={{ color: 'var(--amber)' }}>
          {result.answer}
        </div>
      </div>
    );
  }

  return (
    <div className="ai-panel">
      <div className="flex-between" style={{ marginBottom: 12 }}>
        <span className="ai-label">
          <span className="ai-dot" />
          AI Response
        </span>
        <div className="flex-center gap-8">
          <span className="tag tag-teal">{result.query_type}</span>
          <span className="tag tag-slate">{result.sources.length} sources</span>
        </div>
      </div>

      <div
        className="ai-body"
        dangerouslySetInnerHTML={{ __html: formatAnswer(result.answer) }}
      />

      {result.sources.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: 8, fontWeight: 600 }}>
            Referenced Sources
          </div>
          {result.sources.map(s => (
            <a
              key={s.pmid}
              className="source-item"
              href={s.url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="source-pmid">PMID:{s.pmid}</span>
              <span className="source-title">{s.title}</span>
              <span className="source-arrow">↗</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
