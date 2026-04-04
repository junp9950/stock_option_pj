from __future__ import annotations

from datetime import date

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import SpotDailyPrice, SpotInvestorFlow, Stock
from backend.utils.dates import latest_trading_day
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def _naver_investor_flow_single(code: str, target_date_iso: str) -> tuple[float, float, float]:
    """네이버 금융 main.naver에서 외국인/기관 순매수(주) 조회.
    반환: (foreign_net_shares, institution_net_shares, 0.0)
    실패 시 (0, 0, 0) 반환.
    """
    try:
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415
        r = requests.get(
            "https://finance.naver.com/item/main.naver",
            params={"code": code},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"},
            timeout=5,
        )
        if r.status_code != 200:
            return 0.0, 0.0, 0.0
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.select("table")
        # Table 3: 날짜 | 종가 | 등락 | 외국인 | 기관
        if len(tables) < 4:
            return 0.0, 0.0, 0.0
        t = tables[3]
        # target_date_iso: "2026-04-03" → "04/03"
        target_mmdd = target_date_iso[5:].replace("-", "/")

        def _parse(s: str) -> float:
            s = s.replace(",", "").replace("+", "").replace(" ", "")
            try:
                return float(s)
            except ValueError:
                return 0.0

        for row in t.select("tr"):
            # 날짜가 th에, 나머지가 td에 있는 구조
            cells = [c.get_text(strip=True) for c in row.select("th,td")]
            if not cells or cells[0] != target_mmdd:
                continue
            # cells: [mmdd, close, change, foreign_net, institution_net]
            foreign_net = _parse(cells[3]) if len(cells) > 3 else 0.0
            inst_net = _parse(cells[4]) if len(cells) > 4 else 0.0
            return foreign_net, inst_net, 0.0
        return 0.0, 0.0, 0.0
    except Exception as exc:  # noqa: BLE001
        logger.debug("naver investor flow failed for %s: %s", code, exc)
        return 0.0, 0.0, 0.0


def _pykrx_investor_flow_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """pykrx로 당일 전종목 외국인/기관/개인 순매수(원) 일괄 조회.
    반환: {종목코드: (foreign_net, institution_net, individual_net)}
    실패 시 빈 dict 반환.
    """
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415
        df = pykrx_stock.get_market_net_purchases_of_equities_by_investor(
            yyyymmdd, yyyymmdd
        )
        if df is None or df.empty:
            return {}

        result: dict[str, tuple[float, float, float]] = {}

        def _col(row: pd.Series, *keys: str) -> float:
            for k in keys:
                if k in row.index:
                    return float(row[k])
            return 0.0

        for code, row in df.iterrows():
            code_str = str(code).zfill(6)
            result[code_str] = (
                _col(row, "외국인합계", "외국인"),
                _col(row, "기관합계", "기관"),
                _col(row, "개인"),
            )
        logger.info("pykrx batch investor flow: %d stocks fetched for %s", len(result), yyyymmdd)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx batch investor flow failed: %s", exc)
        return {}


def _pykrx_investor_flow_single(code: str, yyyymmdd: str) -> tuple[float, float, float]:
    """pykrx로 단일 종목 외국인/기관/개인 순매수(원) 조회. 실패 시 (0, 0, 0) 반환."""
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

    Source: FinanceDataReader for prices, pykrx (batch) for investor flow.
    Fallback: demo data generation for local/offline runs.
    """

    # pykrx/FDR 조회는 마지막 실제 거래일 기준으로 (주말·공휴일 진입 방지)
    fetch_date = latest_trading_day(trading_date)
    if fetch_date != trading_date:
        logger.info("trading_date=%s is non-trading day → fetching data for %s", trading_date, fetch_date)

    db.execute(delete(SpotDailyPrice).where(SpotDailyPrice.trading_date == trading_date))
    db.execute(delete(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == trading_date))
    try:
        listing = _load_listing_snapshot()
        date_text = fetch_date.isoformat()
        yyyymmdd = fetch_date.strftime("%Y%m%d")

        # pykrx 전종목 수급 일괄 조회 (한 번만 호출)
        batch_flows = _pykrx_investor_flow_batch(yyyymmdd)
        batch_ok = len(batch_flows) > 0
        if not batch_ok:
            logger.warning("pykrx batch investor flow failed — will use single-stock fallback per stock")

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

            # 수급 데이터: pykrx 배치 → pykrx 단건 → 네이버 순서로 시도
            if batch_ok and stock.code in batch_flows:
                foreign_net, institution_net, individual_net = batch_flows[stock.code]
            elif not batch_ok:
                foreign_net, institution_net, individual_net = _pykrx_investor_flow_single(stock.code, yyyymmdd)
            else:
                foreign_net, institution_net, individual_net = 0.0, 0.0, 0.0

            # pykrx 실패 시 네이버 fallback
            if foreign_net == 0.0 and institution_net == 0.0:
                foreign_net, institution_net, individual_net = _naver_investor_flow_single(stock.code, fetch_date.isoformat())

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
