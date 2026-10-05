"""텔레그램 봇 알림 (2026-10-05). 토큰은 .env TELEGRAM_BOT_TOKEN 에만 둔다 — 코드·로그에 쓰지 않는다.

- 봇에 /start 를 보낸 대화방이 알림을 받는다 (settings 'telegram_chats'). /stop 으로 해제.
- 장 마감 요약: 15:41 수집이 끝나면 종베 후보(양봉·🕯 밑꼬리 도지)·🤖 Claude 선택·뜨는 섹터를 보낸다.
- 가격 알림: /알림 종목 가격 → 장중(09:00~15:30) 현재가가 그 가격 이상이면 하루 한 번 알림, 15:15에 '종가 조건' 점검.
- /후보, /체크 종목, /알림목록, /알림삭제 종목, /도움
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import Setting, Stock
from backend.utils.logger import get_logger

logger = get_logger(__name__)
MAX_CHATS = 5
HELP = ("주식 레이더 봇 명령\n"
        "/후보 — 오늘 종베 후보 요약\n"
        "/체크 종목명 — 시세·섹터·경고·실적\n"
        "/알림 종목명 가격 — 현재가가 그 가격 이상이면 알림 (예: /알림 PS일렉트로닉스 9420)\n"
        "/알림목록 · /알림삭제 종목명\n"
        "/관심 — 관심 종목 점검 지금 받기 (평일 15:40 자동)\n"
        "/stop — 알림 끄기")


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _api(method: str, **params) -> dict:
    tok = _token()
    if not tok:
        return {}
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", json=params, timeout=15)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("텔레그램 %s 실패: %s", method, type(exc).__name__)
        return {}


def _get(db: Session, key: str, default):
    row = db.scalar(select(Setting).where(Setting.key == key))
    try:
        return json.loads(row.value) if row else default
    except ValueError:
        return default


def _put(db: Session, key: str, value) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    v = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=v))
    else:
        row.value = v
    db.commit()


def send(db: Session, msg: str, chat_id: int | str | None = None) -> None:
    targets = [chat_id] if chat_id is not None else list(_get(db, "telegram_chats", {}).keys())
    for c in targets:
        for i in range(0, len(msg), 3900):      # 텔레그램 한 메시지 4096자 제한
            _api("sendMessage", chat_id=c, text=msg[i:i + 3900], disable_web_page_preview=True)


SITE = "http://20.196.212.146"


ME = "감사하모니카"      # 사용자 본인 — 본인이 쓴 글·댓글은 알리지 않는다 (2026-10-05 "내꺼는 빼고 우라늄이 뭐 달았을 때만")


def notify_async(msg: str, author: str = "") -> None:
    """요청 처리를 늦추지 않게 별도 스레드로 보낸다 (종목토론·건의사항 새 글·댓글). 본인이 쓴 건 보내지 않는다."""
    import threading  # noqa: PLC0415
    if (author or "").strip() == ME:
        return

    def _run():
        from backend.db.database import SessionLocal  # noqa: PLC0415
        db = SessionLocal()
        try:
            send(db, msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("텔레그램 알림 실패: %s", type(exc).__name__)
        finally:
            db.close()
    if _token():
        threading.Thread(target=_run, daemon=True).start()


def _cut(s: str, n: int = 120) -> str:
    s = (s or "").strip().replace(chr(10), " ")
    return s if len(s) <= n else s[:n] + "…"


# ── 장 마감 요약 ────────────────────────────────────────────────
def jongbe_summary(db: Session) -> str:
    from backend.screener.jongbe import scan  # noqa: PLC0415
    d = scan(db)
    m = d.get("market") or {}
    lines = [f"📊 {d['trading_date']} 종베 후보", f"시장 {m.get('state', '-')} · {'종베 가능' if d.get('market_ok') else '쉬기'}"]
    fams = d.get("families") or []
    lines.append("뜨는 섹터: " + ", ".join(f"{f['family']}{' 💰' if f.get('money') else ''}" for f in fams[:3]))
    mv = d.get("movers") or []
    if mv:
        lines.append("움직이기 시작: " + ", ".join(x["family"] for x in mv[:4]))
    names = {x["code"]: x for x in d["items"]}
    ai = [names[c] for c in d.get("ai_picks", []) if c in names]
    if ai:
        lines.append("\n🤖 Claude 선택")
        for x in ai:
            lines.append(f"· {x['name']} {x['close']:,}원 ({x['change_pct']:+}%) {x.get('kind', '양봉')} · 시총 {round((x.get('market_cap') or 0) / 1e8):,}억")
    safe = [x for x in d["items"] if x["grade"] == "A" and (x.get("gap20_pct") or 0) < 20 and x["change_pct"] < 12
            and (x.get("market_cap") or 0) >= 1e11 and not any(t in ("투자경고", "투자위험") for t in x.get("flags", []))]
    doji = [x for x in safe if x.get("kind") == "밑꼬리 도지"]
    bull = [x for x in safe if x.get("kind") != "밑꼬리 도지"]
    if bull:
        lines.append(f"\nA등급 양봉 {len(bull)}개 (급등·과열·1천억 미만·경고 제외)")
        lines += [f"· {x['name']} {x['change_pct']:+}% 거래 {x['tv_x']}배 윗꼬리 {x['upper_pct']}%" for x in bull[:10]]
    if doji:
        lines.append(f"\n🕯 밑꼬리 도지 {len(doji)}개")
        lines += [f"· {x['name']} 밑꼬리 {x.get('low_wick_pct')}% · 전날 +{x.get('prev_chg')}%" for x in doji[:8]]
    lines.append("\n파는 법: 다음 날 +2% 미만 전부 정리 / 이상이면 30%·30% / 나머지 최고 종가 -15%")
    return "\n".join(lines)


def summary_pending(db: Session) -> bool:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    return (latest == datetime.now(ZoneInfo("Asia/Seoul")).date() and bool(_get(db, "telegram_chats", {}))
            and _get(db, "telegram_last_summary", "") != latest.isoformat())


def send_summary_once(db: Session) -> bool:
    """오늘 데이터가 들어왔고 아직 안 보냈으면 요약을 보낸다."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest != datetime.now(ZoneInfo("Asia/Seoul")).date() or _get(db, "telegram_last_summary", "") == latest.isoformat():
        return False
    if not _get(db, "telegram_chats", {}):
        return False
    send(db, jongbe_summary(db))
    _put(db, "telegram_last_summary", latest.isoformat())
    return True


# ── 가격 알림 ──────────────────────────────────────────────────
def _live_price(code: str) -> float | None:
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    c = fetch_candles(code, "1m", 1)
    try:
        return float(c[-1]["closePrice"]) if c else None
    except (KeyError, ValueError, TypeError):
        return None


def check_alerts(db: Session, close_check: bool = False) -> None:
    watches = _get(db, "telegram_watch", [])
    if not watches:
        return
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    changed = False
    for w in watches:
        p = _live_price(w["code"])
        if p is None:
            continue
        hit = p >= w["price"]
        if close_check:
            send(db, f"⏰ 종가 점검 {w['name']}: 현재 {p:,.0f}원 · 조건 {w['price']:,}원 {'위 ✅ (종가까지 유지되면 조건 충족)' if hit else '아래'}", w["chat"])
        elif hit and w.get("sent") != today:
            send(db, f"🔔 {w['name']} {p:,.0f}원 — 조건 {w['price']:,}원 돌파 (장중, 종가 확인 필요)", w["chat"])
            w["sent"] = today
            changed = True
        time.sleep(0.2)
    if changed:
        _put(db, "telegram_watch", watches)


def _find(db: Session, q: str):
    return db.execute(select(Stock.code, Stock.name).where((Stock.code == q) | (Stock.name == q))).first() or \
        db.execute(select(Stock.code, Stock.name).where(Stock.name.like(f"%{q}%")).limit(1)).first()


def _check_text(db: Session, q: str) -> str:
    row = _find(db, q)
    if not row:
        return f"'{q}' 종목을 못 찾았습니다."
    from backend.screener.rotation import family_members  # noqa: PLC0415
    from backend.screener.support_setups import _fundamentals  # noqa: PLC0415
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    px = db.execute(text("select trading_date, close_price, change_pct, trading_value from spot_daily_prices where stock_code=:c "
                         "order by trading_date desc limit 21"), {"c": row.code}).all()
    lines = [f"🔎 {row.name} ({row.code})"]
    if px:
        d0 = px[0]
        avg = sum(float(x[3] or 0) for x in px[1:]) / max(len(px) - 1, 1)
        ma20 = sum(float(x[1]) for x in px[:20]) / min(len(px), 20)
        lines.append(f"{d0[0]} 종가 {d0[1]:,.0f}원 ({float(d0[2]):+.1f}%) · 거래 평소 {float(d0[3] or 0) / avg:.1f}배 · 20일선 이격 {(float(d0[1]) / ma20 - 1) * 100:+.1f}%")
    live = _live_price(row.code)
    if live:
        lines.append(f"지금 {live:,.0f}원")
    fams = [f for f, m in family_members(db).items() if row.code in m]
    lines.append("섹터: " + (", ".join(fams[:3]) or "없음"))
    f = _fundamentals().get(row.code)
    if f:
        lines.append(f"실적 {f['period']}: 영업익 {f['op_yoy'] if f['op_yoy'] is not None else '-'}% · 매출 {f['rev_yoy'] if f['rev_yoy'] is not None else '-'}% · 이익률 {f['margin'] if f['margin'] is not None else '-'}%"
                     + (" · ⚠ 적자" if f["loss"] else ""))
    fl = flags_get([row.code]).get(row.code, {}).get("flags", [])
    if fl:
        lines.append("⚠ " + ", ".join(fl))
    return "\n".join(lines)


def poll(db: Session) -> None:
    """새 메시지 처리 (30초마다)."""
    if not _token():
        return
    off = _get(db, "telegram_offset", 0)
    res = _api("getUpdates", offset=off, timeout=0)
    ups = res.get("result") or []
    if not ups:
        return
    chats = _get(db, "telegram_chats", {})
    for u in ups:
        off = max(off, u["update_id"] + 1)
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        cid, txt = str(chat.get("id", "")), (msg.get("text") or "").strip()
        if not cid or not txt:
            continue
        who = chat.get("first_name") or chat.get("username") or cid
        if txt.startswith("/start"):
            if cid not in chats and len(chats) >= MAX_CHATS:
                send(db, "등록 인원이 꽉 찼습니다.", cid); continue
            new = cid not in chats
            chats[cid] = who
            _put(db, "telegram_chats", chats)
            send(db, "✅ 알림 등록 완료. 장 마감 뒤 종베 후보 요약을 보내 드립니다.\n\n" + HELP, cid)
            if new:
                for other in chats:
                    if other != cid:
                        send(db, f"ℹ️ 새 대화방이 알림에 등록됐습니다: {who}", other)
            continue
        if cid not in chats:
            send(db, "먼저 /start 를 보내 주세요.", cid); continue
        if txt.startswith("/stop"):
            chats.pop(cid, None); _put(db, "telegram_chats", chats)
            send(db, "알림을 껐습니다. 다시 받으려면 /start", cid)
        elif txt.startswith("/관심"):
            from backend.services.watchlist import send_report  # noqa: PLC0415
            send_report(db, force=True, chat_id=cid)
        elif txt.startswith("/후보"):
            send(db, jongbe_summary(db), cid)
        elif txt.startswith("/체크"):
            send(db, _check_text(db, txt.split(maxsplit=1)[1].strip()) if " " in txt else "예: /체크 가온전선", cid)
        elif txt.startswith("/알림목록"):
            ws = [w for w in _get(db, "telegram_watch", []) if w["chat"] == cid]
            send(db, "\n".join(f"· {w['name']} {w['price']:,}원 이상" for w in ws) or "걸어 둔 알림이 없습니다.", cid)
        elif txt.startswith("/알림삭제"):
            q = txt.split(maxsplit=1)[1].strip() if " " in txt else ""
            ws = _get(db, "telegram_watch", [])
            keep = [w for w in ws if not (w["chat"] == cid and (w["name"] == q or w["code"] == q))]
            _put(db, "telegram_watch", keep)
            send(db, f"{len(ws) - len(keep)}개 지웠습니다.", cid)
        elif txt.startswith("/알림"):
            parts = txt.split()
            if len(parts) < 3:
                send(db, "예: /알림 PS일렉트로닉스 9420", cid); continue
            row = _find(db, " ".join(parts[1:-1]))
            try:
                price = int(parts[-1].replace(",", "").replace("원", ""))
            except ValueError:
                row = None
            if not row:
                send(db, "종목이나 가격을 못 읽었습니다. 예: /알림 PS일렉트로닉스 9420", cid); continue
            ws = [w for w in _get(db, "telegram_watch", []) if not (w["chat"] == cid and w["code"] == row.code)]
            ws.append({"chat": cid, "code": row.code, "name": row.name, "price": price, "sent": ""})
            _put(db, "telegram_watch", ws)
            send(db, f"✅ {row.name} {price:,}원 이상이면 알려 드립니다 (장중 2분마다, 15:15 종가 점검).", cid)
        else:
            send(db, HELP, cid)
    _put(db, "telegram_offset", off)


def is_market_time(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 30)
