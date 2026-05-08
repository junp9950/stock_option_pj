from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from backend.db.models import Sector, SectorFlowDaily, SectorStock, SpotDailyPrice, SpotInvestorFlow, Stock
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def _percentile_rank(values: list[float], target: float) -> float:
    """target이 values 중에서 몇 번째 백분위인지 반환 (0.0 ~ 1.0)."""
    if not values:
        return 0.5
    below = sum(1 for v in values if v < target)
    return below / len(values)


def _calc_buy_streak(db: Session, sector_id: int, current_date: date, current_combined: int) -> int:
    """sector_flow_daily 과거 기록 기반 연속 순매수일 계산."""
    if current_combined <= 0:
        return 0

    # 오늘 포함 이전 N일 조회 (오늘 제외하고 과거만)
    past = list(db.scalars(
        select(SectorFlowDaily)
        .where(
            SectorFlowDaily.sector_id == sector_id,
            SectorFlowDaily.date < current_date,
        )
        .order_by(desc(SectorFlowDaily.date))
        .limit(20)
    ))

    streak = 1  # 오늘이 양수이므로 1부터 시작
    for row in past:
        if row.combined_net_buy > 0:
            streak += 1
        else:
            break
    return streak


def _calc_volume_ratio(db: Session, codes: list[str], target_date: date, today_volume: int) -> float:
    """오늘 거래량 / 20일 평균 거래량 (0이면 1.0 반환)."""
    if not codes or today_volume == 0:
        return 1.0
    lookback_start = target_date - timedelta(days=30)
    prices = list(db.scalars(
        select(SpotDailyPrice)
        .where(
            SpotDailyPrice.stock_code.in_(codes),
            SpotDailyPrice.trading_date >= lookback_start,
            SpotDailyPrice.trading_date < target_date,
        )
    ))
    if not prices:
        return 1.0
    avg_vol = sum(p.volume for p in prices) / len(prices) if prices else 0
    if avg_vol == 0:
        return 1.0
    return today_volume / avg_vol


def calculate_sector_signals(db: Session, target_date: date) -> list[SectorFlowDaily]:
    """target_date 기준 전체 섹터 수급 집계 + flow_score + stealth_score 계산 후 DB 저장."""
    # 유니버스에 있는 종목 집합
    universe_codes = {s.code for s in db.scalars(select(Stock).where(Stock.is_active == True))}  # noqa: E712

    # target_date 수급 데이터 로드
    flows_raw = list(db.scalars(
        select(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == target_date)
    ))
    prices_raw = list(db.scalars(
        select(SpotDailyPrice).where(SpotDailyPrice.trading_date == target_date)
    ))
    flow_map: dict[str, SpotInvestorFlow] = {f.stock_code: f for f in flows_raw}
    price_map: dict[str, SpotDailyPrice] = {p.stock_code: p for p in prices_raw}

    # 활성 섹터 목록
    sectors = list(db.scalars(select(Sector).where(Sector.is_active == True)))  # noqa: E712
    if not sectors:
        logger.warning("활성 섹터 없음 — 섹터 수급 계산 스킵")
        return []

    # 섹터별 종목 매핑 로드
    all_mappings = list(db.scalars(select(SectorStock)))
    sector_codes_map: dict[int, list[str]] = defaultdict(list)
    for m in all_mappings:
        sector_codes_map[m.sector_id].append(m.stock_code)

    # 각 섹터별 1차 집계
    raw_results: list[dict] = []
    for sector in sectors:
        codes = sector_codes_map.get(sector.id, [])
        # 유니버스 내 종목만 사용
        valid_codes = [c for c in codes if c in universe_codes]
        if len(valid_codes) < 2:
            # 데이터 부족 섹터 제외
            continue

        foreign_total = 0
        inst_total = 0
        up_count = down_count = 0
        change_pcts: list[float] = []
        total_volume = 0
        top_code = top_name = ""
        top_amount = 0

        for code in valid_codes:
            flow = flow_map.get(code)
            price = price_map.get(code)
            if flow is None and price is None:
                continue

            f_net = int(flow.foreign_net_buy or 0) if flow else 0
            i_net = int(flow.institution_net_buy or 0) if flow else 0
            foreign_total += f_net
            inst_total += i_net

            if price:
                chg = float(price.change_pct or 0)
                change_pcts.append(chg)
                if chg > 0:
                    up_count += 1
                elif chg < 0:
                    down_count += 1
                total_volume += int(price.volume or 0)

            # 최대 기여 종목 추적
            combined = f_net + i_net
            if abs(combined) > abs(top_amount):
                top_amount = combined
                top_code = code
                stock_obj = db.scalar(select(Stock).where(Stock.code == code))
                top_name = stock_obj.name if stock_obj else code

        combined_total = foreign_total + inst_total
        avg_change = sum(change_pcts) / len(change_pcts) if change_pcts else 0.0
        max_change = max(change_pcts, default=0.0)

        raw_results.append({
            "sector": sector,
            "codes": valid_codes,
            "foreign_net_buy": foreign_total,
            "inst_net_buy": inst_total,
            "combined_net_buy": combined_total,
            "stock_count": len(valid_codes),
            "up_count": up_count,
            "down_count": down_count,
            "avg_change_pct": avg_change,
            "max_change_pct": max_change,
            "total_volume": total_volume,
            "top_contributor_code": top_code,
            "top_contributor_name": top_name,
            "top_contributor_amount": top_amount,
        })

    if not raw_results:
        return []

    # 백분위 계산을 위한 전체 값 목록
    all_foreign = [r["foreign_net_buy"] for r in raw_results]
    all_inst = [r["inst_net_buy"] for r in raw_results]
    all_combined = [r["combined_net_buy"] for r in raw_results]
    all_change = [r["avg_change_pct"] for r in raw_results]

    saved: list[SectorFlowDaily] = []
    for r in raw_results:
        sector: Sector = r["sector"]

        # 거래량 증가율 (20일 평균 대비)
        vol_ratio = _calc_volume_ratio(db, r["codes"], target_date, r["total_volume"])

        # ── flow_score 계산 ──────────────────────────────────────────
        # 외국인·기관 백분위 + 거래량 증가율 백분위 + 상승비율 가중합
        f_pct = _percentile_rank(all_foreign, r["foreign_net_buy"])
        i_pct = _percentile_rank(all_inst, r["inst_net_buy"])
        sc = r["stock_count"]
        up_ratio = r["up_count"] / sc if sc > 0 else 0.0

        all_vol_ratio = [1.0] * len(raw_results)  # 섹터별 거래량 비율 목록 없으므로 1.0으로 보정
        vol_pct = min(max((vol_ratio - 1.0) / 2.0 + 0.5, 0.0), 1.0)  # 0~1 정규화

        flow_score = (
            f_pct * 0.35
            + i_pct * 0.35
            + vol_pct * 0.15
            + up_ratio * 0.15
        ) * 10.0

        # ── stealth_score 계산 ───────────────────────────────────────
        # 핵심: "수급은 들어왔는데 주가는 안 오른 섹터"
        if r["combined_net_buy"] <= 0:
            # 순매도 섹터는 스텔스 없음
            stealth_score = 0.0
        else:
            # 1. 수급 강도 (combined 백분위)
            supply_strength = _percentile_rank(all_combined, r["combined_net_buy"])

            # 2. 가격 미반영도: 등락률이 낮을수록(심지어 하락이면) 높은 점수
            # avg_change_pct 백분위를 역전 → 안 오른 섹터가 높은 점수
            price_pct = _percentile_rank(all_change, r["avg_change_pct"])
            price_unreflected = 1.0 - price_pct

            # 3. 연속 매집 보너스: buy_streak 길수록 높음 (5일 기준 만점)
            buy_streak = _calc_buy_streak(db, sector.id, target_date, r["combined_net_buy"])
            streak_bonus = min(buy_streak / 5.0, 1.0)

            # 4. 거래량 조용함 보너스: 거래량이 평소와 비슷하거나 낮으면 조용히 쌓는 중
            quietness = 1.0 - min((vol_ratio - 1.0) / 2.0, 1.0)
            quietness = max(quietness, 0.0)

            stealth_score = (
                supply_strength * 0.35
                + price_unreflected * 0.30
                + streak_bonus * 0.20
                + quietness * 0.15
            ) * 10.0

        buy_streak = _calc_buy_streak(db, sector.id, target_date, r["combined_net_buy"])

        # upsert: 기존 레코드 덮어쓰기
        existing = db.scalar(
            select(SectorFlowDaily).where(
                SectorFlowDaily.date == target_date,
                SectorFlowDaily.sector_id == sector.id,
            )
        )
        if existing is None:
            row = SectorFlowDaily(date=target_date, sector_id=sector.id)
            db.add(row)
        else:
            row = existing

        row.foreign_net_buy = r["foreign_net_buy"]
        row.inst_net_buy = r["inst_net_buy"]
        row.combined_net_buy = r["combined_net_buy"]
        row.stock_count = r["stock_count"]
        row.up_count = r["up_count"]
        row.down_count = r["down_count"]
        row.avg_change_pct = r["avg_change_pct"]
        row.max_change_pct = r["max_change_pct"]
        row.total_volume = r["total_volume"]
        row.flow_score = round(flow_score, 2)
        row.stealth_score = round(stealth_score, 2)
        row.buy_streak = buy_streak
        row.top_contributor_code = r["top_contributor_code"]
        row.top_contributor_name = r["top_contributor_name"]
        row.top_contributor_amount = r["top_contributor_amount"]
        saved.append(row)

    db.commit()
    logger.info("섹터 수급 계산 완료: %d개 섹터 (date=%s)", len(saved), target_date)
    return saved
