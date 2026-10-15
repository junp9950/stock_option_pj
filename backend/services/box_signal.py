"""박스 돌파 매수 (2026-10-15 사용자 "매수 신호로 넣어라").

조건 = 차트 후보 '박스 돌파'(screener/my_pattern box_break) 그대로: 돈 들어온 섹터 종목 · 직전 20일 종가 폭 20%↓ · 직전 20일 고가 위 ·
  그날 +5%↑ +29% 미만 · 거래대금 평소 2배↑ · 200일선 위 · 윗꼬리 30%↓ · 거래대금 30억↑. 여기에 시장 상승·횡보장 · 손절폭 25%↓.
장중 = my_pattern.dip_live(토스 실시간 · 섹터 등락) · 장 마감 뒤 = my_pattern.scan(그날 확정).
손절 = 박스 하단(직전 20거래일 최저 종가) −1% · 매도 = 20거래일째 종가 (stop_orders mode 'box').
검증(tmp_claude/cand_replay · boxbrk_test.py, 2025-04~2026-09 재생 241건): 박스 하단 손절·20일 보유 평균 +8.8% · 이김 59% (25년 +8.5 · 26년 +9.2)
  — 손절폭이 커서(평균 19%) 수량은 작고, 계좌에 더해도 수익 변화는 거의 없음(+287%→+287%). 섹터 자료가 지금 것이라 12년 검증은 못 함 · 가격만으로는 이번 장에서만 통함.
기록: settings 'box_signal_log' {날짜: {종목: {name, close, stop, risk, exit, live}}} (최근 60일) · 'box_hist' {날짜: [종목]} (차트 표시용, 2025-04-09~ 재생 포함).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
LOG = "box_signal_log"
HIST = "box_hist"
HOLD = 20
MAX_RISK = 0.25
KIND = "박스 돌파 · 20일 보유"


def _nth_after(d: date, n: int) -> date:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    k = 0
    while k < n:
        d += timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return d


def _box_stops(db: Session, codes: list[str], before: date) -> dict[str, float]:
    """박스 하단 −1% = 그날 전 20거래일 최저 종가 × 0.99 (호가 내림)."""
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    if not codes:
        return {}
    rows = db.execute(text("""select stock_code, min(close_price) from (
        select stock_code, close_price, row_number() over (partition by stock_code order by trading_date desc) rn
        from spot_daily_prices where stock_code = any(:c) and trading_date < :d) x where rn <= 20 group by stock_code"""),
                      {"c": codes, "d": before}).all()
    return {c: float(tick_floor(float(m) * 0.99)) for c, m in rows if m}


def _live_window(db: Session) -> bool:
    from backend.services.stock_signals import _data_latest  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    now = datetime.now(KST)
    return is_trading_day(now.date()) and 9 <= now.hour < 16 and _data_latest(db) < now.date()


def today(db: Session) -> dict:
    """{'date', 'live', 'items': [{code, name, close, stop, risk, exit, family}]} — 장중이면 실시간, 아니면 마지막 장 확정."""
    from backend.services.stock_signals import _bull_days, _data_latest  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    from backend.screener import my_pattern as MP  # noqa: PLC0415
    latest = _data_latest(db)
    live = _live_window(db)
    if live:
        src = (MP.dip_live(db) or {}).get("box_break", []) or []
        d = datetime.now(KST).date()
    else:
        r = cached("my_pattern_v6", (), db, lambda: MP.scan(db)) or {}
        src = r.get("box_break", []) or []
        d = latest
    bull = bool(_bull_days(db).get(latest, False))
    out = {"date": str(d), "live": live, "bull": bull, "items": []}
    if not src:
        return out
    stops = _box_stops(db, [x["code"] for x in src], d)
    ex = str(_nth_after(d, HOLD))
    for x in src:
        st, cl = stops.get(x["code"]), float(x.get("close") or 0)
        if not st or not cl or st >= cl:
            continue
        rk = 1 - st / cl
        if rk > MAX_RISK:
            continue
        out["items"].append({"code": x["code"], "name": x.get("name", x["code"]), "close": cl, "stop": st, "risk": round(rk, 4),
                             "exit": ex, "family": x.get("family", ""), "change_pct": x.get("change_pct")})
    if not bull:
        out["skipped_bear"] = len(out["items"]); out["items"] = []
    try:
        _record(db, out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("박스 돌파 기록 실패: %s", exc)
    return out


def _record(db: Session, v: dict) -> None:
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    if not v["items"]:
        return
    log = _get(db, LOG, {}) or {}
    day = log.setdefault(v["date"], {})
    for x in v["items"]:
        if v["live"] and x["code"] in day and not day[x["code"]].get("live"):
            continue      # 확정 기록은 장중 값으로 덮지 않음
        day[x["code"]] = {"name": x["name"], "close": x["close"], "stop": x["stop"], "risk": x["risk"], "exit": x["exit"], "live": v["live"]}
    for k in sorted(log)[:-60]:
        log.pop(k, None)
    _put(db, LOG, log)
    if not v["live"]:
        h = _get(db, HIST, {}) or {}
        h[v["date"]] = sorted({*(h.get(v["date"]) or []), *(x["code"] for x in v["items"])})
        _put(db, HIST, h)


def lot_info(db: Session, code: str, buy: date) -> dict | None:
    """산 날(또는 2거래일 안 앞) 박스 돌파 신호였던 종목이면 {stop, exit}."""
    from backend.services.telegram import _get  # noqa: PLC0415
    log = _get(db, LOG, {}) or {}
    for d in sorted(log, reverse=True):
        if d > str(buy):
            continue
        if str(_nth_after(date.fromisoformat(d), 2)) < str(buy):
            break
        x = (log.get(d) or {}).get(code)
        if x:
            return {"stop": x["stop"], "exit": str(_nth_after(date.fromisoformat(d), HOLD)), "date": d}
    return None


def hist_days(db: Session, code: str) -> set[str]:
    from backend.services.telegram import _get  # noqa: PLC0415
    return {d for d, cs in (_get(db, HIST, {}) or {}).items() if code in cs}


def daily_job(db: Session) -> str:
    """장 마감 뒤(16:30 · 18:25) 확정 목록을 기록."""
    if _live_window(db):
        return "장중"
    v = today(db)
    return f"{v['date']} 박스 돌파 {len(v['items'])}개" + ("" if v["bull"] else f" (하락장이라 매수 안 함 · {v.get('skipped_bear', 0)}개)")
