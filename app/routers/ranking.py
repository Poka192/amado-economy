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
from ..models import Money, User, UserJob

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
    users = db.execute(select(User)).scalars().all()
    result = []
    for u in users:
        try:
            cash = logic.get_money(db, u.id)
            deposit, loan_p, loan_i = logic.bank_settle(db, u.id)
            stock = sum(h.quantity * _price(db, h.ticker, h.avg_price)
                        for h in st_logic.get_holdings(db, u.id))
            re_value = 0
            from ..models import Property
            for p in db.execute(select(Property).where(Property.owner_id == u.id)).scalars().all():
                re_value += re_logic.property_value(db, p.type_id, p.level, p.staff_promo)
            total = cash + deposit + stock + re_value - (loan_p + loan_i)
            result.append((u, total))
        except Exception:
            continue
    result.sort(key=lambda x: x[1], reverse=True)
    return result[:limit]


def _price(db: Session, ticker: str, fallback: int) -> int:
    prices = st_logic.get_prices(db)
    return prices.get(ticker, {}).get("price", fallback)


@router.get("/achievements")
async def achievements_page(request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require_user)):
    earned = ach.earned(db, user.id)
    return render(request, "achievements.html", user=user, achievements=ACHIEVEMENTS,
                  earned=earned, earned_count=len(earned), total=len(ACHIEVEMENTS))
