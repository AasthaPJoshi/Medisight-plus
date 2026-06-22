"""
FILE: models/orm_models.py
==========================
WHAT THIS FILE IS:
    Defines every database table as a Python class.
    Each class = one table in PostgreSQL.
    Each class attribute = one column in that table.

CONCEPT — ORM (Object Relational Mapper):
    Instead of creating tables with raw SQL like:
        CREATE TABLE users (id SERIAL PRIMARY KEY, email VARCHAR(255)...);
    You write a Python class:
        class User(Base):
            id = Column(Integer, primary_key=True)
            email = Column(String(255))
    Then SQLAlchemy generates and runs the SQL for you.

TABLES IN THIS FILE:
    1. User           — Both patients and doctors (differentiated by 'role' column)
    2. Patient        — Patient profile, linked to their User account
    3. SymptomLog     — Each symptom a patient logs (severity 1-10, duration, notes)
    4. ClinicalNote   — Doctor's notes for a patient visit
    5. BillingEncounter — The billing record created when a note is locked
    6. CodeSuggestion — Individual ICD-10/CPT/HCPCS code suggestions for an encounter
    7. ICD10Code      — Loaded from CMS FY2026 ICD-10-CM file (77K+ rows)
    8. HCPCSCode      — Loaded from CMS HCPCS Level II quarterly file
    9. CPTCode        — Loaded from CMS Medicare Physician Fee Schedule (MPFS)

INPUT:  Base from models/database.py
OUTPUT: All table classes — imported by api/ route files and billing/ingest_codes.py

HOW TO CREATE TABLES IN POSTGRESQL:
    python3 -c "from models.orm_models import create_all_tables; create_all_tables()"
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text,
    DateTime, ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum
from models.database import Base, engine


# ─────────────────────────────────────────────────────────────────────────────
# ENUM: UserRole
# Defines the three types of users in the system
# 'patient'  = logs symptoms, sees plain-English summaries
# 'doctor'   = writes clinical notes, sees AI suggestions + billing codes
# 'billing'  = reviews and approves the ICD-10/CPT/HCPCS code bundle
# ─────────────────────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    patient = "patient"
    doctor = "doctor"
    billing = "billing"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: users
# Stores login credentials and role for every user in the system
# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    # Primary key — auto-increments (1, 2, 3...)
    id = Column(Integer, primary_key=True, index=True)

    # Login email — must be unique across all users
    email = Column(String(255), unique=True, index=True, nullable=False)

    # Full name for display
    full_name = Column(String(255), nullable=False)

    # bcrypt-hashed password — NEVER store plain text passwords
    hashed_password = Column(String(255), nullable=False)

    # Role: 'patient', 'doctor', or 'billing'
    # This is what JWT uses to decide which dashboard to show
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.patient)

    # When the account was created
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships: a User might have a Patient profile OR a set of ClinicalNotes
    # back_populates links the two ends of the relationship together
    patient_profile = relationship("Patient", back_populates="user", uselist=False, foreign_keys="[Patient.user_id]")
    clinical_notes = relationship("ClinicalNote", back_populates="doctor")

    def __repr__(self):
        return f"<User id={self.id} email={self.email} role={self.role}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: patients
# Extended profile for users with role='patient'
# One-to-one with User table
# ─────────────────────────────────────────────────────────────────────────────
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)

    # Links to the users table — every patient IS a user
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    # The doctor assigned to this patient (optional — can be null initially)
    assigned_doctor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Demographics
    date_of_birth = Column(String(20), nullable=True)   # stored as "YYYY-MM-DD"
    gender = Column(String(20), nullable=True)
    blood_type = Column(String(5), nullable=True)       # e.g. "A+", "O-"

    # Known allergies — stored as a comma-separated string
    allergies = Column(Text, nullable=True)

    # Current medications — stored as JSON list
    current_medications = Column(JSON, nullable=True)   # e.g. ["Metformin 500mg", "Lisinopril 10mg"]

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    # foreign_keys must be specified explicitly because Patient has TWO FKs to users:
    # user_id (the patient's own account) and assigned_doctor_id (their doctor)
    # Without foreign_keys=, SQLAlchemy can't determine which FK to use for each relationship
# Relationships
    # foreign_keys must be specified as string because Patient has TWO FKs to users table
    user = relationship("User", back_populates="patient_profile", foreign_keys="[Patient.user_id]")
    symptom_logs = relationship("SymptomLog", back_populates="patient", order_by="SymptomLog.logged_at")
    clinical_notes = relationship("ClinicalNote", back_populates="patient")

    def __repr__(self):
        return f"<Patient id={self.id} user_id={self.user_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: symptom_logs
# Each row = one symptom a patient logged
# The source of data for the patient timeline and the AI suggestion
# ─────────────────────────────────────────────────────────────────────────────
class SymptomLog(Base):
    __tablename__ = "symptom_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Which patient logged this symptom
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    # The symptom name — free text (e.g. "chest pain", "fever", "shortness of breath")
    symptom = Column(String(500), nullable=False)

    # How long the patient has had it (e.g. "3 days", "2 weeks", "since this morning")
    duration = Column(String(255), nullable=True)

    # Severity on a scale of 1-10 (1=barely noticeable, 10=worst pain of life)
    severity = Column(Integer, nullable=False)  # 1-10

    # Free text notes (e.g. "worse when I breathe deeply", "comes and goes")
    notes = Column(Text, nullable=True)

    # When the patient submitted this log
    logged_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationship back to the patient
    patient = relationship("Patient", back_populates="symptom_logs")

    def __repr__(self):
        return f"<SymptomLog id={self.id} symptom='{self.symptom}' severity={self.severity}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: clinical_notes
# Written by the doctor after reviewing a patient
# When is_locked=True, it triggers the billing pipeline
# ─────────────────────────────────────────────────────────────────────────────
class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)

    # Which doctor wrote this note
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Which patient this note is about
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    # The actual clinical note — free text, could be long
    # Example: "Patient presents with 3-day history of productive cough, fever 38.5C.
    #           Auscultation reveals decreased breath sounds in right lower lobe.
    #           Started amoxicillin 500mg TID for 7 days."
    note_text = Column(Text, nullable=False)

    # When note is locked, billing pipeline starts automatically
    # Doctors cannot edit a locked note
    is_locked = Column(Boolean, default=False)
    locked_at = Column(DateTime, nullable=True)

    # AI-generated plain-English summary for the patient (set after note is locked)
    patient_summary = Column(Text, nullable=True)

    # AI-generated follow-up instructions for the patient
    follow_up_instructions = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    doctor = relationship("User", back_populates="clinical_notes")
    patient = relationship("Patient", back_populates="clinical_notes")
    billing_encounter = relationship("BillingEncounter", back_populates="clinical_note", uselist=False)

    def __repr__(self):
        return f"<ClinicalNote id={self.id} doctor_id={self.doctor_id} locked={self.is_locked}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: billing_encounters
# Created automatically when a ClinicalNote is locked
# Holds the billing code review workflow for one patient visit
# ─────────────────────────────────────────────────────────────────────────────
class BillingEncounter(Base):
    __tablename__ = "billing_encounters"

    id = Column(Integer, primary_key=True, index=True)

    # The locked clinical note this billing encounter is based on
    note_id = Column(Integer, ForeignKey("clinical_notes.id"), nullable=False, unique=True)

    # Workflow status:
    # 'draft'          = AI is generating suggestions
    # 'pending_review' = Suggestions ready, waiting for billing staff
    # 'approved'       = Billing staff approved the code bundle
    # 'locked'         = Final — cannot be changed
    status = Column(String(50), default="draft", nullable=False)

    # AI-parsed structured data from the note (stored as JSON)
    # Contains: {primary_diagnosis, secondary_diagnoses, procedures, drugs_supplies, visit_type}
    parsed_note_data = Column(JSON, nullable=True)

    # Denial risk assessment result (stored as JSON)
    # Contains: [{code, risk_level, reason}]
    denial_risk_flags = Column(JSON, nullable=True)

    # Audit log — every action on this encounter is recorded here
    # Format: [{timestamp, user_id, action, details}]
    audit_log = Column(JSON, default=list)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clinical_note = relationship("ClinicalNote", back_populates="billing_encounter")
    code_suggestions = relationship("CodeSuggestion", back_populates="encounter",
                                   order_by="CodeSuggestion.code_type")

    def __repr__(self):
        return f"<BillingEncounter id={self.id} note_id={self.note_id} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: code_suggestions
# Each row = one ICD-10, CPT, or HCPCS code suggested for a billing encounter
# The billing staff edits/approves these before the encounter is locked
# ─────────────────────────────────────────────────────────────────────────────
class CodeSuggestion(Base):
    __tablename__ = "code_suggestions"

    id = Column(Integer, primary_key=True, index=True)

    # Which billing encounter this code belongs to
    encounter_id = Column(Integer, ForeignKey("billing_encounters.id"), nullable=False)

    # What type of code: 'ICD10', 'CPT', or 'HCPCS'
    code_type = Column(String(20), nullable=False)

    # The actual code (e.g. "E11.9" or "99213" or "J0696")
    code = Column(String(20), nullable=False)

    # The human-readable description (e.g. "Type 2 diabetes mellitus without complications")
    description = Column(String(500), nullable=False)

    # AI confidence score 0.0 to 1.0 (e.g. 0.92 = 92% confident this is the right code)
    confidence = Column(Float, nullable=True)

    # Denial risk: 'low', 'medium', 'high'
    denial_risk = Column(String(20), default="low")

    # Reason if denial risk is medium or high
    denial_risk_reason = Column(Text, nullable=True)

    # Has the billing staff approved this specific code?
    is_approved = Column(Boolean, default=False)

    # Was this code manually added by billing staff (not AI suggested)?
    is_manual = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    encounter = relationship("BillingEncounter", back_populates="code_suggestions")

    def __repr__(self):
        return f"<CodeSuggestion {self.code_type}:{self.code} confidence={self.confidence}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: icd10_codes
# Loaded from CMS ICD-10-CM FY2026 order file
# 77,000+ diagnosis codes with descriptions
# Used for billing code suggestion and fuzzy lookup
# ─────────────────────────────────────────────────────────────────────────────
class ICD10Code(Base):
    __tablename__ = "icd10_codes"

    id = Column(Integer, primary_key=True, index=True)

    # The ICD-10-CM code (e.g. "E11.9", "J18.9", "I21.9")
    # Indexed for fast lookup
    code = Column(String(20), nullable=False, unique=True, index=True)

    # Full description (e.g. "Type 2 diabetes mellitus without complications")
    description = Column(String(500), nullable=False)

    # Short description (abbreviated version, also from CMS file)
    short_description = Column(String(200), nullable=True)

    # ICD-10 chapter category (e.g. "Endocrine, nutritional and metabolic diseases")
    category = Column(String(200), nullable=True)

    # First 3 characters = the code category (e.g. "E11" for all Type 2 diabetes)
    # Useful for grouping related conditions
    code_prefix = Column(String(5), nullable=True, index=True)

    def __repr__(self):
        return f"<ICD10Code {self.code}: {self.description[:50]}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: hcpcs_codes
# Loaded from CMS HCPCS Level II 2026 Alpha-Numeric file
# Covers: drugs (J-codes), supplies (A-codes), DME (E-codes), transport (A-codes)
# ─────────────────────────────────────────────────────────────────────────────
class HCPCSCode(Base):
    __tablename__ = "hcpcs_codes"

    id = Column(Integer, primary_key=True, index=True)

    # The HCPCS code (e.g. "J0696" for cefazolin, "E0110" for crutches)
    code = Column(String(20), nullable=False, unique=True, index=True)

    # Full description
    description = Column(String(500), nullable=False)

    # Category derived from the first letter:
    # J = drugs/biologicals, A = supplies, E = DME, B = enteral therapy, etc.
    category = Column(String(5), nullable=True, index=True)

    # When this code became effective (from the CMS quarterly file)
    effective_date = Column(String(20), nullable=True)

    # When this code was terminated (null if still active)
    termination_date = Column(String(20), nullable=True)

    def __repr__(self):
        return f"<HCPCSCode {self.code}: {self.description[:50]}>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: cpt_codes
# Loaded from CMS Medicare Physician Fee Schedule (MPFS)
# CMS's free alternative to the AMA-licensed CPT dataset
# Contains: procedure codes, CMS descriptions, RVU values, payment amounts
# ─────────────────────────────────────────────────────────────────────────────
class CPTCode(Base):
    __tablename__ = "cpt_codes"

    id = Column(Integer, primary_key=True, index=True)

    # The CPT code (e.g. "99213" for office visit, "71046" for chest X-ray 2 views)
    code = Column(String(20), nullable=False, unique=True, index=True)

    # CMS description (not AMA description — CMS descriptions are public domain)
    description = Column(String(500), nullable=False)

    # Relative Value Unit — a measure of work/complexity
    # Higher RVU = more complex procedure = higher payment
    rvu = Column(Float, nullable=True)

    # Medicare non-facility payment amount in USD
    payment_amount = Column(Float, nullable=True)

    # Code category (e.g. "Evaluation and Management", "Surgery", "Radiology")
    category = Column(String(200), nullable=True)

    def __repr__(self):
        return f"<CPTCode {self.code}: {self.description[:50]}>"


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION: create_all_tables
# Creates all tables in PostgreSQL if they don't already exist
# Safe to run multiple times — won't delete data if tables exist
# ─────────────────────────────────────────────────────────────────────────────
def create_all_tables():
    """
    FUNCTION: create_all_tables
    ---------------------------
    Reads all classes above that inherit from Base and creates the corresponding
    PostgreSQL tables. If a table already exists, it is skipped (not dropped).

    Run this ONCE to set up your database:
        python3 -c "from models.orm_models import create_all_tables; create_all_tables()"

    INPUT:  Nothing (uses engine from models/database.py)
    OUTPUT: All tables created in the medisight PostgreSQL database
    """
    print("Creating all tables in PostgreSQL...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully!")
    print("   Tables: users, patients, symptom_logs, clinical_notes,")
    print("           billing_encounters, code_suggestions,")
    print("           icd10_codes, hcpcs_codes, cpt_codes")
