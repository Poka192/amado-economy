"""로또 — 구매/내복권/최근번호."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import lotto_logic
from ..database import get_db
from ..deps import require_user
from ..main import redirect, render
from ..models import LottoTicket, User

router = APIRouter()


@router.get("/lotto")
async def lotto_page(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_user)):
    last_results = lotto_logic.catch_up(db)
    db.commit()
    state = lotto_logic.get_state(db)
    ticket = lotto_logic.get_ticket(db, user.id)
    now_ticket = None
    if ticket is not None and ticket.bought_at > state["last_draw_time"]:
        now_ticket = ticket.number
    recent = _recent_draws(db, state)
    return render(request, "lotto.html", user=user, state=state, cash=0,
                  ticket=now_ticket, recent=recent, last_results=last_results)


@router.post("/lotto/buy")
async def lotto_buy(request: Request, number: str = Form(...),
                    db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        num = int(number)
    except ValueError:
        return redirect("/lotto", err="번호는 숫자여야 합니다.")
    ok, msg = lotto_logic.buy(db, user.id, num)
    db.commit()
    if not ok:
        return redirect("/lotto", err=msg)
    return redirect("/lotto", msg=f"🎫 번호 {msg} 구매 완료! (다음 추첨 대기)")


def _recent_draws(db: Session, state: dict) -> list:
    """최근 추첨 기록은 LottoState 단일 레코드만 저장하므로, 본 회차만 표시."""
    if state["last_drawn"] is None:
        return []
    return [{"drawn": state["last_drawn"], "jackpot": state["jackpot"],
             "draw_count": state["draw_count"]}]
