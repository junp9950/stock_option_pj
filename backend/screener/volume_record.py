"""대량거래 관심종목: 최근 약 4개월 안에 몇 년 만의 최대 거래대금이 터진 종목과 지금 단계.

신기록일 = 그날 거래대금이 그 종목 데이터 전체(약 3년)에서 최대 + 직전 120일 중간값의 10배 이상 + 양봉 + 전날 대비 +5% 이상 + 30억 이상.
  2026-10-06부터 '윗꼬리' 신기록도 넣는다: 장중 고가가 전날 대비 +5% 이상이었는데 음봉이거나 +5% 아래로 마감한 날
  (대한제강 10/1 시가 +28% → 종가 +12.7%, 거래 120배). 사용자: "설거지든 뭐든 대량 거래는 일단 주시해야지".
  이런 종목은 단계 '설거지'로 보여 주기만 하고, 🎯 진입 신호는 3년 검증한 양봉 신기록에만 붙인다.
2023-09~2026-09 전종목 확인(1,113건): 신기록일 종가에 바로 사면 20일 뒤 중간값 -7.1%(플러스 34%)라 추격 매수 신호가 아니다.
대신 20일 안에 95%가 신기록일 종가보다 높은 가격을 찍어(중간값 +15%) 크게 움직이는 종목을 고르는 '관심 등록' 용도다.
진입은 그 뒤 숨고르기(거래가 마르면서 상승분을 지킴) 후 돌려세울 때 본다. 한양디지텍 9/17, 금호타이어 6~8월이 예.

진입 신호 = 숨고르기 + 오늘 돌려세우는 봉(+3% 양봉, 거래대금 20일 평균 2배) + 시장 상승·횡보. 3년 확인(종목마다 처음 맞은 날 종가):
  숨고르기 첫날 644건 40일 시장 대비 -5.1%p / 돌려세우는 봉 하락장 116건 -5.8%p / 돌려세우는 봉 + 상승·횡보장 250건 +1.9%p
  / 여기에 실적 개선(영업이익 +30%, 매출 +10%, 120일 안 공시) 31건 +7.8%p (사례 적음, 실적 데이터 2024-04부터).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

WINDOW = 80          # 신기록일을 찾는 기간 (거래일, 약 4개월)
PRE_MED_DAYS = 120   # '평소' 거래대금 = 직전 120거래일 중간값
MIN_HISTORY = 250    # 그 전 데이터가 최소 1년은 있어야 '몇 년 만'이라고 본다
X_MIN = 10           # 평소의 10배 이상
MIN_VALUE = 3e9      # 신기록일 거래대금 30억 이상
MIN_EVENT_CHG = 5.0  # 신기록일 전날 종가 대비 +5% 이상 (우리금융지주 10/1처럼 갭하락 뒤 대량 매도, 포스코인터 9/3처럼
                     # 주가는 안 움직인 대량 체결(블록딜·지수 편입 등)은 시세가 아니라 뺀다)
TAIL_MIN_HIGH = 8.0  # 윗꼬리 신기록은 장중 고가가 전날 대비 +8% 이상일 때만. 포스코인터내셔널 9/3(블록딜, 고가 +5.8%·종가 +4.3%)을
                     # 사용자와 확인해 빼기로 했다 (2026-10-06 "블록딜 있었잖아"). 블록딜은 주가가 거의 안 움직인다.
# 뉴스로 확인한 블록딜(시간외 대량매매) 날 — 시세가 아니라 지분 매각이라 신기록에서 뺀다 (2026-10-06 웹 검색 확인)
BLOCK_DEALS = {
    ("047050", "2026-09-03"),   # 포스코인터내셔널 (사용자 확인)
    ("058470", "2026-06-12"),   # 리노공업 최대주주 700만주 시간외매매, 주당 9만원 (한국경제 2026-06-15)
}
NEW_DAYS = 10        # 마지막 대량거래일 뒤 10거래일까지는 '신규'
DRY_MAX = 0.25       # 최근 5일 거래대금이 대량거래 최대일의 25% 이하면 말랐다고 본다
# 무너짐 = 지금 종가가 기준선(신기록 전날 종가) 아래이거나, 신기록 뒤 한 번이라도 기준선의 -15% 아래로 마감한 경우.
# 7/30 같은 폭락에서 버틴 종목(금호타이어)은 남고 크게 깬 종목(제주반도체 -56%)은 빠진다. 날짜로 자르지 않는 이유.
# 거래 없이 잠깐 기준선 밑으로 흔든 것(티에스이 9/15 -10% 뒤 회복)은 털기로 보고 봐준다.
BREAK_DEPTH = 0.85
# 설거지 = 신기록 다음 1~2일 안에 거래량이 신기록일보다 많은 음봉 + 윗꼬리가 하루 폭의 절반 이상.
# 3년 확인(5일간 기준선 지킨 종목끼리): 설거지 봉 7건은 20일 뒤 중간값 -12.4%(플러스 14%), 보통 356건은 -2.9%(42%).
# 기준선을 지킨 비율은 둘 다 86~87%라, 설거지 뒤 저점을 지키는 건 강함이 아니라 방치였다.
DIST_UPPER = 0.5
NAME_SKIP = ("리츠", "스팩", "ETF", "ETN")   # 배당·구조상 가격이 받쳐지는 상품 (신한서부티엔디리츠 6/10)
# (예전엔 '상승분 절반 유지'를 조건으로 써서, 깃대가 짧은 티에스이가 거래 없이 8%만 밀려도 무너짐이 됐다)


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": []}
    days = [d for (d,) in db.execute(text(
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by trading_date desc limit :n"),
        {"d": latest, "n": WINDOW + PRE_MED_DAYS + 1})][::-1]
    win_start, load_start = days[-WINDOW], days[0]

    # 기간 시작 전까지의 종목별 최대 거래대금과 데이터 일수 (전체 3년치를 내려받지 않으려고 DB에서 집계)
    prior = {code: (float(mx or 0), int(n)) for code, mx, n in db.execute(text(
        "select stock_code, max(trading_value), count(*) from spot_daily_prices where trading_date < :w group by stock_code"),
        {"w": load_start})}
    by: dict[str, list] = defaultdict(list)
    for r in db.execute(text(
        "select stock_code, trading_date, open_price, high_price, low_price, close_price, trading_value, volume "
        "from spot_daily_prices where trading_date >= :s order by stock_code, trading_date"), {"s": load_start}):
        by[r[0]].append(r)
    # 진입 신호용: 오늘 시장 국면, 실적 개선 종목 (실적 개선 탭 스냅샷)
    from backend.screener.market_regime import current_regime  # noqa: PLC0415
    from backend.services.earnings_screen import read_snapshot  # noqa: PLC0415
    regime = current_regime(db) or {}
    market_ok = regime.get("state") in ("상승", "횡보")
    snap = read_snapshot()
    earn_up = set(snap.get("up_codes") or [r["code"] for r in snap.get("rows", [])])
    names, caps = {}, {}
    for code, name, cap, shares in db.execute(text("select code, name, market_cap, shares_outstanding from stocks")):
        names[code] = name
        caps[code] = (float(cap or 0), float(shares or 0))
    from backend.services.marcap_caps import caps as marcap_caps  # noqa: PLC0415
    marcap = marcap_caps()   # stocks에 시총이 없는 종목(유니버스 밖)을 채운다

    items, limit_up = [], []
    for code, pl in by.items():
        if pl[-1][1] != latest or any(k in names.get(code, "") for k in NAME_SKIP):
            continue
        run_max, n_prior = prior.get(code, (0.0, 0))
        tv = [float(p[6] or 0) for p in pl]
        # 오늘 거래대금 신기록 + 상한가 (종베 후보): 3년 치 신기록일 상한가 247건, 종가 매수 → 다음 날 시가 평균 +5.6%·수익 74%.
        # 단 상한가에 묶이면 종가·시간외에 실제로 못 사는 경우가 많아 숫자보다 나쁠 수 있다.
        if n_prior + len(pl) > MIN_HISTORY and len(pl) > PRE_MED_DAYS:
            o_, h_, l_, c_ = (float(x) for x in pl[-1][2:6])
            prev_c = float(pl[-2][5])
            med_ = statistics.median(tv[-PRE_MED_DAYS - 1:-1]) or 1
            if (prev_c > 0 and c_ >= prev_c * 1.295 and tv[-1] > max(run_max, max(tv[:-1])) and tv[-1] >= X_MIN * med_
                    and tv[-1] >= MIN_VALUE):
                cap0, sh0 = caps.get(code, (0.0, 0.0))
                limit_up.append({"code": code, "name": names.get(code, code), "close_price": round(c_),
                                 "change_pct": round((c_ / prev_c - 1) * 100, 1), "value": round(tv[-1]), "x": round(tv[-1] / med_),
                                 "locked": h_ == l_,   # 점상한가: 하루 종일 상한가에 묶임 → 사기 매우 어려움
                                 "market_cap": cap0 or sh0 * c_ or marcap.get(code) or 0})
        vol = [float(p[7] or 0) for p in pl]
        first = last_big = None
        big_max = 0.0
        for i, p in enumerate(pl):
            if p[1] >= win_start and n_prior + i >= MIN_HISTORY and i >= PRE_MED_DAYS // 2:
                med = statistics.median(tv[max(0, i - PRE_MED_DAYS):i]) or 1
                if tv[i] >= X_MIN * med and (code, p[1].isoformat()) not in BLOCK_DEALS:
                    last_big = i
                    big_max = max(big_max, tv[i])
                    pc = float(pl[i - 1][5])
                    if first is None and tv[i] > run_max and tv[i] >= MIN_VALUE:
                        if p[5] > p[2] and float(p[5]) >= pc * (1 + MIN_EVENT_CHG / 100):
                            first = (i, tv[i] / med, "양봉")
                        elif float(p[3]) >= pc * (1 + TAIL_MIN_HIGH / 100):
                            first = (i, tv[i] / med, "윗꼬리")   # 장중 크게 쐈다가 밀림 (갭하락·블록딜은 여전히 뺌)
            run_max = max(run_max, tv[i])
        if first is None:
            continue
        i, x, kind = first
        ev = pl[i]
        base = float(pl[i - 1][5])                      # 신기록 전날 종가
        i_peak = max(range(i, len(pl)), key=lambda k: pl[k][3])
        peak, close = float(pl[i_peak][3]), float(pl[-1][5])
        kept = (close - base) / (peak - base) if peak > base else 0.0
        dry = (sum(tv[-5:]) / 5) / big_max if big_max else 1.0
        rest = len(pl) - 1 - last_big
        broke = close < base or any(float(p[5]) < base * BREAK_DEPTH for p in pl[i + 1:])
        dist = False
        for k in (i + 1, i + 2):
            if k < len(pl):
                o_, h_, l_, c_ = (float(x) for x in pl[k][2:6])
                rng = h_ - l_
                if (vol[k] > vol[i] and c_ < o_ and rng > 0 and (h_ - max(o_, c_)) / rng >= DIST_UPPER):
                    dist = True
        # 오늘 돌려세우는 봉: +3% 이상 양봉 + 거래대금이 직전 20일 평균의 2배 이상
        avg20 = sum(tv[-21:-1]) / 20 if len(tv) > 21 else 0
        turn = (float(pl[-1][5]) > float(pl[-1][2]) and close >= float(pl[-2][5]) * 1.03 and avg20 > 0 and tv[-1] >= 2 * avg20)
        if kind == "윗꼬리" and not broke and close >= float(ev[3]):
            stage = "꼬리 돌파"      # 신기록일 윗꼬리 끝(고가)을 종가로 넘음 = 그날 물린 사람 0
        elif broke:
            stage = "무너짐"         # 기준선(신기록 전날 종가)을 깼으면 설거지였든 아니든 무너짐 — 2026-10-07 SK스퀘어·동원개발(고점 -43~-48%)이 '위에서 팔림'으로 계속 보였음
        elif dist or kind == "윗꼬리":
            stage = "설거지"
        elif rest < NEW_DAYS:
            stage = "신규"
        elif dry <= DRY_MAX:
            stage = "숨고르기"
        else:
            stage = "진행 중"
        items.append({
            "code": code, "name": names.get(code, code),
            "event_date": ev[1].isoformat(), "event_change_pct": round((float(ev[5]) / base - 1) * 100, 1),
            "event_value": round(tv[i]), "event_x": round(x), "event_kind": kind,
            "event_high_pct": round((float(ev[3]) / base - 1) * 100, 1),
            "peak_date": pl[i_peak][1].isoformat(), "rise_pct": round((peak / base - 1) * 100, 1),
            "close_price": round(close),
            "gap20_pct": round((close / (sum(float(p[5]) for p in pl[-20:]) / 20) - 1) * 100, 1),
            "market_cap": caps.get(code, (0, 0))[0] or caps.get(code, (0, 0))[1] * close or marcap.get(code) or 0, "change_pct": round((close / float(pl[-2][5]) - 1) * 100, 2),
            "off_peak_pct": round((close / peak - 1) * 100, 1), "kept_pct": round(kept * 100),
            "dry_pct": round(dry * 100), "rest_days": rest, "days_since": len(pl) - 1 - i,
            "stage": stage, "stop_price": round(base), "stop_gap_pct": round((base / close - 1) * 100, 1),
            "turn_today": turn, "earn_up": code in earn_up,
            "entry_signal": stage == "숨고르기" and turn and market_ok and kind == "양봉",
        })
    # 섹터 (16개) — 화면에서 어느 섹터 종목인지 보이게
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam_of: dict[str, list[str]] = {}
    for f, mem in family_members(db).items():
        for c in mem:
            fam_of.setdefault(c, []).append(f)
    for x in items:
        x["families"] = fam_of.get(x["code"], [])[:2]
    # 투자주의·경고·위험·단기과열·관리종목·신용불가 (KIS) — 무너짐 빼고 화면에 보이는 종목만
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    fl = flags_get([x["code"] for x in items if x["stage"] != "무너짐"])
    for x in items:
        x["flags"] = fl.get(x["code"], {}).get("flags", [])
    # 신기록 뒤 경과일로 자르지 않는 이유 (2026-10-04, 진입 신호 130건 40일 시장 대비): 61~80일 뒤 신호 43건 평균 +9.6%p·중간 +2.4%p로
    # 21~40일(48건 +4.0%p)보다 나빴던 게 아니다. 대신 화면에 '며칠 전 신기록'을 크게 보여 준다.
    # 이번 상승 구간(7/30 바닥) 이후 신기록만 — 하락장 때 터진 거래는 지금 흐름과 상관없음 (사용자 2026-10-07)
    from backend.screener.my_pattern import CYCLE_START  # noqa: PLC0415
    items = [x for x in items if x["event_date"] >= CYCLE_START]
    if win_start.isoformat() < CYCLE_START:
        win_start = date.fromisoformat(CYCLE_START)
    order = {"꼬리 돌파": 0, "숨고르기": 1, "신규": 2, "진행 중": 3, "설거지": 4, "무너짐": 5}
    items.sort(key=lambda x: x["market_cap"] or 0, reverse=True)   # 단계 안에서는 시총 큰 종목부터
    items.sort(key=lambda x: (order[x["stage"]], not x["entry_signal"]))
    limit_up.sort(key=lambda x: -(x["market_cap"] or 0))
    return {"trading_date": latest.isoformat(), "window_start": win_start.isoformat(), "market_state": regime.get("state"),
            "limit_up": limit_up, "items": items}
