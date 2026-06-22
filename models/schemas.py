"""
FILE: models/schemas.py
=======================
WHAT THIS FILE IS:
    Pydantic schemas — these define what data is EXPECTED in API requests
    and what data is RETURNED in API responses.

CONCEPT — Why separate schemas from ORM models?
    - ORM models (orm_models.py) define the DATABASE structure
    - Pydantic schemas define the API's INPUT/OUTPUT structure
    These are intentionally different:
    * You never want to expose hashed_password in an API response
    * You want request validation (e.g. severity must be 1-10)
    * You want clear, documented API contracts

HOW PYDANTIC WORKS:
    class SymptomLogCreate(BaseModel):
        symptom: str       <- required string
        severity: int      <- required integer
        duration: str = "" <- optional string, defaults to ""

    FastAPI will:
    1. Parse the incoming JSON body against this schema
    2. Automatically return HTTP 422 with details if validation fails
    3. Return HTTP 200 with the response schema if successful

INPUT:  JSON from API requests / ORM objects from database
OUTPUT: Validated Python objects / JSON responses

HOW TO EXPLORE THESE: Run the app and visit http://localhost:8000/docs
    FastAPI auto-generates Swagger UI from these schemas
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from models.orm_models import UserRole


# =============================================================================
# AUTH SCHEMAS
# Used by: POST /auth/register and POST /auth/login
# =============================================================================

class UserRegister(BaseModel):
    """What the frontend sends when a new user signs up"""
    email: EmailStr                    # Pydantic validates email format automatically
    full_name: str
    password: str = Field(min_length=8, description="Must be at least 8 characters")
    role: UserRole = UserRole.patient  # Default to patient if not specified

    model_config = {"from_attributes": True, "use_enum_values": True}


class UserLogin(BaseModel):
    """What the frontend sends when logging in"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """What the API returns after successful login — the JWT token"""
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    full_name: str


class UserResponse(BaseModel):
    """Safe user data to return — NOTE: no hashed_password field"""
    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# SYMPTOM LOG SCHEMAS
# Used by: POST /symptoms and GET /patients/{id}/symptoms
# =============================================================================

class SymptomLogCreate(BaseModel):
    """What the patient sends when logging a symptom"""
    symptom: str = Field(min_length=2, max_length=500,
                         description="Name of the symptom, e.g. 'chest pain'")
    severity: int = Field(ge=1, le=10,
                          description="Severity on scale 1-10 (1=mild, 10=severe)")
    duration: Optional[str] = Field(None, description="How long, e.g. '3 days'")
    notes: Optional[str] = Field(None, description="Additional context")


class SymptomLogResponse(BaseModel):
    """What the API returns after creating/fetching a symptom log"""
    id: int
    patient_id: int
    symptom: str
    severity: int
    duration: Optional[str]
    notes: Optional[str]
    logged_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# PATIENT SCHEMAS
# Used by: GET /patients (doctor view), PATCH /patients/{id}
# =============================================================================

class PatientCreate(BaseModel):
    """Extended profile info for a patient (set after registration)"""
    date_of_birth: Optional[str] = None   # "YYYY-MM-DD"
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    allergies: Optional[str] = None       # comma-separated
    current_medications: Optional[List[str]] = None


class PatientResponse(BaseModel):
    """Patient data returned to the doctor dashboard"""
    id: int
    user_id: int
    full_name: str           # From the related User object
    email: str               # From the related User object
    date_of_birth: Optional[str]
    gender: Optional[str]
    blood_type: Optional[str]
    allergies: Optional[str]
    current_medications: Optional[List[str]]
    assigned_doctor_id: Optional[int]
    # Latest symptom for the patient list view
    latest_severity: Optional[int] = None
    latest_symptom: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================================
# CLINICAL NOTE SCHEMAS
# Used by: POST /notes, POST /notes/{id}/lock, GET /notes/{id}
# =============================================================================

class ClinicalNoteCreate(BaseModel):
    """What the doctor sends when writing a note"""
    patient_id: int
    note_text: str = Field(min_length=10,
                           description="Clinical notes from the doctor's assessment")


class ClinicalNoteLock(BaseModel):
    """When doctor locks a note, they can add follow-up instructions"""
    follow_up_instructions: Optional[str] = None


class ClinicalNoteResponse(BaseModel):
    """Full note response including AI-generated fields"""
    id: int
    doctor_id: int
    patient_id: int
    note_text: str
    is_locked: bool
    locked_at: Optional[datetime]
    patient_summary: Optional[str]      # Plain-English summary for patient
    follow_up_instructions: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# BILLING SCHEMAS
# Used by: all /billing/* routes
# =============================================================================

class CodeSuggestionResponse(BaseModel):
    """Single billing code suggestion from the AI"""
    id: int
    encounter_id: int
    code_type: str          # "ICD10", "CPT", or "HCPCS"
    code: str               # e.g. "E11.9"
    description: str        # e.g. "Type 2 diabetes mellitus without complications"
    confidence: Optional[float]    # 0.0 to 1.0
    denial_risk: str        # "low", "medium", "high"
    denial_risk_reason: Optional[str]
    is_approved: bool
    is_manual: bool

    class Config:
        from_attributes = True


class BillingEncounterResponse(BaseModel):
    """Full billing encounter with all code suggestions"""
    id: int
    note_id: int
    status: str             # "draft", "pending_review", "approved", "locked"
    parsed_note_data: Optional[dict]   # AI-parsed note structure
    denial_risk_flags: Optional[list]  # Risk flags for the code bundle
    audit_log: List[dict]
    code_suggestions: List[CodeSuggestionResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CodeApprovalRequest(BaseModel):
    """What billing staff sends when approving/editing codes"""
    # List of code suggestion IDs to approve
    approved_ids: List[int]
    # Optional: codes to remove (by ID)
    remove_ids: Optional[List[int]] = []
    # Optional: manually add codes not suggested by AI
    manual_codes: Optional[List[dict]] = []
    # e.g. [{"code_type": "ICD10", "code": "J18.9", "description": "Pneumonia"}]


# =============================================================================
# BILLING CODE LOOKUP SCHEMAS
# Used by: GET /billing/lookup/* routes
# =============================================================================

class ICD10LookupResult(BaseModel):
    """One ICD-10 code returned from a search"""
    code: str
    description: str
    short_description: Optional[str]
    category: Optional[str]
    code_prefix: Optional[str]


class HCPCSLookupResult(BaseModel):
    """One HCPCS code returned from a search"""
    code: str
    description: str
    category: Optional[str]
    effective_date: Optional[str]


class CPTLookupResult(BaseModel):
    """One CPT code returned from a search"""
    code: str
    description: str
    rvu: Optional[float]
    payment_amount: Optional[float]
    category: Optional[str]


# =============================================================================
# TIMELINE SCHEMA
# Used by: GET /patients/{id}/timeline
# Returns a merged chronological view of symptoms, notes, and billing
# =============================================================================

class TimelineEvent(BaseModel):
    """One event in the patient timeline (symptom, note, or billing)"""
    event_type: str          # "symptom", "clinical_note", "billing_approved"
    timestamp: datetime
    title: str               # Short description
    detail: Optional[str]    # More detail
    severity: Optional[int]  # Only for symptom events (1-10)
    metadata: Optional[dict] # Anything extra (code bundle, doctor name, etc.)
