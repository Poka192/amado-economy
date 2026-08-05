"""카지노 — 룰렛/홀짝/하이로우/주사위/슬롯."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import casino_logic as c
from .. import logic
from ..database import get_db
from ..defs import CASINO_COOLDOWN, DICE_PAYOUT
from ..deps import require_user
from ..main import redirect, render
from ..models import User

router = APIRouter()


@router.get("/casino")
async def casino_page(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_user)):
    left = logic.cd_remaining(db, user.id, "cd_casino", CASINO_COOLDOWN)
    hr_level = c.get_high_roller_level(db, user.id)
    return render(request, "casino.html", user=user, cash=logic.get_money(db, user.id),
                  left=left, dice_payout=DICE_PAYOUT, hr_level=hr_level,
                  hr_rate=0.025)


@router.post("/casino/roulette")
async def casino_roulette(request: Request, bet: str = Form(...),
                          db: Session = Depends(get_db), user: User = Depends(require_user)):
    left = logic.cd_remaining(db, user.id, "cd_casino", CASINO_COOLDOWN)
    if left > 0:
        return redirect("/casino", err=f"카지노 쿨다운 {left:.0f}초")
    try:
        amt = int(bet)
    except ValueError:
        return redirect("/casino", err="배팅 금액은 숫자여야 합니다.")
    if amt <= 0:
        return redirect("/casino", err="배팅 금액은 1원 이상이어야 합니다.")
    if logic.get_money(db, user.id) < amt:
        return redirect("/casino", err="소지금 부족")
    logic.cd_set(db, user.id, "cd_casino")
    result = c.play_roulette(db, user.id, amt)
    db.commit()
    return redirect("/casino", msg=_fmt_roulette(result))


def _fmt_roulette(r: dict) -> str:
    if r["mult"] <= 0:
        m = f"💀 룰렛 꽝! -{r['bet']:,}원"
    else:
        m = f"🎯 룰렛 {r['mult']:g}배 당첨!"
    if r["bonus"] > 0:
        m += f" (+🎩보너스 {r['bonus']:,}원)"
    if r["hope"] > 0:
        m += f" 🌠소망력 {r['hope']}개 사용"
    return m


@router.post("/casino/odd_even")
async def casino_odd_even(request: Request, bet: str = Form(...), choice: str = Form(...),
                          db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _binary(request, db, user, bet, lambda: c.play_odd_even(
        db, user.id, _bet(db, user, bet), choice))


@router.post("/casino/high_low")
async def casino_high_low(request: Request, bet: str = Form(...), choice: str = Form(...),
                          db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _binary(request, db, user, bet, lambda: c.play_high_low(
        db, user.id, _bet(db, user, bet), choice))


@router.post("/casino/dice")
async def casino_dice(request: Request, bet: str = Form(...), target: str = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _binary(request, db, user, bet, lambda: c.play_dice(
        db, user.id, _bet(db, user, bet), int(target)))


@router.post("/casino/slot")
async def casino_slot(request: Request, bet: str = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    return _binary(request, db, user, bet, lambda: c.play_slot(
        db, user.id, _bet(db, user, bet)))


def _bet(db: Session, user: User, bet: str) -> int:
    try:
        return max(0, int(bet))
    except ValueError:
        return 0


def _binary(request: Request, db: Session, user: User, bet: str, fn) -> object:
    left = logic.cd_remaining(db, user.id, "cd_casino", CASINO_COOLDOWN)
    if left > 0:
        return redirect("/casino", err=f"카지노 쿨다운 {left:.0f}초")
    try:
        amt = int(bet)
    except ValueError:
        return redirect("/casino", err="배팅 금액은 숫자여야 합니다.")
    if amt <= 0:
        return redirect("/casino", err="배팅 금액은 1원 이상이어야 합니다.")
    if logic.get_money(db, user.id) < amt:
        return redirect("/casino", err="소지금 부족")
    logic.cd_set(db, user.id, "cd_casino")
    result = fn()
    db.commit()
    msg = _fmt_binary(result)
    return redirect("/casino", msg=msg)


def _fmt_binary(r: dict) -> str:
    if r["game"] == "홀짝":
        d1, d2, total = r["dice"]
        desc = f"🎲 주사위 {d1}+{d2}={total} ({'홀' if r['is_odd'] else '짝'})"
        result = f"✅ {r['choice']} 당첨!" if r["win"] else f"❌ {r['choice']} 실패!"
    elif r["game"] == "하이로우":
        desc = f"🃏 카드 {r['card']} ({'하이' if r['is_high'] else '로우'})"
        result = f"✅ {r['choice']} 당첨!" if r["win"] else f"❌ {r['choice']} 실패!"
    elif r["game"] == "주사위":
        d1, d2, total = r["dice"]
        desc = f"🎲 주사위 {d1}+{d2}={total}"
        result = f"✅ {r['target']} 적중! {r['mult']:g}배!" if r["win"] else f"❌ {r['target']} 실패!"
    else:  # 슬롯
        desc = " ".join(r["reels"])
        result = f"✨ {r['mult']:g}배 잭팟!" if r["win"] else "💀 꽝!"
    if r.get("bonus", 0) > 0:
        result += f" (+🎩 {r['bonus']:,}원)"
    return f"{desc} → {result}"
