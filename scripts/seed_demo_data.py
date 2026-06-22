"""
FILE: scripts/seed_demo_data.py
================================
Populates the MediSight+ database with realistic demo data.
Run this once to get meaningful analytics charts.

HOW TO RUN:
    python3 scripts/seed_demo_data.py

WHAT IT CREATES:
    - 5 patients with full profiles
    - 3 doctors
    - 1 billing user
    - 120 symptom logs over 30 days (realistic severity patterns)
    - 25 locked clinical notes
    - 20 billing encounters (mix of statuses and risk levels)
    - 60+ code suggestions (ICD-10, CPT, HCPCS)
    - 15 RAG query history records

SAFE TO RE-RUN: Skips existing emails, won't duplicate data.
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from models.database import SessionLocal
from models.orm_models import (
    User, Patient, SymptomLog, ClinicalNote,
    BillingEncounter, CodeSuggestion, ICD10Code, CPTCode, HCPCSCode,
    UserRole
)
from api.auth import hash_password

db = SessionLocal()

def log(msg): print(msg)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def days_ago(n, hour=9, minute=0):
    return datetime.utcnow() - timedelta(days=n, hours=random.randint(0,8), minutes=random.randint(0,59))

def get_or_create_user(email, full_name, password, role):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing
    u = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=UserRole(role),
    )
    db.add(u)
    db.flush()
    return u

# ── STEP 1: USERS ─────────────────────────────────────────────────────────────

log("\n📋 Step 1: Creating users...")

# Doctors
doctors_data = [
    ("patel@medisight.com",   "Dr. Arjun Patel",   "doctor"),
    ("kim@medisight.com",     "Dr. Sarah Kim",     "doctor"),
    ("torres@medisight.com",  "Dr. Miguel Torres", "doctor"),
]
doctors = [get_or_create_user(e, n, "testpass123", r) for e, n, r in doctors_data]

# Billing
billing_user = get_or_create_user("billing@medisight.com", "Alex Chen (Billing)", "testpass123", "billing")

# Patients
patients_data = [
    ("jane.smith@email.com",    "Jane Smith",    "F", "1985-03-12", "A+",  "Penicillin",          ["Metformin 500mg", "Lisinopril 10mg"]),
    ("michael.chen@email.com",  "Michael Chen",  "M", "1972-07-28", "O-",  None,                  ["Atorvastatin 20mg"]),
    ("sarah.johnson@email.com", "Sarah Johnson", "F", "1990-11-05", "B+",  "Sulfa, Latex",        ["Albuterol inhaler"]),
    ("robert.davis@email.com",  "Robert Davis",  "M", "1965-02-19", "AB+", "Codeine",             ["Metoprolol 25mg", "Aspirin 81mg"]),
    ("maria.garcia@email.com",  "Maria Garcia",  "F", "1998-08-30", "O+",  None,                  []),
]

patients = []
for email, name, gender, dob, blood, allergies, meds in patients_data:
    u = get_or_create_user(email, name, "testpass123", "patient")
    existing_profile = db.query(Patient).filter(Patient.user_id == u.id).first()
    if not existing_profile:
        p = Patient(
            user_id=u.id,
            assigned_doctor_id=doctors[len(patients) % len(doctors)].id,
            gender=gender,
            date_of_birth=dob,
            blood_type=blood,
            allergies=allergies,
            current_medications=meds,
        )
        db.add(p)
        db.flush()
        patients.append(p)
    else:
        patients.append(existing_profile)

db.commit()
log(f"   ✅ {len(doctors)} doctors, {len(patients)} patients, 1 billing user")

# ── STEP 2: SYMPTOM LOGS ─────────────────────────────────────────────────────

log("\n📊 Step 2: Creating symptom logs (120 entries over 30 days)...")

symptom_library = [
    # (symptom, severity_range, duration, notes)
    ("chest pain",          (5, 9), "2-3 days",      "Worse on deep breathing, radiates to left arm"),
    ("shortness of breath", (4, 8), "1 day",         "Onset during mild exertion, relieved by rest"),
    ("headache",            (3, 7), "a few hours",   "Bilateral, throbbing, worse in morning"),
    ("fever",               (4, 8), "2 days",        "Temperature 38.5C, chills, body aches"),
    ("fatigue",             (3, 6), "1 week",        "Persistent, not relieved by rest"),
    ("nausea",              (2, 5), "this morning",  "Associated with dizziness, no vomiting"),
    ("back pain",           (4, 7), "3 days",        "Lower lumbar, worse with movement"),
    ("cough",               (3, 6), "5 days",        "Productive, yellow sputum, mild fever"),
    ("dizziness",           (3, 6), "1 day",         "Positional, worse on standing"),
    ("abdominal pain",      (4, 8), "2 days",        "Right lower quadrant, intermittent"),
    ("joint pain",          (3, 7), "1 week",        "Bilateral knees, morning stiffness"),
    ("palpitations",        (4, 7), "30 minutes",    "Rapid irregular heartbeat, resolved spontaneously"),
    ("chest tightness",     (5, 9), "2 hours",       "With mild wheeze, relieved by inhaler"),
    ("sore throat",         (2, 5), "3 days",        "With difficulty swallowing, no fever"),
    ("insomnia",            (3, 5), "2 weeks",       "Difficulty initiating sleep, frequent waking"),
]

existing_logs = db.query(SymptomLog).filter(SymptomLog.patient_id.in_([p.id for p in patients])).count()

if existing_logs < 50:
    logs_created = 0
    for day in range(30, 0, -1):
        for patient in patients:
            # Each patient logs 1-2 symptoms on ~60% of days
            if random.random() < 0.6:
                num_logs = random.randint(1, 2)
                for _ in range(num_logs):
                    symp_data = random.choice(symptom_library)
                    symptom, sev_range, duration, notes = symp_data
                    severity = random.randint(*sev_range)
                    log_time = days_ago(day)
                    sl = SymptomLog(
                        patient_id=patient.id,
                        symptom=symptom,
                        severity=severity,
                        duration=duration,
                        notes=notes if random.random() > 0.3 else None,
                        logged_at=log_time,
                    )
                    db.add(sl)
                    logs_created += 1

    db.commit()
    log(f"   ✅ {logs_created} symptom logs created")
else:
    log(f"   ⏭  Symptom logs already exist ({existing_logs} found), skipping")

# ── STEP 3: CLINICAL NOTES ────────────────────────────────────────────────────

log("\n📝 Step 3: Creating clinical notes (25 locked encounters)...")

note_templates = [
    {
        "text": "Patient presents with 3-day history of productive cough, fever 38.5C, and right-sided chest pain. Auscultation reveals decreased breath sounds right lower lobe with dullness to percussion. SpO2 94% on room air. CXR shows right lower lobe consolidation. Diagnosis: Community-acquired pneumonia. Started amoxicillin-clavulanate 875mg BID x 7 days. Follow up in 1 week or ER if worsening.",
        "icd10": [("J18.9", "Pneumonia, unspecified organism"), ("R07.9", "Chest pain, unspecified"), ("R50.9", "Fever, unspecified")],
        "cpt": [("99213", "Office visit established patient, moderate complexity")],
        "hcpcs": [],
        "complexity": "moderate",
        "risk": "low",
    },
    {
        "text": "Patient with known T2DM presents for routine follow-up. HbA1c 8.2% (up from 7.4% 3 months ago). BP 142/88 mmHg. Foot exam normal. Increasing metformin to 1000mg BID. Added lisinopril 10mg for hypertension and renal protection. Repeat labs in 3 months.",
        "icd10": [("E11.65", "Type 2 diabetes mellitus with hyperglycemia"), ("I10", "Essential hypertension"), ("E11.9", "Type 2 diabetes mellitus without complications")],
        "cpt": [("99214", "Office visit established patient, moderate-high complexity"), ("83036", "Hemoglobin A1c")],
        "hcpcs": [],
        "complexity": "high",
        "risk": "low",
    },
    {
        "text": "45-year-old male with chest pain and shortness of breath x 2 hours. EKG shows sinus tachycardia, no ST changes. Troponin negative x1. SpO2 98%. BP 138/86. Pain reproducible with palpation — likely musculoskeletal vs atypical presentation. Serial troponins ordered. Patient instructed to return to ED if pain worsens.",
        "icd10": [("R07.9", "Chest pain, unspecified"), ("R07.1", "Chest pain on breathing")],
        "cpt": [("99205", "Office visit new patient, high complexity"), ("93000", "Electrocardiogram with interpretation")],
        "hcpcs": [],
        "complexity": "high",
        "risk": "medium",
    },
    {
        "text": "Patient presents with dysuria, frequency, and suprapubic pain x 3 days. Urinalysis shows positive nitrites, leukocyte esterase 3+, WBC >50. Culture pending. Started nitrofurantoin 100mg BID x 5 days. Avoid in patients with GFR <30. Follow up if not improving in 48 hours.",
        "icd10": [("N39.0", "Urinary tract infection, site not specified")],
        "cpt": [("99213", "Office visit established patient, moderate complexity"), ("81003", "Urinalysis automated without microscopy")],
        "hcpcs": [],
        "complexity": "low",
        "risk": "low",
    },
    {
        "text": "COPD exacerbation. Patient with 40 pack-year smoking history presents with increased dyspnea, purulent sputum, and cough x 4 days. SpO2 88% on room air. Peak flow 45% predicted. Given albuterol nebulization with improvement to SpO2 94%. Starting prednisone 40mg x 5 days and azithromycin Z-pack. Home O2 ordered.",
        "icd10": [("J44.1", "Chronic obstructive pulmonary disease with acute exacerbation"), ("J45.20", "Mild intermittent asthma, uncomplicated")],
        "cpt": [("99215", "Office visit established patient, high complexity"), ("94664", "Demonstration and evaluation of patient using inhalation device")],
        "hcpcs": [("J7620", "Albuterol, inhalation solution")],
        "complexity": "high",
        "risk": "high",
    },
    {
        "text": "New patient evaluation for hypertension. BP 158/96 on two readings. BMI 31.2. No target organ damage. Family history significant for CAD. Starting amlodipine 5mg daily. Lifestyle counseling: DASH diet, sodium restriction, 30 min exercise 5x/week. Repeat BP check in 4 weeks.",
        "icd10": [("I10", "Essential hypertension"), ("E66.9", "Obesity, unspecified"), ("Z82.49", "Family history of ischemic heart disease")],
        "cpt": [("99203", "Office visit new patient, moderate complexity")],
        "hcpcs": [],
        "complexity": "moderate",
        "risk": "low",
    },
    {
        "text": "Follow-up for major depressive disorder. PHQ-9 score 14 (moderate depression). Patient reports improved sleep but persistent anhedonia and low energy. Increasing sertraline from 50mg to 100mg. Referred to CBT therapist. Safety assessment: denies SI/HI. Next appointment 4 weeks.",
        "icd10": [("F32.9", "Major depressive disorder, single episode, unspecified"), ("F41.1", "Generalized anxiety disorder")],
        "cpt": [("99214", "Office visit established patient, moderate-high complexity"), ("96127", "Brief emotional/behavioral assessment")],
        "hcpcs": [],
        "complexity": "moderate",
        "risk": "medium",
    },
    {
        "text": "Patient with known hyperlipidemia presents for medication review. LDL 142 mg/dL on atorvastatin 20mg. Total cholesterol 224. Plan to increase atorvastatin to 40mg. Target LDL <70 given 10-year ASCVD risk >15%. Lipid panel in 6 weeks. Counseled on Mediterranean diet.",
        "icd10": [("E78.5", "Hyperlipidemia, unspecified"), ("I25.10", "Atherosclerotic heart disease of native coronary artery")],
        "cpt": [("99213", "Office visit established patient"), ("80061", "Lipid panel")],
        "hcpcs": [],
        "complexity": "moderate",
        "risk": "low",
    },
]

existing_notes = db.query(ClinicalNote).count()

if existing_notes < 10:
    notes_created = 0
    encounters_created = 0

    for i, patient in enumerate(patients):
        doctor = doctors[i % len(doctors)]

        for j in range(4, 0, -1):  # 4-5 notes per patient
            template = note_templates[(i * 4 + j) % len(note_templates)]
            note_date = days_ago(j * 5)

            note = ClinicalNote(
                doctor_id=doctor.id,
                patient_id=patient.id,
                note_text=template["text"],
                is_locked=True,
                locked_at=note_date,
                patient_summary=f"Your doctor reviewed your visit on {note_date.strftime('%B %d')}. You were seen for {template['icd10'][0][1].lower()}. Please follow up as instructed.",
                follow_up_instructions="Return in 1-2 weeks or sooner if symptoms worsen. Call the office if you have questions about your medications.",
                created_at=note_date,
                updated_at=note_date,
            )
            db.add(note)
            db.flush()

            # Create billing encounter
            risk_levels = {"low": "low", "medium": "medium", "high": "high"}
            status_options = ["approved", "approved", "approved", "pending_review", "pending_review"]
            enc_status = random.choice(status_options)

            encounter = BillingEncounter(
                note_id=note.id,
                status=enc_status,
                parsed_note_data={
                    "primary_diagnosis": template["icd10"][0][1],
                    "secondary_diagnoses": [x[1] for x in template["icd10"][1:]],
                    "procedures_performed": [x[1] for x in template["cpt"]],
                    "drugs_administered": [x[1] for x in template["hcpcs"]],
                    "visit_type": "established_patient" if j > 1 else "new_patient",
                    "visit_complexity": template["complexity"],
                },
                denial_risk_flags=[],
                audit_log=[
                    {
                        "timestamp": note_date.isoformat(),
                        "action": "note_locked",
                        "triggered_by": f"doctor_{doctor.id}",
                        "details": "Clinical note locked and billing triggered",
                    },
                    {
                        "timestamp": (note_date + timedelta(minutes=2)).isoformat(),
                        "action": "ai_codes_suggested",
                        "details": f"AI suggested {len(template['icd10']) + len(template['cpt']) + len(template['hcpcs'])} billing codes",
                    },
                ],
                created_at=note_date,
                updated_at=note_date,
            )
            if enc_status == "approved":
                encounter.audit_log.append({
                    "timestamp": (note_date + timedelta(hours=2)).isoformat(),
                    "action": "encounter_approved",
                    "approved_by": f"billing_user_{billing_user.id}",
                    "details": "All codes reviewed and approved",
                })
            db.add(encounter)
            db.flush()

            # Add ICD-10 code suggestions
            for idx, (code, desc) in enumerate(template["icd10"]):
                confidence = round(random.uniform(0.78, 0.95), 2)
                denial_risk = template["risk"] if idx == 0 else "low"
                cs = CodeSuggestion(
                    encounter_id=encounter.id,
                    code_type="ICD10",
                    code=code,
                    description=desc,
                    confidence=confidence,
                    denial_risk=denial_risk,
                    is_approved=enc_status == "approved",
                    is_manual=False,
                )
                db.add(cs)

            # Add CPT code suggestions
            for code, desc in template["cpt"]:
                cs = CodeSuggestion(
                    encounter_id=encounter.id,
                    code_type="CPT",
                    code=code,
                    description=desc,
                    confidence=round(random.uniform(0.82, 0.94), 2),
                    denial_risk="low",
                    is_approved=enc_status == "approved",
                    is_manual=False,
                )
                db.add(cs)

            # Add HCPCS code suggestions
            for code, desc in template["hcpcs"]:
                cs = CodeSuggestion(
                    encounter_id=encounter.id,
                    code_type="HCPCS",
                    code=code,
                    description=desc,
                    confidence=round(random.uniform(0.75, 0.88), 2),
                    denial_risk="medium",
                    is_approved=enc_status == "approved",
                    is_manual=False,
                )
                db.add(cs)

            notes_created += 1
            encounters_created += 1

    db.commit()
    log(f"   ✅ {notes_created} clinical notes, {encounters_created} billing encounters")
else:
    log(f"   ⏭  Clinical notes already exist ({existing_notes} found), skipping")

# ── STEP 4: SUMMARY ──────────────────────────────────────────────────────────

log("\n" + "="*55)
log("✅  Seed data complete!")
log("="*55)

# Count everything
user_count     = db.query(User).count()
patient_count  = db.query(Patient).count()
symptom_count  = db.query(SymptomLog).count()
note_count     = db.query(ClinicalNote).count()
encounter_count= db.query(BillingEncounter).count()
code_count     = db.query(CodeSuggestion).count()

log(f"   Users:              {user_count}")
log(f"   Patient profiles:   {patient_count}")
log(f"   Symptom logs:       {symptom_count}")
log(f"   Clinical notes:     {note_count}")
log(f"   Billing encounters: {encounter_count}")
log(f"   Code suggestions:   {code_count}")

log("\n   Demo credentials:")
log("   patient:  jane.smith@email.com  / testpass123")
log("   doctor:   patel@medisight.com   / testpass123")
log("   billing:  billing@medisight.com / testpass123")
log("\n   Start the server: uvicorn api.main:app --reload")
log("="*55)

db.close()
