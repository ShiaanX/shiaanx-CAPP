import api from './api';

export async function createJob(stepFile, partName, material) {
  const formData = new FormData();
  formData.append('step_file', stepFile);
  formData.append('part_name', partName);
  formData.append('material', material);
  return api.post('/jobs', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

export async function getJob(jobId) {
  return api.get(`/jobs/${jobId}`);
}

export async function getStageOutput(jobId, stage) {
  return api.get(`/jobs/${jobId}/output/${stage}`);
}

export function getPdfUrl(jobId) {
  return `${api.defaults.baseURL}/jobs/${jobId}/pdf`;
}

export function getStepUrl(jobId) {
  return `${api.defaults.baseURL}/jobs/${jobId}/step`;
}

export async function getFixtureSpec(jobId) {
  return api.get(`/jobs/${jobId}/fixture`);
}

export function getFixtureAssemblyUrl(jobId, setupIndex) {
  return `${api.defaults.baseURL}/jobs/${jobId}/fixture_assembly/${setupIndex}`;
}

export function getJawUrl(jobId, setupIndex, side) {
  return `${api.defaults.baseURL}/jobs/${jobId}/jaw/${setupIndex}/${side}`;
}
