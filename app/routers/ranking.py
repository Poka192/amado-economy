"""랭킹/리더보드/업적."""
from __future__ import annotations

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
from ..models import Money, User

router = APIRouter()


@router.get("/ranking")
async def ranking_page(request: Request, db: Session = Depends(get_db)):
    user = optional_user(request, db)

    # 소지금 랭킹
    money_rows = db.execute(
        select(User, Money).join(Money, Money.user_id == User.id)
        .order_by(Money.balance.desc()).limit(20)
    ).all()
    money_rank = [(u, m.balance) for u, m in money_rows]

    # 재산(전재산) 랭킹 — 유저별 합산 (캐시+예치+주식+부동산-대출)
    wealth_rows = _wealth_ranking(db)
    return render(request, "ranking.html", user=user, money_rank=money_rank,
                  wealth_rank=wealth_rows)


def _wealth_ranking(db: Session, limit: int = 20) -> list:
    """전재산 랭킹 — 테이블을 한 번씩만 로드해 메모리에서 계산.

    기존에는 유저마다 get_money/bank_settle/보유자산별 시세 조회(N+1)로
    수십~수백 번의 원격 DB 왕복이 발생했다. 여기선 쓰기 없이 읽기만 한다.
    """
    import time as _time

    from ..models import BankAccount, BankLoan, Money, Property, StockHolding

    users = db.execute(select(User)).scalars().all()
    if not users:
        return []

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

    result = []
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
            total = cash + deposit + stock + re_value - loan_debt
            result.append((u, total))
        except Exception:
            continue
    result.sort(key=lambda x: x[1], reverse=True)
    return result[:limit]


@router.get("/achievements")
async def achievements_page(request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require_user)):
    earned = ach.earned(db, user.id)
    return render(request, "achievements.html", user=user, achievements=ACHIEVEMENTS,
                  earned=earned, earned_count=len(earned), total=len(ACHIEVEMENTS))
