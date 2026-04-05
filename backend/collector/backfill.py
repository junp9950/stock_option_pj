"""
과거 수급·가격 데이터 일괄 백필.

pykrx로 날짜별 전종목 수급, FDR로 종목별 가격을 한꺼번에 수집해
SpotDailyPrice / SpotInvestorFlow 테이블에 저장한다.
이미 데이터가 있는 날짜는 건너뛴다.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, SpotInvestorFlow, Stock
from backend.utils.dates import is_trading_day
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(v, default: float = 0.0) -> float:
    """NaN/None/inf를 default로 대체."""
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _trading_days_in_range(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _already_collected_dates(db: Session) -> set[date]:
    """SpotInvestorFlow에 이미 데이터가 있는 날짜 집합."""
    rows = db.execute(
        select(SpotInvestorFlow.trading_date).distinct()
    ).scalars().all()
    return set(rows)


# ── pykrx 수급 조회 ───────────────────────────────────────────────────────────

def _pykrx_flow_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """날짜 하나, 전종목 외국인/기관 순매수(원) 일괄 조회."""
    try:
        from pykrx import stock as ps  # noqa: PLC0415

        def _fetch(market: str, investor: str) -> pd.DataFrame:
            try:
                df = ps.get_market_net_purchases_of_equities_by_ticker(
                    yyyymmdd, yyyymmdd, market, investor
                )
                return df if df is not None else pd.DataFrame()
            except Exception:  # noqa: BLE001
                return pd.DataFrame()

        # KOSPI + KOSDAQ 합산
        df_f_k = _fetch("KOSPI", "외국인")
        df_f_q = _fetch("KOSDAQ", "외국인")
        df_i_k = _fetch("KOSPI", "기관합계")
        df_i_q = _fetch("KOSDAQ", "기관합계")

        df_foreign = pd.concat([df_f_k, df_f_q]) if not df_f_k.empty or not df_f_q.empty else pd.DataFrame()
        df_inst = pd.concat([df_i_k, df_i_q]) if not df_i_k.empty or not df_i_q.empty else pd.DataFrame()

        if df_foreign.empty and df_inst.empty:
            return {}

        def _net(df: pd.DataFrame, code: str) -> float:
            if df is None or df.empty or code not in df.index:
                return 0.0
            row = df.loc[code]
            for col in ["순매수", "매수", "순매수금액"]:
                if col in (row.index if hasattr(row, 'index') else []):
                    return float(row[col])
            for val in (row if hasattr(row, '__iter__') else []):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
            return 0.0

        all_codes: set[str] = set()
        if not df_foreign.empty:
            all_codes |= {str(c).zfill(6) for c in df_foreign.index}
        if not df_inst.empty:
            all_codes |= {str(c).zfill(6) for c in df_inst.index}

        result = {code: (_net(df_foreign, code), _net(df_inst, code), 0.0) for code in all_codes}
        logger.debug("pykrx flow batch %s: %d stocks", yyyymmdd, len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx batch failed for %s: %s", yyyymmdd, exc)
        return {}


# ── FDR 가격 조회 ─────────────────────────────────────────────────────────────

def _fetch_prices_for_stock(
    code: str, start: date, end: date
) -> Optional[pd.DataFrame]:
    """종목 코드 하나의 전체 기간 가격 데이터를 FDR로 가져온다."""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        df = fdr.DataReader(code, start.isoformat(), end.isoformat())
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index).normalize()
        return df
    except Exception as exc:  # noqa: BLE001
        logger.debug("FDR price fetch failed for %s: %s", code, exc)
        return None


# ── 메인 백필 ─────────────────────────────────────────────────────────────────

def run_backfill(
    db: Session,
    start_date: date,
    end_date: date,
    max_workers: int = 8,
    skip_existing: bool = True,
) -> dict:
    """
    start_date ~ end_date 기간의 가격 + 수급 데이터를 DB에 백필.

    Returns:
        {
            "days_total": int,       # 요청 거래일 수
            "days_skipped": int,     # 이미 있어서 건너뛴 날
            "days_filled": int,      # 새로 채운 날
            "stocks": int,           # 처리 종목 수
            "errors": list[str],     # 오류 메시지
        }
    """
    stocks = list(db.scalars(select(Stock)))
    if not stocks:
        return {"error": "종목 없음"}

    trading_days = _trading_days_in_range(start_date, end_date)
    if not trading_days:
        return {"error": "거래일 없음"}

    already = _already_collected_dates(db) if skip_existing else set()
    target_days = [d for d in trading_days if d not in already]

    logger.info(
        "백필 시작: %s ~ %s | 전체 %d 거래일, 대상 %d일, 건너뜀 %d일, 종목 %d개",
        start_date, end_date,
        len(trading_days), len(target_days), len(already & set(trading_days)),
        len(stocks),
    )

    if not target_days:
        return {
            "days_total": len(trading_days),
            "days_skipped": len(trading_days),
            "days_filled": 0,
            "stocks": len(stocks),
            "errors": [],
        }

    # ── Step 1: FDR로 종목별 전체 기간 가격 다운로드 (병렬)
    logger.info("Step 1/2 — FDR 가격 다운로드 중 (%d 종목)...", len(stocks))
    price_cache: dict[str, pd.DataFrame] = {}

    def _load_price(s: Stock) -> tuple[str, Optional[pd.DataFrame]]:
        return s.code, _fetch_prices_for_stock(s.code, start_date, end_date)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_load_price, s): s.code for s in stocks}
        done = 0
        for fut in as_completed(futs):
            code, df = fut.result()
            if df is not None:
                price_cache[code] = df
            done += 1
            if done % 30 == 0:
                logger.info("  가격 다운로드: %d / %d", done, len(stocks))

    logger.info("  가격 다운로드 완료: %d / %d 종목 성공", len(price_cache), len(stocks))

    # ── Step 2: 날짜별 수급 + 가격 저장
    logger.info("Step 2/2 — 날짜별 수급 저장 중 (%d일)...", len(target_days))
    errors: list[str] = []
    days_filled = 0

    for idx, trading_date in enumerate(target_days):
        yyyymmdd = trading_date.strftime("%Y%m%d")

        # pykrx 수급 조회 (실패하면 0으로 저장)
        flows = _pykrx_flow_batch(yyyymmdd)
        if not flows:
            logger.debug("pykrx flow empty for %s — 수급 0으로 저장", yyyymmdd)

        ts = pd.Timestamp(trading_date)
        inserted = 0

        for stock in stocks:
            code = stock.code

            # 가격 저장
            if code in price_cache:
                df = price_cache[code]
                if ts in df.index:
                    row = df.loc[ts]
                    # 중복 체크
                    exists = db.scalar(
                        select(SpotDailyPrice.id).where(
                            SpotDailyPrice.trading_date == trading_date,
                            SpotDailyPrice.stock_code == code,
                        )
                    )
                    if not exists:
                        db.add(SpotDailyPrice(
                            trading_date=trading_date,
                            stock_code=code,
                            open_price=float(row.get("Open", 0)),
                            high_price=float(row.get("High", 0)),
                            low_price=float(row.get("Low", 0)),
                            close_price=float(row.get("Close", 0)),
                            volume=float(row.get("Volume", 0)),
                            trading_value=float(row.get("Amount", row.get("Turnover", 0))),
                            change_pct=round(_safe_float(row.get("Change", 0)) * 100, 4),
                        ))

            # 수급 저장
            exists_flow = db.scalar(
                select(SpotInvestorFlow.id).where(
                    SpotInvestorFlow.trading_date == trading_date,
                    SpotInvestorFlow.stock_code == code,
                )
            )
            if not exists_flow:
                f, i, p = flows.get(code, (0.0, 0.0, 0.0))
                db.add(SpotInvestorFlow(
                    trading_date=trading_date,
                    stock_code=code,
                    foreign_net_buy=f,
                    institution_net_buy=i,
                    individual_net_buy=p,
                ))
                inserted += 1

        try:
            db.commit()
            days_filled += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            msg = f"{trading_date}: commit 실패 — {exc}"
            logger.warning(msg)
            errors.append(msg)

        if (idx + 1) % 10 == 0 or (idx + 1) == len(target_days):
            logger.info("  저장 진행: %d / %d일 완료", idx + 1, len(target_days))

        # pykrx 과부하 방지 (너무 빠르면 차단될 수 있음)
        time.sleep(0.3)

    logger.info(
        "백필 완료: %d일 채움, %d일 건너뜀, 오류 %d건",
        days_filled, len(trading_days) - len(target_days), len(errors),
    )

    return {
        "days_total": len(trading_days),
        "days_skipped": len(trading_days) - len(target_days),
        "days_filled": days_filled,
        "stocks": len(stocks),
        "errors": errors[:20],  # 최대 20개만 반환
    }
