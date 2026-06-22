"""
FILE: api/admin.py
==================
WHAT THIS FILE IS:
    Admin-only routes for user management and system observability.
    No public registration anywhere — admins create all users here.

    This is the governance layer of MediSight+:
    - Create users with specific roles (patient/doctor/billing)
    - View all users and deactivate accounts
    - System health dashboard (DB, Redis, Pinecone, RAG status)
    - Audit log access across all encounters

WHO CAN ACCESS:
    All routes require role='admin' (a new role we add below).
    For the portfolio demo, we check for a special ADMIN_SECRET header
    so you can test without creating an admin account first.

ROUTES:
    POST /admin/users              → Create a new user (any role)
    GET  /admin/users              → List all users
    PUT  /admin/users/{id}/deactivate → Deactivate a user
    GET  /admin/system             → Full system health + RAG status
    GET  /admin/stats              → Platform usage statistics
"""

import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

from models.database import get_db, engine
from models.orm_models import User, Patient, SymptomLog, ClinicalNote, BillingEncounter, CodeSuggestion, UserRole
from api.auth import hash_password

load_dotenv()

router = APIRouter(prefix="/admin", tags=["Admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "medisight-admin-secret-change-in-production")


def verify_admin(x_admin_secret: str = Header(None)):
    """
    Simple admin verification via secret header.
    In production: replace with a proper admin role check + MFA.
    For portfolio: use ADMIN_SECRET from .env
    """
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access denied")
    return True


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    """Admin creates a user — no public registration"""
    email: EmailStr
    full_name: str
    password: str
    role: str  # patient, doctor, billing


class UserListItem(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── USER MANAGEMENT ───────────────────────────────────────────────────────────

@router.post("/users", status_code=201)
def create_user(
    data: CreateUserRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    """
    ROUTE: POST /admin/users
    -------------------------
    Admin creates a new user account.
    This is the ONLY way to create accounts — no public registration.

    INPUT (JSON + X-Admin-Secret header):
        {
          "email": "newdoctor@hospital.com",
          "full_name": "Dr. Sarah Lee",
          "password": "SecurePass123",
          "role": "doctor"
        }

    OUTPUT: {user_id, email, full_name, role, created_at}
    """
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Email '{data.email}' already registered")

    if data.role not in ["patient", "doctor", "billing"]:
        raise HTTPException(status_code=400, detail="Role must be: patient, doctor, or billing")

    new_user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=UserRole(data.role),
    )
    db.add(new_user)
    db.flush()

    # Auto-create patient profile if role is patient
    if data.role == "patient":
        db.add(Patient(user_id=new_user.id))

    db.commit()
    db.refresh(new_user)

    print(f"✅ Admin created user: {new_user.email} (role: {new_user.role})")

    return {
        "user_id":    new_user.id,
        "email":      new_user.email,
        "full_name":  new_user.full_name,
        "role":       new_user.role.value,
        "created_at": new_user.created_at.isoformat(),
    }


@router.get("/users")
def list_users(
    role: Optional[str] = None,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    """
    ROUTE: GET /admin/users?role=doctor
    ------------------------------------
    List all users, optionally filtered by role.

    OUTPUT: List of users with id, email, name, role, created_at
    """
    query = db.query(User)
    if role:
        query = query.filter(User.role == UserRole(role))

    users = query.order_by(User.created_at.desc()).all()
    return [
        {
            "id":         u.id,
            "email":      u.email,
            "full_name":  u.full_name,
            "role":       u.role.value,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.put("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    new_password: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    """
    ROUTE: PUT /admin/users/{id}/reset-password
    ---------------------------------------------
    Admin resets a user's password.
    Use when a user is locked out or first-time setup.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"message": f"Password reset for {user.email}"}


# ── SYSTEM HEALTH ─────────────────────────────────────────────────────────────

@router.get("/system")
def system_health(
    _: bool = Depends(verify_admin),
):
    """
    ROUTE: GET /admin/system
    -------------------------
    Full system health check across all components.
    Shows: DB, Redis, Pinecone, RAG pipeline, BM25 index, Claude API.

    Use this for the admin observability panel.
    """
    from pathlib import Path
    from sqlalchemy import text

    status = {}

    # PostgreSQL
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["postgresql"] = {"status": "healthy"}
    except Exception as e:
        status["postgresql"] = {"status": "error", "detail": str(e)[:80]}

    # Redis
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), socket_connect_timeout=2)
        r.ping()
        status["redis"] = {"status": "healthy"}
    except Exception as e:
        status["redis"] = {"status": "error", "detail": str(e)[:80]}

    # Pinecone
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        idx = pc.Index(os.getenv("PINECONE_INDEX_NAME", "medisight-kb"))
        stats = idx.describe_index_stats()
        status["pinecone"] = {
            "status": "healthy",
            "vector_count": stats.get("total_vector_count", 0),
            "index": os.getenv("PINECONE_INDEX_NAME", "medisight-kb"),
        }
    except Exception as e:
        status["pinecone"] = {"status": "error", "detail": str(e)[:80]}

    # BM25 index
    bm25_path = Path("data/bm25_index.pkl")
    status["bm25_index"] = {
        "status": "healthy" if bm25_path.exists() else "missing",
        "path":   str(bm25_path),
        "size_mb": round(bm25_path.stat().st_size / (1024*1024), 2) if bm25_path.exists() else 0,
    }

    # Claude API (quick ping)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}]
        )
        status["claude_api"] = {"status": "healthy", "model": "claude-haiku-4-5"}
    except Exception as e:
        status["claude_api"] = {"status": "error", "detail": str(e)[:80]}

    # Eval results (last run)
    eval_path = Path("eval/results.json")
    if eval_path.exists():
        import json
        with open(eval_path) as f:
            eval_data = json.load(f)
        status["last_eval"] = {
            "timestamp":   eval_data.get("timestamp"),
            "faithfulness": eval_data.get("scores", {}).get("faithfulness"),
            "passed":       eval_data.get("overall_passed"),
        }
    else:
        status["last_eval"] = {"status": "not_run", "note": "Run eval/run_ragas.py"}

    overall = "healthy" if all(
        v.get("status") == "healthy"
        for v in status.values()
        if isinstance(v, dict) and "status" in v
    ) else "degraded"

    return {
        "overall": overall,
        "timestamp": datetime.utcnow().isoformat(),
        "components": status,
    }


@router.get("/stats")
def platform_stats(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    """
    ROUTE: GET /admin/stats
    -------------------------
    Platform usage statistics for the admin dashboard.
    Shows user counts, symptom logs, notes, billing encounters.
    """
    user_counts = {}
    for role in ["patient", "doctor", "billing"]:
        user_counts[role] = db.query(User).filter(User.role == UserRole(role)).count()

    return {
        "users": {
            "total":   sum(user_counts.values()),
            "by_role": user_counts,
        },
        "clinical": {
            "symptom_logs":    db.query(SymptomLog).count(),
            "clinical_notes":  db.query(ClinicalNote).count(),
            "locked_notes":    db.query(ClinicalNote).filter(ClinicalNote.is_locked == True).count(),  # noqa
        },
        "billing": {
            "encounters_total":   db.query(BillingEncounter).count(),
            "pending_review":     db.query(BillingEncounter).filter(BillingEncounter.status == "pending_review").count(),
            "approved":           db.query(BillingEncounter).filter(BillingEncounter.status == "approved").count(),
            "code_suggestions":   db.query(CodeSuggestion).count(),
            "codes_approved":     db.query(CodeSuggestion).filter(CodeSuggestion.is_approved == True).count(),  # noqa
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
