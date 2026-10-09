"""60분봉 쌓아 두기 (화면에는 안 씀) — 몇 달 모이면 4시간봉 신호를 검증하려고 (2026-10-09 사용자 "어디 보이진 말고 저장해 놔라").

네이버 차트 API는 분봉을 최근 약 6거래일만 주므로, 매일 장 마감 뒤(넥스트레이드 20시까지 끝난 뒤) 받아서 없는 봉만 더한다.
대상: 하루 거래대금 20일 평균 30억↑ (약 800종목). 시간은 한국 시간 그대로 저장(봉 시작 시각).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.utils.logger import get_logger

logger = get_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")
DDL = """create table if not exists intraday_bars (
  stock_code varchar(12) not null, interval varchar(4) not null, bar_time timestamp not null,
  open_price double precision, high_price double precision, low_price double precision, close_price double precision, volume bigint,
  primary key (stock_code, interval, bar_time))"""


def store_hourly(db: Session, interval: str = "60m") -> dict:
    db.execute(text(DDL))
    db.commit()
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    codes = [r[0] for r in db.execute(text(
        "select stock_code from spot_daily_prices where trading_date > cast(:d as date) - 30 group by 1 having avg(trading_value) >= 3e9"),
        {"d": latest}).all()]
    path = {"60m": "minute60", "30m": "minute30"}[interval]
    now = datetime.now(_KST)
    st, en = (now - timedelta(days=14)).strftime("%Y%m%d0800"), now.strftime("%Y%m%d%H%M")
    added = fail = 0
    for i, c in enumerate(codes):
        try:
            rows = requests.get(f"https://api.stock.naver.com/chart/domestic/item/{c}/{path}?startDateTime={st}&endDateTime={en}",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json() or []
        except Exception:  # noqa: BLE001
            fail += 1
            time.sleep(1.0)
            continue
        vals = [{"c": c, "i": interval, "t": datetime.strptime(r["localDateTime"], "%Y%m%d%H%M%S"), "o": r.get("openPrice"), "h": r.get("highPrice"),
                 "l": r.get("lowPrice"), "cl": r.get("currentPrice"), "v": int(r.get("accumulatedTradingVolume") or 0)} for r in rows if r.get("localDateTime")]
        if vals:
            res = db.execute(text("insert into intraday_bars values (:c, :i, :t, :o, :h, :l, :cl, :v) on conflict do nothing"), vals)
            added += res.rowcount or 0
        if i % 50 == 49:
            db.commit()
        time.sleep(0.12)
    db.commit()
    logger.info("60분봉 저장: %d종목 · 새 봉 %d · 실패 %d", len(codes), added, fail)
    return {"codes": len(codes), "added": added, "fail": fail}
