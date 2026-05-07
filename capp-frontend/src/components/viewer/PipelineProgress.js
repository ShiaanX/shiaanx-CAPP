import React from 'react';
import { FiCheck, FiLoader, FiX } from 'react-icons/fi';

// stageNum matches runner.py STAGE_OUTPUTS stage_num (step 6 removed, so 7-9 not 6-8)
const STAGES = [
  { key: 'features',     label: 'Extract',   stageNum: 1 },
  { key: 'clustered',    label: 'Cluster',   stageNum: 2 },
  { key: 'classified',   label: 'Classify',  stageNum: 3 },
  { key: 'processes',    label: 'Processes', stageNum: 4 },
  { key: 'setups',       label: 'Setups',    stageNum: 5 },
  { key: 'tools',        label: 'Tools',     stageNum: 7 },
  { key: 'params',       label: 'Params',    stageNum: 8 },
  { key: 'program_sheet',label: 'Sheet',     stageNum: 9 },
];

const PipelineProgress = ({ job }) => {
  if (!job || job.status === 'COMPLETE') return null;

  const completedStages = new Set(job.stages_complete || []);
  const currentStage = job.stage || 0;
  const failed = job.status === 'FAILED';

  return (
    <div style={{
      background: 'white',
      borderBottom: '1px solid #dde3ef',
      padding: '10px 24px',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      overflowX: 'auto',
    }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: '#6b7a99', whiteSpace: 'nowrap', marginRight: 8 }}>
        Pipeline
      </span>
      {STAGES.map((stage) => {
        const done = completedStages.has(stage.key);
        const active = !done && stage.stageNum === currentStage;
        const errored = failed && !done && stage.stageNum >= currentStage;

        return (
          <React.Fragment key={stage.key}>
            {stage.stageNum > 1 && (
              <div style={{ width: 20, height: 1, background: done ? '#2d6a4f' : '#dde3ef', flexShrink: 0 }} />
            )}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '4px 10px',
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 600,
              whiteSpace: 'nowrap',
              background: done ? '#e6f4ea' : active ? '#e8f0fe' : errored ? '#fdecea' : '#f5f6f8',
              color: done ? '#1e7e34' : active ? '#1a56db' : errored ? '#c0392b' : '#9aabb8',
            }}>
              {done ? <FiCheck size={11} /> : active ? <FiLoader size={11} style={{ animation: 'spin 1s linear infinite' }} /> : errored ? <FiX size={11} /> : null}
              {stage.label}
            </div>
          </React.Fragment>
        );
      })}
      {failed && (
        <span style={{ fontSize: 12, color: '#c0392b', marginLeft: 8 }}>
          {job.error ? `Error: ${job.error.slice(0, 80)}` : 'Pipeline failed'}
        </span>
      )}
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default PipelineProgress;
