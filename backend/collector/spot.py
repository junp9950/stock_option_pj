from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import SpotDailyPrice, SpotInvestorFlow, Stock
from backend.utils.dates import latest_trading_day
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# KIS 토큰 메모리 캐시
_kis_token: str = ""
_kis_token_expires_at: float = 0.0

# 토큰 파일 경로 (.env 옆에 저장)
import os as _os
from pathlib import Path as _Path
_TOKEN_FILE = _Path(__file__).resolve().parent.parent.parent / ".kis_token"


def _load_token_from_file() -> None:
    """서버 시작 시 파일에서 토큰 복원."""
    global _kis_token, _kis_token_expires_at
    import time
    try:
        if _TOKEN_FILE.exists():
            parts = _TOKEN_FILE.read_text().strip().split("\n")
            if len(parts) == 2:
                token, expires = parts[0], float(parts[1])
                if time.time() < expires - 600:  # 아직 유효하면 복원
                    _kis_token = token
                    _kis_token_expires_at = expires
                    logger.info("KIS 토큰 파일에서 복원 (잔여 %.0f초)", expires - time.time())
    except Exception:  # noqa: BLE001
        pass


def _save_token_to_file(token: str, expires_at: float) -> None:
    """토큰을 파일에 저장."""
    try:
        _TOKEN_FILE.write_text(f"{token}\n{expires_at}")
    except Exception:  # noqa: BLE001
        pass


# 모듈 로드 시 파일에서 토큰 복원 시도
_load_token_from_file()


def _get_kis_token() -> str:
    """KIS Access Token 반환. 만료 10분 전이면 자동 재발급. 파일 캐시 사용."""
    import os, time, requests as _req  # noqa: PLC0415
    global _kis_token, _kis_token_expires_at

    if _kis_token and time.time() < _kis_token_expires_at - 600:
        return _kis_token

    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        return ""
    try:
        r = _req.post(
            "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
            timeout=10,
        ).json()
        token = r.get("access_token", "")
        if token:
            expires_at = time.time() + 86400  # 24시간
            _kis_token = token
            _kis_token_expires_at = expires_at
            _save_token_to_file(token, expires_at)
            logger.info("KIS 토큰 발급 완료 (24시간 유효)")
        else:
            logger.warning("KIS 토큰 발급 실패: %s", r.get("error_description", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("KIS 토큰 발급 오류: %s", exc)
    return _kis_token


def _kis_investor_flow_batch(yyyymmdd: str, codes: list[str]) -> dict[str, tuple[float, float, float]]:
    """한국투자증권 Open API로 종목별 외국인/기관 순매수 수량 조회.
    반환: {종목코드: (foreign_net, institution_net, individual_net)}
    실패 시 빈 dict 반환.
    """
    import os, time as _time  # noqa: PLC0415
    import requests as _req
    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        return {}

    token = _get_kis_token()
    if not token:
        return {}

    result: dict[str, tuple[float, float, float]] = {}
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900",
        "content-type": "application/json",
    }

    for code in codes:
        try:
            r = _req.get(
                "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor",
                headers=headers,
                params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code},
                timeout=5,
            )
            rows = r.json().get("output", [])
            for row in rows:
                if row.get("stck_bsop_date") == yyyymmdd:
                    f = float(row.get("frgn_ntby_qty") or 0)
                    i = float(row.get("orgn_ntby_qty") or 0)
                    p = float(row.get("prsn_ntby_qty") or 0)
                    result[code] = (f, i, p)
                    break
            _time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            logger.debug("KIS flow failed for %s: %s", code, exc)

    logger.info("KIS 수급 수집 완료: %d/%d 종목", len(result), len(codes))
    return result


def _pykrx_investor_flow_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """pykrx로 당일 전종목 외국인/기관 순매수(원) 일괄 조회.
    반환: {종목코드: (foreign_net, institution_net, 0.0)}
    실패 시 빈 dict 반환.
    """
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415

        def _fetch(market: str, investor: str) -> pd.DataFrame:
            try:
                df = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                    yyyymmdd, yyyymmdd, market, investor
                )
                return df if df is not None else pd.DataFrame()
            except Exception:  # noqa: BLE001
                return pd.DataFrame()

        df_f_k = _fetch("KOSPI", "외국인")
        df_f_q = _fetch("KOSDAQ", "외국인")
        df_i_k = _fetch("KOSPI", "기관합계")
        df_i_q = _fetch("KOSDAQ", "기관합계")

        df_foreign = pd.concat([df_f_k, df_f_q]) if not df_f_k.empty or not df_f_q.empty else pd.DataFrame()
        df_inst = pd.concat([df_i_k, df_i_q]) if not df_i_k.empty or not df_i_q.empty else pd.DataFrame()

        if df_foreign.empty and df_inst.empty:
            return {}

        result: dict[str, tuple[float, float, float]] = {}

        def _net(df: pd.DataFrame, code: str) -> float:
            if df is None or df.empty or code not in df.index:
                return 0.0
            row = df.loc[code]
            for col in ["순매수", "매수", "순매수금액"]:
                if col in row.index:
                    return float(row[col])
            # 첫 번째 숫자 컬럼 사용
            for val in row:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
            return 0.0

        all_codes = set()
        if df_foreign is not None and not df_foreign.empty:
            all_codes |= set(str(c).zfill(6) for c in df_foreign.index)
        if df_inst is not None and not df_inst.empty:
            all_codes |= set(str(c).zfill(6) for c in df_inst.index)

        for code in all_codes:
            result[code] = (
                _net(df_foreign, code),
                _net(df_inst, code),
                0.0,
            )

        logger.info("pykrx batch investor flow: %d stocks fetched for %s", len(result), yyyymmdd)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx batch investor flow failed: %s", exc)
        return {}


def _pykrx_investor_flow_single(code: str, yyyymmdd: str) -> tuple[float, float, float]:
    """pykrx로 단일 종목 외국인/기관 순매수(원) 조회. 실패 시 (0, 0, 0) 반환."""
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415

        def _net_from_df(df: pd.DataFrame) -> float:
            if df is None or df.empty:
                return 0.0
            row = df.iloc[0]
            for col in ["순매수", "매수", "순매수금액"]:
                if col in row.index:
                    return float(row[col])
            for val in row:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
            return 0.0

        def _fetch_single(market: str, investor: str) -> pd.DataFrame:
            try:
                df = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                    yyyymmdd, yyyymmdd, market, investor
                )
                return df if df is not None else pd.DataFrame()
            except Exception:  # noqa: BLE001
                return pd.DataFrame()

        df_f = pd.concat([_fetch_single("KOSPI", "외국인"), _fetch_single("KOSDAQ", "외국인")])
        df_i = pd.concat([_fetch_single("KOSPI", "기관합계"), _fetch_single("KOSDAQ", "기관합계")])

        def _get(df: pd.DataFrame) -> float:
            if df is None or df.empty or code not in df.index:
                return 0.0
            return _net_from_df(df.loc[[code]])

        return _get(df_f), _get(df_i), 0.0
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx investor flow skipped for %s: %s", code, exc)
        return 0.0, 0.0, 0.0


def _load_listing_snapshot() -> pd.DataFrame:
    listing = fdr.StockListing("KRX")
    listing["Code"] = listing["Code"].astype(str).str.zfill(6)
    return listing.set_index("Code")


def _fallback_spot_row(db: Session, trading_date: date) -> None:
    """FDR 수집 실패 시 폴백. 이미 실제 데이터가 있는 종목은 건드리지 않는다."""
    from sqlalchemy import select  # noqa: PLC0415
    existing_codes = {
        row[0] for row in db.execute(
            select(SpotDailyPrice.stock_code).where(SpotDailyPrice.trading_date == trading_date)
        )
    }
    if existing_codes:
        logger.info("폴백 스킵: %s에 이미 %d종목 실제 데이터 존재", trading_date, len(existing_codes))
        return
    logger.warning("폴백 데이터 생성: %s (실제 데이터 없음)", trading_date)
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
        trading_date = fetch_date  # 비거래일이면 실제 거래일로 redirect

    try:
        listing = _load_listing_snapshot()
        date_text = fetch_date.isoformat()
        yyyymmdd = fetch_date.strftime("%Y%m%d")

        # FDR 테스트 수집 — 실패하면 기존 데이터 보존 후 리턴
        test_df = fdr.DataReader("005930", date_text, date_text)
        if test_df.empty:
            logger.warning("FDR 수집 실패 (%s) — 기존 DB 데이터 보존", date_text)
            return

        # FDR 정상 확인 (기존 데이터는 upsert로 덮어씀, DELETE 불필요)

        # pykrx 전종목 수급 일괄 조회 (한 번만 호출)
        batch_flows = _pykrx_investor_flow_batch(yyyymmdd)
        batch_ok = len(batch_flows) > 0
        if not batch_ok:
            logger.warning("pykrx batch investor flow failed — KIS API 시도")

        stocks = list(get_universe(db))

        # FDR 가격 병렬 다운로드 (requests read timeout 10초 강제 적용)
        import requests as _requests  # noqa: PLC0415
        _orig_request = _requests.Session.request
        def _patched_request(self, method, url, **kwargs):  # noqa: ANN001
            kwargs.setdefault("timeout", 10)
            return _orig_request(self, method, url, **kwargs)
        _requests.Session.request = _patched_request  # type: ignore[method-assign]

        def _fetch_price(code: str) -> tuple[str, Optional[pd.DataFrame]]:
            try:
                df = fdr.DataReader(code, date_text, date_text)
                return code, df if not df.empty else None
            except Exception:  # noqa: BLE001
                return code, None

        price_map: dict[str, pd.DataFrame] = {}
        try:
            with ThreadPoolExecutor(max_workers=16) as pool:
                futs = {pool.submit(_fetch_price, s.code): s.code for s in stocks}
                done = 0
                for fut in as_completed(futs, timeout=120):
                    code, df = fut.result()
                    if df is not None:
                        price_map[code] = df
                    done += 1
                    if done % 50 == 0:
                        logger.info("  FDR 가격 다운로드: %d / %d", done, len(stocks))
        except Exception:  # noqa: BLE001
            logger.warning("FDR 가격 다운로드 타임아웃 — %d / %d 종목만 수집됨", len(price_map), len(stocks))
        finally:
            _requests.Session.request = _orig_request  # type: ignore[method-assign]
        logger.info("FDR 가격 수집 완료: %d / %d 종목", len(price_map), len(stocks))

        # KIS API fallback (pykrx 실패 시)
        if not batch_ok:
            codes = [s.code for s in stocks]
            kis_flows = _kis_investor_flow_batch(yyyymmdd, codes)
            if kis_flows:
                batch_flows = kis_flows
                batch_ok = True
                logger.info("KIS API 수급 수집 완료: %d 종목", len(kis_flows))
            else:
                logger.warning("KIS API 실패 — 수급 데이터 없음")

        for stock in stocks:
            df = price_map.get(stock.code)
            if df is None:
                logger.warning("No spot data from FDR for %s on %s", stock.code, date_text)
                continue

            row = df.iloc[-1]
            listing_row = listing.loc[stock.code] if stock.code in listing.index else None
            if listing_row is not None:
                stock.name = str(listing_row.get("Name", stock.name))
                stock.market = str(listing_row.get("Market", stock.market))
                _marcap = listing_row.get("Marcap")
                import math as _math
                if _marcap is not None and not (isinstance(_marcap, float) and _math.isnan(_marcap)):
                    stock.market_cap = float(_marcap)
                elif stock.market_cap is None:
                    stock.market_cap = 0.0
                db.add(stock)

            from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415
            price_vals = dict(
                trading_date=trading_date,
                stock_code=stock.code,
                open_price=float(row["Open"]),
                high_price=float(row["High"]),
                low_price=float(row["Low"]),
                close_price=float(row["Close"]),
                volume=float(row["Volume"]),
                trading_value=float(row["Volume"]) * float(row["Close"]),
                change_pct=round(float(row["Change"]) * 100, 4),
            )
            db.execute(
                pg_insert(SpotDailyPrice).values(**price_vals)
                .on_conflict_do_update(
                    constraint="uq_spot_daily_prices",
                    set_={k: v for k, v in price_vals.items() if k not in ("trading_date", "stock_code")},
                )
            )

            # 수급: pykrx 배치 → KIS API fallback → 0
            if batch_ok and stock.code in batch_flows:
                foreign_net, institution_net, individual_net = batch_flows[stock.code]
            else:
                foreign_net, institution_net, individual_net = 0.0, 0.0, 0.0

            flow_vals = dict(
                trading_date=trading_date,
                stock_code=stock.code,
                foreign_net_buy=foreign_net,
                institution_net_buy=institution_net,
                individual_net_buy=individual_net,
            )
            db.execute(
                pg_insert(SpotInvestorFlow).values(**flow_vals)
                .on_conflict_do_update(
                    constraint="uq_spot_investor_flows",
                    set_={k: v for k, v in flow_vals.items() if k not in ("trading_date", "stock_code")},
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR spot collection failed, falling back to demo data: %s", exc)
        _fallback_spot_row(db, trading_date)
    db.commit()
