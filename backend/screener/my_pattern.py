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
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by 1 desc limit 45"), {"d": latest})][::-1]
    px = pd.read_sql(text("select stock_code s, trading_date d, open_price o, high_price h, low_price l, close_price c, trading_value tv "
                          "from spot_daily_prices where trading_date >= :a"), db.connection(), params={"a": days[0]})
    P = {k: px.pivot(index="d", columns="s", values=k).sort_index() for k in ("o", "h", "l", "c", "tv")}
    O, H, L, C, TV = (P[k] for k in ("o", "h", "l", "c", "tv"))
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
    ma20 = C.rolling(20).mean().iloc[-1]
    hi20 = H.rolling(20).max().iloc[-1]
    items, nxt = [], []
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
        if ch != ch or vx != vx:
            continue
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
    val = {"trading_date": str(latest), "market": reg.get("state"), "b_sectors": b_secs,
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
        lines += [f"• {x['name']}  {x['change_pct']:+.1f}% · 거래 {x['tv_x']:.1f}배" for x in b]
    n = r["next"][:k]
    if n:
        lines.append("\n👀 <b>내일 후보</b> (고점 근처 쉬는 중)")
        lines.append(" · ".join(x["name"] for x in n))
    return "\n".join(lines)
