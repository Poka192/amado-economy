"""부동산 — 시세/구매/판매/리모델링/고용/플레이어 거래."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import realestate_logic as re
from ..database import get_db
from ..defs import PROPERTY_TYPES
from ..deps import require_user
from ..main import redirect, render
from ..models import Property, PropertyListing, User

router = APIRouter()


@router.get("/realestate")
async def re_page(request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_user)):
    re.catch_up(db)
    market = re.get_market_prices(db)
    owned_raw = db.execute(select(Property).where(Property.owner_id == user.id)).scalars().all()
    owned = []
    for p in owned_raw:
        owned.append({
            "id": p.id, "type_id": p.type_id, "level": p.level,
            "staff_man": p.staff_man, "staff_guard": p.staff_guard,
            "staff_promo": p.staff_promo,
            "value": re.property_value(db, p.type_id, p.level, p.staff_promo),
            "net": int(re.property_net_per_hour(p.type_id, p.level,
                                                p.staff_man, p.staff_guard, p.staff_promo)),
        })
    listings = db.execute(select(PropertyListing)).scalars().all()
    return render(request, "realestate.html", user=user, types=PROPERTY_TYPES,
                  market=market, owned=owned, listings=listings,
                  limit=re.PROPERTY_LIMIT, max_level=re.MAX_LEVEL,
                  re=re, owner_name=re.owner_name)


@router.post("/realestate/buy")
async def re_buy(request: Request, type_id: str = Form(...),
                 db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.buy_property(db, user.id, type_id)
    db.commit()
    return redirect("/realestate", msg=msg if ok else "", err="" if ok else msg)


@router.post("/realestate/sell")
async def re_sell(request: Request, prop_id: str = Form(...),
                  db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.sell_property(db, user.id, int(prop_id))
    db.commit()
    return redirect("/realestate", msg=("매각 완료 " + msg) if ok else "", err="" if ok else msg)


@router.post("/realestate/renovate")
async def re_renovate(request: Request, prop_id: str = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.renovate(db, user.id, int(prop_id))
    db.commit()
    return redirect("/realestate", msg=("리모델링 완료 Lv." + msg) if ok else "", err="" if ok else msg)


@router.post("/realestate/hire")
async def re_hire(request: Request, prop_id: str = Form(...), kind: str = Form(...),
                  db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.hire_staff(db, user.id, int(prop_id), kind)
    db.commit()
    return redirect("/realestate", msg="고용 완료!" if ok else "", err="" if ok else msg)


@router.post("/realestate/fire")
async def re_fire(request: Request, prop_id: str = Form(...), kind: str = Form(...),
                  db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.fire_staff(db, user.id, int(prop_id), kind)
    db.commit()
    return redirect("/realestate", msg="해고 완료" if ok else "", err="" if ok else msg)


@router.post("/realestate/list")
async def re_list(request: Request, prop_id: str = Form(...), price: str = Form(...),
                  db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        p = int(price)
    except ValueError:
        return redirect("/realestate", err="가격은 숫자여야 합니다.")
    ok, msg = re.list_property(db, user.id, int(prop_id), p)
    db.commit()
    return redirect("/realestate", msg=("매물 등록 완료 " + msg) if ok else "", err="" if ok else msg)


@router.post("/realestate/list_cancel")
async def re_list_cancel(request: Request, listing_id: str = Form(...),
                         db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.cancel_listing(db, user.id, int(listing_id))
    db.commit()
    return redirect("/realestate", msg="매물 취소 완료" if ok else "", err="" if ok else msg)


@router.post("/realestate/buy_listing")
async def re_buy_listing(request: Request, listing_id: str = Form(...),
                         db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, msg = re.buy_listing(db, user.id, int(listing_id))
    db.commit()
    return redirect("/realestate", msg=("구매 완료 " + msg) if ok else "", err="" if ok else msg)
