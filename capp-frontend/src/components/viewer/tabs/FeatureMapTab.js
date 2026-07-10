import React, { useState, useEffect, useCallback, useRef } from 'react';
import api from '../../../services/api';

// Colour palettes per feature type family
const TYPE_PALETTES = {
  bore:     ['#60a5fa','#3b82f6','#2563eb','#1d4ed8','#93c5fd'],
  pocket:   ['#34d399','#10b981','#059669','#6ee7b7'],
  face:     ['#fbbf24','#f59e0b','#d97706','#fde68a'],
  boss:     ['#f472b6','#ec4899','#db2777'],
  slot:     ['#c084fc','#a855f7','#9333ea'],
  chamfer:  ['#fb923c','#f97316','#ea580c'],
  other:    ['#94a3b8','#64748b'],
  background: ['#334155'],
};

function featureFamily(ftype) {
  const t = (ftype || '').toLowerCase();
  if (t.includes('hole') || t.includes('bore') || t === 'counterbore' || t === 'countersink' || t === 'tapped') return 'bore';
  if (t.includes('pocket')) return 'pocket';
  if (t === 'planar_face' || t === 'face') return 'face';
  if (t === 'boss') return 'boss';
  if (t === 'slot') return 'slot';
  if (t === 'chamfer') return 'chamfer';
  if (t === 'background') return 'background';
  return 'other';
}

function assignColors(faces) {
  // Group feature IDs by family, assign distinct shades within each family
  const families = {};
  faces.forEach(f => {
    const fam = featureFamily(f.feature_type);
    if (!families[fam]) families[fam] = [];
    if (!families[fam].includes(f.feature_id)) families[fam].push(f.feature_id);
  });
  const map = {};
  Object.entries(families).forEach(([fam, fids]) => {
    const pal = TYPE_PALETTES[fam] || TYPE_PALETTES.other;
    fids.forEach((fid, i) => { map[fid] = pal[i % pal.length]; });
  });
  return map;
}

const FeatureMapTab = ({ jobId, viewerRef, active }) => {
  const [features, setFeatures] = useState([]);       // [{ feature_id, feature_type, inspection_section, face_indices, centroid }]
  const [colorMap, setColorMap] = useState({});        // feature_id -> css color
  const [faceColorMap, setFaceColorMap] = useState({}); // face_index -> css color
  const [highlighted, setHighlighted] = useState(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef({});

  useEffect(() => {
    if (!jobId || !active) return;
    setLoading(true);
    api.get(`/jobs/${jobId}/faces`).then(res => {
      const faces = res.data.faces || [];
      const colors = assignColors(faces);

      // Group faces by feature_id
      const grouped = {};
      faces.forEach(f => {
        if (!grouped[f.feature_id]) grouped[f.feature_id] = { feature_id: f.feature_id, feature_type: f.feature_type, inspection_section: f.inspection_section, face_indices: [], centroid: f.centroid };
        grouped[f.feature_id].face_indices.push(f.face_index);
      });

      const faceColors = {};
      faces.forEach(f => { faceColors[f.face_index] = colors[f.feature_id]; });

      setColorMap(colors);
      setFaceColorMap(faceColors);
      setFeatures(Object.values(grouped));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [jobId, active]);

  // Push colors to viewer when active
  useEffect(() => {
    if (!viewerRef?.current || !active || Object.keys(faceColorMap).length === 0) return;
    viewerRef.current.contentWindow?.postMessage({ type: 'setMode', mode: 'default' }, '*');
    viewerRef.current.contentWindow?.postMessage({ type: 'setFeatureColors', colors: faceColorMap }, '*');
  }, [active, faceColorMap, viewerRef]);

  // Reset viewer when leaving tab
  useEffect(() => {
    if (!active && viewerRef?.current) {
      viewerRef.current.contentWindow?.postMessage({ type: 'setFeatureColors', colors: {} }, '*');
    }
  }, [active, viewerRef]);

  const isolate = useCallback((fid) => {
    const next = fid === highlighted ? null : fid;
    setHighlighted(next);
    if (!viewerRef?.current) return;

    if (!next) {
      viewerRef.current.contentWindow?.postMessage({ type: 'setFeatureColors', colors: faceColorMap }, '*');
    } else {
      const feat = features.find(f => f.feature_id === fid);
      const dimmed = feat ? feat.face_indices : [];
      viewerRef.current.contentWindow?.postMessage({ type: 'setFeatureColors', colors: faceColorMap, dimmedFaces: dimmed }, '*');
    }
  }, [highlighted, faceColorMap, features, viewerRef]);

  const filtered = features.filter(f =>
    !search || f.feature_id.toLowerCase().includes(search.toLowerCase()) || f.feature_type.toLowerCase().includes(search.toLowerCase())
  );

  // Group by feature family for display
  const sections = [...new Set(filtered.map(f => featureFamily(f.feature_type)))];
  const sectionOrder = ['bore', 'pocket', 'face', 'boss', 'slot', 'chamfer', 'other', 'background'];
  sections.sort((a, b) => sectionOrder.indexOf(a) - sectionOrder.indexOf(b));

  if (loading) return <div style={{ padding: 24, color: '#8892a4', fontSize: 13 }}>Loading feature data…</div>;
  if (features.length === 0) return (
    <div style={{ padding: 24, color: '#8892a4', fontSize: 13 }}>
      No feature data yet.<br /><br />
      Save datums first to generate the feature map.
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Search */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid #dde3ef' }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search feature ID or type…"
          style={{ width: '100%', padding: '7px 10px', border: '1px solid #dde3ef', borderRadius: 6, fontSize: 12, outline: 'none', color: '#1a1a2e' }}
        />
      </div>

      {highlighted && (
        <div style={{ padding: '8px 16px', background: '#f0f4ff', borderBottom: '1px solid #dde3ef', fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: '#1e3a5f', fontWeight: 600 }}>Isolated: {highlighted}</span>
          <button onClick={() => isolate(highlighted)} style={{ background: 'none', border: 'none', color: '#6b7a99', cursor: 'pointer', fontSize: 11 }}>Show all</button>
        </div>
      )}

      {/* Feature list */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sectionOrder.filter(s => sections.includes(s)).map(sec => (
          <div key={sec}>
            <div style={{ padding: '6px 16px', background: '#f4f6fb', borderBottom: '1px solid #dde3ef', fontSize: 10, fontWeight: 700, color: '#6b7a99', letterSpacing: '0.1em', textTransform: 'uppercase', position: 'sticky', top: 0, zIndex: 2 }}>
              {sec} ({filtered.filter(f => featureFamily(f.feature_type) === sec).length})
            </div>
            {filtered.filter(f => featureFamily(f.feature_type) === sec).map(feat => {
              const color = colorMap[feat.feature_id] || '#5b8fff';
              const isHighlighted = feat.feature_id === highlighted;
              return (
                <div
                  key={feat.feature_id}
                  ref={el => { listRef.current[feat.feature_id] = el; }}
                  onClick={() => isolate(feat.feature_id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 16px', cursor: 'pointer',
                    borderBottom: '1px solid #f0f2f8',
                    background: isHighlighted ? '#f0f4ff' : 'white',
                    borderLeft: isHighlighted ? `3px solid ${color}` : '3px solid transparent',
                  }}
                >
                  <div style={{ width: 12, height: 12, borderRadius: 3, background: color, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600, color: '#1a1a2e' }}>{feat.feature_id}</div>
                    <div style={{ fontSize: 10, color: '#8892a4', marginTop: 1 }}>{feat.feature_type.replace(/_/g, ' ')}</div>
                  </div>
                  <div style={{ fontSize: 10, color: '#b0b8cc', fontFamily: 'monospace', flexShrink: 0 }}>{feat.face_indices.length}f</div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div style={{ padding: '10px 16px', borderTop: '1px solid #dde3ef', fontSize: 11, color: '#8892a4', textAlign: 'center' }}>
        {features.length} features · click to isolate
      </div>
    </div>
  );
};

export default FeatureMapTab;
