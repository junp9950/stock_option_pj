"""코스피200 선물 외국인·기관·개인 순매수와 미결제약정을 장중 5분마다 쌓는다 (2026-10-13 사용자: 커뮤니티 글 "외인 선물 매도세가 적고
장 마감 1시간 전 외인 선물 매수 + 미결제 증가 = 신규 롱 → 사야 하는 자리" 같은 걸 분석하고 싶다).
- 투자자별 순매수: 네이버 m.stock.naver.com/api/index/FUT/integration dealTrendInfo (오늘 누적, 억원)
- 가격·미결제약정·전일 대비 증감: KIS 국내선물 현재가 FHMIF10000000, 종목 10100000(최근월물 연결)
지난 자료는 무료로 받을 곳이 없어서(KRX는 로그인 필요) 오늘부터 쌓아 몇 달 뒤 검증한다. 표 futures_flow_intraday (시각 = 한국 시간).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _ensure(db: Session) -> None:
    db.execute(text("create table if not exists futures_flow_intraday (ts timestamp primary key, foreign_eok real, inst_eok real, indiv_eok real, "
                    "price real, oi bigint, oi_chg bigint, volume bigint)"))
    db.commit()


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def snapshot(db: Session) -> dict | None:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    now = datetime.now(KST)
    if not is_trading_day(now.date()):
        return None
    _ensure(db)
    row = {"ts": now.replace(second=0, microsecond=0, tzinfo=None)}
    try:
        j = requests.get("https://m.stock.naver.com/api/index/FUT/integration", headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json()
        dt = j.get("dealTrendInfo") or {}
        if dt.get("bizdate") == now.strftime("%Y%m%d"):
            row.update(foreign_eok=_num(dt.get("foreignValue")), inst_eok=_num(dt.get("institutionalValue")), indiv_eok=_num(dt.get("personalValue")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("선물 수급(네이버) 실패: %s", type(exc).__name__)
    try:
        from backend.collector.spot import _get_kis_token  # noqa: PLC0415
        tok = _get_kis_token()
        r = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-futureoption/v1/quotations/inquire-price", timeout=8,
                         headers={"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {tok}", "appkey": os.getenv("KIS_APP_KEY", ""),
                                  "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": "FHMIF10000000", "custtype": "P"},
                         params={"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": "10100000"}).json()
        o = r.get("output1") or {}
        row.update(price=_num(o.get("futs_prpr")), oi=_num(o.get("hts_otst_stpl_qty")), oi_chg=_num(o.get("otst_stpl_qty_icdc")), volume=_num(o.get("acml_vol")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("선물 미결제(KIS) 실패: %s", type(exc).__name__)
    if len(row) <= 1:
        return None
    cols = ["ts", "foreign_eok", "inst_eok", "indiv_eok", "price", "oi", "oi_chg", "volume"]
    db.execute(text(f"insert into futures_flow_intraday ({', '.join(cols)}) values ({', '.join(':' + c for c in cols)}) on conflict (ts) do update set "
                    + ", ".join(f"{c} = coalesce(excluded.{c}, futures_flow_intraday.{c})" for c in cols[1:])), {c: row.get(c) for c in cols})
    db.commit()
    return row


def day(db: Session, d: str | None = None) -> dict:
    _ensure(db)
    if not d:
        d = db.execute(text("select max(ts)::date from futures_flow_intraday")).scalar()
        d = str(d) if d else datetime.now(KST).date().isoformat()
    rows = db.execute(text("select ts, foreign_eok, inst_eok, indiv_eok, price, oi, oi_chg from futures_flow_intraday where ts::date = cast(:d as date) order by ts"), {"d": d}).all()
    return {"date": d, "rows": [{"t": r[0].strftime("%H:%M"), "foreign": r[1], "inst": r[2], "indiv": r[3], "price": r[4], "oi": r[5], "oi_chg": r[6]} for r in rows]}
