from __future__ import annotations

import asyncio
from datetime import date

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import MarketSignal, MarketSignalDetail, Recommendation, SpotInvestorFlow
from backend.utils.formatting import format_krw
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def _fmt_contract(val: float) -> str:
    """선물 계약수 포맷."""
    if abs(val) >= 10000:
        return f"{val/10000:+.1f}만"
    return f"{val:+.0f}계약"


def _fmt_flow(val: float) -> str:
    """수급 금액 포맷 (억원)."""
    if abs(val) >= 1e11:
        return f"{val/1e8:+.0f}억"
    if abs(val) >= 1e8:
        return f"{val/1e8:+.1f}억"
    return f"{val/1e4:+.0f}만"


def build_daily_message(db: Session, trading_date: date) -> str:
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == trading_date))
    signal_details = list(db.scalars(
        select(MarketSignalDetail)
        .where(MarketSignalDetail.trading_date == trading_date, MarketSignalDetail.is_enabled.is_(True))
        .order_by(MarketSignalDetail.key)
    ))
    recommendations = list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.trading_date == trading_date)
            .order_by(Recommendation.rank)
        )
    )

    sig_label = signal.signal if signal else "중립"
    sig_score = signal.score if signal else 0.0
    sig_emoji = "🟢" if sig_label == "상방" else "🔴" if sig_label == "하방" else "🟡"

    lines = [
        f"<b>📊 {trading_date.isoformat()} 익일 시장 전망</b>",
        f"{sig_emoji} 시장 방향: <b>{sig_label}</b>  점수: {sig_score:.2f}",
        "",
    ]

    # 핵심 지표 요약 (활성화된 것만, 점수 높은 순)
    if signal_details:
        key_details = sorted(signal_details, key=lambda d: abs(d.normalized_score), reverse=True)[:4]
        lines.append("<b>📈 핵심 지표</b>")
        for d in key_details:
            arrow = "▲" if d.normalized_score > 0 else "▼" if d.normalized_score < 0 else "─"
            raw = f"{d.raw_value:,.0f}" if d.raw_value is not None else "—"
            lines.append(f"  {arrow} {d.interpretation}: {raw} ({d.normalized_score:+.1f})")
        lines.append("")

    # 추천 종목
    lines.append("<b>🎯 추천 종목</b>")
    if not recommendations:
        lines.append("  추천 종목이 없습니다.")
    else:
        # 각 종목의 당일 수급 조회
        codes = [r.stock_code for r in recommendations]
        flows = {
            f.stock_code: f
            for f in db.scalars(
                select(SpotInvestorFlow).where(
                    SpotInvestorFlow.trading_date == trading_date,
                    SpotInvestorFlow.stock_code.in_(codes),
                )
            )
        }
        for rec in recommendations[:10]:  # 최대 10종목
            flow = flows.get(rec.stock_code)
            chg = f"+{rec.change_pct:.1f}%" if rec.change_pct >= 0 else f"{rec.change_pct:.1f}%"
            line = f"  <b>{rec.rank}. {rec.stock_name}</b> [{rec.stock_code}]"
            line += f"\n     종가 {format_krw(rec.close_price)} ({chg})  점수 {rec.total_score:.2f}"
            if flow:
                inst_str = _fmt_flow(flow.institution_net_buy)
                fgn_str = _fmt_flow(flow.foreign_net_buy)
                line += f"\n     기관 {inst_str}  외국인 {fgn_str}"
            lines.append(line)

    lines.append("")
    lines.append("<i>⚠️ 투자 참고용 보조 도구. 실제 투자 손익에 대한 책임은 사용자에게 있습니다.</i>")
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
