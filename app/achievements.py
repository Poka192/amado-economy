"""업적/통계 헬퍼."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .defs import ACHIEVEMENTS
from .models import UserAchievement, UserStat

_ALL_ACHIEVEMENT_KEYS = set(ACHIEVEMENTS.keys())


def grant(db: Session, uid: int, achievement_id: str) -> bool:
    """업적 부여. 새로 부여 시 True."""
    if achievement_id not in _ALL_ACHIEVEMENT_KEYS:
        return False
    if db.get(UserAchievement, (uid, achievement_id)) is not None:
        return False
    db.add(UserAchievement(user_id=uid, achievement_id=achievement_id))
    db.flush()
    return True


def earned(db: Session, uid: int) -> set[str]:
    rows = db.execute(
        select(UserAchievement.achievement_id).where(UserAchievement.user_id == uid)
    ).scalars().all()
    return set(rows)


def stat(db: Session, uid: int, key: str) -> int:
    row = db.get(UserStat, (uid, key))
    return row.value if row else 0


def increment_stat(db: Session, uid: int, key: str, amount: int = 1) -> int:
    row = db.get(UserStat, (uid, key))
    if row is None:
        row = UserStat(user_id=uid, stat=key, value=amount)
        db.add(row)
    else:
        row.value += amount
    db.flush()
    return row.value
