from __future__ import annotations

from datetime import date

import re

import FinanceDataReader as fdr
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import (
    DerivativesFuturesDaily,
    DerivativesOptionsDaily,
    FuturesDailyPrice,
    IndexDaily,
    OpenInterestDaily,
)
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def kospi200_closes(count: int = 10) -> dict[date, float]:
    """네이버 지수 차트의 KOSPI200 일별 종가 (최근 count일). 실패하면 빈 dict."""
    try:
        r = requests.get("https://fchart.stock.naver.com/sise.nhn", timeout=15, headers={"User-Agent": "Mozilla/5.0"},
                         params={"symbol": "KPI200", "timeframe": "day", "count": str(count), "requestType": "0"})
        out = {}
        for item in re.findall(r'data="([^"]+)"', r.text):
            d, _o, _h, _l, c, _v = item.split("|")
            out[date(int(d[:4]), int(d[4:6]), int(d[6:8]))] = float(c)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("네이버 KOSPI200 조회 실패: %s", exc)
        return {}

def collect_derivatives_data(db: Session, trading_date: date) -> None:
    """Collect futures/options/index data.

    - KOSPI200 지수: 네이버 지수 차트 → 야후 '^KS200'. FDR 'KS200'은 빈 값을 줘서 코드 기본값 350.5가 저장됐었다(2026-10 확인).
      둘 다 못 받으면 가짜 값 대신 직전에 저장된 실제 값을 쓴다.
    - 선물 종가: 지수 종가로 대신.
    - 옵션 미결제약정·선물 투자자별 매매: pykrx·KRX 직접 조회가 KRX 로그인 필수화 이후 계속 실패해 2026-10-03 제거 → 0.
    """
    date_iso = trading_date.isoformat()  # FDR은 ISO 형식(YYYY-MM-DD) 필요

    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    # ── 1. KOSPI200 index close (네이버 → 야후 ^KS200) ─────────────────────
    index_close = kospi200_closes().get(trading_date)
    if index_close is not None:
        logger.info("네이버 KOSPI200 종가: %.2f", index_close)
    else:
        try:
            index_df = fdr.DataReader("^KS200", date_iso, date_iso)
            if not index_df.empty:
                index_close = float(index_df.iloc[-1]["Close"])
                logger.info("FDR ^KS200 index close: %.2f", index_close)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FDR ^KS200 index fetch failed: %s", exc)
    if index_close is None:
        index_close = db.scalar(select(IndexDaily.close_price).where(IndexDaily.trading_date < trading_date, IndexDaily.close_price != 350.5)
                                .order_by(IndexDaily.trading_date.desc()).limit(1)) or 0.0
        logger.warning("KOSPI200 지수를 못 받아 직전 값 %.2f로 대신", index_close)

    # ── 2. KOSPI200 futures close: 지수 종가로 대신 ─────────────────────────
    futures_close = index_close

    # ── 3. Options & futures open interest: 소스 없음 → 0 ────────────────────
    call_oi, put_oi, futures_oi = 0.0, 0.0, 0.0

    # ── 4. Futures investor breakdown: 소스 없음 → 0 ─────────────────────────
    foreign_net = institution_net = individual_net = 0.0

    # upsert (DELETE 대신 — Supabase timeout 방지)
    db.execute(
        pg_insert(IndexDaily).values(trading_date=trading_date, index_code="1028", close_price=index_close)
        .on_conflict_do_update(constraint="uq_index_daily", set_={"close_price": index_close})
    )
    db.execute(
        pg_insert(FuturesDailyPrice).values(trading_date=trading_date, symbol="KOSPI200", close_price=futures_close)
        .on_conflict_do_update(constraint="uq_futures_daily_price", set_={"close_price": futures_close})
    )
    db.execute(
        pg_insert(DerivativesFuturesDaily).values(
            trading_date=trading_date,
            foreign_net_contracts=foreign_net,
            institution_net_contracts=institution_net,
            individual_net_contracts=individual_net,
            foreign_net_amount=0.0,
        ).on_conflict_do_update(
            constraint="uq_derivatives_futures_daily",
            set_={"foreign_net_contracts": foreign_net, "institution_net_contracts": institution_net, "individual_net_contracts": individual_net},
        )
    )
    db.execute(
        pg_insert(DerivativesOptionsDaily).values(
            trading_date=trading_date,
            call_foreign_net=0.0, put_foreign_net=0.0,
            call_institution_net=0.0, put_institution_net=0.0,
        ).on_conflict_do_update(
            constraint="uq_derivatives_options_daily",
            set_={"call_foreign_net": 0.0},
        )
    )
    db.execute(
        pg_insert(OpenInterestDaily).values(
            trading_date=trading_date, futures_oi=futures_oi, call_oi=call_oi, put_oi=put_oi,
        ).on_conflict_do_update(
            constraint="uq_open_interest_daily",
            set_={"futures_oi": futures_oi, "call_oi": call_oi, "put_oi": put_oi},
        )
    )
    db.commit()
