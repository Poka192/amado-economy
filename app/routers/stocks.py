"""주식 — 시세/매매/지정가/차트/뉴스."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import achievements as ach
from .. import stocks_logic as st
from ..database import get_db
from ..defs import SECTORS, STOCKS
from ..deps import require_user
from ..main import redirect, render
from ..models import StockHolding, StockOrder, User

router = APIRouter()


@router.get("/stocks")
async def stocks_page(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_user)):
    st.catch_up(db)
    prices = st.get_prices(db)
    rows = []
    for name, code, base, sigma, beta, sector, div in STOCKS:
        p = prices.get(code, {"price": base, "open": base})
        change = p["price"] - p["open"]
        change_pct = (change / p["open"] * 100) if p["open"] else 0
        rows.append({"ticker": code, "name": name, "price": p["price"],
                     "open": p["open"], "change": change, "change_pct": change_pct,
                     "sector": sector, "div": div})
    holdings = {h.ticker: h for h in st.get_holdings(db, user.id)}
    cash = _money(db, user.id)
    return render(request, "stocks.html", user=user, rows=rows, holdings=holdings,
                  sectors=SECTORS, cash=cash)


@router.get("/stocks/{ticker}")
async def stock_detail(request: Request, ticker: str, db: Session = Depends(get_db),
                       user: User = Depends(require_user)):
    st.catch_up(db)
    prices = st.get_prices(db)
    info = next((s for s in STOCKS if s[1] == ticker.upper()), None)
    if info is None:
        return redirect("/stocks", err="존재하지 않는 종목입니다.")
    price = prices.get(ticker.upper(), {"price": info[2], "open": info[2]})
    holding = db.get(StockHolding, (user.id, ticker.upper()))
    orders = db.execute(select(StockOrder).where(
        StockOrder.user_id == user.id, StockOrder.status == "open",
        StockOrder.ticker == ticker.upper())).scalars().all()
    history = st.get_history(db, ticker.upper(), 120)
    news = st.get_news(db, 10)
    return render(request, "stock_detail.html", user=user, info=info,
                  price=price["price"], open=price["open"], holding=holding,
                  orders=orders, history=history, news=news,
                  cash=_money(db, user.id))


def _money(db: Session, uid: int) -> int:
    from ..logic import get_money
    return get_money(db, uid)


@router.post("/stocks/{ticker}/buy")
async def stock_buy(request: Request, ticker: str, qty: str = Form(...),
                    db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        n = int(qty)
    except ValueError:
        return redirect(f"/stocks/{ticker.upper()}", err="수량은 숫자여야 합니다.")
    if n <= 0:
        return redirect(f"/stocks/{ticker.upper()}", err="수량은 1주 이상이어야 합니다.")
    ok, msg = st.buy_market(db, user.id, ticker.upper(), n)
    db.commit()
    return redirect(f"/stocks/{ticker.upper()}", msg=msg if ok else "", err="" if ok else msg)


@router.post("/stocks/{ticker}/sell")
async def stock_sell(request: Request, ticker: str, qty: str = Form(...),
                     db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        n = int(qty)
    except ValueError:
        return redirect(f"/stocks/{ticker.upper()}", err="수량은 숫자여야 합니다.")
    if n <= 0:
        return redirect(f"/stocks/{ticker.upper()}", err="수량은 1주 이상이어야 합니다.")
    ok, msg = st.sell_market(db, user.id, ticker.upper(), n)
    db.commit()
    return redirect(f"/stocks/{ticker.upper()}", msg=msg if ok else "", err="" if ok else msg)


@router.post("/stocks/{ticker}/order")
async def stock_order(request: Request, ticker: str, side: str = Form(...),
                      qty: str = Form(...), price: str = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        n, p = int(qty), int(price)
    except ValueError:
        return redirect(f"/stocks/{ticker.upper()}", err="수량/가격은 숫자여야 합니다.")
    ok, msg = st.place_order(db, user.id, ticker.upper(), side, n, p)
    db.commit()
    return redirect(f"/stocks/{ticker.upper()}", msg=msg if ok else "", err="" if ok else msg)


@router.post("/stocks/order/cancel")
async def order_cancel(request: Request, order_id: str = Form(...),
                       db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok = st.cancel_order(db, user.id, int(order_id))
    db.commit()
    return redirect("/stocks", msg="주문 취소 완료" if ok else "", err="" if ok else "주문을 찾을 수 없습니다.")
