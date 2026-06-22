/**
 * COMPONENT: SeverityPulse
 * The signature visual element of MediSight+.
 * A breathing animated dot that pulses based on symptom severity.
 * Low (1-3): green slow pulse. Med (4-6): amber medium pulse. High (7-10): red fast pulse.
 */

import React from 'react';

interface Props {
  severity: number;
  showNumber?: boolean;
  size?: 'sm' | 'md';
}

export function SeverityPulse({ severity, showNumber = true, size = 'md' }: Props) {
  const cls = severity <= 3 ? 'low' : severity <= 6 ? 'med' : 'high';
  const color = severity <= 3
    ? 'var(--green)'
    : severity <= 6
    ? 'var(--amber)'
    : 'var(--red)';

  return (
    <span className="severity-pulse">
      <span className={`pulse-dot pulse-${cls}`} style={size === 'sm' ? { width: 6, height: 6 } : {}} />
      {showNumber && (
        <span className="severity-num" style={{ color, fontSize: size === 'sm' ? 12 : 13 }}>
          {severity}/10
        </span>
      )}
    </span>
  );
}
