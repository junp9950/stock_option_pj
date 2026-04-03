from __future__ import annotations

import asyncio
from datetime import date

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import MarketSignal, Recommendation
from backend.utils.formatting import format_krw
from backend.utils.logger import get_logger


logger = get_logger(__name__)


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


def send_message_sync(token: str, chat_id: str, text: str) -> bool:
    """텔레그램 Bot API로 메시지 동기 전송. 성공 시 True."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info("Telegram message sent successfully to chat_id=%s", chat_id)
            return True
        logger.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send error: %s", exc)
    return False


async def send_daily_message(db: Session, trading_date_str: str) -> None:
    config = get_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.info("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set). Skipping.")
        return

    try:
        trading_date = date.fromisoformat(trading_date_str)
    except ValueError:
        logger.warning("Invalid trading_date_str for telegram: %s", trading_date_str)
        return

    text = build_daily_message(db, trading_date)
    # requests는 동기 라이브러리이므로 executor에서 실행
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        send_message_sync,
        config.telegram_bot_token,
        config.telegram_chat_id,
        text,
    )
