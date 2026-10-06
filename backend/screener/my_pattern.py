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


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": [], "next": []}
    if _cache.get("key") == latest:
        return _cache["val"]
    days = [d for (d,) in db.execute(text(
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by 1 desc limit 140"), {"d": latest})][::-1]
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
    items, nxt, tdoji, tbig, rest2, turn3, turn2 = [], [], [], [], [], [], []
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
               "ret20_pct": round(r20 * 100, 1), "family": f0, "rank": frank[f0], "value": round(float(TV.at[last, c]))}
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
        is_a = cl > o and ch > 0 and off >= -0.08 and g20 > 0 and vx >= 1
        is_b = (any(f in b_secs for f in fs) and 0.03 <= ch < 0.29 and r20 >= 0.12 and g20 <= 0.30 and up <= 0.20)
        is_a = is_a and g20 <= 0.30 and up <= 0.35     # 화면엔 과열(이격 30%↑)·윗꼬리 긴 것 뺌 — 3년: 이격 38%↑ 늘 마이너스
        if (is_a and frank[f0] <= 3) or is_b:
            items.append({**row, "a": is_a, "b": is_b, "family": next((f for f in fs if f in b_secs), f0) if is_b else f0})
        elif frank[f0] <= 3 and g20 > 0 and off >= -0.05 and abs(ch) <= 0.02 and vx <= 1.0 and g20 <= 0.30:
            nxt.append(row)
    items.sort(key=lambda x: (not x["b"], -x["change_pct"]))
    nxt.sort(key=lambda x: (x["rank"], -x["off_hi20_pct"]))
    reg = current_regime(db) or {}
    tdoji.sort(key=lambda x: (x["rank"], x["gap20_pct"]))
    rest2.sort(key=lambda x: (x["rank"], x["gap20_pct"]))
    turn3.sort(key=lambda x: (not x["ai"], x["rank"]))
    turn2.sort(key=lambda x: (not x["ai"], x["rank"]))
    tbig.sort(key=lambda x: (x["rank"], -x["change_pct"]))
    val = {"trading_date": str(latest), "market": reg.get("state"), "b_sectors": b_secs, "trend_doji": tdoji, "trend_big": tbig, "rest2": rest2, "turn3": turn3, "turn2": turn2,
           "hot": order[:3], "sector_day": {f: {"chg": round(schg[f] * 100, 2), "tvx": round(svx[f], 2)} for f in order[:6]},
           "items": items, "next": nxt}
    _cache.update(key=latest, val=val)
    return val


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
    if r["market"] == "하락":
        lines.append("🔴 하락장 — 쉬는 날")
    lines.append("조건 B 섹터: " + (", ".join(r["b_sectors"]) if r["b_sectors"] else "없음 (오늘은 쉬는 날)"))
    b = [x for x in r["items"] if x["b"] and 1.5 <= x["tv_x"] <= 6 and x["upper_pct"] <= 10][:k] or [x for x in r["items"] if x["b"]][:k]
    if b:
        lines.append("\n⭐ <b>B 후보</b> (거래 1.5~6배·윗꼬리 10%↓ 추림)")
        lines += [f"• {x['name']}  {x['change_pct']:+.1f}% · 거래 {x['tv_x']:.1f}배" + ("  ⚠개인만" if x.get("retail_only") else "") for x in b]
        if any(x.get("retail_only") for x in b):
            lines.append("⚠개인만 = 외인·기관 둘 다 팔았는데 오른 날 (그 뒤 약했음)")
    td = r.get("trend_doji", [])[:k]
    if td:
        lines.append("\n🕯 <b>추세 도지</b> (상승 추세, 어제 장대양봉 → 오늘 도지 · <b>5일 안쪽 정리</b>)")
        lines += [f"• {x['name']}  어제 {x['big_pct']:+.1f}% → 오늘 {x['change_pct']:+.1f}% · 이격 {x['gap20_pct']:.0f}%" for x in td]
    r2 = r.get("rest2", [])[:k]
    if r2:
        lines.append("\n🛌 <b>장대양봉 이틀 쉼 + 종가 지킴</b> (뜨는 섹터 · <b>5~10일 보유</b>, 손절 = 장대양봉 종가 아래)")
        lines += [f"• {x['name']}  손절 {x['big_close']:,} · 이격 {x['gap20_pct']:.0f}%" for x in r2]
    t3 = r.get("turn3", [])[:k]
    if t3 and r["market"] != "하락":
        lines.append("\n🔄 <b>바닥 돌려세움</b> (빠진 뒤 바닥 횡보 → 양봉 3연속·20일선 회복 · <b>20일 보유</b>, 상승장에서만)")
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
