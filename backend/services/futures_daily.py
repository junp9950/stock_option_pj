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


def _program(d: date) -> dict:
    """코스피 프로그램 매수·매도·순(억) {날짜: {'nb','ns','ab','as'}} — KIS 프로그램매매 종합(일별), 단위 백만원.
    2026-10-16 사용자 "프로그램 매수매도 비차익 차익은 안 나오나"."""
    import os  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
    from backend.collector.spot import _get_kis_token  # noqa: PLC0415
    tok = _get_kis_token()
    if not tok:
        return {}
    h = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {tok}", "appkey": os.getenv("KIS_APP_KEY", ""),
         "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": "FHPPG04600001", "custtype": "P"}
    p = {"FID_COND_MRKT_DIV_CODE": "J", "FID_MRKT_CLS_CODE": "K", "FID_INPUT_DATE_1": (d - timedelta(days=14)).strftime("%Y%m%d"), "FID_INPUT_DATE_2": d.strftime("%Y%m%d")}
    try:
        rows = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/comp-program-trade-daily", headers=h, params=p, timeout=10).json().get("output") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("프로그램 매매 조회 실패: %s", type(exc).__name__)
        return {}
    f = lambda x, k: float(x.get(k) or 0) / 100  # noqa: E731
    return {date(int(x["stck_bsop_date"][:4]), int(x["stck_bsop_date"][4:6]), int(x["stck_bsop_date"][6:])):
            {"nb": f(x, "nabt_smtn_shnu_tr_pbmn"), "ns": f(x, "nabt_smtn_seln_tr_pbmn"), "ab": f(x, "arbt_smtn_shnu_tr_pbmn"), "as": f(x, "arbt_smtn_seln_tr_pbmn")}
            for x in rows if x.get("stck_bsop_date")}


NAMES = {"new_long": "신규 매수형", "cover": "숏커버형", "new_short": "신규 매도형", "liq": "매수 청산형", "none": "보통"}


def message(db: Session, day: date | None = None, copy: bool = False) -> str | None:
    """copy=True = 펨코 복붙용 (2026-10-16 사용자 양식): 제목·해석·통계 줄 없이 숫자만.
    수급 정리 (외국인 현물·선물·프로그램) — 2026-10-16 사용자 "복붙하면 보기 싫다 · 아이콘 빼고 · 이름은 수급 정리":
    아이콘·굵은 글씨·표 없이 한 줄에 하나, 복사해도 깨지지 않게."""
    a = analyze(db, day)
    if not a:
        return None
    sg = lambda v: f"{v:+,.0f}"  # noqa: E731
    d = date.fromisoformat(a["d"])
    rows = db.execute(text("""select trading_date, sum(case when market = 'KOSPI' then frgn end) / 100.0, sum(case when market = 'KOSDAQ' then frgn end) / 100.0
        from market_investor_flows where trading_date <= :d group by 1 order by 1 desc limit 5"""), {"d": d}).all()
    sp = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in rows if r[1] is not None}
    futs = {k: float(v) for k, v in db.execute(text("select d, foreign_eok from futures_daily where d = any(:ds)"), {"ds": list(sp) or [d]}).all() if v is not None}
    pg = _program(d)
    out = [] if copy else [f"수급 총정리 {d.month}/{d.day} 마감 (코스피 · 억 원)", ""]
    # 개인·기관 현물 (2026-10-16 사용자 "개인, 기관도 넣어 봐 수급 총정리로") — 기관 안: 금융투자·연기금·투신·보험·사모
    iv = db.execute(text("""select prsn, orgn, scrt, mrbn, ivtr, insu, pe_fund, etc_corp from market_investor_flows where trading_date = :d and market = 'KOSPI'"""), {"d": d}).first()
    ivq = db.execute(text("""select prsn, orgn from market_investor_flows where trading_date = :d and market = 'KOSDAQ'"""), {"d": d}).first()
    iv = [float(v or 0) / 100 for v in iv] if iv else None
    ivq = [float(v or 0) / 100 for v in ivq] if ivq else None
    out.append("[외국인]")
    if d in sp:
        out.append(f"현물 {sg(sp[d][0])} (코스닥 {sg(sp[d][1])})")
    out.append(f"선물 {sg(a['foreign'])}" + (f" (약 {a['contracts']:+,}계약)" if a["contracts"] is not None else ""))
    if d in sp:
        t = sp[d][0] + a["foreign"]
        out.append(f"현물+선물 {sg(t)}" + ("" if copy else f" → {'사는 쪽' if t > 0 else '파는 쪽'}"))
    if iv:
        out += ["", "[기관]", f"현물 {sg(iv[1])}" + (f" (코스닥 {sg(ivq[1])})" if ivq else ""),
                f"금융투자 {sg(iv[2])} · 연기금 {sg(iv[3])} · 투신 {sg(iv[4])} · 보험 {sg(iv[5])} · 사모 {sg(iv[6])}",
                f"선물 {sg(a['inst'])}", f"현물+선물 {sg(iv[1] + a['inst'])}",
                "", "[개인]", f"현물 {sg(iv[0])}" + (f" (코스닥 {sg(ivq[0])})" if ivq else ""),
                f"선물 {sg(a['indiv'])}", f"현물+선물 {sg(iv[0] + a['indiv'])}"]
        if not copy:      # 자사주 매입 등 — 사장님용에만 (복붙용은 빼 달라, 2026-10-16)
            out += ["", "[기타법인]", f"현물 {sg(iv[7])}"]
    out += ["", "[선물]"]
    if not iv:
        out.append(f"기관 {sg(a['inst'])} · 개인 {sg(a['indiv'])}")
    if a["doi"] is not None:
        out.append(f"미결제 {sg(a['doi'])}계약" + (f" (남은 {a['oi']:,.0f})" if a["oi"] else ""))
    if not copy:
        out.append(f"선물만 보면 {NAMES[a['kind']]} ({a['meaning']})" + (f" · {a['streak']}일 연속" if a["streak"] >= 2 and a["kind"] != "none" else ""))
    if a["basis"] is not None:
        out.append(f"베이시스 {a['basis']:+.2f} (선물 {a['fut']:,.2f} · 현물 {a['spot']:,.2f})")
    if d in pg:
        x = pg[d]
        out += ["", "[프로그램]",
                f"비차익 매수 {x['nb']:,.0f} · 매도 {x['ns']:,.0f} · 순 {sg(x['nb'] - x['ns'])}",
                f"차익 매수 {x['ab']:,.0f} · 매도 {x['as']:,.0f} · 순 {sg(x['ab'] - x['as'])}",
                f"합계 순 {sg(x['nb'] - x['ns'] + x['ab'] - x['as'])}"]
    days = sorted(sp)
    if len(days) >= 2 and not copy:      # 최근 5일·3일 합은 사장님용에만 (2026-10-16 "복붙용 말고 따로")
        out += ["", "[최근 5일] 외국인 현물 / 선물 / 합계 / 프로그램"]
        for k in days:
            f_ = futs.get(k)
            pr = (pg[k]["nb"] - pg[k]["ns"] + pg[k]["ab"] - pg[k]["as"]) if k in pg else None
            out.append(f"{k.month}/{k.day}  {sg(sp[k][0])} / " + (f"{sg(f_)} / {sg(sp[k][0] + f_)}" if f_ is not None else "- / -")
                       + (f" / {sg(pr)}" if pr is not None else ""))
        l3 = days[-3:]
        if all(k in futs for k in l3):
            s3 = sum(sp[k][0] for k in l3); f3 = sum(futs[k] for k in l3)
            out.append(f"3일 합계 현물 {sg(s3)} + 선물 {sg(f3)} = {sg(s3 + f3)}")
            if (s3 > 0) != (f3 > 0) and abs(s3) > 1000 and abs(f3) > 1000 and not copy:
                out.append("현물과 선물 방향이 반대 — 선물 매매는 헤지·차익일 수 있어 선물만으로 롱·숏 판단 금지")
    s = a["stat"]
    if a["kind"] != "none" and s["n"] and not copy:
        out += ["", f"지난 기록 {NAMES[a['kind']]} {s['n']}번: 다음 날 평균 {s['r1']:+.2f}% · 오른 날 {s['up']}% (전체 {s['base']:+.2f}%) · 참고용"]
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
            send(db, msg, c)
            cp = message(db, today, copy=True)      # 펨코 복붙용 하나 더 (2026-10-16 사용자)
            if cp:
                send(db, cp, c)
    return "보냄"
