"""시황 탭 (2026-10-17 사용자 "오늘 탭을 시황 탭으로 바꾸고 신용 수치, 코스피·코스닥 RSI·이격도 넣어 봐").

- 지수 기술 지표: KIS 업종 일봉(FHKUP03500100, 코스피 0001 · 코스닥 1001) 약 250거래일 → RSI(14, 와일더) · 이격도(5·20·60·120일) · 52주 고점 대비.
- 증시 자금: KIS 증시자금 종합(FHKST649100C0, 하루 늦게 나옴, 억 원) 100거래일 → 신용융자 잔고 · 고객예탁금 · 미수금 · 신용/예탁 비율 · 펀드.
판단 문구는 설명만(매수 규칙 아님). 10분 재사용.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)
B = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/"
_C: dict = {}


def _h(tr: str) -> dict:
    from backend.collector.spot import _get_kis_token  # noqa: PLC0415
    return {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {_get_kis_token()}", "appkey": os.getenv("KIS_APP_KEY", ""),
            "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": tr, "custtype": "P"}


def _index_daily(code: str, n: int = 260) -> list[tuple[str, float]]:
    rows: dict[str, float] = {}
    end = date.today()
    for _ in range(10):
        try:
            r = requests.get(B + "inquire-daily-indexchartprice", headers=_h("FHKUP03500100"), timeout=15, params={
                "FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": (end - timedelta(days=150)).strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"), "FID_PERIOD_DIV_CODE": "D"}).json()
        except Exception:  # noqa: BLE001
            break
        o = [x for x in r.get("output2") or [] if x.get("stck_bsop_date") and x["stck_bsop_date"] not in rows]
        if not o:
            break
        for x in o:
            rows[x["stck_bsop_date"]] = float(x["bstp_nmix_prpr"])
        end = datetime.strptime(min(x["stck_bsop_date"] for x in o), "%Y%m%d").date() - timedelta(days=1)
        if len(rows) >= n:
            break
        time.sleep(0.15)
    return sorted(rows.items())[-n:]


def _rsi(c: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    l_ = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(l_[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + l_[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _tech(name: str, code: str) -> dict | None:
    L = _index_daily(code, 380)
    if len(L) < 130:
        return None
    d, c = [x[0] for x in L], [x[1] for x in L]
    rsi = _rsi(c)
    last = c[-1]
    ma = {n: sum(c[-n:]) / n for n in (5, 20, 60, 120)}
    hi52 = max(c[-250:])
    disp = {n: round(last / ma[n] * 100, 1) for n in ma}
    r = rsi[-1]
    # 설명 (사용자 색약: ▲■▼ 글자로 상태)
    rs_t = "▲ 과매수(70↑)" if r >= 70 else "▼ 과매도(30↓)" if r <= 30 else "■ 중립"
    d20 = disp[20]
    d_t = "▲ 과열(20일 이격 106↑)" if d20 >= 106 else "▼ 침체(20일 이격 94↓)" if d20 <= 94 else "■ 보통"
    return {"name": name, "date": d[-1], "close": last, "chg": round((last / c[-2] - 1) * 100, 2), "rsi": round(r, 1), "rsi_txt": rs_t,
            "rsi_hist": [round(x, 1) for x in rsi[-60:] if x is not None], "disp": disp, "disp_txt": d_t,
            "ma": {str(k): round(v, 2) for k, v in ma.items()}, "above": {str(k): last > v for k, v in ma.items()},
            "from_hi": round((last / hi52 - 1) * 100, 1), "hist": _series(d, c, rsi)}


def _series(d: list[str], c: list[float], rsi: list) -> list[dict]:
    """차트용 1년(250거래일): 종가 · 20/60/120일선 · RSI · 20일 이격도 (2026-10-17 사용자 '누르면 그래프')."""
    out = []
    for i in range(max(0, len(c) - 250), len(c)):
        m = {n: (sum(c[i - n + 1:i + 1]) / n if i + 1 >= n else None) for n in (20, 60, 120)}
        out.append({"d": d[i], "c": c[i], "ma20": round(m[20], 2) if m[20] else None, "ma60": round(m[60], 2) if m[60] else None,
                    "ma120": round(m[120], 2) if m[120] else None, "rsi": round(rsi[i], 1) if rsi[i] is not None else None,
                    "d20": round(c[i] / m[20] * 100, 1) if m[20] else None})
    return out


def _funds() -> dict | None:
    got: dict[str, dict] = {}
    end = date.today()
    for _ in range(3):          # 한 번에 100거래일 → 세 번 = 약 1년 (차트용)
        try:
            j = requests.get(B + "mktfunds", headers=_h("FHKST649100C0"), params={"FID_INPUT_DATE_1": end.strftime("%Y%m%d")}, timeout=15).json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("증시자금 실패: %s", type(exc).__name__)
            break
        o0 = [x for x in j.get("output") or [] if x.get("bsop_date") and x["bsop_date"] not in got]
        if not o0:
            break
        for x in o0:
            got[x["bsop_date"]] = x
        end = datetime.strptime(min(x["bsop_date"] for x in o0), "%Y%m%d").date() - timedelta(days=1)
        time.sleep(0.15)
    o = [got[k] for k in sorted(got)]
    if not o:
        return None
    f = lambda x, k: float(x.get(k) or 0)  # noqa: E731
    rows = [{"d": x["bsop_date"], "credit": f(x, "crdt_loan_rmnd"), "deposit": f(x, "cust_dpmn_amt"), "unpaid": f(x, "uncl_amt"),
             "futs": f(x, "futs_tfam_amt"), "eq_fund": f(x, "sttp_amt"), "mmf": f(x, "mmf_amt"), "lend": f(x, "secu_lend_amt"),
             "cap": f(x, "hts_avls") / 100, "kospi": f(x, "bstp_nmix_prpr")} for x in o]          # 억 원 (시총은 백만 원 → 억)
    z = rows[-1]

    def ch(k, n):
        return round(z[k] - rows[-1 - n][k]) if len(rows) > n else None

    def pct(k, n):
        return round((z[k] / rows[-1 - n][k] - 1) * 100, 1) if len(rows) > n and rows[-1 - n][k] else None
    hi = max(rows, key=lambda r: r["credit"])
    return {"date": z["d"], "credit": z["credit"], "deposit": z["deposit"], "unpaid": z["unpaid"], "futs": z["futs"], "eq_fund": z["eq_fund"],
            "mmf": z["mmf"], "lend": z["lend"],
            "credit_ch": {"1": ch("credit", 1), "5": ch("credit", 5), "20": ch("credit", 20)}, "credit_pct": {"5": pct("credit", 5), "20": pct("credit", 20)},
            "deposit_ch": {"1": ch("deposit", 1), "5": ch("deposit", 5), "20": ch("deposit", 20)}, "deposit_pct": {"5": pct("deposit", 5), "20": pct("deposit", 20)},
            "credit_to_deposit": round(z["credit"] / z["deposit"] * 100, 1) if z["deposit"] else None,
            "credit_to_cap": round(z["credit"] / z["cap"] * 100, 2) if z["cap"] else None,
            "credit_hi": {"d": hi["d"], "v": hi["credit"], "from": round((z["credit"] / hi["credit"] - 1) * 100, 1)},
            "hist": [{"d": r["d"], "credit": r["credit"], "deposit": r["deposit"], "unpaid": r["unpaid"], "kospi": r["kospi"],
                      "ratio": round(r["credit"] / r["deposit"] * 100, 2) if r["deposit"] else None} for r in rows]}


FILE = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "market_board.json"
_lock = __import__("threading").Lock()


def _build() -> dict:
    out = {"idx": [x for x in (_tech("코스피", "0001"), _tech("코스닥", "1001")) if x], "funds": _funds(),
           "asof": datetime.now().strftime("%m/%d %H:%M")}
    if out["idx"] or out["funds"]:
        _C["b"] = (time.time(), out)
        try:
            import json  # noqa: PLC0415
            FILE.parent.mkdir(parents=True, exist_ok=True)
            FILE.write_text(json.dumps(out, ensure_ascii=False))
        except OSError:
            pass
    return out


def board(wait: bool = False) -> dict:
    """10분 안이면 저장값. 그보다 오래됐으면 저장값을 바로 주고 뒤에서 새로 받음 (2026-10-17 "이거 오래 걸리네" — 처음 열 때 KIS 20번+로 10~15초).
    서버가 켜질 때·2분마다 미리 계산(routes.warm_caches)에서 wait=True로 채움."""
    import threading  # noqa: PLC0415
    hit = _C.get("b")
    if not hit and FILE.exists():
        try:
            import json  # noqa: PLC0415
            hit = _C["b"] = (FILE.stat().st_mtime, json.loads(FILE.read_text()))
        except (OSError, ValueError):
            hit = None
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    if hit and not wait:
        if _lock.acquire(blocking=False):
            def _bg():
                try:
                    _build()
                finally:
                    _lock.release()
            threading.Thread(target=_bg, daemon=True).start()
        return hit[1]
    with _lock:
        hit = _C.get("b")
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        return _build()
