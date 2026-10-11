"""내 공간 (2026-10-11 사용자 "관리자 탭"): 로그인(매매 일지 비밀번호)한 junp만.
- 실전 기록: forward_log V1.1 가상 계좌(P·L·S·Z) 수익 곡선·보유·최근 거래
- 관심·보유 관리: settings user_watchlist (텔레그램 /관심 · tools/ask.py와 같은 목록), 보유 종목 손절선 = hold 줄
- 서버 상태: 백업 · 예약 작업 다음 실행 · 최근 작업 기록 · 최근 오류 (토큰·키는 지움)
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

ACCTS = {"P": "기본 (15:12 신호 · 종가 체결)", "L": "주도주 (소량)", "S": "보조 (다음 날 시가)", "Z": "비교: 모멘텀 돌파"}


def _names(db: Session, codes) -> dict:
    codes = list({c for c in codes if c})
    if not codes:
        return {}
    return dict(db.execute(text("select code, name from stocks where code = any(:c)"), {"c": codes}).all())


def _last_close(db: Session, codes) -> dict:
    codes = list({c for c in codes if c})
    if not codes:
        return {}
    return {c: float(px) for c, px in db.execute(text(
        "select distinct on (stock_code) stock_code, close_price from spot_daily_prices where stock_code = any(:c) order by stock_code, trading_date desc"),
        {"c": codes}).all()}


def forward(db: Session) -> dict:
    from backend.services.forward_log import STATE_KEY, VERSION, CONFIG  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    st = _get(db, STATE_KEY, {}) or {}
    out = {"version": VERSION, "last": st.get("last"), "start": "2026-10-12", "slots": CONFIG["slots"], "risk": CONFIG["risk"], "accounts": []}
    codes = set()
    for k in ACCTS:
        a = st.get(k) or {}
        codes |= set((a.get("pos") or {}).keys()) | {t["code"] for t in (a.get("trades") or [])[-15:]}
    nm, px = _names(db, codes), _last_close(db, codes)
    for k, label in ACCTS.items():
        a = st.get(k)
        if not a:
            out["accounts"].append({"k": k, "label": label, "empty": True}); continue
        tr = a.get("trades") or []
        eq = a.get("eq") or []
        peak, mdd = 1.0, 0.0
        for _, v in eq:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        pos = [{"code": c, "name": nm.get(c, c), "d0": p.get("d0"), "px0": p.get("px0"), "stop": p.get("stop"), "close": px.get(c),
                "gain": round((px[c] / p["px0"] - 1) * 100, 2) if px.get(c) and p.get("px0") else None, "exit_next": p.get("exit_next")}
               for c, p in (a.get("pos") or {}).items()]
        out["accounts"].append({"k": k, "label": label, "equity": eq[-1][1] if eq else 1.0, "eq": eq[-250:], "mdd": round(mdd * 100, 2),
                                "n": len(tr), "win": round(sum(t["R"] > 0 for t in tr) / len(tr) * 100) if tr else None,
                                "avgR": round(sum(t["R"] for t in tr) / len(tr), 2) if tr else None, "pos": pos,
                                "trades": [{**{x: t.get(x) for x in ("code", "d0", "d1", "px0", "px1", "why", "R")}, "name": nm.get(t["code"], t["code"]),
                                            "net": round((t.get("net") or 0) * 100, 2)} for t in tr[-15:][::-1]]})
    return out


def watch(db: Session) -> dict:
    from backend.services.watchlist import _items, _positions, _plan, post_items, HELD_EXCLUDE  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    items = _items(db)
    try:
        posts = post_items(db)
    except Exception:  # noqa: BLE001
        posts = {}
    wl = {x["code"]: x for x in items}
    skip = set(_get(db, "held_exclude", None) or HELD_EXCLUDE)
    pos = _positions(db)
    px = _last_close(db, [x["code"] for x in items] + [p["code"] for p in pos])
    held = []
    for p in pos:
        pl = _plan(db, p["code"], wl, posts)
        c = px.get(p["code"])
        held.append({"code": p["code"], "name": p["name"], "avg": round(p["avg"]), "close": c, "stop": pl["stop"] or None, "note": pl["note"],
                     "long": p["code"] in skip, "gain": round((c * 0.998 / p["avg"] - 1) * 100, 1) if c and p["avg"] else None,
                     "room": round((c / pl["stop"] - 1) * 100, 1) if c and pl["stop"] else None,
                     "src": "관심 목록" if (wl.get(p["code"]) or {}).get("kind") == "hold" else "정리 글" if pl["stop"] else None})
    return {"items": [{**x, "close": px.get(x["code"])} for x in items], "held": held}


def watch_set(db: Session, code: str, kind: str | None, level: float | None, note: str | None, remove: bool = False) -> dict:
    from backend.services.telegram import _find, _get, _put  # noqa: PLC0415
    row = _find(db, code)
    if not row:
        return {"ok": False, "msg": "종목을 못 찾았습니다"}
    items = [x for x in (_get(db, "user_watchlist", []) or []) if x["code"] != row.code]
    old = next((x for x in (_get(db, "user_watchlist", []) or []) if x["code"] == row.code), {})
    if not remove:
        items.append({"code": row.code, "name": row.name, "kind": kind or old.get("kind") or "watch",
                      "level": int(level) if level is not None else old.get("level", 0), "note": note if note is not None else old.get("note", "")})
    _put(db, "user_watchlist", items)
    return {"ok": True, "msg": f"{row.name} {'뺐습니다' if remove else '저장했습니다'}", "n": len(items)}


_SECRET = re.compile(r"(bot\d+:[\w-]+|[A-Za-z0-9_-]{32,}|appkey=\S+|appsecret=\S+|crtfc_key=\S+|postgresql://\S+)")


def _clean(s: str) -> str:
    return _SECRET.sub("***", s)


def status(db: Session) -> dict:
    out: dict = {}
    d = Path("/home/junp/backups/db")
    dumps = sorted(d.glob("stock_*.dump"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    out["backup_local"] = [{"name": p.name, "at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m/%d %H:%M"), "mb": round(p.stat().st_size / 1e6)}
                           for p in dumps[-3:]][::-1]
    off = Path("/home/junp/backups/offsite")
    files = sorted(off.glob("userdata_*.dump.gpg")) if off.exists() else []
    out["backup_offsite"] = {"n": len(files), "last": files[-1].name if files else None,
                             "at": datetime.fromtimestamp(files[-1].stat().st_mtime).strftime("%m/%d %H:%M") if files else None,
                             "mb": round(files[-1].stat().st_size / 1e6, 1) if files else None, "repo": "GitHub 비공개 stock-backups"}
    try:
        lg = Path("/home/junp/backups/offsite_backup.log").read_text().strip().splitlines()
        out["backup_offsite"]["log"] = _clean(lg[-1]) if lg else None
    except OSError:
        pass
    try:
        from backend import scheduler as sch  # noqa: PLC0415
        jobs = sch.SCHED.get_jobs() if sch.SCHED else []
        out["jobs"] = sorted([{"id": j.id, "next": j.next_run_time.strftime("%m/%d %H:%M") if j.next_run_time else None} for j in jobs],
                             key=lambda x: x["next"] or "99")[:40]
    except Exception:  # noqa: BLE001
        out["jobs"] = []
    try:
        out["joblog"] = [{"at": str(c)[:16], "stage": st, "status": s_, "msg": _clean((m or "")[:160])} for c, st, s_, m in db.execute(text(
            "select created_at, stage, status, message from job_logs order by id desc limit 12")).all()]
    except Exception:  # noqa: BLE001
        out["joblog"] = []
    try:
        r = subprocess.run(["journalctl", "-u", "stock-analyzer", "--since", "24 hours ago", "--no-pager", "-o", "short-iso"], capture_output=True, text=True, timeout=15)
        # 텔레그램 getUpdates 시간 초과는 늘 생기는 잡음이라 뺌. 줄 앞(호스트·프로세스·날짜 중복)은 잘라 시각 + 내용만
        lines = [l for l in r.stdout.splitlines() if re.search(r"ERROR|Traceback| 500 |실패", l) and "INFO:" not in l and "getUpdates" not in l]
        short = lambda l: (l[5:16].replace("T", " ") + " " + re.sub(r"^.*?\| (WARNING|ERROR) \| ", r"\1 ", l.split(": ", 1)[-1]))[:220]  # noqa: E731
        out["errors"] = {"n": len(lines), "last": [_clean(short(l)) for l in lines[-8:]][::-1]}
    except Exception:  # noqa: BLE001
        out["errors"] = None
    try:
        from backend.services.telegram import _get  # noqa: PLC0415
        out["stop_alert"] = _get(db, "stop_alert_state", {}) or {}
    except Exception:  # noqa: BLE001
        pass
    try:
        out["data"] = {k: str(v) for k, v in zip(("daily", "minute", "flows"), db.execute(text(
            "select (select max(trading_date) from spot_daily_prices), (select max(ts) from stock_minute_bars), (select max(trading_date) from market_investor_flows)")).one())}
    except Exception:  # noqa: BLE001
        pass
    du = os.statvfs("/")
    out["disk"] = {"free_gb": round(du.f_bavail * du.f_frsize / 1e9, 1), "total_gb": round(du.f_blocks * du.f_frsize / 1e9, 1)}
    try:
        out["load"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    return out
