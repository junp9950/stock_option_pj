"""
눌림목 스캐너 품질점수 검증 백테스트. 파라미터(가중치·임계값) 바꿀 때마다
재실행해서 IC/분위별 수익률이 실제로 개선되는지 확인하는 용도로 유지.

각 과거 거래일마다 그 시점까지의 데이터만으로 detect_pullback()을 재현해
후보와 quality_score를 뽑고, 이후 T+1/T+3/T+5/T+10 실제 수익률을 계산해
품질점수(및 하위 구성요소)와의 스피어만 상관(IC)을 측정한다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from backend.db.database import SessionLocal
from backend.db.models import MarketSignal, SpotDailyPrice, Stock
from backend.screener.pullback_scanner import MAX_DAYS_SINCE_SPIKE, detect_pullback

FORWARD_HORIZONS = [1, 3, 5, 10]
MIN_HISTORY_BEFORE = 45  # detect_pullback 최소 요구치(40) + 여유


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearmanr(a: list[float], b: list[float]) -> tuple[float, float]:
    """scipy 없이 스피어만 상관계수만 계산 (p-value는 근사치 없이 생략, None 반환)."""
    n = len(a)
    ra, rb = _rank(a), _rank(b)
    mean_a, mean_b = sum(ra) / n, sum(rb) / n
    cov = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    var_a = sum((x - mean_a) ** 2 for x in ra)
    var_b = sum((x - mean_b) ** 2 for x in rb)
    if var_a == 0 or var_b == 0:
        return 0.0, None
    r = cov / (var_a ** 0.5 * var_b ** 0.5)
    return r, None


def main():
    db = SessionLocal()
    print("가격 데이터 로딩 중...")
    all_prices = list(
        db.query(SpotDailyPrice)
        .order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date)
        .all()
    )
    by_code_asc: dict[str, list[SpotDailyPrice]] = defaultdict(list)
    for p in all_prices:
        by_code_asc[p.stock_code].append(p)  # 오름차순

    all_dates = sorted({p.trading_date for p in all_prices})
    print(f"종목수: {len(by_code_asc)}, 거래일수: {len(all_dates)}")

    market_signal_by_date = {s.trading_date: s.signal for s in db.query(MarketSignal).all()}

    max_horizon = max(FORWARD_HORIZONS)
    # 백테스트 가능한 날짜 인덱스 범위: 앞으로 최소 이력 + 뒤로 최대 forward horizon 확보
    date_index = {d: i for i, d in enumerate(all_dates)}

    records = []  # (quality_score, volume_ratio, pullback_pct, volume_contraction, {horizon: ret_pct})

    total_candidates = 0
    for code, asc in by_code_asc.items():
        if len(asc) < MIN_HISTORY_BEFORE + max_horizon + 5:
            continue
        n = len(asc)
        # 각 as-of 인덱스 i (asc 기준) 에서 detect_pullback 재현
        for i in range(MIN_HISTORY_BEFORE, n):
            as_of_date = asc[i].trading_date
            di = date_index.get(as_of_date)
            if di is None:
                continue
            # 미래 데이터가 max_horizon 만큼 남아있는지(전체 거래일 기준) 체크
            if di + max_horizon >= len(all_dates):
                continue

            # 필요한 만큼만(최근 ~90일) 잘라서 내림차순으로 변환 (detect_pullback 입력 형식)
            start = max(0, i - 90)
            hist_desc = asc[start : i + 1][::-1]
            result = detect_pullback(hist_desc)
            if result is None:
                continue

            entry_price = asc[i].close_price
            if not entry_price:
                continue
            rets = {}
            ok = True
            for h in FORWARD_HORIZONS:
                if i + h >= n:
                    ok = False
                    break
                future_price = asc[i + h].close_price
                rets[h] = (future_price - entry_price) / entry_price * 100
            if not ok:
                continue

            total_candidates += 1
            regime = market_signal_by_date.get(as_of_date, "?")
            records.append((result["quality_score"], result["spike_volume_ratio"],
                             result["pullback_pct"], result["volume_contraction"], rets, regime))

    print(f"\n총 백테스트 후보 수: {total_candidates}")
    if total_candidates < 30:
        print("표본이 너무 적어 통계적으로 의미 있는 검증이 어렵습니다.")
        db.close()
        return

    print("\n=== quality_score IC (스피어만 상관) ===")
    for h in FORWARD_HORIZONS:
        qs = [r[0] for r in records]
        rs = [r[4][h] for r in records]
        ic, pval = spearmanr(qs, rs)
        print(f"T+{h:>2}: IC={ic:+.4f}  (n={len(rs)})")

    print("\n=== 하위 구성요소별 IC (T+5 기준) ===")
    h = 5
    for idx, label in [(1, "spike_volume_ratio(거래량배수)"), (2, "pullback_pct(되돌림%, 클수록 나쁨)"), (3, "volume_contraction(수축률, 낮을수록 좋음)")]:
        vals = [r[idx] for r in records]
        rs = [r[4][h] for r in records]
        ic, pval = spearmanr(vals, rs)
        print(f"{label}: IC={ic:+.4f}")

    print("\n=== quality_score 5분위 그룹별 평균 T+5 수익률 ===")
    sorted_recs = sorted(records, key=lambda r: r[0])
    n = len(sorted_recs)
    qsize = max(1, n // 5)
    for q in range(5):
        chunk = sorted_recs[q * qsize : (q + 1) * qsize] if q < 4 else sorted_recs[q * qsize :]
        if not chunk:
            continue
        avg_q = sum(c[0] for c in chunk) / len(chunk)
        avg_ret = sum(c[4][5] for c in chunk) / len(chunk)
        win_rate = sum(1 for c in chunk if c[4][5] > 0) / len(chunk) * 100
        print(f"Q{q+1} (평균quality={avg_q:.3f}, n={len(chunk)}): 평균T+5수익률={avg_ret:+.2f}%, 승률={win_rate:.1f}%")

    print("\n=== 시장 시그널(당일 market_signal) 국면별 T+5 성과 ===")
    by_regime: dict[str, list] = defaultdict(list)
    for r in records:
        by_regime[r[5]].append(r)
    bullish = {"상방", "강세매수"}
    bearish = {"하방", "강세매도"}
    for label, keys in [("강세(상방+강세매수)", bullish), ("약세(하방+강세매도)", bearish), ("중립", {"중립"})]:
        chunk = [r for k in keys for r in by_regime.get(k, [])]
        if not chunk:
            continue
        avg_ret = sum(c[4][5] for c in chunk) / len(chunk)
        win_rate = sum(1 for c in chunk if c[4][5] > 0) / len(chunk) * 100
        qs = [c[0] for c in chunk]
        rs = [c[4][5] for c in chunk]
        ic, _ = spearmanr(qs, rs)
        print(f"{label} (n={len(chunk)}): 평균T+5수익률={avg_ret:+.2f}%, 승률={win_rate:.1f}%, quality_score IC={ic:+.4f}")

        # 강세장에서 quality 5분위
        if label.startswith("강세") and len(chunk) >= 25:
            sc = sorted(chunk, key=lambda r: r[0])
            qsz = max(1, len(sc) // 5)
            for q in range(5):
                sub = sc[q * qsz : (q + 1) * qsz] if q < 4 else sc[q * qsz :]
                if not sub:
                    continue
                aq = sum(s[0] for s in sub) / len(sub)
                ar = sum(s[4][5] for s in sub) / len(sub)
                wr = sum(1 for s in sub if s[4][5] > 0) / len(sub) * 100
                print(f"  Q{q+1}(quality={aq:.3f}, n={len(sub)}): T+5={ar:+.2f}%, 승률={wr:.1f}%")

    db.close()


if __name__ == "__main__":
    main()
