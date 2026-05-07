import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { FiArrowLeft, FiDownload } from 'react-icons/fi';
import toast from 'react-hot-toast';
import { getJob, getStageOutput, getPdfUrl, getStepUrl } from '../services/cappService';
import PipelineProgress from '../components/viewer/PipelineProgress';
import OverviewTab from '../components/viewer/tabs/OverviewTab';
import StrategyTab from '../components/viewer/tabs/StrategyTab';
import ProgramSheetTab from '../components/viewer/tabs/ProgramSheetTab';

const POLL_INTERVAL = 2000;

const CappViewer = () => {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [outputs, setOutputs] = useState({});
  const pollRef = useRef(null);
  const viewerIframeRef = useRef(null);

  const fetchOutputs = useCallback(async (stagesComplete) => {
    const toFetch = ['classified', 'setups', 'params'].filter(
      s => stagesComplete.includes(s) && !outputs[s]
    );
    for (const stage of toFetch) {
      try {
        const res = await getStageOutput(jobId, stage);
        setOutputs(prev => ({ ...prev, [stage]: res.data }));
      } catch (_) {}
    }
  }, [jobId, outputs]);

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await getJob(jobId);
        const j = res.data;
        setJob(j);
        await fetchOutputs(j.stages_complete || []);
        if (j.status === 'COMPLETE' || j.status === 'FAILED') {
          clearInterval(pollRef.current);
        }
      } catch (err) {
        clearInterval(pollRef.current);
        toast.error('Could not reach CAPP service');
      }
    };

    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(pollRef.current);
  }, [jobId]); // eslint-disable-line

  const tabs = [
    { key: 'overview',       label: 'Overview' },
    { key: 'strategy',       label: 'Strategy' },
    { key: 'program_sheet',  label: 'Program Sheet' },
  ];

  const stepUrl = getStepUrl(jobId);
  const pdfUrl  = getPdfUrl(jobId);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Topbar */}
      <div className="topbar">
        <button
          onClick={() => navigate('/upload')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, color: '#6b7a99', fontSize: 14 }}
        >
          <FiArrowLeft size={16} /> Back
        </button>
        <span className="topbar-title">{job?.part_name || 'Analysing…'}</span>
        {job?.has_pdf && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" className="btn-primary" style={{ textDecoration: 'none', fontSize: 13, padding: '7px 14px' }}>
            <FiDownload size={14} /> Download PDF
          </a>
        )}
        <span className="topbar-brand">ShiaanX</span>
      </div>

      {/* Pipeline progress bar */}
      <PipelineProgress job={job} />

      {/* Main 3-panel layout */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* 3D viewer */}
        <div style={{ flex: 1, background: '#1a1a2e', position: 'relative', overflow: 'hidden' }}>
          {job?.status === 'COMPLETE' ? (
            <iframe
              ref={viewerIframeRef}
              src={`/step-viewer.html?url=${encodeURIComponent(stepUrl)}`}
              title="3D Viewer"
              style={{ width: '100%', height: '100%', border: 'none' }}
            />
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#4a5568' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ width: 64, height: 64, border: '3px solid #2d3748', borderTop: '3px solid #4299e1', borderRadius: '50%', margin: '0 auto 16px', animation: 'spin 1s linear infinite' }} />
                <div style={{ color: '#6b7a99', fontSize: 14 }}>
                  {job?.stage_name ? `Running: ${job.stage_name}…` : 'Starting pipeline…'}
                </div>
              </div>
            </div>
          )}
          <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>

        {/* Right panel */}
        <div style={{ width: 340, background: 'white', borderLeft: '1px solid #dde3ef', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar */}
          <div className="tab-bar" style={{ margin: '0 16px', paddingTop: 12 }}>
            {tabs.map(t => (
              <div
                key={t.key}
                className={`tab ${activeTab === t.key ? 'active' : ''}`}
                onClick={() => setActiveTab(t.key)}
              >
                {t.label}
              </div>
            ))}
          </div>

          {/* Tab content */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 16px 16px' }}>
            {activeTab === 'overview' && (
              <OverviewTab
                classified={outputs.classified}
                setups={outputs.setups}
                features={outputs.features}
              />
            )}
            {activeTab === 'strategy' && (
              <StrategyTab
                params={outputs.params}
                onSelectFaces={(faceIndices) => {
                  viewerIframeRef.current?.contentWindow?.postMessage(
                    { type: 'highlight', faceIndices },
                    '*'
                  );
                }}
              />
            )}
            {activeTab === 'program_sheet' && (
              <ProgramSheetTab jobId={jobId} hasPdf={job?.has_pdf} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CappViewer;
