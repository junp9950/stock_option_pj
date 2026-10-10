"""대형주 눌림 박스 (에이피알형, 2026-10-07): 하루 거래대금 500억↑ 대형주가 60일 고점에서 -5~-20% 눌려 120일선 근처 위에서 쉬고, 거래가 평소 이하.
3년 검증(tmp_claude/trendline_bt.py, 상승·횡보장 5거래일 간격 표본): 대형주 936건 20일 뒤 평균 +7.0%(오른 경우 57%), 5일 +1.8% · 10일 +3.1%.
같은 조건 전 종목은 20일 +3.0% · 추세선에 닿은 경우만 보면 오히려 +1.7%. 대형주는 바닥(-40%)까지 잘 안 빠져서 바닥 박스 감시에는 안 잡힘(사용자).
손절 = 최근 15일 박스 하단 아래 마감."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_TV, OFF_LO, OFF_HI, MAX_VR, MAX_BOX = 5e10, -0.21, -0.05, 1.0, 0.20   # 고점 -20%는 반올림 여유 1%p · 박스 폭 20%↓는 화면용(검증 밖) — 오늘 막 무너진 종목(15일 폭 30~58%) 빼려고


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = pd.read_sql(text("select stock_code s, trading_date d, high_price h, low_price l, close_price c, volume v, trading_value tv "
                          "from spot_daily_prices where trading_date >= cast(:d as date) - 200"), db.connection(), params={"d": latest})
    P = {k: px.pivot(index="d", columns="s", values=k).sort_index().astype(float) for k in ("h", "l", "c", "v", "tv")}
    H, L, C, V, TV = (P[k] for k in ("h", "l", "c", "v", "tv"))
    names = dict(db.execute(text("select code, name from stocks")).all())
    from backend.screener.rotation import family_members  # noqa: PLC0415
    from backend.screener.market_regime import current_regime  # noqa: PLC0415
    fam_of: dict[str, list[str]] = {}
    for f, mem in family_members(db).items():
        for c in mem:
            fam_of.setdefault(c, []).append(f)
    from backend.screener.my_pattern import CYCLE_START  # noqa: PLC0415
    import datetime as _dt  # noqa: PLC0415
    _cyc = max(_dt.date.fromisoformat(CYCLE_START), C.index[-60]) if len(C.index) >= 60 else _dt.date.fromisoformat(CYCLE_START)
    items = []
    for c in C.columns:
        s = C[c].dropna()
        if len(s) < 120 or s.index[-1] != C.index[-1]:
            continue
        liq = float(TV[c].tail(20).mean() or 0)
        if liq < MIN_TV:
            continue
        cl = float(s.iloc[-1])
        ma120 = float(s.tail(120).mean())
        hi60 = float(H[c][H.index >= _cyc].max()) if (H.index >= _cyc).any() else float(H[c].tail(60).max())   # 7/30 바닥 이후 고점 (사용자 2026-10-07)
        off = cl / hi60 - 1
        vr = float(V[c].tail(5).mean() / V[c].tail(60).mean()) if V[c].tail(60).mean() else 9
        if not (cl > ma120 * 0.97 and OFF_LO <= off <= OFF_HI and vr <= MAX_VR):
            continue
        lo15, hi15 = float(L[c].tail(15).min()), float(H[c].tail(15).max())
        if hi15 / lo15 - 1 > MAX_BOX:
            continue
        stop = round(lo15 * 0.99)
        items.append({"code": c, "name": names.get(c, c), "close": round(cl), "change_pct": round((cl / float(s.iloc[-2]) - 1) * 100, 2),
                      "off_hi60_pct": round(off * 100, 1), "hi60": round(hi60), "vol_ratio": round(vr, 2),
                      "box_pct": round((hi15 / lo15 - 1) * 100, 1), "stop": stop, "stop_pct": round((stop / cl - 1) * 100, 1),
                      "liq_eok": round(liq / 1e8), "families": fam_of.get(c, [])[:2]})
    items.sort(key=lambda x: -x["liq_eok"])
    try:
        from backend.services.stock_signals import rs_latest  # noqa: PLC0415
        rs = rs_latest(db)
    except Exception:  # noqa: BLE001
        rs = {}
    for x in items:
        x["rs"] = rs.get(x["code"])
    return {"trading_date": C.index[-1].isoformat(), "market": (current_regime(db) or {}).get("state"), "items": items}
