"""환경 설정. .env 또는 환경변수로 DB URL/비밀키 주입. (SQLite 로컬 / Postgres 배포)"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # postgres:// 프로토콜 호환 (Render/Supabase 등)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # Supabase/관리형 Postgres는 SSL 필수 — 누락 시 자동 추가
    if url.startswith("postgresql://") and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}sslmode=require"
    return url or f"sqlite:///{BASE_DIR / 'app.db'}"


# 세션/비밀번호 해시용 비밀 키 (배포 시 .env로 반드시 교체)
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DATABASE_URL = _db_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# 이자/틱 상수 (봇과 동일)
BANK_INTEREST_RATE = 0.0002        # 예치 이자 0.02%/분
LOAN_INTEREST_RATE = 0.0005        # 대출 이자 0.05%/분
MAX_ACCRUE_MINUTES = 1440          # 이자 정산 상한 (24시간)
LOAN_MIN = 10_000
LOAN_BASE = 50_000
LOAN_DEPOSIT_FACTOR = 2
MAX_LOAN = 1_000_000
