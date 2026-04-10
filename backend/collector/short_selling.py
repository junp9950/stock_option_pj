from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import ShortSellingDaily
from backend.utils.dates import latest_trading_day
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# KRX 데이터포털 엔드포인트
_KRX_API_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://data.krx.co.kr/contents/MDC/STAT/srt/MDCSTAT30101.jsp",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "http://data.krx.co.kr",
}


def _krx_direct_short_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """KRX 데이터포털 직접 HTTP 요청으로 공매도 데이터 일괄 조회.
    pykrx 없이도 동작하는 직접 KRX API 호출.
    반환: {종목코드: (short_volume, short_ratio, short_balance)}
    실패 시 빈 dict 반환.
    """
    try:
        import requests  # noqa: PLC0415

        # KRX 세션 초기화 (JSESSIONID 쿠키 획득)
        session = requests.Session()
        session.headers.update(_KRX_HEADERS)
        try:
            session.get("http://data.krx.co.kr/", timeout=5)
        except Exception:  # noqa: BLE001
            pass  # 실패해도 계속 시도

        vol_map: dict[str, tuple[float, float]] = {}
        bal_map: dict[str, float] = {}

        for mkt_id in ("STK", "KSQ"):  # KOSPI, KOSDAQ
            # ── 공매도 거래량/비중 (pykrx bld: dbms/MDC/STAT/srt/MDCSTAT30101)
            try:
                r = session.post(
                    _KRX_API_URL,
                    data={
                        "bld": "dbms/MDC/STAT/srt/MDCSTAT30101",
                        "mktId": mkt_id,
                        "trdDd": yyyymmdd,
                        "inqCond": "STMFRTSCIFDRFS",
                    },
                    headers=_KRX_HEADERS,
                    timeout=15,
                )
                if r.status_code == 200:
                    for item in r.json().get("OutBlock_1", []):
                        code = str(item.get("ISU_SRT_CD", "")).zfill(6)
                        if not code or code == "000000":
                            continue
                        # 공매도 거래량
                        vol = 0.0
                        for k in ("CVSRTSELL_TRDVOL", "SHRTS_TRDVOL", "공매도거래량", "공매도"):
                            if k in item and item[k] is not None:
                                try:
                                    vol = float(str(item[k]).replace(",", ""))
                                    break
                                except (ValueError, TypeError):
                                    pass
                        # 공매도 비중 (거래량 대비 %)
                        ratio = 0.0
                        for k in ("TRDVOL_WT", "SHRTS_TRDVOL_WT", "공매도비중", "비중"):
                            if k in item and item[k] is not None:
                                try:
                                    ratio = float(str(item[k]).replace(",", ""))
                                    break
                                except (ValueError, TypeError):
                                    pass
                        vol_map[code] = (vol, ratio)
            except Exception as exc:  # noqa: BLE001
                logger.debug("KRX direct short vol %s failed: %s", mkt_id, exc)

            # ── 공매도 잔고 (pykrx bld: dbms/MDC/STAT/srt/MDCSTAT30501)
            try:
                mkt_tp = "1" if mkt_id == "STK" else "2"
                r = session.post(
                    _KRX_API_URL,
                    data={
                        "bld": "dbms/MDC/STAT/srt/MDCSTAT30501",
                        "mktTpCd": mkt_tp,
                        "trdDd": yyyymmdd,
                    },
                    headers=_KRX_HEADERS,
                    timeout=15,
                )
                if r.status_code == 200:
                    for item in r.json().get("OutBlock_1", []):
                        code = str(item.get("ISU_SRT_CD", "")).zfill(6)
                        if not code or code == "000000":
                            continue
                        bal = 0.0
                        for k in ("BAL_AMT", "BALANCE_AMT", "잔고금액", "공매도잔고금액", "SHRTS_BAL_AMT"):
                            if k in item and item[k] is not None:
                                try:
                                    bal = float(str(item[k]).replace(",", ""))
                                    break
                                except (ValueError, TypeError):
                                    pass
                        bal_map[code] = bal
            except Exception as exc:  # noqa: BLE001
                logger.debug("KRX direct short bal %s failed: %s", mkt_id, exc)

        all_codes = set(vol_map) | set(bal_map)
        if not all_codes:
            return {}

        result: dict[str, tuple[float, float, float]] = {}
        for code in all_codes:
            vol, ratio = vol_map.get(code, (0.0, 0.0))
            bal = bal_map.get(code, 0.0)
            if vol > 0 or ratio > 0 or bal > 0:
                result[code] = (vol, ratio, bal)

        logger.info("KRX direct short selling: %d stocks fetched for %s", len(result), yyyymmdd)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("KRX direct short selling failed: %s", exc)
        return {}


def _pykrx_short_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """pykrx로 KOSPI+KOSDAQ 전종목 공매도 데이터 일괄 조회.
    반환: {종목코드: (short_volume, short_ratio, short_balance)}
    실패 시 빈 dict 반환.
    """
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415

        result: dict[str, tuple[float, float, float]] = {}
        vol_map: dict[str, tuple[float, float]] = {}
        bal_map: dict[str, float] = {}

        for market in ("KOSPI", "KOSDAQ"):
            try:
                vol_df = pykrx_stock.get_shorting_volume_by_ticker(yyyymmdd, market=market)
                if vol_df is not None and not vol_df.empty:
                    for code, row in vol_df.iterrows():
                        code_str = str(code).zfill(6)
                        vol = float(row["공매도"]) if "공매도" in row.index else 0.0
                        ratio = float(row["비중"]) if "비중" in row.index else 0.0
                        vol_map[code_str] = (vol, ratio)
            except Exception:  # noqa: BLE001
                pass

            try:
                bal_df = pykrx_stock.get_shorting_balance_by_ticker(yyyymmdd, market=market)
                if bal_df is not None and not bal_df.empty:
                    for code, row in bal_df.iterrows():
                        code_str = str(code).zfill(6)
                        for col in ("공매도잔고금액", "잔고금액", "공매도잔고"):
                            if col in row.index:
                                bal_map[code_str] = float(row[col])
                                break
            except Exception:  # noqa: BLE001
                pass

        all_codes = set(vol_map) | set(bal_map)
        for code in all_codes:
            vol, ratio = vol_map.get(code, (0.0, 0.0))
            bal = bal_map.get(code, 0.0)
            if vol > 0 or ratio > 0 or bal > 0:
                result[code] = (vol, ratio, bal)

        logger.info("pykrx batch short selling: %d stocks fetched for %s", len(result), yyyymmdd)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx batch short selling failed: %s", exc)
        return {}


def _pykrx_short_single(code: str, yyyymmdd: str) -> tuple[float, float, float] | None:
    """pykrx로 단일 종목 공매도 데이터 조회. 실패 시 None 반환."""
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

    Source priority:
      1. pykrx 전종목 일괄 조회 (KOSPI + KOSDAQ)
      2. KRX 데이터포털 직접 HTTP 요청 (pykrx 차단 시)
      3. pykrx 단건 조회 (배치 실패 시)
      4. 데이터 없음 → 레코드 미삽입 (signal engine이 None으로 처리 → 중립 점수)

    KRX 완전 차단 시 가짜 값 대신 레코드를 삽입하지 않는다.
    signal engine은 short=None일 때 공매도 점수 0.0(중립)으로 처리한다.
    """
    fetch_date = latest_trading_day(trading_date)
    if fetch_date != trading_date:
        logger.info("trading_date=%s is non-trading → fetching short data for %s", trading_date, fetch_date)
    yyyymmdd = fetch_date.strftime("%Y%m%d")
    db.execute(delete(ShortSellingDaily).where(ShortSellingDaily.trading_date == trading_date))

    # 1차: pykrx 배치
    batch_data = _pykrx_short_batch(yyyymmdd)
    source = "pykrx"

    # 2차: KRX 직접 API (pykrx 실패 시)
    if not batch_data:
        logger.info("pykrx 실패 → KRX 직접 API 시도")
        batch_data = _krx_direct_short_batch(yyyymmdd)
        source = "krx_direct"

    batch_ok = len(batch_data) > 0

    if batch_ok:
        logger.info("공매도 배치 수집 성공 (%s): %d 종목", source, len(batch_data))
        # 배치 성공: 전종목 레코드 삽입 (배치에 없는 종목 = 당일 공매도 없음 = 실제 0)
        for stock in get_universe(db):
            if stock.code in batch_data:
                short_volume, short_ratio, short_balance = batch_data[stock.code]
            else:
                short_volume = 0.0
                short_ratio = 0.0
                short_balance = 0.0
            db.add(ShortSellingDaily(
                trading_date=trading_date,
                stock_code=stock.code,
                short_volume=short_volume,
                short_ratio=short_ratio,
                short_balance=short_balance,
            ))
        db.commit()
        return

    # 3차: pykrx 단건 (배치 실패 시만)
    logger.warning("공매도 배치 모두 실패 — 종목별 단건 조회 시도")
    single_data: dict[str, tuple[float, float, float]] = {}
    for stock in get_universe(db):
        result = _pykrx_short_single(stock.code, yyyymmdd)
        if result is not None:
            single_data[stock.code] = result

    if single_data:
        logger.info("공매도 단건 수집 성공: %d 종목", len(single_data))
        for code, (vol, ratio, bal) in single_data.items():
            db.add(ShortSellingDaily(
                trading_date=trading_date,
                stock_code=code,
                short_volume=vol,
                short_ratio=ratio,
                short_balance=bal,
            ))
        db.commit()
    else:
        # 모든 소스 실패 → 레코드 미삽입. signal engine이 short=None → 중립 처리
        logger.warning("공매도 데이터 수집 실패 (%s) — 레코드 삽입 안 함 (중립 처리)", trading_date)
        db.commit()
