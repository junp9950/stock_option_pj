from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Stock
from backend.utils.logger import get_logger


logger = get_logger(__name__)

DEFAULT_STOCKS = [
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "market_cap": 430_000_000_000_000},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "market_cap": 130_000_000_000_000},
    {"code": "035420", "name": "NAVER", "market": "KOSPI", "market_cap": 34_000_000_000_000},
    {"code": "005380", "name": "현대차", "market": "KOSPI", "market_cap": 45_000_000_000_000},
    {"code": "105560", "name": "KB금융", "market": "KOSPI", "market_cap": 30_000_000_000_000},
]

_TOP_N = 100  # FDR 시총 상위 N종목 (KOSPI + KOSDAQ 각각)

# 시총 기준 자동선별에서 빠지는 종목을 수동으로 고정 포함
MANUAL_STOCKS: list[dict] = [
    {"code": "353200", "name": "대덕전자", "market": "KOSPI", "market_cap": 0},
]


def _fetch_shares_from_pykrx() -> dict[str, float]:
    """pykrx로 전종목 상장주식수 조회. 실패 시 빈 dict."""
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415
        from datetime import date as _date  # noqa: PLC0415
        today = _date.today().strftime("%Y%m%d")
        df = pykrx_stock.get_market_cap_by_ticker(today, market="ALL")
        if df is None or df.empty:
            return {}
        col = next((c for c in df.columns if "상장" in c or "Shares" in c.lower()), None)
        if col is None:
            return {}
        return {str(code).zfill(6): float(val) for code, val in df[col].items() if val and float(val) > 0}
    except Exception as exc:  # noqa: BLE001
        logger.warning("pykrx shares fetch failed: %s", exc)
        return {}


def _fetch_top_stocks(n: int = _TOP_N) -> list[dict]:
    """FinanceDataReader로 KOSPI + KOSDAQ 시총 상위 n종목씩 조회. 실패 시 빈 리스트."""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        shares_map = _fetch_shares_from_pykrx()
        result = []
        for market in ("KOSPI", "KOSDAQ"):
            listing = fdr.StockListing(market)
            listing = listing[listing["Marcap"].notna() & (listing["Marcap"] > 0)]
            listing = listing.sort_values("Marcap", ascending=False).head(n)
            listing["Code"] = listing["Code"].astype(str).str.zfill(6)
            for _, row in listing.iterrows():
                code = str(row["Code"])
                shares = shares_map.get(code, 0.0)
                if shares == 0.0:
                    shares_col = next((c for c in listing.columns if c in ("Stocks", "Shares", "shares")), None)
                    if shares_col:
                        shares = float(row.get(shares_col, 0) or 0)
                result.append({
                    "code": code,
                    "name": str(row.get("Name", row.get("ISU_ABBRV", code))),
                    "market": market,
                    "market_cap": float(row["Marcap"]),
                    "shares_outstanding": shares,
                })
        logger.info("FDR universe loaded: %d stocks (KOSPI+KOSDAQ top %d each)", len(result), n)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR universe fetch failed, using default 5 stocks: %s", exc)
        return []


def seed_reference_data(db: Session) -> None:
    if db.scalar(select(Stock.id).limit(1)):
        return

    stocks = _fetch_top_stocks() or DEFAULT_STOCKS

    for stock_data in stocks:
        existing = db.scalar(select(Stock).where(Stock.code == stock_data["code"]))
        if existing is None:
            db.add(Stock(
                code=stock_data["code"],
                name=stock_data["name"],
                market=stock_data["market"],
                market_cap=stock_data.get("market_cap", 0.0),
                shares_outstanding=stock_data.get("shares_outstanding", 0.0),
            ))

    db.commit()
    logger.info("Universe seeded with %d stocks", len(stocks))


def _fetch_all_shares_from_fdr() -> dict[str, float]:
    """FDR StockListing으로 전종목 상장주식수 조회."""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        result: dict[str, float] = {}
        for market in ("KOSPI", "KOSDAQ"):
            listing = fdr.StockListing(market)
            listing["Code"] = listing["Code"].astype(str).str.zfill(6)
            shares_col = next((c for c in listing.columns if c in ("Stocks", "Shares", "shares")), None)
            if shares_col:
                for _, row in listing.iterrows():
                    v = row.get(shares_col, 0)
                    if v and float(v) > 0:
                        result[str(row["Code"])] = float(v)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR all shares fetch failed: %s", exc)
        return {}


def refresh_universe(db: Session) -> int:
    """FDR로 유니버스를 최신 시총 기준으로 갱신. 신규 종목 추가 (기존 종목 삭제 없음).
    Returns: 새로 추가된 종목 수.
    """
    stocks = _fetch_top_stocks()
    if not stocks:
        return 0

    # 수동 고정 종목은 항상 포함
    manual_codes = {s["code"] for s in MANUAL_STOCKS}
    stocks = [s for s in stocks if s["code"] not in manual_codes] + MANUAL_STOCKS

    # 전종목 상장주식수 (FDR) — DB에 있는 모든 종목에 일괄 적용
    all_shares = _fetch_all_shares_from_fdr()
    if all_shares:
        for stock in db.scalars(select(Stock)).all():
            s = all_shares.get(stock.code, 0)
            if s > 0 and stock.shares_outstanding != s:
                stock.shares_outstanding = s
        db.commit()
        logger.info("shares_outstanding 갱신 완료: %d종목", len(all_shares))

    existing_codes = {s.code for s in db.scalars(select(Stock))}
    added = 0
    for stock_data in stocks:
        if stock_data["code"] not in existing_codes:
            db.add(Stock(**stock_data))
            added += 1
        else:
            stock = db.scalar(select(Stock).where(Stock.code == stock_data["code"]))
            if stock:
                stock.market_cap = stock_data["market_cap"]
                stock.name = stock_data["name"]
                if stock_data.get("shares_outstanding", 0) > 0:
                    stock.shares_outstanding = stock_data["shares_outstanding"]
    db.commit()
    logger.info("Universe refreshed: %d new stocks added", added)
    return added
