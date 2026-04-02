from __future__ import annotations

from datetime import date

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import SpotDailyPrice, SpotInvestorFlow, Stock
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def _pykrx_investor_flow(code: str, yyyymmdd: str) -> tuple[float, float, float]:
    """pykrx로 외국인/기관/개인 순매수(원) 조회. 실패 시 (0, 0, 0) 반환."""
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415
        df = pykrx_stock.get_market_net_purchases_of_equities_by_investor(
            yyyymmdd, yyyymmdd, code
        )
        if df is None or df.empty:
            return 0.0, 0.0, 0.0
        row = df.iloc[0]

        def _col(r: pd.Series, *keys: str) -> float:
            for k in keys:
                if k in r.index:
                    return float(r[k])
            return 0.0

        return (
            _col(row, "외국인합계", "외국인"),
            _col(row, "기관합계", "기관"),
            _col(row, "개인"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx investor flow skipped for %s: %s", code, exc)
        return 0.0, 0.0, 0.0


def _load_listing_snapshot() -> pd.DataFrame:
    listing = fdr.StockListing("KRX")
    listing["Code"] = listing["Code"].astype(str).str.zfill(6)
    return listing.set_index("Code")


def _fallback_spot_row(db: Session, trading_date: date) -> None:
    for index, stock in enumerate(get_universe(db), start=1):
        base_price = 50_000 + index * 10_000
        change_pct = round(((index % 5) - 2) * 0.8, 2)
        close_price = base_price * (1 + change_pct / 100)
        db.add(
            SpotDailyPrice(
                trading_date=trading_date,
                stock_code=stock.code,
                open_price=base_price * 0.99,
                high_price=close_price * 1.01,
                low_price=base_price * 0.98,
                close_price=close_price,
                volume=2_000_000 + index * 250_000,
                trading_value=6_000_000_000 + index * 1_100_000_000,
                change_pct=change_pct,
            )
        )
        db.add(
            SpotInvestorFlow(
                trading_date=trading_date,
                stock_code=stock.code,
                foreign_net_buy=0.0,
                institution_net_buy=0.0,
                individual_net_buy=0.0,
            )
        )


def collect_spot_data(db: Session, trading_date: date) -> None:
    """Collect spot market data.

    Source: pykrx spot APIs where available.
    Fallback: demo data generation for local/offline runs.
    """

    db.execute(delete(SpotDailyPrice).where(SpotDailyPrice.trading_date == trading_date))
    db.execute(delete(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == trading_date))
    try:
        listing = _load_listing_snapshot()
        date_text = trading_date.isoformat()
        yyyymmdd = trading_date.strftime("%Y%m%d")
        for stock in get_universe(db):
            price_df = fdr.DataReader(stock.code, date_text, date_text)
            if price_df.empty:
                logger.warning("No spot data from FDR for %s on %s", stock.code, date_text)
                continue

            row = price_df.iloc[-1]
            listing_row = listing.loc[stock.code] if stock.code in listing.index else None
            if listing_row is not None:
                stock.name = str(listing_row.get("Name", stock.name))
                stock.market = str(listing_row.get("Market", stock.market))
                stock.market_cap = float(listing_row.get("Marcap", stock.market_cap or 0.0))
                db.add(stock)

            db.add(
                SpotDailyPrice(
                    trading_date=trading_date,
                    stock_code=stock.code,
                    open_price=float(row["Open"]),
                    high_price=float(row["High"]),
                    low_price=float(row["Low"]),
                    close_price=float(row["Close"]),
                    volume=float(row["Volume"]),
                    trading_value=float(listing_row.get("Amount", 0.0)) if listing_row is not None else 0.0,
                    change_pct=round(float(row["Change"]) * 100, 4),
                )
            )
            foreign_net, institution_net, individual_net = _pykrx_investor_flow(stock.code, yyyymmdd)
            db.add(
                SpotInvestorFlow(
                    trading_date=trading_date,
                    stock_code=stock.code,
                    foreign_net_buy=foreign_net,
                    institution_net_buy=institution_net,
                    individual_net_buy=individual_net,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR spot collection failed, falling back to demo data: %s", exc)
        _fallback_spot_row(db, trading_date)
    db.commit()
