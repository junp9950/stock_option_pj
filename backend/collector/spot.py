from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import delete, select
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
                    # _tr_pbmn = 순매수 거래대금(백만원) → 원 변환, 없으면 qty(주) 사용
                    def _won(pbmn_key: str, qty_key: str) -> float:
                        pbmn = row.get(pbmn_key)
                        if pbmn not in (None, "", "0"):
                            return float(pbmn) * 1_000_000
                        return float(row.get(qty_key) or 0)
                    f = _won("frgn_ntby_tr_pbmn", "frgn_ntby_qty")
                    i = _won("orgn_ntby_tr_pbmn", "orgn_ntby_qty")
                    p = _won("prsn_ntby_tr_pbmn", "prsn_ntby_qty")
                    result[code] = (f, i, p)
                    break
            _time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            logger.debug("KIS flow failed for %s: %s", code, exc)

    logger.info("KIS 수급 수집 완료: %d/%d 종목", len(result), len(codes))
    return result


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

    Source: FinanceDataReader for prices, KIS API for investor flow.
    Fallback: demo data generation for local/offline runs.
    """

    # FDR 조회는 마지막 실제 거래일 기준으로 (주말·공휴일 진입 방지)
    fetch_date = latest_trading_day(trading_date)
    if fetch_date != trading_date:
        logger.info("trading_date=%s is non-trading day → fetching data for %s", trading_date, fetch_date)
        trading_date = fetch_date  # 비거래일이면 실제 거래일로 redirect

    try:
        # 종목명/시장/시총 갱신용 부가 정보 — 실패해도 가격·수급 수집 본 기능은 계속 진행.
        # (2026-09-09: fdr.StockListing 원격 CSV가 간헐적으로 404를 반환해 전체 수집이
        # 통째로 멈추는 문제가 있었음 — 이 호출만 실패를 흡수하도록 분리.)
        try:
            listing = _load_listing_snapshot()
        except Exception as exc:  # noqa: BLE001
            logger.warning("종목 리스팅 스냅샷 수집 실패, 이름/시총 갱신 건너뜀: %s", exc)
            listing = None

        date_text = fetch_date.isoformat()
        yyyymmdd = fetch_date.strftime("%Y%m%d")

        # FDR 테스트 수집 — 실패하면 기존 데이터 보존 후 리턴
        test_df = fdr.DataReader("005930", date_text, date_text)
        if test_df.empty:
            logger.warning("FDR 수집 실패 (%s) — 기존 DB 데이터 보존", date_text)
            return

        # FDR 정상 확인 (기존 데이터는 upsert로 덮어씀, DELETE 불필요)

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

        # 수급: KIS API (pykrx는 KRX 로그인 필수화 이후 계속 실패해 2026-10-03 제거)
        batch_flows = _kis_investor_flow_batch(yyyymmdd, [s.code for s in stocks])
        batch_ok = len(batch_flows) > 0
        if batch_ok:
            logger.info("KIS API 수급 수집 완료: %d 종목", len(batch_flows))
        else:
            logger.warning("KIS API 실패 — 수급 데이터 없음")

        for stock in stocks:
            df = price_map.get(stock.code)
            if df is None:
                logger.warning("No spot data from FDR for %s on %s", stock.code, date_text)
                continue

            row = df.iloc[-1]
            # sanity check: FDR 병렬 수집 중 간헐적으로 완전히 다른 종목의 OHLCV가 섞여 반환되는
            # 사례가 있었음 (2026-09-08, 003490/028050/036930에서 확인) — 하루 등락률이
            # KRX 상한(±30%)을 크게 벗어나면 오염된 데이터로 간주하고 skip.
            import math as _math
            change_raw = float(row["Change"])
            # 신규상장 첫날처럼 전일 종가가 없으면 FDR이 NaN을 준다 — NaN은 abs() 비교를 통과해버리므로 0으로 저장
            change_check = round(change_raw * 100, 4) if _math.isfinite(change_raw) else 0.0
            if abs(change_check) > 50:
                logger.warning(
                    "FDR %s close_price sanity fail (change=%.1f%%), skip: %s",
                    stock.code, change_check, date_text,
                )
                continue
            listing_row = listing.loc[stock.code] if listing is not None and stock.code in listing.index else None
            if listing_row is not None:
                stock.name = str(listing_row.get("Name", stock.name))
                stock.market = str(listing_row.get("Market", stock.market))
                _marcap = listing_row.get("Marcap")
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
                change_pct=change_check,
            )
            db.execute(
                pg_insert(SpotDailyPrice).values(**price_vals)
                .on_conflict_do_update(
                    constraint="uq_spot_daily_prices",
                    set_={k: v for k, v in price_vals.items() if k not in ("trading_date", "stock_code")},
                )
            )

            # 수급: KIS API → 실패 시 0
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


def collect_sector_supplement(db: Session, trading_date: date) -> int:
    """유니버스 밖 섹터 종목의 수급·가격 데이터를 KIS + FDR로 보완 수집.

    섹터 분석에 필요하지만 시총 상위 유니버스에 없는 종목을 추가 수집한다.
    이미 수집된 종목은 건너뛴다.
    Returns: 새로 수집한 종목 수
    """
    import time as _time  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415
    from backend.db.models import SectorStock, Stock  # noqa: PLC0415

    yyyymmdd = trading_date.strftime("%Y%m%d")

    # 섹터에 속한 전체 종목 코드
    sector_codes = {
        r.stock_code
        for r in db.scalars(select(SectorStock))
    }
    if not sector_codes:
        return 0

    # 장중(15:30 전)에 미리 들어간 오늘 행은 장중 시세라 다시 받는다 (2026-10-06 발견: 서버 재시작 때 장중 시세가 오늘 행으로
    # 들어가면 15:41 수집이 '이미 수집됨'으로 건너뛰어 섹터 종목 2천여 개가 다음 날 아침까지 장중 값으로 남았다)
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
    from zoneinfo import ZoneInfo as _Z  # noqa: PLC0415
    close_utc = _dt(trading_date.year, trading_date.month, trading_date.day, 15, 30, tzinfo=_Z("Asia/Seoul")).astimezone(_tz.utc).replace(tzinfo=None)
    if _dt.now(_tz.utc).replace(tzinfo=None) >= close_utc:
        stale = db.execute(
            delete(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == trading_date,
                                           SpotInvestorFlow.created_at < close_utc,
                                           SpotInvestorFlow.stock_code.in_(sector_codes),
                                           SpotInvestorFlow.stock_code.not_in(select(Stock.code).where(Stock.is_active)))
        ).rowcount
        db.commit()
        if stale:
            logger.info("Sector supplement: 장중에 들어간 오늘 행 %d개를 종가로 다시 받습니다", stale)

    # 이미 수집된 종목 코드
    existing_flow = {
        r.stock_code
        for r in db.scalars(
            select(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == trading_date)
        )
    }
    missing = sorted(sector_codes - existing_flow)

    # Stock 테이블에 없는 섹터 종목 이름을 FDR에서 가져와 upsert (is_active=False로 유니버스 제외)
    existing_stock_codes = {
        r.code for r in db.scalars(select(Stock).where(Stock.code.in_(sector_codes)))
    }
    name_missing = sorted(sector_codes - existing_stock_codes)
    if name_missing:
        try:
            name_map: dict[str, tuple[str, str]] = {}  # code -> (name, market)
            for market in ("KOSPI", "KOSDAQ"):
                lst = fdr.StockListing(market)
                lst["Code"] = lst["Code"].astype(str).str.zfill(6)
                for _, row in lst.iterrows():
                    name_map[row["Code"]] = (str(row.get("Name", row.get("종목명", ""))), market)
            for code in name_missing:
                if code in name_map:
                    n, mkt = name_map[code]
                    db.execute(
                        pg_insert(Stock)
                        .values(code=code, name=n, market=mkt, market_cap=0.0, is_active=False)
                        .on_conflict_do_update(
                            index_elements=["code"],
                            set_={"name": n, "market": mkt},
                        )
                    )
            db.commit()
            logger.info("Sector supplement: upserted %d stock names into Stock table", len(name_missing))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sector supplement: stock name upsert failed: %s", exc)

    if not missing:
        logger.info("Sector supplement: all %d sector stocks already collected", len(sector_codes))
        return 0

    logger.info("Sector supplement: collecting %d stocks not in universe", len(missing))

    token = _get_kis_token()
    if not token:
        logger.warning("Sector supplement: KIS token unavailable, skipping")
        return 0

    import os as _os, requests as _req  # noqa: PLC0415
    app_key = _os.getenv("KIS_APP_KEY", "")
    app_secret = _os.getenv("KIS_APP_SECRET", "")
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900",
        "content-type": "application/json",
    }

    # FDR로 가격 일괄 조회
    try:
        prices_df = fdr.DataReader(",".join(missing), trading_date, trading_date)
    except Exception:  # noqa: BLE001
        prices_df = None

    collected = 0
    for code in missing:
        try:
            # KIS 수급 조회
            r = _req.get(
                "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor",
                headers=headers,
                params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code},
                timeout=5,
            )
            rows = r.json().get("output", [])
            foreign_net = inst_net = 0.0
            for row in rows:
                if row.get("stck_bsop_date") == yyyymmdd:
                    def _won(pbmn_key: str, qty_key: str) -> float:
                        v = row.get(pbmn_key)
                        if v not in (None, "", "0"):
                            return float(v) * 1_000_000
                        return float(row.get(qty_key) or 0)
                    foreign_net = _won("frgn_ntby_tr_pbmn", "frgn_ntby_qty")
                    inst_net = _won("orgn_ntby_tr_pbmn", "orgn_ntby_qty")
                    break

            flow_vals = dict(
                trading_date=trading_date,
                stock_code=code,
                foreign_net_buy=foreign_net,
                institution_net_buy=inst_net,
                individual_net_buy=0.0,
            )
            db.execute(
                pg_insert(SpotInvestorFlow).values(**flow_vals)
                .on_conflict_do_update(
                    constraint="uq_spot_investor_flows",
                    set_={k: v for k, v in flow_vals.items() if k not in ("trading_date", "stock_code")},
                )
            )

            # FDR 가격 (있으면)
            try:
                price_row = fdr.DataReader(code, trading_date, trading_date)
                if not price_row.empty:
                    pr = price_row.iloc[-1]
                    close_val = float(pr.get("Close", 0))
                    import math as _math
                    change_raw = float(pr.get("Change", 0))
                    change_val = round(change_raw * 100, 4) if _math.isfinite(change_raw) else 0.0  # 신규상장 첫날 NaN
                    # sanity check: change_pct 이 ±50% 초과하면 FDR 오류로 간주하고 skip
                    if abs(change_val) > 50:
                        logger.warning("Sector supplement: %s close_price sanity fail (change=%.1f%%), skip", code, change_val)
                        raise ValueError("sanity fail")
                    price_vals = dict(
                        trading_date=trading_date,
                        stock_code=code,
                        open_price=float(pr.get("Open", 0)),
                        high_price=float(pr.get("High", 0)),
                        low_price=float(pr.get("Low", 0)),
                        close_price=close_val,
                        volume=float(pr.get("Volume", 0)),
                        trading_value=float(pr.get("Volume", 0)) * close_val,
                        change_pct=change_val,
                    )
                    db.execute(
                        pg_insert(SpotDailyPrice).values(**price_vals)
                        .on_conflict_do_update(
                            constraint="uq_spot_daily_prices",
                            set_={k: v for k, v in price_vals.items() if k not in ("trading_date", "stock_code")},
                        )
                    )
            except Exception:  # noqa: BLE001
                pass

            collected += 1
            _time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Sector supplement failed for %s: %s", code, exc)

    db.commit()
    logger.info("Sector supplement done: %d/%d stocks collected", collected, len(missing))
    return collected


def refresh_spot_prices(db: Session, start: date, end: date) -> dict:
    """이미 저장된 start~end 시세(OHLCV)를 FDR 확정치로 다시 덮어쓴다. 수급은 건드리지 않는다.

    2026-09-14부터 15:41·18:00 수집분이 NXT 시간외(~20:00) 진행 중 값이라 종목의 약 40%가 공식 종가와
    어긋났다(대부분 0.2~2%, 큰 것은 6%). 다음 날 아침에 받으면 확정치가 나오므로 매일 아침 최근 며칠을 바로잡는다.
    """
    from sqlalchemy import text  # noqa: PLC0415
    import math as _math  # noqa: PLC0415

    existing: dict[str, dict[date, float]] = {}
    for code, d, close in db.execute(
        text("select stock_code, trading_date, close_price from spot_daily_prices where trading_date between :s and :e"),
        {"s": start, "e": end},
    ):
        existing.setdefault(code, {})[d] = float(close or 0)

    def _fetch(code: str):
        try:
            return code, fdr.DataReader(code, start.isoformat(), end.isoformat())
        except Exception:  # noqa: BLE001
            return code, None

    fixed = checked = failed = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for code, df in pool.map(_fetch, list(existing)):
            if df is None or df.empty:
                failed += 1
                continue
            for ts, row in df.iterrows():
                d = ts.date()
                if d not in existing[code]:
                    continue
                checked += 1
                close = float(row["Close"])
                change_raw = float(row["Change"])
                change = round(change_raw * 100, 4) if _math.isfinite(change_raw) else 0.0
                if close <= 0 or abs(change) > 50 or abs(existing[code][d] / close - 1) < 1e-6:
                    continue
                db.execute(
                    text("update spot_daily_prices set open_price=:o, high_price=:h, low_price=:l, close_price=:c, "
                         "volume=:v, trading_value=:tv, change_pct=:chg where stock_code=:code and trading_date=:d"),
                    {"o": float(row["Open"]), "h": float(row["High"]), "l": float(row["Low"]), "c": close,
                     "v": float(row["Volume"]), "tv": float(row["Volume"]) * close, "chg": change, "code": code, "d": d},
                )
                fixed += 1
    if fixed:   # 작업 로그를 남기면 result_cache의 데이터 버전이 바뀌어 화면 결과도 다시 계산된다
        from backend.db.models import JobLog  # noqa: PLC0415
        db.add(JobLog(trading_date=end, stage="spot_price_fix", status="completed",
                      message=f"시세 확정치 재수집 {start}~{end}: {fixed}건 수정"))
    db.commit()
    logger.info("시세 확정치 재수집 %s~%s: 확인 %d건, 수정 %d건, 실패 종목 %d", start, end, checked, fixed, failed)
    return {"checked": checked, "fixed": fixed, "failed": failed}


def sync_stock_names(db: Session) -> int:
    """종목 이름 바뀐 것 맞추기 (KRX 상장 목록 기준, 매일 아침). 2026-10-06: 세아메카닉스→HT로보틱스 등 18개가 옛 이름으로 남아 있었다."""
    listing = _load_listing_snapshot()
    names = listing["Name"].astype(str).to_dict()
    n = 0
    for st in db.scalars(select(Stock)):
        new = names.get(st.code)
        if new and new != "nan" and new != st.name:
            logger.info("종목 이름 변경: %s %s → %s", st.code, st.name, new)
            st.name = new
            n += 1
    db.commit()
    return n
