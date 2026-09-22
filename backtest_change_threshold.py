"""
MIN_SPIKE_CHANGE_PCT(스파이크 당일 최소 등락률) 임계값을 3/5/7/10%로 바꿔가며
백테스트 성과 비교. 1회성 분석 스크립트.
"""
from __future__ import annotations

from collections import defaultdict

from backend.db.database import SessionLocal
from backend.db.models import MarketSignal, SpotDailyPrice
import backend.screener.pullback_scanner as ps
from backtest_pullback import spearmanr

FORWARD_H = 5
MIN_HISTORY_BEFORE = 45


def run_for_threshold(threshold: float, all_prices_by_code, market_signal_by_date):
    ps.MIN_SPIKE_CHANGE_PCT = threshold
    records = []
    for code, asc in all_prices_by_code.items():
        n = len(asc)
        if n < MIN_HISTORY_BEFORE + FORWARD_H + 5:
            continue
        for i in range(MIN_HISTORY_BEFORE, n - FORWARD_H):
            start = max(0, i - 90)
            hist_desc = asc[start : i + 1][::-1]
            result = ps.detect_pullback(hist_desc)
            if result is None:
                continue
            entry = asc[i].close_price
            if not entry:
                continue
            ret = (asc[i + FORWARD_H].close_price - entry) / entry * 100
            regime = market_signal_by_date.get(asc[i].trading_date, "?")
            records.append((result["quality_score"], ret, regime))

    n = len(records)
    if n < 30:
        print(f"[{threshold}%] 표본 부족 (n={n})")
        return
    qs = [r[0] for r in records]
    rs = [r[1] for r in records]
    ic, _ = spearmanr(qs, rs)
    avg = sum(rs) / n
    win = sum(1 for r in rs if r > 0) / n * 100

    bullish = [r for r in records if r[2] in ("상방", "강세매수")]
    b_avg = sum(r[1] for r in bullish) / len(bullish) if bullish else 0
    b_win = sum(1 for r in bullish if r[1] > 0) / len(bullish) * 100 if bullish else 0

    # 강세장 Q5(품질 상위 20%)
    b_sorted = sorted(bullish, key=lambda r: r[0])
    q5 = b_sorted[int(len(b_sorted) * 0.8):]
    q5_avg = sum(r[1] for r in q5) / len(q5) if q5 else 0
    q5_win = sum(1 for r in q5 if r[1] > 0) / len(q5) * 100 if q5 else 0

    print(f"[MIN_SPIKE_CHANGE_PCT={threshold}%] n={n}, 전체 IC={ic:+.4f}, 전체T+5={avg:+.2f}%(승률{win:.1f}%) | "
          f"강세장T+5={b_avg:+.2f}%(승률{b_win:.1f}%, n={len(bullish)}) | 강세장Q5={q5_avg:+.2f}%(승률{q5_win:.1f}%, n={len(q5)})")


def main():
    db = SessionLocal()
    print("가격 데이터 로딩 중...")
    all_prices = list(db.query(SpotDailyPrice).order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date).all())
    by_code = defaultdict(list)
    for p in all_prices:
        by_code[p.stock_code].append(p)
    market_signal_by_date = {s.trading_date: s.signal for s in db.query(MarketSignal).all()}
    db.close()

    for threshold in [3.0, 5.0, 7.0, 10.0, 15.0]:
        run_for_threshold(threshold, by_code, market_signal_by_date)


if __name__ == "__main__":
    main()
