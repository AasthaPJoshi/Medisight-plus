// All API response and domain types for MediSight+

export type UserRole = 'patient' | 'doctor' | 'billing';

export interface AuthUser {
  user_id: number;
  full_name: string;
  email: string;
  role: UserRole;
  access_token: string;
}

export interface SymptomLog {
  id: number;
  patient_id: number;
  symptom: string;
  severity: number;
  duration: string | null;
  notes: string | null;
  logged_at: string;
}

export interface Patient {
  id: number;
  user_id: number;
  full_name: string;
  email: string;
  date_of_birth: string | null;
  gender: string | null;
  blood_type: string | null;
  allergies: string | null;
  current_medications: string[] | null;
  assigned_doctor_id: number | null;
  latest_severity: number | null;
  latest_symptom: string | null;
}

export interface ClinicalNote {
  id: number;
  doctor_id: number;
  patient_id: number;
  note_text: string;
  is_locked: boolean;
  locked_at: string | null;
  patient_summary: string | null;
  follow_up_instructions: string | null;
  created_at: string;
  updated_at: string;
}

export interface CodeSuggestion {
  id: number;
  encounter_id: number;
  code_type: 'ICD10' | 'CPT' | 'HCPCS';
  code: string;
  description: string;
  confidence: number | null;
  denial_risk: 'low' | 'medium' | 'high';
  denial_risk_reason: string | null;
  is_approved: boolean;
  is_manual: boolean;
}

export interface BillingEncounter {
  id: number;
  note_id: number;
  status: 'draft' | 'pending_review' | 'approved' | 'locked';
  parsed_note_data: Record<string, unknown> | null;
  denial_risk_flags: unknown[] | null;
  audit_log: Record<string, unknown>[];
  code_suggestions: CodeSuggestion[];
  created_at: string;
  updated_at: string;
  // list view extras
  patient_id?: number;
  doctor_id?: number;
  total_code_suggestions?: number;
  approved_codes?: number;
  has_high_risk_flags?: boolean;
}

export interface RAGResult {
  answer: string;
  sources: { pmid: string; title: string; url: string }[];
  confidence: number;
  insufficient_context: boolean;
  query_type: string;
}

export interface ICD10Code {
  code: string;
  description: string;
  short_description: string | null;
  category: string | null;
  code_prefix: string | null;
}

export interface CPTCode {
  code: string;
  description: string;
  rvu: number | null;
  payment_amount: number | null;
  category: string | null;
}

export interface HCPCSCode {
  code: string;
  description: string;
  category: string | null;
  effective_date: string | null;
}

export interface TimelineEvent {
  event_type: 'symptom' | 'clinical_note' | 'billing_approved';
  timestamp: string;
  title: string;
  detail: string | null;
  severity: number | null;
  metadata: Record<string, unknown> | null;
}

export interface NoteAnalysisResult {
  note_id: number;
  encounter_id: number;
  patient_summary: string;
  parsed_note: Record<string, unknown>;
  billing_codes: {
    code_type: string; code: string; description: string;
    confidence: number; denial_risk: string; denial_risk_reason?: string;
  }[];
  denial_flags: unknown[];
  status: string;
  message: string;
}
