from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.passwords import verify_password
from app.auth.schemas import LoginRequest, TokenResponse, UserResponse
from app.config import get_settings
from app.database.models import User
from app.database.session import get_db


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token, _session_id = create_access_token(user)
    settings = get_settings()
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_expire_minutes,
        user=UserResponse(
            id=user.id,
            email=user.email,
            company_id=user.company_id,
            role=user.role,
        ),
    )
