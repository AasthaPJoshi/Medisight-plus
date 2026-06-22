"""
FILE: api/main.py
=================
WHAT THIS FILE IS:
    The entry point for the entire FastAPI application.
    This file creates the app, registers all routers, adds CORS,
    and defines a health check endpoint.

CONCEPT — FastAPI App Structure:
    FastAPI uses a 'router' pattern. Each feature area (auth, patients,
    doctors, billing) has its own router defined in a separate file.
    This main.py imports and mounts all those routers onto the main app.

    When you run: uvicorn api.main:app --reload
    - 'api.main' tells Python to look in the api/main.py file
    - ':app' is the variable name of the FastAPI instance in that file
    - '--reload' auto-restarts when you save any file (great for development)

CORS (Cross-Origin Resource Sharing):
    Your React frontend runs on http://localhost:5173
    Your FastAPI backend runs on http://localhost:8000
    Browsers block requests between different origins by default.
    CORSMiddleware tells the browser "it's OK, I trust these origins."

HOW TO RUN:
    Make sure your venv is active, then:
        uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

    Then open: http://localhost:8000/docs
    This shows the Swagger UI — an interactive API documentation page
    where you can test every endpoint without writing any code.

HOW TO TEST ALL ROUTES AT ONCE:
    http://localhost:8000/docs  → Try every route interactively
    http://localhost:8000/redoc → Alternative documentation view
    http://localhost:8000/health → Quick health check
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Import all routers
from api.auth import router as auth_router
from api.patients import router as patients_router
from api.doctors import router as doctors_router
from api.billing import router as billing_router
from api.rag_routes import router as rag_router
from api.admin import router as admin_router
from api.analytics import router as analytics_router


# Load environment variables
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# CREATE FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MediSight+ API",
    description=(
        "Clinical AI Platform with ICD-10 / CPT / HCPCS Claims Intelligence.\n\n"
        "Three-layer system:\n"
        "- **Patient Layer**: Symptom logging and plain-English health summaries\n"
        "- **Doctor Layer**: AI-assisted differential diagnosis with PubMed citations\n"
        "- **Billing Layer**: ICD-10 / CPT / HCPCS code suggestion with denial risk detection\n\n"
        "Use the **Authorize** button to enter your JWT token before testing protected routes."
    ),
    version="1.0.0",
    # Swagger UI settings
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── RATE LIMITING ─────────────────────────────────────────────────────────────
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─────────────────────────────────────────────────────────────────────────────
# CORS MIDDLEWARE
# Allows the React frontend (port 5173) to call this API (port 8000)
# In production, replace "*" with your actual Vercel domain
# ─────────────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # React dev server (Vite default port)
        "http://localhost:3000",   # Alternative React port
        "http://localhost:8000",   # For testing from same origin
        "*",                       # Allow all during development
        # In production, replace "*" with: "https://your-app.vercel.app"
    ],
    allow_credentials=True,         # Allows cookies and auth headers
    allow_methods=["*"],            # Allow GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],            # Allow Authorization, Content-Type, etc.
)


# ─────────────────────────────────────────────────────────────────────────────
# MOUNT ALL ROUTERS
# Each router adds its own group of routes to the main app
# ─────────────────────────────────────────────────────────────────────────────

# Authentication: /auth/register, /auth/login, /auth/me
app.include_router(auth_router)

# Patient routes: /patients/symptoms, /patients/timeline, /patients/profile
app.include_router(patients_router)

# Doctor routes: /doctors/patients, /doctors/notes, /doctors/notes/{id}/lock
app.include_router(doctors_router)

# Billing routes: /billing/lookup/*, /billing/encounters/*
app.include_router(billing_router)

app.include_router(rag_router)

app.include_router(admin_router)

app.include_router(analytics_router)

# ─────────────────────────────────────────────────────────────────────────────
# STARTUP EVENT
# Runs once when the server starts — sets up database tables
# ─────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """
    Runs automatically when uvicorn starts the app.
    Creates database tables if they don't exist yet.
    Safe to run multiple times (won't drop existing data).
    """
    print("\n" + "="*60)
    print("🏥  MediSight+ API Starting...")
    print("="*60)

    # Import here to avoid circular imports
    from models.orm_models import create_all_tables
    from models.database import test_connection

    # Verify database is reachable
    test_connection()

    # Create all tables
    create_all_tables()

    print("\n✅ All systems ready!")
    print(f"   Swagger UI: http://localhost:8000/docs")
    print(f"   Health check: http://localhost:8000/health")
    print("="*60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# ROOT ROUTE
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Root"])
def root():
    """
    ROUTE: GET /
    Returns basic API info. Useful to confirm the server is running.

    TEST: curl http://localhost:8000/
    """
    return {
        "api": "MediSight+ Clinical AI Platform",
        "version": "1.0.0",
        "status": "running",
        "docs": "http://localhost:8000/docs",
        "layers": {
            "patient": "/patients/*",
            "doctor": "/doctors/*",
            "billing": "/billing/*",
            "auth": "/auth/*",
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK ROUTE
# Used by Railway/deployment platforms to verify the app is alive
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check():
    """
    ROUTE: GET /health
    ------------------
    Returns the health status of the application and its dependencies.
    Railway and other platforms ping this to decide if the app is healthy.

    TEST: curl http://localhost:8000/health
    """
    from models.database import engine
    from sqlalchemy import text

    # Check database connection
    db_status = "unknown"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"

    # Check Redis connection
    redis_status = "unknown"
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"error: {str(e)[:50]}"

    overall = "healthy" if db_status == "healthy" else "degraded"

    return {
        "status": overall,
        "version": "1.0.0",
        "dependencies": {
            "postgresql": db_status,
            "redis": redis_status,
        },
    }
