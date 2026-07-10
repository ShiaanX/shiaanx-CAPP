import React, { useState, useEffect } from 'react';
import { FiDownload, FiPlus, FiTrash2, FiSave } from 'react-icons/fi';
import toast from 'react-hot-toast';
import api from '../../../services/api';

const DEFAULT_TOL = 0.1;

const InspectionTab = ({ jobId }) => {
  const [tolerances, setTolerances] = useState({});
  const [newFeatureId, setNewFeatureId] = useState('');
  const [newNominal, setNewNominal] = useState('');
  const [newUpper, setNewUpper] = useState(String(DEFAULT_TOL));
  const [newLower, setNewLower] = useState(String(DEFAULT_TOL));
  const [newMeasType, setNewMeasType] = useState('dimension');
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [hasDatums, setHasDatums] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    api.get(`/jobs/${jobId}/tolerances`).then(res => setTolerances(res.data || {})).catch(() => {});
    api.get(`/jobs/${jobId}/datums`).then(res => setHasDatums((res.data?.datums || []).length > 0)).catch(() => {});
  }, [jobId]);

  const addRow = () => {
    if (!newFeatureId.trim()) { toast.error('Feature ID is required'); return; }
    const nom = parseFloat(newNominal);
    if (isNaN(nom)) { toast.error('Nominal value must be a number'); return; }
    setTolerances(prev => ({
      ...prev,
      [newFeatureId.trim()]: {
        nominal_mm: nom,
        upper_tol_mm: parseFloat(newUpper) || DEFAULT_TOL,
        lower_tol_mm: parseFloat(newLower) || DEFAULT_TOL,
        measurement_type: newMeasType,
      },
    }));
    setNewFeatureId(''); setNewNominal(''); setNewUpper(String(DEFAULT_TOL)); setNewLower(String(DEFAULT_TOL)); setNewMeasType('dimension');
  };

  const removeRow = (key) => setTolerances(prev => { const n = { ...prev }; delete n[key]; return n; });

  const saveTols = async () => {
    setSaving(true);
    try {
      await api.post(`/jobs/${jobId}/tolerances`, tolerances);
      toast.success('Tolerances saved');
    } catch { toast.error('Failed to save'); }
    finally { setSaving(false); }
  };

  const downloadTemplate = async () => {
    if (!hasDatums) { toast.error('Save datums first before generating the inspection template'); return; }
    setDownloading(true);
    try {
      const resp = await fetch(`${api.defaults.baseURL}/jobs/${jobId}/inspection`);
      if (!resp.ok) { const t = await resp.text(); throw new Error(t); }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'inspection_template.xlsx'; a.click();
      URL.revokeObjectURL(url);
      toast.success('Inspection template downloaded');
    } catch (e) { toast.error('Error: ' + e.message); }
    finally { setDownloading(false); }
  };

  const keys = Object.keys(tolerances);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 0 }}>

      {/* Status */}
      {!hasDatums && (
        <div style={{ margin: '12px 16px 0', padding: '10px 12px', background: '#fff8e1', border: '1px solid #ffd54f', borderRadius: 6, fontSize: 12, color: '#7a5c00' }}>
          ⚠ Tag and save Datum A/B/C in the Datum Tagger tab first.
        </div>
      )}

      {/* Tolerances table */}
      <div style={{ padding: '14px 16px 6px', fontSize: 10, fontWeight: 600, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
        Feature Tolerances
      </div>

      {keys.length > 0 && (
        <div style={{ overflowX: 'auto', margin: '0 16px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ background: '#f4f6fb' }}>
                {['Feature ID', 'Nominal', '+Tol', '−Tol', 'Type', ''].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: '#6b7a99', fontWeight: 600, borderBottom: '1px solid #dde3ef', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.map(key => {
                const t = tolerances[key];
                return (
                  <tr key={key} style={{ borderBottom: '1px solid #f0f2f8' }}>
                    <td style={{ padding: '7px 8px', fontFamily: 'monospace', fontWeight: 600 }}>{key}</td>
                    <td style={{ padding: '7px 8px', fontFamily: 'monospace' }}>{t.nominal_mm}</td>
                    <td style={{ padding: '7px 8px', fontFamily: 'monospace', color: '#2d6a4f' }}>+{t.upper_tol_mm}</td>
                    <td style={{ padding: '7px 8px', fontFamily: 'monospace', color: '#c0392b' }}>−{t.lower_tol_mm}</td>
                    <td style={{ padding: '7px 8px', color: '#6b7a99' }}>{t.measurement_type}</td>
                    <td style={{ padding: '7px 4px' }}>
                      <button onClick={() => removeRow(key)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#b0b8cc' }}>
                        <FiTrash2 size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {keys.length === 0 && (
        <div style={{ padding: '8px 16px 12px', color: '#9aa0b0', fontSize: 12, fontStyle: 'italic' }}>
          No tolerances defined yet — template will use ±{DEFAULT_TOL} mm for all features.
        </div>
      )}

      {/* Add row form */}
      <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f2f8', borderBottom: '1px solid #dde3ef' }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#8892a4', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>Add Tolerance</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <input value={newFeatureId} onChange={e => setNewFeatureId(e.target.value)} placeholder="Feature ID e.g. BORE_001" style={inputStyle} />
          <select value={newMeasType} onChange={e => setNewMeasType(e.target.value)} style={inputStyle}>
            <option value="dimension">dimension</option>
            <option value="diameter">diameter</option>
            <option value="width">width</option>
            <option value="depth">depth</option>
            <option value="radius">radius</option>
          </select>
          <input value={newNominal} onChange={e => setNewNominal(e.target.value)} placeholder="Nominal (mm)" type="number" step="0.001" style={inputStyle} />
          <div style={{ display: 'flex', gap: 6 }}>
            <input value={newUpper} onChange={e => setNewUpper(e.target.value)} placeholder="+Tol" type="number" step="0.001" style={{ ...inputStyle, flex: 1 }} />
            <input value={newLower} onChange={e => setNewLower(e.target.value)} placeholder="−Tol" type="number" step="0.001" style={{ ...inputStyle, flex: 1 }} />
          </div>
        </div>
        <button onClick={addRow} style={{ marginTop: 8, width: '100%', padding: '7px 0', borderRadius: 6, border: '1px solid #dde3ef', background: 'white', color: '#1e3a5f', fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
          <FiPlus size={13} /> Add
        </button>
      </div>

      {/* Actions */}
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button
          onClick={saveTols}
          disabled={saving}
          style={{ width: '100%', padding: '9px 0', borderRadius: 6, border: '1px solid #dde3ef', background: 'white', color: '#1e3a5f', fontSize: 13, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
        >
          <FiSave size={14} /> {saving ? 'Saving…' : 'Save Tolerances'}
        </button>
        <button
          onClick={downloadTemplate}
          disabled={downloading || !hasDatums}
          style={{ width: '100%', padding: '9px 0', borderRadius: 6, border: 'none', background: hasDatums ? '#1e3a5f' : '#eef1f7', color: hasDatums ? 'white' : '#9aa0b0', fontSize: 13, fontWeight: 600, cursor: hasDatums ? 'pointer' : 'not-allowed', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
        >
          <FiDownload size={14} /> {downloading ? 'Generating…' : 'Download Inspection Template'}
        </button>
      </div>
    </div>
  );
};

const inputStyle = {
  padding: '7px 10px', border: '1px solid #dde3ef', borderRadius: 6,
  fontSize: 12, outline: 'none', color: '#1a1a2e', width: '100%',
};

export default InspectionTab;
