"""시장 주요 일정 — 섹터 캘린더 탭 좌우 '이번 주 / 이번 달 일정' (2026-10-11 사용자 "미국 실적·지표, 한국 주요 일정").

출처
- 미국·한국 경제지표: Nasdaq 경제 일정 API. 주의 — ?date=D 로 물으면 미국 날짜 D-1 의 일정이 오고, 시각은 미국 동부시간이다
  (CPI 08:30, FOMC 14:00 으로 확인). 여기서 한국 시각으로 바꿔 저장한다.
- 미국 실적: Nasdaq 실적 일정 API (날짜는 그대로). 장 전 발표 = 한국 같은 날 밤, 장 마감 후 = 한국 다음 날 새벽.
- 한국 실적: DART 기업설명회(IR) 개최 안내 공시 중 목적에 '실적'이 든 것 (시가총액 상위 200). 날짜는 공시 화면에서 읽는다.
  지난 잠정실적 공시도 그날 일정으로 남긴다.
- 규칙으로 아는 것: 옵션 만기(둘째 목요일), 국내·미국 휴장, 수출입 동향(1일 · 11일 · 21일).
표 market_events: 날짜·시각은 모두 한국 시간.
"""
from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Nasdaq 이름 → (한국어, 중요도 2=중요 1=보통). 여기 없는 지표는 넣지 않는다.
US_EVENTS = {
    "Fed Interest Rate Decision": ("FOMC 금리 결정", 2), "FOMC Meeting Minutes": ("FOMC 의사록", 2),
    "CPI": ("소비자물가(CPI)", 2), "Core CPI": ("근원 소비자물가", 2),
    "Nonfarm Payrolls": ("비농업 고용", 2), "Unemployment Rate": ("실업률", 2),
    "PCE Price index": ("PCE 물가", 2), "Core PCE Price Index": ("근원 PCE 물가", 2),
    "GDP": ("GDP 성장률", 2), "PPI": ("생산자물가(PPI)", 2), "Retail Sales": ("소매판매", 2),
    "ISM Manufacturing PMI": ("ISM 제조업 지수", 2), "ISM Non-Manufacturing PMI": ("ISM 서비스업 지수", 2),
    "Core PPI": ("근원 생산자물가", 1), "Core Retail Sales": ("근원 소매판매", 1),
    "Initial Jobless Claims": ("신규 실업수당 청구", 1), "Average Hourly Earnings": ("평균 시간당 임금", 1),
    "JOLTS Job Openings": ("구인 건수(JOLTS)", 1), "ADP Nonfarm Employment Change": ("ADP 민간 고용", 1),
    "Michigan Consumer Sentiment": ("미시간대 소비자심리", 1), "Michigan 1-Year Inflation Expectations": ("미시간대 기대인플레이션", 1),
    "CB Consumer Confidence": ("소비자신뢰지수(CB)", 1), "Existing Home Sales": ("기존주택 판매", 1), "New Home Sales": ("신규주택 판매", 1),
    "Durable Goods Orders": ("내구재 주문", 1), "Philadelphia Fed Manufacturing Index": ("필라델피아 연은 제조업", 1),
    "NY Empire State Manufacturing Index": ("뉴욕 연은 제조업", 1), "Industrial Production": ("산업생산", 1),
    "Personal Spending": ("개인소비지출", 1), "Personal Income": ("개인소득", 1), "Housing Starts": ("주택착공", 1),
    "Beige Book": ("베이지북", 1), "Employment Cost Index": ("고용비용지수", 1), "Trade Balance": ("무역수지", 1),
}
KR_EVENTS = {"Interest Rate Decision": ("한국은행 금리 결정 (금통위)", 2), "GDP": ("한국 GDP 성장률", 2), "CPI": ("한국 소비자물가", 1)}

# 미국 실적 — 한국 투자자가 많이 보는 종목만. 2 = 빅테크·반도체(한국 반도체 주가에 바로 영향)
US_EARNINGS = {
    "AAPL": ("애플", 2), "MSFT": ("마이크로소프트", 2), "NVDA": ("엔비디아", 2), "GOOGL": ("알파벳(구글)", 2), "AMZN": ("아마존", 2),
    "META": ("메타", 2), "TSLA": ("테슬라", 2), "AVGO": ("브로드컴", 2), "TSM": ("TSMC", 2), "ASML": ("ASML", 2), "AMD": ("AMD", 2),
    "MU": ("마이크론", 2), "LRCX": ("램리서치", 2), "AMAT": ("어플라이드 머티리얼즈", 2), "KLAC": ("KLA", 2), "INTC": ("인텔", 2),
    "QCOM": ("퀄컴", 2), "NFLX": ("넷플릭스", 2), "JPM": ("JP모건", 2), "ORCL": ("오라클", 2),
    "GS": ("골드만삭스", 1), "BAC": ("뱅크오브아메리카", 1), "WFC": ("웰스파고", 1), "C": ("씨티그룹", 1), "MS": ("모건스탠리", 1),
    "JNJ": ("존슨앤드존슨", 1), "UNH": ("유나이티드헬스", 1), "LLY": ("일라이 릴리", 1), "ABBV": ("애브비", 1), "NVO": ("노보 노디스크", 1),
    "PFE": ("화이자", 1), "MRK": ("머크", 1), "V": ("비자", 1), "MA": ("마스터카드", 1), "XOM": ("엑슨모빌", 1), "CVX": ("셰브론", 1),
    "KO": ("코카콜라", 1), "PEP": ("펩시코", 1), "PG": ("P&G", 1), "WMT": ("월마트", 1), "COST": ("코스트코", 1), "HD": ("홈디포", 1),
    "MCD": ("맥도날드", 1), "NKE": ("나이키", 1), "DIS": ("디즈니", 1), "SBUX": ("스타벅스", 1), "UBER": ("우버", 1),
    "BA": ("보잉", 1), "CAT": ("캐터필러", 1), "GE": ("GE 에어로스페이스", 1), "GEV": ("GE 버노바", 1), "LMT": ("록히드마틴", 1), "RTX": ("RTX", 1),
    "IBM": ("IBM", 1), "CRM": ("세일즈포스", 1), "ADBE": ("어도비", 1), "NOW": ("서비스나우", 1), "PLTR": ("팔란티어", 1),
    "ARM": ("ARM", 1), "SMCI": ("슈퍼마이크로", 1), "MRVL": ("마벨", 1), "TXN": ("텍사스 인스트루먼트", 1), "NXPI": ("NXP", 1),
    "ON": ("온세미", 1), "DELL": ("델", 1), "ANET": ("아리스타", 1), "VRT": ("버티브", 1), "CEG": ("컨스텔레이션 에너지", 1),
    "T": ("AT&T", 1), "VZ": ("버라이즌", 1), "COIN": ("코인베이스", 1),
}


def _ensure(db: Session) -> None:
    db.execute(text("create table if not exists market_events (ukey text primary key, ev_date date not null, ev_time varchar(8), "
                    "country varchar(2) not null, kind varchar(12) not null, title text not null, importance smallint not null default 1, "
                    "actual text, consensus text, previous text, note text, source varchar(12), updated_at timestamptz default now())"))
    db.execute(text("create index if not exists market_events_date on market_events (ev_date)"))
    db.execute(text("create table if not exists market_events_dart_seen (rcept_no varchar(20) primary key, seen_at timestamptz default now())"))
    db.commit()


def _put(db: Session, ev: dict) -> None:
    ev = {"ev_time": None, "importance": 1, "actual": None, "consensus": None, "previous": None, "note": None, **ev}
    db.execute(text("insert into market_events (ukey, ev_date, ev_time, country, kind, title, importance, actual, consensus, previous, note, source, updated_at) "
                    "values (:ukey, :ev_date, :ev_time, :country, :kind, :title, :importance, :actual, :consensus, :previous, :note, :source, now()) "
                    "on conflict (ukey) do update set ev_date = excluded.ev_date, ev_time = excluded.ev_time, title = excluded.title, "
                    "importance = excluded.importance, actual = excluded.actual, consensus = excluded.consensus, previous = excluded.previous, "
                    "note = excluded.note, updated_at = now()"), ev)


def _val(s: str | None) -> str | None:
    s = html.unescape(s or "").replace("\xa0", " ").strip()
    return s or None


def _get(url: str, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=20, **kw)
        return r.json() if r.ok else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("일정 조회 실패 %s: %s", url.split("?")[0], type(exc).__name__)
        return None


# ── 경제지표 (Nasdaq) ─────────────────────────────────────────
def _economic(db: Session, start: date, end: date) -> int:
    n = 0
    d = start
    while d <= end:
        j = _get(f"https://api.nasdaq.com/api/calendar/economicevents?date={d + timedelta(days=1)}")
        rows = ((j or {}).get("data") or {}).get("rows") or []
        merged: dict[tuple, dict] = {}
        for r in rows:
            name, country = (r.get("eventName") or "").strip(), r.get("country")
            table = US_EVENTS if country == "United States" else KR_EVENTS if country == "South Korea" else None
            if not table or name not in table:
                continue
            try:
                hh, mm = map(int, (r.get("gmt") or "").split(":"))
            except ValueError:
                continue
            if name == "GDP" and country == "United States" and (hh, mm) != (8, 30):
                continue  # 08:30 이 아닌 미국 GDP 는 엉뚱한 줄 (10/15 02:00 등)
            t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).astimezone(KST)
            title, imp = table[name]
            c = "US" if country == "United States" else "KR"
            k = (c, title, t)
            m = merged.setdefault(k, {"ukey": f"nq:{c}:{t:%Y%m%d}:{title}", "ev_date": t.date(), "ev_time": f"{t:%H:%M}", "country": c,
                                      "kind": "policy" if "금리" in title or "FOMC" in title else "indicator", "title": title,
                                      "importance": imp, "source": "nasdaq", "_a": [], "_c": [], "_p": []})
            m["_a"].append(_val(r.get("actual"))); m["_c"].append(_val(r.get("consensus"))); m["_p"].append(_val(r.get("previous")))
        for m in merged.values():
            for key, src in (("actual", "_a"), ("consensus", "_c"), ("previous", "_p")):
                vals = [v for v in m.pop(src) if v]
                m[key] = " · ".join(vals[:2]) or None
            _put(db, m); n += 1
        d += timedelta(days=1)
        time.sleep(0.25)
    db.commit()
    return n


# ── 미국 실적 (Nasdaq) ────────────────────────────────────────
def _us_earnings(db: Session, start: date, end: date) -> int:
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            j = _get(f"https://api.nasdaq.com/api/calendar/earnings?date={d}")
            for r in ((j or {}).get("data") or {}).get("rows") or []:
                sym = (r.get("symbol") or "").upper()
                if sym not in US_EARNINGS:
                    continue
                name, imp = US_EARNINGS[sym]
                tm = r.get("time") or ""
                after = "after" in tm
                kd = d + timedelta(days=1) if after else d
                _put(db, {"ukey": f"nqe:{sym}:{d:%Y%m}", "ev_date": kd, "ev_time": "새벽" if after else "밤" if "pre" in tm else None,
                          "country": "US", "kind": "earnings", "title": f"{name} 실적", "importance": imp, "source": "nasdaq",
                          "consensus": _val(r.get("epsForecast")), "note": "장 마감 후 발표" if after else "장 시작 전 발표" if "pre" in tm else None})
                n += 1
            time.sleep(0.25)
        d += timedelta(days=1)
    db.commit()
    return n


# ── 한국 실적 (DART IR 안내 · 잠정실적) ───────────────────────
def _dart_doc_text(rcept_no: str) -> str | None:
    """DART 공시 화면에서 본문 글자만. (원문 API 는 주말 점검이 잦아 화면 페이지를 읽는다)"""
    h = {"User-Agent": "Mozilla/5.0"}
    t = None
    for k in range(3):  # DART 화면은 가끔 SSL 오류가 나서 몇 번 다시 시도
        try:
            page = requests.get(f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}", headers=h, timeout=20).text
            m = re.search(r'viewDoc\("(\d+)",\s*"(\d+)"', page)
            if not m:
                return None
            r = requests.get(f"https://dart.fss.or.kr/report/viewer.do?rcpNo={m.group(1)}&dcmNo={m.group(2)}&eleId=0&offset=0&length=0&dtd=HTML",
                             headers=h, timeout=20)
            raw = r.content
            cs = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
            t = raw.decode((cs.group(1).decode() if cs else "euc-kr"), errors="ignore")
            break
        except Exception as exc:  # noqa: BLE001
            if k == 2:
                logger.warning("DART 화면 실패 %s: %s", rcept_no, type(exc).__name__)
                return None
            time.sleep(1.5)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " | ", t)
    return re.sub(r"(\s*\|\s*)+", " | ", html.unescape(t).replace("\xa0", " "))


def _kr_earnings(db: Session, back_days: int = 40) -> int:
    key = ""
    try:
        key = open(os.path.expanduser("~/.dart_key")).read().strip()
    except OSError:
        key = os.getenv("DART_API_KEY", "")
    if not key:
        return 0
    # 대상: 거래대금 20일 평균 10억↑ 종목 전부(매수 신호 후보 범위, 약 1,000개) — 중요도는 시총 순위로 (2026-10-11 '실적 D-n' 꼬리표용으로 넓힘)
    caps = db.execute(text("select stock_code from spot_daily_prices where trading_date > current_date - 30 group by stock_code "
                           "having avg(close_price * volume) >= 1e9 order by avg(close_price * volume) desc")).all()
    cap_rank = {c: i for i, (c,) in enumerate(db.execute(text("select code from stocks where is_active and market_cap is not null order by market_cap desc")).all())}
    rank = {c: cap_rank.get(c, 999) for (c,) in caps}
    seen = set(db.execute(text("select rcept_no from market_events_dart_seen")).scalars().all())
    end, bgn = date.today(), date.today() - timedelta(days=back_days)
    found, prelim_cnt = [], {}
    for cls in ("Y", "K"):
        page = 1
        while True:
            j = _get("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": key, "bgn_de": f"{bgn:%Y%m%d}", "end_de": f"{end:%Y%m%d}",
                                                                          "pblntf_ty": "I", "corp_cls": cls, "page_count": 100, "page_no": page})
            if not j or j.get("status") != "000":
                break
            for r in j.get("list") or []:
                if r.get("stock_code") not in rank:
                    continue
                if "잠정)실적" in r["report_nm"]:
                    prelim_cnt[r["stock_code"]] = prelim_cnt.get(r["stock_code"], 0) + 1
                if ("기업설명회" in r["report_nm"] or "잠정)실적" in r["report_nm"]) and r["rcept_no"] not in seen:
                    found.append(r)
            if page >= int(j.get("total_page") or 1):
                break
            page += 1
            time.sleep(0.2)
    n = 0
    for r in found:
        code, rn = r["stock_code"], r["rcept_no"]
        name = r["corp_name"]
        imp = 2 if rank[code] < 30 else 1 if rank[code] < 200 else 0      # 0 = 캘린더엔 안 보이고 꼬리표에만 (시총 순위 밖 = 999)
        if "잠정)실적" in r["report_nm"]:
            # 매달 내는 판매·매출 잠정치(현대차·기아·카지노 등)는 40일 안에 두 번 이상 나와서 거른다 — 분기 잠정실적만 남김
            d = datetime.strptime(r["rcept_dt"], "%Y%m%d").date()
            if prelim_cnt.get(code, 0) >= 2 or (d.month - 1) % 3 == 2:  # 분기 실적은 분기 끝난 뒤 두 달 안에 나온다
                db.execute(text("insert into market_events_dart_seen (rcept_no) values (:r) on conflict do nothing"), {"r": rn})
                continue
            _put(db, {"ukey": f"dart:{code}:{d:%Y%m%d}", "ev_date": d, "country": "KR", "kind": "earnings", "title": f"{name} 잠정실적",
                      "importance": imp, "source": "dart"})
            n += 1
        else:
            t = _dart_doc_text(rn)
            time.sleep(0.3)
            if t is None:
                continue  # 다음에 다시 시도
            body = t.split("기타 투자판단")[0]
            m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", body)
            q = re.search(r"20\d\d년?\s*(\d)\s*분기", body)
            # 진짜 실적 발표만: 직전 분기 실적 + (컨퍼런스콜·웹캐스트 또는 '실적 발표'). 증권사 행사·1대1 미팅·지난 분기 설명은 뺀다.
            call = re.search(r"conference\s*call|컨퍼런스\s*콜|web\s*cast|웹캐스트|실적\s*발표", body, re.I)
            if m and q and call:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if (d.month - 1) // 3 == int(q.group(1)) % 4 and (d.month - 1) % 3 < 2:
                    tm = re.search(r"\b(\d{1,2}):(\d\d)\b", body[m.end():m.end() + 80])
                    _put(db, {"ukey": f"dart:{code}:{d:%Y%m%d}", "ev_date": d, "ev_time": f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None,
                              "country": "KR", "kind": "earnings", "title": f"{name} 실적발표", "importance": imp, "source": "dart",
                              "note": f"{q.group(1)}분기 실적 설명회"})
                    n += 1
        db.execute(text("insert into market_events_dart_seen (rcept_no) values (:r) on conflict do nothing"), {"r": rn})
    db.commit()
    return n


# ── 규칙으로 아는 일정 ────────────────────────────────────────
def _rules(db: Session, start: date, end: date) -> int:
    import holidays  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    yrs = list(range(start.year, end.year + 1))
    kr = holidays.KR(years=yrs, language="ko")
    try:
        us = holidays.financial_holidays("NYSE", years=yrs)
    except Exception:  # noqa: BLE001
        us = {}
    n = 0

    def prev_trading(d: date) -> date:
        while not is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def next_trading(d: date) -> date:
        while not is_trading_day(d):
            d += timedelta(days=1)
        return d

    d = start
    while d <= end:
        if d.weekday() < 5 and not is_trading_day(d):
            _put(db, {"ukey": f"rule:krhol:{d}", "ev_date": d, "country": "KR", "kind": "holiday", "title": f"국내 휴장 ({kr.get(d) or '휴장일'})",
                      "importance": 2, "source": "rule"}); n += 1
        if d in us and d.weekday() < 5:
            # 미국 장이 쉬는 날 밤 (한국 시각으로는 그날 밤 ~ 다음 날 새벽)
            _put(db, {"ukey": f"rule:ushol:{d}", "ev_date": d, "country": "US", "kind": "holiday", "title": "미국 증시 휴장",
                      "importance": 1, "source": "rule", "note": str(us.get(d) or "")}); n += 1
        d += timedelta(days=1)

    # 옵션 만기: 매달 둘째 목요일 (쉬는 날이면 앞 거래일). 3·6·9·12월은 선물도 같이 만기.
    m = date(start.year, start.month, 1)
    while m <= end:
        first_thu = m + timedelta(days=(3 - m.weekday()) % 7)
        exp = prev_trading(first_thu + timedelta(days=7))
        if start <= exp <= end:
            quad = m.month in (3, 6, 9, 12)
            _put(db, {"ukey": f"rule:expiry:{m:%Y%m}", "ev_date": exp, "ev_time": "15:20", "country": "KR", "kind": "expiry",
                      "title": "선물·옵션 동시 만기" if quad else "옵션 만기", "importance": 2 if quad else 1, "source": "rule",
                      "note": "다음 날 코스피200 정기변경 반영" if m.month in (6, 12) else None}); n += 1
        # 수출입 동향: 1일 월간(산업부, 휴일에도 발표) · 11일·21일 잠정(관세청, 휴일이면 다음 거래일)
        for day, title, imp, shift in ((1, "수출입 동향 (지난달)", 2, False), (11, "수출 잠정 (1~10일)", 1, True), (21, "수출 잠정 (1~20일)", 1, True)):
            dd = date(m.year, m.month, day)
            if shift:
                dd = next_trading(dd)
            if start <= dd <= end:
                _put(db, {"ukey": f"rule:export:{m:%Y%m}:{day}", "ev_date": dd, "ev_time": "09:00", "country": "KR", "kind": "indicator",
                          "title": title, "importance": imp, "source": "rule"}); n += 1
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    db.commit()
    return n


def collect(db: Session, back: int = 7, ahead: int = 45, dart: bool = True) -> str:
    _ensure(db)
    today = datetime.now(KST).date()
    start, end = today - timedelta(days=back), today + timedelta(days=ahead)
    out = [f"지표 {_economic(db, start, end)}", f"미국 실적 {_us_earnings(db, start, end)}", f"규칙 {_rules(db, start, end)}"]
    if dart:
        out.append(f"한국 실적 {_kr_earnings(db)}")
    return "시장 일정 " + " · ".join(out)


def refresh_recent(db: Session) -> str:
    """발표 직후 결과값만 다시 받기 (어제~내일)."""
    _ensure(db)
    today = datetime.now(KST).date()
    return f"시장 일정 결과 갱신 {_economic(db, today - timedelta(days=1), today + timedelta(days=1))}"


def events(db: Session, start: date, end: date) -> list[dict]:
    try:
        _ensure(db)
        rows = db.execute(text("select ev_date, ev_time, country, kind, title, importance, actual, consensus, previous, note from market_events "
                               "where ev_date between :s and :e"), {"s": start, "e": end}).mappings().all()
    except Exception:  # noqa: BLE001
        return []
    order = {"새벽": "05:30", "밤": "20:30", None: "99"}
    rows = sorted(rows, key=lambda r: (r["ev_date"], order.get(r["ev_time"], r["ev_time"]), -r["importance"], r["title"]))
    return [{**dict(r), "ev_date": str(r["ev_date"])} for r in rows]
