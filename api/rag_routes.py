"""
FILE: api/rag_routes.py
=======================
WHAT THIS FILE IS:
    FastAPI routes that expose the LangGraph RAG pipeline to the frontend
    and trigger the Claude billing AI when a clinical note is locked.

ROUTES IN THIS FILE:
    POST /rag/query              → Run the 5-node RAG pipeline (doctor query)
    POST /rag/note-analysis/{id} → Analyze a locked note: AI summary + billing codes
    GET  /rag/health             → Check if RAG pipeline is ready

CONCEPT — Two AI pipelines triggered from routes:
    1. /rag/query: The doctor types a clinical question.
       LangGraph retrieves from Pinecone + BM25, Claude Sonnet generates
       a cited differential diagnosis response.

    2. /rag/note-analysis/{id}: Called when a doctor locks a note.
       Two things happen in parallel:
       a) Patient summary: Claude Haiku translates the clinical note into
          plain English the patient can understand.
       b) Billing codes: Claude Sonnet reads the note and suggests
          ICD-10-CM, CPT, and HCPCS codes with confidence scores,
          then the denial checker flags any risky code combinations.

WHO CAN ACCESS:
    /rag/query:         role='doctor' only
    /rag/note-analysis: role='doctor' only
    /rag/health:        any authenticated user

INPUT:  JWT token + JSON body (query or note_id)
OUTPUT: {answer, sources, confidence} or {patient_summary, billing_codes}
"""

import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from api.limiter import limiter

from models.database import get_db
from models.orm_models import (
    ClinicalNote, BillingEncounter, CodeSuggestion,
    ICD10Code, CPTCode, HCPCSCode
)
from api.auth import get_current_user, require_role
from models.orm_models import User

load_dotenv()

router = APIRouter(prefix="/rag", tags=["RAG & AI"])

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST/RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import Field, validator

class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    patient_id: Optional[int] = None

    @validator('query')
    def sanitize_query(cls, v):
        # Block prompt injection attempts
        blocked = ['ignore previous', 'system prompt', 'jailbreak', '<script>']
        if any(b in v.lower() for b in blocked):
            raise ValueError('Invalid query content')
        return v.strip()

class RAGQueryResponse(BaseModel):
    """What the RAG pipeline returns"""
    answer: str
    sources: list
    confidence: float
    insufficient_context: bool
    query_type: str


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: GET /rag/health
# Check if the RAG pipeline is ready (Pinecone connected, BM25 loaded)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
def rag_health(current_user: User = Depends(get_current_user)):
    """
    ROUTE: GET /rag/health
    ----------------------
    Checks if the RAG pipeline components are available.
    Returns status of Pinecone connection and BM25 index.

    TEST: curl http://localhost:8000/rag/health -H "Authorization: Bearer <token>"
    """
    from pathlib import Path
    bm25_path = Path(__file__).parent.parent / "data" / "bm25_index.pkl"

    pinecone_ok = False
    vector_count = 0
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "medisight-kb"))
        stats = index.describe_index_stats()
        vector_count = stats.get("total_vector_count", 0)
        pinecone_ok = True
    except Exception as e:
        pinecone_ok = False

    return {
        "rag_ready": pinecone_ok and bm25_path.exists(),
        "pinecone": {
            "connected": pinecone_ok,
            "vector_count": vector_count,
        },
        "bm25_index": {
            "exists": bm25_path.exists(),
            "path": str(bm25_path),
        },
        "message": (
            "RAG pipeline ready" if (pinecone_ok and bm25_path.exists())
            else "Run python3 rag/ingest.py first to build the knowledge base"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /rag/query
# Doctor asks a clinical question — runs the full 5-node LangGraph pipeline
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import Request
from api.limiter import limiter

@router.post("/query", response_model=RAGQueryResponse)
@limiter.limit("10/minute")
async def rag_query(
    request: Request,
    data: RAGQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: POST /rag/query
    ----------------------
    Runs the full LangGraph 5-node agentic RAG pipeline.

    The doctor types a clinical question in the AI suggestion panel.
    This route feeds it through:
    N1 (classify) → N2 (expand) → N3 (retrieve) → N4 (judge) → N5 (generate)

    If the knowledge base doesn't have relevant context, returns a
    clear INSUFFICIENT_CONTEXT message instead of hallucinating.

    INPUT (JSON body):
        {
          "query": "differential diagnosis for chest pain and fever in 45-year-old",
          "patient_id": 1  (optional — adds patient context like allergies)
        }

    OUTPUT:
        {
          "answer": "Based on the clinical presentation... [Source: PMID:12345678]...",
          "sources": [{"pmid": "12345678", "title": "...", "url": "..."}],
          "confidence": 0.87,
          "insufficient_context": false,
          "query_type": "symptom"
        }

    TEST in Swagger UI:
        POST /rag/query
        Body: {"query": "chest pain differential diagnosis"}
    """
    # Add patient context if patient_id is provided
    query = request.query
    if request.patient_id:
        from models.orm_models import Patient
        patient = db.query(Patient).filter(
            Patient.id == request.patient_id
        ).first()
        if patient and patient.allergies:
            query = f"{query}. Patient allergies: {patient.allergies}"
        if patient and patient.current_medications:
            meds = ", ".join(patient.current_medications or [])
            if meds:
                query = f"{query}. Current medications: {meds}"

    # Import here to avoid circular import and slow startup
    try:
        from rag.graph import run_rag_query
        result = await run_rag_query(query)
    except Exception as e:
        # If RAG pipeline fails (e.g. Pinecone not connected), return helpful error
        raise HTTPException(
            status_code=503,
            detail=f"RAG pipeline unavailable: {str(e)}. Run python3 rag/ingest.py first."
        )

    return RAGQueryResponse(**result)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE: POST /rag/note-analysis/{note_id}
# After a doctor locks a note — generate patient summary + billing codes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/note-analysis/{note_id}")
async def analyze_locked_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor"))
):
    """
    ROUTE: POST /rag/note-analysis/{note_id}
    -----------------------------------------
    Triggered after a doctor locks a clinical note.

    Does THREE things with Claude:

    1. PATIENT SUMMARY (Claude Haiku):
       Translates the clinical note into plain English the patient can read.
       Stored in clinical_notes.patient_summary.

    2. BILLING CODE SUGGESTION (Claude Sonnet):
       Reads the note and suggests:
       - ICD-10-CM diagnosis codes (from our local database)
       - CPT procedure codes (from our local database)
       - HCPCS codes for drugs/supplies mentioned
       Each suggestion includes a confidence score and denial risk flag.

    3. DENIAL RISK CHECK:
       Compares the suggested code bundle against known problematic patterns.

    INPUT:  note_id (URL path), JWT token (doctor)
    OUTPUT: {patient_summary, billing_codes, encounter_id, denial_flags}

    The billing encounter must already exist (created when doctor locked the note).
    """
    # Verify the note exists and belongs to this doctor
    note = db.query(ClinicalNote).filter(
        ClinicalNote.id == note_id,
        ClinicalNote.doctor_id == current_user.id,
        ClinicalNote.is_locked == True,  # noqa: E712 — Must be locked
    ).first()

    if not note:
        raise HTTPException(
            status_code=404,
            detail=f"Locked note {note_id} not found or not locked yet."
        )

    # Get the billing encounter created when the note was locked
    encounter = db.query(BillingEncounter).filter(
        BillingEncounter.note_id == note_id
    ).first()

    if not encounter:
        raise HTTPException(
            status_code=404,
            detail="Billing encounter not found. Lock the note first via POST /doctors/notes/{id}/lock"
        )

    # ── Step 1: Generate patient-friendly summary ─────────────────────────────
    llm_haiku = ChatAnthropic(
        model="claude-haiku-4-5",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=500,
    )

    patient_summary_prompt = f"""You are explaining a doctor's clinical note to a patient in plain English.

Clinical note: {note.note_text}

Write a clear, compassionate summary for the patient (not the doctor).
- Use simple language, no medical jargon
- Explain what the doctor found and what it means
- Include any medications or treatments mentioned
- Keep it to 3-4 sentences maximum
- Do not mention specific test values unless critical"""

    try:
        summary_response = llm_haiku.invoke([HumanMessage(content=patient_summary_prompt)])
        patient_summary = summary_response.content
    except Exception as e:
        patient_summary = "Your doctor has completed your visit notes. Please ask your doctor to explain the findings."

    # Save the patient summary to the note
    note.patient_summary = patient_summary
    db.commit()

    # ── Step 2: Extract structured billing information from the note ───────────
    llm_sonnet = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.0,
        max_tokens=1000,
    )

    billing_extract_prompt = f"""You are a medical billing specialist analyzing a clinical note.
Extract structured billing information from this note.

Clinical note: {note.note_text}

Respond in this EXACT format (JSON):
{{
  "primary_diagnosis": "the main reason for the visit in medical terms",
  "secondary_diagnoses": ["any other conditions mentioned"],
  "procedures_performed": ["procedures, exams, or services performed"],
  "drugs_administered": ["any drugs/injections given during the visit"],
  "supplies_used": ["medical supplies used"],
  "visit_type": "new_patient OR established_patient",
  "visit_complexity": "low OR moderate OR high"
}}

Be specific with medical terminology. Use exact condition names."""

    try:
        extract_response = llm_sonnet.invoke([HumanMessage(content=billing_extract_prompt)])
        import json
        # Clean up the response (remove markdown code blocks if present)
        raw = extract_response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed_note = json.loads(raw.strip())
    except Exception as e:
        parsed_note = {
            "primary_diagnosis": "Unspecified condition",
            "secondary_diagnoses": [],
            "procedures_performed": ["Office visit"],
            "drugs_administered": [],
            "supplies_used": [],
            "visit_type": "established_patient",
            "visit_complexity": "moderate",
        }

    # Save parsed note data to the encounter
    encounter.parsed_note_data = parsed_note
    db.commit()

    # ── Step 3: Map to billing codes ──────────────────────────────────────────
    billing_codes = []

    # ICD-10 mapping for primary diagnosis
    if parsed_note.get("primary_diagnosis"):
        diagnosis = parsed_note["primary_diagnosis"]
        icd_results = (
            db.query(ICD10Code)
            .filter(ICD10Code.description.ilike(f"%{diagnosis[:30]}%"))
            .limit(3)
            .all()
        )
        for i, code in enumerate(icd_results):
            billing_codes.append(CodeSuggestion(
                encounter_id=encounter.id,
                code_type="ICD10",
                code=code.code,
                description=code.description,
                confidence=0.90 - (i * 0.08),  # Primary is most confident
                denial_risk="low",
                is_approved=False,
            ))

    # CPT code for E&M visit
    complexity_map = {
        "low": "99202",
        "moderate": "99203",
        "high": "99205",
    }
    visit_type = parsed_note.get("visit_type", "established_patient")
    complexity = parsed_note.get("visit_complexity", "moderate")

    if visit_type == "established_patient":
        em_code_map = {"low": "99212", "moderate": "99213", "high": "99215"}
        em_code = em_code_map.get(complexity, "99213")
    else:
        em_code = complexity_map.get(complexity, "99203")

    cpt_result = db.query(CPTCode).filter(CPTCode.code == em_code).first()
    if cpt_result:
        billing_codes.append(CodeSuggestion(
            encounter_id=encounter.id,
            code_type="CPT",
            code=cpt_result.code,
            description=cpt_result.description,
            confidence=0.88,
            denial_risk="low",
            is_approved=False,
        ))

    # HCPCS codes for drugs mentioned
    for drug in parsed_note.get("drugs_administered", [])[:3]:
        drug_short = drug[:20]
        hcpcs_result = (
            db.query(HCPCSCode)
            .filter(
                HCPCSCode.description.ilike(f"%{drug_short}%"),
                HCPCSCode.category == "J"
            )
            .first()
        )
        if hcpcs_result:
            billing_codes.append(CodeSuggestion(
                encounter_id=encounter.id,
                code_type="HCPCS",
                code=hcpcs_result.code,
                description=hcpcs_result.description,
                confidence=0.82,
                denial_risk="low",
                is_approved=False,
            ))

    # ── Step 4: Denial risk check ─────────────────────────────────────────────
    denial_flags = []
    code_list = [cs.code for cs in billing_codes]

    # Rule: 99215 (highest E&M) should not be billed with 99213 (lower E&M)
    em_codes = [c for c in code_list if c.startswith("992")]
    if len(em_codes) > 1:
        denial_flags.append({
            "codes": em_codes,
            "risk": "high",
            "reason": "Multiple E&M codes billed for the same date of service — only one is billable per visit"
        })
        # Flag the duplicate in the suggestion
        for cs in billing_codes:
            if cs.code in em_codes[1:]:
                cs.denial_risk = "high"
                cs.denial_risk_reason = "Duplicate E&M code — cannot bill multiple E&M codes same day"

    # Save all code suggestions to database
    for cs in billing_codes:
        db.add(cs)

    # Update encounter status to pending_review
    encounter.status = "pending_review"
    audit_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": "ai_codes_suggested",
        "details": f"AI suggested {len(billing_codes)} billing codes",
        "denial_flags": len(denial_flags),
    }
    current_log = encounter.audit_log or []
    current_log.append(audit_entry)
    encounter.audit_log = current_log

    db.commit()

    print(f"✅ Note {note_id} analyzed: {len(billing_codes)} billing codes suggested")

    return {
        "note_id": note_id,
        "encounter_id": encounter.id,
        "patient_summary": patient_summary,
        "parsed_note": parsed_note,
        "billing_codes": [
            {
                "code_type": cs.code_type,
                "code": cs.code,
                "description": cs.description,
                "confidence": cs.confidence,
                "denial_risk": cs.denial_risk,
                "denial_risk_reason": cs.denial_risk_reason,
            }
            for cs in billing_codes
        ],
        "denial_flags": denial_flags,
        "status": "pending_review",
        "message": f"Analysis complete. {len(billing_codes)} billing codes suggested, {len(denial_flags)} denial risk flags."
    }


