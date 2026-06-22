/**
 * FILE: src/App.tsx
 * Root router. Every portal has its own login URL.
 * Protected routes check role before rendering.
 */

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ToastProvider } from './components/Toast';
import type { UserRole } from './lib/types';
import AnalyticsDashboard from './pages/clinic/AnalyticsDashboard';

// Pages
import LandingPage      from './pages/public/LandingPage';
import LoginPage        from './pages/public/LoginPage';
import PatientDashboard from './pages/patient/PatientDashboard';
import LogSymptom       from './pages/patient/LogSymptom';
import PatientTimeline  from './pages/patient/PatientTimeline';
import PatientProfile   from './pages/patient/PatientProfile';
import ClinicDashboard  from './pages/clinic/ClinicDashboard';
import EncounterWorkspace from './pages/clinic/EncounterWorkspace';
import { PatientList, AIAssistant } from './pages/clinic/ClinicPages';
import { BillingDashboard, BillingEncounters, CodeLookup, AuditLog } from './pages/billing/BillingPages';

// ── PROTECTED ROUTE ──────────────────────────────────────────────────────────
interface ProtectedProps {
  element: React.ReactElement;
  allowedRole: UserRole;
}

function Protected({ element, allowedRole }: ProtectedProps) {
  const { isAuthenticated, role } = useAuth();

  if (!isAuthenticated) {
    // Redirect to the right portal login
    const loginMap: Record<UserRole, string> = {
      patient: '/patient/login',
      doctor:  '/clinic/login',
      billing: '/billing/login',
    };
    return <Navigate to={loginMap[allowedRole]} replace />;
  }

  if (role !== allowedRole) {
    return (
      <div className="perm-block">
        <div className="perm-block-icon">🔒</div>
        <div className="perm-block-title">Access denied</div>
        <div className="perm-block-sub">Your role ({role}) cannot access this portal</div>
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 12 }} onClick={() => window.history.back()}>
          Go back
        </button>
      </div>
    );
  }

  return element;
}

// ── ROOT REDIRECT ─────────────────────────────────────────────────────────────
function RootRedirect() {
  const { isAuthenticated, role } = useAuth();
  if (!isAuthenticated) return <LandingPage />;
  if (role === 'patient') return <Navigate to="/patient/dashboard" replace />;
  if (role === 'doctor')  return <Navigate to="/clinic/dashboard" replace />;
  return <Navigate to="/billing/dashboard" replace />;
}

// ── APP ───────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            {/* Public */}
            <Route path="/" element={<RootRedirect />} />
            <Route path="/login"          element={<LoginPage />} />
            <Route path="/patient/login"  element={<LoginPage />} />
            <Route path="/clinic/login"   element={<LoginPage />} />
            <Route path="/billing/login"  element={<LoginPage />} />

            {/* Patient portal */}
            <Route path="/patient/dashboard" element={<Protected element={<PatientDashboard />} allowedRole="patient" />} />
            <Route path="/patient/symptoms"  element={<Protected element={<LogSymptom />}        allowedRole="patient" />} />
            <Route path="/patient/timeline"  element={<Protected element={<PatientTimeline />}   allowedRole="patient" />} />
            <Route path="/patient/profile"   element={<Protected element={<PatientProfile />}    allowedRole="patient" />} />

            {/* Clinical portal */}
            <Route path="/clinic/dashboard"  element={<Protected element={<ClinicDashboard />}    allowedRole="doctor" />} />
            <Route path="/clinic/patients"   element={<Protected element={<PatientList />}         allowedRole="doctor" />} />
            <Route path="/clinic/encounter"  element={<Protected element={<EncounterWorkspace />}  allowedRole="doctor" />} />
            <Route path="/clinic/ai"         element={<Protected element={<AIAssistant />}         allowedRole="doctor" />} />

            {/* Billing portal */}
            <Route path="/billing/dashboard"   element={<Protected element={<BillingDashboard />}  allowedRole="billing" />} />
            <Route path="/billing/encounters"  element={<Protected element={<BillingEncounters />} allowedRole="billing" />} />
            <Route path="/billing/lookup"      element={<Protected element={<CodeLookup />}         allowedRole="billing" />} />
            <Route path="/billing/audit"       element={<Protected element={<AuditLog />}           allowedRole="billing" />} />

            <Route path="/clinic/analytics" element={<Protected element={<AnalyticsDashboard />} allowedRole="doctor" />} />

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
