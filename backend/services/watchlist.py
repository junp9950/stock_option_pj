"""사용자 관심 종목 장 마감 점검 (2026-10-05 "그 종목들 확인해서 3시 40분에 알림 보내라").

사용자가 차트 보고 적어 둔 관심 목록(기준가·조건)을 장 마감 뒤 15:40에 토스 일봉으로 점검해 텔레그램으로 보낸다.
조건 종류: above = 종가가 기준가 위로 마감(돌파·돌려놓기), near = 종가가 기준가 ±3% 안(수렴 확인),
hold = 종가가 기준가를 지킴(아래면 이탈), watch = 기준가 없이 봉 모양·거래만 본다.
목록은 settings 'user_watchlist'에 저장 — 처음엔 SEED로 채운다.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.utils.logger import get_logger

logger = get_logger(__name__)
KEY, CHAT_KEY = "user_watchlist", "user_watchlist_chats"

# (이름, 조건, 기준가, 사용자 메모) — 2026-10-05 대화의 관심 목록, 신용불가 표시 종목은 뺌, 두에빌·코윈로보틱스는 종목 DB에 없어 뺌
SEED = [
    ("비츠로테크", "above", 11440, "뚫고 마감하면 종베"),
    ("PS일렉트로닉스", "above", 9420, "위 마감 시 11,160까지 박스 열림"),
    ("가온전선", "above", 352860, "5월 꼬리 = 물린 사람 0"),
    ("한국알콜", "above", 16420, "상승삼각형, 9/28 꼬리"),
    ("지역난방공사", "above", 80400, "8일 수렴, 80,000 세 번 막힘"),
    ("컴투스", "above", 41000, "8/27 꼬리"),
    ("금호타이어", "above", 6900, "6,900 위로 돌려놓는지"),
    ("다산네트웍스", "above", 3500, "3,500 저항대"),
    ("전진건설로봇", "near", 38750, "거래 거의 마름, 수렴"),
    ("농심", "near", 387000, "수렴·지지"),
    ("성광벤드", "near", 30300, "마르면서 수렴하면 베스트"),
    ("코스맥스", "near", 260000, "기간 조정, 26만 근처 수렴"),
    ("SK가스", "near", 236500, "수렴"),
    ("SNT에너지", "near", 35750, "수렴"),
    ("셀바스AI", "near", 8620, "수렴, 도지라 쏠 수도"),
    ("한선엔지니어링", "near", 13700, "눌러주는 봉 두 번이면 베팅"),
    ("현대바이오랜드", "hold", 4930, "저점, 수렴 자리 찾기"),
    ("하나금융지주", "hold", 127000, "상승 추세선(대략)"),
    ("코리안리", "hold", 14300, "상승 추세선(대략), 10/2 꼬리 이탈"),
    ("JW중외제약", "watch", 0, "수렴"),
    ("SK이터닉스", "watch", 0, "거래 마르며 수렴"),
    ("롯데렌탈", "watch", 0, "신고가 날 종가 주차"),
    ("KBI메탈", "watch", 0, "장대양봉 자리 주차"),
    ("대원전선", "watch", 0, "수렴"),
    ("펌텍코리아", "watch", 0, "수렴"),
    ("한국비엔씨", "watch", 0, "수렴"),
    ("한국쉘석유", "watch", 0, "수렴"),
    ("S-Oil", "watch", 0, "수렴"),
    ("LG전자", "watch", 0, "거래 더 마르며 수렴"),
    ("SK아이이테크놀로지", "watch", 0, "수렴"),
    ("SFA", "watch", 0, "수렴·조정, 안 나오면 보내기"),
    ("티에스이", "watch", 0, "신고가 도전, 수렴 확인"),
    ("LS에코에너지", "watch", 0, "눌러주는지"),
    ("롯데에너지머티리얼즈", "watch", 0, "거래 붙음, 눌림 확인"),
    ("대주전자재료", "watch", 0, "거래 붙음, 눌림 확인"),
    ("한온시스템", "watch", 0, "돌려세우는 양봉 3연속"),
    ("에스앤에스텍", "watch", 0, "도지"),
    ("나무가", "watch", 0, "저점 수렴 뒤 도지 종가 확인"),
    ("일신방직", "watch", 0, "손바뀜, 거래 안 빠짐"),
    ("한국정보인증", "watch", 0, "보안주 오를 때 안 오르면"),
    ("한미약품", "watch", 0, "거래 뒤 수렴"),
    ("한국콜마", "watch", 0, "지지하다 장대음봉"),
    ("POSCO홀딩스", "watch", 0, "거래 약함, 마르는 중"),
    ("티엠씨", "watch", 0, "상한가, 신용 풀림"),
]


def _items(db: Session) -> list[dict]:
    from backend.services.telegram import _find, _get, _put  # noqa: PLC0415
    items = _get(db, KEY, None)
    if items is None:
        items = []
        for name, kind, level, note in SEED:
            row = _find(db, name)
            if not row:
                logger.warning("관심 목록: 종목 못 찾음 %s", name)
                continue
            items.append({"code": row.code, "name": row.name, "kind": kind, "level": level, "note": note})
        _put(db, KEY, items)
    return items


def box_info(highs: list[float], lows: list[float], close: float, max_width: float = 0.08) -> dict:
    """최근 며칠이 좁은 박스(고가·저가 폭 8% 안)였나 — 손절 짧은 자리 판단용 (2026-10-06 SK가스: 13일 폭 5%, 손절 -2%).
    오늘 봉은 빼고 센다(오늘 뚫었으면 박스 밖이라서)."""
    hs, ls = highs[:-1], lows[:-1]
    k, hi, lo = 0, 0.0, 0.0
    for n in range(2, min(len(hs), 40) + 1):
        h_, l_ = max(hs[-n:]), min(ls[-n:])
        if l_ <= 0 or h_ / l_ - 1 > max_width:
            break
        k, hi, lo = n, h_, l_
    if k < 5:
        return {"box_days": 0}
    stop = lo * 0.995
    return {"box_days": k, "box_width": round((hi / lo - 1) * 100, 1), "box_low": round(lo), "box_high": round(hi),
            "stop_pct": round((stop / close - 1) * 100, 1) if close else None}


def box_text(b: dict) -> str:
    if not b.get("box_days"):
        return ""
    return f" · {b['box_days']}일 수렴 폭 {b['box_width']}% · 손절 {b['box_low']:,} ({b['stop_pct']:+.1f}%)"


def _shape(c: list[dict]) -> dict | None:
    """토스 일봉(오래된→최신) 25개로 오늘 봉 요약."""
    try:
        o, h, l, cl, v = (float(c[-1][k]) for k in ("openPrice", "highPrice", "lowPrice", "closePrice", "volume"))
        pc = float(c[-2]["closePrice"])
        vols = [float(x["volume"]) for x in c[-21:-1]]
        closes = [float(x["closePrice"]) for x in c[-10:]]
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    avg = sum(vols) / len(vols) if vols else 0
    rng = h - l
    tags = []
    chg = (cl / pc - 1) * 100 if pc else 0
    vx = v / avg if avg else 0
    if rng > 0 and abs(cl - o) / o <= 0.01 and abs(cl - o) / rng <= 0.35:   # 몸통 1% 이하·변동폭의 35% 이하 (작은 도지도 포함)
        tags.append("🕯밑꼬리 도지" if (min(o, cl) - l) / rng >= 0.5 else "🕯도지")
    # 거래 터진 꽉 찬 음봉 (사용자 원칙 2026-10-07 "진짜 위험") — fullbear.py: 오르던 종목이면 5일 -1.5%·20일 안 -10% 58%, 약하던 종목은 오히려 반등
    full_bear = rng > 0 and chg <= -4 and (o - cl) / rng >= 0.8 and (cl - l) / rng <= 0.1 and vx >= 2
    try:
        r20 = (float(c[-2]["closePrice"]) / float(c[-22]["closePrice"]) - 1) * 100 if len(c) >= 22 else None
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        r20 = None
    if full_bear:
        tags.append("⚠꽉찬음봉")
    if chg >= 5 and vx >= 2:
        tags.append("🔥장대양봉")
    elif chg <= -5 and vx >= 2:
        tags.append("⚠장대음봉")
    if vx and vx <= 0.5:
        tags.append("거래 마름")
    bx = box_info([float(x["highPrice"]) for x in c], [float(x["lowPrice"]) for x in c], cl)
    return {**bx, "date": c[-1]["timestamp"][:10], "close": cl, "chg": chg, "vx": vx, "open": o, "low": l, "high": h,
            "width": (max(closes) / min(closes) - 1) * 100 if closes else 0, "tags": tags, "r20": r20}


def _when() -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return "마감" if (now.hour, now.minute) >= (15, 30) or now.weekday() >= 5 else f"장중 {now:%H:%M} (봉 모양 확정 전)"


def _won(x: float) -> str:
    return f"{x:,.0f}"


def _full_bear_line(nm: str, s: dict) -> str:
    r20 = s.get("r20")
    if r20 is not None and r20 >= 15:
        how = "오르던 종목 → <b>정리 검토</b> (3년: 5일 -1.5%, 20일 안 -10% 58%)"
    elif r20 is not None and r20 < 0:
        how = "약하던 종목 → 투매일 수 있음, 내일 저가 지키는지 확인 (3년: 5일 +2.3%)"
    else:
        how = "내일 저가 깨면 정리"
    return f"{nm} {s['chg']:+.1f}% · <b>거래 {s['vx']:.1f}배 꽉 찬 음봉</b> (밑꼬리 없음)\n   └ {how}"


def _held(db: Session) -> list[tuple[str, str]]:
    """매매 일지(owner junp) 기준 지금 들고 있는 종목."""
    from sqlalchemy import text  # noqa: PLC0415
    try:
        return [(c, n) for c, n in db.execute(text(
            "select code, max(name) from trade_executions where owner = 'junp' "
            "group by code having sum(case when side = '매수' then qty else -qty end) > 0")).all()]
    except Exception:  # noqa: BLE001
        return []


def report(db: Session, force: bool = False) -> str | None:
    """텔레그램 HTML. 할 일 있는 종목만 한 줄씩 굵게, 조용한 종목은 이름만 묶는다 (2026-10-05 "가독성이 너무 안 좋노")."""
    from html import escape  # noqa: PLC0415
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    g = {k: [] for k in ("brk", "fire", "close", "candle", "warn", "dry", "far")}
    last_date = ""
    skip = {c for c, _ in _held(db)}     # 보유 종목은 보유 종목 점검 메시지에서 따로 본다 (2026-10-08)
    for it in _items(db):
        if it["code"] in skip:
            continue
        s = _day(it["code"], fetch_candles)
        if not s:
            continue
        last_date = max(last_date, s["date"])
        lv, p, nm = it["level"], s["close"], f"<b>{escape(it['name'])}</b>"
        pct = f"{s['chg']:+.1f}%"
        candle = next((t for t in s["tags"] if "도지" in t), "")
        if "⚠꽉찬음봉" in s["tags"]:
            g["warn"].append(_full_bear_line(nm, s))
        elif "🔥장대양봉" in s["tags"]:
            g["fire"].append(f"{nm} {pct} · 거래 {s['vx']:.0f}배" + (f" · {_won(lv)} 위 마감 ✅" if it["kind"] == "above" and p >= lv else ""))
        elif it["kind"] == "above" and p >= lv:
            g["brk"].append(f"{nm} {_won(p)} ({pct}) · {_won(lv)} 위 마감 · 거래 {s['vx']:.1f}배" + (f"\n   └ <i>{escape(it['note'])}</i>" if it.get("note") else ""))
        elif "⚠장대음봉" in s["tags"] or (it["kind"] == "hold" and p < lv):
            g["warn"].append(f"{nm} {pct}" + (f" · {_won(lv)} 이탈" if it["kind"] == "hold" and p < lv else " · 장대음봉"))
        elif it["kind"] == "above" and p >= lv * 0.97:
            g["close"].append(f"{nm} {_won(p)} → {_won(lv)}  <i>{(lv / p - 1) * 100:.1f}% 남음</i>")
        elif it["kind"] == "near" and p > lv * 1.03 and s["chg"] >= 3 and s["vx"] >= 1.5:
            # 수렴 자리에서 거래 붙은 양봉으로 위로 뚫고 나감 — 근처(±3%) 조건만 보다가 놓쳤다 (2026-10-06 SK가스 +7.7%·거래대금 4배)
            g["brk"].append(f"{nm} {_won(p)} ({pct}) · 수렴 자리({_won(lv)}) 위로 돌파 · 거래 {s['vx']:.1f}배" + (f"\n   └ <i>{escape(it['note'])}</i>" if it.get("note") else ""))
        elif it["kind"] == "near" and abs(p / lv - 1) <= 0.03:
            g["close"].append(f"{nm} {_won(p)} · 기준 {_won(lv)} 근처 ({(p / lv - 1) * 100:+.1f}%)" + box_text(s))
        elif candle:
            g["candle"].append(f"{nm} {candle.replace('🕯', '')} ({pct})")
        elif "거래 마름" in s["tags"]:
            g["dry"].append(escape(it["name"]))
        else:
            far = f"(선까지 {(lv / p - 1) * 100:.0f}%)" if it["kind"] == "above" else ""
            g["far"].append(escape(it["name"]) + far)
    if not force and last_date != today:
        return None     # 휴장일
    d = last_date[5:].replace("-", "/")
    out = [f"📋 <b>관심 종목 {d} {_when()}</b>"]
    blocks = (("✅ 매수 조건: 선 위 마감 → 종가 매수 검토", "brk"), ("🔥 거래 실린 장대양봉", "fire"), ("👀 선 코앞 (3% 안)", "close"),
              ("🕯 도지", "candle"), ("⚠ 이탈·장대음봉·꽉 찬 음봉", "warn"))
    for title, k in blocks:
        if g[k]:
            out.append(f"\n{title}")
            out += g[k]
    if g["dry"]:
        out.append(f"\n💤 거래 마름 (수렴 중)\n{', '.join(g['dry'])}")
    if g["far"]:
        out.append(f"\n· 변화 없음\n<i>{', '.join(g['far'])}</i>")
    if not any(g[k] for _, k in blocks):
        out.insert(1, "\n오늘은 조건에 닿은 종목이 없습니다.")
    return "\n".join(out)


def _positions(db: Session) -> list[dict]:
    """매매 일지로 지금 보유 수량·평단(이동평균) — 판 만큼 수량만 줄인다."""
    from sqlalchemy import text  # noqa: PLC0415
    pos: dict[str, dict] = {}
    for code, name, side, qty, price in db.execute(text(
            "select code, name, side, qty, price from trade_executions where owner = 'junp' order by trade_date, seq, id")).all():
        p = pos.setdefault(code, {"code": code, "name": name, "qty": 0, "avg": 0.0})
        if side == "매수":
            tot = p["qty"] + qty
            p["avg"] = (p["avg"] * p["qty"] + float(price) * qty) / tot if tot > 0 else 0.0
            p["qty"] = tot
        else:
            p["qty"] -= qty
    return [p for p in pos.values() if p["qty"] > 0]


def _plan(db: Session, code: str, wl: dict, posts: dict) -> dict:
    """보유 종목의 손절선·메모: 관심 목록 hold 줄 → 정리 글 메모 순."""
    w = wl.get(code)
    if w and w.get("kind") == "hold" and w.get("level"):
        return {"stop": float(w["level"]), "note": w.get("note", "")}
    it = posts.get(code)
    if it and it.get("kind") == "hold" and it.get("level"):
        return {"stop": float(it["level"]), "note": it.get("memo", "").replace(chr(10), " ")}
    return {"stop": 0.0, "note": (w or {}).get("note", "") or (it or {}).get("memo", "").replace(chr(10), " ")}


# 장기 보유(보통 계좌 · 안 파는 종목)는 보유 종목 점검에서 뺀다 — 사용자 2026-10-08 "삼전우 하닉 하나금융지주 이런 거는 빼고".
# settings 'held_exclude'(코드 목록)로 바꿀 수 있다.
HELD_EXCLUDE = ["005935", "000660", "086790", "012330", "0080Y0"]


def held_report(db: Session, force: bool = False) -> str | None:
    """(아이콘은 색이 아니라 모양으로 구분 — 사용자 노랑·초록 색약, 2026-10-08)
    보유 종목 장 마감 점검 — 종목마다 3줄: 이름·종가 / 손절선까지 / 수익·봉·거래. 손절에 가까운 순. 금액은 안 적는다 (%만)."""
    from html import escape  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    skip = set(_get(db, "held_exclude", None) or HELD_EXCLUDE)
    pos = [p for p in _positions(db) if p["code"] not in skip]
    if not pos:
        return None
    wl = {x["code"]: x for x in _items(db)}
    try:
        posts = post_items(db)
    except Exception:  # noqa: BLE001
        posts = {}
    rows = []
    last_date = ""
    for p in pos:
        s = _day(p["code"], fetch_candles)
        if not s:
            continue
        last_date = max(last_date, s["date"])
        c = s["close"]
        stop = _plan(db, p["code"], wl, posts)["stop"]
        gain = (c * 0.998 / p["avg"] - 1) * 100 if p["avg"] else 0.0     # 증권사 앱처럼 팔 때 세금·수수료 0.2% 뺀 수익률
        room = (c / stop - 1) * 100 if stop else None          # 손절선까지 남은 여유 (+면 위)
        risk = "⚠꽉찬음봉" in s["tags"] or "⚠장대음봉" in s["tags"]
        if stop and c < stop:
            icon, line2 = "⛔", f"손절 {_won(stop)} <b>아래 마감 → 정리</b>"
        elif risk or (room is not None and room <= 2):
            icon, line2 = "⚠️", f"손절 {_won(stop)} · <b>{room:.1f}% 남음</b>" if stop else "손절선 없음"
        else:
            icon, line2 = "✅", f"손절 {_won(stop)} · {room:.1f}% 남음" if stop else "손절선 없음"
        if gain >= 5 and stop and stop < p["avg"]:
            line2 += f"\n   ↑ 로스컷 본전({_won(p['avg'])}) 위로 올리기"
        tag = " · <b>거래 터진 꽉 찬 음봉</b>" if "⚠꽉찬음봉" in s["tags"] else (" · <b>장대음봉</b>" if "⚠장대음봉" in s["tags"] else "")
        line3 = f"평단 {_won(p['avg'])} · 수익 <b>{gain:+.1f}%</b> · {_candle_word(s)} · 거래 {s['vx']:.1f}배{tag}"
        rows.append(((room if room is not None else 99), f"{icon} <b>{escape(p['name'])}</b>  {_won(c)} · 오늘 {s['chg']:+.1f}%\n   {line2}\n   {line3}"))
    if not force and last_date != datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat():
        return None
    rows.sort(key=lambda x: x[0])
    n_out = sum(r[1].startswith("⛔") for r in rows)
    n_near = sum(r[1].startswith("⚠️") for r in rows)
    head = f"💼 <b>보유 종목 {last_date[5:].replace('-', '/')} {_when()}</b>"
    summ = f"{len(rows)}종목 · ⛔ 손절 {n_out} · ⚠️ 2% 안 {n_near} · ✅ 여유 {len(rows) - n_out - n_near}"
    return "\n\n".join([head + "\n" + summ] + [r[1] for r in rows])


def send_report(db: Session, force: bool = False, chat_id: str | None = None) -> None:
    from backend.services.telegram import _get, _put, send  # noqa: PLC0415
    _CANDLES.clear()
    msg = report(db, force=force)
    msg2 = held_report(db, force=force)    # 정리 글 체크 대신 보유 종목 기준 (2026-10-08 "장 마감 후에 오는 거 내 보유 종목 기준으로")
    if not msg and not msg2:
        return
    chats = [chat_id] if chat_id else _get(db, CHAT_KEY, None)
    if chats is None:       # 처음 실행 때 등록된 대화방(사용자 본인)으로 고정
        chats = list(_get(db, "telegram_chats", {}).keys())
        _put(db, CHAT_KEY, chats)
    for c in chats:
        if msg:
            send(db, msg, c, html=True)
        if msg2:
            send(db, msg2, c, html=True)



# ── 정리 글 조건 체크 (2026-10-05 "내가 종목토론방에 정리로 적어 놓은 것들 분석해서 담날 체크") ──────
# 사용자가 종목토론에 "1. 종목명 / 메모" 꼴로 올린 정리 글을 종목별로 나누고, 메모에서 가격선·조건(뚫으면·터치·안 밀리면·도지 뜨면)을 읽어
# 장 마감 뒤 그 조건이 맞았는지 본다. 같은 종목이 여러 글에 있으면 최신 글 메모를 쓴다.
_CANDLES: dict = {}
ALIAS = {"포홀": "POSCO홀딩스", "롯에머": "롯데에너지머티리얼즈", "S-oil": "S-Oil", "s-oil": "S-Oil", "에스오일": "S-Oil", "PS일렉": "PS일렉트로닉스"}
_HEAD = re.compile(r"(?m)^\s*(\d{1,2})\s*[.)]\s*(.+?)\s*$")
_NUM = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*(만\s*원|만원|원)?|(\d{1,3})\s*만\s*원?\s*(초반|중반|후반)?")
_KW = [("above", r"뚫|돌파|위\s*마감|넘|올려|위로|올리"), ("hold", r"안\s*밀|지키|지켜|지지|이탈|밀리"), ("near", r"터치|근처|수렴|붙|비비|오면|닿")]
_DOJI_ENTRY = re.compile(r"도지[^.\n]{0,10}?(뜨면|나오면|주면|나올까|뜰까)|도지\s*캔들에서\s*진입|도지에서\s*진입")


def _day(code: str, fetch) -> dict | None:
    if code not in _CANDLES:
        c = None
        for wait in (0.15, 1.0, 2.5):     # 토스 429(요청 과다) 나면 잠깐 쉬고 다시
            c = fetch(code, "1d", 25)
            time.sleep(wait)
            if c:
                break
        if c and len(c) >= 3:
            c = _krx_patch(code, c)
        _CANDLES[code] = _shape(c) if c and len(c) >= 3 else None
    return _CANDLES[code]


def _krx_patch(code: str, c: list[dict]) -> list[dict]:
    """토스 일봉의 오늘 봉·어제 종가를 정규장(15:30) 기준으로 바꾼다 — 손절은 정규장 종가로 본다 (2026-10-08)."""
    from backend.services.naver_live import krx_day  # noqa: PLC0415
    k = krx_day(code)
    if not k or not str(c[-1].get("timestamp", "")).startswith(datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()):
        return c
    c = [dict(x) for x in c]
    c[-1].update(openPrice=k["open"], highPrice=max(k["high"], k["close"]), lowPrice=min(k["low"], k["close"]), closePrice=k["close"], volume=k["volume"])
    c[-2]["closePrice"] = k["base"]
    return c


def _sections(content: str) -> list[tuple[str, str]]:
    content = content or ""
    ms = list(_HEAD.finditer(content))
    out = []
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(content)
        memo = re.sub(r"\[사진\d+\]", "", content[m.end():end]).strip()
        out.append((re.sub(r"\(.*?\)", "", m.group(2)).strip(), memo))
    return out


def _condition(memo: str) -> dict:
    lv, kind = 0, "watch"
    for m in _NUM.finditer(memo):
        if m.group(3):
            base = int(m.group(3))
            v = base * 10000 + {"초반": 2000, "중반": 5000, "후반": 8000}.get(m.group(4) or "", 0) * (10 if base >= 10 else 1)
        else:
            v = int(m.group(1).replace(",", "")) * (10000 if m.group(2) and "만" in m.group(2) else 1)
        if v < 100:
            continue
        ctx = memo[max(0, m.start() - 6): m.end() + 14]
        kind, lv = next((k for k, pat in _KW if re.search(pat, ctx)), "near"), v
        break
    return {"kind": kind, "level": lv, "doji": bool(_DOJI_ENTRY.search(memo))}


def post_items(db: Session, days: int = 14) -> dict:
    from sqlalchemy import select  # noqa: PLC0415
    from backend.db.models import DiscussionPost  # noqa: PLC0415
    from backend.services.telegram import ME, _find  # noqa: PLC0415
    since = datetime.utcnow() - timedelta(days=days)
    out: dict = {}
    for p in db.scalars(select(DiscussionPost).where(DiscussionPost.author == ME, DiscussionPost.created_at >= since,
                                                      DiscussionPost.title.like("%정리%")).order_by(DiscussionPost.id)):
        secs = _sections(p.content)
        if len(secs) < 3:
            continue
        for name, memo in secs:
            q = ALIAS.get(name) or ALIAS.get(name.replace(" ", "")) or name.replace(" ", "")
            row = _find(db, q)
            if not row:
                continue
            wrote = (p.created_at + timedelta(hours=9)).date().isoformat()      # created_at은 UTC
            out[row.code] = {"code": row.code, "name": row.name, "memo": memo, "post": p.id, "title": p.title or "", "wrote": wrote, **_condition(memo)}
    return out


def _candle_word(s: dict) -> str:
    if "🔥장대양봉" in s["tags"]:
        return "장대양봉"
    if "⚠장대음봉" in s["tags"]:
        return "장대음봉"
    t = next((x.replace("🕯", "") for x in s["tags"] if "도지" in x), "")
    return t or ("양봉" if s["close"] > s["open"] else "음봉" if s["close"] < s["open"] else "보합")


def post_report(db: Session, force: bool = False) -> str | None:
    from html import escape  # noqa: PLC0415
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    items = post_items(db)
    if not items:
        return None
    ok, bad, rest = [], [], []
    last_date = ""
    wl = {x["code"]: x for x in _items(db)}
    for it in items.values():
        w = wl.get(it["code"])
        if not it["level"] and w and w.get("level"):      # 메모에 가격이 없으면 관심 목록 기준가를 이어서 쓴다
            it = {**it, "kind": w["kind"], "level": w["level"]}
        s = _day(it["code"], fetch_candles)
        if not s:
            continue
        last_date = max(last_date, s["date"])
        p, lv, kind = s["close"], it["level"], it["kind"]
        if s["date"] <= it["wrote"]:      # 글 쓴 날 이전 봉은 이미 보고 쓴 것 — 다음 거래일부터 채점
            rest.append(f"{escape(it['name'])} (글 쓴 뒤 첫 거래일 전)")
            continue
        is_doji = any("도지" in x for x in s["tags"])
        hits, warn = [], ""
        if kind == "above" and lv and p > lv:
            hits.append(f"{_won(lv)} 돌파 마감")
        elif kind == "near" and lv and abs(p / lv - 1) <= 0.03:
            hits.append(f"{_won(lv)} 근처 ({(p / lv - 1) * 100:+.1f}%)")
        elif kind == "hold" and lv and p < lv:
            warn = f"{_won(lv)} 이탈"
        if it["doji"] and is_doji and not warn:
            hits.append("말씀하신 도지 떴음")
        cond = ""
        if lv:
            cond = {"above": f"{_won(lv)}까지 {(lv / p - 1) * 100:+.1f}%", "near": f"{_won(lv)} 대비 {(p / lv - 1) * 100:+.1f}%",
                    "hold": f"{_won(lv)} {'지킴' if p >= lv else '이탈'}"}[kind]
        base = f"<b>{escape(it['name'])}</b> {_won(p)} ({s['chg']:+.1f}%) · {_candle_word(s)} · 거래 {s['vx']:.1f}배"
        memo = escape(it["memo"].replace(chr(10), " ")[:70])
        if warn:
            bad.append(f"{base} · ⚠ {warn}{chr(10)}   └ <i>{memo}</i>")
        elif hits:
            ok.append(f"{base} · ✅ {', '.join(hits)}{chr(10)}   └ <i>{memo}</i>")
        else:
            rest.append(f"{escape(it['name'])} {s['chg']:+.1f}% {_candle_word(s)}" + (f" · {cond}" if cond else ""))
    if not force and last_date != datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat():
        return None
    out = [f"📝 <b>정리 글 조건 체크 {last_date[5:].replace('-', '/')} {_when()}</b> ({len(items)}종목)"]
    if ok:
        out += ["", "✅ <b>적어 두신 조건이 맞은 종목</b>"] + ok
    if bad:
        out += ["", "⚠ <b>지지선 이탈</b>"] + bad
    if rest:
        out += ["", "· 아직", "<i>" + chr(10).join(rest) + "</i>"]
    return chr(10).join(out)
