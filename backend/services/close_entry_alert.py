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
    allr = [(c, v) for c, v in sc["scores"].items() if (v["score"] >= 6 or v.get("ema") or v.get("hot") or v.get("semi")) and v["flags"][1]]     # 시장보다 센 종목(RS 70~95)만 · 이평선 모였다 돌파 포함
    lim = lambda v: 0.12 if v.get("semi") else 0.08          # 반도체·AI 특별은 손절폭 12%까지
    wide = [cv for cv in allr if cv[1]["risk"] > lim(cv[1])]          # 손절폭 8%↑는 뺀다 (3년 R +0.11) · 5~8%는 후순위 (R +0.35)
    rows = sorted((cv for cv in allr if cv[1]["risk"] <= lim(cv[1])), key=lambda cv: cv[1]["risk"])
    out = [f"⏱ <b>종가 진입 후보</b> {sc.get('at', '')} 기준 (봉 확정 전)"]
    try:
        st = market_status(db) or {}
        if (st.get("전체") or {}).get("state") == "하락":
            out.append("<i>시장 하락 국면 — 원칙상 쉬는 날, 참고만</i>")
    except Exception:  # noqa: BLE001
        pass
    try:
        br = market_breadth(db)
        if br.get("temp") and br["temp"] != "보통":
            out.append(f"{'⚠' if br.get('temp_k') == 'up' else '⬇'} 시장 {br['temp']} (어제 마감 기준) — {br.get('temp_say', '')}")
        if br.get("weak") or br.get("narrow"):
            out.append(f"⚠ 시장 폭 {br['pct']}% ({br['chg10']:+.1f}%p) — 곧 흔들릴 수 있음 · 새로 쫓지 말고 빠지는 날 줍기 준비")
    except Exception:  # noqa: BLE001
        pass
    try:      # 급락 날 줍기 (시장 -2%↓ 날 같이 빠진 센 종목 · 손절 20일선 · 수량 절반)
        from backend.services.stock_signals import dip_now  # noqa: PLC0415
        dp = dip_now(db)
        if dp.get("items"):
            out.append(f"⬇ <b>급락 날 줍기 (시험 중)</b> 시장 {dp.get('market', 0):+.1f}% · 뜨는 섹터 {', '.join(dp.get('sectors', []))} · 같이 빠진 주도주 {len(dp['items'])}개")
            out.append("  종가에 수량 절반 · 손절 20일선 · 21일선 아래 종가면 다음 날 아침 정리")
            for x in dp["items"][:8]:
                out.append(f"  · <b>{x['name']}</b> {x['chg']:+.1f}% · 손절 {x['stop']:,.0f} (-{x['risk']:.1f}%)")
    except Exception:  # noqa: BLE001
        pass
    lead_lines = []
    try:      # 주도주 (V1.0 아님 · 이번 장 한정 별도 전략 L, 2026-10-10) — V1.0 목록 뒤에 붙인다
        from backend.services.forward_log import lead_state  # noqa: PLC0415
        ls = lead_state(db)
        leads = sorted([(c, v) for c, v in sc["scores"].items() if v.get("lead") and not v.get("buy")], key=lambda cv: -(cv[1].get("rs") or 0))
        if leads:
            lead_lines.append(f"🔥 <b>주도주 · 강도 최상위(RS 95↑)</b> — 기본 신호와 별도로 소량 · 이번 장 한정 · 거래당 위험 0.10% · 2종목까지 — " + ("켜짐" if ls["on"] else f"쉬는 중: {ls['why']}")
                              + (f" · ⚠️ 경고: {ls['warn']}" if ls.get("warn") else ""))
            for c, v in leads[:5]:
                lead_lines.append(f"  · <b>{names.get(c, c)}</b> RS {v.get('rs') or 0:.0f} · 스탑로스 {v['stop']:,.0f} (-{v['risk'] * 100:.1f}%)")
    except Exception:  # noqa: BLE001
        pass
    if not rows:
        out.append("매수 신호 (손절폭 8%↓) 종목 없음 → 쉬기" + (f" (손절폭 넓어서 뺀 것 {len(wide)}개)" if wide else ""))
        return "\n".join(out + lead_lines)
    good = [r for r in rows if r[1]["risk"] <= 0.03 and not r[1].get("hot") and not r[1].get("semi")]
    out.append(f"매수 신호 {len(rows)}개 · ✅ 손절폭 3%↓ {len(good)}개" + (f" · 8%↑라 뺀 것 {len(wide)}개" if wide else ""))
    try:
        from backend.services.stock_signals import sector_rank_of  # noqa: PLC0415
        srk = sector_rank_of(db)
    except Exception:  # noqa: BLE001
        srk = {}
    # 순서 = 강도(RS) 높은 순 (2026-10-10 바꿈: 12년 검증에서 RS 순으로 고르면 무작위 순서 10,000번 중 100백분위,
    # 예전 '섹터 1~8위 먼저 → 손절폭 짧은 순'은 무작위와 비슷했음 · ranking_lab.py / site_order_check.py)
    rows = sorted(rows, key=lambda cv: -(cv[1].get("rs") or 0))
    out.append("순서: 강도(RS) 높은 순 — 칸이 모자라면 위에서부터 (12년 검증)")
    for c, v in rows[:k]:
        out.append(f"{'✅' if v['risk'] <= 0.03 and not v.get('hot') and not v.get('semi') else '·'} <b>{names.get(c, c)}</b> RS {v.get('rs') or 0:.0f} · {'이평선 돌파 · ' if v.get('ema') else ''}{'과열 매수(이번 장) · 수량 절반 · ' if v.get('hot') else ''}{'반도체·AI 특별 · 수량 절반 · ' if v.get('semi') else ''}{v['score']}/7 · 스탑로스 {v['stop']:,.0f} (-{v['risk'] * 100:.1f}%)"
                   + (" · 후순위, 수량 절반 이하" if v["risk"] > 0.05 and not v.get("semi") else "")
                   + (f" · {srk[c][1]} {srk[c][0]}위" if srk.get(c, (99,))[0] <= 8 else " · 섹터 밖"))
    out += lead_lines
    out.append("파는 법: 사면 바로 스탑로스 예약 (정규장만) · 21일선 아래 종가면 다음 날 아침 정리")
    out.append("<i>3년(같은 위험 금액당): 손절폭 3%↓ 1.4배 · 3~5% 0.55배 · 5~8% 0.35배 · 8%↑ 0.1배 벎 → 수량은 손절폭에 맞춰</i>")
    return "\n".join(out)


def send(db: Session) -> None:
    from backend.services.telegram import _get, send as tg_send  # noqa: PLC0415
    msg = text_now(db)
    if not msg:
        return
    for c in _get(db, "user_watchlist_chats", []) or list(_get(db, "telegram_chats", {}).keys())[:1]:
        tg_send(db, msg, c, html=True)
