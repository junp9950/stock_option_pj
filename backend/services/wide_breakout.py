"""넓은 돌파 (이번 장 한정 · 2026-10-15 사용자 "넣고, 디폴트로 켜 놔라 · AI장 마무리되면 니가 끄고").

조건(국장 · 시장 상승·횡보장): 종가 > 5·10·20일선 · 직전 10일 고가 돌파 · 그날 +3%↑ +29% 미만(상한가 제외) · 거래대금 20일 평균 1.5배↑ · 30억↑ ·
  강도 RS 70↑ · 20일선 ≥ 60일선 × 0.98(정배열 직전 포함) · 손절폭(그날 저가 −1%) 15% 이하. 지금 규칙·돌파 매수 다음 칸.
  손절 = 그날 저가 −1% · 21일선 아래 마감 → 다음 날 아침 정리 (지금 규칙과 같음). 손절폭이 넓으면 수량은 위험 0.5% 기준이라 저절로 작아짐.
검증(tmp_claude/relax_test.py · relax_robust.py · wide_switch.py): 거래당 R ~2022 +0.03 · 23~25.04 +0.24 · 25.04.09~ +0.62.
  계좌(지금 ∪ 넓은 돌파, 15종목): 늘 켬 12년 +13%/−68% (2019~22 +9% vs 지금 +25%) · 25.06~ +164% vs +71%.
  자동 스위치 = 최근 120거래일 안에 끝난 넓은 돌파 거래(20건↑) 평균 R > 0이면 켬 → 12년 +16%/−64% (지금 +15%/−65%) · 25.06~ +191% · 2019~22 +13%.
  사장님이 /넓은돌파 끄기·켜기로 직접 정하면 그게 먼저 (자동으로 되돌리지 않음 — /넓은돌파 자동 으로 풀기).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KEY = "wide_brk"
LOOK = 120
MIN_N = 20
_ST: dict = {"key": None, "v": None}


def conditions(C, H, L, TV, RS) -> pd.DataFrame:
    """날짜 × 종목 넓은 돌파 조건 (시장 국면 빼고). 전부 그날 종가까지 정보."""
    e5, e10, e20, e60 = (C.ewm(span=n, adjust=False).mean() for n in (5, 10, 20, 60))
    chg = C / C.shift(1) - 1
    hi10 = H.shift(1).rolling(10).max()
    tv20p = TV.shift(1).rolling(20).mean()
    risk = 1 - L * 0.99 / C
    ok = ((C > e5) & (C > e10) & (C > e20) & (C > hi10) & (chg >= 0.03) & (chg < 0.29) & (TV / tv20p >= 1.5)
          & (TV.rolling(20).mean() >= 3e9) & (RS >= 70) & (e20 >= e60 * 0.98) & (risk > 0) & (risk <= 0.15))
    return ok.fillna(False)


def _closed_trades(P: dict, sig: pd.DataFrame) -> list[tuple]:
    """신호마다 지금 규칙과 같은 매도로 끝까지 — (정리 날 위치, R). 아직 안 끝난 건 뺌."""
    C, L = P["c"].to_numpy(dtype="float64"), P["l"].to_numpy(dtype="float64")
    O = P["o"].to_numpy(dtype="float64") if P.get("o") is not None else np.vstack([C[:1], C[:-1]])
    e21 = P["c"].ewm(span=21, adjust=False).mean().to_numpy()
    n = len(C)
    out = []
    ii, jj = np.nonzero(sig.to_numpy())
    for i, j in zip(ii, jj):
        px0 = C[i, j]; st = L[i, j] * 0.99; rk = 1 - st / px0
        if not (px0 > 0 and rk > 0):
            continue
        for t in range(i + 1, n):
            if np.isfinite(L[t, j]) and L[t, j] < st:
                o = O[t, j]; ex = min(o, st) if np.isfinite(o) else st
                out.append((t, (ex / px0 - 1) / rk)); break
            if np.isfinite(C[t, j]) and C[t, j] < e21[t, j]:
                if t + 1 < n and np.isfinite(O[t + 1, j]):
                    out.append((t + 1, (O[t + 1, j] / px0 - 1) / rk))
                break
    return out


def _calc(db: Session) -> dict:
    from backend.services.stock_signals import _bull_days, _close_frames, _data_latest  # noqa: PLC0415
    from backend.services.trading_rules import relative_strength  # noqa: PLC0415
    latest = _data_latest(db)
    P = _close_frames(db, latest)
    C, H, L, TV = P["c"], P["h"], P["l"], P["tv"]
    RS = relative_strength(C, TV)
    bull = pd.Series(_bull_days(db)).reindex(C.index).fillna(False).astype(bool)
    sig = conditions(C, H, L, TV, RS).mul(bull, axis=0)
    tr = _closed_trades(P, sig)
    n = len(C)
    ex = np.array([t for t, _ in tr]); R = np.clip(np.array([r for _, r in tr]), -2, 20)
    on_by_day = {}
    for k in range(max(0, n - 260), n + 1):             # k = 이 날 아침까지 끝난 거래로 판단 (k == n 은 다음 장)
        m = (ex >= k - LOOK) & (ex < k)
        if m.sum() >= MIN_N:
            on_by_day[k] = (float(R[m].mean()), int(m.sum()))
    nxt = on_by_day.get(n)
    hist = {str(C.index[k]): v[0] > 0 for k, v in on_by_day.items() if k < n}
    return {"date": str(latest), "mean": round(nxt[0], 2) if nxt else None, "n": nxt[1] if nxt else 0,
            "auto": bool(nxt and nxt[0] > 0) if nxt else True, "hist": hist}


def state(db: Session) -> dict:
    """{'on', 'auto', 'mean', 'n', 'why', 'manual'} — 하루 한 번 계산 (DB 날짜가 바뀔 때)."""
    from backend.services.stock_signals import _data_latest  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    latest = _data_latest(db)
    if _ST["key"] != latest:
        try:
            _ST.update(key=latest, v=_calc(db))
        except Exception as exc:  # noqa: BLE001
            logger.warning("넓은 돌파 상태 계산 실패: %s", exc)
            _ST.update(key=latest, v={"date": str(latest), "mean": None, "n": 0, "auto": True, "hist": {}})
    v = dict(_ST["v"])
    man = (_get(db, KEY, {}) or {}).get("manual")
    if man and man.get("on") is not None:
        v.update(on=bool(man["on"]), manual=man, why=f"사장님이 {'켬' if man['on'] else '끔'} ({man.get('at', '')})")
    else:
        v.update(on=v["auto"], manual=None,
                 why=(f"최근 {LOOK}거래일 끝난 넓은 돌파 {v['n']}건 평균 {v['mean']:+.2f}R" if v["mean"] is not None else "기록 부족 — 기본 켬")
                 + ("" if v["auto"] else " → 돌파가 안 먹히는 장이라 자동으로 끔"))
    return v


def on_for(db: Session, d) -> bool:
    """차트 지난 날짜 표시용: 그날 스위치 (기록 없는 옛날은 켬으로)."""
    try:
        s = state(db)
        if s.get("manual"):
            return bool(s["on"])
        return bool(s["hist"].get(str(d), True))
    except Exception:  # noqa: BLE001
        return True


def set_manual(db: Session, on: bool | None, reason: str = "") -> str:
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    s = _get(db, KEY, {}) or {}
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    s.setdefault("log", []).append({"at": now, "on": on, "reason": reason[:100]})
    s["manual"] = None if on is None else {"on": on, "at": now, "reason": reason[:100]}
    _put(db, KEY, s)
    st = state(db)
    return f"넓은 돌파: {'켜짐' if st['on'] else '꺼짐'} — {st['why']}"


def daily_check(db: Session) -> str:
    """장 마감 뒤: 자동 스위치가 바뀌면 사장님께 알림 (켜짐→꺼짐 = 'AI장 마무리' 신호일 수 있음)."""
    from backend.services.telegram import _get, _put, owner_chats, send  # noqa: PLC0415
    st = state(db)
    s = _get(db, KEY, {}) or {}
    last = s.get("last_auto")
    if last is not None and last != st["auto"] and not st.get("manual"):
        msg = (f"{'🟢 넓은 돌파 다시 켜짐' if st['auto'] else '⛔ 넓은 돌파 자동으로 꺼짐'} (이번 장 한정 규칙)\n"
               f"최근 {LOOK}거래일 끝난 넓은 돌파 {st['n']}건 평균 {st['mean']:+.2f}R"
               + ("" if st["auto"] else "\n돌파가 연달아 실패하는 장 — 지금 규칙(정배열·+8% 미만·손절폭 8%↓)만 남깁니다. 되돌리려면 /넓은돌파 켜기"))
        for c in owner_chats(db):
            send(db, msg, c)
    s["last_auto"] = st["auto"]
    _put(db, KEY, s)
    return st["why"]
