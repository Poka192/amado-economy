"""랭킹/리더보드/업적."""
from __future__ import annotations

import time as _time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import achievements as ach
from .. import logic
from .. import realestate_logic as re_logic
from .. import stocks_logic as st_logic
from ..database import get_db
from ..defs import ACHIEVEMENTS
from ..deps import optional_user, require_user
from ..main import render
from ..models import User

router = APIRouter()

# 랭킹은 모든 유저에게 동일한 데이터 — 전역 스냅샷 캐시(10초 TTL)로 캐시 miss 시
# 원격 DB 8회 왕복을 1회로 절감. POST 액션 시 main.py에서 invalidate_ranking_cache() 호출.
_rank_cache: dict[int, tuple[float, list, list]] = {}
_RANK_TTL = 10.0


def invalidate_ranking_cache():
    """POST 액션 후 순위가 최신으로 보이도록 전역 랭킹 스냅샷을 비운다."""
    _rank_cache.clear()


class _Row:
    """템플릿이 u.id/u.username만 접근하므로 그 두 필드만 갖는 경량 행."""

    __slots__ = ("id", "username")

    def __init__(self, uid: int, username: str):
        self.id = uid
        self.username = username


def _compute_ranking(db: Session, limit: int = 20) -> tuple[list, list]:
    """전체 랭킹 계산 — 테이블을 한 번씩만 로드해 메모리에서 계산.

    (소지금 TOP, 전재산 TOP)을 (uid, username, value) 튜플로 반환.
    기존 N+1(유저×보유자산 시세 조회)과 GET 쓰기(bank_settle/Money 삽입)를 제거.
    """
    from ..models import BankAccount, BankLoan, Money, Property, StockHolding

    users = db.execute(select(User)).scalars().all()
    if not users:
        return [], []

    names = {u.id: u.username for u in users}
    now = _time.time()
    money_map = {m.user_id: m.balance for m in db.execute(select(Money)).scalars().all()}
    acc_map = {a.user_id: a for a in db.execute(select(BankAccount)).scalars().all()}
    loan_map = {l.user_id: l for l in db.execute(select(BankLoan)).scalars().all()}
    hold_map: dict[int, list] = {}
    for h in db.execute(select(StockHolding)).scalars().all():
        hold_map.setdefault(h.user_id, []).append(h)
    prop_map: dict[int, list] = {}
    for p in db.execute(select(Property)).scalars().all():
        prop_map.setdefault(p.owner_id, []).append(p)

    # 시세는 TTL 캐시(5초) — 캐시가 따뜻하면 쿼리 없음
    prices = st_logic.get_prices(db)
    market = re_logic.get_market_prices(db)

    # 소지금 TOP — Money row 있는 유저만 (기존 User-JOIN과 동일)
    money_rows = [
        (uid, names.get(uid, f"user{uid}"), bal)
        for uid, bal in sorted(money_map.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]

    wealth = []
    for u in users:
        try:
            cash = money_map.get(u.id, logic.MONEY_DEFAULT)
            acc = acc_map.get(u.id)
            deposit = logic.accrued_deposit(acc.balance, acc.last_interest_at, now) if acc else 0
            loan = loan_map.get(u.id)
            loan_debt = 0
            if loan is not None:
                p, i = logic.accrued_loan(loan.principal, loan.interest, loan.last_interest_at, now)
                loan_debt = p + i
            stock = sum(h.quantity * prices.get(h.ticker, {}).get("price", h.avg_price)
                        for h in hold_map.get(u.id, ()))
            re_value = 0
            for p in prop_map.get(u.id, ()):
                base = re_logic.PROPERTY_MAP[p.type_id][2]
                re_value += market.get(p.type_id, base) \
                    + int(base * re_logic.RENOVATE_VALUE_RATE * p.level) \
                    + int(base * re_logic.STAFF_PROMO_VALUE * p.staff_promo)
            wealth.append((u.id, u.username, cash + deposit + stock + re_value - loan_debt))
        except Exception:
            continue
    wealth.sort(key=lambda x: x[2], reverse=True)
    return money_rows, wealth[:limit]


@router.get("/ranking")
async def ranking_page(request: Request, db: Session = Depends(get_db)):
    user = optional_user(request, db)

    engine_id = id(db.get_bind())
    now = _time.time()
    hit = _rank_cache.get(engine_id)
    if hit and now - hit[0] < _RANK_TTL:
        money_data, wealth_data = hit[1], hit[2]
    else:
        money_data, wealth_data = _compute_ranking(db)
        _rank_cache[engine_id] = (now, money_data, wealth_data)

    money_rank = [(_Row(uid, name), bal) for uid, name, bal in money_data]
    wealth_rank = [(_Row(uid, name), total) for uid, name, total in wealth_data]
    return render(request, "ranking.html", user=user, money_rank=money_rank,
                  wealth_rank=wealth_rank)


@router.get("/achievements")
async def achievements_page(request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require_user)):
    earned = ach.earned(db, user.id)
    return render(request, "achievements.html", user=user, achievements=ACHIEVEMENTS,
                  earned=earned, earned_count=len(earned), total=len(ACHIEVEMENTS))
