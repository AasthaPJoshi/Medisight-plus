"""
FILE: models/database.py
========================
WHAT THIS FILE IS:
    The database connection layer. This file creates the SQLAlchemy engine
    (which is the object that knows how to talk to PostgreSQL) and provides
    a 'session' factory that every API route will use to read/write data.

CONCEPT:
    SQLAlchemy is Python's most popular ORM (Object Relational Mapper).
    Instead of writing raw SQL like "SELECT * FROM users", you write
    Python objects and SQLAlchemy translates them to SQL automatically.

    SessionLocal = a factory that produces database sessions
    engine       = the actual connection to PostgreSQL
    Base         = the parent class all our database models will inherit from

INPUT:  DATABASE_URL from .env file (e.g. postgresql://user:pass@localhost/db)
OUTPUT: engine, SessionLocal, Base — imported by every other file that touches the DB

HOW TO TEST THIS FILE:
    python3 -c "from models.database import engine; print('DB connected:', engine.url)"
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables from .env file
# This must happen before we read os.getenv()
load_dotenv()

# Read the database URL from .env
# Format: postgresql://username:password@host:port/database_name
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env file. Check your .env.")

# Create the SQLAlchemy engine
# pool_pre_ping=True means: test the connection before each use
#   (prevents errors when PostgreSQL has closed an idle connection)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,  # Set to True if you want to see every SQL query printed in Terminal
)

# SessionLocal is a factory — call SessionLocal() to get a new database session
# autocommit=False: changes are NOT saved until you explicitly call session.commit()
# autoflush=False: SQLAlchemy won't auto-send pending changes before every query
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base is the parent class for all our ORM models
# When a class inherits from Base, SQLAlchemy knows to treat it as a database table
Base = declarative_base()


def get_db():
    """
    FUNCTION: get_db
    ----------------
    A FastAPI dependency that provides a database session to each API route.

    Usage in a route:
        @app.get("/patients")
        def get_patients(db: Session = Depends(get_db)):
            return db.query(User).all()

    The 'yield' pattern (generator function) ensures:
    1. A fresh session is created for each request
    2. The session is ALWAYS closed after the request, even if an error occurs
    3. This prevents connection leaks (running out of database connections)

    INPUT:  Nothing
    OUTPUT: A SQLAlchemy Session object (yielded to the route handler)
    """
    db = SessionLocal()
    try:
        yield db          # Give the session to the route
    finally:
        db.close()        # Always close, no matter what happens


def test_connection():
    """
    FUNCTION: test_connection
    -------------------------
    Quick sanity check — run this to confirm PostgreSQL is reachable.
    Run from Terminal: python3 -c "from models.database import test_connection; test_connection()"

    INPUT:  Nothing (uses DATABASE_URL from .env)
    OUTPUT: Prints success message or raises an error with details
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✅ PostgreSQL connected successfully!")
            print(f"   Version: {version[:50]}...")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("   Check: Is PostgreSQL running? (brew services list)")
        print("   Check: Is DATABASE_URL correct in .env?")
        raise
