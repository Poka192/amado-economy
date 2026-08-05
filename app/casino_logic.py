"""카지노 로직 — 봇(cogs/general.py) 이식. 룰렛+소망력+하이롤러."""
from __future__ import annotations

import math
import random

from sqlalchemy.orm import Session

from . import achievements as ach
from .defs import (
    CASINO_COOLDOWN,
    DICE_PAYOUT,
    HIGH_ROLLER_PROFIT_RATE,
    ROULETTE_TABLE,
    SLOT_SYMBOLS,
)
from .logic import change_money, get_money, update_quest_progress
from .models import HopePending, Money

# 소망력 효과 파라미터
HOPE_FAIL_DELTA = 0.001   # 실패 -0.1%
HOPE_MULT_DELTA = 0.0002  # 2/3/5/10/25배 +0.02%


def get_high_roller_level(db: Session, uid: int) -> int:
    from .models import HighRoller
    row = db.get(HighRoller, uid)
    return row.level if row else 0


def high_roller_price(level: int) -> int:
    from .defs import HIGH_ROLLER_BASE_PRICE
    return HIGH_ROLLER_BASE_PRICE * (2 ** level)


def buy_high_roller(db: Session, uid: int):
    """(성공, 새 레벨, 지불액)."""
    from .models import HighRoller
    level = get_high_roller_level(db, uid)
    price = high_roller_price(level)
    balance = get_money(db, uid)
    if balance < price:
        return False, 0, 0
    change_money(db, uid, -price)
    row = db.get(HighRoller, uid)
    if row is None:
        db.add(HighRoller(user_id=uid, level=1))
        new_level = 1
    else:
        row.level += 1
        new_level = row.level
    db.flush()
    return True, new_level, price


def high_roller_bonus(db: Session, uid: int, stake: int, mult) -> int:
    """순이익의 +0.025x × 레벨 (버림)."""
    if mult <= 0:
        return 0
    level = get_high_roller_level(db, uid)
    if level <= 0:
        return 0
    profit = int(stake * mult) - stake
    return max(0, int(profit * HIGH_ROLLER_PROFIT_RATE * level))


def casino_pay(db: Session, uid: int, bet: int, mult) -> int:
    """배팅 차감 + 지급(하이롤러 보너스 포함). 새 잔고 반환."""
    balance = get_money(db, uid)
    stake = max(0, min(bet, balance))
    if stake <= 0:
        return balance
    change_money(db, uid, -stake)  # 스테이크 차감
    if mult <= 0:
        change_money(db, _house(db), stake)  # 패배금 → 하우스
        return get_money(db, uid)
    payout = int(stake * mult)
    payout += high_roller_bonus(db, uid, stake, mult)
    change_money(db, uid, payout)
    return get_money(db, uid)


def adjusted_roulette(hope_count: int):
    """소망력 적용 룰렛 테이블 (개당 실패-0.1%, 배율+0.02%, 정규화)."""
    if hope_count <= 0:
        return ROULETTE_TABLE
    n = hope_count
    table = [
        (0, max(0.0, 0.52 - HOPE_FAIL_DELTA * n)),
        (1.5, 0.30),
        (2, 0.14 + HOPE_MULT_DELTA * n),
        (3, 0.025 + HOPE_MULT_DELTA * n),
        (5, 0.008 + HOPE_MULT_DELTA * n),
        (10, 0.004 + HOPE_MULT_DELTA * n),
        (25, 0.003 + HOPE_MULT_DELTA * n),
    ]
    total = sum(p for _, p in table)
    return [(m, p / total) for m, p in table]


def consume_pending_hope(db: Session, uid: int) -> int:
    """대기 소망력 소모 후 개수 반환."""
    row = db.get(HopePending, uid)
    if row is None or row.count <= 0:
        return 0
    count = row.count
    db.delete(row)
    db.flush()
    return count


def play_roulette(db: Session, uid: int, bet: int) -> dict:
    """결과 dict 반환."""
    hope = consume_pending_hope(db, uid)
    table = adjusted_roulette(hope)
    r = random.random()
    cum = 0
    mult = 0
    for m, p in table:
        cum += p
        if r < cum:
            mult = m
            break
    balance_before = get_money(db, uid)
    new_balance = casino_pay(db, uid, bet, mult)
    bonus = high_roller_bonus(db, uid, min(bet, balance_before), mult) if mult > 0 else 0

    update_quest_progress(db, uid, "daily_4")
    ach.increment_stat(db, uid, "casino_plays")
    if mult >= 25:
        ach.grant(db, uid, "roulette_25x")
    return {
        "game": "룰렛", "mult": mult, "hope": hope, "bonus": bonus,
        "bet": bet, "new_balance": new_balance,
    }


def _play_binary(db: Session, uid: int, bet: int, win: bool) -> dict:
    mult = 1.9 if win else 0
    balance_before = get_money(db, uid)
    new_balance = casino_pay(db, uid, bet, mult)
    bonus = high_roller_bonus(db, uid, min(bet, balance_before), mult) if win else 0
    update_quest_progress(db, uid, "daily_4")
    ach.increment_stat(db, uid, "casino_plays")
    return {"game": "", "mult": mult, "win": win, "bonus": bonus, "bet": bet,
            "new_balance": new_balance}


def play_odd_even(db: Session, uid: int, bet: int, choice: str) -> dict:
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2
    is_odd = total % 2 == 1
    win = (choice == "홀") == is_odd
    res = _play_binary(db, uid, bet, win)
    res.update({"game": "홀짝", "dice": (d1, d2, total), "is_odd": is_odd, "choice": choice})
    return res


def play_high_low(db: Session, uid: int, bet: int, choice: str) -> dict:
    card = random.randint(1, 10)
    is_high = card >= 6
    win = (choice == "하이") == is_high
    res = _play_binary(db, uid, bet, win)
    res.update({"game": "하이로우", "card": card, "is_high": is_high, "choice": choice})
    return res


def play_dice(db: Session, uid: int, bet: int, target: int) -> dict:
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2
    win = total == target
    mult = DICE_PAYOUT[target] if win else 0
    balance_before = get_money(db, uid)
    new_balance = casino_pay(db, uid, bet, mult)
    bonus = high_roller_bonus(db, uid, min(bet, balance_before), mult) if win else 0
    update_quest_progress(db, uid, "daily_4")
    ach.increment_stat(db, uid, "casino_plays")
    if win and target in (2, 12):
        ach.grant(db, uid, "dice_24x")
    return {"game": "주사위", "dice": (d1, d2, total), "target": target, "mult": mult,
            "win": win, "bonus": bonus, "bet": bet, "new_balance": new_balance}


def _slot_payout(reels: list) -> float:
    c = reels
    if c[0] == c[1] == c[2]:
        return {"💎": 40, "⭐": 20, "🍀": 10}.get(c[0], 5)
    if c.count("💎") == 2:
        return 2
    if c.count("⭐") == 2:
        return 1.5
    return 0


def play_slot(db: Session, uid: int, bet: int) -> dict:
    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    mult = _slot_payout(reels)
    balance_before = get_money(db, uid)
    new_balance = casino_pay(db, uid, bet, mult)
    bonus = high_roller_bonus(db, uid, min(bet, balance_before), mult) if mult > 0 else 0
    update_quest_progress(db, uid, "daily_4")
    ach.increment_stat(db, uid, "casino_plays")
    if reels[0] == reels[1] == reels[2] == "💎":
        ach.grant(db, uid, "slot_jackpot")
    return {"game": "슬롯", "reels": reels, "mult": mult, "win": mult > 0,
            "bonus": bonus, "bet": bet, "new_balance": new_balance}


def _house(db: Session) -> int:
    """하우스 계좌 (시스템). 최초 생성."""
    from .models import Money
    row = db.get(Money, 1)
    if row is None:
        db.add(Money(user_id=1, balance=0))
        db.flush()
    return 1


def touch_cooldown(now: float, last: float) -> float:
    return max(0, CASINO_COOLDOWN - (now - last))
