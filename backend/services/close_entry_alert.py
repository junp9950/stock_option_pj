"""15:12 종가 진입 후보 텔레그램 (2026-10-09 사용자 "추세매매가 하고 싶다 · 진입은 종베 형식으로 손익비 좋은 자리 · 종베는 그냥 진입 시점일 뿐").

실시간 가격으로 종가 진입 점수(7개 조건)를 계산해 6↑만, 손절폭(지금가 → 오늘 저가 -1%) 짧은 순.
3년(trend_exit.py, 손절 = 그날 저가 -1% 아래 종가 · 아니면 21일선 아래 마감까지 보유):
  점수 6↑ 평균 +2.2% · R +0.60 / 그중 손절폭 3%↓ 평균 +3.9% · R +1.68 · 최악10% -7% / 손절폭 8%↑ R +0.04.
하락장이면 보내되 '쉬는 날'로 적는다 (사용자 원칙). 봉은 15:30 전이라 확정 전.
"""
from __future__ import annotations

from sqlalchemy.orm import Session


def text_now(db: Session, k: int = 8) -> str | None:
    from backend.services.stock_signals import close_scores_now, market_breadth  # noqa: PLC0415
    from backend.services.telegram import market_status  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    sc = close_scores_now(db)
    if not sc.get("live"):
        return None
    names = dict(db.execute(text("select code, name from stocks")).all())
    rows = sorted(((c, v) for c, v in sc["scores"].items() if v["score"] >= 6), key=lambda cv: (cv[1]["risk"] > 0.03, cv[1]["risk"]))
    out = [f"⏱ <b>종가 진입 후보</b> {sc.get('at', '')} 기준 (봉 확정 전)"]
    try:
        st = market_status(db) or {}
        if (st.get("전체") or {}).get("state") == "하락":
            out.append("<i>시장 하락 국면 — 원칙상 쉬는 날, 참고만</i>")
    except Exception:  # noqa: BLE001
        pass
    try:
        br = market_breadth(db)
        if br.get("weak") or br.get("narrow"):
            out.append(f"⚠ 시장 폭 {br['pct']}% ({br['chg10']:+.1f}%p) — 속 약해짐, 크기 줄이기")
    except Exception:  # noqa: BLE001
        pass
    if not rows:
        out.append("점수 6↑ 종목 없음 → 쉬기")
        return "\n".join(out)
    good = [r for r in rows if r[1]["risk"] <= 0.03]
    out.append(f"점수 6↑ {len(rows)}개 · 그중 ✅ 손절폭 3%↓ {len(good)}개")
    for c, v in rows[:k]:
        out.append(f"{'✅' if v['risk'] <= 0.03 else '·'} <b>{names.get(c, c)}</b> {v['score']}/7 · 스탑로스 {v['stop']:,.0f} (-{v['risk'] * 100:.1f}%)")
    out.append("파는 법: 사면 바로 스탑로스 예약 (정규장만) · 21일선 아래 종가면 다음 날 아침 정리")
    out.append("<i>3년: ✅ 평균 +3.9% (손절폭의 1.7배) · 점수 6↑ 전체 +2.2% · 손절폭 8%↑는 얻을 게 없었음</i>")
    return "\n".join(out)


def send(db: Session) -> None:
    from backend.services.telegram import _get, send as tg_send  # noqa: PLC0415
    msg = text_now(db)
    if not msg:
        return
    for c in _get(db, "user_watchlist_chats", []) or list(_get(db, "telegram_chats", {}).keys())[:1]:
        tg_send(db, msg, c, html=True)
