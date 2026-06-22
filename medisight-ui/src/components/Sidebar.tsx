/**
 * COMPONENT: Sidebar
 * Role-aware navigation. Each role sees only their portal's routes.
 * Doctor sees clinical nav. Patient sees patient nav. Billing sees billing nav.
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

interface NavItem {
  section?: string;
  path?: string;
  icon?: string;
  label?: string;
  badge?: string | number;
}

function patientNav(): NavItem[] {
  return [
    { section: 'Overview' },
    { path: '/patient/dashboard', icon: '⊞', label: 'Dashboard' },
    { path: '/patient/timeline',  icon: '◷', label: 'My Timeline' },
    { section: 'Health' },
    { path: '/patient/symptoms',  icon: '❤', label: 'Log Symptom' },
    { path: '/patient/profile',   icon: '◎', label: 'Profile' },
  ];
}

function doctorNav(patientCount = 0): NavItem[] {
  return [
    { section: 'Clinical' },
    { path: '/clinic/dashboard',  icon: '⊞', label: 'Dashboard' },
    { path: '/clinic/patients',   icon: '◎', label: 'Patients', badge: patientCount || undefined },
    { section: 'Workspace' },
    { path: '/clinic/encounter',  icon: '✎', label: 'New Encounter' },
    { path: '/clinic/ai',         icon: '✦', label: 'AI Assistant' },
    { path: '/clinic/analytics', icon: '📊', label: 'Analytics' },
  ];
}

function billingNav(pendingCount = 0): NavItem[] {
  return [
    { section: 'Billing' },
    { path: '/billing/dashboard',   icon: '⊞', label: 'Dashboard' },
    { path: '/billing/encounters',  icon: '◎', label: 'Encounters', badge: pendingCount || undefined },
    { section: 'Tools' },
    { path: '/billing/lookup',      icon: '⊕', label: 'Code Lookup' },
    { path: '/billing/audit',       icon: '◈', label: 'Audit Log' },
  ];
}

interface SidebarProps {
  patientCount?: number;
  pendingCount?: number;
}

export function Sidebar({ patientCount = 0, pendingCount = 0 }: SidebarProps) {
  const { user, role, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const nav =
    role === 'patient' ? patientNav() :
    role === 'doctor'  ? doctorNav(patientCount) :
                         billingNav(pendingCount);

  const initial = (user?.full_name ?? 'U')[0].toUpperCase();

  const roleLabel =
    role === 'patient' ? 'Patient Portal' :
    role === 'doctor'  ? 'Clinical Portal' :
                         'Billing Portal';

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-row">
          <div className="sidebar-logo-icon">🏥</div>
          <div className="sidebar-logo-name">
            Medi<span>Sight</span>+
          </div>
        </div>
        <div className="sidebar-logo-sub">Clinical AI Platform</div>
      </div>

      {/* Role badge */}
      <div className="sidebar-role">{roleLabel}</div>

      {/* Nav */}
      <nav className="sidebar-nav">
        {nav.map((item, i) =>
          item.section ? (
            <div key={i} className="sidebar-section">{item.section}</div>
          ) : (
            <div
              key={item.path}
              className={`sidebar-item${pathname.startsWith(item.path!) ? ' active' : ''}`}
              onClick={() => navigate(item.path!)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && navigate(item.path!)}
            >
              <span className="sidebar-item-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.badge !== undefined && (
                <span className="sidebar-badge">{item.badge}</span>
              )}
            </div>
          )
        )}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-avatar">{initial}</div>
          <div>
            <div className="sidebar-user-name">{user?.full_name}</div>
            <div className="sidebar-user-email">{user?.email}</div>
          </div>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          style={{ width: '100%', justifyContent: 'center', marginTop: 10 }}
          onClick={logout}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
