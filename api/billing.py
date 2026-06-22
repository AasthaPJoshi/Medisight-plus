"""
FILE: api/billing.py
====================
WHAT THIS FILE IS:
    All billing-related routes. This is the core of MediSight+'s unique value
    over a standard clinical AI — the claims intelligence layer.

ROUTES IN THIS FILE:
    GET  /billing/lookup/icd10          → Search ICD-10-CM codes by keyword
    GET  /billing/lookup/hcpcs          → Search HCPCS Level II codes by keyword
    GET  /billing/lookup/cpt            → Search CPT/MPFS codes by keyword
    GET  /billing/encounters            → List all billing encounters (billing staff)
    GET  /billing/encounters/{id}       → Get one encounter with all code suggestions
    POST /billing/encounters/{id}/approve → Billing staff approves/edits code bundle

CONCEPT — The billing workflow:
    1. Doctor writes + locks a clinical note
    2. BillingEncounter is created automatically (doctors.py does this)
    3. (Day 2) AI billing pipeline suggests ICD-10/CPT/HCPCS codes
    4. Billing staff reviews suggestions in the BillingDashboard
    5. Staff approves / edits / removes codes
    6. Encounter is locked — ready for claim submission

WHO CAN ACCESS:
    Lookup routes: any authenticated user (doctors need them for verification)
    Encounter routes: role='billing' or role='doctor'

HOW BILLING CODE LOOKUP WORKS:
    We use PostgreSQL's pg_trgm extension for fuzzy text matching.
    "chest pain" will match "acute chest pain" and "chest pain unspecified"
    even without exact keyword matching.

    SQL equivalent:
    SELECT code, description FROM icd10_codes
    WHERE similarity(description, 'chest pain') > 0.15
    ORDER BY similarity(description, 'chest pain') DESC LIMIT 10;
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text, desc
from typing import List, Optional
from datetime import datetime

from models.database import get_db
from models.orm_models import (
    User, ICD10Code, HCPCSCode, CPTCode,
    BillingEncounter, CodeSuggestion, ClinicalNote
)
from models.schemas import (
    ICD10LookupResult, HCPCSLookupResult, CPTLookupResult,
    BillingEncounterResponse, CodeApprovalRequest, CodeSuggestionResponse
)
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/billing", tags=["Billing"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Check if pg_trgm extension is enabled
# ─────────────────────────────────────────────────────────────────────────────
def ensure_trigram_extension(db: Session):
    """
    pg_trgm is a PostgreSQL extension for fuzzy text search.
    We need it for billing code lookup.
    This is safe to call multiple times — it won't reinstall.
    """
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        db.commit()
    except Exception:
        db.rollback()  # Might fail if no permissions, that's OK


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /billing/lookup/icd10
# Search ICD-10-CM codes by keyword
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/lookup/icd10", response_model=List[ICD10LookupResult])
def lookup_icd10(
    query: str = Query(..., min_length=2, description="Search term, e.g. 'diabetes' or 'chest pain'"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Any authenticated user
):
    """
    ROUTE: GET /billing/lookup/icd10?query=chest+pain&limit=10
    -----------------------------------------------------------
    Search the locally-loaded ICD-10-CM table for matching diagnosis codes.

    How the search works:
    1. First tries exact prefix match (e.g. "E11" returns all E11.* codes)
    2. Then fuzzy text match on description using ILIKE (case-insensitive LIKE)
    3. Returns up to 'limit' results

    NOTE: In Day 1 before we load the CMS files, this will return 0 results.
    After running billing/ingest_codes.py, it will return real codes.

    INPUT:  ?query=chest+pain
    OUTPUT: [{"code": "R07.9", "description": "Chest pain, unspecified", ...}, ...]

    EXAMPLE CURL:
        curl "http://localhost:8000/billing/lookup/icd10?query=diabetes" \
          -H "Authorization: Bearer <your_token>"
    """
    search_term = query.strip().upper()

    # Strategy 1: If query looks like a code prefix (e.g. "E11", "J18")
    # return codes that start with that prefix
    if len(search_term) <= 6 and search_term.replace(".", "").isalnum():
        prefix_results = (
            db.query(ICD10Code)
            .filter(ICD10Code.code.like(f"{search_term}%"))
            .order_by(ICD10Code.code)
            .limit(limit)
            .all()
        )
        if prefix_results:
            return prefix_results

    # Strategy 2: Fuzzy description search using ILIKE
    search_lower = f"%{query.lower()}%"
    results = (
        db.query(ICD10Code)
        .filter(ICD10Code.description.ilike(search_lower))
        .order_by(ICD10Code.code)
        .limit(limit)
        .all()
    )

    if not results:
        print(f"⚠️  No ICD-10 codes found for query: '{query}'")
        print("   Make sure billing/ingest_codes.py has been run to load CMS data.")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /billing/lookup/hcpcs
# Search HCPCS Level II codes by keyword
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/lookup/hcpcs", response_model=List[HCPCSLookupResult])
def lookup_hcpcs(
    query: str = Query(..., min_length=2, description="Search term, e.g. 'insulin' or 'crutches'"),
    category: Optional[str] = Query(None, description="Filter by category: J (drugs), A (supplies), E (DME)"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    ROUTE: GET /billing/lookup/hcpcs?query=insulin&category=J
    ----------------------------------------------------------
    Search HCPCS Level II codes for drugs, supplies, and equipment.

    Category filter:
    - J = Drug codes (e.g. J0696 = cefazolin, J1815 = insulin)
    - A = Supplies and transport (e.g. A4253 = glucose test strips)
    - E = Durable Medical Equipment (e.g. E0110 = crutches)
    - B = Enteral therapy

    INPUT:  ?query=insulin&category=J
    OUTPUT: [{"code": "J1815", "description": "Injection, insulin", ...}, ...]
    """
    query_obj = db.query(HCPCSCode).filter(
        HCPCSCode.description.ilike(f"%{query.lower()}%")
    )

    # Apply category filter if provided
    if category:
        query_obj = query_obj.filter(
            HCPCSCode.category == category.upper()
        )

    # Only return currently active codes (no termination date)
    query_obj = query_obj.filter(
        (HCPCSCode.termination_date == None) |  # noqa: E711
        (HCPCSCode.termination_date == "")
    )

    results = query_obj.order_by(HCPCSCode.code).limit(limit).all()

    if not results:
        print(f"⚠️  No HCPCS codes found for query: '{query}'")
        print("   Make sure billing/ingest_codes.py has been run to load CMS data.")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /billing/lookup/cpt
# Search CPT/MPFS codes by keyword
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/lookup/cpt", response_model=List[CPTLookupResult])
def lookup_cpt(
    query: str = Query(..., min_length=2, description="Search term, e.g. 'office visit' or 'chest x-ray'"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    ROUTE: GET /billing/lookup/cpt?query=office+visit
    ---------------------------------------------------
    Search CPT codes from the CMS Medicare Physician Fee Schedule.

    NOTE: These are CMS descriptions (public domain), NOT AMA descriptions.
    The AMA owns CPT descriptions and charges for a license.
    CMS's MPFS descriptions are free and cover all commonly used codes.

    INPUT:  ?query=office+visit
    OUTPUT: [{"code": "99213", "description": "Office/outpatient visit est", "rvu": 1.3, ...}, ...]
    """
    results = (
        db.query(CPTCode)
        .filter(CPTCode.description.ilike(f"%{query.lower()}%"))
        .order_by(CPTCode.code)
        .limit(limit)
        .all()
    )

    if not results:
        print(f"⚠️  No CPT codes found for query: '{query}'")
        print("   Make sure billing/ingest_codes.py has been run to load CMS data.")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /billing/encounters
# List all billing encounters (billing staff view)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/encounters", response_model=List[dict])
def list_encounters(
    status_filter: Optional[str] = Query(None,
                                         description="Filter by status: draft, pending_review, approved, locked"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("billing", "doctor"))
):
    """
    ROUTE: GET /billing/encounters?status_filter=pending_review
    ------------------------------------------------------------
    Returns all billing encounters, optionally filtered by status.
    Used by the billing dashboard to show the work queue.

    Typical billing workflow:
    - status='pending_review' = AI has suggested codes, waiting for human review
    - status='draft' = AI is still generating (or something went wrong)

    INPUT:  JWT (billing or doctor role), optional ?status_filter
    OUTPUT: List of encounter summaries
    """
    query_obj = db.query(BillingEncounter)

    if status_filter:
        query_obj = query_obj.filter(BillingEncounter.status == status_filter)

    encounters = query_obj.order_by(desc(BillingEncounter.created_at)).all()

    # Build summary for each encounter
    results = []
    for enc in encounters:
        # Get the clinical note to get patient context
        note = db.query(ClinicalNote).filter(ClinicalNote.id == enc.note_id).first()
        approved_count = len([cs for cs in enc.code_suggestions if cs.is_approved])
        total_count = len(enc.code_suggestions)

        results.append({
            "id": enc.id,
            "note_id": enc.note_id,
            "status": enc.status,
            "patient_id": note.patient_id if note else None,
            "doctor_id": note.doctor_id if note else None,
            "total_code_suggestions": total_count,
            "approved_codes": approved_count,
            "has_high_risk_flags": any(
                cs.denial_risk == "high" for cs in enc.code_suggestions
            ),
            "created_at": enc.created_at.isoformat(),
            "updated_at": enc.updated_at.isoformat() if enc.updated_at else None,
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /billing/encounters/{encounter_id}
# Full encounter detail with all code suggestions
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/encounters/{encounter_id}", response_model=BillingEncounterResponse)
def get_encounter(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("billing", "doctor"))
):
    """
    ROUTE: GET /billing/encounters/{encounter_id}
    -----------------------------------------------
    Returns a full billing encounter including all code suggestions
    with their confidence scores and denial risk flags.

    This is what the billing dashboard shows when staff opens an encounter.

    INPUT:  encounter_id (URL path), JWT (billing or doctor)
    OUTPUT: BillingEncounterResponse with nested code_suggestions list
    """
    encounter = db.query(BillingEncounter).filter(
        BillingEncounter.id == encounter_id
    ).first()

    if not encounter:
        raise HTTPException(
            status_code=404,
            detail=f"Billing encounter {encounter_id} not found"
        )

    return encounter


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /billing/encounters/{encounter_id}/approve
# Billing staff reviews and approves the code bundle
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/encounters/{encounter_id}/approve")
def approve_encounter(
    encounter_id: int,
    approval: CodeApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("billing"))
):
    """
    ROUTE: POST /billing/encounters/{encounter_id}/approve
    -------------------------------------------------------
    HUMAN-IN-THE-LOOP: Billing staff reviews AI code suggestions and approves them.

    This route:
    1. Marks specified code suggestions as approved
    2. Removes codes the staff wants to remove
    3. Adds any manual codes the staff wants to add
    4. Sets encounter status to 'approved'
    5. Appends to audit log (who approved, when, what was changed)

    INPUT (JSON body):
        {
          "approved_ids": [1, 2, 3],          <- IDs of CodeSuggestion rows to approve
          "remove_ids": [4],                   <- IDs of CodeSuggestion rows to remove
          "manual_codes": [                    <- Codes to add manually
            {
              "code_type": "ICD10",
              "code": "J18.9",
              "description": "Pneumonia, unspecified"
            }
          ]
        }

    OUTPUT: Confirmation with final approved code bundle
    """
    encounter = db.query(BillingEncounter).filter(
        BillingEncounter.id == encounter_id
    ).first()

    if not encounter:
        raise HTTPException(status_code=404, detail=f"Encounter {encounter_id} not found")

    if encounter.status == "locked":
        raise HTTPException(
            status_code=400,
            detail="This encounter is locked and cannot be modified."
        )

    # ── Step 1: Mark requested codes as approved ──────────────────────────────
    for code_id in approval.approved_ids:
        code = db.query(CodeSuggestion).filter(
            CodeSuggestion.id == code_id,
            CodeSuggestion.encounter_id == encounter_id
        ).first()
        if code:
            code.is_approved = True

    # ── Step 2: Remove rejected codes ─────────────────────────────────────────
    if approval.remove_ids:
        for code_id in approval.remove_ids:
            code = db.query(CodeSuggestion).filter(
                CodeSuggestion.id == code_id,
                CodeSuggestion.encounter_id == encounter_id
            ).first()
            if code:
                db.delete(code)

    # ── Step 3: Add manual codes ───────────────────────────────────────────────
    if approval.manual_codes:
        for manual in approval.manual_codes:
            new_code = CodeSuggestion(
                encounter_id=encounter_id,
                code_type=manual.get("code_type", "ICD10"),
                code=manual.get("code", ""),
                description=manual.get("description", ""),
                confidence=1.0,   # Manual codes are assumed correct
                denial_risk="low",
                is_approved=True,
                is_manual=True,
            )
            db.add(new_code)

    # ── Step 4: Update encounter status ───────────────────────────────────────
    encounter.status = "approved"
    encounter.updated_at = datetime.utcnow()

    # ── Step 5: Append to audit log ───────────────────────────────────────────
    audit_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": "codes_approved",
        "approved_by": f"user_id={current_user.id} ({current_user.email})",
        "approved_count": len(approval.approved_ids),
        "removed_count": len(approval.remove_ids or []),
        "manual_added_count": len(approval.manual_codes or []),
    }
    # Audit log is a JSON list — append to it
    current_log = encounter.audit_log or []
    current_log.append(audit_entry)
    encounter.audit_log = current_log

    db.commit()

    # Get the final approved codes for the response
    approved_codes = db.query(CodeSuggestion).filter(
        CodeSuggestion.encounter_id == encounter_id,
        CodeSuggestion.is_approved == True  # noqa: E712
    ).all()

    print(f"✅ Encounter {encounter_id} approved by {current_user.email}")
    print(f"   Final approved codes: {len(approved_codes)}")

    return {
        "message": "Billing encounter approved successfully",
        "encounter_id": encounter_id,
        "status": "approved",
        "approved_codes": [
            {
                "code_type": c.code_type,
                "code": c.code,
                "description": c.description,
                "is_manual": c.is_manual,
            }
            for c in approved_codes
        ],
        "audit_entry": audit_entry,
    }
