import React from 'react';
import { FiDownload } from 'react-icons/fi';
import { getPdfUrl } from '../../../services/cappService';

const ProgramSheetTab = ({ jobId, hasPdf }) => {
  const pdfUrl = getPdfUrl(jobId);

  if (!hasPdf) {
    return (
      <div style={{ color: '#9aabb8', fontSize: 13, padding: '16px 0' }}>
        Program sheet not ready yet…
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <a href={pdfUrl} target="_blank" rel="noreferrer" className="btn-primary" style={{ alignSelf: 'flex-start', textDecoration: 'none' }}>
        <FiDownload size={15} /> Download PDF
      </a>
      <iframe
        src={pdfUrl}
        title="Program Sheet"
        style={{ width: '100%', height: 500, border: '1px solid #dde3ef', borderRadius: 8 }}
      />
    </div>
  );
};

export default ProgramSheetTab;
