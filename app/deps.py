"""FastAPI 의존성: 세션 로그인 유저 추출."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import read_session_token

SESSION_COOKIE = "session"


class LoginRequired(Exception):
    """로그인 필요 — main.py의 exception_handler가 /login으로 리다이렉트."""


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = read_session_token(token)
    if uid is None:
        return None
    return db.get(User, uid)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = optional_user(request, db)
    if user is None:
        raise LoginRequired()
    return user
