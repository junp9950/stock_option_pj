"""눌림목 레이더: 눌림목 스캐너 + 세력 신호 점수 병합, 그리고 실전 기록/성과 추적."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import JobLog, RadarPick, SpotDailyPrice
from backend.screener.backtest import _exit_trade, _pnl
from backend.screener.market_regime import current_regime
from backend.screener.pullback_scanner import scan_pullback_candidates
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_TRACK_THRESHOLDS = (60, 65, 70, 75, 80)


def build_radar(db: Session, target_date: date, top_n: int = 1000, min_market_cap: float = 0) -> dict:
    candidates = scan_pullback_candidates(db, target_date, top_n=top_n, min_market_cap=min_market_cap)
    try:
        from backend.screener.volume_anomaly import scan as scan_signal  # noqa: PLC0415
        signals = {x["code"]: x for x in scan_signal(db)}
    except Exception:  # noqa: BLE001
        logger.exception("signal scan failed")
        signals = {}
    items = []
    for c in candidates:
        sig = signals.get(c.code)
        signal_score = sig["score"] if sig else None
        # 종합점수 = 세력 신호 60% + 눌림목 품질 40% (신호 없으면 신호 부분 0점)
        total = round(0.6 * (signal_score or 0) + 0.4 * c.quality_score * 100)
        items.append({
            "code": c.code, "name": c.name, "market": c.market, "sector": c.sector, "market_cap": c.market_cap,
            "close_price": c.close_price, "change_pct": c.change_pct,
            "spike_date": c.spike_date, "spike_change_pct": c.spike_change_pct,
            "spike_volume_ratio": c.spike_volume_ratio, "days_since_spike": c.days_since_spike,
            "pullback_pct": c.pullback_pct, "volume_contraction": c.volume_contraction,
            "repeat_cycles": c.repeat_cycles, "quality_score": c.quality_score,
            "total_score": total,
            "grade": "강력" if total >= 75 else "관심" if total >= 60 else "관찰",
            "signal_score": signal_score,
            "signal_reasons": sig["reasons"] if sig else [],
            "vwap": sig["vwap"] if sig else None,
            "vwap_gap_pct": sig["vwap_gap_pct"] if sig else None,
            "stop_price": sig["stop_price"] if sig else None,
            "days_since_event": sig["days_since_event"] if sig else c.days_since_spike,
        })
    # 눌림목 스캐너에는 안 잡히지만 세력 신호가 있는 종목도 누락 없이 포함 (품질점수는 신호점수로 대체)
    seen = {c.code for c in candidates}
    for code, sig in signals.items():
        if code in seen or sig["market_cap"] < min_market_cap:
            continue
        items.append({
            "code": code, "name": sig["name"], "market": sig["market"], "sector": "-", "market_cap": sig["market_cap"],
            "close_price": sig["current_price"], "change_pct": sig["change_pct"],
            "spike_date": sig["event_date"], "spike_change_pct": sig["event_change_pct"],
            "spike_volume_ratio": sig["vol_multiplier"], "days_since_spike": sig["days_since_event"],
            "pullback_pct": sig["retrace_pct"], "volume_contraction": sig["vol_ratio"],
            "repeat_cycles": 0, "quality_score": sig["score"] / 100,
            "total_score": sig["score"],
            "grade": sig["grade"],
            "signal_score": sig["score"],
            "signal_reasons": sig["reasons"],
            "vwap": sig["vwap"], "vwap_gap_pct": sig["vwap_gap_pct"], "stop_price": sig["stop_price"],
            "days_since_event": sig["days_since_event"],
        })
    items.sort(key=lambda x: -x["total_score"])
    return {"trading_date": target_date.isoformat(), "market": current_regime(db), "items": items}


def record_picks(db: Session) -> dict:
    """그날 파이프라인이 끝난 뒤 한 번만, 차트 후보 페이지의 종목을 저장. 여러 번 호출해도 안전."""
    pick_date = db.scalar(
        select(func.max(JobLog.trading_date)).where(
            JobLog.stage == "pipeline", JobLog.status == "completed", JobLog.trading_date <= date.today()
        )
    )
    latest_price = db.scalar(select(func.max(SpotDailyPrice.trading_date)))
    if pick_date is None or pick_date != latest_price:
        return {"recorded": 0, "reason": f"pipeline {pick_date} / prices {latest_price} 불일치"}
    if db.scalar(select(func.count()).select_from(RadarPick).where(RadarPick.pick_date == pick_date)):
        return {"recorded": 0, "reason": f"{pick_date} 이미 기록됨"}

    from backend.screener.chart_candidates import scan as scan_candidates  # noqa: PLC0415
    cands = scan_candidates(db)
    state = (cands["market"] or {}).get("state")
    n = 0
    for it in cands["items"]:
        if it["stop_price"] is None:
            continue  # 손절선 없이는 매도 규칙을 적용할 수 없음
        db.add(RadarPick(
            # total_score = 섹터 점수(0~100). vwap 칸은 차트 후보에 없어 종가로 채움
            pick_date=pick_date, stock_code=it["code"], name=it["name"],
            total_score=it["sector_score"] or 0, signal_score=0, quality_score=len(it["patterns"]),
            market_state=state, market_cap=it["market_cap"] or 0.0,
            close_price=it["close_price"], stop_price=it["stop_price"], vwap=it["close_price"],
            days_since_event=0,
            reasons=json.dumps({"patterns": [p["type"] for p in it["patterns"]], "sector": it["sector_name"]}, ensure_ascii=False),
        ))
        n += 1
    db.commit()
    logger.info("radar picks recorded: %s (%d)", pick_date, n)
    return {"recorded": n, "pick_date": pick_date.isoformat(), "market_state": state}


def pick_performance(db: Session, min_market_cap: float = 100_000_000_000) -> dict:
    """기록된 종목을 다음날 시가에 샀다고 보고, 백테스트와 같은 조건·청산 규칙으로 실제 성과를 계산."""
    picks = [
        p for p in db.scalars(select(RadarPick).order_by(RadarPick.pick_date, RadarPick.total_score.desc()))
        if (p.market_cap or 0) >= min_market_cap
    ]
    if not picks:
        return {"since": None, "record_days": 0, "thresholds": [], "trades": []}

    codes = {p.stock_code for p in picks}
    prices = db.execute(
        select(SpotDailyPrice)
        .where(SpotDailyPrice.stock_code.in_(codes), SpotDailyPrice.trading_date > picks[0].pick_date)
        .order_by(SpotDailyPrice.trading_date)
    ).scalars()
    by_code: dict[str, list] = defaultdict(list)
    for p in prices:
        by_code[p.stock_code].append(p)

    thresholds = []
    trade_rows: list[dict] = []
    for t in _TRACK_THRESHOLDS:
        busy_until: dict[str, date] = {}
        closed, opened, skipped_down = [], [], 0
        for pk in picks:
            if pk.total_score < t:
                continue
            if pk.market_state == "하락":
                skipped_down += 1
                continue
            if pk.stock_code in busy_until and pk.pick_date <= busy_until[pk.stock_code]:
                continue  # 이미 보유 중
            # 포착일 장 마감 후 종가(시간외 단일가 근사)에 산다고 보고, 다음 거래일부터 매도 규칙 적용
            entry = pk.close_price
            future = [x for x in by_code[pk.stock_code] if x.trading_date > pk.pick_date]
            if future:
                exit_price, reason, exit_date, hold, done = _exit_trade(future, pk.stop_price, entry_price=entry)
            else:
                exit_price, reason, exit_date, hold, done = entry, "timeout", pk.pick_date, 0, False
            pct, krw = _pnl(entry, exit_price)
            busy_until[pk.stock_code] = exit_date if done else date.max
            row = {
                "code": pk.stock_code, "name": pk.name, "score": pk.total_score, "pick_date": pk.pick_date.isoformat(),
                "entry_date": pk.pick_date.isoformat(), "entry_price": round(entry),
                "exit_date": exit_date.isoformat(), "last_price": round(exit_price), "status": reason if done else "보유중",
                "pnl_pct": round(pct, 2), "pnl_krw": round(krw), "hold_days": hold,
            }
            (closed if done else opened).append(row)
            if t == _TRACK_THRESHOLDS[0]:
                trade_rows.append(row)
        wins = [r for r in closed if r["pnl_pct"] > 0]
        thresholds.append({
            "min_score": t,
            "closed": len(closed), "open": len(opened), "skipped_down_market": skipped_down,
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "avg_pnl_pct": round(sum(r["pnl_pct"] for r in closed) / len(closed), 2) if closed else None,
            "realized_krw": sum(r["pnl_krw"] for r in closed),
            "unrealized_krw": sum(r["pnl_krw"] for r in opened),
        })

    days = sorted({p.pick_date for p in picks})
    trade_rows.sort(key=lambda r: r["pick_date"], reverse=True)
    return {
        "min_market_cap": min_market_cap,
        "since": days[0].isoformat(), "record_days": len(days), "last_pick_date": days[-1].isoformat(),
        "thresholds": thresholds, "trades": trade_rows[:60],
    }
