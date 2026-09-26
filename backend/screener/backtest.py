"""눌림목 레이더 백테스트.

레이더 화면과 같은 기준: 매 거래일 이벤트 판정·신호점수·눌림목 품질을 레이더 함수 그대로 다시 계산해
종합점수(신호 60% + 품질 40%, 눌림목 미해당이면 신호점수)가 기준을 처음 넘은 날 다음날 시가에 진입한다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock
from backend.screener.market_regime import regime_series
from backend.screener.pullback_scanner import MAX_DAYS_SINCE_SPIKE, detect_pullback
from backend.screener.volume_anomaly import (
    _DUMP_PCT,
    _LOOKBACK_DAYS,
    _MAX_NEXT_DAY_DROP,
    _MAX_REBOUND,
    _MAX_VWAP_GAP,
    _MIN_AVG_TRADING_VALUE,
    _ROUND_TRIP,
    _calc_score,
    _find_events,
    _market_stats,
    _pre_event_vol_trend,
)

# 레이더의 눌림목 스캐너가 보는 과거 구간과 동일 (scan_pullback_candidates의 history_start)
_PULLBACK_HISTORY_DAYS = int((MAX_DAYS_SINCE_SPIKE + 30) * 1.6)

_POSITION_SIZE = 2_000_000
_COMMISSION_PCT = 0.25
_TIMEOUT_DAYS = 20
_MIN_BARS_SINCE = 2
_TRAILING_STOP_PCT = 7.0
_TRAILING_MIN_HOLD = 5  # 3일보다 5일이 65+/75+ 모두 우세 (트레일링이 초반 흔들림에 털리는 것 방지)


@dataclass
class TradeResult:
    code: str
    name: str
    score: int
    bars_since: int
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    pnl_pct: float
    pnl_krw: float
    hold_days: int
    features: dict


def run_backtest(db: Session, lookback_months: int = 6, min_score: int = 60, min_market_cap: float = 100_000_000_000) -> dict:
    from_date = date.today() - timedelta(days=lookback_months * 30 + 90)

    rows = db.execute(
        select(
            SpotDailyPrice.stock_code,
            SpotDailyPrice.trading_date,
            SpotDailyPrice.open_price,
            SpotDailyPrice.high_price,
            SpotDailyPrice.low_price,
            SpotDailyPrice.close_price,
            SpotDailyPrice.volume,
            SpotDailyPrice.trading_value,
            SpotDailyPrice.change_pct,
            Stock.name,
            Stock.market_cap,
            Stock.shares_outstanding,
        )
        .join(Stock, Stock.code == SpotDailyPrice.stock_code)
        .where(SpotDailyPrice.trading_date >= from_date)
        .order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date)
    ).all()

    by_code: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    for r in rows:
        by_code[r.stock_code].append(r)
        meta[r.stock_code] = {"name": r.name, "market_cap": r.market_cap, "shares_outstanding": r.shares_outstanding or 0}

    market_mult, market_chg = _market_stats(by_code)
    regime = regime_series(market_chg)

    signal_start = date.today() - timedelta(days=lookback_months * 30)
    total_events = 0
    best_scores: list[int] = []
    candidates: list[dict] = []
    skipped = defaultdict(int)

    for code, price_list in by_code.items():
        if len(price_list) < 30:
            continue
        m = meta[code]
        mcap = m["market_cap"] or m["shares_outstanding"] * price_list[-1].close_price
        if mcap < min_market_cap:
            continue

        # 이벤트 판정은 레이더 함수 그대로 (유통주식 대비 거래량 조건 포함)
        events = _find_events(price_list, signal_start - timedelta(days=_LOOKBACK_DAYS), m["shares_outstanding"], market_mult)
        total_events += sum(1 for e in events if e["date"] >= signal_start)
        for ev in events:
            if ev["date"] < signal_start:
                continue  # 기간 이전 이벤트는 왕복 판정용으로만 씀
            sig, best = _first_qualifying_day(price_list, ev, events, market_chg, regime, min_score, skipped)
            best_scores.append(best)
            if sig:
                sig["code"] = code
                sig["name"] = m["name"]
                candidates.append(sig)

    candidates.sort(key=lambda x: (x["entry_date"], -x["score"]))

    win_rate_stats = _calc_win_rates(candidates)
    trades = _simulate_trades(candidates)
    trade_stats = _calc_trade_stats(trades)

    return {
        "total_signals": total_events,
        "filtered_signals": len(candidates),
        "tradeable_signals": len(candidates),
        "market_skipped": skipped["market"],
        "min_score": min_score,
        "period": f"{signal_start.isoformat()} ~ {date.today().isoformat()}",
        "win_rate": win_rate_stats,
        "trades": trade_stats,
        "trade_list": [_trade_to_dict(t) for t in trades],
        "monthly": _monthly_breakdown(trades),
        "score_distribution": _score_distribution(best_scores),
        "feature_analysis": _analyze_features(trades),
        "bars_since_breakdown": _bars_since_breakdown(trades),
        "notes": [
            f"시총 {min_market_cap/1e8:,.0f}억+ · 이벤트 {total_events}건 중 종합점수 {min_score}점을 넘은 {len(candidates)}건 진입",
            f"레이더 화면과 동일한 종합점수(신호 60% + 눌림목 품질 40%)로 이벤트 후 {_MIN_BARS_SINCE}~{_LOOKBACK_DAYS}일 매일 재채점, 기준 첫 통과일 다음날 시가 진입",
            f"진입일 시가가 세력 평단(VWAP) 대비 +{_MAX_VWAP_GAP:.0f}% 넘게 갭상승하면 추격 매수 안 함",
            f"시장 하락(전종목 평균 지수 < 20일선, 전일 마감 기준)이면 진입 보류 ({skipped['market']}회)",
            f"트레일링 스탑: {_TRAILING_MIN_HOLD}일 보유 후 고점 대비 -{_TRAILING_STOP_PCT}% · 손절 이벤트 몸통 하단 · 타임아웃 {_TIMEOUT_DAYS}일",
            "같은 종목은 보유 중 중복 진입 안 함",
            f"수수료+세금 {_COMMISSION_PCT}% · 갭하락 시가 체결",
            "생존자 편향 주의: DB에 남아있는 종목만, 시총은 현재 기준",
        ],
    }


# ── 매일 재채점 ──

def _round_trips(price_list: list, events: list, ref_date: date, idx: int) -> int:
    """레이더와 같은 방식: 그날 기준 최근 40일 안의 이벤트들을 순서대로 보고, 이벤트 사이에 10% 넘게 빠졌던 횟수."""
    window = sorted((e for e in events if e["idx"] <= idx and (ref_date - e["date"]).days <= _LOOKBACK_DAYS), key=lambda e: e["idx"])
    n = 0
    for a, b in zip(window, window[1:]):
        seg = price_list[a["idx"] + 1: b["idx"]]
        if seg and min(x.close_price for x in seg) < price_list[a["idx"]].close_price * _ROUND_TRIP:
            n += 1
    return n


def _pullback_quality(price_list: list, ref: int) -> float | None:
    """레이더의 눌림목 스캐너를 그날 시점 데이터로 돌린 품질점수(0~1). 눌림목 패턴이 아니면 None."""
    ref_date = price_list[ref].trading_date
    start = ref_date - timedelta(days=_PULLBACK_HISTORY_DAYS)
    hist = [p for p in price_list[max(0, ref - 80): ref + 1] if p.trading_date >= start][::-1]
    result = detect_pullback(hist)
    return result["quality_score"] if result else None


def _first_qualifying_day(
    price_list: list, ev: dict, events: list, market_chg: dict, regime: dict,
    min_score: int, skipped: dict,
) -> tuple[dict | None, int]:
    """이벤트 이후 매일 레이더와 같은 방식으로 채점. 기준을 처음 넘는 날의 신호와 최고 점수를 반환."""
    idx = ev["idx"]
    event_day = price_list[idx]
    vwap = event_day.trading_value / event_day.volume if event_day.volume else event_day.close_price
    stop_price = min(event_day.open_price, event_day.close_price)
    event_close = event_day.close_price
    best = 0

    # 다음날 큰 음봉 = 분배 (진입 시점엔 이미 아는 정보라 미래 참조 아님)
    if idx + 1 < len(price_list) and float(price_list[idx + 1].change_pct or 0) <= _MAX_NEXT_DAY_DROP:
        return None, best

    # 이후 이벤트가 새로 나오면 레이더는 최신 이벤트로 갈아타므로 그 전날까지만 본다
    later = [e["idx"] for e in events if e["idx"] > idx]
    last_ref = min(later) - 1 if later else len(price_list) - 1
    pre_trend = _pre_event_vol_trend(price_list, idx)

    for ref in range(idx + _MIN_BARS_SINCE, last_ref + 1):
        bars_since = ref - idx
        if (price_list[ref].trading_date - ev["date"]).days > _LOOKBACK_DAYS:
            break
        if ref + 1 >= len(price_list):
            break
        seen = price_list[: ref + 1]
        post = price_list[idx + 1: ref + 1]
        current = seen[-1].close_price

        if current < stop_price:
            break  # 손절선 이탈 = 이 이벤트는 끝

        recent_tv = [p.trading_value for p in seen[-5:] if p.trading_value]
        if (sum(recent_tv) / len(recent_tv) if recent_tv else 0) < _MIN_AVG_TRADING_VALUE:
            continue

        vwap_gap = (current - vwap) / vwap * 100 if vwap > 0 else 0
        if vwap_gap > _MAX_VWAP_GAP:
            continue
        if len(seen) >= 3 and all(float(p.change_pct or 0) > 0 for p in seen[-3:]):
            continue
        post_low_close = min(p.close_price for p in post)
        if post_low_close > 0 and (current - post_low_close) / post_low_close * 100 > _MAX_REBOUND:
            continue

        retrace_pct = (event_close - current) / event_close * 100 if event_close > 0 else 0
        recent_vols = [p.volume for p in seen[-5:] if p.volume]
        vol_ratio = (sum(recent_vols) / len(recent_vols)) / event_day.volume if recent_vols and event_day.volume else 1.0

        round_trips = _round_trips(price_list, events, seen[-1].trading_date, idx)
        cutoff = seen[-1].trading_date - timedelta(days=_LOOKBACK_DAYS)
        dump_days = sum(
            1 for p in seen
            if p.trading_date >= cutoff
            and float(p.change_pct or 0) - market_chg.get(p.trading_date, 0.0) <= -_DUMP_PCT
        )

        post_low = min(p.low_price for p in post)
        low_touch_dist = (post_low - stop_price) / stop_price * 100 if stop_price > 0 else 10.0
        a, b = seen[-2], seen[-1]
        mixed_color = (a.close_price > a.open_price) != (b.close_price > b.open_price)

        score, reasons = _calc_score(
            round_trips=round_trips, dump_days=dump_days, bars_since=bars_since,
            vwap_gap=vwap_gap, vol_ratio=vol_ratio, retrace_pct=retrace_pct,
            vol_multiplier=ev["vol_multiplier"],
            low_touch_dist=low_touch_dist, mixed_color=mixed_color,
            pre_event_vol_trend=pre_trend,
        )
        # 종합점수: 눌림목이면 신호 60% + 품질 40%, 아니면 신호점수 그대로 (레이더 화면과 동일)
        if max(score, 0.6 * score + 40) < min_score:
            best = max(best, score)
            continue  # 품질이 만점이어도 기준 미달이면 품질 계산 생략
        quality = _pullback_quality(price_list, ref)
        total = round(0.6 * score + 0.4 * quality * 100) if quality is not None else score
        best = max(best, total)
        if total < min_score:
            continue

        entry_day = price_list[ref + 1]
        # 시가 진입이라 판단은 전일(ref) 장 마감 기준으로만
        if regime.get(seen[-1].trading_date, {}).get("state") == "하락":
            skipped["market"] += 1
            continue
        if entry_day.open_price and vwap > 0 and (entry_day.open_price - vwap) / vwap * 100 > _MAX_VWAP_GAP:
            continue

        return {
            "event_date": ev["date"],
            "score": total,
            "signal_score": score,
            "quality_score": quality,
            "reasons": reasons,
            "bars_since": bars_since,
            "stop_price": stop_price,
            "vwap": vwap,
            "entry_date": entry_day.trading_date,
            "future": price_list[ref + 1:],
            "features": {
                "signal_score": score,
                "pullback_quality": round(quality * 100) if quality is not None else -1,
                "bars_since": bars_since,
                "pre_event_vol_trend": round(pre_trend, 2),
                "event_volatility": round((event_day.high_price - event_day.low_price) / event_close * 100, 2) if event_close else 0,
                "vwap_gap": round(vwap_gap, 2),
                "vol_ratio": round(vol_ratio, 2),
                "retrace_pct": round(retrace_pct, 2),
                "low_touch_dist_pct": round(low_touch_dist, 2),
                "vol_multiplier": round(ev["vol_multiplier"], 1),
                "mixed_color": mixed_color,
            },
        }, best
    return None, best


# ── 승률 검증 ──

def _calc_win_rates(signals: list[dict]) -> dict:
    results = {}
    for n in (5, 10, 20):
        returns = []
        for sig in signals:
            future = sig["future"]
            if len(future) < n or not future[0].open_price:
                continue
            ret = (future[n - 1].close_price - future[0].open_price) / future[0].open_price * 100 - _COMMISSION_PCT
            returns.append(ret)
        if not returns:
            results[f"{n}d"] = {"count": 0, "win_rate": 0, "avg_return": 0, "median_return": 0, "max_gain": 0, "max_loss": 0}
            continue
        s = sorted(returns)
        mid = len(s) // 2
        median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
        results[f"{n}d"] = {
            "count": len(returns),
            "win_rate": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            "avg_return": round(sum(returns) / len(returns), 2),
            "median_return": round(median, 2),
            "max_gain": round(max(returns), 2),
            "max_loss": round(min(returns), 2),
        }
    return results


# ── 모의 매매 ──

def _exit_trade(future: list, stop: float, entry_price: float | None = None) -> tuple[float, str, date, int, bool]:
    """청산 규칙 적용. (청산가, 사유, 청산일, 보유일, 청산완료 여부). entry_price가 없으면 future[0] 시가 진입,
    있으면 그 가격(예: 전날 종가 매수)으로 들어간 뒤 future[0]부터 판정. 타임아웃 전에 데이터가 끝나면 마지막 종가, 청산완료=False."""
    entry_price = entry_price or future[0].open_price
    high_water = entry_price
    for j, day in enumerate(future[:_TIMEOUT_DAYS]):
        hold = j + 1
        if day.open_price <= stop:
            return day.open_price, "stop_loss", day.trading_date, hold, True
        if day.low_price <= stop:
            return stop, "stop_loss", day.trading_date, hold, True
        high_water = max(high_water, day.high_price)
        trail = high_water * (1 - _TRAILING_STOP_PCT / 100)
        if hold >= _TRAILING_MIN_HOLD and high_water > entry_price and day.low_price <= trail:
            return min(trail, day.open_price), "trailing", day.trading_date, hold, True
    last = future[: _TIMEOUT_DAYS][-1]
    done = len(future) >= _TIMEOUT_DAYS
    return last.close_price, "timeout", last.trading_date, min(len(future), _TIMEOUT_DAYS), done


def _pnl(entry_price: float, exit_price: float) -> tuple[float, float]:
    """(수수료 차감 수익률 %, 200만원 기준 손익 원)."""
    pct = (exit_price - entry_price) / entry_price * 100 - _COMMISSION_PCT
    shares = int(_POSITION_SIZE / entry_price)
    krw = shares * (exit_price - entry_price) - _POSITION_SIZE * _COMMISSION_PCT / 100
    return pct, krw


def _simulate_trades(signals: list[dict]) -> list[TradeResult]:
    trades = []
    busy_until: dict[str, date] = {}
    for sig in signals:
        future = sig["future"]
        entry = future[0]
        if not entry.open_price or entry.open_price <= 0:
            continue
        if busy_until.get(sig["code"]) and entry.trading_date <= busy_until[sig["code"]]:
            continue
        entry_price = entry.open_price
        exit_price, exit_reason, exit_date, hold_days, _ = _exit_trade(future, sig["stop_price"])
        busy_until[sig["code"]] = exit_date
        pnl_pct, pnl_krw = _pnl(entry_price, exit_price)
        trades.append(TradeResult(
            code=sig["code"], name=sig["name"], score=sig["score"], bars_since=sig["bars_since"],
            entry_date=str(entry.trading_date), entry_price=round(entry_price),
            exit_date=str(exit_date), exit_price=round(exit_price), exit_reason=exit_reason,
            pnl_pct=round(pnl_pct, 2), pnl_krw=round(pnl_krw), hold_days=hold_days,
            features=sig["features"],
        ))
    return trades


# ── 통계 ──

def _calc_trade_stats(trades: list[TradeResult]) -> dict:
    if not trades:
        return {"count": 0, "win_count": 0, "loss_count": 0, "win_rate": 0, "total_pnl_krw": 0,
                "avg_pnl_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0, "profit_factor": 0,
                "max_consecutive_loss": 0, "mdd_krw": 0, "avg_hold_days": 0, "stop_loss_count": 0,
                "target_count": 0, "timeout_count": 0, "best_trade": 0, "worst_trade": 0}
    ordered = sorted(trades, key=lambda t: t.exit_date)
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]

    max_streak = streak = 0
    for t in ordered:
        streak = streak + 1 if t.pnl_pct <= 0 else 0
        max_streak = max(max_streak, streak)

    cumulative = peak = mdd = 0.0
    for t in ordered:
        cumulative += t.pnl_krw
        peak = max(peak, cumulative)
        mdd = max(mdd, peak - cumulative)

    return {
        "count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl_krw": round(sum(t.pnl_krw for t in trades)),
        "avg_pnl_pct": round(sum(t.pnl_pct for t in trades) / len(trades), 2),
        "avg_win_pct": round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss_pct": round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0,
        "profit_factor": round(sum(t.pnl_krw for t in wins) / max(abs(sum(t.pnl_krw for t in losses)), 1), 2),
        "max_consecutive_loss": max_streak,
        "mdd_krw": round(mdd),
        "avg_hold_days": round(sum(t.hold_days for t in trades) / len(trades), 1),
        "stop_loss_count": sum(1 for t in trades if t.exit_reason == "stop_loss"),
        "target_count": sum(1 for t in trades if t.exit_reason == "trailing"),
        "timeout_count": sum(1 for t in trades if t.exit_reason == "timeout"),
        "best_trade": round(max(t.pnl_pct for t in trades), 2),
        "worst_trade": round(min(t.pnl_pct for t in trades), 2),
    }


def _monthly_breakdown(trades: list[TradeResult]) -> list[dict]:
    by_month: dict[str, list[TradeResult]] = defaultdict(list)
    for t in trades:
        by_month[t.entry_date[:7]].append(t)
    out = []
    for month in sorted(by_month):
        mt = by_month[month]
        wins = sum(1 for t in mt if t.pnl_pct > 0)
        out.append({
            "month": month, "trades": len(mt), "wins": wins,
            "win_rate": round(wins / len(mt) * 100, 1),
            "total_pnl": round(sum(t.pnl_krw for t in mt)),
            "avg_pnl_pct": round(sum(t.pnl_pct for t in mt) / len(mt), 2),
        })
    return out


def _bars_since_breakdown(trades: list[TradeResult]) -> list[dict]:
    """조정 며칠째에 진입했는지별 성과."""
    buckets = [("2~4일", 2, 4), ("5~9일", 5, 9), ("10~19일", 10, 19), ("20일+", 20, 999)]
    out = []
    for label, lo, hi in buckets:
        g = [t for t in trades if lo <= t.bars_since <= hi]
        if not g:
            continue
        wins = [t for t in g if t.pnl_pct > 0]
        losses = [t for t in g if t.pnl_pct <= 0]
        out.append({
            "range": label, "trades": len(g),
            "win_rate": round(len(wins) / len(g) * 100, 1),
            "avg_pnl_pct": round(sum(t.pnl_pct for t in g) / len(g), 2),
            "profit_factor": round(sum(t.pnl_krw for t in wins) / max(abs(sum(t.pnl_krw for t in losses)), 1), 2),
        })
    return out


def _analyze_features(trades: list[TradeResult]) -> dict:
    """승리/패배 거래군의 특징 평균 비교."""
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    if not wins or not losses:
        return {"count_win": len(wins), "count_loss": len(losses), "items": []}
    items = []
    for k in trades[0].features:
        wv = [float(t.features[k]) for t in wins]
        lv = [float(t.features[k]) for t in losses]
        w, l = sum(wv) / len(wv), sum(lv) / len(lv)
        items.append({
            "feature": k, "win_avg": round(w, 2), "loss_avg": round(l, 2),
            "diff_pct": round((w - l) / abs(l) * 100, 1) if l else None,
        })
    return {"count_win": len(wins), "count_loss": len(losses), "items": items}


def _score_distribution(scores: list[int]) -> list[dict]:
    buckets = [("0-29", 0, 29), ("30-59", 30, 59), ("60-74", 60, 74), ("75-89", 75, 89), ("90-100", 90, 1000)]
    return [{"range": label, "count": sum(1 for s in scores if lo <= s <= hi)} for label, lo, hi in buckets]


def _trade_to_dict(t: TradeResult) -> dict:
    return {
        "code": t.code, "name": t.name, "score": t.score, "bars_since": t.bars_since,
        "entry_date": t.entry_date, "entry_price": t.entry_price,
        "exit_date": t.exit_date, "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "pnl_pct": t.pnl_pct, "pnl_krw": t.pnl_krw, "hold_days": t.hold_days,
        "features": t.features,
    }
