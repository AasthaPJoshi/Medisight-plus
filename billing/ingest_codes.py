"""
FILE: billing/ingest_codes.py
==============================
WHAT THIS FILE IS:
    The most important Day 1 script. Downloads free CMS billing code files
    and loads them into your PostgreSQL database.

    This is what makes MediSight+ stand out from any other clinical AI project
    — real, government-sourced medical billing codes in your local database.

WHAT IT LOADS:
    1. ICD-10-CM FY2026 — from CMS.gov (free ZIP, no license needed)
       ~77,000 diagnosis codes with full and short descriptions
       Example: E11.9 = "Type 2 diabetes mellitus without complications"

    2. HCPCS Level II 2026 — from CMS.gov (free public use file)
       ~7,000 codes for drugs (J), supplies (A), DME (E), etc.
       Example: J1815 = "Injection, insulin, per 5 units"

    3. CPT / MPFS — from CMS Medicare Physician Fee Schedule (free)
       ~11,000+ procedure codes with CMS descriptions and payment rates
       Example: 99213 = "Office/outpatient visit est, 20-29 min"

WHY THESE ARE FREE:
    - ICD-10-CM: maintained by CMS, public domain, free download
    - HCPCS Level II: maintained by CMS, public domain, free download
    - CPT descriptions on MPFS: CMS's own descriptions (not AMA's)
      AMA's full CPT descriptions require a paid license
      CMS's MPFS descriptions cover the same codes and are free

HOW TO RUN:
    python3 billing/ingest_codes.py

    First run: downloads files from CMS (~50MB), parses them, loads to DB
    Subsequent runs: skips download if files exist, re-loads DB

    Expected time: 3-5 minutes on first run

INPUT:  CMS websites (auto-downloaded) + PostgreSQL connection from .env
OUTPUT: icd10_codes, hcpcs_codes, cpt_codes tables populated

CHECK IT WORKED:
    psql -U medisight_user -d medisight -h localhost
    SELECT COUNT(*) FROM icd10_codes;   -- should be ~77,000
    SELECT COUNT(*) FROM hcpcs_codes;   -- should be ~7,000
    SELECT COUNT(*) FROM cpt_codes;     -- should be ~10,000+
    SELECT code, description FROM icd10_codes WHERE code LIKE 'E11%' LIMIT 5;
"""

import os
import sys
import zipfile
import requests
import pandas as pd
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
from dotenv import load_dotenv

# Add project root to Python path so we can import models
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from models.database import engine, SessionLocal
from models.orm_models import ICD10Code, HCPCSCode, CPTCode, create_all_tables

# ─────────────────────────────────────────────────────────────────────────────
# PATHS — where to save downloaded files
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data" / "cms_codes"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ICD10_ZIP_PATH = DATA_DIR / "icd10cm_tabular_2026.zip"
HCPCS_ZIP_PATH = DATA_DIR / "hcpcs_2026.zip"
MPFS_ZIP_PATH  = DATA_DIR / "mpfs_2026.zip"


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD HELPER
# ─────────────────────────────────────────────────────────────────────────────
def download_file(url: str, dest_path: Path, description: str):
    """
    Download a file from a URL with progress indication.
    Skips download if file already exists locally.

    INPUT:  URL string, destination Path, human description
    OUTPUT: Nothing (file saved to dest_path)
    """
    if dest_path.exists():
        size_mb = dest_path.stat().st_size / (1024 * 1024)
        print(f"   ⏭️  {description}: already downloaded ({size_mb:.1f} MB) — skipping")
        return

    print(f"   ⬇️  Downloading {description}...")
    print(f"      URL: {url}")

    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"\r      Progress: {pct:.1f}%", end="", flush=True)

        print(f"\n   ✅ Downloaded: {dest_path.name} ({downloaded / (1024*1024):.1f} MB)")

    except requests.RequestException as e:
        print(f"\n   ❌ Download failed: {e}")
        print(f"   Manual download instructions provided below.")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# SETUP: Enable pg_trgm for fuzzy search
# ─────────────────────────────────────────────────────────────────────────────
def enable_trigram_extension():
    """
    Enable the pg_trgm PostgreSQL extension for fuzzy text search.

    pg_trgm breaks text into 3-character groups (trigrams) and uses them
    for similarity-based searching. This is what allows "chest pain" to match
    "unspecified chest pain" and "acute chest pain disorder".

    Also creates GIN indexes on code description columns for fast search.
    """
    print("\n🔧 Setting up PostgreSQL fuzzy search (pg_trgm)...")
    try:
        with engine.connect() as conn:
            # Enable the extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))

            # Create GIN (Generalized Inverted Index) on icd10_codes description
            # GIN indexes are best for full-text and trigram searches
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_icd10_desc_trgm
                ON icd10_codes USING gin(description gin_trgm_ops);
            """))

            # Create GIN index on hcpcs_codes description
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_hcpcs_desc_trgm
                ON hcpcs_codes USING gin(description gin_trgm_ops);
            """))

            # Create GIN index on cpt_codes description
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cpt_desc_trgm
                ON cpt_codes USING gin(description gin_trgm_ops);
            """))

            conn.commit()
        print("   ✅ pg_trgm extension enabled and indexes created")
    except Exception as e:
        print(f"   ⚠️  pg_trgm setup warning: {e}")
        print("   Fuzzy search may be slower without trigram indexes. Continuing...")


def _load_icd10_sample_data():
    """Fallback: load common ICD-10-CM codes so the app works without CMS download."""
    print("   ℹ️  Loading sample ICD-10-CM codes (fallback mode)...")
    sample_codes = [
        ("E11.9", "Type 2 diabetes mellitus without complications", "Type 2 DM w/o complications", "E11"),
        ("E11.65", "Type 2 diabetes mellitus with hyperglycemia", "Type 2 DM w hyperglycemia", "E11"),
        ("I10", "Essential (primary) hypertension", "Essential hypertension", "I10"),
        ("J18.9", "Pneumonia, unspecified organism", "Pneumonia, unspecified", "J18"),
        ("J06.9", "Acute upper respiratory infection, unspecified", "Acute upper resp infection", "J06"),
        ("R07.9", "Chest pain, unspecified", "Chest pain unspecified", "R07"),
        ("R07.1", "Chest pain on breathing", "Chest pain on breathing", "R07"),
        ("R51.9", "Headache, unspecified", "Headache unspecified", "R51"),
        ("R50.9", "Fever, unspecified", "Fever unspecified", "R50"),
        ("R05.9", "Cough, unspecified", "Cough unspecified", "R05"),
        ("K21.0", "Gastro-esophageal reflux disease with esophagitis", "GERD with esophagitis", "K21"),
        ("M54.5", "Low back pain", "Low back pain", "M54"),
        ("M54.2", "Cervicalgia", "Neck pain", "M54"),
        ("F32.9", "Major depressive disorder, single episode, unspecified", "Major depressive disorder", "F32"),
        ("F41.1", "Generalized anxiety disorder", "Generalized anxiety disorder", "F41"),
        ("Z00.00", "Encounter for general adult medical examination without abnormal findings", "General adult exam", "Z00"),
        ("Z23", "Encounter for immunization", "Encounter for immunization", "Z23"),
        ("J45.20", "Mild intermittent asthma, uncomplicated", "Mild intermittent asthma", "J45"),
        ("N39.0", "Urinary tract infection, site not specified", "UTI unspecified", "N39"),
        ("I25.10", "Atherosclerotic heart disease of native coronary artery without angina pectoris", "Coronary artery disease", "I25"),
        ("E78.5", "Hyperlipidemia, unspecified", "Hyperlipidemia unspecified", "E78"),
        ("E66.9", "Obesity, unspecified", "Obesity unspecified", "E66"),
        ("J44.1", "Chronic obstructive pulmonary disease with acute exacerbation", "COPD with exacerbation", "J44"),
        ("I63.9", "Cerebral infarction, unspecified", "Cerebral infarction", "I63"),
        ("S09.90XA", "Unspecified injury of head, initial encounter", "Head injury unspecified", "S09"),
    ]

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM icd10_codes"))
        db.commit()
        for code, desc, short_desc, prefix in sample_codes:
            db.execute(text(
                "INSERT INTO icd10_codes (code, description, short_description, category, code_prefix) "
                "VALUES (:code, :description, :short_description, :category, :code_prefix) "
                "ON CONFLICT (code) DO NOTHING"
            ), {"code": code, "description": desc, "short_description": short_desc,
                "category": None, "code_prefix": prefix})
        db.commit()
        print(f"   ✅ Loaded {len(sample_codes)} sample ICD-10-CM codes (fallback)")
        return len(sample_codes)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# LOAD ICD-10-CM CODES
# ─────────────────────────────────────────────────────────────────────────────
def load_icd10_codes():
    """
    Download and load ICD-10-CM FY2026 diagnosis codes from CMS.

    CMS publishes the ICD-10-CM order file as a free ZIP download.
    The order file is a fixed-width text file with:
    - Column 1-5:   Code (right-padded with spaces)
    - Column 7:     "1" = header code, "0" = billable code
    - Column 8-14:  Short description (60 chars)
    - Column 15-:   Long description

    We only load billable codes (column 7 = "0") — ~77,000 of them.

    INPUT:  None (downloads from CMS if not cached)
    OUTPUT: Populates icd10_codes table in PostgreSQL
    """
    print("\n📋 Loading ICD-10-CM codes...")

    # CMS FY2026 ICD-10-CM download URL (updated)
    ICD10_URL = (
        "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order-april-1-2026.zip"
    )

    # Try to download — if it fails, provide manual instructions
    try:
        download_file(ICD10_URL, ICD10_ZIP_PATH, "ICD-10-CM FY2026")
    except Exception:
        print("""
   MANUAL DOWNLOAD INSTRUCTIONS FOR ICD-10-CM:
   1. Go to: https://www.cms.gov/medicare/coding-billing/icd-10-codes
   2. Find "2026 ICD-10-CM" section
   3. Download the ZIP file for "Code Descriptions in Tabular Order"
   4. Save it as: data/cms_codes/icd10cm_tabular_2026.zip
   5. Re-run this script
        """)
        return _load_icd10_sample_data()

    # Extract and parse the order file
    codes_loaded = 0
    try:
        with zipfile.ZipFile(ICD10_ZIP_PATH, "r") as zf:
            # Find the order file (usually ends in 'order_2026.txt' or similar)
            order_files = [f for f in zf.namelist()
                          if "order" in f.lower() and f.endswith(".txt")]

            if not order_files:
                # Try alternative: look for any .txt file
                txt_files = [f for f in zf.namelist() if f.endswith(".txt")]
                print(f"   Files in ZIP: {zf.namelist()}")
                if not txt_files:
                    print("   ❌ Could not find ICD-10-CM order file in ZIP")
                    return 0
                order_files = txt_files

            order_file = order_files[0]
            print(f"   Parsing: {order_file}")

            icd10_records = []
            with zf.open(order_file) as f:
                for line in f:
                    try:
                        # Decode the line (CMS files are ASCII/Latin-1)
                        line_str = line.decode("latin-1").rstrip("\n")

                        # The ICD-10-CM order file format:
                        # Chars 1-5:   Order number (we ignore this)
                        # Chars 7-13:  ICD-10-CM code (7 chars, space-padded)
                        # Char 14:     Header/Billable indicator (1=header, 0=billable)
                        # Chars 16-76: Short description (61 chars)
                        # Chars 78-:   Long description

                        if len(line_str) < 20:
                            continue

                        # Extract code (remove spaces)
                        code_raw = line_str[6:13].strip()
                        if not code_raw:
                            continue

                        # Only load billable codes (header codes aren't real diagnoses)
                        is_billable = line_str[14].strip() == "0"
                        if not is_billable:
                            continue

                        # Format the code with a period (E119 → E11.9)
                        # ICD-10-CM codes: letter + 2 digits + optional decimal
                        if len(code_raw) > 3:
                            formatted_code = code_raw[:3] + "." + code_raw[3:]
                        else:
                            formatted_code = code_raw

                        # Short description (chars 16-76)
                        short_desc = line_str[16:77].strip() if len(line_str) > 16 else ""

                        # Long description (chars 78 onward)
                        long_desc = line_str[77:].strip() if len(line_str) > 77 else short_desc

                        # Use long description as the main description
                        description = long_desc if long_desc else short_desc
                        if not description:
                            continue

                        # Code prefix = first 3 characters (e.g. "E11" for all Type 2 diabetes)
                        code_prefix = formatted_code[:3]

                        icd10_records.append({
                            "code": formatted_code,
                            "description": description[:500],
                            "short_description": short_desc[:200] if short_desc else None,
                            "category": None,  # We'll set this separately if needed
                            "code_prefix": code_prefix,
                        })

                    except Exception:
                        continue  # Skip malformed lines

            if not icd10_records:
                print("   ❌ No ICD-10 codes parsed. File format may have changed.")
                print("   Try checking the raw file format and update parsing logic.")
                return 0

            print(f"   Parsed {len(icd10_records):,} billable ICD-10-CM codes")

            # Bulk insert into database
            db = SessionLocal()
            try:
                # Clear existing data first (for re-runs)
                db.query(ICD10Code).delete()
                db.commit()

                # Insert in batches of 1000 for performance
                batch_size = 1000
                for i in range(0, len(icd10_records), batch_size):
                    batch = icd10_records[i:i + batch_size]
                    db.bulk_insert_mappings(ICD10Code, batch)
                    db.commit()

                    if (i // batch_size) % 10 == 0:
                        print(f"   Inserted {min(i + batch_size, len(icd10_records)):,} / "
                              f"{len(icd10_records):,} ICD-10 codes...")

                codes_loaded = len(icd10_records)
                print(f"   ✅ ICD-10-CM: {codes_loaded:,} codes loaded")

            finally:
                db.close()

    except Exception as e:
        print(f"   ❌ Error loading ICD-10 codes: {e}")
        import traceback
        traceback.print_exc()
        return _load_icd10_sample_data()

    return codes_loaded


# ─────────────────────────────────────────────────────────────────────────────
# LOAD HCPCS LEVEL II CODES
# ─────────────────────────────────────────────────────────────────────────────
def load_hcpcs_codes():
    """
    Download and load HCPCS Level II codes from CMS.

    CMS publishes the HCPCS Alpha-Numeric file as a free annual ZIP.
    The file is a pipe-delimited or fixed-width text file containing:
    - HCPCS code (5 characters: 1 letter + 4 digits)
    - Long description
    - Short description
    - Effective date (when code became active)
    - Termination date (if code was retired)

    Key categories we care about:
    - J codes: Drug codes (J0696 = cefazolin, J1815 = insulin)
    - A codes: Supplies (A4253 = glucose test strips)
    - E codes: Durable Medical Equipment (E0110 = crutches)

    INPUT:  None (downloads from CMS if not cached)
    OUTPUT: Populates hcpcs_codes table in PostgreSQL
    """
    print("\n💊 Loading HCPCS Level II codes...")

    # CMS HCPCS Annual file URL (2026)
    # If URL fails: go to cms.gov → Medicare → HCPCS → Annual Update Files
    HCPCS_URL = (
        "https://www.cms.gov/files/zip/2026-alpha-numeric-hcpcs-file-update.zip"
    )

    try:
        download_file(HCPCS_URL, HCPCS_ZIP_PATH, "HCPCS Level II 2026")
    except Exception:
        print("""
   MANUAL DOWNLOAD INSTRUCTIONS FOR HCPCS:
   1. Go to: https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update
   2. Download the latest "Alpha-Numeric HCPCS File" ZIP
   3. Save it as: data/cms_codes/hcpcs_2026.zip
   4. Re-run this script

   ALTERNATIVE: Use the 2025 file if 2026 isn't available yet.
        """)
        # Load sample data so the app still works
        return _load_hcpcs_sample_data()

    codes_loaded = 0
    try:
        with zipfile.ZipFile(HCPCS_ZIP_PATH, "r") as zf:
            print(f"   Files in ZIP: {zf.namelist()}")

            # Look for the main HCPCS data file
            # Typically named HCPC2026_ANWEB.txt or similar
            data_files = [f for f in zf.namelist()
                         if ("anweb" in f.lower() or "hcpc" in f.lower())
                         and f.endswith(".txt") and not f.startswith("__")]

            if not data_files:
                data_files = [f for f in zf.namelist() if f.endswith(".txt")]

            if not data_files:
                print("   ❌ Could not find HCPCS data file in ZIP")
                return _load_hcpcs_sample_data()

            data_file = data_files[0]
            print(f"   Parsing: {data_file}")

            hcpcs_records = []
            with zf.open(data_file) as f:
                # HCPCS file is typically pipe-delimited or fixed-width
                # Try reading the first line to detect format
                first_line = f.readline().decode("latin-1")
                f.seek(0)

                if "|" in first_line or "\t" in first_line:
                    # Pipe or tab delimited
                    sep = "|" if "|" in first_line else "\t"
                    df = pd.read_csv(
                        f, sep=sep, dtype=str, encoding="latin-1",
                        on_bad_lines="skip", low_memory=False
                    )
                    # Try to identify the relevant columns
                    df.columns = [c.strip().upper() for c in df.columns]

                    # Common column names in CMS HCPCS file
                    code_col = next((c for c in df.columns if "HCPC" in c and "CODE" in c), df.columns[0])
                    desc_col = next((c for c in df.columns if "LONG" in c and "DESC" in c),
                                   next((c for c in df.columns if "DESC" in c), df.columns[1]))
                    short_col = next((c for c in df.columns if "SHORT" in c and "DESC" in c), None)
                    eff_col = next((c for c in df.columns if "EFF" in c), None)
                    term_col = next((c for c in df.columns if "TERM" in c), None)

                    for _, row in df.iterrows():
                        code = str(row.get(code_col, "")).strip()
                        desc = str(row.get(desc_col, "")).strip()
                        if not code or len(code) != 5 or not desc or desc == "nan":
                            continue

                        hcpcs_records.append({
                            "code": code,
                            "description": desc[:500],
                            "category": code[0].upper() if code else None,
                            "effective_date": str(row.get(eff_col, "")).strip() if eff_col else None,
                            "termination_date": str(row.get(term_col, "")).strip() if term_col else None,
                        })
                else:
                    # Fixed-width format
                    for line in f:
                        line_str = line.decode("latin-1").rstrip("\n")
                        if len(line_str) < 6:
                            continue
                        code = line_str[:5].strip()
                        desc = line_str[5:].strip()
                        if not code or not desc:
                            continue
                        hcpcs_records.append({
                            "code": code,
                            "description": desc[:500],
                            "category": code[0].upper() if code else None,
                            "effective_date": None,
                            "termination_date": None,
                        })

            if not hcpcs_records:
                print("   ❌ No HCPCS codes parsed.")
                return _load_hcpcs_sample_data()

            print(f"   Parsed {len(hcpcs_records):,} HCPCS codes")

            db = SessionLocal()
            try:
                db.query(HCPCSCode).delete()
                db.commit()

                batch_size = 500
                for i in range(0, len(hcpcs_records), batch_size):
                    batch = hcpcs_records[i:i + batch_size]
                    db.bulk_insert_mappings(HCPCSCode, batch)
                    db.commit()

                codes_loaded = len(hcpcs_records)
                print(f"   ✅ HCPCS Level II: {codes_loaded:,} codes loaded")

            finally:
                db.close()

    except Exception as e:
        print(f"   ❌ Error loading HCPCS codes: {e}")
        return _load_hcpcs_sample_data()

    return codes_loaded


def _load_hcpcs_sample_data():
    """
    Fallback: load a curated set of common HCPCS codes manually.
    Uses direct SQL DELETE to avoid ORM relationship resolution issues.
    """
    print("   ℹ️  Loading sample HCPCS codes (fallback mode)...")
    sample_codes = [
        # J-codes: Drug injections
        ("J0696", "Injection, cefazolin sodium, 500 mg", "J", "20260101", None),
        ("J1815", "Injection, insulin, per 5 units", "J", "20260101", None),
        ("J0290", "Injection, ampicillin sodium, 500 mg", "J", "20260101", None),
        ("J2250", "Injection, midazolam hydrochloride, per 1 mg", "J", "20260101", None),
        ("J3490", "Unclassified drugs", "J", "20260101", None),
        ("J1644", "Injection, heparin sodium, per 1000 units", "J", "20260101", None),
        ("J2469", "Injection, piperacillin sodium/tazobactam sodium, 1 g/0.125 mg", "J", "20260101", None),
        ("J0878", "Injection, daptomycin, 1 mg", "J", "20260101", None),
        # A-codes: Supplies
        ("A4253", "Blood glucose test or reagent strips for home blood glucose monitor", "A", "20260101", None),
        ("A9150", "Nonprescription drugs", "A", "20260101", None),
        ("A6545", "Zinc-water dressings, sterile, each dressing", "A", "20260101", None),
        # E-codes: DME
        ("E0110", "Crutches, underarm, wood, adjustable or fixed, pair, with pads, tips, and handgrips", "E", "20260101", None),
        ("E0114", "Crutches, underarm, other than wood, adjustable or fixed, pair, with pads, tips, and handgrips", "E", "20260101", None),
        ("E0601", "Continuous positive airway pressure (CPAP) device", "E", "20260101", None),
        ("E0627", "Seat lift mechanism, electric, any type", "E", "20260101", None),
        ("E1390", "Oxygen concentrator, single delivery port", "E", "20260101", None),
    ]

    db = SessionLocal()
    try:
        # Use direct SQL to avoid ORM relationship resolution
        db.execute(text("DELETE FROM hcpcs_codes"))
        db.commit()
        records = [
            {"code": c, "description": d, "category": cat,
             "effective_date": eff, "termination_date": term}
            for c, d, cat, eff, term in sample_codes
        ]
        for r in records:
            db.execute(text(
                "INSERT INTO hcpcs_codes (code, description, category, effective_date, termination_date) "
                "VALUES (:code, :description, :category, :effective_date, :termination_date) "
                "ON CONFLICT (code) DO NOTHING"
            ), r)
        db.commit()
        print(f"   ✅ Loaded {len(sample_codes)} sample HCPCS codes (fallback)")
        return len(sample_codes)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# LOAD CPT / MPFS CODES
# ─────────────────────────────────────────────────────────────────────────────
def load_cpt_codes():
    """
    Download and load CPT codes from CMS Medicare Physician Fee Schedule (MPFS).

    IMPORTANT LEGAL NOTE:
    The AMA (American Medical Association) owns copyright on CPT code descriptions.
    A full CPT license costs thousands of dollars per year.

    HOWEVER: CMS publishes the Medicare Physician Fee Schedule (MPFS) which
    contains CPT codes with CMS's own descriptions and RVU/payment data.
    CMS descriptions are public domain — FREE to use.

    The MPFS XLSX file contains:
    - HCPCS code (= CPT code for physician services)
    - CMS description (public domain)
    - Work RVU (Relative Value Unit — measure of physician work)
    - Non-facility payment amount (what Medicare pays in an office setting)

    INPUT:  None (downloads from CMS if not cached)
    OUTPUT: Populates cpt_codes table in PostgreSQL
    """
    print("\n🏥 Loading CPT codes from CMS Medicare Physician Fee Schedule...")

    # CMS MPFS 2026 download URL
    # If this fails: go to cms.gov → Medicare → Payment → Physician Fee Schedule
    MPFS_URL = (
        "https://www.cms.gov/files/zip/2026-medicare-physician-fee-schedule-relative-value-file.zip"
    )

    try:
        download_file(MPFS_URL, MPFS_ZIP_PATH, "CMS MPFS 2026 (CPT codes)")
    except Exception:
        print("""
   MANUAL DOWNLOAD INSTRUCTIONS FOR CPT/MPFS:
   1. Go to: https://www.cms.gov/medicare/payment/fee-schedules/physician
   2. Find "CY 2026 Medicare Physician Fee Schedule" section
   3. Download "Physician Fee Schedule Relative Value Files" ZIP
   4. Save as: data/cms_codes/mpfs_2026.zip
   5. Re-run this script
        """)
        return _load_cpt_sample_data()

    codes_loaded = 0
    try:
        with zipfile.ZipFile(MPFS_ZIP_PATH, "r") as zf:
            print(f"   Files in ZIP: {zf.namelist()}")

            # Look for the main PPRRVU file (Physician/Practitioner RVU)
            data_files = [f for f in zf.namelist()
                         if ("pprrvu" in f.lower() or "rvu" in f.lower() or "pfs" in f.lower())
                         and (f.endswith(".xlsx") or f.endswith(".csv") or f.endswith(".txt"))]

            if not data_files:
                data_files = [f for f in zf.namelist()
                             if f.endswith(".xlsx") or f.endswith(".csv")]

            if not data_files:
                print("   ❌ Could not find MPFS data file in ZIP")
                return _load_cpt_sample_data()

            data_file = data_files[0]
            print(f"   Parsing: {data_file}")

            # Extract to temp location for pandas to read
            zf.extract(data_file, DATA_DIR)
            extracted_path = DATA_DIR / data_file

            if data_file.endswith(".xlsx"):
                # MPFS XLSX typically has header rows to skip
                # Try reading and detect the header
                df = pd.read_excel(extracted_path, dtype=str, header=None)

                # Find the actual header row (look for "HCPCS" in any row)
                header_row = 0
                for i, row in df.iterrows():
                    if any("HCPC" in str(v).upper() for v in row.values if pd.notna(v)):
                        header_row = i
                        break

                df = pd.read_excel(extracted_path, dtype=str, header=header_row)
                df.columns = [str(c).strip().upper().replace(" ", "_") for c in df.columns]

            elif data_file.endswith(".csv"):
                df = pd.read_csv(extracted_path, dtype=str, encoding="latin-1",
                                on_bad_lines="skip")
                df.columns = [str(c).strip().upper().replace(" ", "_") for c in df.columns]
            else:
                return _load_cpt_sample_data()

            # Identify relevant columns
            print(f"   Columns found: {list(df.columns)[:10]}...")

            code_col = next((c for c in df.columns if "HCPCS" in c or "CPT" in c), df.columns[0])
            desc_col = next((c for c in df.columns
                           if "DESCRIPTION" in c or "DESCRIPTOR" in c or "DESC" in c),
                           None)
            rvu_col = next((c for c in df.columns if "WORK_RVU" in c or "WRKRVU" in c), None)
            payment_col = next((c for c in df.columns if "NON_FAC" in c and "PE" not in c), None)

            cpt_records = []
            for _, row in df.iterrows():
                code = str(row.get(code_col, "")).strip()
                if not code or len(code) < 4 or code == "nan":
                    continue

                desc = str(row.get(desc_col, "")).strip() if desc_col else ""
                if not desc or desc == "nan":
                    continue

                try:
                    rvu = float(str(row.get(rvu_col, "")).strip()) if rvu_col else None
                except (ValueError, TypeError):
                    rvu = None

                try:
                    payment = float(str(row.get(payment_col, "")).strip()) if payment_col else None
                except (ValueError, TypeError):
                    payment = None

                cpt_records.append({
                    "code": code[:20],
                    "description": desc[:500],
                    "rvu": rvu,
                    "payment_amount": payment,
                    "category": None,
                })

            # Clean up extracted file
            if extracted_path.exists():
                extracted_path.unlink()

            if not cpt_records:
                return _load_cpt_sample_data()

            print(f"   Parsed {len(cpt_records):,} CPT/MPFS codes")

            db = SessionLocal()
            try:
                db.query(CPTCode).delete()
                db.commit()

                batch_size = 500
                for i in range(0, len(cpt_records), batch_size):
                    batch = cpt_records[i:i + batch_size]
                    db.bulk_insert_mappings(CPTCode, batch)
                    db.commit()

                codes_loaded = len(cpt_records)
                print(f"   ✅ CPT/MPFS: {codes_loaded:,} codes loaded")

            finally:
                db.close()

    except Exception as e:
        print(f"   ❌ Error loading CPT codes: {e}")
        import traceback
        traceback.print_exc()
        return _load_cpt_sample_data()

    return codes_loaded


def _load_cpt_sample_data():
    """
    Fallback: load a curated set of common CPT codes manually.
    Covers E&M codes, common procedures, and diagnostics used in
    the kinds of encounters MediSight+ will handle.
    """
    print("   ℹ️  Loading sample CPT codes (fallback mode)...")
    sample_codes = [
        # E&M Office Visit codes (most commonly used)
        ("99202", "Office or other outpatient visit, new patient, 15-29 min", 0.93, 73.31),
        ("99203", "Office or other outpatient visit, new patient, 30-44 min", 1.60, 126.38),
        ("99204", "Office or other outpatient visit, new patient, 45-59 min", 2.60, 205.26),
        ("99205", "Office or other outpatient visit, new patient, 60-74 min", 3.50, 276.45),
        ("99211", "Office or other outpatient visit, established patient, minimal", 0.18, 24.20),
        ("99212", "Office or other outpatient visit, established patient, 10-19 min", 0.70, 55.36),
        ("99213", "Office or other outpatient visit, established patient, 20-29 min", 1.30, 102.69),
        ("99214", "Office or other outpatient visit, established patient, 30-39 min", 1.92, 151.73),
        ("99215", "Office or other outpatient visit, established patient, 40-54 min", 2.80, 221.20),
        # Common diagnostics
        ("71046", "Radiologic exam, chest, 2 views", 0.22, 37.17),
        ("71048", "Radiologic exam, chest, 4 or more views", 0.32, 48.59),
        ("93000", "Electrocardiogram with interpretation and report", 0.17, 27.41),
        ("85025", "Blood count, complete (CBC), automated", 0.00, 11.26),
        ("80053", "Comprehensive metabolic panel", 0.00, 14.01),
        ("82947", "Glucose; quantitative, blood (except reagent strip)", 0.00, 7.32),
        ("83036", "Hemoglobin A1c level", 0.00, 15.00),
        # Common procedures
        ("99223", "Initial hospital care, high complexity", 3.86, 304.97),
        ("99232", "Subsequent hospital care, moderate complexity", 1.39, 109.75),
        ("99283", "Emergency department visit, moderate severity", 1.42, 112.15),
        ("99285", "Emergency department visit, high severity", 2.70, 213.26),
        ("36415", "Collection of venous blood by venipuncture", 0.00, 3.00),
        ("90471", "Immunization administration", 0.17, 25.00),
        ("90732", "Pneumococcal polysaccharide vaccine", 0.00, 67.00),
        ("90658", "Influenza virus vaccine, trivalent", 0.00, 19.00),
        ("11721", "Debridement of nail, 6 or more", 0.61, 48.24),
        ("97110", "Therapeutic exercises, 15 min", 0.45, 35.56),
    ]

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM cpt_codes"))
        db.commit()
        records = [
            {"code": c, "description": d, "rvu": r, "payment_amount": p, "category": None}
            for c, d, r, p in sample_codes
        ]
        for r in records:
            db.execute(text(
                "INSERT INTO cpt_codes (code, description, rvu, payment_amount, category) "
                "VALUES (:code, :description, :rvu, :payment_amount, :category) "
                "ON CONFLICT (code) DO NOTHING"
            ), r)
        db.commit()
        print(f"   ✅ Loaded {len(sample_codes)} sample CPT codes (fallback)")
        return len(sample_codes)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────
def verify_loading():
    """
    After loading, run quick queries to verify the data is correct.
    Prints a summary table showing what was loaded.
    """
    print("\n🔍 Verifying loaded data...")
    db = SessionLocal()
    try:
        icd10_count = db.query(ICD10Code).count()
        hcpcs_count = db.query(HCPCSCode).count()
        cpt_count = db.query(CPTCode).count()

        print(f"\n   {'Table':<20} {'Count':>10}")
        print(f"   {'─'*30}")
        print(f"   {'icd10_codes':<20} {icd10_count:>10,}")
        print(f"   {'hcpcs_codes':<20} {hcpcs_count:>10,}")
        print(f"   {'cpt_codes':<20} {cpt_count:>10,}")

        # Sample lookups to verify data quality
        print("\n   Sample ICD-10 codes:")
        for code in db.query(ICD10Code).filter(ICD10Code.code.like("E11%")).limit(3).all():
            print(f"   {code.code:<12} {code.description[:60]}")

        print("\n   Sample HCPCS J-codes (drugs):")
        for code in db.query(HCPCSCode).filter(HCPCSCode.category == "J").limit(3).all():
            print(f"   {code.code:<12} {code.description[:60]}")

        print("\n   Sample CPT E&M codes:")
        for code in db.query(CPTCode).filter(CPTCode.code.like("992%")).limit(3).all():
            print(f"   {code.code:<12} {code.description[:60]}")

        if icd10_count > 0 and hcpcs_count > 0 and cpt_count > 0:
            print("\n   ✅ All billing code tables loaded and verified!")
        else:
            print("\n   ⚠️  Some tables are empty. Check the output above for errors.")

    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*60)
    print("🏥  MediSight+ Billing Code Ingestion")
    print("="*60)
    print(f"Data directory: {DATA_DIR}")
    print("This will download ~50MB of data from CMS on first run.")
    print("Subsequent runs use cached files.")
    print()

    # Step 1: Ensure tables exist
    print("Step 1: Creating database tables...")
    create_all_tables()

    # Step 2: Enable fuzzy search extension
    print("\nStep 2: Setting up PostgreSQL extensions...")
    enable_trigram_extension()

    # Step 3: Load all code sets
    print("\nStep 3: Loading billing code sets...")
    icd10_n = load_icd10_codes()
    hcpcs_n = load_hcpcs_codes()
    cpt_n = load_cpt_codes()

    # Step 4: Verify
    verify_loading()

    print("\n" + "="*60)
    print("✅ Billing code ingestion complete!")
    print(f"   ICD-10-CM codes: {icd10_n:,}")
    print(f"   HCPCS Level II:  {hcpcs_n:,}")
    print(f"   CPT/MPFS codes:  {cpt_n:,}")
    print()
    print("Next steps:")
    print("  1. Start the API: uvicorn api.main:app --reload")
    print("  2. Test lookup:   curl 'http://localhost:8000/billing/lookup/icd10?query=diabetes'")
    print("="*60)
