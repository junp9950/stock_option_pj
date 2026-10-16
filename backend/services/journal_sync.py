"""매매 일지 자동 채우기 (2026-10-17 사용자 "오늘 매수기록은 왜 달력에 복기 안하누?? 매일 8시 넘으면 확인하는 로직 넣어야할듯").

달력·복기는 매매 일지(trade_executions) 체결만 보여 주는데, 10/12~10/15는 손으로 넣었다.
평일 20:05(장 후 거래 끝난 뒤)와 다음 날 08:05(놓친 날 보충)에 메리츠 주문내역 API에서 체결된 것을 받아 넣는다.
이미 같은 날·종목·매수/매도·수량·가격 행이 있으면 건너뜀(손으로 넣은 행과 겹치지 않게). 10/14·10/15 손 기록과 API 32건 전부 일치 확인.
새로 넣은 게 있으면 사장님 텔레그램으로 '달력에서 복기 쓰기' 알림.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
OWNER = "junp"
CHAN = {"120": "서버 자동(API)", "157": "앱"}


ETF_RE = re.compile(r"^(KODEX|TIGER|SOL|ACE|RISE|PLUS|KIWOOM|HANARO|KOACT|TIME|TIMEFOLIO|1Q|WON|BNK|ITF|마이다스|에셋플러스|파워|히어로즈|KBSTAR|ARIRANG|KOSEF)\b")


def sell_tax(side: str, code: str, name: str, amount: float) -> float:
    """매도 증권거래세 0.20% (2026년부터, 코스피·코스닥 같음). ETF·ETN은 없음. 메리츠 수수료는 0 (2026-10-17 사용자 "하루 수익 74652인데?")."""
    if side != "매도" or ETF_RE.match(name or "") or not code[:6].isdigit() or "ETN" in (name or ""):
        return 0.0
    return round(amount * 0.002)


def pool_of(crdt) -> str:
    """메리츠 신용 구분 → 짝 맞추기 묶음: 10 현금 · 21/22 신용 · 31/32 신용(다른 대출) · 그 밖은 모름."""
    c = str(crdt or "")
    return {"1": "cash", "2": "cr2", "3": "cr3"}.get(c[:1], "") if len(c) == 2 else ""


def _rows(day: date) -> list[dict]:
    from backend.services import meritz  # noqa: PLC0415
    out = []
    for x in meritz.orders_today(day.strftime("%Y%m%d")):
        q = int(float(x.get("total_cntg_qty") or 0))
        side = {"1": "매도", "2": "매수"}.get(str(x.get("deal_cls_code")))
        iscd = str(x.get("iscd") or "")
        if q <= 0 or not side or not (iscd.startswith("A") and len(iscd) == 7):
            continue
        px = float(x.get("cntg_unpr") or 0)
        t = str(x.get("oder_pros_sta_time") or "")
        hm = f"{t[:2]}:{t[2:4]}" if len(t) >= 4 else ""
        credit = str(x.get("crdt_oder_cls_code") or "") not in ("", "0", "00", "10")
        memo = " · ".join(v for v in (f"메리츠 API 체결내역({day.month}/{day.day})", "신용" if credit else "현금", f"주문 {hm}" if hm else "",
                                      CHAN.get(str(x.get("chan_type_cls_code")), ""), "장 전(넥스트레이드)" if hm and hm < "08:59" and CHAN.get(str(x.get("chan_type_cls_code"))) == "앱" else "")
                          if v)
        # seq 자릿수 맞춤 — 글자 순서 = 주문 순서 (하루 안 매수·매도 짝이 바뀌지 않게, 10/17 'mz98967'이 'mz266154' 뒤로 갔음)
        out.append({"trade_date": day, "seq": f"mz{int(x.get('oder_no') or 0):08d}", "side": side, "code": iscd[1:], "name": x.get("kor_issu_abwr_name") or iscd[1:],
                    "qty": q, "price": px, "amount": q * px, "fee": sell_tax(side, iscd[1:], x.get("kor_issu_abwr_name") or "", q * px), "kind": "", "tag": "", "memo": memo,
                    "pool": pool_of(x.get("crdt_oder_cls_code"))})
    return out


def sync(db: Session, day: date, notify: bool = True) -> dict:
    from backend.services import trade_journal  # noqa: PLC0415
    api = _rows(day)
    have = Counter((s, c, int(q), round(float(p))) for s, c, q, p in db.execute(text(
        "select side, code, qty, price from trade_executions where owner = :o and trade_date = :d"), {"o": OWNER, "d": day}).all())
    new = []
    for r in api:
        k = (r["side"], r["code"], r["qty"], round(r["price"]))
        if have[k] > 0:
            have[k] -= 1          # 손으로 넣은 같은 행 → 건너뜀
            continue
        new.append(r)
    res = trade_journal.add(db, OWNER, new) if new else {"added": 0, "skipped": 0}
    added = res.get("added", 0)
    if added:               # 일지 결과 캐시는 행 수·id로 열쇠를 만들어 저절로 새로 계산됨
        if notify:
            try:
                from backend.services.telegram import SITE, owner_chats, send  # noqa: PLC0415
                buys = sorted({r["name"] for r in new if r["side"] == "매수"})
                sells = sorted({r["name"] for r in new if r["side"] == "매도"})
                msg = f"📒 {day.month}/{day.day} 체결 {added}건 매매 일지에 넣었습니다\n" + (f"매수: {', '.join(buys)}\n" if buys else "") + \
                      (f"매도: {', '.join(sells)}\n" if sells else "") + f"달력에서 종목별 근거를 적으면 피드백이 달립니다\n{SITE}/#journal"
                for c in owner_chats(db):
                    send(db, msg, c)
            except Exception as exc:  # noqa: BLE001
                logger.warning("일지 자동 채우기 알림 실패: %s", type(exc).__name__)
    logger.info("매매 일지 자동 채우기 %s: API %d건 · 새로 %d건", day, len(api), added)
    return {"day": str(day), "api": len(api), "added": added}


def run(db: Session, phase: str) -> dict | None:
    """evening = 오늘(평일 20:05) · morning = 앞 거래일 보충(평일 08:05, 알림 있음)."""
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = date.today()
    if phase == "evening":
        return sync(db, today) if is_trading_day(today) else None
    d = today - timedelta(days=1)
    for _ in range(7):
        if is_trading_day(d):
            return sync(db, d)
        d -= timedelta(days=1)
    return None
