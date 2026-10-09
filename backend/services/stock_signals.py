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


_REG: dict = {"key": None, "v": {}}


def _bull_days(db: Session) -> dict:
    """날짜별 시장 국면이 상승·횡보인가 (전 종목 평균 등락으로 regime_series) — DB 날짜가 바뀔 때만 계산."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if _REG["key"] == latest:
        return _REG["v"]
    from backend.screener.market_regime import regime_series  # noqa: PLC0415
    rows = db.execute(text("select trading_date, avg(greatest(least(change_pct, 30), -30)) from spot_daily_prices "
                           "where trading_date >= cast(:d as date) - 900 and trading_value >= 1e9 and change_pct <> 'NaN' group by 1 order by 1"), {"d": latest}).all()
    reg = regime_series({d: float(v) for d, v in rows if v is not None})
    _REG.update(key=latest, v={d: r["state"] in ("상승", "횡보") for d, r in reg.items()})
    return _REG["v"]


def signals(db: Session, code: str, days: int = 260, owner: str | None = None) -> dict:
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
    # 큰 음봉은 '오르던 종목'일 때만 위험 (3년: 5일 -1.5%) — 전체로는 10일 +0.7%로 오히려 반등 (park_wick.py 2026-10-09)
    fullbear = (chg <= -0.04) & ((O - C) / rng >= 0.8) & (lower <= 0.10) & (vx >= 2) & (r20 >= 0.15)
    # 급등 뒤 쉬는 봉 중 윗꼬리 길고(폭의 50%↑) 거래 1.5배↑ = 위에서 물량 — 3년 10일 -1.7% (사용자 "윗꼬리 큰 쉬는 봉이 맞나")
    park_sell = park & (upper >= 0.5) & (vx >= 1.5)
    record = (TV >= TV.shift(1).rolling(250, min_periods=200).max()) & (tvx >= 3)

    # 아깝게 놓친 자리 (조건 하나만 살짝 모자람) — 문턱은 그대로, 왜 안 걸렸는지만 흐리게 (2026-10-09 테크윙 9/29·10/1)
    box_core = (C > hi20p) & (C > ma200)
    box_w = hi20p / lo20p - 1
    near_box_vol = box_core & (box_w <= 0.20) & (chg >= 0.05) & (tvx >= 1.4) & (tvx < 2) & ~box
    near_box_w = box_core & (box_w > 0.20) & (box_w <= 0.27) & (chg >= 0.05) & (tvx >= 2) & ~box
    ema_core = (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29)
    near_ema_gap = ema_core & (gap_prev > 0.04) & (gap_prev <= 0.05) & (tvx >= 1.5) & ~ema
    near_ema_vol = ema_core & (gap_prev <= 0.04) & (tvx >= 1.2) & (tvx < 1.5) & ~ema
    near_big = (chg >= 0.08) & (C > O) & (vx >= 2.4) & (vx < 3) & ~big
    align = (e5 > e10) & (e10 > e20) & (e20 > e60)
    align_start = align & ~align.shift(1, fill_value=False)
    def _lab(base, ser, fmt):
        return {d: f"{base}? {fmt(ser[d])}" for d in ser.index}
    near = []
    for mask, base, val, fmt in ((near_box_vol, "박스 돌파", tvx, lambda v: f"거래 부족 {v:.1f}배"), (near_box_w, "박스 돌파", box_w, lambda v: f"박스 폭 {v*100:.0f}%"),
                                 (near_ema_gap, "이평선 돌파", gap_prev, lambda v: f"이평선 간격 {v*100:.1f}%"), (near_ema_vol, "이평선 돌파", tvx, lambda v: f"거래 부족 {v:.1f}배"),
                                 (near_big, "급등봉", vx, lambda v: f"거래 부족 {v:.1f}배")):
        for d in mask[mask.fillna(False)].index:
            near.append((d, f"아깝게 놓친 {base} ({fmt(float(val[d]))})"))
    rules = [  # (마스크, 라벨, 종류, 위/아래) — 위에서부터 우선 (한 봉에 여러 개면 앞의 것 2개까지)
        # 3년 상승장 10일: 박스 돌파 +1.5% · 이평선 돌파 +0.7% · 거래 적은 눌림 +0.7% (기준 +0.2%) — 사는 자리로 표시
        # 거래 실린 양봉(섹터 조건 없이 5일 -0.05%)·급등 뒤 쉬는 봉(-0.3%)은 검증이 약해 참고 점으로 내림 (2026-10-09)
        (box, "박스 위로 돌파", "buy", "below"), (ema, "이평선 모였다 돌파", "buy", "below"), (quiet, "거래 적은 눌림", "rest", "below"),
        (park_sell, "⚠ 급등 뒤 윗꼬리 매물", "warn", "above"),
        (park & ~park_sell, "급등 뒤 쉬는 봉 (참고)", "note", "below"), (jb, "거래 실린 양봉 (참고)", "note", "below"),
        (big, "급등봉", "info", "above"), (record, "1년 최대 거래", "info", "above"), (fullbear, "⚠ 거래 많은 큰 음봉", "warn", "above"),
    ]
    start = df.index[-min(days, len(df))]
    items = []
    for mask, lab, kind, pos in rules:
        for d in mask[mask.fillna(False) & (mask.index >= start)].index:
            price = float(L[d]) if pos == "below" else float(H[d])
            items.append({"date": str(d), "label": lab, "kind": kind, "pos": pos, "price": price})
    # ▲ 진입 신호 (2026-10-09 "우리도 진입 신호 같은 건 좀"): (박스 돌파 또는 EMA 모임 돌파·정배열) + 상승·횡보장 + 추세 조건 6/7↑
    # 3년(entry_sig.py, 종가 진입): 1,223건 평균 +3.4% · 이김 36% · 평균 14일 / 하락장이면 -1.7%라 안 냄.
    # 흐름: 손절 = 신호 봉 저가 -1%에 예약 매도(장중 닿으면, 시가가 아래면 시가) · ½ 익절 = EMA14 아래 종가 · 청산 = EMA21 아래 종가. 들고 있는 동안은 새 진입 안 냄.
    # 2026-10-09 사용자 "스탑로스 걸어 놓고 냉정하게" → 예약 손절 3년(entry_stop.py) 1,513건 평균 +2.59%·R +0.51·최악5% -1.0R (종가 손절 +3.06%·R +0.60·최악5% -1.66R)
    e14, e21 = C.ewm(span=14, adjust=False).mean(), C.ewm(span=21, adjust=False).mean()
    s50, s150 = C.rolling(50).mean(), C.rolling(150, min_periods=135).mean()
    hi52, lo52 = H.rolling(250, min_periods=200).max(), L.rolling(250, min_periods=200).min()
    tt7 = (((C > s150) & (C > ma200)).astype(int) + (s150 > ma200).astype(int) + (ma200 > ma200.shift(21)).astype(int)
           + ((s50 > s150) & (s50 > ma200)).astype(int) + (C > s50).astype(int) + (C >= lo52 * 1.3).astype(int) + (C >= hi52 * 0.75).astype(int))
    up60 = (C > e60) & (e20 > e60)
    bulls = _bull_days(db)
    bull = pd.Series([bulls.get(d, False) for d in df.index], index=df.index)
    # 급등봉·과열 당일은 진입 안 냄 (2026-10-09 LG에너지솔루션 4/21 +11.4% 진입 → 손절): 그날 +8% 미만 · 20일선 +15% 안
    # 3년: 1,223건 평균 +3.4% · 이김 36% · 최악10% -10.9% (빠진 급등봉·과열 진입은 +2.1% · 최악10% -17%) — entry_sig2.py
    entry_m = (box | (ema & up60)) & bull & (tt7 >= 6) & (chg < 0.08) & (C / ma20 - 1 < 0.15)
    active = None
    idx = list(df.index)
    i = idx.index(start) if start in idx else 0
    while i < len(idx):
        d = idx[i]
        if not entry_m.iloc[i]:
            i += 1
            continue
        p0, stop = float(C.iloc[i]), float(L.iloc[i]) * 0.99
        items.append({"date": str(d), "label": f"▲ 진입 {p0:,.0f}", "kind": "entry", "pos": "below", "price": float(L.iloc[i])})
        half, out = False, None
        for k in range(i + 1, len(idx)):
            c = float(C.iloc[k])
            if float(L.iloc[k]) < stop:          # 예약 손절 (장중 닿으면 체결, 시가가 손절가 아래면 시가)
                px = min(float(O.iloc[k]) or stop, stop)
                out = (k, f"손절 {(px/p0-1)*100:+.1f}%", "exit_bad"); break
            if not half and k - i > 1 and c < float(e14.iloc[k]):
                half = True
                items.append({"date": str(idx[k]), "label": f"절반 팔기 {(c/p0-1)*100:+.1f}%", "kind": "exit", "pos": "above", "price": float(H.iloc[k])})
            if k - i > 1 and c < float(e21.iloc[k]):
                out = (k, f"나머지 팔기 {(c/p0-1)*100:+.1f}%", "exit"); break
        if out:
            k, lab, kind = out
            items.append({"date": str(idx[k]), "label": lab, "kind": kind, "pos": "above", "price": float(H.iloc[k])})
            i = k + 1
        else:
            last_c = float(C.iloc[-1])
            active = {"date": str(d), "entry": p0, "stop": stop, "days": len(idx) - i, "gain": (last_c / p0 - 1) * 100, "half": half}
            break
    # 종가 진입 점수 6↑ 자리 (close_scores와 같은 7개 조건, 상승·횡보장만) — 사용자 목표 "종가에 안전하고 확률 높은 추세 종목".
    # ▲ 진입은 '거래 실린 돌파일'만 잡아서 거래 없이 계단식으로 오르는 종목(SK이노베이션 9~10월)은 비어 보였다 (2026-10-09).
    try:
        rh = rs_hist(db)
        rs_arr = rh.get("rs", {}).get(code)
        if rs_arr is not None:
            RS = pd.Series(rs_arr.astype(float), index=[pd.Timestamp(x).date() for x in rh["dates"]]).reindex(df.index)
            ehi_t = pd.concat([e5, e10, e20], axis=1).max(axis=1); elo_t = pd.concat([e5, e10, e20], axis=1).min(axis=1)
            fl = [C / H.rolling(60).max() - 1 >= -0.05, (RS >= 70) & (RS < 95), (vx >= 0.7) & (vx < 3), (C - L) / rng >= 0.7,
                  (chg >= 0) & (chg < 0.08), C / ma20 - 1 < 0.15, (ehi_t - elo_t) / C < 0.06]
            base_ok = (C > e20) & (e20 > e60) & (TV.rolling(20).mean() >= 3e9) & bull
            sc = sum(f.fillna(False).astype(int) for f in fl)
            for d in sc[(sc >= 6) & base_ok & (sc.index >= start)].index:
                miss = [CLOSE_FLAGS[j] for j, f in enumerate(fl) if not bool(f[d])]
                items.append({"date": str(d), "label": f"종가 점수 {int(sc[d])}/7" + (f" (빠짐: {miss[0]})" if miss else ""), "kind": "score",
                              "pos": "below", "price": float(L[d]), "score": int(sc[d])})
    except Exception:  # noqa: BLE001
        pass
    for d, lab in near:
        if d >= start:
            items.append({"date": str(d), "label": lab, "kind": "near", "pos": "below", "price": float(L[d])})
    for d in align_start[align_start & (align_start.index >= start)].index:
        items.append({"date": str(d), "label": "상승 추세 시작", "kind": "note", "pos": "above", "price": float(H[d])})
    # 지금 상태 (오늘 후보 목록의 '대기') — 마지막 봉에 점선으로
    try:
        from backend.services.result_cache import cached  # noqa: PLC0415
        from backend.screener.my_pattern import scan as mp_scan  # noqa: PLC0415
        mp = cached("my_pattern_v6", (), db, lambda: mp_scan(db)) or {}
        last_d = df.index[-1]
        for key, lab in (("ema_wait", "돌파 대기 · 이평선 모임"), ("box_near", "돌파 대기 · 박스 꼭대기")):
            if any(x.get("code") == code for x in mp.get(key) or []):
                items.append({"date": str(last_d), "label": lab, "kind": "wait", "pos": "below", "price": float(L[last_d])})
    except Exception:  # noqa: BLE001
        pass
    # 매일 고른 종베 3 (settings top3_log) — 그날 우리가 실제로 꼽은 자리
    try:
        from backend.services.telegram import _get  # noqa: PLC0415
        for d, cs_ in (_get(db, "top3_log", {}) or {}).items():
            dd = pd.Timestamp(d).date()
            if code in cs_ and dd in df.index and dd >= start:
                items.append({"date": d, "label": "종가 매수", "kind": "buy", "pos": "below", "price": float(L[dd])})
    except Exception:  # noqa: BLE001
        pass
    # 매매 일지 실제 매수·매도 (같은 날 같은 방향은 평균가로 묶음)
    try:
        for d, side, qty, amt in (db.execute(text(
                "select trade_date, side, sum(qty), sum(amount) from trade_executions where owner = :o and code = :c and trade_date >= :s "
                "group by 1, 2 order by 1"), {"o": owner, "c": code, "s": start}).all() if owner else []):     # 매매 일지 로그인했을 때만
            if qty:
                items.append({"date": str(d), "label": f"{'매수' if side == '매수' else '매도'} {amt / qty:,.0f}", "kind": "trade_buy" if side == "매수" else "trade_sell",
                              "pos": "below" if side == "매수" else "above", "price": float(amt / qty)})
    except Exception:  # noqa: BLE001
        pass
    items.sort(key=lambda x: x["date"])
    return {"code": code, "items": items, "active": active, "bull_today": bool(bull.iloc[-1]), "tt7": int(tt7.iloc[-1])}


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
    """첫 화면 왼쪽 목록. 장중이 아니면 디스크 캐시(재시작 직후에도 바로), 장중이면 실시간 가격으로 매번."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    if not (is_trading_day(now.date()) and 9 <= now.hour < 16):
        return cached("workspace_list_v5", (), db, lambda: _workspace_list(db))
    return _workspace_list(db)


def _workspace_list(db: Session) -> dict:
    """첫 화면 왼쪽 목록: 오늘 후보 · 관심 (2026-10-09). 장중이면 네이버 실시간 가격."""
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

    try:      # ▲ 진입 신호가 오늘 뜬 종목 — 맨 위
        for x in entry_today(db):
            add(x["code"], f"▲ 진입 ({x['kind']})")
    except Exception:  # noqa: BLE001
        pass
    scores = {}
    try:      # 종가 진입 점수 6↑ (7개 조건 중) — 사용자 목표 "추세 매매 · 진입은 종가에 손익비 좋은 자리" (2026-10-09)
        # 3년(trend_exit.py, 21일선 아래 종가까지 보유): 6↑ 평균 +2.2%·R +0.60 · 그중 손절폭 3%↓ 평균 +3.9%·R +1.68·최악10% -7%
        scores = close_scores_now(db).get("scores", {})      # 장중이면 실시간 가격으로 (15시대에 오늘 봉 기준 후보)
        for c_, v_ in sorted(scores.items(), key=lambda kv: (-kv[1]["score"], kv[1]["risk"])):
            if v_["score"] >= 6 and v_["risk"] <= 0.03:
                add(c_, "✅ 손익비 좋음")
        for c_, v_ in sorted(scores.items(), key=lambda kv: (-kv[1]["score"], kv[1]["risk"])):
            if v_["score"] >= 6 and 0.03 < v_["risk"] <= 0.05:
                add(c_, "종가 점수 6↑")  # 배지에 점수가 있어 짧게
        # 손절폭 5~8%는 후순위·수량 줄이기, 8%↑는 대기 (3년 예약 손절 R: 3%↓ +1.42 · 3~5% +0.55 · 5~8% +0.35(앞뒤 .32/.37) · 8%↑ +0.11, atr_stop_b.py)
        # 2026-10-09 피에스케이 7.1% "너무 높은 거 아니가" → "포함해서 들고 가도 우리 쪽이 높나" → 1R당 같은 금액이면 5~8%도 플러스
        for c_, v_ in sorted(scores.items(), key=lambda kv: kv[1]["risk"]):
            if v_["score"] >= 6 and 0.05 < v_["risk"] <= 0.08:
                add(c_, "후순위 · 수량 절반")
        for c_, v_ in sorted(scores.items(), key=lambda kv: kv[1]["risk"]):
            if v_["score"] >= 6 and v_["risk"] > 0.08:
                add(c_, "⏸ 폭 좁은 날 기다리기")
    except Exception:  # noqa: BLE001
        pass
    log = _get(db, "top3_log", {}) or {}
    if log:
        for c in log.get(max(log), []):
            add(c, "종가 매수")
    from backend.services.result_cache import cached  # noqa: PLC0415
    from backend.screener.my_pattern import scan as mp_scan  # noqa: PLC0415
    mp = cached("my_pattern_v6", (), db, lambda: mp_scan(db)) or {}      # 재시작 직후에도 디스크에 저장된 결과를 바로 씀
    try:
        from backend.screener.my_pattern import cap_sectors  # noqa: PLC0415
        b = [x for x in mp.get("items", []) if x.get("b") and 1.5 <= x["tv_x"] <= 6 and x["upper_pct"] <= 10]
        for x in cap_sectors([x for x in b if (x.get("b_rank") or 99) <= 3], mp.get("heat", {}))[:5]:
            add(x["code"], "종가 매수 (돈 몰린 섹터)", x.get("family", ""))
        for x in cap_sectors([x for x in b if 4 <= (x.get("b_rank") or 99) <= 8], mp.get("heat", {}))[:5]:
            add(x["code"], "며칠 보유 (올라오는 섹터)", x.get("family", ""))
    except Exception:  # noqa: BLE001
        pass
    for key, tag in (("box_break", "박스 위로 돌파"), ("ema_break", "이평선 모였다 돌파"), ("box_near", "돌파 대기 · 박스 꼭대기"), ("ema_wait", "돌파 대기 · 이평선 모임")):
        for x in (mp.get(key) or [])[:6]:
            add(x.get("code"), tag, x.get("family", ""))
    if (mp.get("mode") or {}).get("mode") == "과매도":
        for s in mp.get("dip", [])[:3]:
            for x in s.get("items", [])[:2]:
                add(x.get("code"), "많이 빠진 날 줍기", s.get("family", ""))
    import re  # noqa: PLC0415
    wl = {x["code"]: x for x in W._items(db)}
    mine = {p["code"] for p in W._positions(db)}       # 공개 화면: 보유 종목·평단·수량은 빼고 (매매 일지 탭에서만, 2026-10-09)
    private = re.compile(r"보유\s*[\d,]+\s*주|평단\s*[\d,]+(\s*\([\d/]+\))?|[\d,]+\s*주")
    watch = [{"code": x["code"], "name": x["name"], "kind": x.get("kind"), "level": x.get("level") or 0,
              "note": re.sub(r"^[\s·]+|[\s·]+$", "", re.sub(r"(\s*·\s*)+", " · ", private.sub("", x.get("note", ""))))}
             for x in wl.values() if x["code"] not in mine]
    held = []
    try:
        _trk = [a["code"] for a in tracking(db).get("items", [])]
    except Exception:  # noqa: BLE001
        _trk = []
    codes = list({*cand, *_trk})
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = {r[0]: (float(r[1]), float(r[2] or 0)) for r in db.execute(text(
        "select stock_code, close_price, change_pct from spot_daily_prices where trading_date = :d and stock_code = any(:c)"), {"d": latest, "c": codes}).all()}
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    live_at = None
    px.update(_krx_closes(codes, str(latest)))        # 장 마감 뒤·휴장일엔 정규장 15:30 종가로 (DB 종가엔 시간외가 섞임)
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    if is_trading_day(now.date()) and 9 <= now.hour < 16 and latest < now.date():
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
    def lane(tags):
        # 2026-10-09 사용자 "오늘 정한 기준으로 바꾸고": 오늘 진입 = ▲ 진입 · 종가 점수 6↑(손절폭 8%↓)만. 그 밖(종가 매수·파란 화살표 등)은 대기에 참고로
        return "entry" if any(t.startswith(("▲", "✅ 손익비", "종가 점수 6↑", "후순위")) for t in tags) else "wait"
    cands = []
    for x in cand.values():
        if lane(x["tags"]) == "wait" and not x["tags"][0].startswith(("돌파 대기", "⏸")):
            x["tags"] = ["참고"] + x["tags"]
        y = price(x); y["lane"] = lane(x["tags"])
        sc = scores.get(x["code"])
        y["score"] = sc["score"] if sc else None
        y["risk"] = round(sc["risk"] * 100, 1) if sc else None
        y["rr"] = bool(sc and sc["score"] >= 6 and sc["risk"] <= 0.03)
        if y["lane"] == "entry" and sc and sc["risk"] > 0.08 and not any(t.startswith("▲") for t in x["tags"]):
            y["lane"] = "wait"            # 다른 이유로 올라왔어도 손절폭 5%↑면 대기로
        cands.append(y)
    cands.sort(key=lambda y: (y["lane"] != "entry", not y["rr"], (y["risk"] or 0) > 5, -(y["score"] if y["score"] is not None else -1), y["risk"] if y["risk"] is not None else 99))
    return {"as_of": str(latest), "live": live_at, "mode": mp.get("mode"),
            "candidates": cands, "track": _track_rows(db, px), "track_done": (tracking(db) or {}).get("done", {})}


def holdings(db: Session, owner: str) -> dict:
    """매매 일지(로그인) 보유 종목: 평단·손절선·남은 여유·수익 (정규장 종가, 장중이면 실시간)."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from backend.services import watchlist as W  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    skip = set(_get(db, "held_exclude", None) or W.HELD_EXCLUDE)
    wl = {x["code"]: x for x in W._items(db)}
    held = [{"code": p["code"], "name": p["name"], "avg": round(p["avg"]), "qty": p["qty"], "long": p["code"] in skip,
             "stop": float(wl[p["code"]]["level"]) if wl.get(p["code"], {}).get("kind") == "hold" and wl[p["code"]].get("level") else 0.0}
            for p in W._positions(db, owner)]
    codes = [h["code"] for h in held]
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = {r[0]: (float(r[1]), float(r[2] or 0)) for r in db.execute(text(
        "select stock_code, close_price, change_pct from spot_daily_prices where trading_date = :d and stock_code = any(:c)"), {"d": latest, "c": codes}).all()}
    px.update(_krx_closes(codes, str(latest)))
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    live_at = None
    if now.weekday() < 5 and 9 <= now.hour < 16 and latest < now.date():
        try:
            from backend.services.naver_live import snapshot  # noqa: PLC0415
            lv = snapshot(sorted(codes), max_age=30)
            for c, v in lv.items():
                px[c] = (v["c"], v["chg"] or 0.0)
            live_at = now.strftime("%H:%M") if lv else None
        except Exception:  # noqa: BLE001
            pass
    for h in held:
        c, ch = px.get(h["code"], (0.0, 0.0))
        h.update(close=c, chg=round(ch, 2), gain=round((c * 0.998 / h["avg"] - 1) * 100, 1) if h["avg"] and c else None,
                 room=round((c / h["stop"] - 1) * 100, 1) if h["stop"] and c else None)
    held.sort(key=lambda h: (h["long"], h["room"] if h["room"] is not None else 99))
    return {"as_of": str(latest), "live": live_at, "held": held}


_ENTRY: dict = {"key": None, "v": []}


def entry_today(db: Session, asof=None) -> list[dict]:
    """디스크 캐시 (재시작 직후에도 바로). asof를 주면 그 날짜로 바로 계산(검증용)."""
    if asof is not None:
        return _entry_today(db, asof)
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if _ENTRY["key"] == latest:
        return _ENTRY["v"]
    from backend.services.result_cache import cached  # noqa: PLC0415
    v = cached("entry_today_v2", (), db, lambda: {"date": str(latest), "items": _entry_today(db, latest)}) or {}
    if v.get("date") == str(latest):
        _ENTRY.update(key=latest, v=v["items"])
    return v.get("items", [])


def _entry_today(db: Session, asof=None) -> list[dict]:
    """전 종목에 ▲ 진입 규칙을 돌려 가장 최근 거래일에 신호가 뜬 종목 (DB 날짜가 바뀔 때만 계산, 약 2~4초).
    규칙은 signals()와 같다: (박스 돌파 또는 EMA 모임 돌파·정배열) + 상승·횡보장 + 추세 조건 6/7↑ + 그날 +8% 미만 · 20일선 +15% 안. 하루 거래대금 20일 평균 30억↑만."""
    latest = asof or db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if not _bull_days(db).get(latest, False):
        return []
    px = pd.read_sql(text("select stock_code s, trading_date d, open_price o, high_price h, low_price l, close_price c, trading_value tv "
                          "from spot_daily_prices where trading_date >= cast(:d as date) - 420 and trading_date <= :d"), db.connection(), params={"d": latest})
    P = {k: px.pivot(index="d", columns="s", values=k).sort_index().astype("float32") for k in ("o", "h", "l", "c", "tv")}
    del px
    O, H, L, C, TV = P["o"], P["h"], P["l"], P["c"], P["tv"]
    liq = TV.iloc[-21:-1].mean() >= 3e9
    cols = liq[liq].index
    O, H, L, C, TV = O[cols], H[cols], L[cols], C[cols], TV[cols]
    chg = C / C.shift(1) - 1
    tvx = TV / TV.rolling(20).mean().shift(1)
    e5, e10, e20, e60 = (C.ewm(span=n, adjust=False).mean() for n in (5, 10, 20, 60))
    ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
    gap_prev = ((ehi - elo) / C).shift(1)
    ma200 = C.rolling(200, min_periods=180).mean(); s50 = C.rolling(50).mean(); s150 = C.rolling(150, min_periods=135).mean()
    hi20p, lo20p, hi10p = H.shift(1).rolling(20).max(), L.shift(1).rolling(20).min(), H.shift(1).rolling(10).max()
    hi52, lo52 = H.rolling(250, min_periods=200).max(), L.rolling(250, min_periods=200).min()
    r = -1
    tt7 = (((C > s150) & (C > ma200)).iloc[r].astype(int) + (s150 > ma200).iloc[r].astype(int) + (ma200 > ma200.shift(21)).iloc[r].astype(int)
           + ((s50 > s150) & (s50 > ma200)).iloc[r].astype(int) + (C > s50).iloc[r].astype(int) + (C >= lo52 * 1.3).iloc[r].astype(int) + (C >= hi52 * 0.75).iloc[r].astype(int))
    box = ((hi20p / lo20p - 1 <= 0.20) & (C > hi20p) & (chg >= 0.05) & (tvx >= 2) & (C > ma200)).iloc[r]
    ema = ((gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)).iloc[r]
    up60 = ((C > e60) & (e20 > e60)).iloc[r]
    calm = (chg.iloc[r] < 0.08) & ((C / C.rolling(20).mean() - 1).iloc[r] < 0.15)      # 급등봉·과열 당일 제외
    hit = (box | (ema & up60)) & (tt7 >= 6) & calm
    names = dict(db.execute(text("select code, name from stocks")).all())
    out = [{"code": c, "name": names.get(c, c), "kind": "박스 위로 돌파" if bool(box[c]) else "이평선 모였다 돌파", "close": float(C[c].iloc[r]),
            "stop": float(L[c].iloc[r]) * 0.99, "chg": float(chg[c].iloc[r]) * 100} for c in hit[hit].index]
    out.sort(key=lambda x: -x["chg"])
    return out


_BR: dict = {"key": None, "v": None}


def market_breadth(db: Session) -> dict:
    """시장 폭 = 하루 거래대금 30억↑ 종목 중 50일선 위 비율, 10일 변화, '속 약해짐'(지수 20일선 위인데 폭 10일 새 5%p↓).
    3년(entry_sig2.py): 속 약해짐일 때 진입 10일 -0.3% vs 폭 늘 때 +3.4% · 폭 40% 미만 11건 전패 (Lazy Alpha 교육 '먼저 알아챈다', 2026-10-09)."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if _BR["key"] == latest:
        return _BR["v"]
    px = pd.read_sql(text("select stock_code s, trading_date d, close_price c, trading_value tv, change_pct ch from spot_daily_prices "
                          "where trading_date >= cast(:d as date) - 130"), db.connection(), params={"d": latest})
    C = px.pivot(index="d", columns="s", values="c").sort_index().astype(float)
    TV = px.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
    CH = px.pivot(index="d", columns="s", values="ch").sort_index().astype(float).clip(-30, 30)
    liq = TV.rolling(20).mean() >= 3e9
    br = ((C > C.rolling(50).mean()).where(liq)).mean(axis=1)
    lvl = (1 + CH.where(TV.rolling(20).mean() >= 1e9).mean(axis=1).fillna(0) / 100).cumprod()
    idx_up = bool(lvl.iloc[-1] > lvl.iloc[-20:].mean())
    now, d10 = float(br.iloc[-1]), float(br.iloc[-1] - br.iloc[-11])
    # 첫 화면 시장 상태 카드용 (2026-10-09 "Lazy Alpha 라운지처럼 깔끔하게"): 60일 신고가·신저가 수 · 오늘 오른 종목 비율
    l1 = TV.rolling(20).mean().iloc[-1] >= 1e9
    hi60 = int(((C.iloc[-1] >= C.iloc[-60:].max()) & liq.iloc[-1]).sum()); lo60 = int(((C.iloc[-1] <= C.iloc[-60:].min()) & liq.iloc[-1]).sum())
    adv = float((CH.iloc[-1][l1] > 0).mean())
    v = {"date": str(latest), "pct": round(now * 100), "chg10": round(d10 * 100, 1), "index_up": idx_up,
         "weak": bool(idx_up and d10 <= -0.05), "narrow": bool(now < 0.40), "hi60": hi60, "lo60": lo60, "adv_pct": round(adv * 100)}
    _BR.update(key=latest, v=v)
    return v


CLOSE_FLAGS = ["60일 고점 -5% 안", "RS 70~95", "거래 0.7~3배", "고가 쪽 마감", "그날 0~+8%", "20일선 +15% 안", "EMA 간격 6% 안"]


def close_scores(db: Session) -> dict:
    """종가 진입 점수 (0~7) — 사용자 목표 "종가에 안전하고 확률 높은 종목을 추세 기반으로" (2026-10-09).
    대상: 거래대금 20일 평균 30억↑ · 추세 기본(종가 > EMA20 > EMA60). 7개 조건 중 맞는 개수.
    3년(close_entry_study.py · 종가 진입 · 손절 그날 저가-1% · 최대 10일, 상승·횡보장): 점수 0 이김 20%·평균 -1.7% → 점수 6↑ 이김 43%·평균 +1.5%·최악10% -11%,
    점수 7 이김 46%·+1.5%. 기간을 반으로 나눠도 둘 다 점수 따라 이김 비율이 올라감(앞 26→47%, 뒤 31→46%). 디스크 캐시."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    from backend.services.result_cache import cached  # noqa: PLC0415
    v = cached("close_scores_v1", (), db, lambda: _close_scores(db, latest)) or {}
    return v


_CF: dict = {"key": None, "v": None}


def _close_frames(db: Session, latest) -> dict:
    """종가 점수용 최근 400일 고가·저가·종가·거래량·거래대금 (float32 · 약 15MB) — DB 날짜가 바뀔 때만 다시 읽는다.
    장중 점수(2분마다)를 매번 DB에서 읽지 않게 메모리에 둔다. numpy에 바로 채워 read_sql·pivot의 큰 메모리를 피한다."""
    if _CF["key"] == latest:
        return _CF["v"]
    dates = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date >= cast(:d as date) - 400 "
                                           "and trading_date <= :d order by 1"), {"d": latest}).all()]
    codes = [r[0] for r in db.execute(text("select distinct stock_code from spot_daily_prices where trading_date = :d"), {"d": latest}).all()]
    di, ci = {d: i for i, d in enumerate(dates)}, {c: i for i, c in enumerate(codes)}
    A = {k: np.full((len(dates), len(codes)), np.nan, dtype="float32") for k in ("h", "l", "c", "v", "tv")}
    for s_, d_, h_, l_, c_, v_, t_ in db.execute(text("select stock_code, trading_date, high_price, low_price, close_price, volume, trading_value "
                                                      "from spot_daily_prices where trading_date >= cast(:d as date) - 400 and trading_date <= :d"), {"d": latest}):
        j = ci.get(s_)
        if j is None:
            continue
        i = di[d_]
        A["h"][i, j], A["l"][i, j], A["c"][i, j] = h_ or np.nan, l_ or np.nan, c_ or np.nan
        A["v"][i, j], A["tv"][i, j] = v_ if v_ is not None else np.nan, t_ if t_ is not None else np.nan
    v = {k: pd.DataFrame(a, index=dates, columns=codes) for k, a in A.items()}
    _CF.update(key=latest, v=v)
    return v


def _close_scores(db: Session, latest, live: dict | None = None, frac: float = 1.0, frames: dict | None = None) -> dict:
    """live = 네이버 실시간 {code: {o,h,l,c,v}} 이면 오늘 줄을 붙여 장중 점수 (거래량은 frac로 나눠 마감 환산).
    frames = 앞에서 잘라 낸 프레임이면 그 마지막 날 기준 점수 (지난 날짜 다시 계산용)."""
    P = frames or _close_frames(db, latest)
    H, L, C, V, TV = P["h"], P["l"], P["c"], P["v"], P["tv"]
    asof = str(latest)
    if live:
        from datetime import date as _date  # noqa: PLC0415
        today = _date.today()
        row = {k: pd.Series({c: x[k] for c, x in live.items() if x.get(k)}, dtype="float32").reindex(C.columns) for k in ("h", "l", "c")}
        vol = pd.Series({c: x["v"] / max(frac, 0.05) for c, x in live.items()}, dtype="float32").reindex(C.columns)
        add = lambda F, ser: pd.concat([F, ser.to_frame(today).T])  # noqa: E731
        H, L, C, V, TV = add(H, row["h"]), add(L, row["l"]), add(C, row["c"]), add(V, vol), add(TV, row["c"] * vol)
        asof = str(today)
    liq = TV.rolling(20).mean() >= 3e9
    e5, e10, e20, e60 = (C.ewm(span=n, adjust=False).mean() for n in (5, 10, 20, 60))
    rs_raw = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1) + 0.2 * (C / C.shift(252) - 1)
    RS = rs_raw.where(liq).rank(axis=1, pct=True).iloc[-1] * 98 + 1
    r = -1
    c, h, l = C.iloc[r], H.iloc[r], L.iloc[r]
    chg = c / C.iloc[r - 1] - 1
    trend = (c > e20.iloc[r]) & (e20.iloc[r] > e60.iloc[r]) & liq.iloc[r]
    hi60 = c / H.iloc[-60:].max() - 1
    vx = V.iloc[r] / V.iloc[-21:-1].mean()
    pos = (c - l) / (h - l).replace(0, np.nan)
    gap20 = c / C.iloc[-20:].mean() - 1
    ehi = np.maximum(np.maximum(e5.iloc[r], e10.iloc[r]), e20.iloc[r]); elo = np.minimum(np.minimum(e5.iloc[r], e10.iloc[r]), e20.iloc[r])
    spread = (ehi - elo) / c
    flags = [hi60 >= -0.05, (RS >= 70) & (RS < 95), (vx >= 0.7) & (vx < 3), pos >= 0.7, (chg >= 0) & (chg < 0.08), gap20 < 0.15, spread < 0.06]
    out = {}
    for code in trend[trend.fillna(False).astype(bool)].index:
        f = [bool(x.get(code, False)) for x in flags]
        out[code] = {"score": sum(f), "flags": f, "stop": float(l[code]) * 0.99, "risk": float(1 - l[code] * 0.99 / c[code])}
    return {"date": asof, "scores": out, "live": bool(live)}


_CSL: dict = {"t": 0.0, "v": None}


def close_scores_now(db: Session, max_age: float = 120) -> dict:
    """장중(평일 9:00~DB에 오늘 시세 들어오기 전)이면 실시간 가격으로 계산한 점수(2분 캐시), 아니면 장 마감 점수.
    사용자는 종가에 들어가니 15시대에 오늘 봉 기준 후보·손절폭을 봐야 한다 (2026-10-09)."""
    import time  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if not (is_trading_day(now.date()) and 9 <= now.hour < 16 and latest < now.date()):
        return close_scores(db)
    hit = _CSL["v"]
    if hit and hit.get("date") == str(now.date()) and time.time() - _CSL["t"] < max_age:
        return hit
    try:
        from backend.screener.my_pattern import _day_frac  # noqa: PLC0415
        from backend.services.naver_live import snapshot  # noqa: PLC0415
        codes = list(_close_frames(db, latest)["c"].columns)
        live = snapshot(codes, max_age=60)
        if len(live) < len(codes) * 0.5:
            return close_scores(db)
        frac = 1.0 if (now.hour, now.minute) >= (15, 30) else _day_frac(now)
        v = _close_scores(db, latest, live=live, frac=frac)
        v["at"] = now.strftime("%H:%M")
        _CSL.update(t=time.time(), v=v)
        return v
    except Exception:  # noqa: BLE001
        return close_scores(db)


_RSH: dict = {"key": None, "v": None}


def rs_hist(db: Session) -> dict:
    """날짜별 RS(1~99) — 차트에 지난 날짜의 종가 진입 점수를 찍으려면 그날의 전 종목 순위가 필요하다 (2026-10-09 SK이노베이션
    "진입 신호가 하나도 안 떴는데"). {"dates": [...최근 270거래일], "rs": {code: float16 배열}}. 하루 한 번 계산 · 디스크 캐시."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if _RSH["key"] == latest:
        return _RSH["v"]
    from backend.services.result_cache import cached  # noqa: PLC0415
    v = cached("rs_hist_v1", (), db, lambda: _rs_hist(db, latest)) or {}
    if v.get("date") == str(latest):
        _RSH.update(key=latest, v=v)
    return v


def _rs_hist(db: Session, latest, keep: int = 270) -> dict:
    # 메모리 아끼기 (pandas read_sql·pivot이 500MB 넘게 씀): 최근 400일 안에 하루라도 30억↑ 거래된 종목만, numpy 배열에 바로 채운다
    codes = [r[0] for r in db.execute(text("select stock_code from spot_daily_prices where trading_date >= cast(:d as date) - 400 "
                                           "group by 1 having max(trading_value) >= 3e9"), {"d": latest}).all()]
    dates = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date >= cast(:d as date) - 800 "
                                           "and trading_date <= :d order by 1"), {"d": latest}).all()]
    ci, di = {c: i for i, c in enumerate(codes)}, {d: i for i, d in enumerate(dates)}
    ac = np.full((len(dates), len(codes)), np.nan, dtype="float32"); at = ac.copy()
    for s_, d_, c_, t_ in db.execute(text("select stock_code, trading_date, close_price, trading_value from spot_daily_prices "
                                          "where trading_date >= cast(:d as date) - 800 and trading_date <= :d and stock_code = any(:cs)"),
                                     {"d": latest, "cs": codes}):
        ac[di[d_], ci[s_]] = c_ if c_ else np.nan
        at[di[d_], ci[s_]] = t_ if t_ is not None else np.nan
    C, TV = pd.DataFrame(ac, index=dates, columns=codes), pd.DataFrame(at, index=dates, columns=codes)
    liq = TV.rolling(20).mean() >= 3e9
    del TV
    raw = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1) + 0.2 * (C / C.shift(252) - 1)
    RS = (raw.where(liq).iloc[-keep:].rank(axis=1, pct=True) * 98 + 1)
    return {"date": str(latest), "dates": [str(d) for d in RS.index],
            "rs": {c: RS[c].to_numpy(dtype="float16") for c in RS.columns if RS[c].notna().any()}}


def tracking(db: Session) -> dict:
    """최근 20거래일 종가 진입 신호(점수 6↑ · 손절폭 8%↓)를 우리 규칙대로 따라가 본 것 — 첫 화면 '진행 중' 탭 (2026-10-09 관심 탭 대신).
    규칙: 신호 날 종가 진입 · 스탑로스 = 그날 저가 -1% (장중 닿으면 끝) · 21일선 아래 종가면 다음 날 아침 정리.
    날짜마다 그날까지 데이터로 점수를 다시 계산한다 (signal_log가 쌓이기 전 날짜는 '다시 계산'). DB 날짜가 바뀔 때만 · 디스크 캐시."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("tracking_v2", (), db, lambda: _tracking(db, latest)) or {}


def _tracking(db: Session, latest, days: int = 20) -> dict:
    P = _close_frames(db, latest)
    C, H, L = P["c"], P["h"], P["l"]
    e21 = C.ewm(span=21, adjust=False).mean()
    bulls = _bull_days(db)
    n = len(C.index)
    sig: dict[str, list] = {}
    for k in range(days - 1, -1, -1):             # 오래된 날부터
        r = n - 1 - k
        d = C.index[r]
        if not bulls.get(d, False):
            continue
        sc = _close_scores(db, d, frames={key: v.iloc[:r + 1] for key, v in P.items()}).get("scores", {})
        for code, v in sc.items():
            if v["score"] >= 6 and v["risk"] <= 0.08:
                sig.setdefault(code, []).append((r, float(C[code].iloc[r]), v["stop"], v["score"]))
    names = dict(db.execute(text("select code, name from stocks")).all())
    alive, done = [], {"stop": 0, "exit": 0, "win": 0}
    for code, lst in sig.items():
        free_from = -1                             # 정리한 뒤에 나온 신호부터 다시 따라간다
        for r0, p0, stop, score in lst:
            if r0 <= free_from:
                continue
            status, end = "hold", n - 1
            for m in range(r0 + 1, n):
                lo, c = float(L[code].iloc[m]), float(C[code].iloc[m])
                if lo == lo and lo < stop:
                    status, end = "stop", m; break
                if m - r0 > 1 and c == c and c < float(e21[code].iloc[m]):
                    status, end = ("exit" if m < n - 1 else "exit_tmr"), m; break
            if status in ("stop", "exit"):
                done[status] += 1
                px_out = stop if status == "stop" else float(C[code].iloc[end])
                done["win"] += px_out > p0
                free_from = end
                continue
            c_now = float(C[code].iloc[-1])
            alive.append({"code": code, "name": names.get(code, code), "date": str(C.index[r0]), "entry": p0, "stop": round(stop), "score": score,
                          "gain": round((c_now / p0 - 1) * 100, 1), "to21": round((c_now / float(e21[code].iloc[-1]) - 1) * 100, 1),
                          "sell_tmr": status == "exit_tmr", "days": n - 1 - r0})
            break
    alive.sort(key=lambda a: (not a["sell_tmr"], -a["gain"]))
    return {"date": str(latest), "items": alive, "done": done}


def _track_rows(db: Session, px: dict) -> list[dict]:
    try:
        t = tracking(db)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for a in t.get("items", []):
        c, ch = px.get(a["code"], (0.0, 0.0))
        out.append({**a, "close": c or a["entry"], "chg": round(ch, 2), "tags": []})
    return out
