"""사용자 관심 종목 장 마감 점검 (2026-10-05 "그 종목들 확인해서 3시 40분에 알림 보내라").

사용자가 차트 보고 적어 둔 관심 목록(기준가·조건)을 장 마감 뒤 15:40에 토스 일봉으로 점검해 텔레그램으로 보낸다.
조건 종류: above = 종가가 기준가 위로 마감(돌파·돌려놓기), near = 종가가 기준가 ±3% 안(수렴 확인),
hold = 종가가 기준가를 지킴(아래면 이탈), watch = 기준가 없이 봉 모양·거래만 본다.
목록은 settings 'user_watchlist'에 저장 — 처음엔 SEED로 채운다.
"""
from __future__ import annotations

import time
from datetime import datetime
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
    if rng > 0 and abs(cl - o) / o <= 0.01 and rng / cl >= 0.03:
        tags.append("🕯밑꼬리 도지" if (min(o, cl) - l) / rng >= 0.5 else "🕯도지")
    if chg >= 5 and vx >= 2:
        tags.append("🔥장대양봉")
    elif chg <= -5 and vx >= 2:
        tags.append("⚠장대음봉")
    if vx and vx <= 0.5:
        tags.append("거래 마름")
    return {"date": c[-1]["timestamp"][:10], "close": cl, "chg": chg, "vx": vx,
            "width": (max(closes) / min(closes) - 1) * 100 if closes else 0, "tags": tags}


def _won(x: float) -> str:
    return f"{x:,.0f}"


def report(db: Session, force: bool = False) -> str | None:
    """텔레그램 HTML. 할 일 있는 종목만 한 줄씩 굵게, 조용한 종목은 이름만 묶는다 (2026-10-05 "가독성이 너무 안 좋노")."""
    from html import escape  # noqa: PLC0415
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    g = {k: [] for k in ("brk", "fire", "close", "candle", "warn", "dry", "far")}
    last_date = ""
    for it in _items(db):
        c = fetch_candles(it["code"], "1d", 25)
        time.sleep(0.15)
        s = _shape(c) if c and len(c) >= 3 else None
        if not s:
            continue
        last_date = max(last_date, s["date"])
        lv, p, nm = it["level"], s["close"], f"<b>{escape(it['name'])}</b>"
        pct = f"{s['chg']:+.1f}%"
        candle = next((t for t in s["tags"] if "도지" in t), "")
        if "🔥장대양봉" in s["tags"]:
            g["fire"].append(f"{nm} {pct} · 거래 {s['vx']:.0f}배" + (f" · {_won(lv)} 위 마감 ✅" if it["kind"] == "above" and p >= lv else ""))
        elif it["kind"] == "above" and p >= lv:
            g["brk"].append(f"{nm} {_won(p)} ({pct}) · {_won(lv)} 위 마감 · 거래 {s['vx']:.1f}배" + (f"\n   └ <i>{escape(it['note'])}</i>" if it.get("note") else ""))
        elif "⚠장대음봉" in s["tags"] or (it["kind"] == "hold" and p < lv):
            g["warn"].append(f"{nm} {pct}" + (f" · {_won(lv)} 이탈" if it["kind"] == "hold" and p < lv else " · 장대음봉"))
        elif it["kind"] == "above" and p >= lv * 0.97:
            g["close"].append(f"{nm} {_won(p)} → {_won(lv)}  <i>{(lv / p - 1) * 100:.1f}% 남음</i>")
        elif it["kind"] == "near" and abs(p / lv - 1) <= 0.03:
            g["close"].append(f"{nm} {_won(p)} · 기준 {_won(lv)} 근처 ({(p / lv - 1) * 100:+.1f}%)")
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
    out = [f"📋 <b>관심 종목 {d} 마감</b>"]
    blocks = (("✅ 매수 조건: 선 위 마감 → 종가 매수 검토", "brk"), ("🔥 거래 실린 장대양봉", "fire"), ("👀 선 코앞 (3% 안)", "close"),
              ("🕯 도지", "candle"), ("⚠ 이탈·장대음봉", "warn"))
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


def send_report(db: Session, force: bool = False, chat_id: str | None = None) -> None:
    from backend.services.telegram import _get, _put, send  # noqa: PLC0415
    msg = report(db, force=force)
    if not msg:
        return
    chats = [chat_id] if chat_id else _get(db, CHAT_KEY, None)
    if chats is None:       # 처음 실행 때 등록된 대화방(사용자 본인)으로 고정
        chats = list(_get(db, "telegram_chats", {}).keys())
        _put(db, CHAT_KEY, chats)
    for c in chats:
        send(db, msg, c, html=True)
