"""
"원래 조용하던 종목에 거래량을 터뜨리면(세력 개입), 회수하려고 한번 더
펌핑하는 거 아니냐"는 가설 검증용 1회성 분석 스크립트.

detect_pullback()이 실제로 잡아내는 후보 모집단 안에서, 스파이크 이전
20일 평균 거래대금(baseline liquidity)으로 3분위(저유동성/중/고유동성)
나눠서 거래량배수(spike_volume_ratio)의 예측력(IC)이 유동성 구간별로
달라지는지, 그리고 T+5뿐 아니라 T+10/T+20까지 봤을 때도 그런지 확인한다.
"""
from __future__ import annotations

from collections import defaultdict

from backend.db.database import SessionLocal
from backend.db.models import SpotDailyPrice
from backend.screener.pullback_scanner import detect_pullback
from backtest_pullback import spearmanr

FORWARD_HORIZONS = [5, 10, 20]
MIN_HISTORY_BEFORE = 45


def main():
    db = SessionLocal()
    print("가격 데이터 로딩 중...")
    all_prices = list(
        db.query(SpotDailyPrice).order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date).all()
    )
    by_code_asc: dict[str, list[SpotDailyPrice]] = defaultdict(list)
    for p in all_prices:
        by_code_asc[p.stock_code].append(p)

    max_horizon = max(FORWARD_HORIZONS)
    records = []  # (volume_ratio, baseline_liquidity_won, rets{h})

    for code, asc in by_code_asc.items():
        n = len(asc)
        if n < MIN_HISTORY_BEFORE + max_horizon + 5:
            continue
        for i in range(MIN_HISTORY_BEFORE, n - max_horizon):
            start = max(0, i - 90)
            hist_desc = asc[start : i + 1][::-1]
            result = detect_pullback(hist_desc)
            if result is None:
                continue

            spike_idx = result["days_since_spike"]
            spike_pos_in_asc = i - spike_idx  # asc 기준 스파이크 위치
            # 스파이크 이전 20일 평균 거래대금(baseline liquidity)
            window = asc[max(0, spike_pos_in_asc - 20) : spike_pos_in_asc]
            if len(window) < 10:
                continue
            baseline_value = sum((w.trading_value or 0) for w in window) / len(window)

            entry_price = asc[i].close_price
            if not entry_price:
                continue
            rets = {h: (asc[i + h].close_price - entry_price) / entry_price * 100 for h in FORWARD_HORIZONS}

            records.append((result["spike_volume_ratio"], baseline_value, rets))

    print(f"총 후보 수: {len(records)}")

    print("\n=== 전체(유동성 무관) 거래량배수 IC ===")
    for h in FORWARD_HORIZONS:
        vals = [r[0] for r in records]
        rs = [r[2][h] for r in records]
        ic, _ = spearmanr(vals, rs)
        print(f"T+{h:>2}: IC={ic:+.4f}")

    print("\n=== 스파이크 이전 유동성(20일 평균 거래대금) 3분위별 거래량배수 IC ===")
    sorted_recs = sorted(records, key=lambda r: r[1])
    n = len(sorted_recs)
    tsize = n // 3
    labels = ["저유동성(원래 조용했던 종목)", "중유동성", "고유동성(원래도 활발했던 종목)"]
    for t in range(3):
        chunk = sorted_recs[t * tsize : (t + 1) * tsize] if t < 2 else sorted_recs[t * tsize :]
        avg_liq = sum(c[1] for c in chunk) / len(chunk)
        print(f"\n[{labels[t]}] n={len(chunk)}, 평균 스파이크 전 일평균거래대금={avg_liq/1e8:.1f}억")
        for h in FORWARD_HORIZONS:
            vals = [c[0] for c in chunk]
            rs = [c[2][h] for c in chunk]
            ic, _ = spearmanr(vals, rs)
            avg_ret = sum(rs) / len(rs)
            print(f"  T+{h:>2}: 거래량배수 IC={ic:+.4f}  (구간 평균 T+{h} 수익률={avg_ret:+.2f}%)")

    db.close()


if __name__ == "__main__":
    main()
