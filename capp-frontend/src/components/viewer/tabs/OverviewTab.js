import React from 'react';
import { FiCheckCircle, FiAlertTriangle } from 'react-icons/fi';

const Row = ({ label, value }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f2f7' }}>
    <span style={{ fontSize: 13, color: '#6b7a99' }}>{label}</span>
    <span style={{ fontSize: 13, fontWeight: 600, color: '#1a1a2e' }}>{value ?? '—'}</span>
  </div>
);

const OverviewTab = ({ classified, setups, features }) => {
  if (!classified) {
    return <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>Waiting for analysis…</div>;
  }

  const bb = classified.bounding_box || features?.bounding_box || {};
  const dims = bb
    ? `${(bb.xmax - bb.xmin || 0).toFixed(1)} × ${(bb.ymax - bb.ymin || 0).toFixed(1)} × ${(bb.zmax - bb.zmin || 0).toFixed(1)} mm`
    : '—';

  const stockDims = bb
    ? `${((bb.xmax - bb.xmin || 0) + 3).toFixed(1)} × ${((bb.ymax - bb.ymin || 0) + 3).toFixed(1)} × ${((bb.zmax - bb.zmin || 0) + 3).toFixed(1)} mm`
    : '—';

  const vol = classified.mass_properties?.volume;
  const volCm3 = vol ? (vol / 1000).toFixed(1) : '—';

  const clusters = classified.clusters || [];
  const featureCount = clusters.length;
  const setupCount = setups?.setups?.length ?? '—';

  const unrecognized = clusters.filter(c => c.feature_type === 'unrecognized' || c.feature_type === 'unknown');
  const allMachinable = unrecognized.length === 0;

  const warnings = classified.warnings || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Overview */}
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#9aabb8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
          Overview
        </div>
        <Row label="Part dimensions"   value={dims} />
        <Row label="Stock size"        value={stockDims} />
        <Row label="Part volume"       value={volCm3 !== '—' ? `${volCm3} cm³` : '—'} />
        <Row label="Features detected" value={featureCount} />
        <Row label="Setups required"   value={setupCount} />
        <Row label="Machine type"      value="3 Axis VMC" />
      </div>

      {/* Machinability */}
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#9aabb8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
          Machinability
        </div>
        {allMachinable ? (
          <div className="badge badge-green">
            <FiCheckCircle size={13} /> All Features Machinable
          </div>
        ) : (
          <div className="badge badge-orange">
            <FiAlertTriangle size={13} /> {unrecognized.length} Unrecognised Feature{unrecognized.length > 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#9aabb8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
            Warnings
          </div>
          {warnings.map((w, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12, color: '#7a5200', background: '#fff8e1', borderRadius: 6, padding: '8px 10px', marginBottom: 6 }}>
              <FiAlertTriangle size={13} style={{ marginTop: 1, flexShrink: 0 }} />
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default OverviewTab;
