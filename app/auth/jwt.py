from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from app.auth.schemas import TokenPayload
from app.config import get_settings
from app.database.models import User


settings = get_settings()


def create_access_token(user: User) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    session_id = str(uuid4())
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "company_id": user.company_id,
        "role": user.role,
        "session_id": session_id,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, session_id


def decode_access_token(token: str) -> TokenPayload:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return TokenPayload(**payload)
