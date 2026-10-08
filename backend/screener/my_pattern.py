"""내 패턴(A)·최적 조건(B) 종베 후보 — 장 마감 시세(DB 마지막 날)로 계산 (2026-10-06).

패턴 A = 사용자 실제 매수 501건에서 돈을 번 자리: 양봉 & 20일 고점 -8% 안 & 20일선 위 & 거래(거래대금) 평소 1배↑.
  3년 전 종목(상승·횡보장): A만 +0.30%/+0.42%(학습/검증, 기준 +0.19%/+0.11%), A & 섹터 1~3위 +0.49%/+0.66%.
조건 B = 섹터 종목 그날 등락 중간 +1.2%↑ & 거래 중간 1.0배↑, 종목 +3%↑ & 20일 +12%↑ & 이격 30%↓ & 윗꼬리 20%↓.
  3년 검증 1년 +1.91%·이김 81%(날짜 단위 +0.91%). 결과 = 다음 날 갭이면 시가, 아니면 종가.
내일 후보 = 뜨는 섹터(1~3위)·20일선 위·20일 고점 -5% 안에서 오늘 조용히 쉰 종목(±2%, 거래 1배↓) — 내일 거래 붙은 양봉이면 A가 된다.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

_cache: dict = {}
CYCLE_START = "2026-07-30"   # 이번 상승 구간 시작(바닥). 기준봉 VWAP은 이 뒤 장대양봉에서만 (사용자 2026-10-07)
# 과매도 줍기 섹터별 3년 결과 (dipbuy.py, 섹터 평균 종가 매수 → 5일 뒤) — 다른 섹터는 전체 평균 +1.9%
DIP_NOTE = {"AI메모리·기판": "3년 5일 +4.0% ⭐", "반도체 장비·재료": "3년 5일 +2.6%", "2차전지": "3년 5일 +1.3% (반등 약함)"}


# ── 장세에 따라 오늘 '어떤 방식으로 살지'를 먼저 정한다 (2026-10-07 사용자: "그때그때 장세에 맞게 해야 하고 빠진 건 담아야 하는데 왜 틀에 박혀 있노")
# 10/6 조건 B가 과열된 기판·2차전지에 몰려 10/7 -1.6%(4/14 이김), 사용자는 섹터를 나눠 +1.2% → 한 가지 규칙만 매일 쓰지 않는다.
MODES = {
    "쉬기": ("🔴", "오늘은 쉬는 날", "시장이 하락 중 — 새로 사지 말고 손절선만 확인"),
    "과매도": ("📉", "주도 섹터가 크게 빠진 날 → 과매도 줍기", "종가 무렵 <b>대형·덜 빠진 주도주</b>를 절반 비중으로 (3년 5일 +2.7~3.0%) · 손절 = 오늘 저가 아래 마감"),
    "과열": ("🔥", "주도 섹터가 과열 → 올라오는 섹터 먼저", "주도 섹터 종베는 <b>섹터당 1개만·다음 날 정리</b>, 돈이 막 들어온 섹터와 박스 돌파를 먼저"),
    "주도": ("🟢", "주도 섹터에 돈이 몰리는 날 → 종베", "주도 섹터의 거래 붙은 양봉을 <b>섹터당 2개까지</b> 나눠서 · 다음 날 분할 매도"),
    "순환": ("🔄", "돈이 다른 섹터로 옮겨 가는 날 → 순환", "주도 섹터는 쉬고, 돈이 옮겨 간 섹터로 — <b>올라오는 섹터(4~8위) 종베·스윙</b>이 먼저, 새로 들어온 섹터(9위↓)는 작게"),
    "쉬어가기": ("⚪", "살 자리가 뚜렷하지 않은 날", "억지로 사지 말고 내일 후보·관심 종목 선만 확인"),
}


def decide_mode(state: str | None, lead_b: list, hot_lead: list, dip_top: list, rot: list) -> dict:
    """state=시장 국면, lead_b=돈 몰린 20일 1~3위 섹터, hot_lead=그중 과열(25%↑), dip_top=20일 1~3위 중 오늘 -2%↓, rot=돈 몰린 4위↓ 섹터."""
    if state == "하락":
        k, secs = "쉬기", []
    elif dip_top:
        k, secs = "과매도", dip_top
    elif lead_b and hot_lead:
        k, secs = "과열", hot_lead
    elif lead_b:
        k, secs = "주도", lead_b
    elif rot:
        k, secs = "순환", rot
    else:
        k, secs = "쉬어가기", []
    ico, title, do = MODES[k]
    return {"mode": k, "icon": ico, "title": title, "do": do, "sectors": secs}


def trim_dip(secs: list, max_secs: int = 5, per: int = 6) -> list:
    """과매도 줍기 목록 줄이기 (2026-10-07 시장 전체가 빠진 날 11개 섹터·수십 종목이 떠서 못 읽음):
    20일 순위 위쪽 섹터 5개만, 섹터 평균보다 덜 빠진 종목만, ⭐(대형·덜 빠짐) 먼저, 여러 섹터에 겹치면 한 번만, 섹터당 6개."""
    secs = sorted(secs, key=lambda d: d.get("rank", 99))[:max_secs]
    seen: set = set()
    for d in secs:
        its = [x for x in d["items"] if x["change_pct"] > d["chg"] and x["code"] not in seen]
        its.sort(key=lambda x: (not x["best"], -x["liq"]))
        d["items"] = its[:per]
        seen.update(x["code"] for x in d["items"])
    return secs


def cap_sectors(items: list, heat: dict, per: int = 2, hot_per: int = 1) -> list:
    """같은 섹터에 몰리지 않게 섹터당 2개, 과열(25%↑) 섹터는 1개 (2026-10-07)."""
    cnt: dict[str, int] = {}
    out = []
    for x in items:
        f = x.get("family")
        lim = hot_per if (heat.get(f) or 0) >= 25 else per
        if cnt.get(f, 0) < lim:
            out.append(x)
            cnt[f] = cnt.get(f, 0) + 1
    return out


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": [], "next": []}
    if _cache.get("key") == latest:
        return _cache["val"]
    days = [d for (d,) in db.execute(text(
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by 1 desc limit 220"), {"d": latest})][::-1]   # 200일선 때문에 220일
    px = pd.read_sql(text("select stock_code s, trading_date d, open_price o, high_price h, low_price l, close_price c, trading_value tv "
                          "from spot_daily_prices where trading_date >= :a"), db.connection(), params={"a": days[0]})
    P = {k: px.pivot(index="d", columns="s", values=k).sort_index() for k in ("o", "h", "l", "c", "tv")}
    O, H, L, C, TV = (P[k] for k in ("o", "h", "l", "c", "tv"))
    # 추세 도지 (2026-10-06 upd.py): 상승 추세 종목의 장대양봉(+8%↑·거래 3배↑) 다음 날 도지 + 이격 20%↓
    #   3년 분할 매도 +1.05%(학습)/+1.68%(검증), 5일 보유 +1.12%/+3.06%. 이격 20%↑면 효과 없음.
    ma20s, ma60s = C.rolling(20).mean(), C.rolling(60).mean()
    trend = (C > ma20s) & (ma20s > ma60s) & (ma20s > ma20s.shift(5)) & (C / L.rolling(60).min() >= 1.2)
    chg = C / C.shift(1) - 1
    tvx = TV / TV.shift(1).rolling(20).mean()
    ret20 = C / C.shift(20) - 1
    from backend.screener.rotation import family_members  # noqa: PLC0415
    from backend.screener.market_regime import current_regime  # noqa: PLC0415
    fam = family_members(db)
    rank, schg, svx = {}, {}, {}
    for f, m in fam.items():
        cc = [c for c in m if c in C.columns]
        if len(cc) < 5:
            continue
        rank[f] = ret20[cc].median(axis=1).iloc[-1]
        schg[f] = float(chg[cc].iloc[-1].median())
        svx[f] = float(tvx[cc].iloc[-1].median())
    order = sorted(rank, key=lambda f: -rank[f])
    # 섹터 과열 = 그 섹터 종목 중 20일선보다 20% 넘게 뜬 비율. 25%↑면 B도 다음 날만 좋고 들고 가면 나빠짐 (hotsec.py, 2026-10-06)
    gap_last = C.iloc[-1] / C.rolling(20).mean().iloc[-1] - 1
    heat = {f: round(float((gap_last[[c for c in m if c in C.columns]] > 0.2).mean()) * 100) for f, m in fam.items()
            if len([c for c in m if c in C.columns]) >= 5}
    frank = {f: i + 1 for i, f in enumerate(order)}
    b_secs = [f for f in order if schg[f] >= 0.012 and svx[f] >= 1.0]
    names = dict(db.execute(text("select code, name from stocks")).all())
    code_f: dict[str, list[str]] = {}
    for f, m in fam.items():
        for c in m:
            code_f.setdefault(c, []).append(f)
    last = C.index[-1]
    # 그날 외인·기관 순매수 — 둘 다 팔았는데 오른 날(개인만 산 날)은 그 뒤가 약했다 (2026-01~10: +3%↑ 날 20일 -9.0% vs -3.2%)
    flows = {c: (float(fo or 0), float(ins or 0)) for c, fo, ins in db.execute(text(
        "select stock_code, foreign_net_buy, institution_net_buy from spot_investor_flows where trading_date = :d"), {"d": latest})}
    ma20 = C.rolling(20).mean().iloc[-1]
    hi20 = H.rolling(20).max().iloc[-1]
    # 단기 EMA(5·10·20) 간격 — 전날 기준. 모여 있을 때(4%↓) 돌파가 5일 +0.9~1.0%, 벌어졌을 때(7%↑) -0.2~-1.4% (ema_squeeze.py, 2026-10-07)
    _e5, _e10, _e20 = (C.ewm(span=n, adjust=False).mean() for n in (5, 10, 20))
    _hi = _e5.where(_e5 > _e10, _e10).where(lambda x: x > _e20, _e20)
    _lo = _e5.where(_e5 < _e10, _e10).where(lambda x: x < _e20, _e20)
    ema_gap = ((_hi - _lo) / C).iloc[-2]          # 전날 간격
    # EMA 모임 돌파 / 내일 후보 (사용자 원칙 2026-10-07 "단기 EMA가 모여 있을 때 돌파해야 성공률이 높다", ema_squeeze.py)
    ema_now = ((_hi - _lo) / C).iloc[-1]
    # EMA60 정배열(종가>EMA60 & EMA20>EMA60) — 짧은 모임 돌파 5일: 정배열 +0.94/+1.97% vs 아님 +0.35/+0.76% (학습/검증, ema_combo.py)
    _e60 = C.ewm(span=60, adjust=False).mean()
    up60 = ((C > _e60) & (_e20 > _e60)).iloc[-1]
    hi10p, hi10n = H.rolling(10).max().shift(1).iloc[-1], H.rolling(10).max().iloc[-1]
    ma60n = C.rolling(60).mean().iloc[-1]
    liq20 = TV.rolling(20).median().iloc[-1]     # 평균은 하루 폭발에 부풀어서(샘표·한국가스공사) 중간값
    hi20n = H.rolling(20).max().iloc[-1]
    ema_brk, ema_wait = [], []
    items, nxt, tdoji, tbig, rest2, turn3, turn2, bbrk, bnear = [], [], [], [], [], [], [], [], []
    # 박스 돌파 / 뚫기 직전 (2026-10-06 boxbreak.py·rank2.py, 사용자 포스코퓨처엠 10/6 차트):
    #   직전 20일 종가 폭 20%↓ 박스 + 200일선 위 + 섹터 돈 몰린 날 + 상승·횡보장, 거래대금 20일 평균 30억↑
    #   돌파 = 종가 > 직전 20일 최고가 · +5%↑ · 거래 2배↑ · 윗꼬리 30%↓ → 10일 +5.9/+6.8/+6.5% (앞 2년/최근 1년/AI 랠리), 다음 날 +1.2~2.3%
    #   직전 = 종가가 그 고점 -3%~0% · +3%↑ · 거래 1배↑ → 10일 +6.0/+8.0/+7.9% (표본 37/96/126건 — 보조)
    ma200 = C.rolling(200, min_periods=180).mean().iloc[-1]
    hi20p = H.rolling(20).max().shift(1).iloc[-1]
    cmx, cmn = C.rolling(20).max().shift(1).iloc[-1], C.rolling(20).min().shift(1).iloc[-1]
    liq3 = TV.shift(1).rolling(20).mean().iloc[-1]
    # 과매도 줍기 (2026-10-07 dipbuy.py·dipstock.py): 직전 20일 +10%↑ 섹터가 오늘 평균 -2%↓ → 그 섹터를 종가에 사면 3년
    #   아무 종목 5일 +1.9%·10일 +3.4%(기준 +0.2/+0.5), 기판 5일 +4.0%(71%), 미국 장비 급락 다음 날 기판 +8.7%(8/8).
    #   종목 고르기는 차이가 작다 — 직전 20일 +15%↑ & 20일선 위 & 20일 고점 -10% 안이 5일 +2.3%로 조금 낫다. 하락장 전환 구간(26-05)은 실패.
    dch = chg.clip(-0.3, 0.3)
    liq1 = TV.shift(1).rolling(20).mean() >= 1e9
    dip_secs = []
    for f, m in fam.items():
        cc = [c for c in m if c in C.columns]
        if len(cc) < 8:
            continue
        g = dch[cc].where(liq1[cc]).mean(axis=1)
        s20 = float((1 + g.iloc[-21:-1].fillna(0)).prod() - 1)
        if g.iloc[-1] <= -0.02 and s20 >= 0.10:
            dip_secs.append({"family": f, "chg": round(float(g.iloc[-1]) * 100, 1), "s20": round(s20 * 100), "items": [],
                              "note": DIP_NOTE.get(f, "")})
    r20p = C.iloc[-2] / C.iloc[-22] - 1 if len(C.index) > 22 else C.iloc[-1] * float("nan")
    # 바닥 돌려세움 (2026-10-06 turnup.py): 120일 고점 -25%↓ 빠진 뒤 15일 폭 15% 안 횡보 → 작은 양봉 3연속 + 20일선 되찾음
    #   AI 랠리 중 AI 종목 20일 +11.3%(기준 +4.9%), 전 종목 +3.3%(+2.0%). 랠리 전(약세)엔 마이너스 → 상승장에서만.
    hi120 = H.rolling(120, min_periods=100).max()
    bh, bl = H.shift(3).rolling(15).max(), L.shift(3).rolling(15).min()
    bottom = (C.shift(3) / hi120.shift(3) <= 0.75) & (bh / bl - 1 <= 0.15)
    upc = (C > O) & (chg > 0)
    AI_SET = {c for f in ("AI메모리·기판", "반도체 장비·재료", "AI SW·플랫폼") for c in fam.get(f, [])}
    tvx_s = TV / TV.shift(1).rolling(20).mean()
    big = (chg >= 0.08) & (tvx_s >= 3) & (C > O) & (chg < 0.29)
    prev = C.index[-2] if len(C.index) >= 3 else None
    prev2 = C.index[-3] if len(C.index) >= 3 else None
    for c in C.columns:
        cl, o, h, l = C.at[last, c], O.at[last, c], H.at[last, c], L.at[last, c]
        if not (cl == cl and cl >= 1000) or c not in code_f or (TV[c].iloc[-5:].mean() or 0) < 1e9:
            continue
        fs = sorted((f for f in code_f[c] if f in frank), key=lambda f: frank[f])
        if not fs:
            continue
        f0 = fs[0]
        ch, vx, g20 = float(chg.at[last, c]), float(tvx.at[last, c]), float(cl / ma20[c] - 1)
        off = float(cl / hi20[c] - 1)
        up = float((h - max(o, cl)) / (h - l)) if h > l else 0.0
        r20 = float(ret20.at[last, c])
        row = {"code": c, "name": names.get(c, c), "close": round(float(cl)), "change_pct": round(ch * 100, 2), "tv_x": round(vx, 2),
               "gap20_pct": round(g20 * 100, 1), "off_hi20_pct": round(off * 100, 1), "upper_pct": round(up * 100),
               "ret20_pct": round(r20 * 100, 1), "family": f0, "rank": frank[f0], "value": round(float(TV.at[last, c])),
               "ema_gap": round(float(ema_gap.get(c, float("nan"))) * 100, 1) if ema_gap.get(c) == ema_gap.get(c) else None}
        fo, ins = flows.get(c, (0.0, 0.0))
        row.update(fo_eok=round(fo / 1e8, 1), ins_eok=round(ins / 1e8, 1), retail_only=bool(c in flows and fo < 0 and ins < 0))
        if ch != ch or vx != vx:
            continue
        if prev2 is not None and bool(big.at[prev, c]) and bool(trend.at[prev2, c]) and abs(ch) <= 0.03 \
                and abs(float((cl - o) / o)) <= 0.015 and g20 <= 0.20:
            tdoji.append({**row, "big_pct": round(float(chg.at[prev, c]) * 100, 1)})      # 오늘이 그 자리
        if prev is not None and bool(big.at[last, c]) and bool(trend.at[prev, c]) and g20 <= 0.20:
            tbig.append(row)                                                                # 내일 도지면 그 자리
        if len(C.index) > 25 and bool(bottom.at[last, c]) and bool(upc.at[last, c]) and bool(upc.at[prev, c]):
            r3 = {**row, "box_low": round(float(bl.at[last, c])), "off120_pct": round((cl / float(hi120.at[last, c]) - 1) * 100), "ai": c in AI_SET}
            if bool(upc.at[prev2, c]) and cl > float(ma20[c]) and float(C.at[C.index[-4], c]) <= float(C.rolling(20).mean().at[C.index[-4], c]):
                turn3.append(r3)          # 오늘 3연속째 + 20일선 되찾음
            elif not bool(upc.at[prev2, c]):
                turn2.append(r3)          # 2연속 — 내일 양봉이면 3연속
        # 장대양봉 이틀 뒤 쉼 + 장대양봉 종가 지킴 (AI 랠리 2025-04~: 5일 +3.36% · 10일 +4.92%, 기준 +1.61/+3.18) — 5~10일 보유
        if prev2 is not None and bool(big.at[prev2, c]) and abs(ch) <= 0.03 and abs(float(chg.at[prev, c])) <= 0.03 \
                and cl >= float(C.at[prev2, c]) and frank[f0] <= 3 and g20 <= 0.30:
            rest2.append({**row, "big_close": round(float(C.at[prev2, c])), "big_pct": round(float(chg.at[prev2, c]) * 100, 1)})
        if (any(f in b_secs for f in fs) and cl > float(ma200[c] or 0) > 0 and float(liq3[c] or 0) >= 3e9
                and cmn[c] > 0 and cmx[c] / cmn[c] - 1 <= 0.20 and up <= 0.30 and ch < 0.29):
            line = float(hi20p[c])
            fb = next(f for f in fs if f in b_secs)
            bx = {**row, "family": fb, "line": round(line), "line_pct": round((cl / line - 1) * 100, 1), "b_rank": frank.get(fb, 99)}
            if cl > line and ch >= 0.05 and vx >= 2:
                bbrk.append(bx)
            elif line * 0.97 <= cl <= line and ch >= 0.03 and vx >= 1:
                bnear.append(bx)
        is_a = bool(cl > o and ch > 0 and off >= -0.08 and g20 > 0 and vx >= 1)
        is_b = bool(any(f in b_secs for f in fs) and 0.03 <= ch < 0.29 and r20 >= 0.12 and g20 <= 0.30 and up <= 0.20)
        is_a = is_a and g20 <= 0.30 and up <= 0.35     # 화면엔 과열(이격 30%↑)·윗꼬리 긴 것 뺌 — 3년: 이격 38%↑ 늘 마이너스
        if (is_a and frank[f0] <= 3) or is_b:
            fb = next((f for f in fs if f in b_secs), f0) if is_b else f0
            # b_rank = 돈 몰린 그 섹터의 20일 순위: 1~3위 주도(종베 다음 날이 가장 좋음), 4~8위 막 도는 중(5~10일 스윙이 가장 좋음) — bonly.py
            items.append({**row, "a": is_a, "b": is_b, "family": fb, "b_rank": frank.get(fb, 99) if is_b else None})
        elif frank[f0] <= 3 and g20 > 0 and off >= -0.05 and abs(ch) <= 0.02 and vx <= 1.0 and g20 <= 0.30:
            nxt.append(row)
    for c in C.columns:
        cl, lq = float(C.at[last, c]), float(liq20.get(c) or 0)
        if not (cl == cl and lq >= 3e9 and float(TV.at[last, c] or 0) > 0):
            continue
        if float(hi20n[c]) > cl * 1.15:     # 20일 안에 지금보다 15%↑ 위 고점(폭발 뒤 흘러내린 종목) — 그 뒤 모인 EMA는 의미 없음 (2026-10-07 "이런 건 개오바")
            continue
        g0, g1, ch_ = float(ema_gap.get(c, 9)), float(ema_now.get(c, 9)), float(chg.at[last, c])
        fs_ = sorted((f for f in code_f.get(c, []) if f in frank), key=lambda f: frank[f])
        base = {"code": c, "name": names.get(c, c), "close": round(cl), "change_pct": round(ch_ * 100, 1), "liq": lq,
                "ema_gap": round(g0 * 100, 1), "ema_now": round(g1 * 100, 1), "family": fs_[0] if fs_ else "",
                "money": any(f in b_secs for f in fs_), "up60": bool(up60.get(c, False))}
        if (g0 <= 0.04 and cl > float(_hi.at[last, c]) and cl > float(hi10p[c]) and 0.03 <= ch_ < 0.29
                and float(tvx.at[last, c]) >= 1.5):
            ema_brk.append({**base, "tv_x": round(float(tvx.at[last, c]), 1)})
        elif (g1 <= 0.03 and cl >= float(_lo.at[last, c]) * 0.99 and cl >= float(hi10n[c]) * 0.96 and cl > float(ma60n[c])
              and abs(ch_) <= 0.02):
            ema_wait.append({**base, "to_high_pct": round((float(hi10n[c]) / cl - 1) * 100, 1), "line": round(float(hi10n[c]))})
    # 기준봉 앵커드 VWAP — 60일 안 마지막 장대양봉(+8%·거래 3배)부터 거래량 가중 평균 종가. 종가가 그 아래면 ⚠ (vwap.py: 아래면 20일 0.0%, 위 +2.3%)
    _bigs = (chg >= 0.08) & (tvx >= 3) & (C > O)
    _vol = (TV / C)
    for x in ema_brk + ema_wait:
        c = x["code"]
        idx = [i for i in range(max(0, len(C.index) - 60), len(C.index)) if bool(_bigs[c].iloc[i]) and str(C.index[i]) >= CYCLE_START]
        if idx:
            a = idx[-1]
            av = float(TV[c].iloc[a:].sum() / _vol[c].iloc[a:].sum())
            x["avwap"], x["avwap_below"] = round(av), bool(x["close"] < av)
    ema_brk.sort(key=lambda x: (not x["money"], not x["up60"], -x["liq"]))
    ema_wait.sort(key=lambda x: (not x["money"], not x["up60"], -x["liq"]))
    for ds in dip_secs:
        for c in fam[ds["family"]]:
            if c not in C.columns or not (float(liq3.get(c) or 0) >= 3e9):
                continue
            cl = float(C.at[last, c])
            if cl == cl and float(r20p.get(c) or 0) >= 0.15 and cl > float(ma20[c]) and cl / float(hi20[c]) - 1 >= -0.10:
                ds["items"].append({"code": c, "name": names.get(c, c), "change_pct": round(float(chg.at[last, c]) * 100, 1),
                                    "off_hi20_pct": round((cl / float(hi20[c]) - 1) * 100, 1), "low": round(float(L.at[last, c])),
                                    "liq": float(liq3[c]), "best": bool(float(liq3[c]) >= 5e10 and float(chg.at[last, c]) * 100 > ds["chg"])})
        # 대형(하루 500억↑) & 섹터보다 덜 빠짐이 가장 좋았음(5일 +3.0%) → 먼저, 그다음 거래대금 순 (dipstock.py)
        ds["rank"] = frank.get(ds["family"], 99)
    dip_secs = trim_dip(dip_secs)
    # 순환: 20일 4위↓ 섹터에 오늘 돈이 들어옴(등락 중간 +1%↑·거래 중간 1배↑) → 그 섹터의 거래 붙은 양봉(20일선 위)
    rot_secs = []
    for f in order[8:]:          # 9위↓ = 새로 들어온 섹터 (4~8위는 '올라오는 섹터' 조건 B가 이미 맡음)
        if schg[f] >= 0.01 and svx[f] >= 1.0:
            its = []
            for c in fam[f]:
                if c not in C.columns or (TV[c].iloc[-5:].mean() or 0) < 1e9:
                    continue
                cl = float(C.at[last, c])
                ch_, vx_ = float(chg.at[last, c]), float(tvx.at[last, c])
                hh, ll, oo = float(H.at[last, c]), float(L.at[last, c]), float(O.at[last, c])
                up_ = (hh - max(oo, cl)) / (hh - ll) if hh > ll else 0
                if 0.03 <= ch_ < 0.29 and vx_ >= 1.5 and up_ <= 0.2 and cl > float(ma20[c]):
                    its.append({"code": c, "name": names.get(c, c), "change_pct": round(ch_ * 100, 1), "tv_x": round(vx_, 1)})
            its.sort(key=lambda x: -x["change_pct"])
            rot_secs.append({"family": f, "chg": round(schg[f] * 100, 1), "tvx": round(svx[f], 2), "rank": frank[f], "items": its[:8]})
    lead_b = [f for f in b_secs if frank[f] <= 3]
    mode = decide_mode((current_regime(db) or {}).get("state"), lead_b, [f for f in lead_b if (heat.get(f) or 0) >= 25],
                       [d["family"] for d in dip_secs if frank.get(d["family"], 99) <= 3],
                       [f for f in b_secs if frank[f] > 3] + [r["family"] for r in rot_secs if r["family"] not in b_secs])
    items.sort(key=lambda x: (not x["b"], -x["change_pct"]))
    bset = {x["code"] for x in items if x["b"]}
    for x in bbrk + bnear:
        x["is_b"] = x["code"] in bset
    bbrk.sort(key=lambda x: (not x["is_b"], -x["change_pct"]))
    bnear.sort(key=lambda x: -x["line_pct"])
    nxt.sort(key=lambda x: (x["rank"], -x["off_hi20_pct"]))
    reg = current_regime(db) or {}
    tdoji.sort(key=lambda x: (x["rank"], x["gap20_pct"]))
    rest2.sort(key=lambda x: (x["rank"], x["gap20_pct"]))
    turn3.sort(key=lambda x: (not x["ai"], x["rank"]))
    turn2.sort(key=lambda x: (not x["ai"], x["rank"]))
    tbig.sort(key=lambda x: (x["rank"], -x["change_pct"]))
    val = {"trading_date": str(latest), "market": reg.get("state"), "b_sectors": b_secs, "trend_doji": tdoji, "trend_big": tbig, "rest2": rest2, "turn3": turn3, "turn2": turn2,
           "hot": order[:3], "sector_day": {f: {"chg": round(schg[f] * 100, 2), "tvx": round(svx[f], 2), "heat": heat.get(f)} for f in order[:6]},
           "heat": heat,
           "items": items, "next": nxt, "box_break": bbrk, "box_near": bnear, "dip": dip_secs,
           "rotation": rot_secs, "mode": mode, "ema_break": ema_brk[:10], "ema_wait": ema_wait[:12]}
    _cache.update(key=latest, val=val)
    return val


def _log_box(db: Session, r: dict) -> None:
    """박스 돌파·뚫기 직전 나온 종목을 날짜별로 남겨 둔다 — 한 달 뒤 실제 결과를 백테스트와 비교 (settings 'box_picks_log')."""
    try:
        from backend.services.telegram import _get, _put  # noqa: PLC0415
        log = _get(db, "box_picks_log", {}) or {}
        log[r["trading_date"]] = {"break": [[x["code"], x["name"], x["close"], x["line"], x["is_b"]] for x in r.get("box_break", [])],
                                  "near": [[x["code"], x["name"], x["close"], x["line"], x["is_b"]] for x in r.get("box_near", [])]}
        _put(db, "box_picks_log", log)
    except Exception:  # noqa: BLE001
        pass


def ema_tag(x: dict) -> str:
    g = x.get("ema_gap")
    return "" if g is None else ("  EMA 모임✓" if g <= 4 else "  ⚠EMA 벌어짐" if g >= 7 else "")


def _log_picks(db: Session, r: dict, lead: list, swing: list) -> None:
    """내 추천(장세·조건 B·박스·과매도·순환)을 날짜별로 남긴다 — 사용자 종베(user_jongbe)와 매일 비교 (settings 'my_picks_log')."""
    try:
        from backend.services.telegram import _get, _put  # noqa: PLC0415
        log = _get(db, "my_picks_log", {}) or {}
        nm = lambda xs: [[x["code"], x["name"], x.get("close")] for x in xs]  # noqa: E731
        log[r["trading_date"]] = {"mode": (r.get("mode") or {}).get("mode"), "lead": nm(lead), "swing": nm(swing),
                                  "box": nm(r.get("box_break", [])),
                                  "dip": [[x["code"], x["name"], None] for d in r.get("dip", []) for x in d["items"][:4]],
                                  "rot": [[x["code"], x["name"], None] for d in r.get("rotation", []) for x in d["items"][:4]]}
        _put(db, "my_picks_log", log)
    except Exception:  # noqa: BLE001
        pass


def top3_lines(db: Session, r: dict) -> list[str]:
    """매일 종베 3개 (2026-10-08 사용자 "한 세 개 정도 꼽아서 매일 보내라").
    주도 섹터 조건 B가 있으면 그 상위 3, 없고 시장이 -1%↓ 빠진 날이면 '버틴 종목'(hold_up) 3, 둘 다 없으면 쉬기."""
    from backend.screener.hold_up import STAT, picks  # noqa: PLC0415
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    good = [x for x in r["items"] if x["b"] and 1.5 <= x["tv_x"] <= 6 and x["upper_pct"] <= 10]
    lead = cap_sectors([x for x in good if (x.get("b_rank") or 99) <= 3], r.get("heat", {}))[:3]
    out = ["", "🎯 <b>오늘 종베 3</b>"]
    log = []
    if r.get("market") == "하락":
        out.append("<i>시장 하락 국면 — 원칙상 쉬는 날, 참고만</i>")
    if lead:
        out.append("주도 섹터 거래 붙은 양봉 (조건 B)")
        for i, x in enumerate(lead, 1):
            out.append(f"{i}. <b>{x['name']}</b> {x['change_pct']:+.1f}% · {x.get('family', '')}")
            log.append(x["code"])
    else:
        h = picks(db)
        if h["items"] and h.get("down_day"):
            out.append(f"시장 {h['market']:+.1f}%에도 버틴 종목 · 최근 돈 들어온 종목")
            for i, x in enumerate(h["items"], 1):
                out.append(f"{i}. <b>{x['name']}</b> {x['close']:,.0f} · 오늘 {x['chg']:+.1f}% (시장보다 {x['rel']:+.1f}%p)")
                out.append(f"   손절 오늘 저가 {x['low']:,.0f} · 기준봉 {x['spike']} · 20일선 {x['gap20']:+.0f}%")
                log.append(x["code"])
            out.append(f"<i>{STAT}</i>")
        else:
            out.append("오늘은 고를 종목 없음 → 쉬기")
    if log:
        out.append("파는 법: 다음 날 +2% 못 가면 정리 · 넘으면 절반 덜고 나머지 손절선 올리기")
        hist = _get(db, "top3_log", {}) or {}
        hist[r["trading_date"]] = log
        _put(db, "top3_log", dict(list(hist.items())[-120:]))
    return out


def text_summary(db: Session, k: int = 5) -> str:
    """텔레그램용 짧은 요약."""
    r = scan(db)
    if not r["trading_date"]:
        return ""
    lines = []
    try:
        from backend.services.telegram import market_status, status_line  # noqa: PLC0415
        st = market_status(db)
        if st:
            lines.append(status_line(st))
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"\n🎯 <b>오늘 종베</b> ({r['trading_date'][5:]})")
    md = r.get("mode") or {}
    if md:
        lines.append(f"{md['icon']} <b>{md['title']}</b>" + (f" ({', '.join(md['sectors'])})" if md.get("sectors") else ""))
        lines.append("→ " + md["do"])
    lines.append("돈 몰린 섹터: " + (", ".join(r["b_sectors"]) if r["b_sectors"] else "없음 (오늘은 쉬는 날)"))
    try:
        lines += top3_lines(db, r)
    except Exception:  # noqa: BLE001
        pass
    bb, bn = r.get("box_break", []), r.get("box_near", [])
    if (bb or bn) and r["market"] != "하락":
        _log_box(db, r)
        lines.append("\n🥇 <b>스윙 1순위: 박스 돌파</b> (눌려 있던 20일 고점을 종가로 뚫음 · <b>5~10일</b>, 손절 = 뚫은 고점 아래 마감)")
        lines += [f"• {x['name']}  {x['change_pct']:+.1f}% · 손절 {x['line']:,} · {x['family']}" + ("  ⭐종베도 OK" if x["is_b"] else "") + ema_tag(x)
                  + ("  🔥과열 섹터(짧게)" if (r.get("heat", {}).get(x["family"]) or 0) >= 25 else "") for x in bb[:k]] or ["• 오늘은 없음"]
        if bn:
            lines.append("  └ 뚫기 직전 (고점 -3% 안 마감 · 10일 · 보조): " + " · ".join(f"{x['name']}({x['line_pct']:+.1f}%)" for x in bn[:k]))
    good = [x for x in r["items"] if x["b"] and 1.5 <= x["tv_x"] <= 6 and x["upper_pct"] <= 10]
    hot_ = r.get("heat", {})
    lead = cap_sectors([x for x in good if (x.get("b_rank") or 99) <= 3], hot_)[:k]
    swing = cap_sectors([x for x in good if 4 <= (x.get("b_rank") or 99) <= 8], hot_)[:k]
    _log_picks(db, r, lead, swing)
    rot = r.get("rotation", [])
    if rot and r["market"] != "하락":
        lines.append("\n🔄 <b>새로 돈이 들어온 섹터</b> (20일 9위↓ 섹터에 오늘 돈 · 작게, 검증 약함)")
        for d in rot:
            lines.append(f"• <b>{d['family']}</b> {d['chg']:+.1f}% · 거래 {d['tvx']}배: " + (" · ".join(x["name"] for x in d["items"][:6]) or "고를 종목 없음"))
    b = lead + swing
    hot_ = r.get("heat", {})
    fmt = lambda x: (f"• {x['name']}  {x['change_pct']:+.1f}% · 거래 {x['tv_x']:.1f}배 · {x['family']}" + ema_tag(x) + ("  ⚠개인만" if x.get("retail_only") else "")  # noqa: E731
                     + ("  🔥과열 섹터(다음 날 정리만)" if (hot_.get(x["family"]) or 0) >= 25 else ""))
    if lead:
        lines.append("\n1️⃣ ⭐ <b>주도 섹터의 힘 있는 양봉</b> → <b>종베</b> (다음 날 분할 매도)")
        lines += [fmt(x) for x in lead]
    if swing:
        lines.append("\n1️⃣ ⭐ <b>올라오는 섹터의 힘 있는 양봉</b> → <b>5~10일 스윙</b>")
        lines += [fmt(x) for x in swing]
    if b:
        if any(x.get("retail_only") for x in b):
            lines.append("⚠개인만 = 외인·기관 둘 다 팔았는데 오른 날 (그 뒤 약했음)")
    eb, ew = r.get("ema_break", []), r.get("ema_wait", [])
    if (eb or ew) and r["market"] != "하락":
        lines.append("\n📏 <b>EMA(5·10·20) 모임 돌파</b> (모인 뒤 돌파 5일 +0.9~1.0% · 섹터 돈 겹치면 20일 +6%)")
        if eb:
            lines.append("• 오늘 돌파: " + " · ".join(f"{x['name']} {x['change_pct']:+.1f}%" + ("⭐" if x["money"] else "") for x in eb[:6]))
        if ew:
            lines.append("• 내일 후보(모여서 10일 고점 앞): " + " · ".join(f"{x['name']}({x['to_high_pct']:.1f}%)" for x in ew[:8]))
    dp = r.get("dip", [])
    if dp and r["market"] != "하락":
        lines.append("\n📉 <b>과매도 줍기</b> (오른 섹터가 하루 크게 빠진 날 · 종가·시간외 매수 · <b>5~10일</b>, 손절 = 오늘 저가 아래 마감)")
        for d in dp:
            lines.append(f"• <b>{d['family']}</b> 오늘 {d['chg']:+.1f}% (20일 +{d['s20']}%) {d.get('note', '')}: " + " · ".join(x["name"] for x in d["items"][:6]))
    td = r.get("trend_doji", [])[:k]
    if td:
        lines.append("\n2️⃣ 🕯 <b>추세 도지</b> (상승 추세, 어제 장대양봉 → 오늘 도지 · <b>5일 안쪽 정리</b>)")
        lines += [f"• {x['name']}  어제 {x['big_pct']:+.1f}% → 오늘 {x['change_pct']:+.1f}% · 이격 {x['gap20_pct']:.0f}%" for x in td]
    r2 = r.get("rest2", [])[:k]
    if r2:
        lines.append("\n3️⃣ 🛌 <b>장대양봉 이틀 쉼 + 종가 지킴</b> (뜨는 섹터 · <b>5~10일 보유</b>, 손절 = 장대양봉 종가 아래)")
        lines += [f"• {x['name']}  손절 {x['big_close']:,} · 이격 {x['gap20_pct']:.0f}%" for x in r2]
    t3 = r.get("turn3", [])[:k]
    if t3 and r["market"] != "하락":
        lines.append("\n4️⃣ 🔄 <b>바닥 돌려세움</b> (빠진 뒤 바닥 횡보 → 양봉 3연속·20일선 회복 · <b>20일 보유</b>, 상승장에서만)")
        lines += [f"• {x['name']}{' (AI)' if x['ai'] else ''}  손절 {x['box_low']:,} · 고점 대비 {x['off120_pct']}%" for x in t3]
    tb = r.get("trend_big", [])[:k]
    if tb:
        lines.append("\n🕯 <b>내일 추세 도지 후보</b> (오늘 장대양봉, 내일 도지면 그 자리)")
        lines.append(" · ".join(x["name"] for x in tb))
    n = r["next"][:k]
    if n:
        lines.append("\n👀 <b>내일 후보</b> (고점 근처 쉬는 중)")
        lines.append(" · ".join(x["name"] for x in n))
    return "\n".join(lines)


_dip_live: dict = {}


def dip_live(db: Session, max_age: int = 300) -> dict:
    """장중 과매도 줍기 — 토스 실시간 가격으로 섹터 평균을 계산 (5분 캐시, 토스 429 방지).
    섹터: 오늘 평균 -2%↓ & 어제까지 20일 +10%↑. 종목: 직전 20일 +15%↑ · 20일선 위 · 20일 고점 -10% 안 · 하루 30억↑."""
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415
    lock = _dip_live.setdefault("lock", threading.Lock())
    if _dip_live.get("val") and time.time() - _dip_live["t"] < max_age:
        return _dip_live["val"]
    if not lock.acquire(blocking=not _dip_live.get("val")):
        return _dip_live["val"]          # 계산 중이면 직전 결과를 바로 (계산 20초 — 화면이 기다리지 않게)
    try:
        if _dip_live.get("val") and time.time() - _dip_live["t"] < max_age:
            return _dip_live["val"]
        val = _dip_live_compute(db)
        _dip_live.update(t=time.time(), val=val)
        return val
    finally:
        lock.release()


def _day_frac(now) -> float:
    """장중 누적 거래 비율 대략 (첫 30분 25%, 중간 60%, 마지막 30분 15%) — 거래 배수를 마감 기준으로 환산."""
    mins = max(1, min(390, (now.hour - 9) * 60 + now.minute))
    return 0.25 * min(mins, 30) / 30 + 0.60 * max(0, min(mins, 360) - 30) / 330 + 0.15 * max(0, mins - 360) / 30


def _live_b_box(db: Session, fam: dict, b_live: list, srank: dict, live: dict, prev, names: dict, heat: dict, now) -> dict:
    """장중 조건 B·박스 돌파 — 돈 몰린 섹터(지금 등락 중간 +1.2%↑)의 +3%↑ 종목만 토스 일봉으로 거래·꼬리를 본다 (거래는 마감 환산)."""
    import time  # noqa: PLC0415
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    res = {"best_lead": [], "best_swing": [], "box_break": [], "box_near": []}
    cand = {}
    for f in sorted(b_live, key=lambda f: srank[f]):
        for c in fam.get(f, []):
            if c in live and prev.get(c, 0) > 0 and 0.03 <= live[c] / prev[c] - 1 < 0.29:
                cand.setdefault(c, f)
    if not cand:
        return res
    hist = pd.read_sql(text("select stock_code s, trading_date d, high_price h, close_price c, trading_value tv from spot_daily_prices "
                            "where stock_code = any(:c) and trading_date >= current_date - 330 and trading_date < current_date"),
                       db.connection(), params={"c": list(cand)})
    HC = hist.pivot(index="d", columns="s", values="c").sort_index().astype(float)
    HH = hist.pivot(index="d", columns="s", values="h").sort_index().astype(float)
    HT = hist.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
    frac = _day_frac(now)
    for c, f in list(cand.items())[:120]:
        k = None
        for w in (0.15, 1.0, 2.5):
            k = fetch_candles(c, "1d", 2)
            time.sleep(w)
            if k:
                break
        if not k or c not in HC.columns or len(HC[c].dropna()) < 22:
            continue
        t = k[-1]
        o, h, l, cl, v = (float(t[x]) for x in ("openPrice", "highPrice", "lowPrice", "closePrice", "volume"))
        tv_avg = float(HT[c].tail(20).mean() or 0)
        if tv_avg <= 0 or tv_avg < 1e9:
            continue
        vx = cl * v / tv_avg / frac
        ch = cl / prev[c] - 1
        up = (h - max(o, cl)) / (h - l) if h > l else 0.0
        closes = HC[c].dropna()
        r20 = cl / float(closes.iloc[-20]) - 1
        ma20 = (float(closes.tail(19).sum()) + cl) / 20
        g20 = cl / ma20 - 1
        rk = srank.get(f, 99)
        es = [closes.ewm(span=n, adjust=False).mean().iloc[-1] for n in (5, 10, 20)]     # 어제까지 종가로 만든 EMA = 돌파 전날 간격
        egap = round((max(es) - min(es)) / float(closes.iloc[-1]) * 100, 1)
        row = {"code": c, "name": names.get(c, c), "close": round(cl), "change_pct": round(ch * 100, 1), "tv_x": round(vx, 1), "ema_gap": egap,
               "upper_pct": round(up * 100), "gap20_pct": round(g20 * 100, 1), "family": f, "b_rank": rk, "retail_only": False, "live": True}
        if r20 >= 0.12 and g20 <= 0.30 and up <= 0.10 and 1.5 <= vx <= 6:
            (res["best_lead"] if rk <= 3 else res["best_swing"] if rk <= 8 else []).append(row)
        # 박스 돌파: 직전 20일 종가 폭 20%↓ · 200일선 위 · 거래대금 30억↑ · 종가(지금) > 직전 20일 최고가
        c20 = closes.tail(20)
        ma200 = float(closes.tail(200).mean()) if len(closes) >= 180 else 0
        line = float(HH[c].dropna().tail(20).max())
        if tv_avg >= 3e9 and ma200 and cl > ma200 and c20.max() / c20.min() - 1 <= 0.20 and up <= 0.30:
            bx = {**row, "line": round(line), "line_pct": round((cl / line - 1) * 100, 1), "is_b": False}
            if cl > line and ch >= 0.05 and vx >= 2:
                res["box_break"].append(bx)
            elif line * 0.97 <= cl <= line and vx >= 1:
                res["box_near"].append(bx)
    bset = {x["code"] for x in res["best_lead"] + res["best_swing"]}
    for x in res["box_break"] + res["box_near"]:
        x["is_b"] = x["code"] in bset
    for k_ in ("best_lead", "best_swing", "box_break"):
        res[k_].sort(key=lambda x: -x["change_pct"])
    res["best_lead"] = cap_sectors(res["best_lead"], heat)[:8]
    res["best_swing"] = cap_sectors(res["best_swing"], heat)[:8]
    return res


def _dip_live_compute(db: Session) -> dict:
    import time  # noqa: PLC0415
    from backend.screener.rotation import family_members  # noqa: PLC0415
    from backend.services.toss_client import _get  # noqa: PLC0415
    fam = family_members(db)
    now = pd.Timestamp.now(tz="Asia/Seoul")
    today = now.strftime("%Y-%m-%d")
    px = pd.read_sql(text("select stock_code s, trading_date d, high_price h, close_price c, trading_value tv from spot_daily_prices "
                          "where trading_date >= cast(:t as date) - 45 and trading_date < cast(:t as date)"), db.connection(), params={"t": today})
    C = px.pivot(index="d", columns="s", values="c").sort_index().astype(float)
    H = px.pivot(index="d", columns="s", values="h").sort_index().astype(float)
    TV = px.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
    out = {"as_of": now.strftime("%H:%M"), "secs": [], "rot": [], "sectors": [], "mode": None}
    if len(C.index) < 22:
        return out
    liq = TV.tail(20).mean()
    names = dict(db.execute(text("select code, name from stocks")).all())
    codes = sorted(c for c in C.columns if C[c].iloc[-1] == C[c].iloc[-1])    # 시장 국면도 지금 가격으로 — 전 종목
    live: dict[str, float] = {}
    for i in range(0, len(codes), 200):
        for w in (0.3, 2, 5):
            time.sleep(w)
            r = _get("/prices", {"symbols": ",".join(codes[i:i + 200])})
            if r is not None and r.status_code == 200:
                for x in r.json().get("result", []):
                    if x.get("lastPrice") and (x.get("timestamp") or "").startswith(today):
                        live[x["symbol"]] = float(x["lastPrice"])
                break
    prev = C.iloc[-1]
    dch = (C / C.shift(1) - 1).clip(-0.3, 0.3)
    stats = {}
    for f, m in fam.items():
        cc = [c for c in m if c in live and prev.get(c, 0) > 0 and liq.get(c, 0) >= 1e9]
        if len(cc) >= 8:
            chs = sorted(live[c] / prev[c] - 1 for c in cc)
            stats[f] = {"med": chs[len(chs) // 2], "s20": float((1 + dch[cc].tail(20).mean(axis=1)).prod() - 1), "cc": cc}
    srank = {f: i + 1 for i, f in enumerate(sorted(stats, key=lambda f: -stats[f]["s20"]))}
    ma20 = {c: (C[c].tail(19).sum() + live[c]) / 20 for c in live if c in C.columns}
    # ── 시장·섹터 표도 지금 가격으로 (2026-10-07 "지금 기준으로 시장 데이터 전부")
    try:
        from backend.services.telegram import market_status  # noqa: PLC0415
        out["market"] = market_status(db, {c: (live[c] / prev[c] - 1) * 100 for c in live if prev.get(c, 0) > 0})
    except Exception:  # noqa: BLE001
        out["market"] = None
    heat_live = {}
    for f, m in fam.items():
        cc = [c for c in m if c in ma20]
        if len(cc) >= 5:
            heat_live[f] = round(sum(1 for c in cc if live[c] / ma20[c] - 1 > 0.2) / len(cc) * 100)
    out["heat"] = heat_live
    out["sector_day"] = {f: {"chg": round(float(stats[f]["med"]) * 100, 2), "tvx": None, "heat": heat_live.get(f)}
                         for f in sorted(stats, key=lambda f: srank[f])[:6]}
    b_live = [f for f in stats if stats[f]["med"] >= 0.012]
    out["b_sectors"] = sorted(b_live, key=lambda f: srank[f])
    out.update(_live_b_box(db, fam, b_live, srank, live, prev, names, heat_live, now))
    for f in sorted(stats, key=lambda f: srank[f]):
        out["sectors"].append({"family": f, "chg": round(float(stats[f]["med"]) * 100, 1), "rank": srank[f]})
        if srank[f] > 8 and stats[f]["med"] >= 0.01:
            its = sorted(({"code": c, "name": names.get(c, c), "change_pct": round((live[c] / prev[c] - 1) * 100, 1)} for c in stats[f]["cc"]
                          if live[c] / prev[c] - 1 >= 0.03 and live[c] > ma20.get(c, 9e18) and liq.get(c, 0) >= 1e9), key=lambda x: -x["change_pct"])
            out["rot"].append({"family": f, "chg": round(float(stats[f]["med"]) * 100, 1), "rank": srank[f], "items": its[:8]})
    for f, m in fam.items():
        cc = [c for c in m if c in live and prev.get(c, 0) > 0 and liq.get(c, 0) >= 1e9]
        if len(cc) < 8:
            continue
        g = sum(max(min(live[c] / prev[c] - 1, 0.3), -0.3) for c in cc) / len(cc)
        s20 = float((1 + dch[cc].tail(20).mean(axis=1)).prod() - 1)
        if g > -0.02 or s20 < 0.10:
            continue
        rows = []
        for c in cc:
            p = live[c]
            ma = (C[c].tail(19).sum() + p) / 20
            hi = max(float(H[c].tail(19).max()), p)
            if liq.get(c, 0) >= 3e9 and prev[c] / C[c].iloc[-21] - 1 >= 0.15 and p > ma and p / hi - 1 >= -0.10:
                rows.append({"code": c, "name": names.get(c, c), "change_pct": round(float(p / prev[c] - 1) * 100, 1), "liq": float(liq[c]),
                             "best": bool(liq[c] >= 5e10 and p / prev[c] - 1 > g)})
        out["secs"].append({"family": f, "chg": round(float(g) * 100, 1), "s20": round(s20 * 100), "note": DIP_NOTE.get(f, ""), "items": rows,
                            "rank": srank.get(f, 99)})
    out["secs"] = trim_dip(out["secs"])
    try:
        from backend.screener.market_regime import current_regime  # noqa: PLC0415
        heat = out.get("heat") or (_cache.get("val") or {}).get("heat", {})
        lead_b = [f for f in stats if srank[f] <= 3 and stats[f]["med"] >= 0.012]
        mstate = ((out.get("market") or {}).get("전체") or {}).get("state") or (current_regime(db) or {}).get("state")
        out["mode"] = decide_mode(mstate, lead_b, [f for f in lead_b if (heat.get(f) or 0) >= 25],
                                  [d["family"] for d in out["secs"] if srank.get(d["family"], 99) <= 3],
                                  [f for f in stats if 3 < srank[f] <= 8 and stats[f]["med"] >= 0.012] + [r["family"] for r in out["rot"]])
    except Exception:  # noqa: BLE001
        pass
    return out


def dip_live_text(db: Session) -> str:
    """장중(14:50) 판단 텔레그램 — 장세(과매도/순환/주도/과열)와 그에 맞는 후보. 쉬기·쉬어가기면 빈 문자열."""
    r = dip_live(db, max_age=60)
    md = r.get("mode") or {}
    if not md or md["mode"] in ("쉬기", "쉬어가기"):
        return ""
    lines = [f"⏱ <b>장중 판단</b> ({r['as_of']}, 종가 전)", f"{md['icon']} <b>{md['title']}</b>" + (f" ({', '.join(md['sectors'])})" if md.get("sectors") else ""),
             "→ " + md["do"]]
    if md["mode"] == "과매도" and r["secs"]:
        lines.append("\n📉 <b>과매도 줍기</b> (오른 섹터가 오늘 -2%↓ · 대형·덜 빠진 순)")
        lines += [f"• <b>{d['family']}</b> (20일 {d['rank']}위) {d['chg']:+.1f}% {d['note']}\n  "
                  + (" · ".join(f"{'⭐' if x.get('best') else ''}{x['name']} {x['change_pct']:+.1f}%" for x in d["items"][:6]) or "고를 종목 없음")
                  for d in r["secs"][:4]]
        lines.append("⭐ = 하루 500억↑ 대형 & 섹터보다 덜 빠짐 (3년 5일 +3.0% · 가장 좋았음)")
        lines.append("손절 = 오늘 저가 아래 마감 · 절반 비중 · 5~10일")
    if r.get("rot"):
        lines.append("\n🔄 <b>새로 돈이 들어오는 섹터</b> (20일 9위↓ · 작게)")
        lines += [f"• <b>{d['family']}</b> {d['chg']:+.1f}%: " + (" · ".join(f"{x['name']} {x['change_pct']:+.1f}%" for x in d["items"][:6]) or "고를 종목 없음") for d in r["rot"]]
    if md["mode"] in ("주도", "과열"):
        lines.append("\n주도 섹터 종베 후보는 장 마감 뒤 거래량이 확정돼야 정확함 — 15:45 요약 확인")
    return "\n".join(lines)
