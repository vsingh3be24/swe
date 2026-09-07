"""Auth API: register, login (returns JWT), and me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
)
from finalsay.db import get_db
from finalsay.models import User
from finalsay.schemas import Token, UserOut, UserRegister

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Public self-registration always yields a plain student account. Privileged
# roles (reviewer/admin/issuer) are provisioned only by the seed script (the
# four demo accounts) so an anonymous caller cannot self-assign privilege and
# reach role-protected routes (trust-boundary fix; R7.1).
SELF_REGISTER_ROLE = "student"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> User:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=SELF_REGISTER_ROLE,
        display_name=payload.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 password-flow login. ``username`` is the email address."""
    user = authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id, role=user.role)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
