from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # .env 파일 자동 로드 (DATABASE_URL 등)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.api.routes import router
from backend.config import get_config
from backend.db.database import Base, SessionLocal, engine
from backend.db.seed import seed_reference_data
from backend.scheduler import start_scheduler
from backend.services.daily_pipeline import run_daily_pipeline


config = get_config()
app = FastAPI(title=config.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 새 주소 (2026-10-13 사용자: 클라우드플레어 Pages 무료 주소). Pages가 요청을 이 서버로 넘길 때 X-Stockradar-Via 헤더를 붙인다.
# 옛 주소(sslip.io)로 직접 들어온 '화면' 요청과 처음 만든 stockradar-pages 주소는 새 주소로 넘긴다.
# /api 는 넘기지 않음 (열려 있는 화면·텔레그램·내 점검 명령이 끊기지 않게). 302(임시)로 — 주소를 또 바꿀 수 있어서.
NEW_SITE = "https://bat-rader.pages.dev"


@app.middleware("http")
async def _to_new_site(request, call_next):
    via = request.headers.get("x-stockradar-via", "")
    if request.method == "GET" and not request.url.path.startswith("/api") and via != "bat-rader.pages.dev":
        host = (request.headers.get("host") or "").split(":")[0]
        if via or host.endswith("sslip.io") or host == "20.196.212.146":   # 옛 주소(IP:8000)로 오는 사람도 새 주소로
            from starlette.responses import RedirectResponse  # noqa: PLC0415
            q = ("?" + request.url.query) if request.url.query else ""
            return RedirectResponse(NEW_SITE + request.url.path + q, status_code=302)
    return await call_next(request)   # 폰에서 느림 (2026-10-07) — 첫 화면 150KB·차트 24KB를 압축해서 보냄
app.include_router(router, prefix=config.api_prefix)


@app.get('/quant', response_class=HTMLResponse, include_in_schema=False)
def quant_dashboard() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'quant.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/earnings', response_class=HTMLResponse, include_in_schema=False)
def earnings_dashboard() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'earnings.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/suggestions', response_class=HTMLResponse, include_in_schema=False)
def suggestions_page() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'suggestions.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/discussion', response_class=HTMLResponse, include_in_schema=False)
def discussion_page() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'discussion.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def status_dashboard() -> str:
    """첫 화면 — 화면 코드(HTML·CSS·JS)는 backend/views/app.html (2026-10-11 main.py에서 떼어 냄: 파이썬 문자열 이스케이프 실수 줄이기)."""
    from pathlib import Path
    return (Path(__file__).parent / 'views' / 'app.html').read_text(encoding='utf-8')


@app.on_event("startup")
def startup_event() -> None:
    import threading
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text  # noqa: PLC0415
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE stocks ADD COLUMN IF NOT EXISTS shares_outstanding FLOAT DEFAULT 0.0"))
        conn.execute(text("ALTER TABLE radar_picks ADD COLUMN IF NOT EXISTS market_cap FLOAT DEFAULT 0.0"))
        conn.execute(text("ALTER TABLE discussion_comments ADD COLUMN IF NOT EXISTS image_data TEXT"))
        conn.execute(text("ALTER TABLE discussion_comments ADD COLUMN IF NOT EXISTS parent_id INTEGER"))
        conn.execute(text("ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS title VARCHAR(100)"))
        conn.execute(text("ALTER TABLE suggestions ADD COLUMN IF NOT EXISTS image_data TEXT"))
        conn.execute(text("ALTER TABLE jongbe_picks ADD COLUMN IF NOT EXISTS ai_pick BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS pool VARCHAR(4) DEFAULT ''"))
    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    def _bg() -> None:
        from backend.utils.dates import is_trading_day  # noqa: PLC0415
        from datetime import date as _date  # noqa: PLC0415
        today = _date.today()
        from datetime import datetime as _dtm  # noqa: PLC0415
        from zoneinfo import ZoneInfo as _ZI  # noqa: PLC0415
        _now = _dtm.now(_ZI("Asia/Seoul"))
        if is_trading_day(today) and (_now.hour, _now.minute) < (15, 41):
            # 장중 재시작(배포)이면 수집하지 않는다 — 장중 시세가 오늘 종가 행으로 들어가 15:41 수집을 막았다 (2026-10-06)
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("장중 재시작 — startup 파이프라인 스킵 (15:41 정규 수집에 맡김)")
            return
        if not is_trading_day(today):
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("오늘(%s)은 거래일이 아니므로 startup 파이프라인 스킵", today)
            return
        from sqlalchemy import text as _t  # noqa: PLC0415
        _db0 = SessionLocal()
        try:      # 오늘 수집이 이미 끝났으면(장 마감 뒤 배포) 다시 돌리지 않는다 — 재시작마다 3분 넘게 무거웠다 (2026-10-06)
            done = _db0.execute(_t("select count(*) from spot_investor_flows where trading_date = :d and "
                                   "(foreign_net_buy <> 0 or institution_net_buy <> 0)"), {"d": today}).scalar() or 0
        finally:
            _db0.close()
        if done:
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("오늘 수집 이미 끝남 — startup 파이프라인 스킵")
            return
        _db = SessionLocal()
        try:
            run_daily_pipeline(_db)
        finally:
            _db.close()
    def _warm_journal() -> None:
        _db = SessionLocal()
        try:
            from backend.services import trade_journal  # noqa: PLC0415
            trade_journal.warm(_db)          # 매매 일지 먼저 (12초) — 뒤에 두니 재시작 뒤 한참 '여는 중'이었다 (2026-10-14)
            from backend.api.routes import warm_caches  # noqa: PLC0415
            warm_caches(_db)                 # 첫 화면(오늘)·차트 후보를 재시작 직후 바로 데움
        except Exception as exc:  # noqa: BLE001
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).warning("매매 일지 미리 계산 실패: %s", exc)
        finally:
            _db.close()
    import os  # noqa: PLC0415
    if os.environ.get("NO_SCHEDULER"):        # 화면 시험용 서버(:8011 등) — 수집·예약 작업(텔레그램 확인·알림)을 돌리지 않는다 (2026-10-10)
        return
    threading.Thread(target=_warm_journal, daemon=True).start()
    threading.Thread(target=_bg, daemon=True).start()
    start_scheduler()
