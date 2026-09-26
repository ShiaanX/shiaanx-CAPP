import axios from 'axios';

const api = axios.create({
  baseURL: process.env.REACT_APP_CAPP_API_URL || 'http://localhost:8001',
  headers: { 'Content-Type': 'application/json' },
});

export default api;
