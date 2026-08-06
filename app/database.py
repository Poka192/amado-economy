"""SQLAlchemy 엔진/세션. SQLite(개발)와 Postgres(배포) 모두 지원."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL, IS_SQLITE

engine_kwargs = {"pool_pre_ping": True}
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # 관리형 Postgres(예: Supabase) 무료티어는 동시 연결 수가 제한된다.
    # 연결 풀을 작게 유지하고, 대기/문장 타임아웃을 걸어 요청이 무한 대기하지 않게 한다.
    # 참고: 핸들러는 전부 `async def` + 동기 SQLAlchemy라 이벤트 루프에서 직렬 실행된다
    # → 요청 1 + 백그라운드(로또) 1 커넥션이면 충분. `sync def`로 바꾸면 FastAPI
    #   스레드풀(40)이 2-커넥션 풀을 순식간에 소진하므로 바꾸지 말 것.
    engine_kwargs.update({
        "pool_size": 2,
        "max_overflow": 0,
        "pool_timeout": 5,
        "pool_recycle": 300,
        "connect_args": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=15000",
        },
    })

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
