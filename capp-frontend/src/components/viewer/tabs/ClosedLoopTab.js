import React, { useState } from 'react';
import {
  FiFileText, FiCode, FiActivity, FiClipboard,
  FiCheckCircle, FiAlertTriangle, FiZap, FiBookOpen,
  FiChevronDown, FiChevronUp,
} from 'react-icons/fi';

// ─── Demo data (Motor Mount, Aviocian Technologies, June 2026) ─────────────────

const DATA_SOURCES = [
  {
    key: 'drawing',
    icon: FiFileText,
    label: 'Engineering Drawing',
    detail: 'Motor Mount · Al 6061',
    meta: 'Aviocian Technologies',
    status: 'collected',
  },
  {
    key: 'program',
    icon: FiCode,
    label: 'CAM Program',
    detail: '3 setups · 20 NC programs',
    meta: '12mm / 4mm / 2mm end mills',
    status: 'collected',
  },
  {
    key: 'machine',
    icon: FiActivity,
    label: 'Machine Data',
    detail: 'Feed overrides · cycle time',
    meta: 'Collected 05 Jun 2026',
    status: 'collected',
  },
  {
    key: 'qc',
    icon: FiClipboard,
    label: 'QC Report',
    detail: '15 dimensions measured',
    meta: 'Inspection date: 01 Apr 2025',
    status: 'collected',
  },
];

const DEVIATIONS = [
  {
    id: 'SL-04',
    feature: 'Ø3.2mm Through Hole',
    nominal: 3.20,
    upper: 0.10,
    lower: 0.10,
    actual: 3.02,
    pass: false,
  },
  {
    id: 'SL-05',
    feature: 'Ø3.2mm Through Hole',
    nominal: 3.20,
    upper: 0.10,
    lower: 0.10,
    actual: 3.03,
    pass: false,
  },
  {
    id: 'SL-13',
    feature: '5mm Depth',
    nominal: 5.00,
    upper: 0.10,
    lower: 0.10,
    actual: 4.80,
    pass: false,
  },
  {
    id: 'SL-01',
    feature: 'Ø16.1mm Bore',
    nominal: 16.10,
    upper: 0.20,
    lower: 0.20,
    actual: 16.02,
    pass: true,
  },
  {
    id: 'SL-03',
    feature: '104.78mm Length',
    nominal: 104.78,
    upper: 0.30,
    lower: 0.30,
    actual: 104.79,
    pass: true,
  },
];

const ROOT_CAUSE = {
  finding: 'Tool deflection under high cutting speed',
  detail:
    'The 2mm end mill was interpolating the Ø3.2mm holes at F1000 mm/min. ' +
    'At this feed rate, the small tool bends slightly under lateral cutting pressure. ' +
    'The deflection causes the tool to remove less material than commanded — ' +
    'producing a hole 0.18mm undersized, outside the ±0.10mm tolerance.',
  evidence: [
    { label: 'Feature', value: 'Ø3.2mm holes (×2)' },
    { label: 'Tool', value: 'Ø2mm end mill (circular interp)' },
    { label: 'Programmed feed', value: 'F1000 mm/min' },
    { label: 'Measured result', value: '3.02mm (−0.18mm)' },
    { label: 'Tolerance band', value: '±0.10mm → FAIL' },
  ],
};

const RULE_ADDED = {
  sheet: '02_process_selection.json',
  rule: {
    trigger: 'circular_interp · Ø ≤ 4mm · tool_dia ≤ 2mm',
    action: 'Reduce Vf: 1000 → 400 mm/min',
    reason: 'Tool deflection observed on Motor Mount (SL-04/05). Slowing feed removes bending effect.',
    added_at: '2026-06-05T14:32:17',
    source: 'closed_loop · job SX_2627_007',
  },
};

// ─── Sub-components ────────────────────────────────────────────────────────────

const sectionLabel = (text) => (
  <div style={{
    fontSize: 10, fontWeight: 700, color: '#8892a4',
    letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10,
  }}>
    {text}
  </div>
);

const DataSourceCard = ({ icon: Icon, label, detail, meta, status }) => (
  <div style={{
    flex: '1 1 120px', minWidth: 120,
    background: 'white', border: '1px solid #dde3ef', borderRadius: 8,
    padding: '12px 12px 10px',
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
      <div style={{
        width: 28, height: 28, borderRadius: 6, background: '#f0f4fb',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        <Icon size={14} color="#1e3a5f" />
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.3, wordBreak: 'break-word' }}>{label}</span>
    </div>
    <div style={{ fontSize: 11, color: '#4a5568', marginBottom: 2 }}>{detail}</div>
    <div style={{ fontSize: 10, color: '#9aa0b0', marginBottom: 8 }}>{meta}</div>
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 10, fontWeight: 600,
      color: status === 'collected' ? '#2d6a4f' : '#b0720a',
      background: status === 'collected' ? '#e8f5e9' : '#fff8e1',
      borderRadius: 4, padding: '3px 7px',
    }}>
      <FiCheckCircle size={10} />
      {status === 'collected' ? 'Collected' : 'Pending'}
    </div>
  </div>
);

const DeviationBar = ({ nominal, upper, lower, actual }) => {
  const range = Math.max(nominal * 0.05, (upper + lower) * 4);
  const min = nominal - range;
  const max = nominal + range;
  const span = max - min;

  const toPercent = (v) => ((v - min) / span) * 100;

  const tolLeft = toPercent(nominal - lower);
  const tolRight = toPercent(nominal + upper);
  const tolWidth = tolRight - tolLeft;
  const actualPos = toPercent(actual);
  const pass = actual >= nominal - lower && actual <= nominal + upper;

  return (
    <div style={{ margin: '8px 0 4px', position: 'relative', height: 20 }}>
      {/* track */}
      <div style={{
        position: 'absolute', top: 8, left: 0, right: 0, height: 4,
        background: '#e8eef7', borderRadius: 2,
      }} />
      {/* tolerance band */}
      <div style={{
        position: 'absolute', top: 6, height: 8,
        left: `${tolLeft}%`, width: `${tolWidth}%`,
        background: '#bbf7d0', borderRadius: 2,
      }} />
      {/* nominal tick */}
      <div style={{
        position: 'absolute', top: 4, height: 12, width: 2,
        left: `${toPercent(nominal)}%`, transform: 'translateX(-50%)',
        background: '#2d6a4f',
      }} />
      {/* actual marker */}
      <div style={{
        position: 'absolute', top: 3, width: 14, height: 14,
        left: `${actualPos}%`, transform: 'translateX(-50%)',
        background: pass ? '#2d6a4f' : '#dc2626',
        borderRadius: '50%', border: '2px solid white',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </div>
  );
};

// ─── Main component ────────────────────────────────────────────────────────────

const ClosedLoopTab = () => {
  const [ruleExpanded, setRuleExpanded] = useState(false);

  const failing = DEVIATIONS.filter(d => !d.pass);
  const passing = DEVIATIONS.filter(d => d.pass);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, paddingTop: 4 }}>

      {/* Demo badge */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 10px', background: '#eff6ff',
        border: '1px solid #bfdbfe', borderRadius: 6, fontSize: 11, color: '#1d4ed8',
      }}>
        <FiZap size={12} />
        <span><strong>Demo part:</strong> Motor Mount · Aviocian Technologies · Job SX_2627_007</span>
      </div>

      {/* ── Section 1: Data sources ── */}
      <div>
        {sectionLabel('Step 1 — Data Collected')}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {DATA_SOURCES.map(s => (
            <DataSourceCard key={s.key} {...s} />
          ))}
        </div>
      </div>

      {/* ── Section 2: Deviation analysis ── */}
      <div>
        {sectionLabel('Step 2 — Deviation Analysis')}

        {/* Summary pills */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '5px 10px', borderRadius: 20,
            background: '#fee2e2', fontSize: 11, fontWeight: 700, color: '#991b1b',
          }}>
            <FiAlertTriangle size={11} /> {failing.length} FAIL
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '5px 10px', borderRadius: 20,
            background: '#dcfce7', fontSize: 11, fontWeight: 700, color: '#166534',
          }}>
            <FiCheckCircle size={11} /> {passing.length} PASS
          </div>
          <div style={{
            padding: '5px 10px', borderRadius: 20,
            background: '#f4f6fb', fontSize: 11, fontWeight: 600, color: '#6b7a99',
          }}>
            {DEVIATIONS.length} measured
          </div>
        </div>

        {/* Failing features */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {DEVIATIONS.map(d => {
            const deviation = (d.actual - d.nominal).toFixed(2);
            const devSign = d.actual >= d.nominal ? '+' : '';
            return (
              <div key={d.id} style={{
                background: d.pass ? 'white' : '#fff5f5',
                border: `1px solid ${d.pass ? '#dde3ef' : '#fca5a5'}`,
                borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ display: 'flex', align: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#9aa0b0', marginRight: 6 }}>{d.id}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: '#1a1a2e' }}>{d.feature}</span>
                  </div>
                  <div style={{
                    fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                    background: d.pass ? '#dcfce7' : '#fee2e2',
                    color: d.pass ? '#166534' : '#991b1b',
                  }}>
                    {d.pass ? 'PASS' : 'FAIL'}
                  </div>
                </div>
                <DeviationBar {...d} />
                <div style={{ display: 'flex', gap: 16, marginTop: 6, fontSize: 11 }}>
                  <span style={{ color: '#6b7a99' }}>
                    Nominal <strong style={{ color: '#1a1a2e' }}>{d.nominal.toFixed(2)}</strong>
                  </span>
                  <span style={{ color: '#6b7a99' }}>
                    Tol <strong style={{ color: '#1a1a2e' }}>±{d.upper.toFixed(2)}</strong>
                  </span>
                  <span style={{ color: '#6b7a99' }}>
                    Actual <strong style={{ color: d.pass ? '#166534' : '#dc2626' }}>{d.actual.toFixed(2)}</strong>
                  </span>
                  <span style={{ color: '#6b7a99' }}>
                    Δ <strong style={{ color: d.pass ? '#166534' : '#dc2626' }}>{devSign}{deviation}</strong>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Section 3: Root cause ── */}
      <div>
        {sectionLabel('Step 3 — Root Cause Identified')}
        <div style={{
          background: 'white', border: '1px solid #fca5a5',
          borderLeft: '4px solid #dc2626', borderRadius: 8, padding: '14px 14px 12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <FiZap size={14} color="#dc2626" />
            <span style={{ fontSize: 13, fontWeight: 700, color: '#1a1a2e' }}>
              {ROOT_CAUSE.finding}
            </span>
          </div>
          <p style={{ fontSize: 12, color: '#4a5568', lineHeight: 1.6, marginBottom: 12 }}>
            {ROOT_CAUSE.detail}
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {ROOT_CAUSE.evidence.map(e => (
              <div key={e.label} style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 11, padding: '4px 0',
                borderBottom: '1px solid #f9e9e9',
              }}>
                <span style={{ color: '#9aa0b0' }}>{e.label}</span>
                <span style={{ fontWeight: 600, color: '#1a1a2e', fontFamily: 'monospace', fontSize: 11 }}>{e.value}</span>
              </div>
            ))}
          </div>

          <div style={{
            marginTop: 12, padding: '10px 12px',
            background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6,
            fontSize: 11, color: '#166534',
          }}>
            <strong>Fix:</strong> Reduce feed rate for 2mm end mill circular interpolation from F1000 → F400 mm/min. Removing bending effect brings hole within tolerance.
          </div>
        </div>
      </div>

      {/* ── Section 4: Rule auto-added ── */}
      <div>
        {sectionLabel('Step 4 — Rule Auto-Added to System')}
        <div style={{
          background: '#f0fdf4', border: '1px solid #86efac',
          borderRadius: 8, padding: '12px 14px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FiBookOpen size={14} color="#16a34a" />
              <span style={{ fontSize: 12, fontWeight: 700, color: '#166534' }}>
                Rule written to <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{RULE_ADDED.sheet}</span>
              </span>
            </div>
            <button
              onClick={() => setRuleExpanded(e => !e)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: '#16a34a', display: 'flex', alignItems: 'center', gap: 4,
                fontSize: 11,
              }}
            >
              {ruleExpanded ? <><FiChevronUp size={13} /> Hide</> : <><FiChevronDown size={13} /> View rule</>}
            </button>
          </div>

          <div style={{ fontSize: 11, color: '#166534' }}>
            <strong>Trigger:</strong> {RULE_ADDED.rule.trigger} &nbsp;→&nbsp; <strong>Action:</strong> {RULE_ADDED.rule.action}
          </div>

          {ruleExpanded && (
            <div style={{
              marginTop: 10, padding: '10px 12px',
              background: 'white', border: '1px solid #bbf7d0', borderRadius: 6,
            }}>
              <pre style={{
                fontFamily: 'monospace', fontSize: 10, color: '#1a1a2e',
                whiteSpace: 'pre-wrap', margin: 0, lineHeight: 1.6,
              }}>
{JSON.stringify({
  trigger: RULE_ADDED.rule.trigger,
  action: RULE_ADDED.rule.action,
  reason: RULE_ADDED.rule.reason,
  added_at: RULE_ADDED.rule.added_at,
  source: RULE_ADDED.rule.source,
}, null, 2)}
              </pre>
            </div>
          )}

          <div style={{ marginTop: 8, fontSize: 10, color: '#4ade80' }}>
            Added {new Date(RULE_ADDED.rule.added_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })} · {RULE_ADDED.rule.source}
          </div>
        </div>

        {/* Punchline */}
        <div style={{
          marginTop: 10, padding: '10px 14px',
          background: '#1e2433', borderRadius: 8,
          fontSize: 12, color: '#c0c8d8', lineHeight: 1.6, fontStyle: 'italic',
        }}>
          "Next time a Ø3.2mm hole appears in any drawing with a 2mm tool — the fix is already built in. The system will never make this mistake again."
        </div>
      </div>

    </div>
  );
};

export default ClosedLoopTab;
