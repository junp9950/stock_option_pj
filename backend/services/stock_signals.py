"""차트에 찍을 신호 — 우리 검증 규칙을 한 종목 일봉에 거슬러 적용 (2026-10-09 사용자 "차트에 조건들 넣어서 신호 넣고").

섹터·시장 조건이 필요한 규칙(조건 B 섹터 돈, 박스 돌파 섹터 돈)은 종목 하나만으로는 못 보니 종목 자체 조건만 쓴다.
그래서 차트 신호는 '이 종목에서 그 모양이 나온 자리'이고, 오늘 후보 목록(섹터·시장까지 본 것)과 다를 수 있다.
  기준봉        +8%↑ · 거래 3배↑ 양봉
  박스 돌파     20일 박스 폭 20%↓ → 전 20일 고가 위 종가 · +5%↑ · 거래대금 2배↑ · 200일선 위   (3년 10일 +6% 안팎, 상승장·섹터 돈 조건 포함 시)
  EMA 모임 돌파 전날 EMA5·10·20 간격 4%↓ → 종가가 세 선과 전 10일 고가 위 · +3%↑ · 거래대금 1.5배↑   (5일 +0.9~1.0%)
  종베 모양     +3~29% · 20일 +12%↑ · 20일선 이격 30%↓ · 윗꼬리 10%↓ · 거래대금 1.5~6배
  주차 도지     기준봉 뒤 1~5일 안 도지(몸통 1%↓), 기준봉 종가 -3% 안
  조용한 음봉   오르던 종목(20일 +15%↑ · 20일선 위 · 20일선 > 60일선)의 거래 0.5~0.8배 음봉   (5일 +0.7%, 0.5배↓은 오히려 나쁨)
  ⚠ 꽉 찬 음봉  -4%↓ · 몸통 80%↑ · 밑꼬리 10%↓ · 거래 2배↑   (오르던 종목이면 5일 -1.5%)
  거래 신기록   1년 최대 거래대금 · 평소 3배↑
그리고 매매 일지의 실제 매수·매도 자리.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


def signals(db: Session, code: str, days: int = 160) -> dict:
    q = db.execute(text("select trading_date, open_price, high_price, low_price, close_price, volume, trading_value from spot_daily_prices "
                        "where stock_code = :c order by trading_date desc limit 520"), {"c": code}).all()
    if len(q) < 60:
        return {"code": code, "items": []}
    df = pd.DataFrame(q[::-1], columns=["d", "o", "h", "l", "c", "v", "tv"]).set_index("d").astype(float)
    O, H, L, C, V, TV = df.o, df.h, df.l, df.c, df.v, df.tv
    chg = C / C.shift(1) - 1
    tvx = TV / TV.rolling(20).mean().shift(1)
    vx = V / V.rolling(20).mean().shift(1)
    rng = (H - L).replace(0, np.nan)
    e5, e10, e20, e60 = (C.ewm(span=n, adjust=False).mean() for n in (5, 10, 20, 60))
    ehi = pd.concat([e5, e10, e20], axis=1).max(axis=1); elo = pd.concat([e5, e10, e20], axis=1).min(axis=1)
    gap_prev = ((ehi - elo) / C).shift(1)
    ma20, ma60 = C.rolling(20).mean(), C.rolling(60).mean()
    ma200 = C.rolling(200, min_periods=180).mean()
    hi20p, lo20p = H.shift(1).rolling(20).max(), L.shift(1).rolling(20).min()
    hi10p = H.shift(1).rolling(10).max()
    r20 = C.shift(1) / C.shift(21) - 1
    upper = (H - pd.concat([O, C], axis=1).max(axis=1)) / rng
    lower = (pd.concat([O, C], axis=1).min(axis=1) - L) / rng
    body = (C - O).abs() / rng

    big = (chg >= 0.08) & (vx >= 3) & (C > O)
    box = (hi20p / lo20p - 1 <= 0.20) & (C > hi20p) & (chg >= 0.05) & (tvx >= 2) & (C > ma200)
    ema = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)
    jb = (chg >= 0.03) & (chg < 0.29) & (r20 >= 0.12) & (C / ma20 - 1 <= 0.30) & (upper <= 0.10) & (tvx >= 1.5) & (tvx <= 6)
    doji = ((C - O).abs() / O <= 0.01) & (body <= 0.35)
    after_big = pd.Series(False, index=df.index)
    big_close = pd.Series(np.nan, index=df.index)
    for k in range(1, 6):
        after_big |= big.shift(k, fill_value=False)
        big_close = big_close.fillna(C.where(big).shift(k))
    park = doji & after_big & (C >= big_close * 0.97)
    uptrend = (r20 >= 0.15) & (C > ma20) & (ma20 > ma60)
    quiet = uptrend & (C < O) & (chg < 0) & (chg > -0.06) & (vx >= 0.5) & (vx < 0.8)
    fullbear = (chg <= -0.04) & ((O - C) / rng >= 0.8) & (lower <= 0.10) & (vx >= 2)
    record = (TV >= TV.shift(1).rolling(250, min_periods=200).max()) & (tvx >= 3)

    rules = [  # (마스크, 라벨, 종류, 위/아래) — 위에서부터 우선 (한 봉에 여러 개면 앞의 것 2개까지)
        (box, "박스 돌파", "buy", "below"), (ema, "EMA 모임 돌파", "buy", "below"), (jb, "종베 모양", "buy", "below"),
        (park, "주차 도지", "buy", "below"), (quiet, "조용한 음봉", "rest", "below"),
        (big, "기준봉", "info", "above"), (record, "거래 신기록", "info", "above"), (fullbear, "⚠ 꽉 찬 음봉", "warn", "above"),
    ]
    start = df.index[-min(days, len(df))]
    items = []
    for mask, lab, kind, pos in rules:
        for d in mask[mask.fillna(False) & (mask.index >= start)].index:
            price = float(L[d]) if pos == "below" else float(H[d])
            items.append({"date": str(d), "label": lab, "kind": kind, "pos": pos, "price": price})
    # 매매 일지 실제 매수·매도 (같은 날 같은 방향은 평균가로 묶음)
    try:
        for d, side, qty, amt in db.execute(text(
                "select trade_date, side, sum(qty), sum(amount) from trade_executions where owner = 'junp' and code = :c and trade_date >= :s "
                "group by 1, 2 order by 1"), {"c": code, "s": start}).all():
            if qty:
                items.append({"date": str(d), "label": f"{'매수' if side == '매수' else '매도'} {amt / qty:,.0f}", "kind": "trade_buy" if side == "매수" else "trade_sell",
                              "pos": "below" if side == "매수" else "above", "price": float(amt / qty)})
    except Exception:  # noqa: BLE001
        pass
    items.sort(key=lambda x: x["date"])
    return {"code": code, "items": items}


_KRX: dict = {"key": None, "v": {}}


def _krx_closes(codes: list[str], key: str) -> dict[str, tuple[float, float]]:
    """종목별 직전 거래일 정규장 종가·등락 (하루 한 번, 8개씩 동시에 받아 캐시)."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    from backend.services.naver_live import krx_day  # noqa: PLC0415
    if _KRX["key"] != key:
        _KRX.update(key=key, v={})
    need = [c for c in codes if c not in _KRX["v"]]
    if need:
        with ThreadPoolExecutor(8) as ex:
            for c, k in zip(need, ex.map(lambda c_: krx_day(c_), need)):
                _KRX["v"][c] = (k["close"], (k["close"] / k["base"] - 1) * 100) if k and k.get("base") else None
    return {c: _KRX["v"][c] for c in codes if _KRX["v"].get(c)}


def workspace_list(db: Session) -> dict:
    """첫 화면 왼쪽 목록: 오늘 후보 · 보유 · 관심 (2026-10-09). 장중이면 네이버 실시간 가격."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from backend.services import watchlist as W  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    from backend.services.result_cache import peek  # noqa: PLC0415
    names = dict(db.execute(text("select code, name from stocks")).all())
    cand: dict[str, dict] = {}

    def add(code, tag, family=""):
        if not code:
            return
        x = cand.setdefault(code, {"code": code, "name": names.get(code, code), "tags": [], "family": family})
        if tag not in x["tags"]:
            x["tags"].append(tag)
        if family and not x["family"]:
            x["family"] = family

    log = _get(db, "top3_log", {}) or {}
    if log:
        for c in log.get(max(log), []):
            add(c, "종베 3")
    mp = (peek("dashboard_core_v6") or (None, None))[1] or peek("my_pattern_v6") or {}
    try:
        from backend.screener.my_pattern import cap_sectors  # noqa: PLC0415
        b = [x for x in mp.get("items", []) if x.get("b") and 1.5 <= x["tv_x"] <= 6 and x["upper_pct"] <= 10]
        for x in cap_sectors([x for x in b if (x.get("b_rank") or 99) <= 3], mp.get("heat", {}))[:5]:
            add(x["code"], "종베 (주도 섹터)", x.get("family", ""))
        for x in cap_sectors([x for x in b if 4 <= (x.get("b_rank") or 99) <= 8], mp.get("heat", {}))[:5]:
            add(x["code"], "스윙 (올라오는 섹터)", x.get("family", ""))
    except Exception:  # noqa: BLE001
        pass
    for key, tag in (("box_break", "박스 돌파"), ("ema_break", "EMA 모임 돌파"), ("box_near", "박스 뚫기 직전"), ("ema_wait", "EMA 모임 대기")):
        for x in (mp.get(key) or [])[:6]:
            add(x.get("code"), tag, x.get("family", ""))
    if (mp.get("mode") or {}).get("mode") == "과매도":
        for s in mp.get("dip", [])[:3]:
            for x in s.get("items", [])[:2]:
                add(x.get("code"), "과매도 줍기", s.get("family", ""))
    skip = set(_get(db, "held_exclude", None) or W.HELD_EXCLUDE)
    wl = {x["code"]: x for x in W._items(db)}
    held = []
    for p in W._positions(db):
        w = wl.get(p["code"], {})
        held.append({"code": p["code"], "name": p["name"], "avg": round(p["avg"]), "qty": p["qty"], "long": p["code"] in skip,
                     "stop": float(w["level"]) if w.get("kind") == "hold" and w.get("level") else 0.0})
    watch = [{"code": x["code"], "name": x["name"], "kind": x.get("kind"), "level": x.get("level") or 0, "note": x.get("note", "")}
             for x in wl.values() if x["code"] not in {h["code"] for h in held}]
    codes = list({*cand, *(h["code"] for h in held), *(w["code"] for w in watch)})
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = {r[0]: (float(r[1]), float(r[2] or 0)) for r in db.execute(text(
        "select stock_code, close_price, change_pct from spot_daily_prices where trading_date = :d and stock_code = any(:c)"), {"d": latest, "c": codes}).all()}
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    live_at = None
    px.update(_krx_closes(codes, str(latest)))        # 장 마감 뒤·휴장일엔 정규장 15:30 종가로 (DB 종가엔 시간외가 섞임)
    if now.weekday() < 5 and 9 <= now.hour < 16 and latest < now.date():
        try:
            from backend.services.naver_live import snapshot  # noqa: PLC0415
            lv = snapshot(sorted(codes), max_age=30)
            for c, v in lv.items():
                px[c] = (v["c"], v["chg"] or 0.0)
            if lv:
                live_at = now.strftime("%H:%M")
        except Exception:  # noqa: BLE001
            pass
    def price(x):
        c, ch = px.get(x["code"], (0.0, 0.0))
        return {**x, "close": c, "chg": round(ch, 2)}
    held = [price(h) for h in held]
    for h in held:
        h["gain"] = round((h["close"] * 0.998 / h["avg"] - 1) * 100, 1) if h["avg"] and h["close"] else None
        h["room"] = round((h["close"] / h["stop"] - 1) * 100, 1) if h["stop"] and h["close"] else None
    held.sort(key=lambda h: (h["long"], h["room"] if h["room"] is not None else 99))
    return {"as_of": str(latest), "live": live_at, "mode": mp.get("mode"),
            "candidates": [price(x) for x in cand.values()], "held": held, "watch": sorted((price(w) for w in watch), key=lambda w: -w["chg"])}
