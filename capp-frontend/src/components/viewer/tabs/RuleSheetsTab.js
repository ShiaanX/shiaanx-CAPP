import React, { useState } from 'react';
import { FiBookOpen, FiZap, FiChevronDown, FiChevronUp, FiCheckCircle } from 'react-icons/fi';

// ─── Inline rule sheet data (mirrors rule_sheets/ on disk) ────────────────────
// Only the sections relevant to the demo are inlined here; a production version
// would fetch these from the CAPP service.

const SHEETS = [
  {
    id: '02',
    name: 'Process Selection',
    file: '02_process_selection.json',
    description: 'Diameter bands, DDR → drill cycle, stock-to-leave, feed rate overrides',
    sections: [
      {
        key: 'drill_diameter_bands_mm',
        label: 'Drill Diameter Bands',
        rows: [
          { label: 'Micro drill (d < 1mm)', value: 'micro_drill only — no spot drill' },
          { label: '1–13mm', value: 'spot_drill → twist_drill' },
          { label: '13–32mm', value: 'spot_drill → pilot_drill (60%) → core_drill' },
          { label: '> 32mm', value: 'circular_interp or boring_bar' },
        ],
      },
      {
        key: 'ddr_drill_cycle',
        label: 'DDR → Drill Cycle',
        rows: [
          { label: 'DDR ≤ 3', value: 'Standard cycle' },
          { label: 'DDR 3–5', value: 'Peck drilling' },
          { label: 'DDR > 5', value: 'Deep peck' },
        ],
      },
      {
        key: 'feed_rate_overrides',
        label: 'Feed Rate Overrides',
        highlight: true,
        rows: [
          {
            id: 'FR-001',
            label: 'circular_interp · Ø ≤ 4mm · tool ≤ 2mm',
            value: 'Cap Vf at 400 mm/min (was 1000)',
            badge: 'Auto-added · Jun 2026',
            badgeColor: '#2563eb',
            badgeBg: '#eff6ff',
            reason: 'Tool deflection on Motor Mount SX_2627_007 — Ø3.2mm holes came out 3.02mm (−0.18mm). Reducing feed eliminates bending.',
            source: 'Aviocian Technologies · closed_loop',
          },
        ],
      },
    ],
  },
  {
    id: '04',
    name: 'Cutting Parameters',
    file: '04_cutting_parameters.json',
    description: 'Machine RPM limits, coolant, peck fractions, ap/ae rules',
    sections: [
      {
        key: 'machine',
        label: 'Machine Limits',
        rows: [
          { label: 'Max RPM (VMC)', value: '10,000 rpm' },
          { label: 'Coolant default', value: 'through_spindle' },
          { label: 'TSC Vc boost (d < 6mm)', value: '+10%' },
        ],
      },
      {
        key: 'peck',
        label: 'Peck Q Fractions',
        rows: [
          { label: 'Standard peck Q', value: '30% of diameter' },
          { label: 'Deep peck Q', value: '15% of diameter' },
        ],
      },
    ],
  },
  {
    id: '05',
    name: 'Setup Planning',
    file: '05_setup_planning.json',
    description: 'Axis clustering, WCS assignment, datum stability',
    sections: [
      {
        key: 'wcs',
        label: 'WCS Assignment',
        rows: [
          { label: 'Sequence', value: 'G54 → G55 → G56 → G57 → G58 → G59' },
          { label: 'Corner zero threshold', value: 'xmin within 2% of part dim' },
        ],
      },
      {
        key: 'sort',
        label: 'Setup Sort Order',
        rows: [
          { label: 'Priority 1', value: 'Principal-axis setups first' },
          { label: 'Priority 2', value: 'Descending feature count' },
          { label: 'Angled setups', value: 'Always last' },
        ],
      },
    ],
  },
];

// ─── Sub-components ────────────────────────────────────────────────────────────

const SectionBlock = ({ section }) => {
  const [open, setOpen] = useState(section.highlight || false);

  return (
    <div style={{
      border: section.highlight ? '1px solid #bfdbfe' : '1px solid #e8eef7',
      borderRadius: 7,
      overflow: 'hidden',
      marginBottom: 6,
    }}>
      {/* Section header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', padding: '8px 10px',
          background: section.highlight ? '#eff6ff' : '#f8fafd',
          border: 'none', cursor: 'pointer', textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {section.highlight && <FiZap size={11} color="#2563eb" />}
          <span style={{ fontSize: 11, fontWeight: 700, color: section.highlight ? '#1d4ed8' : '#1a1a2e' }}>
            {section.label}
          </span>
          {section.highlight && (
            <span style={{
              fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
              background: '#dbeafe', color: '#1d4ed8',
            }}>NEW</span>
          )}
        </div>
        {open ? <FiChevronUp size={12} color="#9aa0b0" /> : <FiChevronDown size={12} color="#9aa0b0" />}
      </button>

      {/* Rows */}
      {open && (
        <div style={{ padding: '6px 10px 8px', background: 'white' }}>
          {section.rows.map((row, i) => (
            <div key={i} style={{
              padding: '6px 0',
              borderBottom: i < section.rows.length - 1 ? '1px solid #f0f4fb' : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ fontSize: 11, color: '#6b7a99', flex: 1 }}>{row.label}</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#1a1a2e', fontFamily: 'monospace', textAlign: 'right' }}>{row.value}</span>
              </div>
              {row.badge && (
                <div style={{
                  marginTop: 4, display: 'inline-flex', alignItems: 'center', gap: 4,
                  fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
                  background: row.badgeBg, color: row.badgeColor,
                }}>
                  <FiCheckCircle size={9} /> {row.badge}
                </div>
              )}
              {row.reason && (
                <div style={{
                  marginTop: 5, padding: '6px 8px',
                  background: '#f0f6ff', border: '1px solid #dbeafe', borderRadius: 5,
                  fontSize: 10, color: '#1e40af', lineHeight: 1.5,
                }}>
                  <strong>Why:</strong> {row.reason}
                  <div style={{ marginTop: 3, color: '#6b7a99' }}>Source: {row.source}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── Main component ────────────────────────────────────────────────────────────

const RuleSheetsTab = () => {
  const [activeSheet, setActiveSheet] = useState('02');

  const sheet = SHEETS.find(s => s.id === activeSheet);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingTop: 4 }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 10px', background: '#f0fdf4',
        border: '1px solid #86efac', borderRadius: 6, fontSize: 11, color: '#166534',
      }}>
        <FiBookOpen size={12} />
        <span><strong>Rule Sheets</strong> — versioned decision logic powering the pipeline</span>
      </div>

      {/* Sheet selector */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {SHEETS.map(s => (
          <button
            key={s.id}
            onClick={() => setActiveSheet(s.id)}
            style={{
              fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6,
              cursor: 'pointer', border: 'none',
              background: activeSheet === s.id ? '#1e3a5f' : '#f0f4fb',
              color: activeSheet === s.id ? 'white' : '#4a5568',
            }}
          >
            {s.id} · {s.name}
            {s.id === '02' && (
              <span style={{
                marginLeft: 5, fontSize: 8, fontWeight: 800, padding: '1px 4px',
                borderRadius: 3, background: '#2563eb', color: 'white',
              }}>1 NEW</span>
            )}
          </button>
        ))}
      </div>

      {/* Sheet content */}
      {sheet && (
        <div>
          {/* Sheet meta */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#1a1a2e' }}>{sheet.name}</div>
            <div style={{ fontSize: 10, color: '#9aa0b0', marginTop: 1 }}>{sheet.file} · {sheet.description}</div>
          </div>

          {/* Sections */}
          {sheet.sections.map(sec => (
            <SectionBlock key={sec.key} section={sec} />
          ))}
        </div>
      )}

    </div>
  );
};

export default RuleSheetsTab;
