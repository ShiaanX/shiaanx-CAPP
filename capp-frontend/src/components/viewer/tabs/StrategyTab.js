import React, { useState } from 'react';
import { FiChevronDown, FiChevronRight, FiTool, FiClock } from 'react-icons/fi';

const fmtTime = (seconds) => {
  if (!seconds) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
};

const CuttingConditions = ({ op }) => {
  const rows = [
    ['Surface Speed',  op.Vc_mmin     ? `${op.Vc_mmin} m/min`              : '—'],
    ['Spindle Speed',  op.rpm         ? `${Math.round(op.rpm)} RPM`         : '—'],
    ['Feed Rate',      op.vf_mmpm     ? `${Math.round(op.vf_mmpm)} mm/min`  : '—'],
    ['Feed per Tooth', op.fz_mm       ? `${op.fz_mm.toFixed(3)} mm`         : '—'],
    ['Axial Depth',    op.ap_mm       ? `${op.ap_mm.toFixed(2)} mm`         : '—'],
    ['Radial Depth',   op.ae_mm       ? `${op.ae_mm.toFixed(2)} mm`         : '—'],
    ['Coolant',        op.coolant     || '—'],
    ['Est. Time',      fmtTime(op.estimated_time_s)],
  ];
  return (
    <div style={{ marginTop: 10, background: '#f8fafc', borderRadius: 8, padding: '10px 12px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#9aabb8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        Cutting Conditions
      </div>
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #edf0f7' }}>
          <span style={{ fontSize: 12, color: '#6b7a99' }}>{label}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#1a1a2e' }}>{value}</span>
        </div>
      ))}
    </div>
  );
};

const OperationRow = ({ op, index, total, faceIndices, onSelectFaces }) => {
  const [open, setOpen] = useState(false);
  const passLabel = op.pass_type ? ` [${op.pass_type}]` : '';

  const handleClick = () => {
    const next = !open;
    setOpen(next);
    if (next && onSelectFaces) onSelectFaces(faceIndices || []);
  };

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        onClick={handleClick}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 12px',
          borderRadius: 8,
          cursor: 'pointer',
          background: open ? '#e8f0fe' : 'white',
          border: '1px solid #dde3ef',
        }}
      >
        {open ? <FiChevronDown size={14} color="#1a56db" /> : <FiChevronRight size={14} color="#9aabb8" />}
        <span style={{ fontSize: 12, color: '#9aabb8', minWidth: 32 }}>{index + 1}/{total}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1a1a2e', flex: 1 }}>
          {(op.operation || '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}{passLabel}
        </span>
        {op.tool_diameter_mm && (
          <span style={{ fontSize: 11, color: '#6b7a99', display: 'flex', alignItems: 'center', gap: 4 }}>
            <FiTool size={11} /> ⌀{op.tool_diameter_mm}mm
          </span>
        )}
        {op.estimated_time_s > 0 && (
          <span style={{ fontSize: 11, color: '#6b7a99', display: 'flex', alignItems: 'center', gap: 4 }}>
            <FiClock size={11} /> {fmtTime(op.estimated_time_s)}
          </span>
        )}
      </div>

      {open && (
        <div style={{ padding: '0 12px 8px 12px', border: '1px solid #dde3ef', borderTop: 'none', borderRadius: '0 0 8px 8px', background: 'white' }}>
          {op.tool_description && (
            <div style={{ paddingTop: 10, fontSize: 12, color: '#4a5568' }}>
              <span style={{ fontWeight: 600 }}>Tool: </span>{op.tool_description}
            </div>
          )}
          {op.reason && (
            <div style={{ fontSize: 12, color: '#6b7a99', marginTop: 4, fontStyle: 'italic' }}>{op.reason}</div>
          )}
          <CuttingConditions op={op} />
        </div>
      )}
    </div>
  );
};

const FeatureGroup = ({ cluster, onSelectFaces }) => {
  const ops = cluster.process_sequence || [];
  const totalTime = ops.reduce((s, op) => s + (op.estimated_time_s || 0), 0);
  const label = (cluster.feature_type || 'Feature').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#6b7a99', textTransform: 'uppercase', letterSpacing: 0.8, padding: '6px 4px 4px', display: 'flex', justifyContent: 'space-between' }}>
        <span>{label}</span>
        {totalTime > 0 && <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><FiClock size={10} />{fmtTime(totalTime)}</span>}
      </div>
      {ops.map((op, i) => (
        <OperationRow key={i} op={op} index={i} total={ops.length} faceIndices={cluster.face_indices} onSelectFaces={onSelectFaces} />
      ))}
    </div>
  );
};

const SetupSection = ({ setupId, clusters, onSelectFaces }) => {
  const [open, setOpen] = useState(true);
  const allOps = clusters.flatMap(c => c.process_sequence || []);
  const totalTime = allOps.reduce((s, op) => s + (op.estimated_time_s || 0), 0);

  return (
    <div style={{ marginBottom: 12 }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '10px 14px', background: '#1e2433',
          borderRadius: 8, cursor: 'pointer', color: 'white',
        }}
      >
        {open ? <FiChevronDown size={14} /> : <FiChevronRight size={14} />}
        <span style={{ fontWeight: 700, flex: 1 }}>Setup {setupId}</span>
        <span style={{ fontSize: 12, color: '#8892a4' }}>{allOps.length} operations</span>
        {totalTime > 0 && <span style={{ fontSize: 12, color: '#8892a4' }}>{fmtTime(totalTime)}</span>}
      </div>

      {open && (
        <div style={{ marginTop: 4, paddingLeft: 4 }}>
          {clusters.map((c, i) => (
            <FeatureGroup key={i} cluster={c} onSelectFaces={onSelectFaces} />
          ))}
        </div>
      )}
    </div>
  );
};

const StrategyTab = ({ params, onSelectFaces }) => {
  if (!params) {
    return <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>Waiting for analysis…</div>;
  }

  const clusters = params.clusters || [];

  // Group clusters by setup_id
  const bySetup = {};
  clusters.forEach(c => {
    const sid = c.setup_id ?? 1;
    if (!bySetup[sid]) bySetup[sid] = [];
    bySetup[sid].push(c);
  });

  const setupIds = Object.keys(bySetup).sort();

  if (!setupIds.length) {
    return <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>No operations found.</div>;
  }

  return (
    <div>
      {setupIds.map(sid => (
        <SetupSection key={sid} setupId={sid} clusters={bySetup[sid]} onSelectFaces={onSelectFaces} />
      ))}
    </div>
  );
};

export default StrategyTab;
