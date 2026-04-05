"""
가격 기반 히스토리컬 백테스트.

FDR 가격 데이터만으로 RSI / MACD / MA / 거래량 / 모멘텀 신호를 계산하고
T+1 수익률을 검증한다. 기관·공매도 데이터 없이도 수 개월치 백테스트 가능.

개선사항:
  A. 최소 점수 필터  : 일별 top-N 중 점수 < MIN_SCORE 이면 그날 진입 스킵
  B. 시장 필터       : KOSPI200 종가가 20일 이동평균선 아래면 그날 전체 스킵
  C. RSI 추세추종    : 과매도 반등(역추세) → RSI 상승 추세(모멘텀) 방식으로 전환
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.db.models import Stock
from backend.utils.dates import is_trading_day
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# ── 파라미터 ──────────────────────────────────────────────────────────────────
MIN_SCORE = 0.05          # A. 이 점수 미만이면 그날 진입 안 함
MARKET_FILTER_MA = 20     # B. KOSPI200 n일선 아래면 스킵
KOSPI200_CODE = "KS200"   # FinanceDataReader KOSPI200 코드


# ── 기술지표 계산 ─────────────────────────────────────────────────────────────

def _rsi(prices: pd.Series, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    delta = prices.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_loss = loss.iloc[-1]
    rs = gain.iloc[-1] / last_loss if last_loss > 1e-9 else 1e9
    return float(100 - 100 / (1 + rs))


def _rsi_momentum(prices: pd.Series, period: int = 14, lookback: int = 3) -> float:
    """C. RSI 추세추종: 최근 RSI가 상승 추세이고 40~70 구간이면 양수 점수.
    (기존: 과매도일수록 높음 → 변경: RSI가 올라가는 추세일수록 높음)
    """
    if len(prices) < period + lookback + 2:
        return 0.0
    rsi_now = _rsi(prices, period)
    rsi_prev = _rsi(prices.iloc[:-lookback], period)
    rsi_delta = rsi_now - rsi_prev  # 양수 = RSI 상승 중

    # RSI가 40~75 구간에서 상승 중이면 가장 좋음 (과매수 영역은 페널티)
    if rsi_now > 75:
        zone = -0.5
    elif rsi_now < 30:
        zone = -0.3  # 하락 추세 중 과매도 → 역추세 리스크
    else:
        zone = 0.0

    trend_s = min(max(rsi_delta / 10, -1.0), 1.0)  # 10pt 상승이면 +1.0
    return trend_s + zone


def _macd_diff(prices: pd.Series) -> float:
    if len(prices) < 27:
        return 0.0
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1] - signal.iloc[-1])


def _ma_score(prices: pd.Series) -> float:
    close = prices.iloc[-1]
    score = 0.0
    if len(prices) >= 20:
        score += 0.5 if close > prices.rolling(20).mean().iloc[-1] else -0.5
    if len(prices) >= 60:
        score += 0.5 if close > prices.rolling(60).mean().iloc[-1] else -0.5
    return score  # -1.0 ~ 1.0


def _vol_surge(volumes: pd.Series) -> float:
    if len(volumes) < 20:
        return 1.0
    avg = volumes.rolling(20).mean().iloc[-1]
    return float(volumes.iloc[-1] / avg) if avg > 0 else 1.0


def _momentum(prices: pd.Series, days: int = 5) -> float:
    if len(prices) < days + 1:
        return 0.0
    return float(prices.iloc[-1] / prices.iloc[-(days + 1)] - 1)


def _score(prices: pd.Series, volumes: pd.Series) -> float:
    """종합 점수 (-1 ~ 1). RSI는 추세추종 방식으로 계산."""
    rsi_s = _rsi_momentum(prices)           # C. 추세추종 RSI
    rsi_s = min(max(rsi_s, -1.0), 1.0)

    macd = _macd_diff(prices)
    macd_s = min(max(macd / (prices.iloc[-1] * 0.01 + 1e-9), -1.0), 1.0)

    ma_s = _ma_score(prices)

    surge = _vol_surge(volumes)
    vol_s = min((surge - 1.0) / 2.0, 1.0)

    mom = _momentum(prices)
    mom_s = min(max(mom * 10, -1.0), 1.0)

    return (
        rsi_s  * 0.20 +
        macd_s * 0.20 +
        ma_s   * 0.25 +
        vol_s  * 0.15 +
        mom_s  * 0.20
    )


# ── 시장 필터 ─────────────────────────────────────────────────────────────────

def _fetch_kospi200(fetch_start: date, fetch_end: date) -> Optional[pd.DataFrame]:
    """B. KOSPI200 가격 다운로드."""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        df = fdr.DataReader(KOSPI200_CODE, fetch_start.isoformat(), fetch_end.isoformat())
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df[["Close"]].copy()
    except Exception as exc:  # noqa: BLE001
        logger.warning("KOSPI200 fetch failed (시장 필터 비활성화): %s", exc)
        return None


def _market_is_bullish(kospi200: Optional[pd.DataFrame], sig_ts: pd.Timestamp) -> bool:
    """B. 신호일 기준 KOSPI200 종가 > 20일 MA이면 True (상승장)."""
    if kospi200 is None:
        return True  # 데이터 없으면 필터 패스
    hist = kospi200[kospi200.index <= sig_ts]
    if len(hist) < MARKET_FILTER_MA:
        return True
    ma = hist["Close"].rolling(MARKET_FILTER_MA).mean().iloc[-1]
    return float(hist["Close"].iloc[-1]) > float(ma)


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

def _fetch_price(code: str, fetch_start: date, fetch_end: date) -> Optional[pd.DataFrame]:
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        df = fdr.DataReader(code, fetch_start.isoformat(), fetch_end.isoformat())
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df[["Close", "Volume"]].copy()
    except Exception as exc:  # noqa: BLE001
        logger.debug("FDR failed for %s: %s", code, exc)
        return None


def _get_trading_days(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


# ── 메인 백테스트 ─────────────────────────────────────────────────────────────

def run_historical_backtest(
    db: Session,
    start_date: date,
    end_date: date,
    top_n: int = 5,
    fee_rate: float = 0.00015,
    slippage: float = 0.0005,
    max_workers: int = 8,
) -> dict:
    """
    start_date ~ end_date 기간 동안 매일 top_n 종목 T+1 전략 백테스트.

    개선:
      A. 최소 점수 필터 (MIN_SCORE 이상인 날만 진입)
      B. 시장 필터 (KOSPI200 > 20일선인 날만 진입)
      C. RSI 추세추종 방식

    Returns:
        win_rate, avg_return, sharpe, cumulative_return, daily_results 등
    """
    # 유니버스 로드
    from sqlalchemy import select  # noqa: PLC0415
    stocks = list(db.scalars(select(Stock)))
    if not stocks:
        return {"error": "종목 없음"}

    code_to_name: dict[str, str] = {s.code: s.name for s in stocks}

    # 지표 계산 워밍업을 위해 시작일 90일 전부터 가격 다운로드
    fetch_start = start_date - timedelta(days=90)

    logger.info(
        "히스토리컬 백테스트 시작: %s ~ %s, 종목 %d개 (필터: 최소점수=%.2f, 시장필터=MA%d, RSI=추세추종)",
        start_date, end_date, len(stocks), MIN_SCORE, MARKET_FILTER_MA,
    )

    # ── 병렬로 가격 데이터 + KOSPI200 다운로드
    price_data: dict[str, pd.DataFrame] = {}

    def _load(stock: Stock) -> tuple[str, Optional[pd.DataFrame]]:
        return stock.code, _fetch_price(stock.code, fetch_start, end_date)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_load, s): s.code for s in stocks}
        done = 0
        for fut in as_completed(futures):
            code, df = fut.result()
            if df is not None and not df.empty:
                price_data[code] = df
            done += 1
            if done % 20 == 0:
                logger.info("가격 다운로드 진행: %d / %d", done, len(stocks))

    # B. KOSPI200 다운로드
    kospi200 = _fetch_kospi200(fetch_start, end_date)
    if kospi200 is not None:
        logger.info("KOSPI200 시장 필터 활성화")
    else:
        logger.warning("KOSPI200 로드 실패 → 시장 필터 비활성화")

    logger.info("가격 다운로드 완료: %d 종목", len(price_data))

    # ── 거래일 목록
    trading_days = _get_trading_days(start_date, end_date)
    if len(trading_days) < 2:
        return {"error": "거래일 부족 (최소 2일 필요)"}

    # ── 날짜별 시뮬레이션
    daily_results = []
    all_returns: list[float] = []
    skipped_market = 0
    skipped_score = 0

    for i, signal_date in enumerate(trading_days[:-1]):  # 마지막 날은 T+1 없음
        next_date = trading_days[i + 1]
        sig_ts = pd.Timestamp(signal_date)
        next_ts = pd.Timestamp(next_date)

        # B. 시장 필터: 하락장이면 스킵
        if not _market_is_bullish(kospi200, sig_ts):
            skipped_market += 1
            continue

        # 신호일 기준 점수 계산
        scored: list[tuple[float, str]] = []
        for code, df in price_data.items():
            hist = df[df.index <= sig_ts]
            if len(hist) < 20:
                continue
            if sig_ts not in hist.index:
                continue
            s = _score(hist["Close"], hist["Volume"])
            scored.append((s, code))

        if not scored:
            continue

        scored.sort(reverse=True)

        # A. 최소 점수 필터: top-1 점수가 MIN_SCORE 미만이면 그날 스킵
        if scored[0][0] < MIN_SCORE:
            skipped_score += 1
            continue

        # MIN_SCORE 이상인 종목만 선택 (최대 top_n)
        selected = [code for s, code in scored if s >= MIN_SCORE][:top_n]

        # T+1 수익률 계산
        returns = []
        for code in selected:
            df = price_data.get(code)
            if df is None:
                continue
            if sig_ts not in df.index or next_ts not in df.index:
                continue
            entry = float(df.loc[sig_ts, "Close"])
            exit_p = float(df.loc[next_ts, "Close"])
            if entry <= 0:
                continue
            net = (exit_p - entry) / entry - (fee_rate + slippage) * 2
            returns.append(net)

        if not returns:
            continue

        avg = sum(returns) / len(returns)
        wr = sum(1 for r in returns if r > 0) / len(returns)
        all_returns.extend(returns)
        daily_results.append({
            "date": signal_date.isoformat(),
            "avg_return_pct": round(avg * 100, 3),
            "win_rate_pct": round(wr * 100, 1),
            "count": len(returns),
            "top_stocks": [code_to_name.get(c, c) for c in selected],
        })

    logger.info(
        "시뮬레이션 완료: 진입 %d일, 시장필터 스킵 %d일, 점수필터 스킵 %d일",
        len(daily_results), skipped_market, skipped_score,
    )

    # ── 최종 집계
    if not all_returns:
        return {"error": "수익률 계산 가능한 날짜 없음 (필터 조건이 너무 엄격할 수 있습니다)"}

    avg_ret = sum(all_returns) / len(all_returns)
    win_rate = sum(1 for r in all_returns if r > 0) / len(all_returns)

    # 날짜별 포트폴리오 평균 수익률 (복리 누적)
    daily_avg_returns = [dr["avg_return_pct"] / 100 for dr in daily_results]

    compound = 1.0
    cum_curve = []
    peak = 1.0
    max_dd = 0.0
    for r in daily_avg_returns:
        compound *= (1 + r)
        if compound > peak:
            peak = compound
        dd = (peak - compound) / peak
        if dd > max_dd:
            max_dd = dd
        cum_curve.append(round((compound - 1) * 100, 3))

    cumulative = compound - 1

    # 샤프: 일별 평균수익률 기준
    if len(daily_avg_returns) > 1:
        mean_d = sum(daily_avg_returns) / len(daily_avg_returns)
        variance = sum((r - mean_d) ** 2 for r in daily_avg_returns) / (len(daily_avg_returns) - 1)
        std = math.sqrt(variance)
        sharpe = (mean_d / std * math.sqrt(252)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    logger.info(
        "백테스트 완료: 승률=%.1f%%, 평균수익=%.3f%%, 샤프=%.2f, 누적=%.1f%%",
        win_rate * 100, avg_ret * 100, sharpe, cumulative * 100,
    )

    return {
        "period": f"{start_date.isoformat()} ~ {end_date.isoformat()}",
        "trading_days": len(trading_days),
        "simulated_days": len(daily_results),
        "skipped_market_filter": skipped_market,
        "skipped_score_filter": skipped_score,
        "total_trades": len(all_returns),
        "top_n": top_n,
        "filters": {
            "min_score": MIN_SCORE,
            "market_filter_ma": MARKET_FILTER_MA,
            "rsi_mode": "추세추종",
        },
        "metrics": {
            "win_rate_pct": round(win_rate * 100, 1),
            "avg_return_pct": round(avg_ret * 100, 3),
            "cumulative_return_pct": round(cumulative * 100, 2),
            "sharpe": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
        },
        "cumulative_curve": cum_curve,
        "daily_results": daily_results,
    }
