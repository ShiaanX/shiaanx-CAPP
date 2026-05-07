import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { FiUpload, FiList, FiBook } from 'react-icons/fi';

const RULES_URL = 'https://shiaanx.github.io/shiaanx-CAPP/docs/RULES.html';

const Sidebar = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const items = [
    { path: '/upload', icon: <FiUpload size={20} />, label: 'Analyse Part' },
    { path: '/parts',  icon: <FiList size={20} />,   label: 'Recent Parts' },
  ];

  return (
    <div className="sidebar">
      <div className="sidebar-logo">SX</div>
      {items.map(item => (
        <div
          key={item.path}
          className={`nav-item ${location.pathname.startsWith(item.path) ? 'active' : ''}`}
          onClick={() => navigate(item.path)}
          title={item.label}
        >
          {item.icon}
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div
        className="nav-item"
        onClick={() => window.open(RULES_URL, '_blank', 'noopener')}
        title="Process Rules Sheet"
        style={{ marginBottom: 8 }}
      >
        <FiBook size={20} />
      </div>
    </div>
  );
};

export default Sidebar;
