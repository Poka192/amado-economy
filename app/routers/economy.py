"""대시보드/구걸/알바/송금/은행/직업/퀘스트."""
from __future__ import annotations

import random
import time as _time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import achievements as ach
from .. import logic
from .. import realestate_logic as re_logic
from .. import stocks_logic as st_logic
from ..config import LOAN_MIN
from ..database import get_db
from ..deps import require_user
from ..main import redirect, render
from ..models import BankAccount, BankLoan, Property, User, UserJob

router = APIRouter()


def _wants_json(request: Request) -> bool:
    """AJAX 폼(fetch)은 Accept: application/json 을 보낸다."""
    return "application/json" in request.headers.get("accept", "")


def _net_worth(db: Session, uid: int) -> dict:
    # GET에서 이자를 실제로 기입(bank_settle)하지 않고 순수 계산만 한다.
    # (이자 반영 시점은 다음 액션의 commit으로 미뤄진다 — 표시값은 동일)
    now = _time.time()
    acc = db.get(BankAccount, uid)
    deposit = logic.accrued_deposit(acc.balance, acc.last_interest_at, now) if acc else 0
    loan = db.get(BankLoan, uid)
    loan_debt = 0
    if loan is not None:
        p, i = logic.accrued_loan(loan.principal, loan.interest, loan.last_interest_at, now)
        loan_debt = p + i
    cash = logic.get_money(db, uid)

    prices = {t: v["price"] for t, v in st_logic.get_prices(db).items()}
    stock_value = 0
    stock_count = 0
    for h in st_logic.get_holdings(db, uid):
        p = prices.get(h.ticker, h.avg_price)
        stock_value += h.quantity * p
        stock_count += h.quantity

    market = re_logic.get_market_prices(db)  # 내부에서 ensure_market 수행
    re_value = 0
    re_count = 0
    from ..models import Property
    for p in db.execute(select(Property).where(Property.owner_id == uid)).scalars().all():
        base = re_logic.PROPERTY_MAP[p.type_id][2]
        re_value += market.get(p.type_id, base) \
            + int(base * re_logic.RENOVATE_VALUE_RATE * p.level) \
            + int(base * re_logic.STAFF_PROMO_VALUE * p.staff_promo)
        re_count += 1

    total = cash + deposit + stock_value + re_value - loan_debt
    return {
        "cash": cash, "deposit": deposit, "loan": loan_debt, "stock": stock_value,
        "stock_count": stock_count, "property": re_value, "property_count": re_count,
        "total": total,
    }


@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    st_logic.catch_up(db)
    re_logic.catch_up(db)
    worth = _net_worth(db, user.id)

    # 쿨다운 표시
    return render(request, "dashboard.html", worth=worth, user=user,
                  beg_left=logic.cd_remaining(db, user.id, "cd_beg", 10),
                  alba_left=logic.cd_remaining(db, user.id, "cd_alba", 300))


# ---------------------------------------------------------------------------
# 구걸 / 알바
# ---------------------------------------------------------------------------

@router.post("/beg")
async def beg(request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_user)):
    left = logic.cd_remaining(db, user.id, "cd_beg", 10)
    if left > 0:
        if _wants_json(request):
            return JSONResponse({"ok": False, "msg": f"구걸 쿨다운 {left:.0f}초",
                                 "cash": logic.get_money(db, user.id), "beg_left": left})
        return redirect("/dashboard", err=f"구걸 쿨다운 {left:.0f}초")
    logic.cd_set(db, user.id, "cd_beg")
    amount = random.randint(-50_000, 25_000)
    new_balance = logic.change_money(db, user.id, amount)
    ach.increment_stat(db, user.id, "beg_count")
    if new_balance == 0:
        ach.grant(db, user.id, "beggar_0")
    db.commit()
    msg = f"{amount:,}원 획득! (잔고 {new_balance:,}원)" if amount >= 0 else \
        f"{amount:,}원 잃음! (잔고 {new_balance:,}원)"
    msg = f"🦹 구걸 결과: {msg}"
    if _wants_json(request):
        return JSONResponse({"ok": True, "msg": msg, "cash": new_balance, "beg_left": 10})
    return redirect("/dashboard", msg=msg)


@router.post("/alba")
async def alba(request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_user)):
    left = logic.cd_remaining(db, user.id, "cd_alba", 300)
    if left > 0:
        if _wants_json(request):
            return JSONResponse({"ok": False, "msg": f"알바 쿨다운 {left:.0f}초",
                                 "cash": logic.get_money(db, user.id), "alba_left": left})
        return redirect("/dashboard", err=f"알바 쿨다운 {left:.0f}초")
    logic.cd_set(db, user.id, "cd_alba")
    job = random.choice(["🍞 편의점", "☕ 카페", "🍔 패스트푸드", "🍕 피자집", "📦 택배",
                         "🚚 배달", "🧹 청소", "📚 서점", "🎮 PC방", "🌷 꽃집"])
    wage = random.randint(10_000, 50_000)
    new_balance = logic.change_money(db, user.id, wage)
    logic.update_quest_progress(db, user.id, "daily_5")
    count = ach.increment_stat(db, user.id, "alba_plays")
    if count >= 10:
        ach.grant(db, user.id, "alba_10")
    if count >= 50:
        ach.grant(db, user.id, "alba_50")
    db.commit()
    msg = f"💼 {job} 알바 완료! +{wage:,}원 (잔고 {new_balance:,}원)"
    if _wants_json(request):
        return JSONResponse({"ok": True, "msg": msg, "cash": new_balance, "alba_left": 300})
    return redirect("/dashboard", msg=msg)


# ---------------------------------------------------------------------------
# 송금
# ---------------------------------------------------------------------------

@router.post("/transfer")
async def transfer(request: Request, username: str = Form(...),
                   amount: str = Form(...), db: Session = Depends(get_db),
                   user: User = Depends(require_user)):
    target = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
    if target is None:
        return redirect("/dashboard", err="대상 유저가 없습니다.")
    if target.id == user.id:
        return redirect("/dashboard", err="자기 자신에게는 송금할 수 없습니다.")
    try:
        amt = int(amount)
    except ValueError:
        return redirect("/dashboard", err="금액은 숫자여야 합니다.")
    if amt <= 0:
        return redirect("/dashboard", err="금액은 1원 이상이어야 합니다.")
    if logic.get_money(db, user.id) < amt:
        return redirect("/dashboard", err="소지금이 부족합니다.")
    logic.change_money(db, user.id, -amt)
    logic.change_money(db, target.id, amt)
    db.commit()
    return redirect("/dashboard", msg=f"💸 {target.username}님에게 {amt:,}원 송금 완료")


# ---------------------------------------------------------------------------
# 은행
# ---------------------------------------------------------------------------

@router.get("/bank")
async def bank_page(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    deposit, loan_p, loan_i = logic.bank_settle(db, user.id)
    cash = logic.get_money(db, user.id)
    limit = logic.loan_limit(deposit, loan_p + loan_i)
    return render(request, "bank.html", user=user, cash=cash, deposit=deposit,
                  loan_p=loan_p, loan_i=loan_i, loan_total=loan_p + loan_i, limit=limit)


@router.post("/bank/deposit")
async def bank_deposit(request: Request, amount: str = Form(...),
                       db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        amt = int(amount)
    except ValueError:
        return redirect("/bank", err="금액은 숫자여야 합니다.")
    cash = logic.get_money(db, user.id)
    if amt <= 0 or cash < amt:
        return redirect("/bank", err="잔고 부족")
    logic.change_money(db, user.id, -amt)
    deposit, _, _ = logic.bank_settle(db, user.id)
    acc = db.get(logic.BankAccount, user.id)
    acc.balance += amt
    logic.update_quest_progress(db, user.id, "daily_6", amt)
    if acc.balance > 0:
        ach.grant(db, user.id, "bank_first")
    if acc.balance >= 100_000:
        ach.grant(db, user.id, "bank_100000")
    db.commit()
    return redirect("/bank", msg=f"🏦 {amt:,}원 예치 완료")


@router.post("/bank/withdraw")
async def bank_withdraw(request: Request, amount: str = Form(...),
                        db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        amt = int(amount)
    except ValueError:
        return redirect("/bank", err="금액은 숫자여야 합니다.")
    deposit, _, _ = logic.bank_settle(db, user.id)
    if amt <= 0 or deposit < amt:
        return redirect("/bank", err="예치금 부족")
    acc = db.get(logic.BankAccount, user.id)
    acc.balance -= amt
    logic.change_money(db, user.id, amt)
    db.commit()
    return redirect("/bank", msg=f"🏦 {amt:,}원 출금 완료")


@router.post("/bank/loan")
async def bank_loan(request: Request, amount: str = Form(...),
                    db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        amt = int(amount)
    except ValueError:
        return redirect("/bank", err="금액은 숫자여야 합니다.")
    if amt < LOAN_MIN:
        return redirect("/bank", err=f"대출은 최소 {LOAN_MIN:,}원부터입니다.")
    deposit, loan_p, loan_i = logic.bank_settle(db, user.id)
    available = logic.loan_limit(deposit, loan_p + loan_i)
    if amt > available:
        return redirect("/bank", err=f"대출 한도 초과 (추가 가능 {available:,}원)")
    loan = db.get(logic.BankLoan, user.id)
    if loan is None:
        db.add(logic.BankLoan(user_id=user.id, principal=amt, interest=0))
    else:
        loan.principal += amt
    logic.change_money(db, user.id, amt)
    ach.grant(db, user.id, "loan_first")
    db.commit()
    return redirect("/bank", msg=f"🏦 {amt:,}원 대출 완료 (이자 0.05%/분)")


@router.post("/bank/repay")
async def bank_repay(request: Request, amount: str = Form(""),
                     db: Session = Depends(get_db), user: User = Depends(require_user)):
    _, loan_p, loan_i = logic.bank_settle(db, user.id)
    loan = db.get(logic.BankLoan, user.id)
    if loan is None or (loan.principal + loan.interest) <= 0:
        return redirect("/bank", err="대출이 없습니다.")
    if amount.strip() == "":
        repay = loan.principal + loan.interest  # 전액
    else:
        try:
            repay = int(amount)
        except ValueError:
            return redirect("/bank", err="금액은 숫자여야 합니다.")
    total_debt = loan.principal + loan.interest
    repay = max(0, min(repay, total_debt))
    cash = logic.get_money(db, user.id)
    if repay > cash:
        return redirect("/bank", err="소지금 부족")
    logic.change_money(db, user.id, -repay)
    # 이자 먼저, 잔여는 원금
    interest_paid = min(loan.interest, repay)
    loan.interest -= interest_paid
    remaining = repay - interest_paid
    loan.principal -= remaining
    db.commit()
    return redirect("/bank", msg=f"🏦 {repay:,}원 상환 완료")


# ---------------------------------------------------------------------------
# 직업
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def jobs_page(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    my_job = db.get(UserJob, user.id)
    work_left = logic.cd_remaining(db, user.id, "cd_work", 300)
    return render(request, "jobs.html", user=user, jobs=logic.JOBS, my_job=my_job,
                  work_left=work_left)


@router.post("/jobs/select")
async def job_select(request: Request, job_id: str = Form(...),
                     db: Session = Depends(get_db), user: User = Depends(require_user)):
    if logic.select_job(db, user.id, job_id):
        db.commit()
        name = next((j[1] for j in logic.JOBS if j[0] == job_id), job_id)
        return redirect("/jobs", msg=f"💼 {name} 선택 완료!")
    return redirect("/jobs", err="직업을 찾을 수 없습니다.")


@router.post("/jobs/work")
async def job_work(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_user)):
    left = logic.cd_remaining(db, user.id, "cd_work", 300)
    if left > 0:
        if _wants_json(request):
            return JSONResponse({"ok": False, "msg": f"출근 쿨다운 {left:.0f}초",
                                 "cash": logic.get_money(db, user.id), "work_left": left})
        return redirect("/jobs", err=f"출근 쿨다운 {left:.0f}초")
    result = logic.work_job(db, user.id)
    if result[0] is None:
        if _wants_json(request):
            return JSONResponse({"ok": False, "msg": "직업을 먼저 선택하세요.",
                                 "cash": logic.get_money(db, user.id), "work_left": 0})
        return redirect("/jobs", err="직업을 먼저 선택하세요.")
    salary, leveled_up, next_level, level = result
    logic.cd_set(db, user.id, "cd_work")
    ach.increment_stat(db, user.id, "job_works")
    msg = f"💼 출근 완료! +{salary:,}원"
    if leveled_up:
        msg += f" 🎉 Lv.{level} 레벨업!"
    db.commit()
    if _wants_json(request):
        return JSONResponse({"ok": True, "msg": msg, "cash": logic.get_money(db, user.id),
                             "work_left": 300, "level": level,
                             "leveled_up": leveled_up})
    return redirect("/jobs", msg=msg)


# ---------------------------------------------------------------------------
# 퀘스트
# ---------------------------------------------------------------------------

@router.get("/quests")
async def quests_page(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_user)):
    date = logic.today_str()
    from ..models import QuestProgress
    rows = db.execute(select(QuestProgress).where(
        QuestProgress.user_id == user.id, QuestProgress.date == date)).scalars().all()
    prog = {(r.quest_id): r for r in rows}
    quests = []
    for qid, name, desc, reward in logic.DAILY_QUESTS:
        r = prog.get(qid)
        quests.append({
            "id": qid, "name": name, "desc": desc, "reward": reward,
            "threshold": logic.QUEST_THRESHOLDS[qid],
            "progress": r.progress if r else 0,
            "completed": bool(r.completed) if r else False,
            "claimed": bool(r.claimed) if r else False,
        })
    total_claimed = sum(1 for q in quests if q["claimed"])
    return render(request, "quests.html", user=user, quests=quests,
                  total_claimed=total_claimed)


@router.post("/quests/claim")
async def quest_claim(request: Request, quest_id: str = Form(...),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    ok, reward = logic.claim_quest_reward(db, user.id, quest_id)
    db.commit()
    if not ok:
        return redirect("/quests", err="완료되지 않았거나 이미 수령했습니다.")
    return redirect("/quests", msg=f"📋 {reward:,}원 보상 수령!")
