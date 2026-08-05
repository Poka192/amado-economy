"""SQLAlchemy ORM 모델 — 디스코드 봇의 경제 스키마를 웹으로 이식."""
import time

from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# 계정 / 화폐
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[float] = mapped_column(Float, default=_now)


class SystemState(Base):
    """전역 상태 KV (주식/부동산 마지막 틱 시각 등)."""
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float, default=0)


class Money(Base):
    __tablename__ = "money"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=5000)


# ---------------------------------------------------------------------------
# 은행
# ---------------------------------------------------------------------------

class BankAccount(Base):
    __tablename__ = "bank_accounts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    last_interest_at: Mapped[float] = mapped_column(Float, default=_now)


class BankLoan(Base):
    __tablename__ = "bank_loans"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    principal: Mapped[int] = mapped_column(Integer, default=0)
    interest: Mapped[int] = mapped_column(Integer, default=0)
    last_interest_at: Mapped[float] = mapped_column(Float, default=_now)


# ---------------------------------------------------------------------------
# 아이템 / 상점
# ---------------------------------------------------------------------------

class InventoryItem(Base):
    __tablename__ = "user_inventory"
    __table_args__ = (UniqueConstraint("user_id", "item_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class HighRoller(Base):
    __tablename__ = "high_roller"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[int] = mapped_column(Integer, default=0)


class HopePending(Base):
    __tablename__ = "hope_pending"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# 직업 / 퀘스트 / 업적 / 통계
# ---------------------------------------------------------------------------

class UserJob(Base):
    __tablename__ = "user_jobs"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer, default=1)
    work_count: Mapped[int] = mapped_column(Integer, default=0)
    last_work_at: Mapped[float] = mapped_column(Float, default=0)


class QuestProgress(Base):
    __tablename__ = "daily_quest_progress"
    __table_args__ = (UniqueConstraint("user_id", "quest_id", "date"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    quest_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    claimed: Mapped[int] = mapped_column(Integer, default=0)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    achievement_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    earned_at: Mapped[float] = mapped_column(Float, default=_now)


class UserStat(Base):
    __tablename__ = "user_stats"
    __table_args__ = (UniqueConstraint("user_id", "stat"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    stat: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# 로또
# ---------------------------------------------------------------------------

class LottoTicket(Base):
    __tablename__ = "lotto_tickets"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer)
    bought_at: Mapped[float] = mapped_column(Float, default=_now)


class LottoState(Base):
    __tablename__ = "lotto_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_drawn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_draw_time: Mapped[float] = mapped_column(Float, default=0)
    jackpot: Mapped[int] = mapped_column(Integer, default=0)
    draw_count: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# 주식
# ---------------------------------------------------------------------------

class StockPrice(Base):
    __tablename__ = "stock_prices"

    ticker: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(Integer)
    open_price: Mapped[int] = mapped_column(Integer, default=0)


class StockHolding(Base):
    __tablename__ = "stock_holdings"
    __table_args__ = (UniqueConstraint("user_id", "ticker"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ticker: Mapped[str] = mapped_column(String(8), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[int] = mapped_column(Integer, default=0)


class StockOrder(Base):
    __tablename__ = "stock_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(4))  # buy / sell
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open / filled / canceled
    created_at: Mapped[float] = mapped_column(Float, default=_now)


class StockHistory(Base):
    __tablename__ = "stock_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(8), index=True)
    price: Mapped[int] = mapped_column(Integer)
    ts: Mapped[float] = mapped_column(Float, default=_now, index=True)


class StockNews(Base):
    __tablename__ = "stock_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=_now)


class StockDividend(Base):
    __tablename__ = "stock_dividends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float, default=_now)


# ---------------------------------------------------------------------------
# 부동산
# ---------------------------------------------------------------------------

class Property(Base):
    __tablename__ = "re_properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type_id: Mapped[str] = mapped_column(String(16))
    level: Mapped[int] = mapped_column(Integer, default=1)
    bought_at: Mapped[float] = mapped_column(Float, default=_now)
    last_accrual_at: Mapped[float] = mapped_column(Float, default=_now)
    reno_count: Mapped[int] = mapped_column(Integer, default=0)
    staff_man: Mapped[int] = mapped_column(Integer, default=0)
    staff_guard: Mapped[int] = mapped_column(Integer, default=0)
    staff_promo: Mapped[int] = mapped_column(Integer, default=0)
    sell_price: Mapped[int] = mapped_column(Integer, default=0)


class PropertyMarket(Base):
    __tablename__ = "re_market"

    type_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    price: Mapped[int] = mapped_column(Integer)


class PropertyState(Base):
    __tablename__ = "re_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_tick_time: Mapped[float] = mapped_column(Float, default=_now)


class PropertyListing(Base):
    __tablename__ = "re_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type_id: Mapped[str] = mapped_column(String(16))
    level: Mapped[int] = mapped_column(Integer, default=1)
    staff_man: Mapped[int] = mapped_column(Integer, default=0)
    staff_guard: Mapped[int] = mapped_column(Integer, default=0)
    staff_promo: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[int] = mapped_column(Integer)
    listed_at: Mapped[float] = mapped_column(Float, default=_now)
