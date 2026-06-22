/**
 * PAGE: Login  /login  /patient/login  /clinic/login  /billing/login
 * Role-selector gateway. Each portal has its own login URL for context.
 * On success, redirects to the role's dashboard.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../components/Toast';
import { authAPI } from '../../lib/api';
import type { UserRole } from '../../lib/types';

type LoginMode = 'login' | 'register';

const ROLE_MAP: Record<string, UserRole> = {
  '/patient/login': 'patient',
  '/clinic/login':  'doctor',
  '/billing/login': 'billing',
};

const ROLE_DEFAULTS: Record<UserRole, string> = {
  patient: 'patient@test.com',
  doctor:  'doctor@test.com',
  billing: 'billing@test.com',
};

const ROLE_ICONS: Record<UserRole, string> = {
  patient: '🧑',
  doctor:  '👨‍⚕️',
  billing: '💼',
};

const ROLE_LABELS: Record<UserRole, string> = {
  patient: 'Patient',
  doctor:  'Clinician',
  billing: 'Billing Staff',
};

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated, role } = useAuth();
  const { toast } = useToast();

  const pathRole = ROLE_MAP[location.pathname] ?? null;
  const [selectedRole, setSelectedRole] = useState<UserRole>(pathRole ?? 'patient');
  const [mode, setMode] = useState<LoginMode>('login');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('testpass123');
  const [fullName, setFullName] = useState('');
  const [loading, setLoading]   = useState(false);

  // Update email when role changes
  useEffect(() => {
    setEmail(ROLE_DEFAULTS[selectedRole]);
  }, [selectedRole]);

  // Redirect if already logged in
  useEffect(() => {
    if (isAuthenticated && role) {
      redirectRole(role);
    }
  }, [isAuthenticated, role]); // eslint-disable-line

  function redirectRole(r: UserRole) {
    if (r === 'patient') navigate('/patient/dashboard');
    else if (r === 'doctor') navigate('/clinic/dashboard');
    else navigate('/billing/dashboard');
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) { toast('Email and password required', 'error'); return; }
    setLoading(true);
    try {
      let user;
      if (mode === 'login') {
        user = await authAPI.login(email, password);
      } else {
        if (!fullName) { toast('Full name required', 'error'); setLoading(false); return; }
        user = await authAPI.register(email, password, fullName, selectedRole);
      }
      login(user);
      toast(`Welcome, ${user.full_name}`, 'success');
      redirectRole(user.role as UserRole);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Sign in failed';
      toast(String(msg), 'error');
    }
    setLoading(false);
  }

  const showRolePicker = !pathRole;

  return (
    <div className="login-bg">
      <div className="login-glow" />
      <form className="login-card" onSubmit={handleSubmit}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div className="login-mark">🏥</div>
          <div className="login-title">Medi<span>Sight</span>+</div>
          <div className="login-sub">
            {pathRole
              ? `${ROLE_LABELS[pathRole]} Portal`
              : 'Clinical AI Platform'}
          </div>
        </div>

        {/* Role picker — only on /login */}
        {showRolePicker && (
          <div className="form-group">
            <label className="field-label">Sign in as</label>
            <div className="role-picker">
              {(['patient', 'doctor', 'billing'] as UserRole[]).map(r => (
                <div
                  key={r}
                  className={`role-opt${selectedRole === r ? ' selected' : ''}`}
                  onClick={() => setSelectedRole(r)}
                >
                  <div className="role-opt-icon">{ROLE_ICONS[r]}</div>
                  <div className="role-opt-label">{ROLE_LABELS[r]}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Fixed role display */}
        {pathRole && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20, padding: '8px 12px', background: 'var(--teal-glow)', border: '1px solid var(--teal-border)', borderRadius: 8 }}>
            <span style={{ fontSize: 20 }}>{ROLE_ICONS[pathRole]}</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--teal)' }}>{ROLE_LABELS[pathRole]}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Clinical AI Platform</div>
            </div>
          </div>
        )}

        {mode === 'register' && (
          <div className="form-group">
            <label className="field-label">Full name</label>
            <input
              className="field-input"
              placeholder="Your full name"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              autoFocus
            />
          </div>
        )}

        <div className="form-group">
          <label className="field-label">Email</label>
          <input
            className="field-input"
            type="email"
            placeholder="your@email.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            autoFocus={mode === 'login'}
          />
        </div>

        <div className="form-group">
          <label className="field-label">Password</label>
          <input
            className="field-input"
            type="password"
            placeholder="Enter password"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />
        </div>

        <button className="btn btn-primary btn-wide" type="submit" disabled={loading}>
          {loading ? <><span className="spinner" />Processing...</> : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12, color: 'var(--text-muted)' }}>
          {mode === 'login' ? (
            <>No account?{' '}
              <span style={{ color: 'var(--teal)', cursor: 'pointer' }} onClick={() => setMode('register')}>
                Register here
              </span>
            </>
          ) : (
            <>Have an account?{' '}
              <span style={{ color: 'var(--teal)', cursor: 'pointer' }} onClick={() => setMode('login')}>
                Sign in
              </span>
            </>
          )}
        </div>

        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          <span
            style={{ color: 'var(--teal)', cursor: 'pointer' }}
            onClick={() => navigate('/')}
          >
            Back to home
          </span>
        </div>
      </form>
    </div>
  );
}
