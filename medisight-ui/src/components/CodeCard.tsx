/**
 * COMPONENT: CodeCard
 * Displays a single billing code (ICD-10, CPT, or HCPCS) with:
 * - Color-coded type pill
 * - Code in monospace
 * - Description
 * - Confidence bar
 * - Denial risk tag
 * - Approved checkmark
 */

import React from 'react';
import type { CodeSuggestion } from '../lib/types';

interface Props {
  code: CodeSuggestion | {
    code_type: string; code: string; description: string;
    confidence?: number; denial_risk?: string; is_approved?: boolean;
  };
  onApprove?: () => void;
  onRemove?: () => void;
  showActions?: boolean;
}

export function CodeCard({ code, onApprove, onRemove, showActions = false }: Props) {
  const type = code.code_type.toUpperCase();
  const pillClass = type === 'ICD10' ? 'pill-icd10' : type === 'CPT' ? 'pill-cpt' : 'pill-hcpcs';
  const conf = code.confidence ?? 0;
  const risk = code.denial_risk ?? 'low';

  const riskClass =
    risk === 'high'   ? 'tag-red' :
    risk === 'medium' ? 'tag-amber' :
    'tag-green';

  const approved = (code as CodeSuggestion).is_approved;

  return (
    <div className={`code-card ${approved ? 'approved' : ''} ${risk === 'high' ? 'flagged' : ''}`}>
      <div className={`code-type-pill ${pillClass}`}>{type}</div>

      <div className="code-info">
        <div className="code-code">{code.code}</div>
        <div className="code-desc">{code.description}</div>
      </div>

      {conf > 0 && (
        <div className="conf-bar">
          <div className="conf-val">{Math.round(conf * 100)}%</div>
          <div className="conf-track">
            <div className="conf-fill" style={{ width: `${Math.round(conf * 100)}%` }} />
          </div>
        </div>
      )}

      <span className={`tag ${riskClass}`} style={{ fontSize: 10 }}>{risk}</span>

      {approved && <span style={{ color: 'var(--green)', fontSize: 16, flexShrink: 0 }}>✓</span>}

      {showActions && !approved && (
        <div style={{ display: 'flex', gap: 5 }}>
          {onApprove && (
            <button className="btn btn-sm btn-primary" onClick={onApprove}>Approve</button>
          )}
          {onRemove && (
            <button className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button>
          )}
        </div>
      )}
    </div>
  );
}
