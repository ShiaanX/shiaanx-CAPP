import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiUploadCloud } from 'react-icons/fi';
import toast from 'react-hot-toast';
import { createJob } from '../services/cappService';

const MATERIALS = [
  'aluminium',
  'aluminium_6061',
  'aluminium_7075',
  'steel_mild',
  'steel_stainless',
  'titanium',
  'brass',
];

const Upload = () => {
  const navigate = useNavigate();
  const fileRef = useRef();
  const [file, setFile] = useState(null);
  const [partName, setPartName] = useState('');
  const [material, setMaterial] = useState('aluminium');
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleFile = (f) => {
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['step', 'stp'].includes(ext)) {
      toast.error('Only .step / .stp files are supported');
      return;
    }
    setFile(f);
    if (!partName) setPartName(f.name.replace(/\.(step|stp)$/i, ''));
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files[0]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { toast.error('Please select a STEP file'); return; }
    setLoading(true);
    try {
      const res = await createJob(file, partName || file.name, material);
      navigate(`/parts/${res.data.job_id}`);
    } catch (err) {
      toast.error('Failed to start analysis. Is the CAPP service running?');
      setLoading(false);
    }
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Topbar */}
      <div className="topbar">
        <span className="topbar-title">Analyse Part</span>
        <span className="topbar-brand">ShiaanX</span>
      </div>

      {/* Content */}
      <div className="page-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ width: '100%', maxWidth: 520 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Upload STEP File</h2>
          <p style={{ color: '#6b7a99', fontSize: 14, marginBottom: 24 }}>
            Upload a .step or .stp file to run the CAPP analysis pipeline.
          </p>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Drop zone */}
            <div
              onClick={() => fileRef.current.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              style={{
                border: `2px dashed ${dragging ? '#1e3a5f' : file ? '#2d6a4f' : '#c5d0e0'}`,
                borderRadius: 10,
                padding: '32px 20px',
                textAlign: 'center',
                cursor: 'pointer',
                background: dragging ? '#f0f4fa' : file ? '#f0faf4' : '#fafbfc',
                transition: 'all 0.15s',
              }}
            >
              <FiUploadCloud size={36} color={file ? '#2d6a4f' : '#9aabb8'} style={{ marginBottom: 8 }} />
              {file ? (
                <>
                  <div style={{ fontWeight: 600, color: '#2d6a4f' }}>{file.name}</div>
                  <div style={{ fontSize: 12, color: '#6b7a99', marginTop: 4 }}>
                    {(file.size / 1024).toFixed(1)} KB — click to replace
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontWeight: 600, color: '#1a1a2e' }}>Drop your STEP file here</div>
                  <div style={{ fontSize: 12, color: '#6b7a99', marginTop: 4 }}>or click to browse</div>
                </>
              )}
              <input
                ref={fileRef}
                type="file"
                accept=".step,.stp"
                style={{ display: 'none' }}
                onChange={(e) => handleFile(e.target.files[0])}
              />
            </div>

            {/* Part name */}
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#4a5568', display: 'block', marginBottom: 6 }}>
                Part Name
              </label>
              <input
                type="text"
                value={partName}
                onChange={(e) => setPartName(e.target.value)}
                placeholder="e.g. Bracket Assembly"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  border: '1px solid #c5d0e0',
                  borderRadius: 8,
                  fontSize: 14,
                  outline: 'none',
                }}
              />
            </div>

            {/* Material */}
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#4a5568', display: 'block', marginBottom: 6 }}>
                Material
              </label>
              <select
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  border: '1px solid #c5d0e0',
                  borderRadius: 8,
                  fontSize: 14,
                  background: 'white',
                  outline: 'none',
                }}
              >
                {MATERIALS.map(m => (
                  <option key={m} value={m}>{m.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>

            <button type="submit" className="btn-primary" disabled={loading} style={{ marginTop: 8 }}>
              {loading ? 'Starting analysis…' : 'Analyse Part'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default Upload;
