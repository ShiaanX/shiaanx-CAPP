import React, { useState, useEffect } from 'react';
import { FiAlertTriangle, FiBox, FiEye } from 'react-icons/fi';
import { getFixtureSpec, getFixtureAssemblyUrl } from '../../../services/cappService';

const HEADER = { fontSize: 12, fontWeight: 700, color: '#9aabb8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 };
const ROW_STYLE = { display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid #f0f2f7' };
const LABEL_STYLE = { fontSize: 13, color: '#6b7a99' };
const VALUE_STYLE = { fontSize: 13, fontWeight: 600, color: '#1a1a2e', textAlign: 'right', maxWidth: 180 };

const SpecRow = ({ label, value }) => (
  <div style={ROW_STYLE}>
    <span style={LABEL_STYLE}>{label}</span>
    <span style={VALUE_STYLE}>{value ?? '—'}</span>
  </div>
);

const fmt = (val, unit = '') => val != null ? `${val}${unit}` : '—';

const fixtureLabel = (t) => ({
  vise: 'Vise',
  step_jaw_vise: 'Step Jaw Vise',
  angle_plate: 'Angle Plate',
  sine_plate: 'Sine Plate',
  fixture_plate: 'Fixture Plate',
  custom_soft_jaw: 'Custom Soft Jaw',
}[t] || (t || '—'));

const jawLabel = (t) => ({
  standard_hard: 'Standard Hard Jaws',
  soft_aluminum: 'Soft Aluminium Jaws',
  step_jaw: 'Step Jaws',
  custom_profile: 'Custom Profile Soft Jaws',
}[t] || (t || '—'));

const zZeroLabel = (t) => ({
  top_of_stock: 'Top of Stock',
  top_of_part: 'Top of Part',
  bottom_of_part: 'Bottom of Part',
}[t] || (t || '—'));

const xyZeroLabel = (t) => ({
  center_of_part: 'Centre of Part',
  corner_of_part: 'Corner of Part',
}[t] || (t || '—'));

const FixtureTab = ({ jobId, active, onLoadAssembly }) => {
  const [fixtureData, setFixtureData] = useState(null);
  const [selectedSetup, setSelectedSetup] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [assemblyLoading, setAssemblyLoading] = useState(false);

  useEffect(() => {
    if (!active || fixtureData) return;
    setLoading(true);
    getFixtureSpec(jobId)
      .then(res => {
        const data = res.data;
        if (data.error || !data.setups || data.setups.length === 0) {
          setError(data.error || 'No fixture data available');
        } else {
          setFixtureData(data);
        }
      })
      .catch(() => setError('Could not load fixture data'))
      .finally(() => setLoading(false));
  }, [active, jobId]); // eslint-disable-line

  const handleLoadAssembly = (setupIdx) => {
    const url = getFixtureAssemblyUrl(jobId, setupIdx + 1);
    setAssemblyLoading(true);
    onLoadAssembly(url);
    setTimeout(() => setAssemblyLoading(false), 3000);
  };

  const handleSetupSelect = (idx) => {
    setSelectedSetup(idx);
  };

  if (loading) {
    return <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>Loading fixture data…</div>;
  }

  if (error) {
    return (
      <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', background: '#f8fafc', borderRadius: 8, padding: '12px 14px' }}>
          <FiAlertTriangle size={15} style={{ marginTop: 1, flexShrink: 0, color: '#c0392b' }} />
          <span>Fixture data not available — re-run pipeline to generate.</span>
        </div>
      </div>
    );
  }

  if (!fixtureData) return null;

  const setups = fixtureData.setups || [];
  const setup = setups[selectedSetup] || {};
  const fs = setup.fixture_spec || {};
  const notes = fs.setup_notes || [];
  const clampedFaces = (fs.clamped_faces || []).join(', ');
  const hasSoftJaws = !!fs.soft_jaw_required;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Setup selector */}
      <div>
        <div style={HEADER}>Fixture Setup</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {setups.map((s, i) => (
            <button
              key={i}
              onClick={() => handleSetupSelect(i)}
              style={{
                padding: '5px 12px',
                borderRadius: 20,
                border: '1px solid',
                borderColor: selectedSetup === i ? '#4299e1' : '#dde3ef',
                background: selectedSetup === i ? '#e8f0fe' : 'white',
                color: selectedSetup === i ? '#1a6aaf' : '#6b7a99',
                fontSize: 12,
                fontWeight: selectedSetup === i ? 700 : 400,
                cursor: 'pointer',
              }}
            >
              Setup {s.setup_id || i + 1}
            </button>
          ))}
        </div>
        {setup.axis_label && (
          <div style={{ fontSize: 11, color: '#9aabb8', marginTop: 6 }}>{setup.axis_label}</div>
        )}
      </div>

      {/* Fixture spec table */}
      <div>
        <div style={HEADER}>Fixture Specification</div>
        <SpecRow label="Fixture Type"   value={fixtureLabel(fs.fixture_type)} />
        <SpecRow label="Jaw Type"       value={jawLabel(fs.jaw_type)} />
        <SpecRow label="Jaw Opening"    value={fmt(fs.jaw_opening_mm, ' mm')} />
        <SpecRow label="Jaw Height"     value={fmt(fs.jaw_height_mm, ' mm')} />
        <SpecRow label="Parallels"      value={fs.parallels_mm ? `${fs.parallels_mm} mm` : 'None'} />
        <SpecRow label="Clamped Faces"  value={clampedFaces || '—'} />
        <SpecRow label="Rest Face"      value={fs.rest_face || '—'} />
        <SpecRow label="Datum Face"     value={fs.datum_face || '—'} />
        <SpecRow label="Z Zero"         value={zZeroLabel(fs.z_zero_face)} />
        <SpecRow label="WCS XY Zero"    value={xyZeroLabel(fs.wcs_xy_zero)} />
        <SpecRow label="Clamp Clearance" value={fmt(fs.clamp_clearance_mm, ' mm')} />
      </div>

      {/* Soft jaw warning */}
      {hasSoftJaws && (
        <div style={{ background: '#fff3cd', borderRadius: 8, padding: '10px 14px', border: '1px solid #ffc107' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <FiAlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0, color: '#664d03' }} />
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#664d03' }}>Soft Jaws Required</div>
              <div style={{ fontSize: 12, color: '#856404', marginTop: 3 }}>
                {fs.soft_jaw_profile_file || 'Jaw files generated for this setup'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Setup notes */}
      {notes.length > 0 && (
        <div>
          <div style={HEADER}>Setup Notes</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {notes.map((note, i) => (
              <div key={i} style={{ fontSize: 12, color: '#374151', padding: '5px 0', borderBottom: '1px solid #f0f2f7', display: 'flex', gap: 8 }}>
                <span style={{ color: '#9aabb8', flexShrink: 0 }}>•</span>
                <span>{note}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Load in 3D viewer */}
      <div>
        <button
          onClick={() => handleLoadAssembly(selectedSetup)}
          disabled={assemblyLoading}
          style={{
            width: '100%',
            padding: '10px 0',
            borderRadius: 8,
            border: 'none',
            background: assemblyLoading ? '#dde3ef' : '#1a3a5c',
            color: assemblyLoading ? '#9aabb8' : 'white',
            fontSize: 13,
            fontWeight: 600,
            cursor: assemblyLoading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          <FiEye size={14} />
          {assemblyLoading ? 'Loading Assembly…' : 'Load in 3D Viewer'}
        </button>

        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8, fontSize: 11, color: '#9aabb8' }}>
          <span><span style={{ color: '#4a90d9' }}>●</span> Part</span>
          <span><span style={{ color: '#e67e22' }}>●</span> Left Jaw</span>
          <span><span style={{ color: '#e67e22' }}>●</span> Right Jaw</span>
        </div>
      </div>

      {/* WCS info */}
      <div>
        <div style={HEADER}>WCS</div>
        <SpecRow label="Code"   value={setup.wcs || '—'} />
        <SpecRow label="Setup"  value={setup.setup_id != null ? `Setup ${setup.setup_id}` : '—'} />
        {setup.spindle_direction && (
          <SpecRow label="Spindle" value={`[${(setup.spindle_direction || []).map(v => v.toFixed(2)).join(', ')}]`} />
        )}
      </div>

    </div>
  );
};

export default FixtureTab;
