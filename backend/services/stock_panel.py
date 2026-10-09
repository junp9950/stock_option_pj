"""종목 차트 창 오른쪽 패널 (2026-10-09, 사용자 "저 UI가 더 깔끔하노" — Lazy Alpha식 카드·칩·단계 막대를 우리 데이터로).

결론(상태 제목)을 먼저 크게, 근거는 ✓/⚠ 칩으로. 색약이라 색이 아니라 ✓·⚠ 모양으로 나눈다.
추세 조건 8개 = 미너비니 템플릿(150·200일선 위, 150>200, 200일선 상승, 50>150·200, 50일선 위, 52주 저점 +30%↑, 52주 고점 -25% 안, RS 70↑).
3년 확인(/home/junp/tmp_claude/la_validate.py): 8/8이면 상승장 60일 +9.0%, 2~5점은 마이너스. RS는 90~95가 가장 좋고 95↑는 오히려 나빴다.
"""
from __future__ import annotations

import threading
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

CYCLE_START = date(2026, 7, 30)
_RS: dict = {"key": None, "v": {}}
_RS_LOCK = threading.Lock()


def _rs_compute(db: Session, latest) -> dict:
    px = pd.read_sql(text("select stock_code s, trading_date d, close_price c, trading_value tv from spot_daily_prices "
                          "where trading_date >= cast(:d as date) - 380"), db.connection(), params={"d": latest})
    C = px.pivot(index="d", columns="s", values="c").sort_index().astype(float).ffill(limit=5)
    TV = px.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
    r = lambda k: C.iloc[-1] / C.iloc[-1 - k] - 1 if len(C) > k else C.iloc[-1] * np.nan
    raw = 0.4 * r(63) + 0.2 * r(126) + 0.2 * r(189) + 0.2 * r(min(252, len(C) - 1))
    ok = (TV.iloc[-20:].mean() >= 1e9) & raw.notna()
    rs = (raw[ok].rank(pct=True) * 98 + 1).round()
    return {"date": str(latest), "rs": {k: float(v) for k, v in rs.items()}}


def rs_table(db: Session) -> dict[str, float]:
    """전 종목 RS Rating(1~99, IBD식 0.4·3개월 + 0.2·6·9·12개월 백분위). 디스크 캐시라 재시작 직후에도 바로 (2026-10-09 "모든 탭 느리다")."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if _RS["key"] == latest:
        return _RS["v"]
    from backend.services.result_cache import cached  # noqa: PLC0415
    with _RS_LOCK:
        if _RS["key"] == latest:
            return _RS["v"]
        v = cached("rs_table_v1", (), db, lambda: _rs_compute(db, latest)) or {}
        if v.get("date") == str(latest):
            _RS.update(key=latest, v=v["rs"])
        return v.get("rs", {})


def _grade(tt: int) -> tuple[str, str]:
    return ("S", "강세") if tt >= 8 else ("H", "양호") if tt == 7 else ("N", "중립") if tt >= 5 else ("W", "약세") if tt >= 3 else ("D", "하락")


_PANEL: dict = {}


def panel(db: Session, code: str, owner: str | None = None) -> dict:
    """60초 캐시 (같은 종목을 다시 누르면 바로)."""
    import time  # noqa: PLC0415
    key = (code, owner)
    hit = _PANEL.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    v = _panel(db, code, owner)
    if len(_PANEL) > 300:
        _PANEL.clear()
    _PANEL[key] = (time.time(), v)
    return v


def _panel(db: Session, code: str, owner: str | None = None) -> dict:
    """owner(매매 일지 로그인)가 있을 때만 평단·손절·수익을 넣는다 — 공개 화면엔 금액·보유 정보 금지 (2026-10-09)."""
    name = db.execute(text("select name from stocks where code = :c"), {"c": code}).scalar() or code
    q = db.execute(text("select trading_date, open_price, high_price, low_price, close_price, volume from spot_daily_prices "
                        "where stock_code = :c order by trading_date desc limit 300"), {"c": code}).all()
    if len(q) < 30:
        return {"code": code, "name": name, "ok": False}
    df = pd.DataFrame(q[::-1], columns=["d", "o", "h", "l", "c", "v"]).set_index("d").astype(float)
    C, H, L, V = df.c, df.h, df.l, df.v
    c = float(C.iloc[-1]); prev = float(C.iloc[-2])
    ema = {k: float(C.ewm(span=k, adjust=False).mean().iloc[-1]) for k in (5, 10, 20, 60)}
    sma = {k: float(C.rolling(k, min_periods=int(k * .9)).mean().iloc[-1]) if len(C) >= k * .9 else np.nan for k in (20, 50, 150, 200)}
    s200_prev = C.rolling(200, min_periods=180).mean().iloc[-22] if len(C) >= 202 else np.nan
    hi52, lo52 = float(H.iloc[-250:].max()), float(L.iloc[-250:].min())
    rs = rs_table(db).get(code)
    nan = lambda x: x != x
    tt_list = [
        ("150·200일선 위", not nan(sma[150]) and not nan(sma[200]) and c > sma[150] and c > sma[200]),
        ("150일선 > 200일선", not nan(sma[150]) and not nan(sma[200]) and sma[150] > sma[200]),
        ("200일선 오르는 중", not nan(sma[200]) and not nan(s200_prev) and sma[200] > s200_prev),
        ("50일선 > 150·200일선", not nan(sma[50]) and not nan(sma[150]) and not nan(sma[200]) and sma[50] > sma[150] and sma[50] > sma[200]),
        ("50일선 위", not nan(sma[50]) and c > sma[50]),
        ("52주 저점 +30%↑", c >= lo52 * 1.3),
        ("52주 고점 -25% 안", c >= hi52 * 0.75),
        ("RS 70↑", rs is not None and rs >= 70),
    ]
    tt = sum(1 for _, v in tt_list if v)
    letter, word = _grade(tt)
    up = ema[5] > ema[10] > ema[20] > ema[60]
    down = ema[5] < ema[10] < ema[20] < ema[60]
    align = "정배열" if up else "역배열" if down else "엇갈림"
    spread = (max(ema[5], ema[10], ema[20]) / min(ema[5], ema[10], ema[20]) - 1) * 100
    gap20 = (c / sma[20] - 1) * 100 if not nan(sma[20]) else 0.0
    vx = float(V.iloc[-1] / V.iloc[-50:].mean()) if V.iloc[-50:].mean() else 0.0
    r20 = (c / float(C.iloc[-21]) - 1) * 100 if len(C) > 21 else 0.0
    since = df[df.index >= CYCLE_START]
    hi_cyc = float(since.h.max()) if len(since) else hi52
    support, resist = float(L.iloc[-21:-1].min()), float(H.iloc[-21:-1].max())

    # 섹터 (16개 중 이 종목이 속한 것 중 순위가 가장 높은 것)
    sector = None
    try:
        from backend.screener.rotation import family_members, scan, scan_live  # noqa: PLC0415
        from backend.services.result_cache import cached  # noqa: PLC0415
        fams = [f for f, m in family_members(db).items() if code in m]
        rot = scan_live(db) or cached("sector_rotation", (), db, lambda: scan(db))
        items = {x["family"]: x for x in rot.get("items", [])}
        best = sorted((items[f] for f in fams if f in items), key=lambda x: x["rank"])
        if best:
            b = best[0]
            sector = {"family": b["family"], "rank": b["rank"], "chg": b["chg_pct"], "money": b["tv1_x"], "status": b.get("status", "")}
    except Exception:  # noqa: BLE001
        pass

    # 보유 여부 (매매 일지) · 손절선 (관심 종목 hold 줄)
    held = None
    try:
        from backend.services import watchlist as W  # noqa: PLC0415
        pos = {p["code"]: p for p in W._positions(db, owner)} if owner else {}
        if code in pos:
            wl = {x["code"]: x for x in W._items(db)}
            stop = float(wl[code]["level"]) if code in wl and wl[code].get("kind") == "hold" and wl[code].get("level") else 0.0
            p = pos[code]
            held = {"qty": p["qty"], "avg": p["avg"], "stop": stop, "gain": (c * 0.998 / p["avg"] - 1) * 100 if p["avg"] else 0.0}
    except Exception:  # noqa: BLE001
        pass

    # 오늘 우리 후보 목록에 있나
    tags = []
    try:
        from backend.services.result_cache import cached  # noqa: PLC0415
        from backend.screener.my_pattern import scan as mp_scan  # noqa: PLC0415
        mp = cached("my_pattern_v6", (), db, lambda: mp_scan(db)) or {}
        for key, lab in (("box_break", "박스 위로 돌파 (며칠 보유)"), ("ema_break", "이평선 모였다 돌파"), ("box_near", "돌파 대기 · 박스 꼭대기")):
            if any(x.get("code") == code for x in mp.get(key, []) or []):
                tags.append(lab)
        from backend.services.telegram import _get  # noqa: PLC0415
        log = _get(db, "top3_log", {}) or {}
        if log and code in log.get(max(log), []):
            tags.insert(0, "종가 매수 후보")
    except Exception:  # noqa: BLE001
        pass

    # 우리 진입 신호(차트 ▲ 진입)가 지금 살아 있나
    act = None
    try:
        from backend.services.stock_signals import signals as _sig  # noqa: PLC0415
        act = _sig(db, code).get("active")
    except Exception:  # noqa: BLE001
        pass
    # 단계 · 상태 제목
    if held:
        room = (c / held["stop"] - 1) * 100 if held["stop"] else None
        if held["stop"] and c < held["stop"]:
            stage, title, sub = 4, "손절선 아래 마감", f"손절 {held['stop']:,.0f} · 정리 신호"
        elif room is not None and room <= 2:
            stage, title, sub = 3, "보유 중 · 손절선 근접", f"손절 {held['stop']:,.0f}까지 {room:.1f}%"
        else:
            stage, title = (3, "보유 중 · 수익") if held["gain"] >= 5 else (2, "보유 중")
            sub = f"손절 {held['stop']:,.0f}까지 {room:.1f}%" if room is not None else "손절선 없음 — 정해 두세요"
    elif act and act["days"] == 1:
        stage, title, sub = 1, "▲ 진입 신호 · 이번 봉", f"진입 {act['entry']:,.0f} · 스탑로스 {act['stop']:,.0f} 예약 ({(act['stop']/act['entry']-1)*100:+.1f}%) · 3년 평균 +2.6% · 이김 32%"
    elif act:
        stage = 3 if act["half"] else 2
        title = f"진입 신호 {act['days']}일째 · {act['gain']:+.1f}%"
        sub = f"{act['date'][5:].replace('-', '/')} 진입 {act['entry']:,.0f} · 스탑로스 {act['stop']:,.0f}" + (" · 절반 팔았음 (21일선 아래 종가면 다음 날 아침 나머지)" if act["half"] else " · 14일선 아래로 내려오면 절반 팔기")
    elif tags:
        stage, title = 1, tags[0]
        sub = " · ".join(tags[1:]) or "오늘 우리 후보 목록에 있음"
        if tags[0].startswith(("종가 매수", "✅ 손익비", "종가 점수")):
            # 사용자 (2026-10-09): "추세매매가 하고 싶은 거다 · 종베는 그냥 진입 시점일 뿐" → 종가에 사서 21일선까지 끌고 간다
            try:
                from backend.services.stock_signals import close_scores_now as _csn  # noqa: PLC0415
                _s = _csn(db).get("scores", {}).get(code)
            except Exception:  # noqa: BLE001
                _s = None
            _stop = _s["stop"] if _s else float(L.iloc[-1]) * 0.99
            # 2026-10-09 "스탑로스 걸어 놓고 냉정하게": 손절은 예약 주문, 추세 매도는 종가 판단 → 다음 날 아침
            sub = (f"종가에 진입 · 스탑로스 {_stop:,.0f}원 예약 (오늘 저가 -1%) · 21일선 아래 종가면 다음 날 아침 정리"
                   + (f" · {sub}" if tags[1:] else ""))
    elif up and c > ema[10] and spread <= 4:
        stage, title, sub = 0, "힘 모으는 중", f"이평선 정배열 · 5·10·20일선 간격 {spread:.1f}% · 종가가 10일선 위"
    else:
        stage, title, sub = 0, "관찰 중", f"이평선 {align}"

    chips = []
    try:
        from backend.services.stock_signals import close_scores_now as _cs  # noqa: PLC0415
        _sc = _cs(db).get("scores", {}).get(code)
        if _sc:
            chips.append((_sc["score"] >= 6, f"종가 점수 {_sc['score']}/7") if (_sc["score"] >= 6 or _sc["score"] <= 3) else None)
            chips.append((_sc["risk"] <= 0.03, f"손절폭 {_sc['risk'] * 100:.1f}%") if (_sc["risk"] <= 0.03 or _sc["risk"] >= 0.08) else None)
    except Exception:  # noqa: BLE001
        pass
    chips.append((tt >= 7, f"추세 조건 {tt}/8") if (tt >= 7 or tt <= 4) else None)
    if rs is not None:
        chips.append((False, f"RS {rs:.0f} · 과열권") if rs >= 95 else (True, f"RS {rs:.0f}") if rs >= 70 else (False, f"RS {rs:.0f} · 약함") if rs < 50 else None)
    chips.append((True, "정배열") if up else (False, "역배열") if down else None)
    chips.append((True, f"EMA 모임 {spread:.1f}%") if spread <= 4 else (False, f"EMA 벌어짐 {spread:.1f}%") if spread >= 7 else None)
    if gap20 >= 20:
        chips.append((False, f"20일선 +{gap20:.0f}% 과열"))
    chips.append((True, f"거래 실림 {vx:.1f}배") if vx >= 1.5 else (False, "거래 마름") if vx <= 0.5 else None)
    if not nan(sma[200]) and c < sma[200]:
        chips.append((False, "200일선 아래"))
    if sector and sector["rank"] <= 3:
        chips.append((True, f"주도 섹터 {sector['family']}"))
    chips = [{"ok": a, "text": b} for a, b in (x for x in chips if x)]

    if held:
        cards = [{"label": "평단", "value": f"{held['avg']:,.0f}", "sub": f"{held['qty']:,}주"},
                 {"label": "손절선", "value": f"{held['stop']:,.0f}" if held["stop"] else "-", "sub": f"{(held['stop']/c-1)*100:+.1f}%" if held["stop"] else "정해 두세요"},
                 {"label": "수익", "value": f"{held['gain']:+.1f}%", "sub": "세금·수수료 뺌"}]
    else:
        cards = [{"label": "지지 (20일 저가)", "value": f"{support:,.0f}", "sub": f"{(support/c-1)*100:+.1f}%"},
                 {"label": "저항 (20일 고가)", "value": f"{resist:,.0f}", "sub": f"{(resist/c-1)*100:+.1f}%"},
                 {"label": "52주 고가", "value": f"{hi52:,.0f}", "sub": f"{(hi52/c-1)*100:+.1f}%"}]

    csc = None
    try:
        from backend.services.stock_signals import CLOSE_FLAGS, close_scores_now  # noqa: PLC0415
        csc = close_scores_now(db).get("scores", {}).get(code)      # 장중이면 실시간 가격 기준
    except Exception:  # noqa: BLE001
        pass
    rows = [
        ({"k": "종가 진입 점수", "v": f"{'✅ ' if csc['score'] >= 6 and csc['risk'] <= 0.03 else ''}{csc['score']}/7 · 손절폭 {csc['risk'] * 100:.1f}%", "tip": " · ".join(f"{'✓' if f else '✗'} {n}" for n, f in zip(CLOSE_FLAGS, csc["flags"]))}
         if csc else {"k": "종가 진입 점수", "v": "추세 아님 (종가 > 20일선 > 60일선 아님)"}),
        {"k": "추세 조건", "v": f"{tt}/8", "tip": " · ".join(f"{'✓' if v else '✗'} {n}" for n, v in tt_list)},
        {"k": "RS Rating", "v": f"{rs:.0f}" if rs is not None else "-"},
        {"k": "이평선 (5·10·20·60)", "v": align},
        {"k": "EMA 5·10·20 간격", "v": f"{spread:.1f}%"},
        {"k": "20일 수익률", "v": f"{r20:+.1f}%"},
        {"k": "20일선 이격", "v": f"{gap20:+.1f}%"},
        {"k": "거래량 (50일 평균 대비)", "v": f"{vx*100:.0f}%"},
        {"k": "52주 고점 대비", "v": f"{(c/hi52-1)*100:+.1f}%"},
        {"k": "7/30 이후 고점 대비", "v": f"{(c/hi_cyc-1)*100:+.1f}%"},
    ]
    if sector:
        rows.append({"k": "섹터", "v": f"{sector['family']} {sector['rank']}위 · 오늘 {sector['chg']:+.1f}%" + (f" · {sector['status']}" if sector["status"] else "")})
    try:
        from backend.services.result_cache import peek  # noqa: PLC0415
        st = peek("dashboard_core_v6")
        st = st[0] if isinstance(st, (list, tuple)) else None
        if st and st.get("코스피"):
            rows.append({"k": "시장 (코스피)", "v": st["코스피"]["state"]})
    except Exception:  # noqa: BLE001
        pass
    # 신호 앞 체크리스트 (Lazy Alpha 교육 '5초 체크리스트'를 우리 검증 기준으로): 하나라도 ⚠면 약한 고리 (2026-10-09)
    checks = []
    try:
        from backend.services.stock_signals import _bull_days, market_breadth  # noqa: PLC0415
        bull_now = _bull_days(db).get(df.index[-1], False)
        brd = market_breadth(db)
        if bull_now and not brd.get("weak") and not brd.get("narrow"):
            checks.append({"ok": True, "k": "시장 상태", "v": f"시장 상승·횡보 · 시장 폭 {brd['pct']}%"})
        else:
            why = "하락 국면" if not bull_now else ("속 약해짐 (지수는 오르는데 폭 감소)" if brd.get("weak") else "시장 폭 좁음")
            checks.append({"ok": False, "k": "시장 상태", "v": why})
    except Exception:  # noqa: BLE001
        pass
    strong = tt >= 6 and rs is not None and 70 <= rs < 95
    checks.append({"ok": strong, "k": "강한 종목", "v": f"추세 조건 {tt}/8 · RS {rs:.0f}" + ("" if strong else (" (RS 95↑는 과열권)" if rs is not None and rs >= 95 else ""))} if rs is not None else
                  {"ok": False, "k": "강한 종목", "v": f"추세 조건 {tt}/8 · RS 없음"})
    good_spot = gap20 < 15 and spread <= 7
    checks.append({"ok": good_spot, "k": "좋은 자리", "v": f"20일선 {gap20:+.0f}% · 이평선 간격 {spread:.1f}%" + ("" if good_spot else " (멀리 옴 · 추격 주의)")})
    if act and act["days"] == 1:
        checks.append({"ok": True, "k": "신호", "v": "▲ 진입 · 장 마감 확정"})
    elif tags:
        checks.append({"ok": True, "k": "신호", "v": f"{tags[0]} · 장 마감 기준"})
    else:
        checks.append({"ok": False, "k": "신호", "v": "아직 확정 신호 없음"})
    if act:                                   # 스윙 진입: 신호 봉 저가 -1%
        stop_ref, stop_lab = act["stop"], "진입 손절"
    else:                                     # 종가 진입: 오늘 저가 -1% (3년: 손절폭 3%↓ R +1.7 · 8%↑ R 0, trend_exit.py)
        stop_ref, stop_lab = float(L.iloc[-1]) * 0.99, "스탑로스(오늘 저가 -1%)"
    dist = (1 - stop_ref / c) * 100 if stop_ref else 99      # 종가에서 손절선까지 내려가는 폭 (목록의 손절폭과 같은 기준)
    checks.append({"ok": dist <= 5, "k": "손절 거리", "v": f"{stop_lab} {stop_ref:,.0f}까지 {dist:.1f}%"
                   + (" ✅ 손익비 좋음 (3%↓)" if dist <= 3 else "" if dist <= 5 else " (멀어서 손익비 나쁨 · 3년: 8%↑면 얻을 게 없었음)")})
    disp_c, disp_chg = c, (c / prev - 1) * 100
    try:      # 보여 주는 종가·등락은 정규장 15:30 기준 (DB 종가엔 시간외가 섞인다)
        from backend.services.naver_live import krx_day  # noqa: PLC0415
        k = krx_day(code)
        if k and k["base"]:
            disp_c, disp_chg = k["close"], (k["close"] / k["base"] - 1) * 100
    except Exception:  # noqa: BLE001
        pass
    return {"code": code, "name": name, "ok": True, "date": str(df.index[-1]), "close": disp_c, "chg": disp_chg,
            "grade": {"letter": letter, "word": word}, "stage": stage, "title": title, "sub": sub,
            "chips": chips, "cards": cards, "rows": rows, "held": bool(held), "checks": checks}
