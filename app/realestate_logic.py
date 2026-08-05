"""부동산 로직 — 봇(cogs/realestate.py) 이식."""
from __future__ import annotations

import math
import random
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import achievements as ach
from .defs import (
    ANTI_FLIP_SECONDS,
    MAX_ACCRUE_HOURS,
    MAX_CATCHUP_TICKS,
    MAX_LEVEL,
    MAX_TICK_MOVE_RE,
    MEAN_REVERSION_RE,
    PRICE_MAX_RATIO,
    PRICE_MIN_RATIO,
    PROPERTY_LIMIT,
    PROPERTY_MAP,
    PROPERTY_TYPES,
    RE_MARKET_SIGMA,
    RENOVATE_COOLDOWN,
    RENOVATE_COST_RATE,
    RENOVATE_RENT_RATE,
    RENOVATE_VALUE_RATE,
    SELL_FEE_RATE,
    STAFF_HIRE_RATE,
    STAFF_MANAGER_RENT,
    STAFF_GUARD_MAINT,
    STAFF_MAX_BASE,
    STAFF_PROMO_VALUE,
    STAFF_SALARY_RATE,
)
from .logic import change_money, get_money
from .models import (
    Property,
    PropertyListing,
    PropertyMarket,
    PropertyState,
    SystemState,
    User,
)


def _now() -> float:
    return time.time()


def ensure_market(db: Session):
    rows = db.execute(select(PropertyMarket)).scalars().all()
    have = {r.type_id for r in rows}
    for tid, _name, base, _rent, _maint in PROPERTY_TYPES:
        if tid not in have:
            db.add(PropertyMarket(type_id=tid, price=base))
            db.flush()
    state = db.get(PropertyState, 1)
    if state is None:
        db.add(PropertyState(id=1, last_tick_time=_now()))
    db.flush()


def get_market_prices(db: Session) -> dict[str, int]:
    ensure_market(db)
    rows = db.execute(select(PropertyMarket)).scalars().all()
    return {r.type_id: r.price for r in rows}


def _market_tick(db: Session, now: float):
    """모든 종목 가격 갱신 (평균회귀 + 랜덤, 기준가 70~160% 클램프)."""
    market_shock = random.gauss(0, RE_MARKET_SIGMA)
    for row in db.execute(select(PropertyMarket)).scalars().all():
        tid, base = PROPERTY_MAP[row.type_id][0], PROPERTY_MAP[row.type_id][2]
        drift = MEAN_REVERSION_RE * ((base - row.price) / base)
        pct = market_shock + random.gauss(0, RE_MARKET_SIGMA) + drift
        pct = max(-MAX_TICK_MOVE_RE, min(MAX_TICK_MOVE_RE, pct))
        new_price = int(round(row.price * math.exp(pct)))
        row.price = max(int(base * PRICE_MIN_RATIO), min(int(base * PRICE_MAX_RATIO), new_price))
    db.flush()


def catch_up(db: Session):
    """오프라인 시간 보정 (가격 틱 + 임대 정산)."""
    ensure_market(db)
    state = db.get(PropertyState, 1)
    last = state.last_tick_time if state else _now()
    now = _now()
    elapsed = now - last
    if elapsed >= 600:
        missed = min(int(elapsed / 600), MAX_CATCHUP_TICKS)
        for _ in range(missed):
            _market_tick(db, now)
    # 임대 정산
    for owner in db.execute(select(Property.owner_id).distinct()).scalars().all():
        _settle_owner(db, owner, now)
    state = db.get(PropertyState, 1)
    if state is None:
        state = PropertyState(id=1)
        db.add(state)
    state.last_tick_time = now
    db.commit()


# ---------------------------------------------------------------------------
# 가치/수익 계산
# ---------------------------------------------------------------------------

def property_value(db: Session, type_id: str, level: int, staff_promo: int) -> int:
    market = get_market_prices(db)
    t = PROPERTY_MAP[type_id]
    base = t[2]
    return market.get(type_id, base) + int(base * RENOVATE_VALUE_RATE * level) \
        + int(base * STAFF_PROMO_VALUE * staff_promo)


def property_net_per_hour(type_id: str, level: int, sm: int, sg: int, sp: int) -> float:
    """시간당 순수익 (임대료 − 관리비 − 인력 급여)."""
    t = PROPERTY_MAP[type_id]
    base, rent, maint = t[2], t[3], t[4]
    rent_eff = rent * (1 + RENOVATE_RENT_RATE * level) * (1 + STAFF_MANAGER_RENT * sm)
    maint_eff = maint * (1 + RENOVATE_RENT_RATE * level) * (1 - STAFF_GUARD_MAINT * sg)
    salary = base * STAFF_SALARY_RATE * (sm + sg + sp)
    return rent_eff - maint_eff - salary


def max_staff(level: int) -> int:
    return min(5, STAFF_MAX_BASE + level)


def _settle_owner(db: Session, owner_id: int, now: float):
    for p in db.execute(
        select(Property).where(Property.owner_id == owner_id)
    ).scalars().all():
        hours = min(MAX_ACCRUE_HOURS, max(0.0, (now - p.last_accrual_at) / 3600))
        net = property_net_per_hour(p.type_id, p.level, p.staff_man, p.staff_guard, p.staff_promo)
        amount = int(net * hours)
        if amount:
            change_money(db, owner_id, amount)
            ach.grant(db, owner_id, "re_first_rent")
        p.last_accrual_at = now
    db.flush()


# ---------------------------------------------------------------------------
# 구매/판매/리모델링/고용
# ---------------------------------------------------------------------------

def buy_property(db: Session, uid: int, type_id: str) -> tuple[bool, str]:
    if type_id not in PROPERTY_MAP:
        return False, "존재하지 않는 부동산입니다."
    market = get_market_prices(db)
    price = market.get(type_id, PROPERTY_MAP[type_id][2])
    count = db.execute(select(func.count()).select_from(Property)
                       .where(Property.owner_id == uid)).scalar()
    if count >= PROPERTY_LIMIT:
        return False, f"보유 한도 {PROPERTY_LIMIT}개를 초과합니다."
    if get_money(db, uid) < price:
        return False, f"잔고 부족 ({price:,}원 필요)"
    change_money(db, uid, -price)
    db.add(Property(owner_id=uid, type_id=type_id, level=1, sell_price=price))
    db.flush()
    ach.grant(db, uid, "re_first_property")
    if type_id == "resort":
        ach.grant(db, uid, "re_casino_resort")
    return True, PROPERTY_MAP[type_id][1]


def sell_property(db: Session, uid: int, prop_id: int) -> tuple[bool, str]:
    p = db.get(Property, prop_id)
    if p is None or p.owner_id != uid:
        return False, "보유하지 않은 부동산입니다."
    if _now() - p.bought_at < ANTI_FLIP_SECONDS:
        return False, "구매 후 24시간 이내엔 매각할 수 없습니다."
    value = property_value(db, p.type_id, p.level, p.staff_promo)
    fee = int(value * SELL_FEE_RATE)
    change_money(db, uid, value - fee)
    db.delete(p)
    db.flush()
    ach.increment_stat(db, uid, "re_sells")
    return True, f"+{value - fee:,}원 (수수료 {fee:,}원)"


def renovate(db: Session, uid: int, prop_id: int) -> tuple[bool, str]:
    p = db.get(Property, prop_id)
    if p is None or p.owner_id != uid:
        return False, "보유하지 않은 부동산입니다."
    if p.level >= MAX_LEVEL:
        return False, "이미 최대 레벨입니다."
    if _now() - p.bought_at < RENOVATE_COOLDOWN:
        return False, "리모델링 쿨다운(24시간) 중입니다."
    base = PROPERTY_MAP[p.type_id][2]
    cost = int(base * RENOVATE_COST_RATE * (p.level + 1))
    if get_money(db, uid) < cost:
        return False, f"리모델링 비용 {cost:,}원이 부족합니다."
    change_money(db, uid, -cost)
    p.level += 1
    p.bought_at = _now()  # 쿨다운 갱신
    db.flush()
    if p.level >= 5:
        ach.grant(db, uid, "re_renovation_5")
    return True, f"Lv.{p.level}"


def hire_staff(db: Session, uid: int, prop_id: int, kind: str) -> tuple[bool, str]:
    p = db.get(Property, prop_id)
    if p is None or p.owner_id != uid:
        return False, "보유하지 않은 부동산입니다."
    slot = {"man": p.staff_man, "guard": p.staff_guard, "promo": p.staff_promo}
    if slot[kind] >= max_staff(p.level):
        return False, "인력 한도 초과"
    base = PROPERTY_MAP[p.type_id][2]
    cost = int(base * STAFF_HIRE_RATE)
    if get_money(db, uid) < cost:
        return False, f"고용 비용 {cost:,}원이 부족합니다."
    change_money(db, uid, -cost)
    setattr(p, f"staff_{kind}", slot[kind] + 1)
    db.flush()
    return True, kind


def fire_staff(db: Session, uid: int, prop_id: int, kind: str) -> tuple[bool, str]:
    p = db.get(Property, prop_id)
    if p is None or p.owner_id != uid:
        return False, "보유하지 않은 부동산입니다."
    slot = {"man": p.staff_man, "guard": p.staff_guard, "promo": p.staff_promo}
    if slot[kind] <= 0:
        return False, "해당 인력이 없습니다."
    setattr(p, f"staff_{kind}", slot[kind] - 1)
    db.flush()
    return True, kind


# ---------------------------------------------------------------------------
# 플레이어 간 거래 (매물 등록/취소/구매)
# ---------------------------------------------------------------------------

def list_property(db: Session, uid: int, prop_id: int, price: int) -> tuple[bool, str]:
    p = db.get(Property, prop_id)
    if p is None or p.owner_id != uid:
        return False, "보유하지 않은 부동산입니다."
    if price < 500_000:
        return False, "매물 가격은 50만원 이상이어야 합니다."
    if _now() - p.bought_at < ANTI_FLIP_SECONDS:
        return False, "구매 후 24시간 이내엔 등록할 수 없습니다."
    db.add(PropertyListing(owner_id=uid, type_id=p.type_id, level=p.level,
                           staff_man=p.staff_man, staff_guard=p.staff_guard,
                           staff_promo=p.staff_promo, price=price))
    db.delete(p)
    db.flush()
    return True, "등록 완료"


def cancel_listing(db: Session, uid: int, listing_id: int) -> tuple[bool, str]:
    li = db.get(PropertyListing, listing_id)
    if li is None or li.owner_id != uid:
        return False, "내 매물이 아닙니다."
    db.add(Property(owner_id=uid, type_id=li.type_id, level=li.level,
                    staff_man=li.staff_man, staff_guard=li.staff_guard,
                    staff_promo=li.staff_promo))
    db.delete(li)
    db.flush()
    return True, "취소 완료"


def buy_listing(db: Session, uid: int, listing_id: int) -> tuple[bool, str]:
    li = db.get(PropertyListing, listing_id)
    if li is None:
        return False, "존재하지 않는 매물입니다."
    if li.owner_id == uid:
        return False, "내 매물은 구매할 수 없습니다."
    count = db.execute(select(func.count()).select_from(Property)
                       .where(Property.owner_id == uid)).scalar()
    if count >= PROPERTY_LIMIT:
        return False, f"보유 한도 {PROPERTY_LIMIT}개를 초과합니다."
    if get_money(db, uid) < li.price:
        return False, f"잔고 부족 ({li.price:,}원 필요)"
    change_money(db, uid, -li.price)
    change_money(db, li.owner_id, li.price)
    db.add(Property(owner_id=uid, type_id=li.type_id, level=li.level,
                    staff_man=li.staff_man, staff_guard=li.staff_guard,
                    staff_promo=li.staff_promo))
    db.delete(li)
    db.flush()
    ach.grant(db, uid, "re_first_trade")
    ach.grant(db, li.owner_id, "re_first_trade")
    return True, "구매 완료"


def owner_name(db: Session, uid: int) -> str:
    u = db.get(User, uid)
    return u.username if u else f"user{uid}"
