"""Admin authentication: password login + JWT verification."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Header, HTTPException

from .config import settings

JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 24


def create_admin_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    return jwt.encode(
        {"sub": "admin", "exp": expire},
        settings.ADMIN_JWT_SECRET.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def verify_jwt(authorization: Optional[str] = Header(None)) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(403, "Invalid Header")
    token = authorization.split(" ", 1)[1]
    try:
        jwt.decode(token, settings.ADMIN_JWT_SECRET.get_secret_value(), algorithms=[JWT_ALGORITHM])
        return True
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token หมดอายุ กรุณา Login ใหม่")
    except jwt.PyJWTError:
        raise HTTPException(403, "Invalid Token")
