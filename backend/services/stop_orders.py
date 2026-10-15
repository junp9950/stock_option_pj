"""손절가 자동 주문 (메리츠 스톱지정가) — 2026-10-13 사용자 "손절가 주문은 내일부터 걸어 줘, 내일 매수 종목부터".

규칙
- 대상: 2026-10-14부터 새로 사거나 더 산 수량만. 10/13까지 들고 있던 것(기준 잔고)은 건드리지 않는다.
- 손절가: 관리 탭 '관심·보유'의 손절선(hold 줄)이 있으면 그것, 없으면 사이트 규칙 = 산 날 저가 −1%(호가 단위 내림).
  산 날 장중에는 저가가 확정 전이라 그때까지의 저가로 걸고, 다음 날 아침 확정 저가로 다시 건다.
- 주문: 감시가 = 손절가, 지정가 = 손절가 −1%(호가 내림, 갭 하락에도 체결되게 — 사용자 승인). KRX 정규장만 · 당일 유효라 매일 아침 다시 건다.
- 시각: 08:50 아침 걸기(안 되면 09:01 다시) · 장중 5분마다 새로 산 것·손절선 바뀐 것·체결 확인 · 15:40 마감 정리.
- 나오는 기준(10/14부터 새로 산 것만, 사용자 승인 10/13): 반등 모드로 산 것 = 5거래일째 15:21 종가 시장가 매도(12년: 21선 따라가기보다 +1.3%p),
  바닥 모으기 후보로 산 것(bottom_mode, 10/15) = 손절 산 값 −25% · 켜진 날부터 20거래일째 15:21 종가 시장가 매도 (21일선 매도 없음),
  그 밖 = 21일선 위로 한 번 마감한 뒤부터 21일선 아래 마감이면 다음 날 08:50 시초가 시장가 매도.
- 안전: 하루 주문 40건 상한(10/13 15→40), 수량은 실제 잔고를 넘지 않음, 브로커 경고가 오면 자동 확인하지 않고 알림만,
  텔레그램 /스톱끄기 · /스톱켜기 · /스톱 (상태). 알림은 사장님 대화방(telegram_chats)에만.
상태: settings 'meritz_stop' = {on, start, baseline{lot: qty}, lots{lot: {...}}, orders{date: [...]}, notified[]}
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
KEY = "meritz_stop"
START = "2026-10-14"
MAX_ORDERS_DAY = 40      # 2026-10-13: 15였는데 아침에 이미 12건이라 새로 산 4번째부터 손절이 안 걸릴 뻔 — 폭주 방지용 상한은 남김


def _now() -> datetime:
    return datetime.now(KST)


def _st(db: Session) -> dict:
    from backend.services.telegram import _get  # noqa: PLC0415
    s = _get(db, KEY, None) or {}
    s.setdefault("on", True); s.setdefault("start", START); s.setdefault("baseline", {}); s.setdefault("lots", {})
    s.setdefault("orders", {}); s.setdefault("notified", [])
    return s


def _save(db: Session, s: dict) -> None:
    from backend.services.telegram import _put  # noqa: PLC0415
    s["orders"] = dict(sorted(s["orders"].items())[-10:])          # 최근 10일치만
    s["notified"] = s["notified"][-200:]
    _put(db, KEY, s)


def _tell(db: Session, msg: str) -> None:
    from backend.services.telegram import owner_chats, send  # noqa: PLC0415
    try:
        for c in owner_chats(db):      # 사장님 본인 방만 — 알림 목록엔 /start 한 다른 사람 방도 있음 (2026-10-13)
            send(db, msg, c)
    except Exception as exc:  # noqa: BLE001
        logger.warning("스톱 알림 실패: %s", type(exc).__name__)


def _lot(h: dict) -> str:
    return f"{h['code']}|{'신용' if h['credit'] else '현금'}|{h['loan_date']}"


def _trading_days_before(d: date, n: int) -> date:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    k = 0
    while k < n:
        d -= timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return d


def _buy_date(h: dict, today: date) -> date:
    if h["credit"] and len(h["loan_date"]) == 8:      # 대출일 = 결제일(T+2) → 2영업일 전이 산 날
        ld = date(int(h["loan_date"][:4]), int(h["loan_date"][4:6]), int(h["loan_date"][6:]))
        return min(_trading_days_before(ld, 2), today)
    return today


def _stop_for(db: Session, code: str, buy: date, today: date) -> tuple[int | None, str, bool]:
    """(손절가, 근거, 확정 여부)."""
    from backend.services.telegram import _get  # noqa: PLC0415
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    for x in _get(db, "user_watchlist", []) or []:
        if x.get("code") == code and x.get("kind") == "hold" and (x.get("level") or 0) > 0:
            return int(x["level"]), "관리 탭 손절선", True
    low = None
    if buy < today:
        low = db.execute(text("select low_price from spot_daily_prices where stock_code = :c and trading_date = :d"), {"c": code, "d": buy}).scalar()
        final = True
    else:
        try:      # 산 날 장중·장 후: 정규장 저가 (토스 일봉은 장 후 넥스트레이드 저가가 섞임, 2026-10-13)
            from backend.services.naver_live import krx_day  # noqa: PLC0415
            k = krx_day(code)
            if k and k["date"] == str(today):
                low = float(k["low"])
        except Exception:  # noqa: BLE001
            low = None
        final = _now().hour * 100 + _now().minute >= 1530
    if not low:
        return None, "산 날 저가를 못 받음", False
    return int(tick_floor(float(low) * 0.99)), "산 날 저가 −1%", final


def _stop_lot(db: Session, L: dict, today: date) -> tuple[int | None, str, bool]:
    """바닥 모으기로 산 것은 산 값(평균) −25% — 관리 탭 손절선이 있으면 그게 먼저. 나머지는 _stop_for."""
    if L.get("mode") == "box" and L.get("box_stop"):      # 박스 돌파 = 박스 하단 −1% (관리 탭 손절선이 있으면 그것)
        from backend.services.telegram import _get  # noqa: PLC0415
        for x in _get(db, "user_watchlist", []) or []:
            if x.get("code") == L["code"] and x.get("kind") == "hold" and (x.get("level") or 0) > 0:
                return int(x["level"]), "관리 탭 손절선", True
        return int(L["box_stop"]), "박스 하단 −1%", True
    if L.get("mode") == "bottom":
        from backend.services.bottom_mode import STOP_PCT  # noqa: PLC0415
        from backend.services.telegram import _get  # noqa: PLC0415
        from backend.utils.ticks import tick_floor  # noqa: PLC0415
        for x in _get(db, "user_watchlist", []) or []:
            if x.get("code") == L["code"] and x.get("kind") == "hold" and (x.get("level") or 0) > 0:
                return int(x["level"]), "관리 탭 손절선", True
        return int(tick_floor(float(L["avg"]) * (1 - STOP_PCT))), "바닥 모으기 산 값 −25%", True
    return _stop_for(db, L["code"], date.fromisoformat(L["buy"]), today)


def _mode_for(db: Session, code: str, buy: date) -> str:
    """산 날 과매도 반등 목록(매수 5 + 참고)에 있던 종목이면 'crash'(5거래일째 종가 매도), 아니면 'trend'(21일선 이탈 매도)."""
    try:
        from backend.services.bottom_mode import lot_exit  # noqa: PLC0415
        if lot_exit(db, code, buy):
            return "bottom"
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend.services.box_signal import lot_info  # noqa: PLC0415
        if lot_info(db, code, buy):
            return "box"
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend.services.stock_signals import crash_now  # noqa: PLC0415
        cr = crash_now(db)
        if cr.get("active") and cr.get("date") == str(buy) and code in {x["code"] for x in cr.get("items", []) + cr.get("ref", [])}:
            return "crash"
    except Exception:  # noqa: BLE001
        pass
    return "trend"


def _close_vs_ema21(code: str, today: date) -> tuple[float | None, float | None]:
    """오늘 정규장 종가와 21일 지수이동평균(오늘 포함).
    토스 일봉 종가는 15:30 뒤 넥스트레이드 가격으로 바뀐다(2026-10-13 삼화콘덴서 정규장 142,800 → 18:40 토스 145,500) →
    지난날 = DB 종가(사이트 신호와 같은 값), 오늘 = 네이버 분봉 15:30 종가(naver_live.krx_day). 안 되면 토스 일봉."""
    try:
        from backend.db.database import SessionLocal  # noqa: PLC0415
        from backend.services.naver_live import krx_day  # noqa: PLC0415
        k = krx_day(code)
        if k and k["date"] == str(today):
            db = SessionLocal()
            try:
                rows = db.execute(text("select close_price from spot_daily_prices where stock_code = :c and trading_date < :d "
                                       "order by trading_date desc limit 120"), {"c": code, "d": today}).scalars().all()
            finally:
                db.close()
            if len(rows) >= 60:
                ema = None
                for c in [float(x) for x in rows[::-1]] + [float(k["close"])]:
                    ema = c if ema is None else ema + (c - ema) * 2 / 22
                return float(k["close"]), ema
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend.services import toss_client as t  # noqa: PLC0415
        cs = t._get("/candles", {"symbol": code, "interval": "1d", "count": 100}).json()["result"]["candles"]  # noqa: SLF001
        cs = sorted(cs, key=lambda x: x["timestamp"])
        if not cs or cs[-1]["timestamp"][:10] != str(today):
            return None, None
        ema = None
        for x in cs:
            c = float(x["closePrice"])
            ema = c if ema is None else ema + (c - ema) * 2 / 22
        return float(cs[-1]["closePrice"]), ema
    except Exception:  # noqa: BLE001
        return None, None


def _nth_trading_day_after(d: date, n: int) -> date:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    k = 0
    while k < n:
        d += timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return d


def _market_exit(db: Session, s: dict, lot: str, L: dict, today: date, why: str) -> str:
    """오늘 걸린 손절 주문을 취소하고 시장가 매도 (아침 = 시초가, 15:21 = 종가)."""
    from backend.services import meritz as M  # noqa: PLC0415
    o = _open_order(s, lot, today)
    if o:
        c = M.cancel(L["code"], o["order_no"], o["qty"], o["trigger"], o["limit"])
        if not c["ok"]:
            return f"⚠ {L['name']} {why} 매도 전 손절 주문 취소 실패 — {c['msg']} (직접 확인해 주세요)"
        o["done"] = "취소"
    r = M.market_sell(L["code"], L["qty"], L["credit"], L.get("loan_date", ""))
    s["orders"].setdefault(str(today), []).append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": 0, "limit": 0,
                                                  "order_no": r["order_no"], "ok": r["ok"], "at": _now().strftime("%H:%M"), "msg": r["msg"], "warn": r["warn"], "market": why})
    if r["ok"]:
        L["sell_pending"] = str(today)
        return f"▼ {L['name']} {L['qty']}주 {why} — 시장가 매도 주문 넣음"
    return f"⚠ {L['name']} {why} 시장가 매도 실패 — {r['warn'] or r['msg']} (직접 팔아 주세요)"


def sync(db: Session, s: dict, today: date) -> list[str]:
    """실제 잔고로 기준·대상 수량을 맞춘다. 알림 문장 목록을 돌려준다."""
    from backend.services import meritz as M  # noqa: PLC0415
    msgs = []
    hs = M.holdings()
    now_q = {}
    meta = {}
    for h in hs:
        now_q[_lot(h)] = now_q.get(_lot(h), 0) + h["qty"]; meta[_lot(h)] = h
    if str(today) < s["start"]:
        s["baseline"] = now_q            # 시작 전: 지금 들고 있는 것 전부가 기준(주문 안 함)
        return msgs
    # 장기 보유(관리 탭 '장기 보유(알림 제외)' = held_exclude) · 사용자가 뺀 종목은 더 사도 자동 매도 안 함 (2026-10-13 "하닉은 안 팔 거다")
    from backend.services.telegram import _get  # noqa: PLC0415
    from backend.services.watchlist import HELD_EXCLUDE  # noqa: PLC0415
    excl = set(_get(db, "held_exclude", None) or HELD_EXCLUDE) | set(s.get("exclude", []))
    for lot in list(now_q):
        if lot.split("|")[0] in excl:
            s["baseline"][lot] = now_q[lot]
            if lot in s["lots"]:
                o = _open_order(s, lot, today)       # 오늘 걸린 손절이 있으면 취소 (빼기로 한 종목이 팔리지 않게, 2026-10-13 2차 검토)
                if o:
                    c_ = M.cancel(o["code"], o["order_no"], o["qty"], o["trigger"], o["limit"])
                    if c_["ok"]:
                        o["done"] = "취소(제외)"
                    else:
                        msgs.append(f"⚠ {s['lots'][lot]['name']} 오늘 손절 주문 취소 실패 — 증권사 앱에서 직접 취소해 주세요")
                msgs.append(f"✅ {s['lots'][lot]['name']}: 장기 보유라 자동 매도에서 뺌")
                s["lots"].pop(lot)
    for lot, q in now_q.items():
        base = s["baseline"].get(lot, 0)
        extra = q - base
        L = s["lots"].get(lot)
        if extra > 0 and not L:
            h = meta[lot]
            buy = _buy_date(h, today)
            mode = _mode_for(db, h["code"], buy)
            L = {"code": h["code"], "name": h["name"], "credit": h["credit"], "loan_date": h["loan_date"], "qty": extra,
                 "buy": str(buy), "avg": h["avg"], "mode": mode, "legacy": str(buy) < START, "armed": False}
            if mode == "bottom":
                from backend.services.bottom_mode import lot_exit  # noqa: PLC0415
                L["exit"] = lot_exit(db, h["code"], buy)
            elif mode == "box":
                from backend.services.box_signal import lot_info  # noqa: PLC0415
                bi = lot_info(db, h["code"], buy) or {}
                L["exit"], L["box_stop"] = bi.get("exit"), bi.get("stop")
            stop, src, final = _stop_lot(db, L, today)
            L.update(stop=stop, src=src, final=final)
            s["lots"][lot] = L
            msgs.append(f"🆕 새로 산 것 감지: {h['name']} {extra}주 ({'신용' if h['credit'] else '현금'}) · 손절가 "
                        + (f"{stop:,} ({src})" if stop else f"없음 — {src}, 관리 탭에서 손절선을 넣어 주세요"))
        elif L and extra != L["qty"]:
            if extra <= 0:
                msgs.append(f"✅ {L['name']} 새로 산 수량이 정리됐습니다 (손절 주문 대상에서 뺌)")
                s["lots"].pop(lot, None)
            else:
                L["qty"] = extra
                if L.get("mode") == "bottom":          # 바닥 모으기 2·3차로 더 사면 평균이 바뀜 → 손절가도
                    L["avg"] = meta[lot]["avg"]
                    L["stop"], L["src"], L["final"] = _stop_lot(db, L, today)
        if q < base:                     # 기준 잔고를 판 경우 기준도 줄인다(다음에 다시 사면 새 것으로 보게)
            s["baseline"][lot] = q
    for lot in list(s["lots"]):
        if lot not in now_q:
            msgs.append(f"✅ {s['lots'][lot]['name']} 잔고에서 사라짐 (매도·손절) — 손절 주문 대상에서 뺌")
            s["lots"].pop(lot)
    for lot in list(s["baseline"]):
        if lot not in now_q:
            s["baseline"].pop(lot)
    return msgs


def _place(db: Session, s: dict, lot: str, L: dict, today: date) -> str:
    from backend.services import meritz as M  # noqa: PLC0415
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    day = s["orders"].setdefault(str(today), [])
    if len(day) >= MAX_ORDERS_DAY:
        return f"⚠ {L['name']}: 오늘 주문 상한({MAX_ORDERS_DAY}건)이라 안 걸었습니다"
    if not L.get("stop"):
        return f"⚠ {L['name']}: 손절가가 없어 안 걸었습니다 — 관리 탭에서 손절선을 넣어 주세요"
    trig = int(L["stop"]); lim = int(tick_floor(trig * 0.99))
    # 손절가가 지금가(마지막 정규장 종가) 이상이면 내지 않음 — 즉시 발동·거절 위험, 갭 하락은 사람이 판단 (2026-10-13 2차 검토)
    last = _last_close(L["code"])
    if last and last <= trig:
        day.append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": trig, "limit": lim, "order_no": None,
                    "ok": False, "at": _now().strftime("%H:%M"), "msg": "손절가 ≥ 지금가", "warn": ""})
        return f"⚠ {L['name']} 손절가 {trig:,} ≥ 지금가 {last:,.0f} — 주문 안 냄, 직접 판단해 주세요"
    # 앞서 실패로 기록됐는데 실제론 접수됐을 수 있음(응답 유실) → 오늘 주문 내역에 같은 종목·수량 미체결 매도가 있으면 그걸로 (2차 검토)
    if any(o["lot"] == lot and not o["ok"] and not o.get("market") for o in day):
        hit = _find_open_sell(L["code"], L["qty"], today)
        if hit:
            day.append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": trig, "limit": lim, "order_no": hit,
                        "ok": True, "at": _now().strftime("%H:%M"), "msg": "앞 주문이 접수돼 있었음", "warn": ""})
            return f"🛑 {L['name']} {L['qty']}주 · 앞서 낸 손절 주문이 접수돼 있었음 (다시 안 냄)"
    r = M.stop_sell(L["code"], L["qty"], trig, lim, L["credit"], L.get("loan_date", ""))
    day.append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": trig, "limit": lim, "order_no": r["order_no"],
                "ok": r["ok"], "at": _now().strftime("%H:%M"), "msg": r["msg"] if not r["ok"] else "", "warn": r["warn"]})
    if r["ok"]:
        return f"🛑 {L['name']} {L['qty']}주 · 감시 {trig:,} → 지정가 {lim:,} ({L['src']})"
    return f"⚠ {L['name']} 주문 실패 — {r['warn'] or r['msg']} (직접 걸어 주세요)"


def _last_close(code: str) -> float | None:
    try:
        from backend.services.naver_live import krx_day  # noqa: PLC0415
        k = krx_day(code)
        return float(k["close"]) if k else None
    except Exception:  # noqa: BLE001
        return None


def _find_open_sell(code: str, qty: int, today: date) -> str | None:
    """오늘 주문 내역에서 이 종목 미체결 매도(같은 수량) 주문번호."""
    from backend.services import meritz as M  # noqa: PLC0415
    try:
        for x in M.orders_today(today.strftime("%Y%m%d"), "1"):
            if str(x.get("iscd", "")).endswith(code) and int(float(x.get("ncnt_qty") or 0)) > 0 and int(float(x.get("odqt") or 0)) == int(qty) \
                    and not str(x.get("rctf_cncl_cls_code") or "0").strip("0"):
                return str(x.get("oder_no"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _open_order(s: dict, lot: str, today: date) -> dict | None:
    xs = [o for o in s["orders"].get(str(today), []) if o["lot"] == lot and o["ok"] and not o.get("done")]
    return xs[-1] if xs else None


def _check_refused(s: dict, today: date) -> list[str]:
    """접수 뒤 증권사 거부 확인 (2026-10-14 첫날: 삼성SDI 현금 2주가 0307 거부 — 매도 가능 0 — 인데 '걸었음'으로 알림).
    거부면 실패로 돌려 09:01에 한 번 더 걸고 바로 알린다. 그래도 거부면 하루 두 번 실패라 더 안 낸다."""
    from backend.services import meritz as M  # noqa: PLC0415
    out = []
    try:
        hist = {str(x.get("oder_no")): x for x in M.orders_today(today.strftime("%Y%m%d"), "1")}
        for o in s["orders"].get(str(today), []):
            h = hist.get(str(o.get("order_no")))
            if o.get("ok") and not o.get("done") and h and str(h.get("oder_pros_stat_cls_code")) == "3":
                o.update(ok=False, done="거부", msg=f"증권사 거부 {h.get('oder_rfus_reas_code')}")
                out.append(f"⚠ {o['name']} {o['qty']}주 손절 주문이 증권사에서 거부됨 (코드 {h.get('oder_rfus_reas_code')} · 매도 가능 {h.get('oder_able_qty')}주)"
                           " — 이 수량은 지금 손절이 안 걸려 있습니다. 앱에서 확인해 주세요")
    except Exception as exc:  # noqa: BLE001
        logger.warning("스톱 거부 확인 실패: %s", type(exc).__name__)
    return out


def _gap_resell(db: Session, s: dict, today: date) -> list[str]:
    """갭 하락으로 손절 감시는 발동했는데 지정가(손절가 −1%)가 지금가보다 위라 안 팔리고 걸려만 있는 것 → 취소하고 시장가 매도.
    2026-10-15 사용자 "장초 갭락으로 매도 주문 실행 안 되면 니가 체크해서 다시 팔아라" (그날 아침 삼화콘덴서·삼성전기·롯데렌탈·주성·대덕을 손으로 처리).
    정규장 09:00~15:19만 (15:20부터는 종가 단일가). 일부 체결이면 남은 수량만."""
    from backend.services import meritz as M  # noqa: PLC0415
    from backend.services.naver_live import snapshot  # noqa: PLC0415
    hm = _now().hour * 100 + _now().minute
    if not (900 <= hm < 1520):
        return []
    day = s["orders"].get(str(today), [])
    open_ = [o for o in day if o["ok"] and not o.get("done") and not o.get("market")]
    if not open_:
        return []
    out = []
    try:
        hist = {str(x.get("oder_no")): x for x in M.orders_today(today.strftime("%Y%m%d"), "1")}
        lv = snapshot(sorted({o["code"] for o in open_}), max_age=20)
    except Exception as exc:  # noqa: BLE001
        logger.warning("갭 하락 확인 실패: %s", type(exc).__name__)
        return []
    for o in open_:
        h = hist.get(str(o.get("order_no"))) or {}
        rem = int(float(h.get("ncnt_qty") or 0))
        p = (lv.get(o["code"]) or {}).get("c")
        L = s["lots"].get(o["lot"])
        if not (L and rem > 0 and p and p < o["limit"]):
            continue
        c = M.cancel(o["code"], o["order_no"], rem, o["trigger"], o["limit"])
        if not c["ok"]:
            out.append(f"⚠ {o['name']} 갭 하락 — 손절 주문 취소 실패 ({c['msg']}) · 직접 확인해 주세요"); continue
        o["done"] = "취소(갭 하락)"
        r = M.market_sell(o["code"], rem, L["credit"], L.get("loan_date", ""))
        day.append({"lot": o["lot"], "code": o["code"], "name": o["name"], "qty": rem, "trigger": 0, "limit": 0, "order_no": r["order_no"], "ok": r["ok"],
                    "at": _now().strftime("%H:%M"), "msg": r["msg"], "warn": r["warn"], "market": "갭 하락 손절 시장가"})
        if r["ok"]:
            L["sell_pending"] = str(today)
            out.append(f"▼ {o['name']} {rem}주 갭 하락 — 손절가 {o['trigger']:,} 아래({p:,.0f})라 안 팔려 시장가로 다시 매도")
        else:
            out.append(f"⚠ {o['name']} 갭 하락 시장가 매도 실패 — {r['warn'] or r['msg']} (직접 팔아 주세요)")
    return out


_RUN_LOCK = __import__("threading").Lock()


def run(db: Session, phase: str) -> str:
    """같은 계좌 작업이 겹치면(아침이 길어져 09:01과 겹침 등) 뒤의 것은 건너뜀 (2026-10-13 2차 검토)."""
    if not _RUN_LOCK.acquire(blocking=False):
        return "앞 작업이 도는 중이라 건너뜀"
    try:
        return _run(db, phase)
    finally:
        _RUN_LOCK.release()


def _run(db: Session, phase: str) -> str:
    """phase: morning(08:50) · retry(09:01) · intraday(5분) · preclose(15:21 반등 모드 5일째 종가 매도) · close(15:40 21일선 확인)
    · late(20:10 장 후 시간외에 산 것) · baseline(기준 잡기)."""
    from backend.services import meritz as M  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    if not M.enabled():
        return "메리츠 키 없음"
    today = _now().date()
    if phase not in ("baseline", "late") and not is_trading_day(today):
        return "장 없는 날"
    s = _st(db)
    # 하루만 끄기 (2026-10-15 급락 날 사용자 "오늘 장중에는 손절 안 되게") — 다음 거래일 아침에 저절로 다시 켬
    if not s["on"] and s.get("off_until") and str(today) > s["off_until"] and phase in ("morning", "retry", "intraday"):
        s["on"] = True; s.pop("off_until", None)
        _tell(db, "🛑 손절 자동 주문 다시 켬 (어제 하루만 껐던 것) — 오늘 아침 확정 손절가로 겁니다")
    try:
        msgs = sync(db, s, today)
    except Exception as exc:  # noqa: BLE001
        _save(db, s)
        logger.warning("스톱 잔고 확인 실패: %s", exc)
        if phase in ("morning", "retry") and str(today) >= s["start"]:
            _tell(db, f"⚠ 손절 주문: 메리츠 잔고를 못 읽어 오늘 아침 주문을 못 걸었습니다 ({exc}). 직접 걸어 주세요.")
        return f"잔고 확인 실패: {exc}"
    out = list(msgs)
    if str(today) >= s["start"] and phase in ("retry", "intraday", "close") and s["orders"].get(str(today)):
        out += _check_refused(s, today)
    if str(today) >= s["start"] and s["on"] and phase in ("retry", "intraday") and not (s.get("no_stop_until") and str(today) <= s["no_stop_until"]):
        out += _gap_resell(db, s, today)
    if str(today) >= s["start"] and s["on"] and phase in ("morning", "retry", "intraday"):
        day = s["orders"].setdefault(str(today), [])
        for lot, L in s["lots"].items():
            if L.get("sell_pending") == str(today):
                continue
            if L.get("exit_next") and phase in ("morning", "retry"):
                tried = [x for x in day if x["lot"] == lot and x.get("market")]
                if not any(x["ok"] for x in tried) and len(tried) < 2:      # 08:50 실패하면 09:01 한 번 더
                    out.append(_market_exit(db, s, lot, L, today, L["exit_next"]))
                continue
            # 아침: 확정 저가(전날까지 산 것)나 관리 탭 손절선으로 다시 계산. 장중: 관리 탭 손절선이 바뀐 것만
            # (산 날 장중 손절가는 그때까지 저가 −1%로 두고 따라 내리지 않는다 — 따라 내리면 영영 안 걸림)
            if phase in ("morning", "retry"):
                stop, src, final = _stop_lot(db, L, today)
                if stop:
                    L.update(stop=stop, src=src, final=final)
            else:
                stop, src, final = _stop_lot(db, L, today)
                if stop and src == "관리 탭 손절선":
                    L.update(stop=stop, src=src, final=True)
            if s.get("no_stop_until") and str(today) <= s["no_stop_until"]:
                continue      # 하따 구간 손절 안 걸기 (2026-10-15 사용자 "오늘 하락은 하따 줍기니까 기존 손절선 적용하지 말자") — 정해진 날 매도·21선 매도는 그대로
            o = _open_order(s, lot, today)
            if o and (o["trigger"] != L.get("stop") or o["qty"] != L["qty"]):
                c = M.cancel(L["code"], o["order_no"], o["qty"], o["trigger"], o["limit"])
                if not c["ok"]:
                    out.append(f"⚠ {L['name']} 기존 손절 주문 취소 실패 — {c['msg']} (직접 확인해 주세요)")
                    continue
                o["done"] = "취소"
                out.append(f"↺ {L['name']} 손절가 바뀜: {o['trigger']:,} → {L.get('stop') or 0:,}")
                o = None
            if o:
                continue
            fails = [x for x in day if x["lot"] == lot and not x["ok"]]
            if len(fails) >= 2 or (fails and phase == "intraday"):
                continue                  # 하루 두 번(아침·09:01)까지만 시도 — 실패 알림이 5분마다 쏟아지지 않게
            out.append(_place(db, s, lot, L, today))
        if phase == "morning" and day:      # 아침에 낸 주문이 접수 직후 거부됐는지 (거부는 몇 초 안에 옴)
            import time as _t  # noqa: PLC0415
            _t.sleep(5)
            out += _check_refused(s, today)
    if str(today) >= s["start"] and s["on"] and phase == "preclose":
        for lot, L in s["lots"].items():
            if L.get("mode") == "crash" and not L.get("legacy") and not L.get("sell_pending") \
                    and str(_nth_trading_day_after(date.fromisoformat(L["buy"]), 5)) <= str(today):
                out.append(_market_exit(db, s, lot, L, today, "반등 모드 5거래일째 종가"))
            elif L.get("mode") == "bottom" and not L.get("sell_pending") and L.get("exit") and L["exit"] <= str(today):
                out.append(_market_exit(db, s, lot, L, today, "바닥 모으기 20거래일째 종가"))
            elif L.get("mode") == "box" and not L.get("sell_pending") and L.get("exit") and L["exit"] <= str(today):
                out.append(_market_exit(db, s, lot, L, today, "박스 돌파 20거래일째 종가"))
    if str(today) >= s["start"] and phase == "close":
        for lot, L in s["lots"].items():
            if L.get("legacy") or L.get("mode") != "trend" or L.get("sell_pending"):
                continue
            if s.get("no_stop_until") and str(today) <= s["no_stop_until"]:
                continue      # 하따 구간엔 21일선 매도도 멈춤 (2026-10-15 사용자)
            c, e = _close_vs_ema21(L["code"], today)
            if c is None:
                continue
            if c > e:
                if not L.get("armed"):
                    L["armed"] = True
                L.pop("exit_next", None)
            elif L.get("armed") and not L.get("exit_next"):
                L["exit_next"] = "21일선 아래 마감 → 다음 날 시초가"
                out.append(f"▼ {L['name']} 종가 {c:,.0f} < 21일선 {e:,.0f} → 내일 아침 시초가에 자동 매도\n"
                           f"· 오늘 장 후(넥스트레이드 ~20:00 · 시간외 단일가 16:00~18:00)에 직접 정리해도 됩니다 — 팔면 내일 자동 매도는 안 나갑니다\n"
                           f"· 계속 들고 싶으면 오늘 /스톱끄기")
    # 체결 확인 (내 손절 주문이 체결됐으면 알림)
    if str(today) >= s["start"] and phase in ("intraday", "close", "retry") and s["orders"].get(str(today)):
        try:
            hist = {str(x.get("oder_no")): x for x in M.orders_today(today.strftime("%Y%m%d"), "1")}
            for o in s["orders"].get(str(today), []):
                h = hist.get(str(o.get("order_no")))
                key = f"{today}|{o.get('order_no')}"
                if h and float(h.get("total_cntg_qty") or 0) > 0 and key not in s["notified"]:
                    s["notified"].append(key)
                    out.append(f"🔔 {'매도' if o.get('market') else '손절'} 체결: {o['name']} {int(float(h['total_cntg_qty']))}주 @ {float(h.get('cntg_unpr') or 0):,.0f}"
                               + (f" ({o['market']})" if o.get("market") else ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("스톱 체결 확인 실패: %s", type(exc).__name__)
    _save(db, s)
    out = [m for m in out if m]
    if out and phase != "baseline":
        head = {"morning": "🛑 오늘 손절 주문 (메리츠 스톱지정가)", "retry": "🛑 손절 주문 다시 걸기", "intraday": "🛑 손절 주문",
                "close": "🛑 장 마감 · 내일 아침 손절 주문 걸 것", "late": "🛑 시간외 · 내일 아침 손절 주문 걸 것",
                "preclose": "▼ 정해진 날 종가 매도 (반등 모드·바닥 모으기·박스 돌파)"}[phase]
        _tell(db, head + "\n" + "\n".join(out) + ("" if s["on"] else "\n(지금 꺼져 있음 — /스톱켜기)"))
    return " / ".join(out) or "변화 없음"


def status(db: Session) -> str:
    s = _st(db)
    today = str(_now().date())
    od = [o for o in s["orders"].get(today, []) if o["ok"] and not o.get("done")]
    lines = [f"손절 자동 주문: {'켜짐' if s['on'] else '꺼짐'} · {s['start']}부터 새로 산 것만 · 지정가 = 손절가 −1%"]
    if s.get("no_stop_until") and today <= s["no_stop_until"]:
        lines.append(f"⏸ 하따 구간: {s['no_stop_until'][5:]}까지 손절 주문·21일선 매도 안 함 (반등 종목 정해진 날 매도는 그대로)")
    for L in s["lots"].values():
        tail = "" if L.get("legacy") else (f" · 박스 돌파 · {str(L.get('exit'))[5:]} 종가 매도" if L.get("mode") == "box"
                                            else f" · 바닥 모으기 · {str(L.get('exit'))[5:]} 종가 매도" if L.get("mode") == "bottom"
                                            else " · 5거래일째 종가 매도 " + str(_nth_trading_day_after(date.fromisoformat(L["buy"]), 5))[5:] if L.get("mode") == "crash"
                                            else " · 21일선 이탈 매도 " + ("대기 중" if L.get("armed") else "(21일선 위 마감 뒤부터)"))
        lines.append((f"· {L['name']} {L['qty']}주 · 손절 {L['stop']:,} ({L['src']})" if L.get("stop") else f"· {L['name']} {L['qty']}주 · 손절가 없음")
                     + tail + (f" · ▼ {L['exit_next']}" if L.get("exit_next") else ""))
    if not s["lots"]:
        lines.append("· 대상 없음 (새로 산 종목이 생기면 자동으로)")
    lines.append(f"오늘 걸린 주문 {len(od)}건" + ("" if not od else ": " + ", ".join(f"{o['name']} {o['trigger']:,}" for o in od)))
    lines.append("/스톱끄기 · /스톱켜기")
    return "\n".join(lines)


def set_on(db: Session, on: bool) -> str:
    s = _st(db); s["on"] = on; _save(db, s)
    if not on:
        from backend.services import meritz as M  # noqa: PLC0415
        today = _now().date(); n = 0
        for o in s["orders"].get(str(today), []):
            if o["ok"] and not o.get("done") and o.get("order_no"):
                if M.cancel(o["code"], o["order_no"], o["qty"], o["trigger"], o["limit"])["ok"]:
                    o["done"] = "취소"; n += 1
        _save(db, s)
        return f"손절 자동 주문을 껐습니다. 오늘 걸려 있던 주문 {n}건 취소. 다시 켜려면 /스톱켜기"
    return "손절 자동 주문을 켰습니다. 다음 5분 확인 때부터 다시 겁니다."
