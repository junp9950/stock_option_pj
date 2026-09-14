from __future__ import annotations

import json
from datetime import date

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import Recommendation
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def attach_dart_earnings(db: Session, trading_date: date, recommendations: list[Recommendation]) -> None:
    """당일 추천 종목들에 DART 실적 점수(dart-analyzer의 earnings_auto_score)를 붙여 DB에 저장.

    stock_option_pj의 기술·수급 점수만으로는 재무 건전성을 전혀 반영하지 못했던 문제를 보완.
    DART API 실패는 종목 단위로만 스킵하고 파이프라인 전체를 막지 않는다.
    """
    config = get_config()
    if not config.dart_api_key:
        logger.info("DART_API_KEY 미설정 - 추천 종목 실적 점수 계산을 건너뜁니다")
        return

    try:
        from dart_analyzer.checklist import EARNINGS_AUTO_MAX, earnings_auto_score
        from dart_analyzer.corp_code import find_corp
        from dart_analyzer.financials import REPORT_CODES, fetch_financial_trend
    except Exception as exc:  # noqa: BLE001
        logger.error("dart-analyzer import 실패 - 실적 점수 계산 건너뜀: %s", exc)
        return

    this_year = date.today().year
    years = [str(y) for y in range(this_year - 2, this_year + 1)]

    # build_recommendations()가 반환하는 Recommendation 객체는 세션에 붙어있지 않은
    # 별도 인스턴스라 그대로 mutate해서 commit해도 저장되지 않음 -> stock_code로 직접 UPDATE.
    for rec in recommendations[: config.dart_earnings_pool]:
        try:
            corp = find_corp(rec.stock_code)
            financials = fetch_financial_trend(corp.corp_code, years, REPORT_CODES["annual"], "CFS")
            score, details = earnings_auto_score(financials)
            db.execute(
                update(Recommendation)
                .where(Recommendation.trading_date == trading_date, Recommendation.stock_code == rec.stock_code)
                .values(
                    earnings_score=score,
                    earnings_max=EARNINGS_AUTO_MAX,
                    earnings_note=json.dumps(details, ensure_ascii=False, default=str),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("종목 %s DART 실적 점수 계산 실패 (스킵): %s", rec.stock_code, exc)

    db.commit()
