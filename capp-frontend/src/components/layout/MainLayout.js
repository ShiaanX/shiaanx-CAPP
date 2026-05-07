import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';

const MainLayout = () => (
  <div className="app-shell">
    <Sidebar />
    <div className="main-content">
      <Outlet />
    </div>
  </div>
);

export default MainLayout;
