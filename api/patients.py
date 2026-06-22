"""
FILE: api/patients.py
=====================
WHAT THIS FILE IS:
    All routes related to patients — logging symptoms, viewing their timeline,
    and updating their profile.

ROUTES IN THIS FILE:
    POST   /patients/symptoms             → Patient logs a new symptom
    GET    /patients/symptoms             → Patient views all their symptoms
    GET    /patients/timeline             → Patient views full chronological timeline
    PUT    /patients/profile              → Patient updates their profile (DOB, allergies, etc.)
    GET    /patients/profile              → Patient views their profile

    (Doctor-facing patient routes are in api/doctors.py)

WHO CAN ACCESS:
    All routes require role='patient' except where noted.
    The patient can ONLY see their OWN data — enforced by using
    current_user.id to look up their patient profile.

INPUT:  JWT token (Authorization header) + JSON body where applicable
OUTPUT: JSON response with symptom/timeline data

HOW TO TEST:
    1. Register a patient: POST /auth/register with role="patient"
    2. Copy the token from response
    3. In Swagger UI (/docs): click "Authorize", paste: Bearer <token>
    4. Try POST /patients/symptoms
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from datetime import datetime

from models.database import get_db
from models.orm_models import User, Patient, SymptomLog, ClinicalNote, BillingEncounter
from models.schemas import (
    SymptomLogCreate, SymptomLogResponse,
    PatientCreate, PatientResponse,
    TimelineEvent
)
from api.auth import get_current_user, require_role

# All routes here start with /patients
router = APIRouter(prefix="/patients", tags=["Patients"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: get patient profile or raise 404
# ─────────────────────────────────────────────────────────────────────────────
def get_patient_profile(user: User, db: Session) -> Patient:
    """
    Helper to fetch the Patient profile row for a logged-in user.
    Used in every patient route to avoid code repetition.

    INPUT:  User ORM object, database session
    OUTPUT: Patient ORM object
            OR raises 404 if patient profile doesn't exist
    """
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found. Please contact support.",
        )
    return patient


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /patients/symptoms
# Patient logs a new symptom
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/symptoms", response_model=SymptomLogResponse, status_code=201)
def log_symptom(
    symptom_data: SymptomLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("patient"))  # Only patients can log symptoms
):
    """
    ROUTE: POST /patients/symptoms
    --------------------------------
    A patient logs a new symptom.

    The frontend sends:
        {
          "symptom": "chest pain",
          "severity": 7,
          "duration": "2 days",
          "notes": "Worse when I breathe deeply"
        }

    The server:
    1. Finds the patient's profile (using their JWT user_id)
    2. Creates a SymptomLog row in the database
    3. Returns the created log with its ID and timestamp

    INPUT (JSON body): SymptomLogCreate schema
    OUTPUT: SymptomLogResponse (the saved symptom with ID and logged_at)
    """
    # Get the patient profile associated with this logged-in user
    patient = get_patient_profile(current_user, db)

    # Create the symptom log row
    new_log = SymptomLog(
        patient_id=patient.id,
        symptom=symptom_data.symptom,
        severity=symptom_data.severity,
        duration=symptom_data.duration,
        notes=symptom_data.notes,
        logged_at=datetime.utcnow(),
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    print(f"✅ Symptom logged: '{new_log.symptom}' severity={new_log.severity} "
          f"for patient_id={patient.id}")

    return new_log


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /patients/symptoms
# Patient sees all their symptom logs (newest first)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/symptoms", response_model=List[SymptomLogResponse])
def get_symptoms(
    limit: int = 50,      # How many to return (default: last 50)
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("patient"))
):
    """
    ROUTE: GET /patients/symptoms
    --------------------------------
    Returns all symptom logs for the logged-in patient, newest first.

    Query params:
        ?limit=50  (how many to return, default 50, max 200)

    INPUT:  JWT token
    OUTPUT: List of SymptomLogResponse objects
    """
    patient = get_patient_profile(current_user, db)

    # Clamp limit between 1 and 200 for safety
    limit = max(1, min(limit, 200))

    logs = (
        db.query(SymptomLog)
        .filter(SymptomLog.patient_id == patient.id)
        .order_by(desc(SymptomLog.logged_at))  # Newest first
        .limit(limit)
        .all()
    )
    return logs


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /patients/timeline
# Full chronological timeline: symptoms + notes + billing events merged
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/timeline", response_model=List[TimelineEvent])
def get_timeline(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("patient"))
):
    """
    ROUTE: GET /patients/timeline
    --------------------------------
    Returns a unified chronological timeline for the patient:
    - Each symptom log becomes a "symptom" event
    - Each locked clinical note becomes a "clinical_note" event
    - Each approved billing encounter becomes a "billing_approved" event

    The frontend renders these as a scrollable timeline feed.

    INPUT:  JWT token
    OUTPUT: List of TimelineEvent objects, sorted newest to oldest
    """
    patient = get_patient_profile(current_user, db)

    timeline_events = []

    # ── Symptom events ────────────────────────────────────────────────────────
    symptoms = (
        db.query(SymptomLog)
        .filter(SymptomLog.patient_id == patient.id)
        .all()
    )
    for s in symptoms:
        timeline_events.append(TimelineEvent(
            event_type="symptom",
            timestamp=s.logged_at,
            title=f"Symptom logged: {s.symptom}",
            detail=s.notes,
            severity=s.severity,
            metadata={"duration": s.duration},
        ))

    # ── Clinical note events (locked notes only — drafts not visible to patient) ──
    notes = (
        db.query(ClinicalNote)
        .filter(
            ClinicalNote.patient_id == patient.id,
            ClinicalNote.is_locked == True,  # noqa: E712
        )
        .all()
    )
    for n in notes:
        timeline_events.append(TimelineEvent(
            event_type="clinical_note",
            timestamp=n.locked_at or n.created_at,
            title="Doctor's visit note",
            # Show the patient-friendly summary, NOT the raw clinical text
            detail=n.patient_summary or "Your doctor recorded a note from your visit.",
            severity=None,
            metadata={
                "follow_up": n.follow_up_instructions,
                "doctor_id": n.doctor_id,
            },
        ))

    # ── Billing events (approved encounters only) ─────────────────────────────
    billing = (
        db.query(BillingEncounter)
        .join(ClinicalNote, BillingEncounter.note_id == ClinicalNote.id)
        .filter(
            ClinicalNote.patient_id == patient.id,
            BillingEncounter.status.in_(["approved", "locked"]),
        )
        .all()
    )
    for b in billing:
        # Count how many codes were approved
        approved_code_count = len([
            cs for cs in b.code_suggestions if cs.is_approved
        ])
        timeline_events.append(TimelineEvent(
            event_type="billing_approved",
            timestamp=b.updated_at,
            title="Visit billing finalized",
            detail=f"{approved_code_count} billing codes were approved for your visit.",
            severity=None,
            metadata={"encounter_id": b.id, "status": b.status},
        ))

    # Sort all events by timestamp, newest first
    timeline_events.sort(key=lambda e: e.timestamp, reverse=True)
    return timeline_events


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /patients/profile
# Patient views their own profile
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/profile", response_model=PatientResponse)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("patient"))
):
    """
    ROUTE: GET /patients/profile
    --------------------------------
    Returns the current patient's full profile including latest symptom info.

    INPUT:  JWT token
    OUTPUT: PatientResponse with demographics and latest symptom
    """
    patient = get_patient_profile(current_user, db)

    # Get the most recent symptom for display
    latest_log = (
        db.query(SymptomLog)
        .filter(SymptomLog.patient_id == patient.id)
        .order_by(desc(SymptomLog.logged_at))
        .first()
    )

    # Build a rich response combining Patient + User data
    return PatientResponse(
        id=patient.id,
        user_id=patient.user_id,
        full_name=current_user.full_name,
        email=current_user.email,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        blood_type=patient.blood_type,
        allergies=patient.allergies,
        current_medications=patient.current_medications,
        assigned_doctor_id=patient.assigned_doctor_id,
        latest_severity=latest_log.severity if latest_log else None,
        latest_symptom=latest_log.symptom if latest_log else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: PUT /patients/profile
# Patient updates their own profile (DOB, allergies, medications)
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/profile", response_model=PatientResponse)
def update_profile(
    profile_data: PatientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("patient"))
):
    """
    ROUTE: PUT /patients/profile
    --------------------------------
    Patient updates their demographic information.

    INPUT (JSON body):
        {
          "date_of_birth": "1990-05-15",
          "gender": "Female",
          "blood_type": "O+",
          "allergies": "Penicillin, Sulfa drugs",
          "current_medications": ["Metformin 500mg", "Lisinopril 10mg"]
        }

    OUTPUT: Updated PatientResponse
    """
    patient = get_patient_profile(current_user, db)

    # Update only the fields that were provided
    if profile_data.date_of_birth is not None:
        patient.date_of_birth = profile_data.date_of_birth
    if profile_data.gender is not None:
        patient.gender = profile_data.gender
    if profile_data.blood_type is not None:
        patient.blood_type = profile_data.blood_type
    if profile_data.allergies is not None:
        patient.allergies = profile_data.allergies
    if profile_data.current_medications is not None:
        patient.current_medications = profile_data.current_medications

    db.commit()
    db.refresh(patient)

    print(f"✅ Profile updated for patient_id={patient.id}")

    return PatientResponse(
        id=patient.id,
        user_id=patient.user_id,
        full_name=current_user.full_name,
        email=current_user.email,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        blood_type=patient.blood_type,
        allergies=patient.allergies,
        current_medications=patient.current_medications,
        assigned_doctor_id=patient.assigned_doctor_id,
    )
