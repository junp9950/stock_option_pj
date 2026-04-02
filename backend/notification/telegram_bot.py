from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import MarketSignal, Recommendation
from backend.utils.formatting import format_krw


def build_daily_message(db: Session, trading_date: date) -> str:
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == trading_date))
    recommendations = list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.trading_date == trading_date)
            .order_by(Recommendation.rank)
        )
    )
    lines = [
        f"[{trading_date.isoformat()}] 익일 시장 전망",
        f"시장 방향: {signal.signal if signal else '중립'} / 점수: {signal.score if signal else 0}",
        "",
        "추천 종목",
    ]
    if not recommendations:
        lines.append("추천 종목이 없습니다.")
    for rec in recommendations:
        lines.append(f"{rec.rank}. {rec.stock_name} / 점수 {rec.total_score} / 종가 {format_krw(rec.close_price)}")
    lines.append("")
    lines.append("이 시스템은 투자 참고용 보조 도구이며, 실제 투자 손익에 대한 책임은 사용자에게 있다.")
    return "\n".join(lines)


async def send_daily_message(_: Session, __: str) -> None:
    config = get_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    # MVP에서는 실행 가능성을 우선해 메시지 생성만 보장하고, 실제 전송은 환경 설정 시 활성화한다.
