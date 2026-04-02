from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import ShortSellingDaily
from backend.utils.logger import get_logger


logger = get_logger(__name__)

_FALLBACK_VOL_BASE = 20_000
_FALLBACK_RATIO_BASE = 1.8
_FALLBACK_BAL_BASE = 90_000_000


def _pykrx_short(code: str, yyyymmdd: str) -> tuple[float, float, float] | None:
    """pykrx로 공매도 데이터 조회. 실패 시 None 반환."""
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415

        vol_df = pykrx_stock.get_shorting_volume_by_date(yyyymmdd, yyyymmdd, code)
        bal_df = pykrx_stock.get_shorting_balance_by_date(yyyymmdd, yyyymmdd, code)

        short_volume = 0.0
        short_ratio = 0.0
        short_balance = 0.0

        if vol_df is not None and not vol_df.empty:
            vrow = vol_df.iloc[0]
            short_volume = float(vrow["공매도"]) if "공매도" in vrow.index else 0.0
            short_ratio = float(vrow["비중"]) if "비중" in vrow.index else 0.0

        if bal_df is not None and not bal_df.empty:
            brow = bal_df.iloc[0]
            for col in ("공매도잔고금액", "잔고금액", "공매도잔고"):
                if col in brow.index:
                    short_balance = float(brow[col])
                    break
            if short_ratio == 0.0 and "비중" in brow.index:
                short_ratio = float(brow["비중"])

        if short_volume == 0.0 and short_ratio == 0.0 and short_balance == 0.0:
            return None

        return short_volume, short_ratio, short_balance
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx short selling skipped for %s: %s", code, exc)
        return None


def collect_short_selling_data(db: Session, trading_date: date) -> None:
    """Collect short selling data.

    Source: pykrx shorting endpoints where available.
    Fallback: synthetic demo values for local/offline runs.
    """

    yyyymmdd = trading_date.strftime("%Y%m%d")
    db.execute(delete(ShortSellingDaily).where(ShortSellingDaily.trading_date == trading_date))
    for index, stock in enumerate(get_universe(db), start=1):
        result = _pykrx_short(stock.code, yyyymmdd)
        if result is not None:
            short_volume, short_ratio, short_balance = result
            logger.debug("pykrx short data for %s: vol=%s ratio=%s bal=%s", stock.code, short_volume, short_ratio, short_balance)
        else:
            short_volume = _FALLBACK_VOL_BASE + index * 1_500
            short_ratio = _FALLBACK_RATIO_BASE + index * 0.2
            short_balance = _FALLBACK_BAL_BASE + index * 10_000_000
        db.add(
            ShortSellingDaily(
                trading_date=trading_date,
                stock_code=stock.code,
                short_volume=short_volume,
                short_ratio=short_ratio,
                short_balance=short_balance,
            )
        )
    db.commit()
