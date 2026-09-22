"""
"거래량은 크게 터졌는데 주가는 별로 안 올랐으면(+5% 이하) 페널티를 줘야
하지 않냐"는 가설 검증용 1회성 분석 스크립트.

거래량배수가 큰(고배율) 스파이크들을 당일 등락률 기준으로 나눠서, 등락률이
약했던 그룹(거래량 대비 비효율적 상승)과 강했던 그룹의 이후 성과를 비교한다.
"""
from __future__ import annotations

from collections import defaultdict

from backend.db.database import SessionLocal
from backend.db.models import SpotDailyPrice
from backend.screener.pullback_scanner import detect_pullback
from backtest_pullback import spearmanr

FORWARD_HORIZONS = [5, 10, 20]
MIN_HISTORY_BEFORE = 45
HIGH_VOLUME_RATIO_THRESHOLD = 8.0  # 이 이상을 "거래량 크게 터짐"으로 간주
WEAK_CHANGE_THRESHOLD = 5.0        # 당일 등락률이 이 이하면 "약한 반응"


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
    records = []  # (volume_ratio, spike_change_pct, rets{h})

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
            entry_price = asc[i].close_price
            if not entry_price:
                continue
            rets = {h: (asc[i + h].close_price - entry_price) / entry_price * 100 for h in FORWARD_HORIZONS}
            records.append((result["spike_volume_ratio"], result["spike_change_pct"], rets))

    print(f"총 후보 수: {len(records)}")

    high_vol = [r for r in records if r[0] >= HIGH_VOLUME_RATIO_THRESHOLD]
    print(f"\n거래량배수 >= {HIGH_VOLUME_RATIO_THRESHOLD}배 인 후보: {len(high_vol)}개")

    weak = [r for r in high_vol if r[1] <= WEAK_CHANGE_THRESHOLD]
    strong = [r for r in high_vol if r[1] > WEAK_CHANGE_THRESHOLD]
    print(f"  - 등락률 <= {WEAK_CHANGE_THRESHOLD}% (거래량 대비 약한 반응): {len(weak)}개")
    print(f"  - 등락률 >  {WEAK_CHANGE_THRESHOLD}% (거래량 대비 강한 반응): {len(strong)}개")

    for label, group in [("약한 반응 그룹", weak), ("강한 반응 그룹", strong)]:
        if not group:
            continue
        print(f"\n[{label}] n={len(group)}")
        for h in FORWARD_HORIZONS:
            rs = [g[2][h] for g in group]
            avg_ret = sum(rs) / len(rs)
            win_rate = sum(1 for r in rs if r > 0) / len(rs) * 100
            print(f"  T+{h:>2}: 평균수익률={avg_ret:+.2f}%, 승률={win_rate:.1f}%")

    print("\n=== 참고: 거래량배수 구간 전체에서 등락률(spike_change_pct) 자체의 IC ===")
    for h in FORWARD_HORIZONS:
        vals = [r[1] for r in high_vol]
        rs = [r[2][h] for r in high_vol]
        ic, _ = spearmanr(vals, rs)
        print(f"T+{h:>2}: IC={ic:+.4f}  (거래량배수>={HIGH_VOLUME_RATIO_THRESHOLD}배 구간 내에서, 당일등락률 vs 미래수익률)")

    db.close()


if __name__ == "__main__":
    main()
