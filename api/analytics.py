"""
FILE: api/analytics.py
=======================
Analytics endpoints for the Clinical Analytics Dashboard.

ROUTES:
    GET /analytics/symptoms/trends       → Severity trend by day (last 30 days)
    GET /analytics/symptoms/frequency    → Most common symptoms
    GET /analytics/symptoms/heatmap      → Symptom frequency by day of week + hour
    GET /analytics/billing/codes         → Most suggested ICD-10/CPT/HCPCS codes
    GET /analytics/billing/denial-risk   → Denial risk distribution
    GET /analytics/billing/approval-rate → Approval rate over time
    GET /analytics/patients/risk-scores  → Risk score per patient
    GET /analytics/rag/history           → Recent RAG queries (doctor view)
    GET /analytics/overview              → Single endpoint with all KPIs
"""

import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

from models.database import get_db
from models.orm_models import (
    User, Patient, SymptomLog, ClinicalNote,
    BillingEncounter, CodeSuggestion, UserRole
)
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ── PATIENT RISK SCORING ──────────────────────────────────────────────────────

def compute_risk_score(patient_id: int, db: Session) -> dict:
    """
    Compute a 0-100 risk score for a patient based on:
    - Average severity last 30 days (40 pts)
    - Frequency of high-severity (7+) logs (30 pts)
    - Days since last clinical note (20 pts)
    - Total symptom count last 30 days (10 pts)
    """
    cutoff = datetime.utcnow() - timedelta(days=30)

    logs = db.query(SymptomLog).filter(
        SymptomLog.patient_id == patient_id,
        SymptomLog.logged_at >= cutoff,
    ).all()

    if not logs:
        return {"score": 0, "level": "unknown", "factors": {}}

    avg_severity = sum(l.severity for l in logs) / len(logs)
    high_severity_count = sum(1 for l in logs if l.severity >= 7)
    high_severity_rate = high_severity_count / len(logs)

    last_note = db.query(ClinicalNote).filter(
        ClinicalNote.patient_id == patient_id,
        ClinicalNote.is_locked == True,  # noqa
    ).order_by(desc(ClinicalNote.locked_at)).first()

    days_since_note = 999
    if last_note and last_note.locked_at:
        days_since_note = (datetime.utcnow() - last_note.locked_at).days

    # Score components
    severity_score      = min((avg_severity / 10) * 40, 40)
    high_sev_score      = min(high_severity_rate * 30, 30)
    note_recency_score  = min((days_since_note / 30) * 20, 20)
    frequency_score     = min((len(logs) / 20) * 10, 10)

    total = round(severity_score + high_sev_score + note_recency_score + frequency_score)
    total = max(0, min(100, total))

    level = "critical" if total >= 75 else "high" if total >= 50 else "moderate" if total >= 25 else "low"

    return {
        "score": total,
        "level": level,
        "color": "#EF4444" if level == "critical" else "#F59E0B" if level == "high" else "#3B82F6" if level == "moderate" else "#10B981",
        "factors": {
            "avg_severity":        round(avg_severity, 1),
            "high_severity_rate":  round(high_severity_rate * 100),
            "days_since_note":     days_since_note if days_since_note < 999 else None,
            "symptom_count_30d":   len(logs),
        }
    }


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@router.get("/overview")
def analytics_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/overview
    Single endpoint with all platform KPIs.
    Used for the top stat cards on the analytics dashboard.
    """
    now = datetime.utcnow()
    cutoff_30d = now - timedelta(days=30)
    cutoff_7d  = now - timedelta(days=7)

    total_symptoms = db.query(SymptomLog).count()
    symptoms_7d    = db.query(SymptomLog).filter(SymptomLog.logged_at >= cutoff_7d).count()

    all_logs_30d = db.query(SymptomLog).filter(SymptomLog.logged_at >= cutoff_30d).all()
    avg_severity  = round(sum(l.severity for l in all_logs_30d) / len(all_logs_30d), 1) if all_logs_30d else 0

    total_encounters  = db.query(BillingEncounter).count()
    pending_encounters = db.query(BillingEncounter).filter(BillingEncounter.status == "pending_review").count()
    approved_encounters = db.query(BillingEncounter).filter(BillingEncounter.status == "approved").count()

    total_codes   = db.query(CodeSuggestion).count()
    approved_codes = db.query(CodeSuggestion).filter(CodeSuggestion.is_approved == True).count()  # noqa
    code_approval_rate = round((approved_codes / total_codes * 100) if total_codes else 0, 1)

    total_notes  = db.query(ClinicalNote).count()
    locked_notes = db.query(ClinicalNote).filter(ClinicalNote.is_locked == True).count()  # noqa

    return {
        "symptoms": {
            "total":        total_symptoms,
            "last_7_days":  symptoms_7d,
            "avg_severity_30d": avg_severity,
        },
        "billing": {
            "total_encounters":    total_encounters,
            "pending_review":      pending_encounters,
            "approved":            approved_encounters,
            "code_approval_rate":  code_approval_rate,
        },
        "clinical": {
            "total_notes":  total_notes,
            "locked_notes": locked_notes,
        },
        "timestamp": now.isoformat(),
    }


@router.get("/symptoms/trends")
def symptom_trends(
    days: int = 30,
    patient_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/symptoms/trends?days=30
    Returns daily average severity for the last N days.
    Suitable for a line chart.

    OUTPUT: [{"date": "2026-05-01", "avg_severity": 5.2, "count": 3}, ...]
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(SymptomLog).filter(SymptomLog.logged_at >= cutoff)
    if patient_id:
        query = query.filter(SymptomLog.patient_id == patient_id)

    logs = query.all()

    # Group by date
    by_date = defaultdict(list)
    for log in logs:
        date_key = log.logged_at.strftime("%Y-%m-%d")
        by_date[date_key].append(log.severity)

    # Fill in all dates (even empty ones)
    result = []
    for i in range(days, -1, -1):
        date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        severities = by_date.get(date, [])
        result.append({
            "date":         date,
            "avg_severity": round(sum(severities) / len(severities), 1) if severities else 0,
            "count":        len(severities),
            "max_severity": max(severities) if severities else 0,
        })

    return result


@router.get("/symptoms/frequency")
def symptom_frequency(
    limit: int = 10,
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/symptoms/frequency
    Most common symptoms logged in the last N days.
    Suitable for a horizontal bar chart.

    OUTPUT: [{"symptom": "chest pain", "count": 24, "avg_severity": 6.8}, ...]
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs = db.query(SymptomLog).filter(SymptomLog.logged_at >= cutoff).all()

    by_symptom = defaultdict(list)
    for log in logs:
        by_symptom[log.symptom.lower()].append(log.severity)

    result = [
        {
            "symptom":      symptom,
            "count":        len(severities),
            "avg_severity": round(sum(severities) / len(severities), 1),
            "max_severity": max(severities),
        }
        for symptom, severities in by_symptom.items()
    ]

    result.sort(key=lambda x: x["count"], reverse=True)
    return result[:limit]


@router.get("/symptoms/heatmap")
def symptom_heatmap(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/symptoms/heatmap
    Symptom count by day of week and hour of day.
    Suitable for a calendar/heatmap chart.

    OUTPUT: [{"day": 0, "hour": 9, "count": 5, "avg_severity": 6.1}, ...]
    where day 0=Monday ... 6=Sunday
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs = db.query(SymptomLog).filter(SymptomLog.logged_at >= cutoff).all()

    grid = defaultdict(list)
    for log in logs:
        key = (log.logged_at.weekday(), log.logged_at.hour)
        grid[key].append(log.severity)

    result = []
    days_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for day in range(7):
        for hour in range(24):
            severities = grid.get((day, hour), [])
            result.append({
                "day":          day,
                "day_label":    days_labels[day],
                "hour":         hour,
                "count":        len(severities),
                "avg_severity": round(sum(severities) / len(severities), 1) if severities else 0,
            })

    return result


@router.get("/billing/codes")
def billing_code_frequency(
    code_type: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/billing/codes?code_type=ICD10
    Most frequently suggested billing codes.
    Suitable for a bar chart.

    OUTPUT: [{"code": "E11.9", "description": "...", "count": 12, "approval_rate": 0.92}, ...]
    """
    query = db.query(CodeSuggestion)
    if code_type:
        query = query.filter(CodeSuggestion.code_type == code_type.upper())

    suggestions = query.all()

    by_code = defaultdict(lambda: {"count": 0, "approved": 0, "desc": "", "type": ""})
    for s in suggestions:
        by_code[s.code]["count"] += 1
        by_code[s.code]["approved"] += 1 if s.is_approved else 0
        by_code[s.code]["desc"] = s.description
        by_code[s.code]["type"] = s.code_type

    result = [
        {
            "code":          code,
            "description":   data["desc"],
            "code_type":     data["type"],
            "count":         data["count"],
            "approved":      data["approved"],
            "approval_rate": round(data["approved"] / data["count"], 2) if data["count"] else 0,
        }
        for code, data in by_code.items()
    ]

    result.sort(key=lambda x: x["count"], reverse=True)
    return result[:limit]


@router.get("/billing/denial-risk")
def denial_risk_distribution(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/billing/denial-risk
    Distribution of denial risk levels across all code suggestions.
    Suitable for a pie/donut chart.
    """
    suggestions = db.query(CodeSuggestion).all()
    dist = defaultdict(int)
    for s in suggestions:
        dist[s.denial_risk or "low"] += 1

    total = len(suggestions)
    return {
        "total": total,
        "distribution": [
            {"risk": "low",    "count": dist["low"],    "pct": round(dist["low"]    / total * 100, 1) if total else 0},
            {"risk": "medium", "count": dist["medium"], "pct": round(dist["medium"] / total * 100, 1) if total else 0},
            {"risk": "high",   "count": dist["high"],   "pct": round(dist["high"]   / total * 100, 1) if total else 0},
        ]
    }


@router.get("/billing/approval-rate")
def billing_approval_trend(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /analytics/billing/approval-rate
    Encounter approval rate over time.
    Suitable for a line chart.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    encounters = db.query(BillingEncounter).filter(
        BillingEncounter.created_at >= cutoff
    ).all()

    by_week = defaultdict(lambda: {"total": 0, "approved": 0})
    for enc in encounters:
        week = enc.created_at.strftime("%Y-W%U")
        by_week[week]["total"] += 1
        if enc.status == "approved":
            by_week[week]["approved"] += 1

    return [
        {
            "week":          week,
            "total":         data["total"],
            "approved":      data["approved"],
            "approval_rate": round(data["approved"] / data["total"] * 100, 1) if data["total"] else 0,
        }
        for week, data in sorted(by_week.items())
    ]


@router.get("/patients/risk-scores")
def patient_risk_scores(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """
    GET /analytics/patients/risk-scores
    Risk score for every assigned patient.
    Suitable for a ranked list with colored badges.
    """
    # Get all patients assigned to this doctor
    patients = db.query(Patient).filter(
        Patient.assigned_doctor_id == current_user.id
    ).all()

    # Also get all patients if no assigned ones (demo mode)
    if not patients:
        patients = db.query(Patient).limit(10).all()

    result = []
    for patient in patients:
        user = db.query(User).filter(User.id == patient.user_id).first()
        risk = compute_risk_score(patient.id, db)
        result.append({
            "patient_id":  patient.id,
            "full_name":   user.full_name if user else f"Patient {patient.id}",
            "email":       user.email if user else "",
            "risk_score":  risk["score"],
            "risk_level":  risk["level"],
            "risk_color":  risk["color"],
            "factors":     risk["factors"],
        })

    result.sort(key=lambda x: x["risk_score"], reverse=True)
    return result


@router.get("/rag/history")
def rag_query_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """
    GET /analytics/rag/history
    Recent RAG queries for this doctor.
    Returns mock history until we add the rag_queries table.
    """
    # Return the sample queries from the eval golden set for demo
    sample_history = [
        {"query": "Differential diagnosis for chest pain and fever", "confidence": 0.87, "sources": 5, "query_type": "symptom", "latency_ms": 22000, "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat()},
        {"query": "Management of type 2 diabetes with hypertension", "confidence": 0.91, "sources": 5, "query_type": "procedure", "latency_ms": 19000, "timestamp": (datetime.utcnow() - timedelta(hours=5)).isoformat()},
        {"query": "Community-acquired pneumonia antibiotic selection", "confidence": 0.85, "sources": 5, "query_type": "procedure", "latency_ms": 21000, "timestamp": (datetime.utcnow() - timedelta(days=1)).isoformat()},
        {"query": "COPD exacerbation management guidelines", "confidence": 0.93, "sources": 5, "query_type": "procedure", "latency_ms": 18000, "timestamp": (datetime.utcnow() - timedelta(days=1, hours=3)).isoformat()},
        {"query": "Drug interactions for warfarin and amoxicillin", "confidence": 0.44, "sources": 3, "query_type": "drug", "latency_ms": 15000, "timestamp": (datetime.utcnow() - timedelta(days=2)).isoformat()},
    ]
    return sample_history[:limit]
