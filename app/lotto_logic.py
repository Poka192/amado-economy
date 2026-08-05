"""로또 로직 — 봇(cogs/lotto.py) 이식. 티켓 10만 고정, 당첨금 1억+10%복리."""
from __future__ import annotations

import random
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .defs import (
    LOTTO_BASE_PRIZE,
    LOTTO_DRAW_INTERVAL,
    LOTTO_MAX,
    LOTTO_MIN,
    LOTTO_PRIZE_RATE,
    TICKET_PRICE,
)
from .logic import change_money, get_money
from .models import LottoState, LottoTicket, User

DRAW_INTERVAL = LOTTO_DRAW_INTERVAL


def _prize(draw_count: int) -> int:
    return int(LOTTO_BASE_PRIZE * (1 + LOTTO_PRIZE_RATE) ** draw_count)


def get_state(db: Session) -> dict:
    row = db.get(LottoState, 1)
    if row is None:
        row = LottoState(id=1, jackpot=LOTTO_BASE_PRIZE)
        db.add(row)
        db.flush()
    return {
        "last_drawn": row.last_drawn,
        "last_draw_time": row.last_draw_time,
        "jackpot": row.jackpot,
        "draw_count": row.draw_count,
    }


def _set_state(db: Session, drawn, now: float, jackpot: int, draw_count: int):
    row = db.get(LottoState, 1)
    if row is None:
        row = LottoState(id=1)
        db.add(row)
    row.last_drawn = drawn
    row.last_draw_time = now
    row.jackpot = jackpot
    row.draw_count = draw_count
    db.flush()


def _fmt(n: int) -> str:
    return f"{n:03d}"


def get_ticket(db: Session, uid: int):
    return db.get(LottoTicket, uid)


def buy(db: Session, uid: int, number: int) -> tuple[bool, str]:
    """티켓 구매. (성공, 메시지). 같은 턴 변경 불가."""
    if not (LOTTO_MIN <= number <= LOTTO_MAX):
        return False, "번호는 001~999 사이여야 합니다."
    state = get_state(db)
    ticket = get_ticket(db, uid)
    if ticket is not None and ticket.bought_at > state["last_draw_time"]:
        return False, f"이번 추첨에 이미 구매했습니다. (내 번호 {_fmt(ticket.number)})"
    balance = get_money(db, uid)
    if balance < TICKET_PRICE:
        return False, f"티켓은 {TICKET_PRICE:,}원입니다. (현재 {balance:,}원)"
    change_money(db, uid, -TICKET_PRICE)
    if ticket is None:
        db.add(LottoTicket(user_id=uid, number=number, bought_at=time.time()))
    else:
        ticket.number = number
        ticket.bought_at = time.time()
    db.flush()
    return True, _fmt(number)


def catch_up(db: Session) -> list[dict]:
    """접근 시 지난 추첨 소급 처리 (Render 절전 대비). 최대 50회까지."""
    state = get_state(db)
    now = time.time()
    results = []
    guard = 0
    while state["last_draw_time"] == 0 or now - state["last_draw_time"] >= DRAW_INTERVAL:
        results.append(draw(db, now))
        guard += 1
        if guard >= 50:
            break
        state = get_state(db)
    return results


def draw(db: Session, now: float | None = None) -> dict:
    """추첨 실행. 결과 dict 반환. (호출부가 주기적으로 호출)"""
    now = now or time.time()
    drawn = random.randint(LOTTO_MIN, LOTTO_MAX)
    state = get_state(db)
    draw_count = state["draw_count"]
    prize = _prize(draw_count)

    rows = db.execute(
        select(LottoTicket).where(LottoTicket.number == drawn)
    ).scalars().all()
    winners = [r.user_id for r in rows]

    if winners:
        share = prize // len(winners)
        for uid in winners:
            change_money(db, uid, share)
        _set_state(db, drawn, now, LOTTO_BASE_PRIZE, 0)
        return {"drawn": drawn, "winners": winners, "share": share, "prize": prize,
                "jackpot": LOTTO_BASE_PRIZE, "rolled": True}
    next_count = draw_count + 1
    next_prize = _prize(next_count)
    _set_state(db, drawn, now, next_prize, next_count)
    return {"drawn": drawn, "winners": [], "prize": prize,
            "jackpot": next_prize, "rolled": False}


def get_display_name(db: Session, uid: int) -> str:
    user = db.get(User, uid)
    return user.username if user else f"user{uid}"
