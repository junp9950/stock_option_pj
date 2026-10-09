"""순환매 모니터: 272개 테마를 섹터 16개로 묶어 매일 순위·확산·자금 흐름을 본다.

- 20일 상승: 섹터 소속 종목 20일 수익률 중간값, 순위는 16개 중
- 확산: 20일선 위 종목 비율
- 자금: 최근 5일 섹터 거래대금 평균 / 그 전 20거래일 평균
- 과열: 섹터 안 종목 중 20일선 이격도 +20% 넘은 비율이 20% 이상 (10~20%는 주의)
  3년 확인(같은 날 16개 섹터 평균 대비 20일 뒤): 0~5% +0.12%p, 10~20% -0.34%p, 20~30% -1.72%p(55건), 30%↑ -3.12%p(8건).
  1~2위 섹터는 20%↑ -2.36%p(49건). 예전 기준(확산 90%·자금 감소)은 자금 감소가 오히려 덜 빠져 버렸다.
3년 확인(상승·횡보장): 뜨거운 섹터 상위 3 + 그날 섹터 거래대금 1.2배 이상인 날의 거래 실린 양봉은 다음 날 평균 +0.94%(수익 71%),
섹터 밖은 +0.28%.
단 섹터 단위 '다음 10~20일 어느 섹터가 앞서나'는 거의 맞히지 못했다(같은 날 16개 평균 대비): 1~2위 -0.35%p/-0.47%p,
유입(순위 3계단↑+자금 1.05배) -0.20%p, 순위 하락 +0.17%p — 모두 1%p 미만. 그래서 이 화면은 '지금 어디에 돈이 붙었나'를 보는 용도다.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

FAMILIES: dict[str, str] = {
    "AI메모리·기판": r"HBM|CXL|소캠|SOCAMM|반도체 기판|FC-BGA|PCB|DDR|메모리|낸드|D램",
    "반도체 장비·재료": r"반도체 장비|반도체 재료|반도체 부품|시스템반도체|파운드리|온디바이스|AI반도체|NPU|칩렛|유리기판",
    "전력·전선": r"전선|전력|변압기|스마트그리드|ESS|초고압",
    "원전·에너지": r"원자력|원전|SMR|핵융합",
    "신재생": r"태양광|풍력|수소|연료전지|SOFC|신재생",
    "로봇": r"로봇|휴머노이드|피지컬 AI",
    "우주항공·방산": r"우주|위성|스페이스X|누리호|방산|드론|항공",
    "통신": r"통신장비|광통신|5G|6G|유심|USIM",
    "2차전지": r"2차전지|리튬|전고체|양극재|음극재|전해질|폐배터리",
    "바이오": r"제약|바이오|신약|항암|비만|치료제|백신|의료기기",
    "조선·해운": r"조선|해운|LNG",
    "자동차": r"자동차|전기차|자율주행|타이어",
    "화장품·소비": r"화장품|음식료|면세",
    "게임·엔터": r"게임|엔터|K-POP|웹툰|드라마",
    "금융·지주": r"증권|은행|보험|지주사",   # '밸류업'은 뺌 — 밸류업 지수·계획 테마는 업종이 아니라서 금융 섹터 355종목 중 157개가 이것 때문에 들어와 있었음 (2026-10-07)
    "AI SW·플랫폼": r"인공지능|AI 챗봇|클라우드|데이터센터|소프트웨어|플랫폼|핀테크|전자결제|애플페이",
}


EXCLUDE_KEY = "sector_exclusions"   # settings 표: {"종목코드": ["섹터", ...]} — 네이버 테마 때문에 붙었지만 시장이 그렇게 안 보는 섹터에서 뺌
# 기본값 (2026-10-07 사용자: "LS ELECTRIC·효성중공업이 신재생에 드가는 게 맞나") — 태양광·수소·풍력 테마가 붙어 있지만 전력기기주
DEFAULT_EXCLUSIONS = {"010120": ["신재생"], "298040": ["신재생"]}
OVERRIDE_KEY = "sector_overrides"   # settings 표: {"종목코드": "섹터"} — 네이버 테마가 시장이 보는 재료를 못 따라갈 때 직접 지정


def get_overrides(db: Session) -> dict[str, str]:
    raw = db.execute(text("select value from settings where key = :k"), {"k": OVERRIDE_KEY}).scalar()
    try:
        return {k: v for k, v in json.loads(raw or "{}").items() if v in FAMILIES}
    except ValueError:
        return {}


def set_override(db: Session, code: str, family: str | None) -> dict[str, str]:
    """family가 비면 지정을 지운다. 지정은 원래 테마 분류에 '더하는' 것 (원래 섹터에서 빼지 않음)."""
    from backend.db.models import JobLog, Setting  # noqa: PLC0415
    ov = get_overrides(db)
    if family:
        ov[code] = family
    else:
        ov.pop(code, None)
    row = db.query(Setting).filter(Setting.key == OVERRIDE_KEY).one_or_none()
    if row is None:
        db.add(Setting(key=OVERRIDE_KEY, value=json.dumps(ov, ensure_ascii=False)))
    else:
        row.value = json.dumps(ov, ensure_ascii=False)
    db.add(JobLog(stage="sector_override", status="completed", message=f"{code} → {family or '지정 해제'}"))  # 화면 캐시 갱신용
    db.commit()
    return ov


def family_members(db: Session) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {f: set() for f in FAMILIES}
    for code, theme in db.execute(text(
        "select ss.stock_code, s.sector_name from sector_stocks ss join sectors s on s.id = ss.sector_id where s.is_active"
    )):
        for f, pat in FAMILIES.items():
            if re.search(pat, theme or ""):
                out[f].add(code)
    for code, f in get_overrides(db).items():
        out[f].add(code)
    for code, fams in get_exclusions(db).items():
        for f in fams:
            out.get(f, set()).discard(code)
    return {f: sorted(m) for f, m in out.items()}


def get_exclusions(db: Session) -> dict[str, list[str]]:
    raw = db.execute(text("select value from settings where key = :k"), {"k": EXCLUDE_KEY}).scalar()
    try:
        ex = json.loads(raw) if raw else {}
    except ValueError:
        ex = {}
    merged = {k: list(v) for k, v in DEFAULT_EXCLUSIONS.items()}
    for k, v in (ex or {}).items():
        merged[k] = sorted(set(merged.get(k, [])) | set(v))
    return merged


def scan(db: Session, live: dict | None = None, frac: float = 1.0) -> dict:
    """live = {code: {c, v, chg}} 이면 오늘 줄을 붙여 장중 기준으로 계산 (거래대금은 frac로 나눠 마감 환산)."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": []}
    px = pd.read_sql(text("select stock_code, trading_date, close_price c, trading_value tv, change_pct ch from spot_daily_prices "
                          "where trading_date >= :d"), db.connection(), params={"d": latest - timedelta(days=110)})
    names = dict(db.execute(text("select code, name from stocks")).all())
    C = px.pivot(index="trading_date", columns="stock_code", values="c").sort_index()
    TV = px.pivot(index="trading_date", columns="stock_code", values="tv").sort_index()
    CH = px.pivot(index="trading_date", columns="stock_code", values="ch").sort_index()
    if live:
        today = datetime.now(_KST).date()
        cc = [c for c in C.columns if c in live]
        C = pd.concat([C, pd.DataFrame([{c: live[c]["c"] for c in cc}], index=[today])])
        TV = pd.concat([TV, pd.DataFrame([{c: live[c]["c"] * live[c]["v"] / max(frac, 0.05) for c in cc}], index=[today])])
        CH = pd.concat([CH, pd.DataFrame([{c: live[c]["chg"] for c in cc}], index=[today])])
    ret20 = C / C.shift(20) - 1
    above = C > C.rolling(20).mean()
    stretched = (C / C.rolling(20).mean() - 1) >= 0.2   # 20일선보다 20% 넘게 뜬 종목
    rows = {}
    for f, mem in family_members(db).items():
        m = [x for x in mem if x in C.columns]
        if len(m) < 5:
            continue
        tv = TV[m].sum(axis=1)
        rows[f] = {
            "ret20": ret20[m].median(axis=1), "breadth": above[m].mean(axis=1),
            "tv5": tv.rolling(5).mean() / tv.shift(5).rolling(20, min_periods=15).mean(),
            "tv1": tv / tv.shift(1).rolling(20, min_periods=15).mean(),
            "ret5": (C[m] / C[m].shift(5) - 1).median(axis=1), "chg": CH[m].median(axis=1), "members": m,
            "stretch": stretched[m].mean(axis=1),
        }
    ret_df = pd.DataFrame({f: r["ret20"] for f, r in rows.items()})
    rank = ret_df.rank(axis=1, ascending=False)
    d, d10 = C.index[-1], C.index[-11]
    items = []
    for f, r in rows.items():
        tv5 = r["tv5"]
        st = float(r["stretch"].iloc[-1])
        m = r["members"]
        # 오늘 돈이 붙은 종목: 거래대금이 20일 평균의 2배 이상·30억 이상인 것 중 많이 오른 순 (대형주는 여러 섹터에 다 속해서 거래대금 순은 의미가 없다)
        avg20 = TV[m].iloc[-21:-1].mean()
        today = pd.DataFrame({"tv": TV.loc[d, m], "ch": CH.loc[d, m], "x": TV.loc[d, m] / avg20}).dropna()
        today = today[(today.x >= 2) & (today.tv >= 3e9)].sort_values("ch", ascending=False).head(3)
        items.append({
            "family": f, "count": len(m),
            "rank": int(rank.at[d, f]), "rank_10ago": int(rank.at[d10, f]),
            "ret20_pct": round(float(r["ret20"].iloc[-1]) * 100, 1), "ret5_pct": round(float(r["ret5"].iloc[-1]) * 100, 1),
            "chg_pct": round(float(r["chg"].iloc[-1]), 2),
            "breadth_pct": round(float(r["breadth"].iloc[-1]) * 100), "breadth_10ago": round(float(r["breadth"].loc[d10]) * 100),
            "tv5_x": round(float(tv5.iloc[-1]), 2), "tv5_peak5": round(float(tv5.iloc[-6:].max()), 2), "tv1_x": round(float(r["tv1"].iloc[-1]), 2),
            "stretch_pct": round(st * 100), "stretch_10ago": round(float(r["stretch"].loc[d10]) * 100),
            "status": "과열" if st >= 0.2 else ("주의" if st >= 0.1 else ""),
            "leaders": [{"code": c, "name": names.get(c, c), "change_pct": round(float(x.ch), 1), "tv_x": round(float(x.x), 1)} for c, x in today.iterrows()],
        })
    items.sort(key=lambda x: x["rank"])
    return {"trading_date": d.isoformat(), "items": items}


_KST = ZoneInfo("Asia/Seoul")
_LIVE: dict = {"t": 0.0, "v": None}
_LIVE_LOCK = threading.Lock()


def scan_live(db: Session, max_age: float = 90) -> dict | None:
    """장중(평일 9:00~DB 갱신 전)에는 네이버 실시간 시세로 다시 계산 — 90초 캐시, 계산 중이면 직전 결과 (2026-10-08 사용자 요청)."""
    now = datetime.now(_KST)
    if now.weekday() >= 5 or now.hour < 9:
        return None
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None or latest >= now.date():
        return None
    hit = _LIVE["v"]
    if hit and hit.get("trading_date") == now.date().isoformat() and time.time() - _LIVE["t"] < max_age:
        return hit
    if not _LIVE_LOCK.acquire(blocking=hit is None):
        return hit if hit and hit.get("trading_date") == now.date().isoformat() else None
    try:
        from backend.screener.my_pattern import _day_frac  # noqa: PLC0415
        from backend.services.naver_live import snapshot  # noqa: PLC0415
        codes = [r[0] for r in db.execute(text("select distinct stock_code from spot_daily_prices where trading_date = :d"), {"d": latest}).all()]
        live = snapshot(codes)
        if len(live) < len(codes) * 0.5:      # 휴장일·장 전·네이버 실패
            return None
        frac = 1.0 if (now.hour, now.minute) >= (15, 30) else _day_frac(now)
        out = scan(db, live=live, frac=frac)
        out["live"] = {"as_of": now.strftime("%H:%M"), "projected": frac < 1.0}
        _LIVE.update(t=time.time(), v=out)
        return out
    finally:
        _LIVE_LOCK.release()



_MEM: dict = {"t": 0.0, "key": None, "v": None}
_MEM_LOCK = threading.Lock()


def members_all(db: Session) -> dict:
    """16개 섹터 소속 종목을 한 번에 (섹터 누르면 바로 펼치게 미리 받아 둔다, 2026-10-09). 장중 90초 · 그 밖엔 DB 날짜가 바뀔 때까지 캐시."""
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    now = datetime.now(_KST)
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    live_on = now.weekday() < 5 and now.hour >= 9 and latest is not None and latest < now.date() and is_trading_day(now.date())
    key = (str(latest), live_on)
    if _MEM["v"] is not None and _MEM["key"] == key and (not live_on or time.time() - _MEM["t"] < 90):
        return _MEM["v"]
    with _MEM_LOCK:
        if _MEM["v"] is not None and _MEM["key"] == key and (not live_on or time.time() - _MEM["t"] < 90):
            return _MEM["v"]
        fams = family_members(db)
        allc = sorted({c for m in fams.values() for c in m})
        px = pd.read_sql(text("select stock_code s, trading_date d, close_price c, trading_value tv from spot_daily_prices "
                              "where trading_date >= cast(:d as date) - 45 and stock_code = any(:m)"), db.connection(), params={"d": latest, "m": allc})
        C = px.pivot(index="d", columns="s", values="c").sort_index().astype(float)
        TV = px.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
        names = dict(db.execute(text("select code, name from stocks")).all())
        live, as_of = {}, str(C.index[-1])
        if live_on:
            from backend.services.naver_live import snapshot  # noqa: PLC0415
            live = snapshot(list(C.columns))
            if live:
                as_of = f"오늘 {now:%H:%M}"
        rows = {}
        for c in C.columns:
            s_ = C[c].dropna()
            avg = TV[c].iloc[-21:-1].mean()
            if len(s_) < 21 or not avg or avg < 1e9:
                continue
            last = s_.iloc[-1]
            if c in live:
                now_p, prev, tv_today = live[c]["c"], last, live[c]["c"] * live[c]["v"]
                ma20, base20 = (s_.iloc[-19:].sum() + now_p) / 20, s_.iloc[-20]
            else:
                now_p, prev, tv_today = last, s_.iloc[-2], TV[c].iloc[-1]
                ma20, base20 = s_.iloc[-20:].mean(), s_.iloc[-21]
            rows[c] = {"code": c, "name": names.get(c, c), "chg": round(float(now_p / prev - 1) * 100, 1), "ret20": round(float(now_p / base20 - 1) * 100, 1),
                       "gap20": round(float(now_p / ma20 - 1) * 100, 1), "tv_x": round(float(tv_today / avg), 1), "tv": round(float(tv_today) / 1e8)}
        out = {"as_of": as_of, "live": bool(live),
               "families": {f: sorted((rows[c] for c in m if c in rows), key=lambda x: -x["chg"]) for f, m in fams.items()}}
        _MEM.update(t=time.time(), key=key, v=out)
        return out


def members(db: Session, family: str) -> dict:
    d = members_all(db)
    return {"family": family, "as_of": d["as_of"], "live": d["live"], "items": d["families"].get(family, [])}
