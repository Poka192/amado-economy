"""핵심 경제 로직 — 봇(cogs/bank.py, money_systems.py, general.py) 이식.

모든 함수는 `db: Session`을 첫 인자로 받는다 (SQLAlchemy 세션).
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    BANK_INTEREST_RATE,
    LOAN_INTEREST_RATE,
    LOAN_BASE,
    LOAN_DEPOSIT_FACTOR,
    LOAN_MIN,
    MAX_ACCRUE_MINUTES,
    MAX_LOAN,
)
from .models import (
    BankAccount,
    BankLoan,
    Money,
    QuestProgress,
    User,
    UserJob,
)

MONEY_DEFAULT = 5000

# 일일 퀘스트 정의: (id, 이름, 설명, 보상금) — 봇과 동일
DAILY_QUESTS = [
    ("daily_1", "📚 단어 학습", "끝말잇기 게임 1회 플레이", 3000),
    ("daily_2", "🎮 게임 마스터", "끝말잇기 게임 3회 플레이", 8000),
    ("daily_3", "💬 소셜 버터플라이", "채팅 10회 입력", 2000),
    ("daily_4", "🎰 행운의 룰렛", "카지노에서 1회 플레이", 4000),
    ("daily_5", "💼 알바왕", "알바 1회 실행", 5000),
    ("daily_6", "💰 저축왕", "은행에 1000원 이상 예치", 6000),
    ("daily_7", "📈 투자자", "주식 1주 이상 매수", 5000),
]
QUEST_THRESHOLDS = {"daily_1": 1, "daily_2": 3, "daily_3": 10, "daily_4": 1,
                    "daily_5": 1, "daily_6": 1000, "daily_7": 1}

# 직업: (id, 이름, 설명, 기본급, 레벨업 필요 횟수, 레벨별 추가급)
JOBS = [
    ("convenience", "🏪 편의점 알바", "편의점에서 일합니다", 1500, 10, 200),
    ("cafe", "☕ 카페 알바", "카페에서 일합니다", 2000, 12, 250),
    ("delivery", "🚚 배달 알바", "배달을 합니다", 2500, 15, 300),
    ("pcbang", "🎮 PC방 알바", "PC방에서 일합니다", 3000, 18, 350),
    ("office", "🏢 사무직", "사무실에서 일합니다", 4000, 20, 500),
    ("manager", "👔 매니저", "매니저로 일합니다", 5500, 25, 600),
    ("ceo", "👔 CEO", "회사를 운영합니다", 8000, 30, 800),
]

# ---------------------------------------------------------------------------
# 돈
# ---------------------------------------------------------------------------

def get_money(db: Session, uid: int) -> int:
    row = db.get(Money, uid)
    if row is None:
        row = Money(user_id=uid, balance=MONEY_DEFAULT)
        db.add(row)
        db.flush()
    return row.balance


def change_money(db: Session, uid: int, delta: int) -> int:
    row = db.get(Money, uid)
    if row is None:
        row = Money(user_id=uid, balance=max(0, MONEY_DEFAULT + delta))
        db.add(row)
        db.flush()
        return row.balance
    row.balance = max(0, row.balance + delta)
    db.flush()
    return row.balance


# ---------------------------------------------------------------------------
# 은행 (예치 이자 / 대출 이자 / 한도 / 상환)
# ---------------------------------------------------------------------------

def _elapsed_minutes(last: float, now: float) -> float:
    return min(MAX_ACCRUE_MINUTES, max(0.0, (now - last) / 60))


def accrued_deposit(balance: int, last_interest_at: float, now: float) -> int:
    """예치금에 이자를 더한 정산값. (쓰기 없음 — 랭킹/표시용)"""
    minutes = _elapsed_minutes(last_interest_at, now)
    return balance + int(balance * BANK_INTEREST_RATE * minutes)


def accrued_loan(principal: int, interest: int, last_interest_at: float, now: float) -> tuple[int, int]:
    """대출(원금, 이자)에 이자를 더한 정산값. (쓰기 없음)"""
    minutes = _elapsed_minutes(last_interest_at, now)
    debt = principal + interest
    return principal, interest + int(debt * LOAN_INTEREST_RATE * minutes)


def bank_settle(db: Session, uid: int, now: float | None = None) -> tuple[int, int, int]:
    """예치/대출 이자 정산. (예치금, 원금, 이자) 반환."""
    now = now or time.time()
    acc = db.get(BankAccount, uid)
    if acc is None:
        acc = BankAccount(user_id=uid, balance=0, last_interest_at=now)
        db.add(acc)
    new_balance = accrued_deposit(acc.balance, acc.last_interest_at, now)
    acc.balance = new_balance
    acc.last_interest_at = now

    loan = db.get(BankLoan, uid)
    if loan is None:
        db.flush()
        return new_balance, 0, 0
    principal, interest = accrued_loan(loan.principal, loan.interest, loan.last_interest_at, now)
    loan.interest = interest
    loan.last_interest_at = now
    db.flush()
    return new_balance, principal, interest


def loan_limit(deposit: int, debt: int) -> int:
    """대출 가능 한도 = 기본 5만 + 예치금×2, 최대 100만, 기존 부채 차감."""
    return max(0, min(LOAN_BASE + deposit * LOAN_DEPOSIT_FACTOR, MAX_LOAN) - debt)


# ---------------------------------------------------------------------------
# 직업
# ---------------------------------------------------------------------------

def get_user_job(db: Session, uid: int):
    return db.get(UserJob, uid)


def select_job(db: Session, uid: int, job_id: str) -> bool:
    if job_id not in {j[0] for j in JOBS}:
        return False
    row = db.get(UserJob, uid)
    if row is None:
        db.add(UserJob(user_id=uid, job_id=job_id, level=1, work_count=0))
    else:
        row.job_id = job_id
    db.flush()
    return True


def work_job(db: Session, uid: int) -> tuple:
    """출근. (salary, leveled_up, next_level, level) 반환. 쿨다운은 호출부에서."""
    row = db.get(UserJob, uid)
    if row is None:
        return None, False, 0, 0
    job = next((j for j in JOBS if j[0] == row.job_id), None)
    if job is None:
        return None, False, 0, 0
    _, _, _, base_salary, req_count, level_bonus = job

    salary = base_salary + (row.level - 1) * level_bonus
    row.work_count += 1
    leveled_up = False
    if row.work_count >= req_count * row.level:
        row.level += 1
        row.work_count = 0
        leveled_up = True
        salary = base_salary + (row.level - 1) * level_bonus
    row.last_work_at = time.time()
    db.flush()

    change_money(db, uid, salary)
    next_level = req_count * row.level - row.work_count
    return salary, leveled_up, next_level, row.level


# ---------------------------------------------------------------------------
# 일일 퀘스트
# ---------------------------------------------------------------------------

def today_str() -> str:
    return time.strftime("%Y-%m-%d")


def update_quest_progress(db: Session, uid: int, quest_id: str, amount: int = 1):
    """퀘스트 진행도 증가. 임계값 도달 시 완료 처리."""
    if quest_id not in QUEST_THRESHOLDS:
        return
    date = today_str()
    row = db.get(QuestProgress, (uid, quest_id, date))
    if row is None:
        row = QuestProgress(user_id=uid, quest_id=quest_id, date=date,
                            completed=0, progress=0, claimed=0)
        db.add(row)
    if row.completed:
        db.flush()
        return
    row.progress += amount
    if row.progress >= QUEST_THRESHOLDS[quest_id]:
        row.completed = 1
    db.flush()


def claim_quest_reward(db: Session, uid: int, quest_id: str) -> tuple[bool, int]:
    """보상 수령. (성공, 보상금) — 미완료/이미수령 시 (False, 0)."""
    date = today_str()
    row = db.get(QuestProgress, (uid, quest_id, date))
    if row is None or not row.completed or row.claimed:
        return False, 0
    reward = next((q[3] for q in DAILY_QUESTS if q[0] == quest_id), 0)
    row.claimed = 1
    change_money(db, uid, reward)
    db.flush()
    return True, reward


# ---------------------------------------------------------------------------
# 쿨다운 (UserStat에 epoch초 저장)
# ---------------------------------------------------------------------------

def cd_remaining(db: Session, uid: int, key: str, duration: float) -> float:
    """남은 쿨다운(초). 준비됐으면 0."""
    from .models import UserStat
    row = db.get(UserStat, (uid, key))
    if row is None:
        return 0
    left = row.value + duration - time.time()
    return max(0.0, left)


def cd_set(db: Session, uid: int, key: str):
    from .models import UserStat
    row = db.get(UserStat, (uid, key))
    if row is None:
        db.add(UserStat(user_id=uid, stat=key, value=int(time.time())))
    else:
        row.value = int(time.time())
    db.flush()
