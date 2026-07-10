import React, { useState, useEffect, useCallback } from 'react';
import { FiTag, FiTrash2, FiSave } from 'react-icons/fi';
import toast from 'react-hot-toast';
import api from '../../../services/api';

const DATUM_COLORS = { A: '#ff6b6b', B: '#4df0c0', C: '#f7c948' };

const DatumTaggerTab = ({ jobId, viewerRef, active }) => {
  const [selected, setSelected] = useState(null);  // { faceIndex, faceType, normal, centroid }
  const [datums, setDatums] = useState({});         // { A: faceIndex|null, B: ..., C: ... }
  const [saving, setSaving] = useState(false);

  // Load existing datums on mount
  useEffect(() => {
    if (!jobId) return;
    api.get(`/jobs/${jobId}/datums`).then(res => {
      const map = {};
      (res.data?.datums || []).forEach(d => { map[d.label] = d.face_index; });
      setDatums(map);
    }).catch(() => {});
  }, [jobId]);

  // Tell viewer to enter datum_tagger mode when this tab is active
  useEffect(() => {
    if (!viewerRef?.current) return;
    viewerRef.current.contentWindow?.postMessage({ type: 'setMode', mode: active ? 'datum_tagger' : 'default' }, '*');
  }, [active, viewerRef]);

  // Sync datum colors into viewer whenever datums or selection changes
  useEffect(() => {
    if (!viewerRef?.current || !active) return;
    viewerRef.current.contentWindow?.postMessage({ type: 'setDatumColors', ...datums }, '*');
  }, [datums, selected, active, viewerRef]);

  // Listen for face selection events from the viewer iframe
  const onMessage = useCallback((e) => {
    if (!active) return;
    if (e.data?.type === 'faceSelected') {
      setSelected({ faceIndex: e.data.faceIndex, faceType: e.data.faceType, normal: e.data.normal, centroid: e.data.centroid });
    }
    if (e.data?.type === 'faceDeselected') {
      setSelected(null);
    }
  }, [active]);

  useEffect(() => {
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [onMessage]);

  // Keyboard shortcuts A/B/C
  useEffect(() => {
    if (!active) return;
    const handler = (e) => {
      if (e.target.tagName === 'INPUT') return;
      const k = e.key.toUpperCase();
      if (['A', 'B', 'C'].includes(k) && selected) tagDatum(k);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [active, selected]); // eslint-disable-line

  const tagDatum = (label) => {
    if (selected === null) return;
    setDatums(prev => {
      const next = { ...prev };
      // Remove this face from any other label it already had
      Object.keys(next).forEach(l => { if (next[l] === selected.faceIndex && l !== label) delete next[l]; });
      next[label] = selected.faceIndex;
      return next;
    });
  };

  const untagDatum = (label) => {
    setDatums(prev => { const next = { ...prev }; delete next[label]; return next; });
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = { datums: Object.entries(datums).map(([label, face_index]) => ({ label, face_index })) };
      await api.post(`/jobs/${jobId}/datums`, payload);
      toast.success('Datums saved');
    } catch {
      toast.error('Failed to save datums');
    } finally {
      setSaving(false);
    }
  };

  const taggedCount = Object.keys(datums).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, height: '100%' }}>

      {/* Selected face */}
      <div style={{ padding: '14px 16px', borderBottom: '1px solid #dde3ef' }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
          Selected Face
        </div>
        {selected ? (
          <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
            <Row label="Face #" value={selected.faceIndex} />
            <Row label="Type"   value={selected.faceType} />
            {selected.normal && <Row label="Normal" value={selected.normal.map(v => v.toFixed(3)).join(', ')} small />}
            {selected.centroid && <Row label="Centroid" value={selected.centroid.map(v => v.toFixed(2)).join(', ')} small />}
          </div>
        ) : (
          <div style={{ color: '#9aa0b0', fontSize: 12, fontStyle: 'italic' }}>Click a face in the 3D view</div>
        )}

        {/* Tag buttons */}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          {['A', 'B', 'C'].map(label => (
            <button
              key={label}
              disabled={!selected}
              onClick={() => tagDatum(label)}
              style={{
                flex: 1, padding: '8px 0', borderRadius: 6,
                border: `1px solid ${DATUM_COLORS[label]}`,
                color: DATUM_COLORS[label],
                background: `${DATUM_COLORS[label]}18`,
                fontWeight: 700, fontSize: 13, cursor: selected ? 'pointer' : 'not-allowed',
                opacity: selected ? 1 : 0.35,
              }}
            >
              {label} <span style={{ fontSize: 9, opacity: 0.6 }}>[{label}]</span>
            </button>
          ))}
        </div>
      </div>

      {/* Tagged datums */}
      <div style={{ padding: '12px 16px 6px', fontSize: 10, fontWeight: 600, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
        Tagged Datums
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0 16px' }}>
        {taggedCount === 0 ? (
          <div style={{ color: '#9aa0b0', fontSize: 12, fontStyle: 'italic', paddingTop: 8 }}>
            No datums tagged yet.<br />Select a face, then press A, B, or C.
          </div>
        ) : (
          ['A', 'B', 'C'].filter(l => l in datums).map(label => {
            const fi = datums[label];
            return (
              <div key={label} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px', borderRadius: 8,
                border: '1px solid #dde3ef', background: '#f8faff',
                marginBottom: 8, cursor: 'pointer',
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                  border: `1px solid ${DATUM_COLORS[label]}`,
                  background: `${DATUM_COLORS[label]}20`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontWeight: 700, fontSize: 13, color: DATUM_COLORS[label],
                }}>
                  {label}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>Face #{fi}</div>
                </div>
                <button onClick={() => untagDatum(label)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#b0b8cc', padding: 4 }}>
                  <FiTrash2 size={14} />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Save */}
      <div style={{ padding: 16, borderTop: '1px solid #dde3ef' }}>
        <button
          onClick={save}
          disabled={saving || taggedCount === 0}
          style={{
            width: '100%', padding: '10px 0', borderRadius: 6,
            background: taggedCount > 0 ? '#1e3a5f' : '#eef1f7',
            color: taggedCount > 0 ? '#fff' : '#9aa0b0',
            border: 'none', fontWeight: 600, fontSize: 13, cursor: taggedCount > 0 ? 'pointer' : 'not-allowed',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          }}
        >
          <FiSave size={14} /> {saving ? 'Saving…' : 'Save Datums'}
        </button>
        <div style={{ marginTop: 8, fontSize: 11, color: '#8892a4', textAlign: 'center' }}>
          Saving also runs the datum transform automatically
        </div>
      </div>
    </div>
  );
};

const Row = ({ label, value, small }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: small ? 10 : 12 }}>
    <span style={{ color: '#8892a4' }}>{label}</span>
    <span style={{ color: '#1a1a2e', fontWeight: 500 }}>{value}</span>
  </div>
);

export default DatumTaggerTab;
