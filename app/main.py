"""FastAPI 엔트리 — 앱 생성, 템플릿/정적 파일, 로또 백그라운드."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import lotto_logic
from .database import Base, SessionLocal, engine, get_db
from .deps import AdminRequired, LoginRequired
from .defs import LOTTO_DRAW_INTERVAL

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STATIC_DIR = BASE_DIR / "static"


def fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def money(n) -> str:
    return f"{fmt(n)}원"


templates.env.filters["fmt"] = fmt
templates.env.filters["money"] = money
templates.env.globals["money"] = money


async def _lotto_loop():
    while True:
        await asyncio.sleep(LOTTO_DRAW_INTERVAL)
        try:
            db = SessionLocal()
            try:
                lotto_logic.draw(db)
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[로또] 태스크 오류: {exc!r}")


async def _lotto_catchup():
    """기동 시 지난 추첨 소급 처리 (단 한 번)."""
    db = SessionLocal()
    try:
        state = lotto_logic.get_state(db)
        now = time.time()
        if state["last_draw_time"] > 0 and now - state["last_draw_time"] >= LOTTO_DRAW_INTERVAL:
            lotto_logic.draw(db)
        else:
            # 최초 실행 시 첫 당첨금 표시용 상태만 보장
            pass
        db.commit()
    finally:
        db.close()


def _migrate_and_promote_admin(db: Session):
    """users.is_admin 컬럼 마이그레이션 + 'admin' 계정 자동 승격.

    create_all은 기존 테이블에 열을 추가하지 못하므로,
    운영 DB(Supabase/Postgres) 재배포 시 ALTER로 컬럼을 보장한다.
    """
    from sqlalchemy import inspect, select, text
    from .models import User

    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_admin" not in cols:
            db.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
            db.commit()
    admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
    if admin is not None and not admin.is_admin:
        admin.is_admin = True
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from . import casino_logic
    from . import forex_logic
    from . import stocks_logic
    from . import realestate_logic as re_logic

    db = SessionLocal()
    try:
        _migrate_and_promote_admin(db)
        casino_logic.ensure_house(db)
        stocks_logic.ensure_seed(db)
        re_logic.ensure_market(db)
        forex_logic.ensure_seed(db)
        db.commit()
    finally:
        db.close()
    task = asyncio.create_task(_lotto_loop())
    try:
        await _lotto_catchup()
    except Exception as exc:  # noqa: BLE001
        print(f"[로또] 케치업 오류: {exc!r}")
    yield
    task.cancel()


app = FastAPI(title="아마도 경제", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# GET 페이지 5초 캐시 — 원격 DB(교차대륙) 지연을 피해 반복 방문 시 즉시 응답.
# 라우트 DB 작업까지 건너뛰기 위해 응답 레벨에서 캐시한다.
_page_cache: dict[tuple, tuple[float, bytes]] = {}
_PAGE_CACHE_TTL = 5.0
_PAGE_CACHE_MAX = 512


def _cache_uid(request: Request) -> int:
    from .deps import SESSION_COOKIE
    from .security import read_session_token
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return 0
    try:
        return read_session_token(token) or 0
    except Exception:
        return 0


# 페이지 캐시에서 제외할 경로 — /static(정적), /ping(헬스체크), /admin(실시간 관리자 페이지)
_NON_CACHE_PATHS = ("/static", "/ping", "/admin")


def _is_cacheable_path(path: str) -> bool:
    return not path.startswith(_NON_CACHE_PATHS)


@app.middleware("http")
async def _page_cache_middleware(request: Request, call_next):
    if request.method == "POST":
        # 액션 후엔 해당 유저의 캐시 무효화 (최신 데이터 반영)
        uid = _cache_uid(request)
        if uid and _page_cache:
            for key in [k for k in _page_cache if k[1] == uid]:
                del _page_cache[key]
        # 랭킹 스냅샷은 모든 유저가 공유 → POST 시 무효화 (순위 최신 반영)
        from .routers.ranking import invalidate_ranking_cache
        invalidate_ranking_cache()
        return await call_next(request)

    if request.method == "GET" and _is_cacheable_path(request.url.path):
        uid = _cache_uid(request)
        key = (request.url.path, uid,
               request.query_params.get("msg", ""),
               request.query_params.get("err", ""))
        now = time.time()
        hit = _page_cache.get(key)
        if hit and now - hit[0] < _PAGE_CACHE_TTL:
            return Response(content=hit[1], media_type="text/html")

    response = await call_next(request)

    if request.method == "GET" and response.status_code == 200 \
            and _is_cacheable_path(request.url.path):
        body = b"".join([chunk async for chunk in response.body_iterator])
        uid = _cache_uid(request)
        key = (request.url.path, uid,
               request.query_params.get("msg", ""),
               request.query_params.get("err", ""))
        if len(_page_cache) >= _PAGE_CACHE_MAX:
            _page_cache.clear()
        _page_cache[key] = (time.time(), body)
        new_resp = Response(content=body, media_type="text/html")
        for name, val in response.headers.items():
            if name.lower() not in ("content-length", "content-type", "content-encoding"):
                new_resp.headers[name] = val
        # 동적 페이지는 브라우저 휴리스틱 캐시 방지 (서버 5초 캐시는 위에서 처리)
        new_resp.headers["Cache-Control"] = "no-store"
        return new_resp

    if request.method == "GET" and request.url.path.startswith("/static") \
            and response.status_code == 200:
        # 정적 자산은 브라우저 캐시 (5분) — 내비게이션마다 재요청 방지
        response.headers.setdefault("Cache-Control", "public, max-age=300")

    return response


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(AdminRequired)
async def _admin_required(request: Request, exc: AdminRequired):
    return RedirectResponse("/dashboard?err=관리자 권한이 필요합니다.", status_code=303)


def render(request: Request, name: str, **ctx):
    """템플릿 렌더 공통 (로그인 유저는 호출부에서 전달 + 메시지 주입)."""
    ctx["request"] = request
    ctx.setdefault("user", None)
    msg = request.query_params.get("msg", "")
    err = request.query_params.get("err", "")
    ctx["flash_msg"], ctx["flash_err"] = msg, err
    return templates.TemplateResponse(request, name, ctx)


def redirect(path: str, msg: str = "", err: str = ""):
    if msg:
        return RedirectResponse(f"{path}?msg={msg}", status_code=303)
    if err:
        return RedirectResponse(f"{path}?err={err}", status_code=303)
    return RedirectResponse(path, status_code=303)


# 라우터 등록
from .routers import admin as admin_router  # noqa: E402
from .routers import auth as auth_router  # noqa: E402
from .routers import casino as casino_router  # noqa: E402
from .routers import economy as economy_router  # noqa: E402
from .routers import forex as forex_router  # noqa: E402
from .routers import lotto as lotto_router  # noqa: E402
from .routers import ranking as ranking_router  # noqa: E402
from .routers import realestate as realestate_router  # noqa: E402
from .routers import shop as shop_router  # noqa: E402
from .routers import stocks as stocks_router  # noqa: E402

app.include_router(admin_router.router)
app.include_router(auth_router.router)
app.include_router(economy_router.router)
app.include_router(shop_router.router)
app.include_router(casino_router.router)
app.include_router(lotto_router.router)
app.include_router(stocks_router.router)
app.include_router(realestate_router.router)
app.include_router(forex_router.router)
app.include_router(ranking_router.router)


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    from .deps import optional_user
    user = optional_user(request, db)
    if user is None:
        return render(request, "index.html")
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/ping")
async def ping():
    """헬스체크/keep-alive — DB·템플릿 없이 즉시 응답 (Render 절전 방지용)."""
    return Response(content="ok", media_type="text/plain")
