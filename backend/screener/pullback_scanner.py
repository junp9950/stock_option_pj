from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.db.models import Sector, SectorStock, SpotDailyPrice, Stock

# 큰 거래량(급등) 캔들이 나온 뒤, 지지선을 깨지 않고 조용히 눌린(눌림목) 종목을 찾는다.
MIN_SPIKE_VOLUME_RATIO = 2.5   # 스파이크 당일 거래량 / 20일 평균 거래량
MIN_SPIKE_CHANGE_PCT = 3.0     # 스파이크 당일 최소 상승률
MIN_DAYS_SINCE_SPIKE = 2       # 스파이크 후 최소 경과일 (당일 급등주 제외)
MAX_DAYS_SINCE_SPIKE = 15      # 이 이상 지나면 눌림목이 아니라 그냥 다른 국면으로 간주
MAX_PULLBACK_PCT = 15.0        # 스파이크 종가 대비 최대 되돌림 폭
MAX_VOLUME_CONTRACTION = 0.6   # 되돌림 구간 평균거래량 / 스파이크 거래량 상한
DEFAULT_MIN_MARKET_CAP = 0.0   # 기본은 시총 필터 없음(0) - 거래량 급증이 1순위, 시총 필터는 선택 사항


@dataclass
class PullbackCandidate:
    code: str
    name: str
    market: str
    sector: str
    market_cap: float
    close_price: float
    change_pct: float
    spike_date: str
    spike_change_pct: float
    spike_volume_ratio: float
    days_since_spike: int
    pullback_pct: float
    volume_contraction: float
    quality_score: float


def _find_spike(price_hist: list[SpotDailyPrice]) -> tuple[int, float, float] | None:
    """price_hist: 최신순(내림차순) 정렬. 룩백 구간에서 거래량 급증+상승 캔들을 찾는다.
    반환: (price_hist 상의 인덱스, volume_ratio, change_pct) 중 volume_ratio가 가장 큰 것.
    """
    best: tuple[int, float, float] | None = None
    max_idx = min(len(price_hist) - 21, MAX_DAYS_SINCE_SPIKE)
    for idx in range(MIN_DAYS_SINCE_SPIKE, max_idx + 1):
        p = price_hist[idx]
        window = [x.volume for x in price_hist[idx + 1 : idx + 21] if x.volume and x.volume > 0]
        if len(window) < 15:
            continue
        avg_vol_20d = sum(window) / len(window)
        if avg_vol_20d <= 0 or not p.volume:
            continue
        volume_ratio = p.volume / avg_vol_20d
        change_pct = float(p.change_pct or 0)
        if volume_ratio >= MIN_SPIKE_VOLUME_RATIO and change_pct >= MIN_SPIKE_CHANGE_PCT:
            if best is None or volume_ratio > best[1]:
                best = (idx, volume_ratio, change_pct)
    return best


def detect_pullback(price_hist: list[SpotDailyPrice]) -> dict | None:
    """price_hist: 최신순(내림차순) 정렬된 SpotDailyPrice 리스트 (최소 40일 이상 필요).
    조건에 맞으면 세부 지표 dict, 아니면 None을 반환한다.
    """
    if len(price_hist) < 40:
        return None

    spike = _find_spike(price_hist)
    if spike is None:
        return None
    spike_idx, volume_ratio, spike_change_pct = spike
    spike_day = price_hist[spike_idx]
    today = price_hist[0]

    since_spike = price_hist[:spike_idx]  # 스파이크 당일 제외, 오늘 포함, 최신순
    if not since_spike:
        return None

    # 지지선 붕괴 체크: 스파이크 저가 밑으로 마감한 적 있으면 탈락 (더 이상 눌림목이 아님)
    if any(p.close_price < spike_day.low_price for p in since_spike):
        return None

    if not spike_day.close_price:
        return None
    pullback_pct = (spike_day.close_price - today.close_price) / spike_day.close_price * 100
    if pullback_pct < -1.0 or pullback_pct > MAX_PULLBACK_PCT:
        # 음수(=스파이크 이후 더 상승)면 이미 다음 국면 - 제외
        return None

    recent_vols = [p.volume for p in since_spike if p.volume and p.volume > 0]
    avg_recent_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 0.0
    volume_contraction = avg_recent_vol / spike_day.volume if spike_day.volume else 1.0
    if volume_contraction > MAX_VOLUME_CONTRACTION:
        return None

    pullback_quality = max(0.0, 1 - max(pullback_pct, 0) / MAX_PULLBACK_PCT)
    contraction_quality = max(0.0, 1 - volume_contraction / MAX_VOLUME_CONTRACTION)
    volume_quality = min(volume_ratio / 5.0, 1.0)
    quality_score = round(volume_quality * 0.35 + pullback_quality * 0.35 + contraction_quality * 0.30, 3)

    return {
        "spike_date": spike_day.trading_date.isoformat(),
        "spike_change_pct": round(spike_change_pct, 2),
        "spike_volume_ratio": round(volume_ratio, 2),
        "days_since_spike": spike_idx,
        "pullback_pct": round(pullback_pct, 2),
        "volume_contraction": round(volume_contraction, 2),
        "quality_score": quality_score,
    }


def scan_pullback_candidates(
    db: Session, trading_date: date, top_n: int = 30, min_market_cap: float = DEFAULT_MIN_MARKET_CAP
) -> list[PullbackCandidate]:
    """전종목(유니버스 소속 여부·활성 상태 무관 - 가격 데이터가 있는 모든 종목)을 스캔해
    '급등 후 눌림목' 패턴에 맞는 종목을 품질순으로 반환한다.

    거래량 급증 탐지가 1순위이므로 Stock.is_active 여부로 미리 걸러내지 않는다 -
    섹터 보완 수집 등으로 가격 데이터만 있고 유니버스에는 편입 안 된 중소형 급등주도
    빠짐없이 검토 대상에 포함시키기 위함. 시가총액 필터는 그 다음 단계의 선택적 필터.
    시가총액이 0(수집 안 됨/불명)인 경우는 "작다고 확인된 것"이 아니라 "몰라서 0"인
    경우가 많아 필터에서 제외하지 않고 통과시킨다.
    """
    history_start = trading_date - timedelta(days=int((MAX_DAYS_SINCE_SPIKE + 30) * 1.6))
    all_prices = list(
        db.scalars(
            select(SpotDailyPrice)
            .where(SpotDailyPrice.trading_date.between(history_start, trading_date))
            .order_by(SpotDailyPrice.stock_code, desc(SpotDailyPrice.trading_date))
        )
    )
    prices_history: dict[str, list[SpotDailyPrice]] = {}
    for p in all_prices:
        prices_history.setdefault(p.stock_code, []).append(p)

    stocks = {s.code: s for s in db.scalars(select(Stock))}

    # 업종 매핑 (수동 큐레이션된 "custom" 섹터 태그 재사용 - 실제 KRX 업종 분류는 미수집)
    sector_map: dict[str, str] = {}
    sector_rows = db.execute(
        select(SectorStock.stock_code, Sector.sector_name)
        .join(Sector, SectorStock.sector_id == Sector.id)
        .where(Sector.source == "custom", Sector.is_active.is_(True))
    )
    for code, sector_name in sector_rows:
        sector_map.setdefault(code, sector_name)

    candidates: list[PullbackCandidate] = []
    for code, hist in prices_history.items():
        if hist[0].trading_date != trading_date:
            continue  # 당일 데이터 없는 종목(거래정지 등) 제외
        stock = stocks.get(code)
        if stock is None:
            continue
        result = detect_pullback(hist)
        if result is None:
            continue
        # 시총 필터 (선택적, 2순위) - 시총이 확인된 경우에만 적용. 0(불명)은 통과시킴.
        cap = stock.market_cap or 0.0
        if min_market_cap > 0 and 0 < cap < min_market_cap:
            continue
        today = hist[0]
        candidates.append(
            PullbackCandidate(
                code=code,
                name=stock.name,
                market=stock.market,
                sector=sector_map.get(code, "기타"),
                market_cap=stock.market_cap or 0.0,
                close_price=today.close_price,
                change_pct=float(today.change_pct or 0),
                **result,
            )
        )

    candidates.sort(key=lambda c: -c.quality_score)
    return candidates[:top_n]
