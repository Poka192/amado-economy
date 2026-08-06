"""외환 로직 — 환율 시뮬레이션 + 환전/외환 투자.

주식(stocks_logic.py)과 같은 온디맨드 틱 패턴:
- 시스템 상태에 마지막 틱 시각(fx_last_tick)을 저장하고,
- 접근 시 경과 시간만큼 틱을 소급 시뮬레이션한다 (Render 절전에도 시세 보정).
"""
from __future__ import annotations

import math
import random
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import achievements as ach
from .defs import (
    FX_CURRENCIES,
    FX_FEE_RATE,
    FX_MAX_HOLDING_UNITS,
    FX_MIN_EXCHANGE_KRW,
    FX_SIGMA,
    FX_TICK_SECONDS,
    MAX_CATCHUP_TICKS_FX,
    MAX_TICK_MOVE_FX,
    MEAN_REVERSION_FX,
)
from .logic import change_money, get_money
from .models import (
    FxHistory,
    FxHolding,
    FxRate,
    FxTrade,
    SystemState,
)


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


def _base_rate(code: str) -> int:
    """기준 환율(센트). 미지 코드면 0."""
    for c, _name, base, _sig in FX_CURRENCIES:
        if c == code:
            return base
    return 0


def _sigma(code: str) -> float:
    for c, _name, _base, sig in FX_CURRENCIES:
        if c == code:
            return sig
    return FX_SIGMA


# 프로세스당 1회만 시드 존재 확인 (원격 DB 왕복 절약)
_seeded_engines: set[int] = set()

# 표시용 환율 캐시 (5초 TTL) — 페이지마다 통째로 재조회 절감. catch_up 커밋 시 무효화.
_rates_cache: dict[int, tuple[float, dict[str, dict]]] = {}
_RATES_TTL = 5.0


def _is_seeded(db: Session) -> bool:
    return id(db.get_bind()) in _seeded_engines


def _invalidate_rates(db: Session):
    _rates_cache.pop(id(db.get_bind()), None)


def ensure_seed(db: Session):
    """시드: 통화 미존재 시 기준 환율로 생성. (1회만 검사)"""
    if _is_seeded(db):
        return
    existing = db.execute(select(FxRate.code)).scalars().all()
    have = set(existing)
    for code, name, base, _sig in FX_CURRENCIES:
        if code not in have:
            db.add(FxRate(code=code, name=name, rate=base, open_rate=base))
            db.flush()
            db.add(FxHistory(code=code, rate=base, ts=_now()))
    db.flush()
    if state_get(db, "fx_last_tick") == 0:
        state_set(db, "fx_last_tick", _now())
    _seeded_engines.add(id(db.get_bind()))
    _invalidate_rates(db)


def _simulate_tick(rates: dict[str, FxRate]):
    """환율 1틱 메모리 변동 (DB 쓰기 없음)."""
    for code, row in rates.items():
        base = _base_rate(code)
        if base <= 0:
            continue
        drift = MEAN_REVERSION_FX * ((base - row.rate) / base)
        pct = random.gauss(0, _sigma(code)) + drift
        pct = max(-MAX_TICK_MOVE_FX, min(MAX_TICK_MOVE_FX, pct))
        row.rate = max(1, int(round(row.rate * math.exp(pct))))


def catch_up(db: Session) -> int:
    """접근 시 오프라인 시간 보정. 실행한 틱 수 반환.

    원격 DB(예: Supabase)에서는 틱마다 쓰면 수천 번 왕복이 되어
    요청이 수 분간 막히므로, 전체 틱을 메모리에서 시뮬레이션하고
    최종 환율만 한 번에 기록한다.
    """
    ensure_seed(db)
    last = state_get(db, "fx_last_tick")
    now = _now()
    if last <= 0:
        last = now
    elapsed = now - last
    if elapsed < FX_TICK_SECONDS:
        return 0
    ticks = min(int(elapsed / FX_TICK_SECONDS), MAX_CATCHUP_TICKS_FX)
    rates = {r.code: r for r in db.execute(select(FxRate)).scalars().all()}
    for _ in range(ticks):
        _simulate_tick(rates)
    for row in rates.values():
        db.add(FxHistory(code=row.code, rate=row.rate, ts=now))
    db.flush()
    state_set(db, "fx_last_tick", now)
    db.commit()  # 환율 진행 확정 (GET 접근 시에도 반복 실행 방지)
    _invalidate_rates(db)  # 틱 확정 후 캐시 갱신
    return ticks


def get_rates(db: Session) -> dict[str, dict]:
    """모든 통화 환율. {code: {name, rate, open, change, change_pct}}. (5초 TTL 캐시)"""
    ensure_seed(db)
    engine_id = id(db.get_bind())
    now = _now()
    hit = _rates_cache.get(engine_id)
    if hit and now - hit[0] < _RATES_TTL:
        return hit[1]
    rows = db.execute(select(FxRate)).scalars().all()
    out = {}
    for r in rows:
        chg = r.rate - r.open_rate if r.open_rate else 0
        pct = (chg / r.open_rate) * 100 if r.open_rate else 0.0
        out[r.code] = {
            "name": r.name,
            "rate": r.rate,
            "open": r.open_rate,
            "change": chg,
            "change_pct": pct,
        }
    _rates_cache[engine_id] = (now, out)
    return out


def get_rate(db: Session, code: str) -> dict | None:
    ensure_seed(db)
    row = db.get(FxRate, code.upper())
    if row is None:
        return None
    chg = row.rate - row.open_rate if row.open_rate else 0
    pct = (chg / row.open_rate) * 100 if row.open_rate else 0.0
    return {
        "code": row.code,
        "name": row.name,
        "rate": row.rate,
        "open": row.open_rate,
        "change": chg,
        "change_pct": pct,
    }


def get_holding(db: Session, uid: int, code: str) -> FxHolding | None:
    return db.get(FxHolding, (uid, code.upper()))


def get_holdings(db: Session, uid: int) -> list[dict]:
    """유저의 보유 외화 + 평가 정보."""
    rows = db.execute(
        select(FxHolding).where(FxHolding.user_id == uid)
    ).scalars().all()
    # 통화별 환율은 한 번에 로드 (보유 건마다 db.get 하던 N+1 제거)
    rates = {r.code: r for r in db.execute(select(FxRate)).scalars().all()}
    out = []
    for h in rows:
        rate = rates.get(h.code)
        cur_rate = rate.rate if rate else 0
        # 센트 → 외화 단위 → 원화 평가 (1단위 = rate/100 원)
        units = h.amount_cents / 100.0
        value_krw = int(units * cur_rate / 100) if cur_rate else 0
        cost_krw = int(units * h.avg_cost_cents / 100) if h.avg_cost_cents else 0
        profit = value_krw - cost_krw
        profit_pct = (profit / cost_krw) * 100 if cost_krw else 0.0
        out.append({
            "code": h.code,
            "name": rate.name if rate else h.code,
            "amount_cents": h.amount_cents,
            "units": units,
            "avg_cost_cents": h.avg_cost_cents,
            "value_krw": value_krw,
            "cost_krw": cost_krw,
            "profit": profit,
            "profit_pct": profit_pct,
        })
    return out


def get_history(db: Session, code: str, limit: int = 100) -> list[FxHistory]:
    return db.execute(
        select(FxHistory)
        .where(FxHistory.code == code.upper())
        .order_by(FxHistory.id.desc())
        .limit(limit)
    ).scalars().all()[::-1]


def _record_trade(db: Session, uid: int, code: str, side: str,
                  amount_cents: int, rate: int):
    db.add(FxTrade(user_id=uid, code=code.upper(), side=side,
                   amount_cents=amount_cents, rate=rate))


def buy(db: Session, uid: int, code: str, krw: int) -> tuple[bool, str]:
    """원화로 외화 매수 (환전). 수수료 적용 후 환율 기준 센트 환산."""
    code = code.upper()
    if code not in [c for c, *_ in FX_CURRENCIES]:
        return False, "존재하지 않는 통화입니다."
    if krw < FX_MIN_EXCHANGE_KRW:
        return False, f"최소 {FX_MIN_EXCHANGE_KRW:,}원 이상 환전할 수 있습니다."
    rate_row = db.get(FxRate, code)
    if rate_row is None:
        return False, "환율 정보를 찾을 수 없습니다."
    rate = rate_row.rate  # 1단위당 원 × 100 (센트)

    balance = get_money(db, uid)
    if balance < krw:
        return False, f"소지금 부족 ({krw:,}원 필요, 현재 {balance:,}원)"

    # 수수료 차감 후 환전 가능한 외화 (센트)
    # 1단위 = rate/100 원 → net_krw원 = net_krw*100/rate 단위 = net_krw*10_000/rate 센트
    fee = int(krw * FX_FEE_RATE)
    net_krw = krw - fee
    amount_cents = int(net_krw * 10_000 / rate)

    holding = get_holding(db, uid, code)
    if holding is None:
        # 보유 단위 제한 (1단위 = 100센트)
        if amount_cents > FX_MAX_HOLDING_UNITS * 100:
            return False, f"{code} 최대 보유 한도를 초과합니다."
        holding = FxHolding(user_id=uid, code=code,
                            amount_cents=amount_cents, avg_cost_cents=rate)
        db.add(holding)
    else:
        new_amount = holding.amount_cents + amount_cents
        if new_amount > FX_MAX_HOLDING_UNITS * 100:
            return False, f"{code} 최대 보유 한도를 초과합니다."
        total = holding.amount_cents + amount_cents
        # 가중평균 매입가
        if total > 0:
            holding.avg_cost_cents = (
                (holding.avg_cost_cents * holding.amount_cents) + (rate * amount_cents)
            ) // total
        holding.amount_cents = total

    change_money(db, uid, -krw)
    _record_trade(db, uid, code, "buy", amount_cents, rate)
    ach.increment_stat(db, uid, "fx_trades")
    n = ach.stat(db, uid, "fx_trades")
    if n == 1:
        ach.grant(db, uid, "fx_first")
    elif n == 10:
        ach.grant(db, uid, "fx_10")
    units = amount_cents / 100.0
    return True, f"{code} {units:,.2f} 매수 완료 (수수료 {fee:,}원)"

def sell(db: Session, uid: int, code: str, amount_cents: int) -> tuple[bool, str]:
    """외화를 원화로 매도. 수수료 적용."""
    code = code.upper()
    if code not in [c for c, *_ in FX_CURRENCIES]:
        return False, "존재하지 않는 통화입니다."
    if amount_cents <= 0:
        return False, "올바른 수량을 입력하세요."
    holding = get_holding(db, uid, code)
    if holding is None or holding.amount_cents < amount_cents:
        return False, f"{code} 보유량이 부족합니다."
    rate_row = db.get(FxRate, code)
    if rate_row is None:
        return False, "환율 정보를 찾을 수 없습니다."
    rate = rate_row.rate

    # 매도액(원) = (센트 × 환율센트 / 10000), 수수료 차감
    gross = int(amount_cents * rate / 10000)
    fee = int(gross * FX_FEE_RATE)
    net = gross - fee

    # 수익 추적 (매도액 - 평단가 기준)
    avg_cost = holding.avg_cost_cents
    cost = int(amount_cents * avg_cost / 10000) if avg_cost else 0
    profit = net - cost if avg_cost else 0

    holding.amount_cents -= amount_cents
    if holding.amount_cents <= 0:
        db.delete(holding)
    change_money(db, uid, net)
    _record_trade(db, uid, code, "sell", amount_cents, rate)
    ach.increment_stat(db, uid, "fx_trades")
    n = ach.stat(db, uid, "fx_trades")
    if n == 10:
        ach.grant(db, uid, "fx_10")

    if profit > 0:
        total_profit = ach.increment_stat(db, uid, "fx_profit", profit)
        if total_profit >= 100_000:
            ach.grant(db, uid, "fx_profit_100000")
    units = amount_cents / 100.0
    return True, f"{code} {units:,.2f} 매도 완료 (+{net:,}원)"
