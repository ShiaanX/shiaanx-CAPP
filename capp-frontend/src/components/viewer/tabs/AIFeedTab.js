import React, { useState, useEffect } from 'react';
import {
  FiActivity, FiDatabase, FiCpu, FiTrendingUp,
  FiArrowRight, FiCheckCircle, FiZap,
} from 'react-icons/fi';

// ─── Demo data ─────────────────────────────────────────────────────────────────

const VENDORS = [
  {
    name: 'Aviocian Technologies',
    location: 'Bengaluru',
    jobs: 12,
    parts: 38,
    color: '#3b82f6',
    bg: '#eff6ff',
    border: '#bfdbfe',
    dataPoints: ['Program sheets', 'Inspection reports', 'Feed overrides', 'Cycle time logs'],
  },
  {
    name: 'Krishnamurthy CNC',
    location: 'Pune',
    jobs: 8,
    parts: 21,
    color: '#8b5cf6',
    bg: '#f5f3ff',
    border: '#ddd6fe',
    dataPoints: ['Program sheets', 'QC reports', 'Tool change logs'],
  },
  {
    name: 'TS Engg',
    location: 'Chennai',
    jobs: 5,
    parts: 14,
    color: '#0891b2',
    bg: '#ecfeff',
    border: '#a5f3fc',
    dataPoints: ['Program sheets', 'Deviation reports', 'Setup photos'],
  },
];

const MODEL_INPUTS = [
  { label: 'Tool deflection events', count: 47, icon: FiActivity, color: '#dc2626' },
  { label: 'Feed overrides captured', count: 312, icon: FiTrendingUp, color: '#f59e0b' },
  { label: 'Rule updates applied', count: 9, icon: FiDatabase, color: '#16a34a' },
  { label: 'Parts re-run after fix', count: 23, icon: FiCheckCircle, color: '#2563eb' },
];

const LEARNING_EVENTS = [
  {
    date: '05 Jun 2026',
    event: 'Ø3.2mm hole deflection — Motor Mount',
    action: 'Vf reduced: 1000 → 400 mm/min for Ø≤4mm circular interp',
    source: 'Aviocian Technologies',
    impact: '2 future jobs auto-corrected',
  },
  {
    date: '18 May 2026',
    event: 'Surface roughness Ra >1.6 on Al pocket',
    action: 'Finish pass Vc boosted: 180 → 220 m/min',
    source: 'Krishnamurthy CNC',
    impact: 'Applied to 4 subsequent pocket operations',
  },
  {
    date: '03 Apr 2026',
    event: 'Drill walking on thin-wall bracket',
    action: 'Center drill depth rule updated for t < 3mm walls',
    source: 'TS Engg',
    impact: '1 job correction, rule propagated system-wide',
  },
];

// ─── Animated flow line ─────────────────────────────────────────────────────────

const FlowDot = ({ delay, color }) => {
  const [pos, setPos] = useState(0);
  useEffect(() => {
    const start = Date.now() + delay;
    let raf;
    const tick = () => {
      const elapsed = (Date.now() - start) % 2000;
      setPos(Math.max(0, elapsed / 2000));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [delay]);

  return (
    <div style={{
      position: 'absolute',
      left: `${pos * 100}%`,
      top: '50%',
      transform: 'translate(-50%, -50%)',
      width: 7, height: 7, borderRadius: '50%',
      background: color,
      boxShadow: `0 0 6px ${color}`,
      opacity: 0.9,
    }} />
  );
};

const FlowLine = ({ color }) => (
  <div style={{ position: 'relative', height: 3, background: '#e8eef7', borderRadius: 2, margin: '10px 0', overflow: 'hidden' }}>
    <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(90deg, transparent, ${color}22, transparent)` }} />
    <FlowDot delay={0} color={color} />
    <FlowDot delay={700} color={color} />
  </div>
);

// ─── Main component ─────────────────────────────────────────────────────────────

const AIFeedTab = () => {
  const [expanded, setExpanded] = useState(null);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, paddingTop: 4 }}>

      {/* Header badge */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 10px', background: '#eff6ff',
        border: '1px solid #bfdbfe', borderRadius: 6, fontSize: 11, color: '#1d4ed8',
      }}>
        <FiZap size={12} />
        <span><strong>AI Engine Feed</strong> — real manufacturing data flowing into the model</span>
      </div>

      {/* Vendor cards → flow → model */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
          Data Sources — 3 Vendors
        </div>

        {VENDORS.map((v, i) => (
          <div key={v.name} style={{ marginBottom: 4 }}>
            {/* Vendor card */}
            <div style={{
              background: v.bg, border: `1px solid ${v.border}`, borderRadius: 8,
              padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#1a1a2e' }}>{v.name}</div>
                <div style={{ fontSize: 10, color: '#9aa0b0', marginTop: 1 }}>{v.location} · {v.jobs} jobs · {v.parts} parts</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                  {v.dataPoints.map(dp => (
                    <span key={dp} style={{
                      fontSize: 9, fontWeight: 600, padding: '2px 6px',
                      background: 'white', border: `1px solid ${v.border}`,
                      borderRadius: 4, color: v.color,
                    }}>{dp}</span>
                  ))}
                </div>
              </div>
              <FiArrowRight size={14} color={v.color} style={{ flexShrink: 0, marginLeft: 8 }} />
            </div>

            {/* Animated flow line */}
            <FlowLine color={v.color} />
          </div>
        ))}

        {/* AI Model box */}
        <div style={{
          background: '#1e2433', borderRadius: 10, padding: '14px 16px',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <FiCpu size={18} color="white" />
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'white' }}>ShiaanX Process Intelligence</div>
            <div style={{ fontSize: 10, color: '#8892a4', marginTop: 2 }}>Learning from every cut · 73 jobs · 3 vendors</div>
          </div>
        </div>
      </div>

      {/* Model input stats */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
          What the Model Has Learned
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {MODEL_INPUTS.map(m => (
            <div key={m.label} style={{
              background: 'white', border: '1px solid #dde3ef', borderRadius: 8,
              padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <m.icon size={13} color={m.color} />
                <span style={{ fontSize: 10, color: '#6b7a99' }}>{m.label}</span>
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: '#1a1a2e', lineHeight: 1 }}>{m.count}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Learning events */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
          Recent Learning Events
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {LEARNING_EVENTS.map((e, i) => (
            <div
              key={i}
              style={{
                background: 'white', border: '1px solid #dde3ef', borderRadius: 8,
                padding: '10px 12px', cursor: 'pointer',
                borderLeft: i === 0 ? '3px solid #dc2626' : '1px solid #dde3ef',
              }}
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.3 }}>{e.event}</div>
                  <div style={{ fontSize: 10, color: '#9aa0b0', marginTop: 2 }}>{e.date} · {e.source}</div>
                </div>
                <div style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, flexShrink: 0, marginLeft: 8,
                  background: '#dcfce7', color: '#166534',
                }}>FIXED</div>
              </div>

              {expanded === i && (
                <div style={{ marginTop: 10, borderTop: '1px solid #f0f4fb', paddingTop: 8 }}>
                  <div style={{ fontSize: 11, color: '#4a5568', marginBottom: 6 }}>
                    <strong style={{ color: '#1a1a2e' }}>Action:</strong> {e.action}
                  </div>
                  <div style={{
                    fontSize: 10, color: '#2563eb', background: '#eff6ff',
                    border: '1px solid #bfdbfe', borderRadius: 4, padding: '4px 8px',
                  }}>
                    Impact: {e.impact}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Punchline */}
      <div style={{
        padding: '10px 14px',
        background: '#1e2433', borderRadius: 8,
        fontSize: 12, color: '#c0c8d8', lineHeight: 1.6, fontStyle: 'italic',
      }}>
        "Every defect from every vendor makes the next part better — automatically."
      </div>

    </div>
  );
};

export default AIFeedTab;
