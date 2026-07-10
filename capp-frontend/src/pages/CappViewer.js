import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { FiArrowLeft, FiDownload } from 'react-icons/fi';
import toast from 'react-hot-toast';
import { getJob, getStageOutput, getPdfUrl, getStepUrl } from '../services/cappService';
import PipelineProgress from '../components/viewer/PipelineProgress';
import OverviewTab from '../components/viewer/tabs/OverviewTab';
import StrategyTab from '../components/viewer/tabs/StrategyTab';
import ProgramSheetTab from '../components/viewer/tabs/ProgramSheetTab';
import FixtureTab from '../components/viewer/tabs/FixtureTab';
import FeatureMapTab from '../components/viewer/tabs/FeatureMapTab';
import ClosedLoopTab from '../components/viewer/tabs/ClosedLoopTab';
import DatumTaggerTab from '../components/viewer/tabs/DatumTaggerTab';
import InspectionTab from '../components/viewer/tabs/InspectionTab';
import RuleSheetsTab from '../components/viewer/tabs/RuleSheetsTab';
import AIFeedTab from '../components/viewer/tabs/AIFeedTab';

const POLL_INTERVAL = 2000;

const CappViewer = () => {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [outputs, setOutputs] = useState({});
  const [viewerUrl, setViewerUrl] = useState(null);
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
    { key: 'program_sheet',  label: 'Program' },
    { key: 'fixture',        label: 'Fixture' },
    { key: 'feature_map',    label: 'Features' },
    { key: 'closed_loop',    label: 'Closed Loop' },
    { key: 'datum_tagger',   label: 'Datums' },
    { key: 'inspection',     label: 'Inspection' },
    { key: 'rule_sheets',    label: 'Rules' },
    { key: 'ai_feed',        label: 'AI Feed' },
  ];

  const stepUrl = getStepUrl(jobId);
  const pdfUrl  = getPdfUrl(jobId);

  // Initialise viewerUrl once job is complete
  useEffect(() => {
    if (job?.status === 'COMPLETE' && !viewerUrl) {
      setViewerUrl(stepUrl);
    }
  }, [job?.status]); // eslint-disable-line

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
              src={viewerUrl ? `/step-viewer.html?url=${encodeURIComponent(viewerUrl)}` : ''}
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
          <div className="tab-bar" style={{ margin: '0 8px', paddingTop: 10, overflowX: 'auto', flexShrink: 0, flexWrap: 'nowrap' }}>
            {tabs.map(t => (
              <div
                key={t.key}
                className={`tab ${activeTab === t.key ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab(t.key);
                  if (t.key !== 'fixture') setViewerUrl(stepUrl);
                }}
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
            {activeTab === 'fixture' && (
              <FixtureTab
                jobId={jobId}
                active={activeTab === 'fixture'}
                onLoadAssembly={(url) => setViewerUrl(url)}
              />
            )}
            {activeTab === 'feature_map' && (
              <FeatureMapTab
                jobId={jobId}
                viewerRef={viewerIframeRef}
                active={activeTab === 'feature_map'}
              />
            )}
            {activeTab === 'closed_loop' && <ClosedLoopTab />}
            {activeTab === 'datum_tagger' && (
              <DatumTaggerTab
                jobId={jobId}
                viewerRef={viewerIframeRef}
                active={activeTab === 'datum_tagger'}
              />
            )}
            {activeTab === 'inspection' && <InspectionTab jobId={jobId} />}
            {activeTab === 'rule_sheets' && <RuleSheetsTab />}
            {activeTab === 'ai_feed' && <AIFeedTab />}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CappViewer;
