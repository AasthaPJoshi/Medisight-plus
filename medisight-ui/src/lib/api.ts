/**
 * FILE: src/lib/api.ts
 * All API calls to the MediSight+ FastAPI backend.
 * JWT token is injected automatically via Axios interceptor.
 */

import axios from 'axios';
import type {
  AuthUser, SymptomLog, Patient, ClinicalNote,
  BillingEncounter, RAGResult, ICD10Code, CPTCode, HCPCSCode,
  TimelineEvent, NoteAnalysisResult,
} from './types';

const BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const client = axios.create({ baseURL: BASE });

// Inject JWT token on every request
client.interceptors.request.use(cfg => {
  const token = localStorage.getItem('ms_token');
  if (token && cfg.headers) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

// Auto-logout on 401
client.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('ms_token');
      localStorage.removeItem('ms_user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

// ── AUTH ─────────────────────────────────────────────────────────────────
export const authAPI = {
  login: (email: string, password: string) =>
    client.post<AuthUser>('/auth/login', { email, password }).then(r => r.data),

  register: (email: string, password: string, full_name: string, role: string) =>
    client.post<AuthUser>('/auth/register', { email, password, full_name, role }).then(r => r.data),

  me: () => client.get('/auth/me').then(r => r.data),
};

// ── PATIENT ──────────────────────────────────────────────────────────────
export const patientAPI = {
  logSymptom: (data: { symptom: string; severity: number; duration?: string; notes?: string }) =>
    client.post<SymptomLog>('/patients/symptoms', data).then(r => r.data),

  getSymptoms: (limit = 50) =>
    client.get<SymptomLog[]>(`/patients/symptoms?limit=${limit}`).then(r => r.data),

  getTimeline: () =>
    client.get<TimelineEvent[]>('/patients/timeline').then(r => r.data),

  getProfile: () =>
    client.get<Patient>('/patients/profile').then(r => r.data),

  updateProfile: (data: Partial<Patient>) =>
    client.put<Patient>('/patients/profile', data).then(r => r.data),
};

// ── DOCTOR ───────────────────────────────────────────────────────────────
export const doctorAPI = {
  getPatients: () =>
    client.get<Patient[]>('/doctors/patients').then(r => r.data),

  getPatient: (id: number) =>
    client.get<{ patient: Patient; symptoms: SymptomLog[]; clinical_notes: ClinicalNote[] }>(
      `/doctors/patients/${id}`
    ).then(r => r.data),

  assignPatient: (patientId: number) =>
    client.post(`/doctors/patients/${patientId}/assign`).then(r => r.data),

  createNote: (patient_id: number, note_text: string) =>
    client.post<ClinicalNote>('/doctors/notes', { patient_id, note_text }).then(r => r.data),

  updateNote: (noteId: number, patient_id: number, note_text: string) =>
    client.put<ClinicalNote>(`/doctors/notes/${noteId}`, { patient_id, note_text }).then(r => r.data),

  lockNote: (noteId: number, follow_up?: string) =>
    client.post<ClinicalNote>(`/doctors/notes/${noteId}/lock`, {
      follow_up_instructions: follow_up ?? null
    }).then(r => r.data),
};

// ── RAG ──────────────────────────────────────────────────────────────────
export const ragAPI = {
  query: (query: string, patient_id?: number) =>
    client.post<RAGResult>('/rag/query', { query, patient_id }).then(r => r.data),

  analyzeNote: (noteId: number) =>
    client.post<NoteAnalysisResult>(`/rag/note-analysis/${noteId}`).then(r => r.data),

  health: () =>
    client.get('/rag/health').then(r => r.data),
};

// ── BILLING ──────────────────────────────────────────────────────────────
export const billingAPI = {
  getEncounters: (status?: string) =>
    client.get<BillingEncounter[]>(
      `/billing/encounters${status ? `?status_filter=${status}` : ''}`
    ).then(r => r.data),

  getEncounter: (id: number) =>
    client.get<BillingEncounter>(`/billing/encounters/${id}`).then(r => r.data),

  approveEncounter: (id: number, approved_ids: number[], remove_ids?: number[], manual_codes?: unknown[]) =>
    client.post(`/billing/encounters/${id}/approve`, {
      approved_ids,
      remove_ids: remove_ids ?? [],
      manual_codes: manual_codes ?? [],
    }).then(r => r.data),

  lookupICD10: (query: string, limit = 15) =>
    client.get<ICD10Code[]>(`/billing/lookup/icd10?query=${encodeURIComponent(query)}&limit=${limit}`).then(r => r.data),

  lookupCPT: (query: string, limit = 15) =>
    client.get<CPTCode[]>(`/billing/lookup/cpt?query=${encodeURIComponent(query)}&limit=${limit}`).then(r => r.data),

  lookupHCPCS: (query: string, limit = 15, category?: string) =>
    client.get<HCPCSCode[]>(
      `/billing/lookup/hcpcs?query=${encodeURIComponent(query)}&limit=${limit}${category ? `&category=${category}` : ''}`
    ).then(r => r.data),
};
