"""초대 사용자 '내 계좌' — 사장님이 허용한 사람만 (2026-10-13 사용자: "허용한 유저만 쓸 수 있고 알 수 있게").

- 계정: settings 'portal_users' = {이름: {pin(salt$pbkdf2), on, created, chat(텔레그램 대화방), code(연결 코드)}}. 사장님(관리 탭)만 만들고 끔.
- 키: settings 'portal_keys:이름' = Fernet 암호문 {broker: meritz|toss, app_key, app_secret, account_seq}. 암호 키 = .env PORTAL_SECRET.
  화면·로그·텔레그램에 키를 다시 보여 주지 않음(끝 4자리만).
- 자동 주문은 **손절(매도)만**. 다른 사람 계좌에 자동 매수는 절대 만들지 않는다(사용자 원칙 10/13).
  손절가 = 그 사람이 정한 선(종목별) 또는 산 날 저가 −1%. 연결한 날 이전부터 들고 있던 건 기준 잔고라 안 건드림(원하면 화면에서 손절선을 넣으면 대상).
  메리츠: 스톱지정가(당일) → 매일 08:50 다시 · 지정가 = 손절가 −1%. 토스: 조건주문(시장가 매도, 1년 만료) → 한 번 걸면 유지.
- 21일선 매도(2026-10-13 사용자 "21일선 매도 넣어야지", 사장님 계좌와 같은 규칙, 화면에서 끌 수 있음 · 기본 켜짐):
  연결한 뒤 산 종목이 21일선(지수이평) 위로 한 번 마감한 뒤부터, 21일선 아래로 마감하면(15:40 확인) 다음 날 08:50 시초가 시장가 매도.
  메리츠 = 시장가 매도(08:50 → 시초가) · 토스 = 조건주문 취소 후 OPG 시장가. 09:01에 한 번 더(실패했을 때만).
- 알림: 그 사람 텔레그램 방(/연결 코드)으로만. 사장님 방에는 안 보냄.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
MAX_ORDERS_DAY = 40      # 2026-10-13: 15였는데 아침에 이미 12건이라 새로 산 4번째부터 손절이 안 걸릴 뻔 — 폭주 방지용 상한은 남김
_FAILS: dict = {}


def _get(db, k, d):
    from backend.services.telegram import _get as g  # noqa: PLC0415
    return g(db, k, d)


def _put(db, k, v):
    from backend.services.telegram import _put as p  # noqa: PLC0415
    p(db, k, v)


def _now() -> datetime:
    return datetime.now(KST)


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


# ── 계정 ──────────────────────────────────────────────────────
def users(db: Session) -> dict:
    return _get(db, "portal_users", {}) or {}


def auth(db: Session, name: str, pin: str) -> bool:
    name, pin = (name or "").strip()[:20], (pin or "").strip()
    f = _FAILS.get(name)
    if f and f[0] >= 5 and time.time() < f[1]:
        return False                      # 5번 틀리면 15분 잠금
    u = users(db).get(name)
    ok = bool(u and u.get("on") and "$" in (u.get("pin") or "") and secrets.compare_digest(_hash(pin, u["pin"].split("$")[0]), u["pin"].split("$")[1]))
    if ok:
        _FAILS.pop(name, None)
    else:
        n = (f[0] if f else 0) + 1
        _FAILS[name] = (n, time.time() + 900)
    return ok


def admin(db: Session, action: str, name: str, pin: str | None = None) -> dict:
    name = (name or "").strip()
    us = users(db)
    if action == "create":
        if not re.fullmatch(r"[0-9A-Za-z가-힣_]{2,20}", name) or name.lower() in ("junp", "admin"):
            return {"ok": False, "msg": "이름은 한글·영문·숫자 2~20자"}
        if name in us:
            return {"ok": False, "msg": "이미 있는 이름"}
        if not pin or len(pin) < 6:
            return {"ok": False, "msg": "임시 비밀번호는 6자 이상"}
        salt = secrets.token_hex(8)
        us[name] = {"pin": f"{salt}${_hash(pin, salt)}", "on": True, "created": _now().strftime("%Y-%m-%d"), "chat": None,
                    "code": f"{secrets.randbelow(900000) + 100000}", "temp": True}
    elif name not in us:
        return {"ok": False, "msg": "없는 이름"}
    elif action == "reset":
        if not pin or len(pin) < 6:
            return {"ok": False, "msg": "새 비밀번호는 6자 이상"}
        salt = secrets.token_hex(8); us[name]["pin"] = f"{salt}${_hash(pin, salt)}"; us[name]["temp"] = True
    elif action in ("on", "off"):
        us[name]["on"] = action == "on"
        if action == "off":
            st = _state(db, name); st["on"] = False; _save(db, name, st)
    elif action == "delete":
        cancel_all(db, name)
        us.pop(name)
        db.execute(text("delete from settings where key in (:a, :b)"), {"a": f"portal_keys:{name}", "b": f"pt_state:{name}"}); db.commit()
    else:
        return {"ok": False, "msg": "알 수 없는 작업"}
    _put(db, "portal_users", us)
    return {"ok": True, "msg": {"create": "만들었습니다", "reset": "비밀번호를 바꿨습니다", "on": "켰습니다", "off": "껐습니다(자동 주문도 멈춤)",
                                "delete": "지웠습니다(키·기록도 삭제)"}[action]}


def change_pin(db: Session, name: str, new_pin: str) -> dict:
    """본인이 비밀번호 바꾸기 (2026-10-13 사용자: '임시 비번이니까 본인이 바꿀 수 있게'). 로그인한 상태에서만 부름."""
    new_pin = (new_pin or "").strip()
    if len(new_pin) < 8:
        return {"ok": False, "msg": "새 비밀번호는 8자 이상으로 해 주세요"}
    us = users(db)
    if name not in us:
        return {"ok": False, "msg": "없는 이름"}
    salt = secrets.token_hex(8)
    us[name]["pin"] = f"{salt}${_hash(new_pin, salt)}"; us[name]["temp"] = False
    _put(db, "portal_users", us)
    return {"ok": True, "msg": "비밀번호를 바꿨습니다"}


def admin_list(db: Session) -> list[dict]:
    out = []
    for name, u in users(db).items():
        k = keys(db, name)
        st = _state(db, name)
        out.append({"name": name, "on": u.get("on"), "created": u.get("created"), "chat": bool(u.get("chat")), "code": u.get("code"),
                    "broker": k.get("broker") if k else None, "stop_on": st.get("on"), "lots": len(st.get("lots", {})),
                    "last": st.get("last_run")})
    return out


# ── 키 (암호화) ───────────────────────────────────────────────
def _fernet():
    from cryptography.fernet import Fernet  # noqa: PLC0415
    k = os.getenv("PORTAL_SECRET", "").strip()
    if not k:
        raise RuntimeError("PORTAL_SECRET 없음")
    return Fernet(k.encode())


def keys(db: Session, name: str) -> dict | None:
    raw = _get(db, f"portal_keys:{name}", None)
    if not raw:
        return None
    try:
        return json.loads(_fernet().decrypt(raw.encode()).decode())
    except Exception:  # noqa: BLE001
        return None


def client(db: Session, name: str):
    k = keys(db, name)
    if not k:
        return None
    if k["broker"] == "meritz":
        from backend.services.meritz import Client  # noqa: PLC0415
        return Client(k["app_key"], k["app_secret"], f"pt_{name}")
    from backend.services.toss_trade import TossClient  # noqa: PLC0415
    return TossClient(k["app_key"], k["app_secret"], f"pt_{name}", k.get("account_seq"))


def save_keys(db: Session, name: str, broker: str, app_key: str, app_secret: str) -> dict:
    if broker not in ("meritz", "toss") or len((app_key or "").strip()) < 8 or len((app_secret or "").strip()) < 8:
        return {"ok": False, "msg": "증권사와 키 두 칸을 확인해 주세요"}
    k = {"broker": broker, "app_key": app_key.strip(), "app_secret": app_secret.strip(), "account_seq": None}
    # 저장 전에 실제로 잔고가 읽히는지 확인 (주문은 안 냄)
    try:
        if broker == "meritz":
            from backend.services.meritz import Client  # noqa: PLC0415
            c = Client(k["app_key"], k["app_secret"], f"pt_{name}")
            hs = c.holdings()
        else:
            from backend.services.toss_trade import TossClient  # noqa: PLC0415
            c = TossClient(k["app_key"], k["app_secret"], f"pt_{name}")
            k["account_seq"] = c.first_account(); c.account_seq = k["account_seq"]
            hs = c.holdings()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        for s in (app_key, app_secret):
            msg = msg.replace(s or "§", "***")
        return {"ok": False, "msg": f"연결 확인 실패: {msg[:160]}"}
    _put(db, f"portal_keys:{name}", _fernet().encrypt(json.dumps(k).encode()).decode())
    st = _state(db, name)
    st["baseline"] = {_lot(h): h["qty"] for h in hs}       # 지금 들고 있는 건 기준(자동 주문 안 함)
    st["lots"], st["start"] = {}, _now().strftime("%Y-%m-%d")
    _save(db, name, st)
    return {"ok": True, "msg": f"연결됐습니다 · 보유 {len(hs)}종목 확인 (지금 들고 있는 건 손절선을 넣어야 대상)", "n": len(hs)}


def delete_keys(db: Session, name: str) -> dict:
    cancel_all(db, name)
    db.execute(text("delete from settings where key = :k"), {"k": f"portal_keys:{name}"}); db.commit()
    st = _state(db, name); st["on"] = False; _save(db, name, st)
    return {"ok": True, "msg": "키를 지웠습니다 (걸려 있던 자동 손절 주문도 취소)"}


# ── 상태 ──────────────────────────────────────────────────────
def _state(db: Session, name: str) -> dict:
    s = _get(db, f"pt_state:{name}", None) or {}
    for k, v in (("on", False), ("start", None), ("baseline", {}), ("lots", {}), ("orders", {}), ("lines", {}), ("exclude", []), ("log", []), ("notified", []), ("exit21", True)):
        s.setdefault(k, v)
    return s


def _save(db: Session, name: str, s: dict) -> None:
    s["orders"] = dict(sorted(s["orders"].items())[-10:])
    s["log"] = s["log"][-40:]; s["notified"] = s["notified"][-200:]
    _put(db, f"pt_state:{name}", s)


def _lot(h: dict) -> str:
    return f"{h['code']}|{'신용' if h.get('credit') else '현금'}|{h.get('loan_date', '')}"


def _tell(db: Session, name: str, s: dict, msg: str) -> None:
    s["log"].append(f"{_now().strftime('%m/%d %H:%M')} {msg}")
    chat = (users(db).get(name) or {}).get("chat")
    if chat:
        try:
            from backend.services.telegram import send  # noqa: PLC0415
            send(db, msg, chat_id=chat)
        except Exception:  # noqa: BLE001
            pass


def _stop_for(db: Session, s: dict, code: str, buy: date, today: date) -> tuple[int | None, str, bool]:
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    line = (s.get("lines") or {}).get(code)
    if line:
        return int(line), "내가 정한 손절선", True
    if buy < today:
        low = db.execute(text("select low_price from spot_daily_prices where stock_code = :c and trading_date = :d"), {"c": code, "d": buy}).scalar()
        final = True
    else:
        try:      # 산 날: 정규장 저가 (토스 일봉은 장 후 넥스트레이드 저가가 섞임, 2026-10-13)
            from backend.services.naver_live import krx_day  # noqa: PLC0415
            k = krx_day(code)
            low = float(k["low"]) if k and k["date"] == str(today) else None
        except Exception:  # noqa: BLE001
            low = None
        final = _now().hour * 100 + _now().minute >= 1530
    if not low:
        return None, "산 날 저가를 못 받음", False
    return int(tick_floor(float(low) * 0.99)), "산 날 저가 −1%", final


def _sync(db: Session, s: dict, hs: list[dict], today: date) -> list[str]:
    from backend.services.stop_orders import _buy_date  # noqa: PLC0415
    msgs, now_q, meta = [], {}, {}
    for h in hs:
        now_q[_lot(h)] = now_q.get(_lot(h), 0) + h["qty"]; meta[_lot(h)] = h
    excl = set(s.get("exclude") or [])
    for lot, q in now_q.items():
        code = lot.split("|")[0]
        base = 0 if code in (s.get("lines") or {}) else s["baseline"].get(lot, 0)     # 손절선을 직접 넣은 종목은 예전부터 들고 있던 것도 대상
        extra = q - base
        L = s["lots"].get(lot)
        if code in excl:
            if L:
                s["lots"].pop(lot); msgs.append(f"✅ {L['name']}: 자동 손절에서 뺌")
            continue
        if extra > 0 and not L:
            h = meta[lot]; buy = _buy_date(h, today)
            stop, src, final = _stop_for(db, s, code, buy, today)
            s["lots"][lot] = {"code": code, "name": h["name"], "credit": h.get("credit", False), "loan_date": h.get("loan_date", ""),
                              "qty": extra, "buy": str(buy), "stop": stop, "src": src, "final": final}
            msgs.append(f"🆕 자동 손절 대상: {h['name']} {extra}주 · 손절가 " + (f"{stop:,} ({src})" if stop else f"없음 — {src}"))
        elif L and extra != L["qty"]:
            if extra <= 0:
                s["lots"].pop(lot); msgs.append(f"✅ {L['name']} 정리됨 — 자동 손절 대상에서 뺌")
            else:
                L["qty"] = extra
        if q < s["baseline"].get(lot, 0):
            s["baseline"][lot] = q
    for lot in list(s["lots"]):
        if lot not in now_q:
            msgs.append(f"✅ {s['lots'][lot]['name']} 잔고에서 사라짐 (매도·손절)"); s["lots"].pop(lot)
    return msgs


def _market_exit(c, broker: str, s: dict, lot: str, L: dict, today: date, phase: str, why: str) -> str:
    """걸려 있는 손절 주문을 먼저 취소하고 시장가 매도 (08:50 = 시초가)."""
    day = s["orders"].setdefault(str(today), [])
    if broker == "toss":
        o = L.get("toss_order")
        if o:
            if not c.stop_cancel(o["id"]).get("ok"):
                return f"⚠ {L['name']} {why} — 걸린 조건주문 취소 실패, 직접 팔아 주세요"
            L.pop("toss_order")
        r = c.market_sell(L["code"], L["qty"], opening=(phase == "morning"), client_id=f"x21-{L['code']}-{today:%Y%m%d}-{phase}")
    else:
        live = [x for x in day if x["lot"] == lot and x["ok"] and not x.get("done") and not x.get("market")]
        if live:
            o = live[-1]
            if not c.cancel(L["code"], o["order_no"], o["qty"], o["trigger"], o["limit"]).get("ok"):
                return f"⚠ {L['name']} {why} — 걸린 손절 주문 취소 실패, 직접 팔아 주세요"
            o["done"] = "취소"
        r = c.market_sell(L["code"], L["qty"], L.get("credit", False), L.get("loan_date", ""))
    day.append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": 0, "limit": 0,
                "order_no": r["order_no"], "ok": r["ok"], "at": _now().strftime("%H:%M"), "market": why})
    if r["ok"]:
        L["sell_pending"] = str(today)
        return f"▼ {L['name']} {L['qty']}주 {why} — 시장가 매도 주문 넣음"
    return f"⚠ {L['name']} {why} 시장가 매도 실패 — {r['warn'] or r['msg']} (직접 팔아 주세요)"


def run(db: Session, name: str, phase: str) -> str:
    """phase: morning · retry · intraday · close. 손절만."""
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    today = _now().date()
    if not is_trading_day(today):
        return "장 없는 날"
    k = keys(db, name)
    c = client(db, name)
    if not c:
        return "키 없음"
    s = _state(db, name)
    s["last_run"] = _now().strftime("%m/%d %H:%M")
    try:
        hs = c.holdings()
    except Exception as exc:  # noqa: BLE001
        # 연결이 안 되면 손절 주문이 조용히 안 걸린 채 지나감 → 연속 2번 실패하면 하루 한 번 알림 (2026-10-13)
        s["fails"] = s.get("fails", 0) + 1
        if s["on"] and s["fails"] >= 2 and s.get("fail_told") != str(today):   # 자동 손절 켠 사람만
            s["fail_told"] = str(today)
            _tell(db, name, s, f"⚠ 증권사 연결이 안 됩니다 — 오늘 손절 주문이 안 걸려 있을 수 있습니다.\n"
                               f"키 만료·허용 IP(20.196.212.146)를 확인하고, 사이트 '내 계좌'에서 키를 다시 넣어 주세요.\n({str(exc)[:80]})")
        _save(db, name, s)
        return f"잔고 실패 {str(exc)[:80]}"
    if s.get("fail_told") == str(today):
        _tell(db, name, s, "✅ 증권사 연결이 다시 됩니다 — 자동 손절 정상")
        s["fail_told"] = f"{today} 복구"
    s["fails"] = 0
    out = _sync(db, s, hs, today)
    if s["on"] and phase in ("morning", "retry", "intraday"):
        day = s["orders"].setdefault(str(today), [])
        for lot, L in s["lots"].items():
            if L.get("sell_pending") == str(today):
                continue
            if L.get("exit_next"):
                if not s.get("exit21", True):
                    L.pop("exit_next")                      # 21일선 매도를 껐으면 손절만
                elif phase in ("morning", "retry"):
                    tried = [x for x in day if x["lot"] == lot and x.get("market")]
                    if not any(x["ok"] for x in tried) and len(tried) < 2:     # 08:50 실패하면 09:01 한 번 더
                        out.append(_market_exit(c, k["broker"], s, lot, L, today, phase, L["exit_next"]))
                    continue
                else:
                    continue                                 # 장중: 아침 매도가 실패한 것 — 손절 주문도 안 겹치게 둔다(알림으로 직접)
            if phase in ("morning", "retry") or (s.get("lines") or {}).get(L["code"]):
                stop, src, final = _stop_for(db, s, L["code"], date.fromisoformat(L["buy"]), today)
                if stop:
                    L.update(stop=stop, src=src, final=final)
            if not L.get("stop"):
                continue
            if k["broker"] == "toss":
                o = L.get("toss_order")
                if o and (o.get("trigger") != L["stop"] or o.get("qty") != L["qty"]):
                    if c.stop_cancel(o["id"]).get("ok"):
                        out.append(f"↺ {L['name']} 손절가 바뀜 {o['trigger']:,} → {L['stop']:,}"); L.pop("toss_order")
                    else:
                        continue
                if not L.get("toss_order"):
                    expire = (today + timedelta(days=360)).isoformat()
                    r = c.stop_create(L["code"], L["qty"], L["stop"], expire)
                    if r["ok"]:
                        L["toss_order"] = {"id": r["order_no"], "trigger": L["stop"], "qty": L["qty"]}
                        out.append(f"🛑 {L['name']} {L['qty']}주 · 감시가 {L['stop']:,} 닿으면 시장가 매도 (토스 조건주문, {expire[5:]}까지)")
                    else:
                        out.append(f"⚠ {L['name']} 조건주문 실패 — {r['msg']} (직접 걸어 주세요)")
                continue
            # 메리츠: 당일 스톱지정가 — 매일 다시
            mine = [x for x in day if x["lot"] == lot and not x.get("market")]
            live = [x for x in mine if x["ok"] and not x.get("done")]
            if live and (live[-1]["trigger"] != L["stop"] or live[-1]["qty"] != L["qty"]):
                if c.cancel(L["code"], live[-1]["order_no"], live[-1]["qty"], live[-1]["trigger"], live[-1]["limit"]).get("ok"):
                    live[-1]["done"] = "취소"; live = []
                else:
                    continue
            if live or len([x for x in mine if not x["ok"]]) >= 2 or len(day) >= MAX_ORDERS_DAY:
                continue
            lim = int(tick_floor(L["stop"] * 0.99))
            r = c.stop_sell(L["code"], L["qty"], L["stop"], lim, L.get("credit", False), L.get("loan_date", ""))
            day.append({"lot": lot, "code": L["code"], "name": L["name"], "qty": L["qty"], "trigger": L["stop"], "limit": lim,
                        "order_no": r["order_no"], "ok": r["ok"], "at": _now().strftime("%H:%M")})
            out.append(f"🛑 {L['name']} {L['qty']}주 · 감시 {L['stop']:,} → 지정가 {lim:,}" if r["ok"] else f"⚠ {L['name']} 손절 주문 실패 — {r['warn'] or r['msg']}")
    if s["on"] and s.get("exit21", True) and phase == "close":
        from backend.services.stop_orders import _close_vs_ema21  # noqa: PLC0415
        for lot, L in s["lots"].items():
            if L.get("sell_pending") or L["buy"] < (s.get("start") or ""):
                continue                                     # 연결 전부터 들고 있던 것(손절선만 넣은 것)은 21일선 매도 안 함
            cl, e = _close_vs_ema21(L["code"], today)
            if cl is None:
                continue
            if cl > e:
                L["armed"] = True; L.pop("exit_next", None)
            elif L.get("armed") and not L.get("exit_next"):
                L["exit_next"] = "21일선 아래 마감 → 다음 날 시초가"
                out.append(f"▼ {L['name']} 종가 {cl:,.0f} < 21일선 {e:,.0f} → 내일 아침 시초가에 자동 매도\n"
                           f"· 오늘 장 후(넥스트레이드 ~20:00 · 시간외 단일가 16:00~18:00)에 직접 정리해도 됩니다 — 팔면 내일 자동 매도는 안 나갑니다\n"
                           f"· 계속 들고 싶으면 오늘 밤 사이트 '내 계좌'에서 21일선 매도를 꺼 주세요")
    if out:
        _tell(db, name, s, "\n".join(out))
    _save(db, name, s)
    return " / ".join(out) or "변화 없음"


def cancel_all(db: Session, name: str) -> int:
    k, c = keys(db, name), client(db, name)
    if not c:
        return 0
    s, n = _state(db, name), 0
    try:
        if k["broker"] == "toss":
            for L in s["lots"].values():
                if L.get("toss_order") and c.stop_cancel(L["toss_order"]["id"]).get("ok"):
                    L.pop("toss_order"); n += 1
        else:
            for o in s["orders"].get(str(_now().date()), []):
                if o["ok"] and not o.get("done") and c.cancel(o["code"], o["order_no"], o["qty"], o["trigger"], o["limit"]).get("ok"):
                    o["done"] = "취소"; n += 1
    except Exception:  # noqa: BLE001
        pass
    _save(db, name, s)
    return n


def run_all(db: Session, phase: str) -> None:
    for name, u in users(db).items():
        if not u.get("on"):
            continue
        try:
            logger.info("초대 사용자 손절(%s · %s): %s", name, phase, run(db, name, phase))
        except Exception as exc:  # noqa: BLE001
            logger.warning("초대 사용자 손절 실패 %s: %s", name, type(exc).__name__)


# ── 화면용 ───────────────────────────────────────────────────
_BOT: dict = {}


def _bot_name() -> str | None:
    if "v" not in _BOT:
        try:
            from backend.services.telegram import _api  # noqa: PLC0415
            _BOT["v"] = ((_api("getMe") or {}).get("result") or {}).get("username")
        except Exception:  # noqa: BLE001
            return None
    return _BOT.get("v")


def me(db: Session, name: str) -> dict:
    u = users(db).get(name) or {}
    k = keys(db, name)
    s = _state(db, name)
    today = str(_now().date())
    return {"name": name, "broker": k.get("broker") if k else None, "key_tail": (k["app_key"][-4:] if k else None),
            "stop_on": s.get("on"), "exit21": s.get("exit21", True), "start": s.get("start"), "chat": bool(u.get("chat")), "code": u.get("code"), "temp": bool(u.get("temp")),
            "lots": [{"code": L["code"], "name": L["name"], "qty": L["qty"], "stop": L.get("stop"), "src": L.get("src"),
                      "exit_next": L.get("exit_next"), "armed": L.get("armed"), "old": L["buy"] < (s.get("start") or ""),
                      "order": bool(L.get("toss_order")) or any(o["lot"] == lot and o["ok"] and not o.get("done") for o in s["orders"].get(today, []))}
                     for lot, L in s["lots"].items()],
            "lines": s.get("lines", {}), "exclude": s.get("exclude", []), "log": s.get("log", [])[-15:][::-1], "last": s.get("last_run"),
            "bot": _bot_name()}


def set_stop_on(db: Session, name: str, on: bool) -> dict:
    s = _state(db, name)
    if on and not keys(db, name):
        return {"ok": False, "msg": "먼저 증권사 키를 연결해 주세요"}
    s["on"] = on; _save(db, name, s)
    n = 0 if on else cancel_all(db, name)
    return {"ok": True, "msg": "자동 손절을 켰습니다 (다음 5분 확인부터)" if on else f"자동 손절을 껐습니다 · 걸려 있던 주문 {n}건 취소"}


def set_exit21(db: Session, name: str, on: bool) -> dict:
    s = _state(db, name)
    s["exit21"] = on
    if not on:
        for L in s["lots"].values():
            L.pop("exit_next", None)
    _save(db, name, s)
    return {"ok": True, "msg": "21일선 매도를 켰습니다 (오늘 15:40 마감 확인부터)" if on else "21일선 매도를 껐습니다 — 손절가 매도만 합니다"}


def set_line(db: Session, name: str, code: str, stop: float | None, exclude: bool | None = None) -> dict:
    code = re.sub(r"\D", "", code or "")[:6]
    if len(code) != 6:
        return {"ok": False, "msg": "종목코드 6자리"}
    s = _state(db, name)
    if stop:
        s["lines"][code] = int(stop)
    elif stop is not None:
        s["lines"].pop(code, None)
    if exclude is not None:
        ex = set(s["exclude"]); (ex.add if exclude else ex.discard)(code); s["exclude"] = sorted(ex)
    _save(db, name, s)
    return {"ok": True, "msg": "저장했습니다 (5분 안에 주문에 반영)"}


def link_chat(db: Session, code: str, chat_id) -> str | None:
    us = users(db)
    for name, u in us.items():
        if u.get("code") and u.get("code") == (code or "").strip():
            u["chat"] = str(chat_id); u["code"] = f"{secrets.randbelow(900000) + 100000}"     # 한 번 쓰면 새 코드
            _put(db, "portal_users", us)
            return name
    return None
