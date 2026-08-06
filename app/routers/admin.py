"""관리자 패널 — /admin 전용. require_admin + CSRF(double-submit cookie)."""
from __future__ import annotations

import secrets
import time as _time

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import logic
from .. import lotto_logic
from ..database import get_db
from ..defs import ACHIEVEMENTS, PROPERTY_MAP, SHOP_ITEMS, STOCKS
from ..deps import require_admin
from ..main import redirect, render
from ..models import (
    BankAccount,
    BankLoan,
    FxHolding,
    HighRoller,
    HopePending,
    InventoryItem,
    LottoState,
    LottoTicket,
    Money,
    Property,
    PropertyListing,
    QuestProgress,
    StockHolding,
    StockOrder,
    User,
    UserAchievement,
    UserJob,
    UserStat,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

STOCK_TICKERS = [s[1] for s in STOCKS]
ITEM_IDS = [i[0] for i in SHOP_ITEMS]


# ---------------------------------------------------------------------------
# CSRF (double-submit cookie — 서버 상태 없음)
# ---------------------------------------------------------------------------

def _csrf_ok(request: Request, token: str) -> bool:
    return bool(token) and secrets.compare_digest(token, request.cookies.get("csrf", ""))


def _redirect_to(q: str, msg: str = "", err: str = ""):
    path = f"/admin?q={q}" if q else "/admin"
    return redirect(path, msg=msg, err=err)


# ---------------------------------------------------------------------------
# 데이터 수집
# ---------------------------------------------------------------------------

def _summaries(db: Session) -> dict:
    return {
        "users": db.execute(select(func.count()).select_from(User)).scalar() or 0,
        "cash": db.execute(select(func.coalesce(func.sum(Money.balance), 0))).scalar() or 0,
        "deposit": db.execute(select(func.coalesce(func.sum(BankAccount.balance), 0))).scalar() or 0,
        "loan": db.execute(
            select(func.coalesce(func.sum(BankLoan.principal + BankLoan.interest), 0))
        ).scalar() or 0,
        "admins": db.execute(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        ).scalar() or 0,
    }


def _snapshot(db: Session, uid: int) -> dict:
    return {
        "money": db.get(Money, uid),
        "bank": db.get(BankAccount, uid),
        "loan": db.get(BankLoan, uid),
        "stocks": db.execute(select(StockHolding).where(StockHolding.user_id == uid)).scalars().all(),
        "fx": db.execute(select(FxHolding).where(FxHolding.user_id == uid)).scalars().all(),
        "props": db.execute(select(Property).where(Property.owner_id == uid)).scalars().all(),
        "inv": db.execute(select(InventoryItem).where(InventoryItem.user_id == uid)).scalars().all(),
        "hr": db.get(HighRoller, uid),
        "hope": db.get(HopePending, uid),
        "job": db.get(UserJob, uid),
        "stats": db.execute(select(UserStat).where(UserStat.user_id == uid)).scalars().all(),
        "achs": db.execute(select(UserAchievement).where(UserAchievement.user_id == uid)).scalars().all(),
        "quests": db.execute(select(QuestProgress).where(QuestProgress.user_id == uid)).scalars().all(),
        "ticket": db.get(LottoTicket, uid),
        "orders": db.execute(
            select(StockOrder).where(StockOrder.user_id == uid, StockOrder.status == "open")
        ).scalars().all(),
    }


def _user_rows(db: Session) -> list[dict]:
    balances = dict(db.execute(select(Money.user_id, Money.balance)).all())
    users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return [{"user": u, "cash": balances.get(u.id, 0)} for u in users]


# ---------------------------------------------------------------------------
# 페이지
# ---------------------------------------------------------------------------

@router.get("")
async def admin_page(request: Request, q: str = "",
                     user: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    # csrf 쿠키가 이미 있으면 재사용 (매 GET마다 새로 발급하면 리다이렉트/멀티탭에서 토큰 불일치)
    token = request.cookies.get("csrf") or secrets.token_hex(16)
    target = None
    snapshot = None
    query = q.strip()
    if query:
        target = db.execute(select(User).where(User.username == query)).scalar_one_or_none()
        if target is not None:
            snapshot = _snapshot(db, target.id)

    resp = render(
        request, "admin.html",
        user=user,
        csrf=token,
        summaries=_summaries(db),
        user_rows=_user_rows(db),
        q=query,
        target=target,
        snap=snapshot,
        lotto=lotto_logic.get_state(db),
        ACHIEVEMENTS=ACHIEVEMENTS,
        PROPERTY_MAP=PROPERTY_MAP,
        JOBS=logic.JOBS,
        STOCK_TICKERS=STOCK_TICKERS,
        ITEM_IDS=ITEM_IDS,
    )
    resp.set_cookie("csrf", token, samesite="lax", httponly=True, max_age=3600)
    return resp


# ---------------------------------------------------------------------------
# 유저 경제 액션
# ---------------------------------------------------------------------------

def _get_user(db: Session, uid: int) -> User | None:
    return db.get(User, uid)


@router.post("/cash")
async def admin_set_cash(request: Request, uid: int = Form(...), amount: int = Form(...),
                         csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    row = db.get(Money, uid)
    if row is None:
        row = Money(user_id=uid, balance=0)
        db.add(row)
    row.balance = max(0, amount)
    db.commit()
    return _redirect_to(u.username, msg=f"💰 {u.username} 소지금 = {amount:,}원")


@router.post("/add_cash")
async def admin_add_cash(request: Request, uid: int = Form(...), delta: int = Form(...),
                         csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    new_balance = logic.change_money(db, uid, delta)
    db.commit()
    return _redirect_to(u.username, msg=f"💰 {u.username} 소지금 {delta:+,}원 → {new_balance:,}원")


@router.post("/deposit")
async def admin_set_deposit(request: Request, uid: int = Form(...), amount: int = Form(...),
                            csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    acc = db.get(BankAccount, uid)
    if acc is None:
        acc = BankAccount(user_id=uid, balance=0, last_interest_at=_time.time())
        db.add(acc)
    acc.balance = max(0, amount)
    acc.last_interest_at = _time.time()
    db.commit()
    return _redirect_to(u.username, msg=f"🏦 {u.username} 예치금 = {amount:,}원")


@router.post("/loan")
async def admin_set_loan(request: Request, uid: int = Form(...), amount: int = Form(...),
                         csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    loan = db.get(BankLoan, uid)
    if loan is None:
        loan = BankLoan(user_id=uid, principal=0, interest=0, last_interest_at=_time.time())
        db.add(loan)
    loan.principal = max(0, amount)
    loan.interest = 0
    loan.last_interest_at = _time.time()
    db.commit()
    return _redirect_to(u.username, msg=f"💳 {u.username} 대출 원금 = {amount:,}원")


@router.post("/item")
async def admin_give_item(request: Request, uid: int = Form(...), item_id: str = Form(...),
                          qty: int = Form(1), csrf: str = Form(""),
                          db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    iid = item_id.strip()
    if not iid:
        return _redirect_to(u.username, err="아이템 ID가 비어 있습니다.")
    row = db.get(InventoryItem, (uid, iid))
    if row is None:
        db.add(InventoryItem(user_id=uid, item_id=iid, quantity=max(0, qty)))
    else:
        row.quantity = max(0, row.quantity + qty)
    db.commit()
    return _redirect_to(u.username, msg=f"🎁 {u.username}에게 {iid} ×{qty} 지급")


@router.post("/stock")
async def admin_give_stock(request: Request, uid: int = Form(...), ticker: str = Form(...),
                           qty: int = Form(...), avg_price: int = Form(0),
                           csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    t = ticker.strip().upper()
    if t not in STOCK_TICKERS:
        return _redirect_to(u.username, err=f"알 수 없는 종목: {t}")
    row = db.get(StockHolding, (uid, t))
    if row is None:
        db.add(StockHolding(user_id=uid, ticker=t, quantity=max(0, qty), avg_price=max(0, avg_price)))
    else:
        row.quantity = max(0, qty)
        row.avg_price = max(0, avg_price)
    db.commit()
    return _redirect_to(u.username, msg=f"📈 {u.username} {t} {qty}주 설정 (평단 {avg_price:,})")


@router.post("/clear_cd")
async def admin_clear_cd(request: Request, uid: int = Form(...),
                         csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    db.execute(delete(UserStat).where(UserStat.user_id == uid, UserStat.stat.like("cd_%")))
    db.commit()
    return _redirect_to(u.username, msg=f"⏱️ {u.username} 쿨다운 전체 해제")


@router.post("/set_admin")
async def admin_set_admin(request: Request, uid: int = Form(...), make: str = Form("0"),
                          csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    u.is_admin = make == "1"
    db.commit()
    role = "관리자 승격" if u.is_admin else "관리자 해제"
    return _redirect_to(u.username, msg=f"🛡️ {u.username} {role}")


@router.post("/reset")
async def admin_reset(request: Request, uid: int = Form(...),
                      csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    # 소지금 기본값 초기화 + 경제 데이터 전체 삭제 (계정·업적 유지)
    m = db.get(Money, uid)
    if m is None:
        db.add(Money(user_id=uid, balance=logic.MONEY_DEFAULT))
    else:
        m.balance = logic.MONEY_DEFAULT
    for model in (BankAccount, BankLoan, StockHolding, StockOrder, FxHolding,
                  InventoryItem, HighRoller, HopePending, UserJob, QuestProgress,
                  UserStat, LottoTicket):
        db.execute(delete(model).where(model.user_id == uid))
    db.execute(delete(Property).where(Property.owner_id == uid))
    db.execute(delete(PropertyListing).where(PropertyListing.owner_id == uid))
    db.commit()
    return _redirect_to(u.username, msg=f"🧹 {u.username} 경제 초기화 완료 (소지금 {logic.MONEY_DEFAULT:,}원)")


@router.post("/delete")
async def admin_delete(request: Request, uid: int = Form(...), confirm: str = Form(""),
                       csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    u = _get_user(db, uid)
    if u is None:
        return _redirect_to("", err="유저를 찾을 수 없습니다.")
    if confirm.strip() != "삭제":
        return _redirect_to(u.username, err="삭제하려면 확인란에 '삭제'를 입력하세요.")
    # SQLite는 FK CASCADE 미동작 → 수동 정리 (Postgres는 CASCADE로 자동)
    for model in (Money, BankAccount, BankLoan, StockHolding, StockOrder, FxHolding,
                  InventoryItem, HighRoller, HopePending, UserJob, QuestProgress,
                  UserStat, UserAchievement, LottoTicket):
        db.execute(delete(model).where(model.user_id == uid))
    db.execute(delete(Property).where(Property.owner_id == uid))
    db.execute(delete(PropertyListing).where(PropertyListing.owner_id == uid))
    db.delete(u)
    db.commit()
    return _redirect_to("", msg=f"🗑️ {u.username} 계정 삭제 완료")


# ---------------------------------------------------------------------------
# 로또 컨트롤
# ---------------------------------------------------------------------------

@router.post("/lotto")
async def admin_lotto(request: Request, action: str = Form(...), amount: int = Form(0),
                      csrf: str = Form(""), db: Session = Depends(get_db)):
    if not _csrf_ok(request, csrf):
        return _redirect_to("", err="보안 토큰이 올바르지 않습니다.")
    row = db.get(LottoState, 1)
    if row is None:
        row = LottoState(id=1)
        db.add(row)
    if action == "set":
        row.jackpot = max(0, amount)
        db.commit()
        return _redirect_to("", msg=f"🎫 로또 잭팟 = {amount:,}원")
    if action == "draw":
        from .. import lotto_logic as ll
        result = ll.draw(db)
        rolled = result.get("rolled", False)
        drawn = result.get("drawn", "?")
        msg = f"🎲 강제 추첨 완료 — 당첨 번호 {drawn:03d}" if rolled else \
            f"🎲 강제 추첨 (당첨자 없음) — 번호 {result.get('drawn', 0):03d}"
        return _redirect_to("", msg=msg)
    return _redirect_to("", err="알 수 없는 동작")
