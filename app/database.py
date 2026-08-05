"""SQLAlchemy 엔진/세션. SQLite(개발)와 Postgres(배포) 모두 지원."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL, IS_SQLITE

engine_kwargs = {"pool_pre_ping": True}
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 의존성: 요청별 세션."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
