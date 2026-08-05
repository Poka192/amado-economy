"""회원가입 / 로그인 / 로그아웃."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import SESSION_COOKIE, optional_user
from ..main import redirect, render
from ..models import User
from ..security import hash_password, make_session_token, verify_password

router = APIRouter()


@router.get("/register")
async def register_page(request: Request, db: Session = Depends(get_db)):
    if optional_user(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "register.html")


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9가-힣_]{2,16}", username):
        return render(request, "register.html",
                      flash_err="아이디는 2~16자 (영문/숫자/한글/밑줄)로 입력하세요.")
    if len(password) < 4:
        return render(request, "register.html", flash_err="비밀번호는 4자 이상이어야 합니다.")
    exists = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if exists:
        return render(request, "register.html", flash_err="이미 사용 중인 아이디입니다.")
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.commit()
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE, make_session_token(user.id), httponly=True,
                        max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@router.get("/login")
async def login_page(request: Request, db: Session = Depends(get_db)):
    if optional_user(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "login.html")


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return render(request, "login.html", flash_err="아이디 또는 비밀번호가 올바르지 않습니다.")
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE, make_session_token(user.id), httponly=True,
                        max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
