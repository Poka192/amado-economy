"""상점/구매/판매/인벤토리/소망력/하이롤러."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import achievements as ach
from .. import logic
from ..casino_logic import (
    buy_high_roller,
    get_high_roller_level,
    high_roller_price,
)
from ..database import get_db
from ..defs import (
    HIGH_ROLLER_BASE_PRICE,
    HIGH_ROLLER_PROFIT_RATE,
    HOPE_MAX_PER_USE,
    HOPE_PRICE,
    HOPE_SELL_PRICE,
    SHOP_ITEMS,
)
from ..deps import require_user
from ..main import redirect, render
from ..models import HighRoller, HopePending, InventoryItem, User

router = APIRouter()


def _inventory(db: Session, uid: int) -> dict[str, int]:
    rows = db.execute(select(InventoryItem).where(InventoryItem.user_id == uid)).scalars().all()
    return {r.item_id: r.quantity for r in rows}


def _get_item_quantity(db: Session, uid: int, item_id: str) -> int:
    row = db.get(InventoryItem, (uid, item_id))
    return row.quantity if row else 0


def _add_item(db: Session, uid: int, item_id: str, qty: int):
    row = db.get(InventoryItem, (uid, item_id))
    if row is None:
        db.add(InventoryItem(user_id=uid, item_id=item_id, quantity=qty))
    else:
        row.quantity += qty
    db.flush()


def _consume_item(db: Session, uid: int, item_id: str, qty: int) -> bool:
    row = db.get(InventoryItem, (uid, item_id))
    if row is None or row.quantity < qty:
        return False
    row.quantity -= qty
    if row.quantity <= 0:
        db.delete(row)
    db.flush()
    return True


def _get_pending_hope(db: Session, uid: int) -> int:
    row = db.get(HopePending, uid)
    return row.count if row else 0


def _add_pending_hope(db: Session, uid: int, qty: int) -> int:
    row = db.get(HopePending, uid)
    cur = row.count if row else 0
    new_count = min(HOPE_MAX_PER_USE, cur + qty)
    if row is None:
        db.add(HopePending(user_id=uid, count=new_count))
    else:
        row.count = new_count
    db.flush()
    return new_count


@router.get("/shop")
async def shop_page(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    return render(request, "shop.html", user=user, items=SHOP_ITEMS,
                  inv=_inventory(db, user.id),
                  hope_price=HOPE_PRICE, hope_sell=HOPE_SELL_PRICE,
                  hr_level=get_high_roller_level(db, user.id),
                  hr_price=high_roller_price(get_high_roller_level(db, user.id)),
                  hr_base=HIGH_ROLLER_BASE_PRICE, hr_rate=HIGH_ROLLER_PROFIT_RATE,
                  pending_hope=_get_pending_hope(db, user.id),
                  hope_max=HOPE_MAX_PER_USE)


@router.post("/shop/buy")
async def shop_buy(request: Request, item_id: str = Form(...), qty: str = Form("1"),
                   db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = next((i for i in SHOP_ITEMS if i[0] == item_id), None)
    if item is None:
        return redirect("/shop", err="존재하지 않는 아이템입니다.")
    try:
        n = int(qty)
    except ValueError:
        return redirect("/shop", err="수량은 숫자여야 합니다.")
    if n <= 0:
        return redirect("/shop", err="수량은 1개 이상이어야 합니다.")
    total = item[3] * n
    if logic.get_money(db, user.id) < total:
        return redirect("/shop", err=f"잔고 부족 ({total:,}원 필요)")
    logic.change_money(db, user.id, -total)
    _add_item(db, user.id, item_id, n)
    shop_count = ach.increment_stat(db, user.id, "shop_buys", n)
    if shop_count == n:
        ach.grant(db, user.id, "shop_first")
    if shop_count >= 10:
        ach.grant(db, user.id, "shop_10")
    db.commit()
    return redirect("/shop", msg=f"🛒 {item[1]} x{n} 구매 완료! (-{total:,}원)")


@router.post("/shop/sell")
async def shop_sell(request: Request, item_id: str = Form(...), qty: str = Form("1"),
                    db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = next((i for i in SHOP_ITEMS if i[0] == item_id), None)
    if item is None:
        return redirect("/shop", err="판매할 수 없는 아이템입니다.")
    try:
        n = int(qty)
    except ValueError:
        return redirect("/shop", err="수량은 숫자여야 합니다.")
    if n <= 0:
        return redirect("/shop", err="수량은 1개 이상이어야 합니다.")
    if not _consume_item(db, user.id, item_id, n):
        return redirect("/shop", err="보유 수량이 부족합니다.")
    total = item[4] * n
    logic.change_money(db, user.id, total)
    db.commit()
    return redirect("/shop", msg=f"💰 {item[1]} x{n} 판매 완료! (+{total:,}원)")


@router.post("/hope/use")
async def hope_use(request: Request, qty: str = Form(...),
                   db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        n = int(qty)
    except ValueError:
        return redirect("/shop", err="개수는 숫자여야 합니다.")
    if n <= 0:
        return redirect("/shop", err="1개 이상 입력하세요.")
    if n > HOPE_MAX_PER_USE:
        return redirect("/shop", err=f"한 번에 최대 {HOPE_MAX_PER_USE:,}개까지 사용 가능합니다.")
    owned = _get_item_quantity(db, user.id, "hope")
    if owned < n:
        return redirect("/shop", err=f"보유한 소망력이 {owned}개입니다.")
    pending = _get_pending_hope(db, user.id)
    if pending + n > HOPE_MAX_PER_USE:
        room = HOPE_MAX_PER_USE - pending
        return redirect("/shop", err=f"대기 버퍼 초과 (최대 {HOPE_MAX_PER_USE:,}개, {room}개만 더 가능)")
    _consume_item(db, user.id, "hope", n)
    new_pending = _add_pending_hope(db, user.id, n)
    db.commit()
    return redirect("/shop", msg=f"🌠 소망력 {n}개 사용! (대기 {new_pending}개, 다음 룰렛 적용)")


@router.post("/highroller/buy")
async def hr_buy(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_user)):
    ok, new_level, paid = buy_high_roller(db, user.id)
    db.commit()
    if not ok:
        return redirect("/shop", err=f"하이롤러 구매에 {high_roller_price(get_high_roller_level(db, user.id)):,}원이 필요합니다.")
    return redirect("/shop", msg=f"🎩 하이롤러 Lv.{new_level} 구매 완료! (-{paid:,}원)")
