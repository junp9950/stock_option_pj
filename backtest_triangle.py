"""
삼각수렴 돌파(triangle_scanner) 품질점수 검증 백테스트.
"""
from __future__ import annotations

from collections import defaultdict

from backend.db.database import SessionLocal
from backend.db.models import MarketSignal, SpotDailyPrice
from backend.screener.triangle_scanner import detect_triangle_breakout
from backtest_pullback import spearmanr

FORWARD_HORIZONS = [1, 3, 5, 10, 20]
MIN_HISTORY_BEFORE = 55


def main():
    db = SessionLocal()
    print("가격 데이터 로딩 중...")
    all_prices = list(
        db.query(SpotDailyPrice).order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date).all()
    )
    by_code_asc: dict[str, list[SpotDailyPrice]] = defaultdict(list)
    for p in all_prices:
        by_code_asc[p.stock_code].append(p)

    market_signal_by_date = {s.trading_date: s.signal for s in db.query(MarketSignal).all()}

    max_horizon = max(FORWARD_HORIZONS)
    records = []

    for code, asc in by_code_asc.items():
        n = len(asc)
        if n < MIN_HISTORY_BEFORE + max_horizon + 5:
            continue
        for i in range(MIN_HISTORY_BEFORE, n - max_horizon):
            start = max(0, i - 55)
            hist_desc = asc[start : i + 1][::-1]
            result = detect_triangle_breakout(hist_desc)
            if result is None:
                continue
            entry_price = asc[i].close_price
            if not entry_price:
                continue
            rets = {h: (asc[i + h].close_price - entry_price) / entry_price * 100 for h in FORWARD_HORIZONS}
            regime = market_signal_by_date.get(asc[i].trading_date, "?")
            records.append((result["quality_score"], result["low_rise_pct"], result["range_contraction"], rets, regime))

    print(f"\n총 후보 수: {len(records)}")
    if len(records) < 30:
        print("표본이 너무 적습니다.")
        db.close()
        return

    print("\n=== quality_score IC ===")
    for h in FORWARD_HORIZONS:
        qs = [r[0] for r in records]
        rs = [r[3][h] for r in records]
        ic, _ = spearmanr(qs, rs)
        print(f"T+{h:>2}: IC={ic:+.4f}")

    print("\n=== 베이스라인 대비 ===")
    for h in [5]:
        rs = [r[3][h] for r in records]
        avg = sum(rs) / len(rs)
        win = sum(1 for r in rs if r > 0) / len(rs) * 100
        print(f"전체 평균 T+{h} 수익률={avg:+.2f}%, 승률={win:.1f}% (n={len(rs)})")

    print("\n=== 시장 국면별 ===")
    by_regime = defaultdict(list)
    for r in records:
        by_regime[r[4]].append(r)
    bullish = {"상방", "강세매수"}
    for label, keys in [("강세", bullish), ("전체(국면무관)", set(by_regime.keys()))]:
        chunk = [r for k in keys for r in by_regime.get(k, [])] if label == "강세" else records
        if not chunk:
            continue
        for h in [5, 10, 20]:
            rs = [c[3][h] for c in chunk]
            avg = sum(rs) / len(rs)
            win = sum(1 for r in rs if r > 0) / len(rs) * 100
            print(f"[{label}] T+{h:>2}: 평균={avg:+.2f}%, 승률={win:.1f}% (n={len(chunk)})")

    db.close()


if __name__ == "__main__":
    main()
