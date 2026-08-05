"""FastAPI 엔트리 — 앱 생성, 템플릿/정적 파일, 로또 백그라운드."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import lotto_logic
from .database import Base, SessionLocal, engine, get_db
from .deps import LoginRequired
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from . import stocks_logic
    from . import realestate_logic as re_logic

    db = SessionLocal()
    try:
        stocks_logic.ensure_seed(db)
        re_logic.ensure_market(db)
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


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


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
from .routers import auth as auth_router  # noqa: E402
from .routers import casino as casino_router  # noqa: E402
from .routers import economy as economy_router  # noqa: E402
from .routers import lotto as lotto_router  # noqa: E402
from .routers import ranking as ranking_router  # noqa: E402
from .routers import realestate as realestate_router  # noqa: E402
from .routers import shop as shop_router  # noqa: E402
from .routers import stocks as stocks_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(economy_router.router)
app.include_router(shop_router.router)
app.include_router(casino_router.router)
app.include_router(lotto_router.router)
app.include_router(stocks_router.router)
app.include_router(realestate_router.router)
app.include_router(ranking_router.router)


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    from .deps import optional_user
    user = optional_user(request, db)
    if user is None:
        return render(request, "index.html")
    return RedirectResponse("/dashboard", status_code=303)
