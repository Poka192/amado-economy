"""외환 — 환율 시세/환전/외환 투자."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import forex_logic as fx
from ..database import get_db
from ..defs import FX_CURRENCIES, FX_MIN_EXCHANGE_KRW
from ..deps import require_user
from ..logic import get_money
from ..main import redirect, render
from ..models import User

router = APIRouter()


@router.get("/forex")
async def forex_page(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_user)):
    fx.catch_up(db)
    rates = fx.get_rates(db)
    holdings = fx.get_holdings(db, user.id)
    cash = get_money(db, user.id)
    rows = []
    for code, name, _base, _sig in FX_CURRENCIES:
        r = rates.get(code, {"rate": 0, "open": 0})
        change = r["rate"] - r["open"]
        change_pct = (change / r["open"] * 100) if r["open"] else 0
        rows.append({"code": code, "name": name, "rate": r["rate"],
                     "change": change, "change_pct": change_pct})
    return render(request, "forex.html", user=user, rows=rows,
                  holdings=holdings, cash=cash, min_exchange=FX_MIN_EXCHANGE_KRW)


@router.post("/forex/convert")
async def forex_convert(request: Request, code: str = Form(...),
                        side: str = Form(...), amount: str = Form(...),
                        db: Session = Depends(get_db),
                        user: User = Depends(require_user)):
    code = code.upper()
    if side not in ("buy", "sell"):
        return redirect("/forex", err="잘못된 거래 방향입니다.")
    try:
        amt = int(amount)
    except ValueError:
        return redirect("/forex", err="금액은 숫자여야 합니다.")
    if side == "buy":
        ok, msg = fx.buy(db, user.id, code, amt)
    else:
        ok, msg = fx.sell(db, user.id, code, amt)
    db.commit()
    return redirect("/forex", msg=msg if ok else "", err="" if ok else msg)


@router.get("/forex/{code}")
async def forex_detail(request: Request, code: str, db: Session = Depends(get_db),
                       user: User = Depends(require_user)):
    fx.catch_up(db)
    rate = fx.get_rate(db, code)
    if rate is None:
        return redirect("/forex", err="존재하지 않는 통화입니다.")
    holding = fx.get_holding(db, user.id, code)
    history = fx.get_history(db, code, 120)
    cash = get_money(db, user.id)
    return render(request, "forex_detail.html", user=user, rate=rate,
                  holding=holding, history=history, cash=cash,
                  min_exchange=FX_MIN_EXCHANGE_KRW)


@router.post("/forex/{code}/sell")
async def forex_sell(request: Request, code: str, amount: str = Form(...),
                     db: Session = Depends(get_db), user: User = Depends(require_user)):
    code = code.upper()
    try:
        units = float(amount)
    except ValueError:
        return redirect(f"/forex/{code}", err="수량은 숫자여야 합니다.")
    if units <= 0:
        return redirect(f"/forex/{code}", err="수량은 0보다 커야 합니다.")
    amount_cents = int(units * 100)
    ok, msg = fx.sell(db, user.id, code, amount_cents)
    db.commit()
    return redirect(f"/forex/{code}", msg=msg if ok else "", err="" if ok else msg)
