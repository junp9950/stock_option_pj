"""매수 신호·보유 종목 '주의 꼬리표' (2026-10-11 사용자 "실적 D-2처럼 붙이기 좋네").
- 실적 D-n: market_events 의 한국 실적 일정(DART IR 안내·시총 800위) 중 오늘~5거래일 안
- ⚠ 위험 공시: 최근 30일 DART 전체 공시 중 증자·CB·감자·최대주주변경·소송 등 (종목별 첫 건)
규칙은 안 바꾸고 보이는 정보만. 30분 캐시."""
from __future__ import annotations

import os
import re
import time
from datetime import date, timedelta

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.utils.logger import get_logger

logger = get_logger(__name__)
_C: dict = {}
RISK_SHORT = [("유상증자", "유증"), ("전환사채", "CB"), ("신주인수권부사채", "BW"), ("교환사채", "EB"), ("감자", "감자"), ("최대주주변경", "최대주주 변경"),
              ("최대주주 변경", "최대주주 변경"), ("소송", "소송"), ("횡령", "횡령"), ("배임", "배임"), ("불성실공시", "불성실공시"), ("관리종목", "관리종목"),
              ("상장폐지", "상장폐지"), ("거래정지", "거래정지"), ("매매거래정지", "거래정지"), ("회생", "회생"), ("감사의견", "감사의견"), ("주식관련사채", "사채")]


def _bizdays(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _earnings(db: Session) -> dict[str, dict]:
    today = date.today()
    rows = db.execute(text("select ukey, ev_date, ev_time from market_events where kind = 'earnings' and country = 'KR' and source = 'dart' "
                           "and ev_date between :a and :b order by ev_date"), {"a": today, "b": today + timedelta(days=9)}).all()
    out = {}
    for uk, d, tm in rows:
        code = uk.split(":")[1]
        n = _bizdays(today, d)
        if n <= 5 and code not in out:
            out[code] = {"date": str(d), "dn": n, "time": tm, "label": "실적 오늘" if n == 0 else f"실적 D-{n}"}
    return out


def _risk() -> dict[str, dict]:
    try:
        key = open(os.path.expanduser("~/.dart_key")).read().strip()
    except OSError:
        key = os.getenv("DART_API_KEY", "")
    if not key:
        return {}
    out, end, bgn = {}, date.today(), date.today() - timedelta(days=30)
    for cls in ("Y", "K"):
        for page in range(1, 40):
            try:
                j = requests.get("https://opendart.fss.or.kr/api/list.json", timeout=15, params={
                    "crtfc_key": key, "bgn_de": f"{bgn:%Y%m%d}", "end_de": f"{end:%Y%m%d}", "corp_cls": cls, "page_count": 100, "page_no": page}).json()
            except Exception:  # noqa: BLE001
                break
            if j.get("status") != "000":
                break
            for r in j.get("list") or []:
                code, nm = r.get("stock_code"), re.sub(r"\s+", "", r.get("report_nm") or "")
                if not code or code in out or "종속회사" in nm or "자회사" in nm:
                    continue
                for kw, short in RISK_SHORT:
                    if kw.replace(" ", "") in nm:
                        out[code] = {"label": f"⚠ {short}", "title": re.sub(r"\s+", " ", r.get("report_nm") or "").strip(), "date": r.get("rcept_dt")}
                        break
            if page >= int(j.get("total_page") or 1):
                break
            time.sleep(0.15)
    return out


def notes_quick() -> dict[str, list[dict]]:
    """화면용: 계산해 둔 것만 바로 (없으면 {} + 뒤에서 계산). 처음 계산은 DART 30초쯤이라 목록을 붙잡지 않게."""
    hit = _C.get("n")
    if not hit or time.time() - hit[0] >= 1800:
        import threading  # noqa: PLC0415
        if not _C.get("busy"):
            _C["busy"] = True
            def _run():
                from backend.db.database import SessionLocal  # noqa: PLC0415
                db = SessionLocal()
                try:
                    notes(db, force=True)
                finally:
                    db.close(); _C["busy"] = False
            threading.Thread(target=_run, daemon=True).start()
    return hit[1] if hit else {}


def notes(db: Session, force: bool = False) -> dict[str, list[dict]]:
    """code → [{label, kind('earn'|'risk'), title}] — 둘 다 있으면 위험 먼저."""
    hit = _C.get("n")
    if hit and not force and time.time() - hit[0] < 1800:
        return hit[1]
    out: dict[str, list[dict]] = {}
    try:
        for c, v in _risk().items():
            out.setdefault(c, []).append({"label": v["label"], "kind": "risk", "title": f"{v['date'][4:6]}/{v['date'][6:]} {v['title']}"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("위험 공시 꼬리표 실패: %s", type(exc).__name__)
    try:
        for c, v in _earnings(db).items():
            out.setdefault(c, []).append({"label": v["label"], "kind": "earn", "title": f"{v['date'][5:]} {v['time'] or ''} 실적 발표 (회사 IR 공시)".strip()})
    except Exception as exc:  # noqa: BLE001
        logger.warning("실적 꼬리표 실패: %s", type(exc).__name__)
    _C["n"] = (time.time(), out)
    return out


def tag_text(db: Session, code: str) -> str:
    """텔레그램용 짧은 꼬리표 ' · ⚠ 유증 · 실적 D-2' (없으면 '')."""
    try:
        L = notes(db).get(code) or []
    except Exception:  # noqa: BLE001
        return ""
    return "".join(f" · <b>{x['label']}</b>" for x in L)
