import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import MainLayout from './components/layout/MainLayout';
import Upload from './pages/Upload';
import CappViewer from './pages/CappViewer';
import './styles/App.css';

const App = () => (
  <HashRouter>
    <Toaster position="top-right" />
    <Routes>
      <Route path="/" element={<Navigate to="/upload" replace />} />
      <Route element={<MainLayout />}>
        <Route path="/upload"       element={<Upload />} />
        <Route path="/parts/:jobId" element={<CappViewer />} />
      </Route>
    </Routes>
  </HashRouter>
);

export default App;
