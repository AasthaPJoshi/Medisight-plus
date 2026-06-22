"""
FILE: api/auth.py
=================
WHAT THIS FILE IS:
    Authentication routes — register new users, login, and decode JWT tokens.

CONCEPT — JWT (JSON Web Token):
    When a user logs in, we give them a JWT token (a long encoded string).
    Every future request includes this token in the header:
        Authorization: Bearer eyJhbGciOiJIUzI1...

    The server decodes this token (without hitting the database) to know:
    - Who is making the request (user_id)
    - What they're allowed to do (role: patient / doctor / billing)
    - When the token expires (exp claim)

    This is stateless auth — no session stored on the server.

ROUTES IN THIS FILE:
    POST /auth/register   → Create new user account (patient/doctor)
    POST /auth/login      → Login, returns JWT token
    GET  /auth/me         → Returns current user info from JWT

INPUT:  UserRegister / UserLogin JSON body (defined in models/schemas.py)
OUTPUT: TokenResponse (JWT token + role + user_id)

HOW TO TEST:
    # After running the app (uvicorn api.main:app --reload):
    # Open http://localhost:8000/docs in browser
    # Try POST /auth/register then POST /auth/login
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

from models.database import get_db
from models.orm_models import User, Patient, UserRole
from models.schemas import UserRegister, UserLogin, TokenResponse, UserResponse

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

# APIRouter groups all auth routes together
# prefix="/auth" means all routes here start with /auth
router = APIRouter(prefix="/auth", tags=["Authentication"])

# CryptContext handles bcrypt password hashing
# bcrypt is one-way: you can verify a password against a hash,
# but you CANNOT reverse the hash to get the original password
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTPBearer extracts the JWT token from the Authorization header
security = HTTPBearer()

# Load JWT settings from environment
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET not set in .env file!")


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """
    Convert a plain text password into a bcrypt hash.
    INPUT:  "mypassword123"
    OUTPUT: "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5oZVyS..."
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check if a plain text password matches a stored bcrypt hash.
    INPUT:  "mypassword123", "$2b$12$..."
    OUTPUT: True (if match) or False (if wrong password)
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_jwt_token(user_id: int, email: str, role: str) -> str:
    """
    Create a JWT token that encodes user identity and role.

    The token payload (called 'claims') contains:
    - sub: subject = user_id (standard JWT claim)
    - email: user's email
    - role: "patient", "doctor", or "billing"
    - exp: expiration timestamp (1440 minutes = 24 hours from now)

    INPUT:  user_id=1, email="patient@test.com", role="patient"
    OUTPUT: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIi..."
    """
    expires_at = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),    # 'sub' is standard JWT for "subject" (the user)
        "email": email,
        "role": role,
        "exp": expires_at,
    }
    # jwt.encode signs the payload with our secret key
    # Anyone with the secret can verify the token, but not forge one
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def decode_jwt_token(token: str) -> dict:
    """
    Decode and verify a JWT token. Raises exception if invalid or expired.

    INPUT:  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    OUTPUT: {"sub": "1", "email": "...", "role": "patient", "exp": ...}
            OR raises HTTPException 401 if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: get_current_user
# Used in every protected route to identify WHO is making the request
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI dependency: extracts and validates JWT, returns the User object.

    Usage in a protected route:
        @router.get("/me")
        def get_me(current_user: User = Depends(get_current_user)):
            return current_user

    INPUT:  JWT token from Authorization header
    OUTPUT: User ORM object from database
            OR raises 401 Unauthorized
    """
    # Extract the raw token string from "Bearer <token>"
    token = credentials.credentials

    # Decode the JWT to get user info
    payload = decode_jwt_token(token)
    user_id = int(payload.get("sub"))

    # Fetch the user from database to confirm they still exist
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found — account may have been deleted",
        )
    return user


def require_role(*allowed_roles: str):
    """
    ROLE-BASED ACCESS CONTROL factory.
    Returns a dependency that checks the current user has an allowed role.

    Usage:
        @router.post("/notes")
        def create_note(current_user: User = Depends(require_role("doctor"))):
            ...

        @router.get("/billing")
        def view_billing(current_user: User = Depends(require_role("doctor", "billing"))):
            ...

    INPUT:  One or more role strings ("patient", "doctor", "billing")
    OUTPUT: A dependency function that returns the user if authorized,
            or raises 403 Forbidden if the role doesn't match
    """
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {', '.join(allowed_roles)}. "
                       f"Your role: {current_user.role.value}",
            )
        return current_user
    return dependency


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    ROUTE: POST /auth/register
    --------------------------
    Create a new user account and return a JWT token immediately.

    The user is logged in automatically after registration.
    If role='patient', a Patient profile row is also created.

    INPUT (JSON body):
        {
          "email": "patient@test.com",
          "full_name": "Jane Smith",
          "password": "securepass123",
          "role": "patient"
        }

    OUTPUT:
        {
          "access_token": "eyJ...",
          "token_type": "bearer",
          "role": "patient",
          "user_id": 1,
          "full_name": "Jane Smith"
        }

    ERRORS:
        409 Conflict  — email already registered
        422 Unprocessable — validation error (bad email, password too short, etc.)
    """
    # Check if email is already in use
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user_data.email}' is already registered. Please login instead.",
        )

    # Create the User row with a hashed password
    new_user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hash_password(user_data.password),
        role=UserRole(user_data.role),
    )
    db.add(new_user)
    db.flush()  # Flush to get the new_user.id before commit

    # If registering as a patient, create the Patient profile automatically
    if user_data.role == "patient":
        patient_profile = Patient(user_id=new_user.id)
        db.add(patient_profile)

    db.commit()
    db.refresh(new_user)

    print(f"✅ New user registered: {new_user.email} (role: {new_user.role})")

    # Return a JWT token so the user is immediately logged in
    token = create_jwt_token(new_user.id, new_user.email, new_user.role.value)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=new_user.role.value,
        user_id=new_user.id,
        full_name=new_user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    ROUTE: POST /auth/login
    -----------------------
    Authenticate user and return a JWT token.

    INPUT (JSON body):
        {
          "email": "patient@test.com",
          "password": "securepass123"
        }

    OUTPUT:
        {
          "access_token": "eyJ...",
          "token_type": "bearer",
          "role": "patient",
          "user_id": 1,
          "full_name": "Jane Smith"
        }

    ERRORS:
        401 Unauthorized — wrong email or password
    """
    # Find the user by email
    user = db.query(User).filter(User.email == credentials.email).first()

    # SECURITY: same error message whether email is wrong OR password is wrong
    # Never tell attackers which one failed — prevents email enumeration
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    print(f"✅ User logged in: {user.email} (role: {user.role})")

    token = create_jwt_token(user.id, user.email, user.role.value)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role.value,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """
    ROUTE: GET /auth/me
    -------------------
    Returns the currently authenticated user's profile.
    Useful for the frontend to display user info after login.

    INPUT:  JWT token in Authorization header
    OUTPUT: User profile (no password)
    """
    return current_user
