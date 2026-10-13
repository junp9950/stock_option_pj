"""사장님 메리츠 계좌 순자산 = 주식 평가액 − 신용·기타 대출 + 현금(D+2) — 15:12 알림의 '살 수량' 계산용 (2026-10-13).
신용으로 사도 위험 비율은 '손절 때 잃는 돈 ÷ 순자산'이라 계산은 같다. 금액은 사장님 텔레그램 방에만 보낸다(공개 화면 X).
"""
from __future__ import annotations

import math
import time

_C: dict = {"t": 0.0, "v": None}


def net_equity(max_age: float = 300) -> float | None:
    if _C["v"] is not None and time.time() - _C["t"] < max_age:
        return _C["v"]
    try:
        from backend.services import meritz as M  # noqa: PLC0415
        if not M.enabled():
            return None
        r = M.call("GET", "/accounts/v1/me/deposit")
        d = r["data"] if isinstance(r.get("data"), dict) else ((r.get("data") or [{}])[0] if isinstance(r.get("data"), list) else {})
        if not r["ok"] or not d:
            return None
        f = lambda k: float(d.get(k) or 0)  # noqa: E731
        hs = M.holdings()
        codes = sorted({h["code"] for h in hs})
        px = {}
        try:
            from backend.services.naver_live import snapshot  # noqa: PLC0415
            px = {c: v["c"] for c, v in snapshot(codes, max_age=60).items()}
        except Exception:  # noqa: BLE001
            pass
        if len(px) < len(codes):
            from backend.db.database import SessionLocal  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415
            db = SessionLocal()
            try:
                for c, p in db.execute(text("select distinct on (stock_code) stock_code, close_price from spot_daily_prices "
                                            "where stock_code = any(:c) order by stock_code, trading_date desc"), {"c": codes}).all():
                    px.setdefault(c, float(p))
            finally:
                db.close()
        stock = sum(h["qty"] * px.get(h["code"], h["avg"]) for h in hs)
        eq = stock + f("d2_aft_tfam") - (f("crdt_loan_amt") + f("etc_lndn_amt") + f("smam_loan_amt") + f("nnrd_loan_amt"))
        if not (eq > 0):
            return None
        _C.update(t=time.time(), v=eq)
        return eq
    except Exception:  # noqa: BLE001
        return None


def size_text(code: str, price: float, risk: float, rp: float = 0.005, mult: float = 1.0) -> str:
    """'○주 · ○○○만 원 (증거금 ○○만)' — 순자산 × rp × mult ÷ (가격 × 손절폭). 못 구하면 빈칸."""
    eq = net_equity()
    if not eq or not price or not risk or risk <= 0:
        return ""
    qty = math.floor(eq * rp * mult / (price * risk))
    if qty <= 0:
        return " · 1주도 안 됨(위험 기준)"
    amt = qty * price
    margin = ""
    try:
        from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
        m = (flags_get([code], fetch=False).get(code) or {}).get("margin")
        if m and m < 100:
            margin = f" · 신용 증거금 {amt * m / 100 / 1e4:,.0f}만"
    except Exception:  # noqa: BLE001
        pass
    return f" · <b>{qty:,}주</b> ≈ {amt / 1e4:,.0f}만 원{margin}"
