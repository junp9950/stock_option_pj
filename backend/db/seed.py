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

_TOP_N = 30  # FDR 시총 상위 N종목


def _fetch_top_stocks(n: int = _TOP_N) -> list[dict]:
    """FinanceDataReader로 KOSPI 시총 상위 n종목 조회. 실패 시 빈 리스트."""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        listing = fdr.StockListing("KOSPI")
        listing = listing[listing["Marcap"].notna() & (listing["Marcap"] > 0)]
        listing = listing.sort_values("Marcap", ascending=False).head(n)
        listing["Code"] = listing["Code"].astype(str).str.zfill(6)
        result = []
        for _, row in listing.iterrows():
            result.append({
                "code": str(row["Code"]),
                "name": str(row.get("Name", row.get("ISU_ABBRV", row["Code"]))),
                "market": "KOSPI",
                "market_cap": float(row["Marcap"]),
            })
        logger.info("FDR universe loaded: %d KOSPI stocks", len(result))
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
            db.add(Stock(**stock_data))

    db.commit()
    logger.info("Universe seeded with %d stocks", len(stocks))


def refresh_universe(db: Session) -> int:
    """FDR로 유니버스를 최신 시총 기준으로 갱신. 신규 종목 추가 (기존 종목 삭제 없음).
    Returns: 새로 추가된 종목 수.
    """
    stocks = _fetch_top_stocks()
    if not stocks:
        return 0

    existing_codes = {s.code for s in db.scalars(select(Stock))}
    added = 0
    for stock_data in stocks:
        if stock_data["code"] not in existing_codes:
            db.add(Stock(**stock_data))
            added += 1
        else:
            # 시총만 업데이트
            stock = db.scalar(select(Stock).where(Stock.code == stock_data["code"]))
            if stock:
                stock.market_cap = stock_data["market_cap"]
                stock.name = stock_data["name"]
    db.commit()
    logger.info("Universe refreshed: %d new stocks added", added)
    return added
