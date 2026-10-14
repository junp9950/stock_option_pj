"""코스피200 선물 일일 수급 해석 (2026-10-14 사용자 "그럼 이건 니가 매일 분석할 수 있나").

매일 16:47(선물 확정치 16:40 뒤): 외국인 순매수(억) × 미결제약정 증감으로 유형을 붙이고 사장님 텔레그램으로.
  🟢 신규 매수형 = 외국인 매수 + 미결제 증가 (새로 상승에 걸음)      🔄 숏커버형 = 외국인 매수 + 미결제 감소 (하락 베팅 정리)
  🔴 신규 매도형 = 외국인 매도 + 미결제 증가 (새로 하락에 걸음)      ⚪ 매수 청산형 = 외국인 매도 + 미결제 감소 (상승 베팅 정리)
  외국인 매수·매도 = 금액÷선물가(계약 수 비례)의 60일 표준점수 ±0.5 밖. 그 안이면 '보통'.
지난 자료: 사용자 증권사 내보내기(외국인·기관·개인 금액, 2025-03~) + 한국거래소 미결제약정(모든 만기 합) — 표 futures_daily.
그날 자료: futures_flow_intraday 마지막 줄(네이버 확정치 · KIS 최근월 미결제 증감) + 네이버 코스피200 종가.
검증(futx/lab/oi_test.py, 323일): 신규 매수형 다음 날 +0.79%(68% 오름) · 숏커버형 −0.27% · 신규 매도형 +0.17% · 매수 청산형 −0.77% · 기준 +0.33% — 1년 반·상승장뿐이라 '참고'.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
KINDS = {"new_long": "🟢 신규 매수형", "cover": "🔄 숏커버형", "new_short": "🔴 신규 매도형", "liq": "⚪ 매수 청산형", "none": "보통"}
MEANING = {"new_long": "새로 상승에 걸음", "cover": "하락 베팅 정리", "new_short": "새로 하락에 걸음", "liq": "상승 베팅 정리", "none": "외국인 매매가 평소 수준"}


def _ensure(db: Session) -> None:
    db.execute(text("""create table if not exists futures_daily (d date primary key, foreign_eok double precision, inst_eok double precision,
        indiv_eok double precision, oi double precision, doi double precision, fut double precision, spot double precision, expiry boolean default false,
        src varchar(10), updated_at timestamptz default now())"""))
    db.commit()


def record(db: Session, day: date | None = None) -> dict | None:
    """그날 확정치를 표에 (16:47). 자료가 없으면 None."""
    _ensure(db)
    day = day or datetime.now(KST).date()
    r = db.execute(text("""select foreign_eok, inst_eok, indiv_eok, price, oi, oi_chg from futures_flow_intraday
        where ts::date = :d and foreign_eok is not null order by ts desc limit 1"""), {"d": day}).first()
    if r is None:
        return None
    spot = None
    try:
        j = requests.get("https://m.stock.naver.com/api/index/KPI200/basic", headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json()
        if str(j.get("localTradedAt", "")).startswith(str(day)):
            spot = float(str(j.get("closePrice")).replace(",", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("코스피200 종가 실패: %s", type(exc).__name__)
    db.execute(text("""insert into futures_daily (d, foreign_eok, inst_eok, indiv_eok, oi, doi, fut, spot, src) values (:d, :f, :i, :p, :oi, :doi, :fut, :spot, 'live')
        on conflict (d) do update set foreign_eok = excluded.foreign_eok, inst_eok = excluded.inst_eok, indiv_eok = excluded.indiv_eok,
        oi = coalesce(excluded.oi, futures_daily.oi), doi = coalesce(excluded.doi, futures_daily.doi), fut = coalesce(excluded.fut, futures_daily.fut),
        spot = coalesce(excluded.spot, futures_daily.spot), updated_at = now()"""),
               {"d": day, "f": r[0], "i": r[1], "p": r[2], "oi": r[4], "doi": r[5], "fut": r[3], "spot": spot})
    db.commit()
    return {"d": str(day)}


def _frame(db: Session):
    import pandas as pd  # noqa: PLC0415
    _ensure(db)
    x = pd.DataFrame(db.execute(text("select d, foreign_eok, inst_eok, indiv_eok, oi, doi, fut, spot, expiry from futures_daily order by d")).all(),
                     columns=["d", "f", "inst", "indiv", "oi", "doi", "fut", "spot", "expiry"])
    if x.empty:
        return x
    x["fc"] = x.f / x.fut.fillna(x.spot)                       # 계약 수 비례
    x["z"] = (x.fc - x.fc.rolling(60, min_periods=30).mean()) / x.fc.rolling(60, min_periods=30).std()
    x["kind"] = "none"
    x.loc[(x.z > 0.5) & (x.doi > 0), "kind"] = "new_long"
    x.loc[(x.z > 0.5) & (x.doi < 0), "kind"] = "cover"
    x.loc[(x.z < -0.5) & (x.doi > 0), "kind"] = "new_short"
    x.loc[(x.z < -0.5) & (x.doi < 0), "kind"] = "liq"
    x["r1"] = x.spot.shift(-1) / x.spot * 100 - 100
    return x


def analyze(db: Session, day: date | None = None) -> dict | None:
    x = _frame(db)
    if x.empty:
        return None
    if day is not None:
        x = x[x.d <= day]
    if x.empty:
        return None
    t = x.iloc[-1]
    hist = x.iloc[:-1]
    hist = hist[~hist.expiry.fillna(False).astype(bool) & hist.r1.notna()]
    same = hist[hist.kind == t.kind]
    streak = 0
    for k in reversed(x.kind.tolist()):
        if k != t.kind:
            break
        streak += 1
    f3, f3p = x.f.iloc[-3:].sum(), x.f.iloc[-6:-3].sum()
    return {"d": str(t.d), "kind": t.kind, "label": KINDS[t.kind], "meaning": MEANING[t.kind], "foreign": float(t.f), "inst": float(t.inst or 0),
            "indiv": float(t.indiv or 0), "contracts": round(float(t.f) * 1e8 / (float(t.fut or t.spot) * 250000)) if (t.fut or t.spot) else None,
            "oi": None if t.oi != t.oi else float(t.oi), "doi": None if t.doi != t.doi else float(t.doi), "z": round(float(t.z), 2) if t.z == t.z else None,
            "basis": round(float(t.fut - t.spot), 2) if t.fut == t.fut and t.spot == t.spot else None, "fut": t.fut, "spot": t.spot,
            "streak": streak, "f3": float(f3), "f3_prev": float(f3p),
            "stat": {"n": int(len(same)), "r1": round(float(same.r1.mean()), 2) if len(same) else None, "up": round(float((same.r1 > 0).mean() * 100)) if len(same) else None,
                     "base": round(float(hist.r1.mean()), 2) if len(hist) else None}}


def message(db: Session, day: date | None = None) -> str | None:
    a = analyze(db, day)
    if not a:
        return None
    sg = lambda v: f"{v:+,.0f}"  # noqa: E731
    d = date.fromisoformat(a["d"])
    out = [f"📊 <b>코스피200 선물 수급 — {d.month}/{d.day} 마감</b>",
           f"외국인 {sg(a['foreign'])}억" + (f" (≈{a['contracts']:+,}계약)" if a["contracts"] is not None else "") + f" · 기관 {sg(a['inst'])} · 개인 {sg(a['indiv'])}",
           (f"미결제 {sg(a['doi'])}계약" if a["doi"] is not None else "미결제 증감 없음") + f" → <b>{a['label']}</b> ({a['meaning']})"]
    if a["streak"] >= 2 and a["kind"] != "none":
        out.append(f"{'⚠️ ' if a['kind'] == 'new_short' else ''}{a['label']} {a['streak']}일 연속")
    out.append(f"최근 3일 외국인 {sg(a['f3'])}억 · 그 전 3일 {sg(a['f3_prev'])}억")
    if a["basis"] is not None:
        out.append(f"베이시스 {a['basis']:+.2f} (선물 {a['fut']:,.2f} · 현물 {a['spot']:,.2f})")
    s = a["stat"]
    if a["kind"] != "none" and s["n"]:
        out.append(f"지난 기록 '{a['label'][2:]}' {s['n']}번: 다음 날 평균 {s['r1']:+.2f}% · 오른 날 {s['up']}% (전체 {s['base']:+.2f}%) — 참고, 검증 중")
    return "\n".join(out)


def daily_job(db: Session) -> str:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = datetime.now(KST).date()
    if not is_trading_day(today):
        return "장 없는 날"
    if record(db, today) is None:
        return "오늘 선물 자료 없음"
    msg = message(db, today)
    if msg:
        from backend.services.telegram import owner_chats, send  # noqa: PLC0415
        for c in owner_chats(db):
            send(db, msg, c, html=True)
    return "보냄"
