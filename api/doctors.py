"""
FILE: api/doctors.py
====================
WHAT THIS FILE IS:
    All routes that only a doctor can access — viewing patient lists,
    writing clinical notes, and locking notes (which triggers billing).

ROUTES IN THIS FILE:
    GET    /doctors/patients                  → List all patients assigned to this doctor
    GET    /doctors/patients/{patient_id}     → One patient's full details + symptom history
    POST   /doctors/notes                     → Write a new clinical note for a patient
    GET    /doctors/notes/{note_id}           → View a specific note
    POST   /doctors/notes/{note_id}/lock      → Lock the note (triggers billing pipeline)
    GET    /doctors/patients/{id}/assign      → Assign a patient to this doctor

WHO CAN ACCESS:
    All routes require role='doctor'.
    A doctor can see ANY patient in the system (not just their assigned ones)
    but the patient list is filtered to assigned patients by default.

INPUT:  JWT token + JSON body for note creation
OUTPUT: Patient lists, note responses, billing trigger confirmation

HOW TO TEST:
    1. Register a doctor: POST /auth/register with role="doctor"
    2. Register a patient: POST /auth/register with role="patient"
    3. Log in as doctor, use token in Swagger /docs
    4. Try GET /doctors/patients (initially empty — need to assign)
    5. Try POST /doctors/notes with a patient_id
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from datetime import datetime

from models.database import get_db
from models.orm_models import User, Patient, SymptomLog, ClinicalNote, BillingEncounter
from models.schemas import (
    ClinicalNoteCreate, ClinicalNoteResponse, ClinicalNoteLock,
    PatientResponse, SymptomLogResponse
)
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/doctors", tags=["Doctors"])


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /doctors/patients
# Doctor views list of all their assigned patients
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/patients", response_model=List[PatientResponse])
def list_patients(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: GET /doctors/patients
    --------------------------------
    Returns all patients assigned to this doctor, with their latest symptom.

    The doctor dashboard shows:
    - Patient name and email
    - Most recent symptom and its severity
    - Last visit date (from most recent locked note)

    INPUT:  JWT token (doctor)
    OUTPUT: List of PatientResponse objects
    """
    # Find all patient profiles where assigned_doctor_id = this doctor's user ID
    patients = (
        db.query(Patient)
        .filter(Patient.assigned_doctor_id == current_user.id)
        .all()
    )

    # Build rich response for each patient
    results = []
    for patient in patients:
        # Get the user record for this patient (to get name/email)
        patient_user = db.query(User).filter(User.id == patient.user_id).first()
        if not patient_user:
            continue

        # Get their most recent symptom
        latest_log = (
            db.query(SymptomLog)
            .filter(SymptomLog.patient_id == patient.id)
            .order_by(desc(SymptomLog.logged_at))
            .first()
        )

        results.append(PatientResponse(
            id=patient.id,
            user_id=patient.user_id,
            full_name=patient_user.full_name,
            email=patient_user.email,
            date_of_birth=patient.date_of_birth,
            gender=patient.gender,
            blood_type=patient.blood_type,
            allergies=patient.allergies,
            current_medications=patient.current_medications,
            assigned_doctor_id=patient.assigned_doctor_id,
            latest_severity=latest_log.severity if latest_log else None,
            latest_symptom=latest_log.symptom if latest_log else None,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /doctors/patients/{patient_id}
# Doctor views one patient's full detail: profile + all symptoms
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/patients/{patient_id}", response_model=dict)
def get_patient_detail(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: GET /doctors/patients/{patient_id}
    ------------------------------------------
    Returns a patient's full details: demographics + all symptom logs + all notes.
    This is what the doctor sees when they click on a patient in their list.

    INPUT:  patient_id (URL path parameter), JWT token (doctor)
    OUTPUT: Dict with patient profile + symptoms + notes
    """
    # Find the patient
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    patient_user = db.query(User).filter(User.id == patient.user_id).first()

    # All symptom logs, newest first
    symptoms = (
        db.query(SymptomLog)
        .filter(SymptomLog.patient_id == patient.id)
        .order_by(desc(SymptomLog.logged_at))
        .all()
    )

    # All clinical notes for this patient (doctor can see all, locked or not)
    notes = (
        db.query(ClinicalNote)
        .filter(ClinicalNote.patient_id == patient.id)
        .order_by(desc(ClinicalNote.created_at))
        .all()
    )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient_user.full_name if patient_user else "Unknown",
            "email": patient_user.email if patient_user else "Unknown",
            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,
            "blood_type": patient.blood_type,
            "allergies": patient.allergies,
            "current_medications": patient.current_medications,
        },
        "symptoms": [
            {
                "id": s.id,
                "symptom": s.symptom,
                "severity": s.severity,
                "duration": s.duration,
                "notes": s.notes,
                "logged_at": s.logged_at.isoformat(),
            }
            for s in symptoms
        ],
        "clinical_notes": [
            {
                "id": n.id,
                "note_text": n.note_text,
                "is_locked": n.is_locked,
                "created_at": n.created_at.isoformat(),
                "locked_at": n.locked_at.isoformat() if n.locked_at else None,
            }
            for n in notes
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /doctors/patients/{patient_id}/assign
# Assign a patient to this doctor
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/patients/{patient_id}/assign")
def assign_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: POST /doctors/patients/{patient_id}/assign
    --------------------------------------------------
    Assigns a patient to this doctor.
    In a real system this would have an approval workflow.
    For the portfolio, it's a direct assignment.

    INPUT:  patient_id (URL), JWT doctor token
    OUTPUT: Confirmation message
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    patient.assigned_doctor_id = current_user.id
    db.commit()

    return {"message": f"Patient {patient_id} successfully assigned to Dr. {current_user.full_name}"}


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /doctors/notes
# Doctor writes a new clinical note for a patient
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/notes", response_model=ClinicalNoteResponse, status_code=201)
def create_note(
    note_data: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: POST /doctors/notes
    --------------------------
    Doctor writes a clinical note for a patient visit.

    Notes start as drafts (is_locked=False).
    The doctor can edit drafts freely.
    Once locked (via POST /notes/{id}/lock), the note cannot be changed
    and the billing pipeline starts automatically.

    INPUT (JSON body):
        {
          "patient_id": 1,
          "note_text": "Patient presents with 3-day fever and productive cough..."
        }

    OUTPUT: The created ClinicalNoteResponse with is_locked=False
    """
    # Verify the patient exists
    patient = db.query(Patient).filter(Patient.id == note_data.patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=404,
            detail=f"Patient {note_data.patient_id} not found"
        )

    # Create the note
    new_note = ClinicalNote(
        doctor_id=current_user.id,
        patient_id=note_data.patient_id,
        note_text=note_data.note_text,
        is_locked=False,   # Starts as a draft
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)

    print(f"✅ Clinical note created: note_id={new_note.id} for patient_id={note_data.patient_id}")
    return new_note


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: PUT /doctors/notes/{note_id}
# Doctor edits an existing (unlocked) note
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/notes/{note_id}", response_model=ClinicalNoteResponse)
def update_note(
    note_id: int,
    note_data: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: PUT /doctors/notes/{note_id}
    ------------------------------------
    Edit the text of an unlocked clinical note.
    Raises 400 if the note is already locked.

    INPUT:  note_id (URL), JSON body with updated note_text
    OUTPUT: Updated ClinicalNoteResponse
    """
    note = db.query(ClinicalNote).filter(
        ClinicalNote.id == note_id,
        ClinicalNote.doctor_id == current_user.id   # Doctor can only edit their own notes
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")

    if note.is_locked:
        raise HTTPException(
            status_code=400,
            detail="Cannot edit a locked note. Locked notes are part of the official record."
        )

    note.note_text = note_data.note_text
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)

    return note


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /doctors/notes/{note_id}/lock
# Lock the note — triggers billing pipeline creation
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/notes/{note_id}/lock", response_model=ClinicalNoteResponse)
def lock_note(
    note_id: int,
    lock_data: ClinicalNoteLock,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: POST /doctors/notes/{note_id}/lock
    ------------------------------------------
    IMPORTANT: This is the most critical route in the doctor workflow.

    When a doctor locks a note:
    1. Note becomes immutable (is_locked=True)
    2. A BillingEncounter is created in 'draft' status
    3. (Day 2 addition) The billing AI pipeline runs in the background
       to suggest ICD-10/CPT/HCPCS codes

    The doctor cannot lock an already-locked note.

    INPUT:
        note_id (URL path)
        JSON body: { "follow_up_instructions": "Return in 2 weeks if symptoms persist" }

    OUTPUT: The locked ClinicalNoteResponse
    """
    # Find the note — must belong to this doctor
    note = db.query(ClinicalNote).filter(
        ClinicalNote.id == note_id,
        ClinicalNote.doctor_id == current_user.id
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")

    if note.is_locked:
        raise HTTPException(
            status_code=400,
            detail="This note is already locked."
        )

    # Lock the note
    note.is_locked = True
    note.locked_at = datetime.utcnow()
    note.updated_at = datetime.utcnow()

    if lock_data.follow_up_instructions:
        note.follow_up_instructions = lock_data.follow_up_instructions

    # Create the billing encounter in 'draft' status
    # The billing AI pipeline will populate it with code suggestions
    billing_encounter = BillingEncounter(
        note_id=note.id,
        status="draft",
        audit_log=[{
            "timestamp": datetime.utcnow().isoformat(),
            "action": "encounter_created",
            "triggered_by": f"doctor_id={current_user.id}",
            "details": "Billing encounter created when doctor locked clinical note"
        }]
    )
    db.add(billing_encounter)
    db.commit()
    db.refresh(note)
    db.refresh(billing_encounter)

    print(f"✅ Note locked: note_id={note_id}")
    print(f"   Billing encounter created: encounter_id={billing_encounter.id}")
    print(f"   Status: draft (billing AI will process this)")

    # TODO (Day 2): Add background task to run billing AI pipeline
    # background_tasks.add_task(run_billing_pipeline, billing_encounter.id)

    return note
