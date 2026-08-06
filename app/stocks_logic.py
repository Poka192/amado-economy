"""주식 로직 — 봇(cogs/stocks.py) 이식. 24/7 틱, 평균회귀, 뉴스, 배당, 지정가 주문."""
from __future__ import annotations

import math
import random
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import achievements as ach
from .defs import (
    MARKET_SIGMA,
    MAX_TICK_MOVE,
    MEAN_REVERSION_DRIFT,
    NEWS_EVENTS,
    SECTORS,
    STOCKS,
    STOCK_TICK_SECONDS,
    price_step,
)
from .logic import change_money, get_money, update_quest_progress
from .models import (
    StockDividend,
    StockHolding,
    StockHistory,
    StockNews,
    StockOrder,
    StockPrice,
    SystemState,
)

MAX_CATCHUP_TICKS = 1000
HISTORY_LIMIT = 300
NEWS_PER_TICK = 0.05       # 틱당 뉴스 확률
DIVIDEND_EVERY_TICKS = 100  # 100틱(50분)마다 배당


def _now() -> float:
    return time.time()


def state_get(db: Session, key: str) -> float:
    row = db.get(SystemState, key)
    return row.value if row else 0


def state_set(db: Session, key: str, val: float):
    row = db.get(SystemState, key)
    if row is None:
        db.add(SystemState(key=key, value=val))
    else:
        row.value = val
    db.flush()


def ensure_seed(db: Session):
    """시드: 종목 미존재 시 기준가로 생성."""
    existing = db.execute(select(StockPrice.ticker)).scalars().all()
    have = set(existing)
    for name, code, base, *_ in STOCKS:
        if code not in have:
            db.add(StockPrice(ticker=code, name=name, price=base, open_price=base))
            db.flush()
            db.add(StockHistory(ticker=code, price=base, ts=_now()))
    db.flush()
    if state_get(db, "stock_last_tick") == 0:
        state_set(db, "stock_last_tick", _now())


def get_prices(db: Session) -> dict[str, dict]:
    ensure_seed(db)
    rows = db.execute(select(StockPrice)).scalars().all()
    return {r.ticker: {"name": r.name, "price": r.price, "open": r.open_price} for r in rows}


def _round_to_step(price: int) -> int:
    step = price_step(price)
    return max(100, int(round(price / step)) * step)


def beta_of(ticker: str) -> float:
    return next((b for _, c, _b, _s, b, _sec, _d in STOCKS if c == ticker), 1.0)


def sigma_of(ticker: str) -> float:
    return next((s for _, c, _b, s, _be, _sec, _d in STOCKS if c == ticker), 0.005)


def _maybe_news(db: Session, now: float):
    content, sector, base_impact, intensity = random.choice(NEWS_EVENTS)
    impact = base_impact * intensity * random.uniform(0.3, 1.0)
    affected = SECTORS.get(sector, [])
    for row in db.execute(select(StockPrice)).scalars().all():
        if row.ticker in affected:
            pct = impact * random.uniform(0.3, 1.0)
            row.price = _round_to_step(max(100, int(round(row.price * (1 + pct)))))
    db.add(StockNews(ticker=", ".join(affected) or sector, title=content,
                     body=f"{sector} 섹터에 {content} 뉴스가 발생했습니다.", created_at=now))
    db.flush()


def _trim_history(db: Session):
    """종목별 히스토리 상한 유지 — 종목당 쿼리 1회로 경량화."""
    keep = HISTORY_LIMIT * 2
    for ticker in db.execute(select(StockPrice.ticker)).scalars().all():
        db.execute(
            StockHistory.__table__.delete().where(
                StockHistory.ticker == ticker,
                StockHistory.id.in_(
                    select(StockHistory.id)
                    .where(StockHistory.ticker == ticker)
                    .order_by(StockHistory.id.desc())
                    .offset(keep)
                ),
            )
        )
    db.flush()


def catch_up(db: Session):
    """접근 시 오프라인 시간 보정 (최대 MAX_CATCHUP_TICKS).

    원격 DB(예: Supabase)에서는 틱마다 쓰면 수천 번 왕복이 되어
    요청이 수 분간 막히므로, 전체 틱을 메모리에서 시뮬레이션하고
    최종 가격만 한 번에 기록한다. 지정가 주문/배당은 최종 가격 기준으로 처리.
    """
    ensure_seed(db)
    last = state_get(db, "stock_last_tick")
    now = _now()
    elapsed = now - last
    if elapsed < STOCK_TICK_SECONDS:
        return 0
    ticks = min(int(elapsed / STOCK_TICK_SECONDS), MAX_CATCHUP_TICKS)

    # 메모리에서 전체 틱 시뮬레이션
    rows = {r.ticker: r for r in db.execute(select(StockPrice)).scalars().all()}
    for _ in range(ticks):
        market_shock = random.gauss(0, MARKET_SIGMA)
        for ticker, row in rows.items():
            base = next((b for _, c, b, *_ in STOCKS if c == ticker), row.price)
            drift = MEAN_REVERSION_DRIFT * ((base - row.price) / base) if base else 0.0
            pct = beta_of(ticker) * market_shock + random.gauss(0, sigma_of(ticker)) + drift
            pct = max(-MAX_TICK_MOVE, min(MAX_TICK_MOVE, pct))
            row.price = _round_to_step(max(100, int(round(row.price * math.exp(pct)))))

    # 최종 가격 히스토리 1건씩 기록
    for ticker, row in rows.items():
        db.add(StockHistory(ticker=ticker, price=row.price, ts=now))
    db.flush()
    _trim_history(db)

    # 지정가 주문 체결 + 배당 (최종 상태 기준)
    _check_orders(db, now)
    for _ in range(ticks // DIVIDEND_EVERY_TICKS):
        _pay_dividends(db, now)

    # 뉴스 (틱 수에 비례한 확률로 최대 1건)
    if random.random() < min(1.0, NEWS_PER_TICK * ticks):
        _maybe_news(db, now)

    state_set(db, "stock_last_tick", now)
    db.flush()
    return ticks


def buy_market(db: Session, uid: int, ticker: str, qty: int) -> tuple[bool, str]:
    price_row = db.execute(
        select(StockPrice).where(StockPrice.ticker == ticker)
    ).scalar_one_or_none()
    if price_row is None:
        return False, "존재하지 않는 종목입니다."
    cost = price_row.price * qty
    balance = get_money(db, uid)
    if balance < cost:
        return False, f"잔고 부족 ({cost:,}원 필요, 현재 {balance:,}원)"
    change_money(db, uid, -cost)
    holding = db.get(StockHolding, (uid, ticker))
    if holding is None:
        db.add(StockHolding(user_id=uid, ticker=ticker, quantity=qty, avg_price=price_row.price))
    else:
        total = holding.quantity + qty
        holding.avg_price = (holding.avg_price * holding.quantity + price_row.price * qty) // total
        holding.quantity = total
    db.flush()
    update_quest_progress(db, uid, "daily_7")
    ach.increment_stat(db, uid, "stock_buys", qty)
    return True, f"{ticker} {qty}주 매수 완료"


def sell_market(db: Session, uid: int, ticker: str, qty: int) -> tuple[bool, str]:
    price_row = db.execute(
        select(StockPrice).where(StockPrice.ticker == ticker)
    ).scalar_one_or_none()
    holding = db.get(StockHolding, (uid, ticker))
    if price_row is None or holding is None or holding.quantity < qty:
        return False, "보유 수량 부족"
    proceeds = price_row.price * qty
    change_money(db, uid, proceeds)
    holding.quantity -= qty
    if holding.quantity <= 0:
        db.delete(holding)
    db.flush()
    # 수익 계산
    profit = (price_row.price - holding.avg_price) * qty if holding.quantity > 0 else \
        (price_row.price - _old_avg(db, uid, ticker)) * qty
    if profit > 0:
        ach.increment_stat(db, uid, "stock_profit", profit)
    return True, f"{ticker} {qty}주 매도 완료 (+{proceeds:,}원)"


def _old_avg(db: Session, uid: int, ticker: str) -> int:
    # 매도 후 holding 삭제된 경우 평균단가 재조회용 (간단화: 0)
    return 0


def place_order(db: Session, uid: int, ticker: str, side: str, qty: int, price: int) -> tuple[bool, str]:
    if qty <= 0 or price <= 0:
        return False, "수량/가격은 양수여야 합니다."
    db.add(StockOrder(user_id=uid, ticker=ticker, side=side, quantity=qty,
                      price=price, status="open"))
    db.flush()
    return True, f"{ticker} {side} {qty}주 @ {price:,}원 주문 접수"


def cancel_order(db: Session, uid: int, order_id: int) -> bool:
    order = db.get(StockOrder, order_id)
    if order is None or order.user_id != uid or order.status != "open":
        return False
    order.status = "canceled"
    db.flush()
    return True


def _check_orders(db: Session, now: float):
    for order in db.execute(
        select(StockOrder).where(StockOrder.status == "open")
    ).scalars().all():
        price_row = db.execute(
            select(StockPrice).where(StockPrice.ticker == order.ticker)
        ).scalar_one_or_none()
        if price_row is None:
            continue
        if order.side == "buy" and price_row.price <= order.price:
            cost = price_row.price * order.quantity
            if get_money(db, order.user_id) >= cost:
                change_money(db, order.user_id, -cost)
                holding = db.get(StockHolding, (order.user_id, order.ticker))
                if holding is None:
                    db.add(StockHolding(user_id=order.user_id, ticker=order.ticker,
                                        quantity=order.quantity, avg_price=price_row.price))
                else:
                    total = holding.quantity + order.quantity
                    holding.avg_price = (holding.avg_price * holding.quantity + price_row.price * order.quantity) // total
                    holding.quantity = total
                order.status = "filled"
        elif order.side == "sell" and price_row.price >= order.price:
            holding = db.get(StockHolding, (order.user_id, order.ticker))
            if holding and holding.quantity >= order.quantity:
                proceeds = price_row.price * order.quantity
                change_money(db, order.user_id, proceeds)
                holding.quantity -= order.quantity
                if holding.quantity <= 0:
                    db.delete(holding)
                order.status = "filled"
    db.flush()


def _pay_dividends(db: Session, now: float):
    for holding in db.execute(select(StockHolding)).scalars().all():
        price_row = db.execute(
            select(StockPrice).where(StockPrice.ticker == holding.ticker)
        ).scalar_one_or_none()
        if price_row is None:
            continue
        div_rate = next((d for _, c, _b, _s, _be, _sec, d in STOCKS if c == holding.ticker), 0.0)
        amount = int(holding.quantity * price_row.price * div_rate)
        if amount > 0:
            change_money(db, holding.user_id, amount)
            db.add(StockDividend(user_id=holding.user_id, ticker=holding.ticker,
                                 amount=amount, created_at=now))
            ach.grant(db, holding.user_id, "dividend_first")
    db.flush()


def get_holdings(db: Session, uid: int) -> list:
    return db.execute(
        select(StockHolding).where(StockHolding.user_id == uid)
    ).scalars().all()


def get_history(db: Session, ticker: str, limit: int = 100) -> list:
    return db.execute(
        select(StockHistory).where(StockHistory.ticker == ticker)
        .order_by(StockHistory.id.desc()).limit(limit)
    ).scalars().all()[::-1]


def get_news(db: Session, limit: int = 20) -> list:
    return db.execute(
        select(StockNews).order_by(StockNews.id.desc()).limit(limit)
    ).scalars().all()


def get_dividends(db: Session, uid: int) -> list:
    return db.execute(
        select(StockDividend).where(StockDividend.user_id == uid)
        .order_by(StockDividend.id.desc()).limit(30)
    ).scalars().all()
