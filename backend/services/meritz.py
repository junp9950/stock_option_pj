"""메리츠증권 Open API (2026-10-12 베타 오픈, 사용자 계좌 = 메리츠 Super365) — 토큰·요청·잔고·주문.

- 키: /home/junp/stock_option_pj/.env 의 MERITZ_APP_KEY · MERITZ_APP_SECRET (코드·기억·로그에 옮겨 적지 않는다)
- 앱키에 계좌가 묶여 있어 계좌번호는 안 넣는다. 모의계좌 없음 = 실계좌.
- 응답 판정: HTTP 상태가 아니라 rsp_cd (오류도 HTTP 500으로 온다). 주문은 warn_cls_code 가 '0'이 아니면 접수 안 된 것.
- API마다 초당 10건 — 호출 사이 0.12초 쉼. 토큰(12시간)은 파일에 두고 재사용(재시작마다 새로 받지 않게).
명세·주의점은 github.com/meritz-securities/open-api (llms.txt · catalog.json).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
BASE = "https://openapi.imeritz.com:9443"
OK_CODES = {"0000", "0001", "5762", "5766", "5820", "5822"}
_TOKEN_FILE = Path.home() / ".meritz_token.json"
_LOCK = threading.Lock()
_LAST = {"t": 0.0}


def enabled() -> bool:
    return bool(os.getenv("MERITZ_APP_KEY") and os.getenv("MERITZ_APP_SECRET"))


def _mac() -> str:
    n = uuid.getnode()
    return "".join(f"{(n >> s) & 0xFF:02X}" for s in range(40, -1, -8))


def _token() -> str:
    try:
        d = json.loads(_TOKEN_FILE.read_text())
        if d.get("exp", 0) > time.time() + 300 and d.get("key") == os.getenv("MERITZ_APP_KEY", "")[-6:]:
            return d["token"]
    except (OSError, ValueError, KeyError):
        pass
    r = requests.post(f"{BASE}/oauth2/token", timeout=15, headers={"content-type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "client_credentials", "client_id": os.getenv("MERITZ_APP_KEY", ""),
                            "client_secret": os.getenv("MERITZ_APP_SECRET", ""), "scope": "login"})
    if r.status_code != 200:
        try:
            j = r.json()
        except ValueError:
            j = {}
        raise RuntimeError(f"메리츠 토큰 발급 실패 HTTP {r.status_code} {j.get('rsp_cd', '')} {j.get('rsp_msg', '')}".strip())
    d = r.json()
    tok, ttl = d["access_token"], int(d.get("expires_in", 43200))
    _TOKEN_FILE.write_text(json.dumps({"token": tok, "exp": time.time() + ttl - 60, "key": os.getenv("MERITZ_APP_KEY", "")[-6:]}))
    os.chmod(_TOKEN_FILE, 0o600)
    return tok


def call(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """{'ok', 'rsp_cd', 'msg', 'sub', 'data', 'body'} — ok는 rsp_cd가 성공 코드일 때 (주문은 warn까지 따로 봐야 함)."""
    with _LOCK:
        wait = 0.12 - (time.time() - _LAST["t"])
        if wait > 0:
            time.sleep(wait)
        _LAST["t"] = time.time()
    h = {"authorization": f"Bearer {_token()}", "mac_address": _mac(), "content-type": "application/json; charset=utf-8"}
    try:
        if method == "GET":
            r = requests.get(BASE + path, headers=h, params=params or {}, timeout=15)
        else:
            r = requests.post(BASE + path, headers=h, json=body or {}, timeout=15)
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rsp_cd": "NET", "msg": type(exc).__name__, "sub": "", "data": None, "body": {}}
    b = j.get("body") if isinstance(j.get("body"), dict) else j
    cd = str(b.get("rsp_cd") or j.get("rsp_cd") or "")
    return {"ok": cd in OK_CODES, "rsp_cd": cd, "msg": b.get("rsp_msg") or j.get("rsp_msg") or "", "sub": b.get("rsp_sub_msg") or "",
            "data": b.get("data"), "body": b}


def holdings() -> list[dict]:
    """국내 보유분만, 신용 대출 건(대출일)마다 한 줄. code는 6자리. loan_date = 결제일(매수일 +2영업일)로 내려온다."""
    res = call("GET", "/accounts/v1/me/holdings")
    if not res["ok"]:
        raise RuntimeError(f"잔고 조회 실패 {res['rsp_cd']} {res['msg']} {res['sub']}")
    out = []
    for x in res["data"] or []:
        iscd = str(x.get("iscd") or "")
        if not (iscd.startswith("A") and len(iscd) == 7):
            continue          # 해외주식·기타 제외
        credit = (x.get("mksc_cls_name") or "") == "신용"
        out.append({"code": iscd[1:], "name": x.get("isnm"), "credit": credit, "loan_date": x.get("loan_date") or "",
                    "qty": int(float(x.get("rmnd_qty") or 0)), "avg": float(x.get("byng_unpr") or 0)})
    return [x for x in out if x["qty"] > 0]


def stop_sell(code: str, qty: int, trigger: int, limit: int, credit: bool, loan_date: str = "") -> dict:
    """스톱지정가 매도 (KRX 정규장만, 당일 유효). trigger에 닿으면 limit 지정가로 나간다.
    돌려주는 것: {'ok', 'order_no', 'warn', 'msg'} — 경고가 오면 자동으로 '확인'해 다시 보내지 않는다(사람이 보게)."""
    common = {"iscd": "A" + code, "oder_unpr": int(limit), "odqt": int(qty), "oder_cls_code": "83", "oder_cond_cls_code": "0",
              "exch_kind_code": "01", "aspr_cond_prc": int(trigger), "warn_cnfr_yn": "N"}
    if credit:
        body = {**common, "loan_oder_cls_code": "01", "loan_date": loan_date, "loan_srno": "1", "whol_amt_rdmp_yn": "N"}
        res = call("POST", "/trading/v1/credit-orders/sell", body=body)
    else:
        body = {**common, "orgl_oder_no": 0, "whol_rctf_cncl_yn": "N"}
        res = call("POST", "/trading/v1/orders/sell", body=body)
    d = res["data"] if isinstance(res["data"], dict) else ((res["data"] or [{}])[0] if isinstance(res["data"], list) else {})
    warn = str(d.get("warn_cls_code") or "0")
    ok = res["ok"] and warn in ("0", "") and bool(d.get("oder_no"))
    return {"ok": ok, "order_no": d.get("oder_no"), "warn": "" if warn in ("0", "") else f"{warn} {d.get('warn_msg') or ''}".strip(),
            "msg": f"{res['rsp_cd']} {res['msg']} {res['sub']}".strip()}


def cancel(code: str, order_no, qty: int, trigger: int = 0, limit: int = 0) -> dict:
    body = {"iscd": "A" + code, "oder_unpr": int(limit), "odqt": int(qty), "oder_cls_code": "83", "oder_cond_cls_code": "0",
            "orgl_oder_no": int(order_no), "whol_rctf_cncl_yn": "Y", "warn_cnfr_yn": "N", "exch_kind_code": "01", "aspr_cond_prc": int(trigger)}
    res = call("POST", "/trading/v1/orders/cancel", body=body)
    return {"ok": res["ok"], "msg": f"{res['rsp_cd']} {res['msg']} {res['sub']}".strip()}


def orders_today(yyyymmdd: str, side: str = "0") -> list[dict]:
    """주문내역 (하루). side '0' 전체 · '1' 매도 · '2' 매수. 연속조회까지."""
    out, params = [], {"oder_date": yyyymmdd, "deal_cls_code": side, "cntg_cls_code": "0", "sort_stnd_code": "2"}
    for _ in range(10):
        res = call("GET", "/trading/v1/orders/history", params=params)
        if not res["ok"]:
            break
        out += list(res["data"] or [])
        if res["rsp_cd"] != "5762" or not res["body"].get("tr_cont_key"):
            break
        params = {**params, "tr_cont": "1", "tr_cont_key": res["body"]["tr_cont_key"]}
    return out


def market_sell(code: str, qty: int, credit: bool, loan_date: str = "") -> dict:
    """시장가 매도. 장 시작 전(08:50)에 내면 시초가, 15:20~15:30 동시호가에 내면 종가에 체결된다.
    21일선 이탈 다음 날 시초가 매도 · 반등 모드 5거래일째 종가 매도용 (2026-10-13 사용자 승인)."""
    common = {"iscd": "A" + code, "oder_unpr": 0, "odqt": int(qty), "oder_cls_code": "05", "oder_cond_cls_code": "0",
              "exch_kind_code": "01", "warn_cnfr_yn": "N"}
    if credit:
        res = call("POST", "/trading/v1/credit-orders/sell", body={**common, "loan_oder_cls_code": "01", "loan_date": loan_date, "loan_srno": "1", "whol_amt_rdmp_yn": "N"})
    else:
        res = call("POST", "/trading/v1/orders/sell", body={**common, "orgl_oder_no": 0, "whol_rctf_cncl_yn": "N"})
    d = res["data"] if isinstance(res["data"], dict) else ((res["data"] or [{}])[0] if isinstance(res["data"], list) else {})
    warn = str(d.get("warn_cls_code") or "0")
    ok = res["ok"] and warn in ("0", "") and bool(d.get("oder_no"))
    return {"ok": ok, "order_no": d.get("oder_no"), "warn": "" if warn in ("0", "") else f"{warn} {d.get('warn_msg') or ''}".strip(),
            "msg": f"{res['rsp_cd']} {res['msg']} {res['sub']}".strip()}
