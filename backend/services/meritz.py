"""메리츠증권 Open API (2026-10-12 베타 오픈, 사용자 계좌 = 메리츠 Super365) — 토큰·요청·잔고·주문.

- 키: /home/junp/stock_option_pj/.env 의 MERITZ_APP_KEY · MERITZ_APP_SECRET (코드·기억·로그에 옮겨 적지 않는다)
- 앱키에 계좌가 묶여 있어 계좌번호는 안 넣는다. 모의계좌 없음 = 실계좌.
- 응답 판정: HTTP 상태가 아니라 rsp_cd (오류도 HTTP 500으로 온다). 주문은 warn_cls_code 가 '0'이 아니면 접수 안 된 것.
- API마다 초당 10건 — 호출 사이 0.12초 쉼. 토큰(12시간)은 파일에 두고 재사용(재시작마다 새로 받지 않게).
- 2026-10-13: 초대 사용자 계좌도 다루려고 Client(키·시크릿·이름표)로 묶음. 모듈 함수(holdings·stop_sell…)는 사장님 키(.env) 그대로.
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


def _mac() -> str:
    n = uuid.getnode()
    return "".join(f"{(n >> s) & 0xFF:02X}" for s in range(40, -1, -8))


def _first(res: dict) -> dict:
    d = res["data"]
    return d if isinstance(d, dict) else ((d or [{}])[0] if isinstance(d, list) else {})


def _order_result(res: dict) -> dict:
    d = _first(res)
    warn = str(d.get("warn_cls_code") or "0")
    ok = res["ok"] and warn in ("0", "") and bool(d.get("oder_no"))
    return {"ok": ok, "order_no": d.get("oder_no"), "warn": "" if warn in ("0", "") else f"{warn} {d.get('warn_msg') or ''}".strip(),
            "msg": f"{res['rsp_cd']} {res['msg']} {res['sub']}".strip()}


class Client:
    """키 하나 = 계좌 하나. tag는 토큰 파일 이름표(사장님 = 'junp', 초대 사용자 = 'pt_이름')."""

    def __init__(self, app_key: str, app_secret: str, tag: str = "junp"):
        self.key, self.secret, self.tag = (app_key or "").strip(), (app_secret or "").strip(), tag
        self.token_file = Path.home() / (".meritz_token.json" if tag == "junp" else f".meritz_token_{tag}.json")
        self._lock, self._last = threading.Lock(), 0.0

    def enabled(self) -> bool:
        return bool(self.key and self.secret)

    def _token(self, force: bool = False) -> str:
        try:
            d = json.loads(self.token_file.read_text())
            if not force and d.get("exp", 0) > time.time() + 300 and d.get("key") == self.key[-6:]:
                return d["token"]
        except (OSError, ValueError, KeyError):
            pass
        r = requests.post(f"{BASE}/oauth2/token", timeout=15, headers={"content-type": "application/x-www-form-urlencoded"},
                          data={"grant_type": "client_credentials", "client_id": self.key, "client_secret": self.secret, "scope": "login"})
        if r.status_code != 200:
            try:
                j = r.json()
            except ValueError:
                j = {}
            raise RuntimeError(f"메리츠 토큰 발급 실패 HTTP {r.status_code} {j.get('rsp_cd', '')} {j.get('rsp_msg', '')}".strip())
        d = r.json()
        tok, ttl = d["access_token"], int(d.get("expires_in", 43200))
        self.token_file.write_text(json.dumps({"token": tok, "exp": time.time() + ttl - 60, "key": self.key[-6:]}))
        os.chmod(self.token_file, 0o600)
        return tok

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        """{'ok', 'rsp_cd', 'msg', 'sub', 'data', 'body'} — ok는 rsp_cd가 성공 코드일 때 (주문은 warn까지 따로 봐야 함).
        '유효하지 않은 token'(EGW00121)이면 토큰을 새로 받아 한 번 더 (2026-10-14 12:4x 파일 속 토큰이 만료 전인데 거부돼 장중 손절 점검이 멈췄던 것)."""
        res = self._call(method, path, params, body)
        if res["rsp_cd"] in ("EGW00121", "EGW00123"):
            logger.warning("메리츠 토큰 거부(%s) — 새로 받아 다시 시도", res["rsp_cd"])
            try:
                self._token(force=True)
            except Exception as exc:  # noqa: BLE001
                logger.error("메리츠 토큰 새로 받기 실패: %s", exc)
                return res
            res = self._call(method, path, params, body)
        return res

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        with self._lock:
            wait = 0.12 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        h = {"authorization": f"Bearer {self._token()}", "mac_address": _mac(), "content-type": "application/json; charset=utf-8"}
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

    def holdings(self) -> list[dict]:
        """국내 보유분만, 신용 대출 건(대출일)마다 한 줄. code는 6자리. loan_date = 결제일(매수일 +2영업일)로 내려온다."""
        res = self.call("GET", "/accounts/v1/me/holdings")
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

    def stop_sell(self, code: str, qty: int, trigger: int, limit: int, credit: bool, loan_date: str = "") -> dict:
        """스톱지정가 매도 (KRX 정규장만, 당일 유효). trigger에 닿으면 limit 지정가로 나간다.
        경고가 오면 자동으로 '확인'해 다시 보내지 않는다(사람이 보게)."""
        common = {"iscd": "A" + code, "oder_unpr": int(limit), "odqt": int(qty), "oder_cls_code": "83", "oder_cond_cls_code": "0",
                  "exch_kind_code": "01", "aspr_cond_prc": int(trigger), "warn_cnfr_yn": "N"}
        if credit:
            res = self.call("POST", "/trading/v1/credit-orders/sell", body={**common, "loan_oder_cls_code": "01", "loan_date": loan_date, "loan_srno": "1", "whol_amt_rdmp_yn": "N"})
        else:
            res = self.call("POST", "/trading/v1/orders/sell", body={**common, "orgl_oder_no": 0, "whol_rctf_cncl_yn": "N"})
        return _order_result(res)

    def cancel(self, code: str, order_no, qty: int, trigger: int = 0, limit: int = 0) -> dict:
        body = {"iscd": "A" + code, "oder_unpr": int(limit), "odqt": int(qty), "oder_cls_code": "83", "oder_cond_cls_code": "0",
                "orgl_oder_no": int(order_no), "whol_rctf_cncl_yn": "Y", "warn_cnfr_yn": "N", "exch_kind_code": "01", "aspr_cond_prc": int(trigger)}
        res = self.call("POST", "/trading/v1/orders/cancel", body=body)
        return {"ok": res["ok"], "msg": f"{res['rsp_cd']} {res['msg']} {res['sub']}".strip()}

    def orders_today(self, yyyymmdd: str, side: str = "0") -> list[dict]:
        """주문내역 (하루). side '0' 전체 · '1' 매도 · '2' 매수. 연속조회까지."""
        out, params = [], {"oder_date": yyyymmdd, "deal_cls_code": side, "cntg_cls_code": "0", "sort_stnd_code": "2"}
        for _ in range(10):
            res = self.call("GET", "/trading/v1/orders/history", params=params)
            if not res["ok"]:
                break
            out += list(res["data"] or [])
            if res["rsp_cd"] != "5762" or not res["body"].get("tr_cont_key"):
                break
            params = {**params, "tr_cont": "1", "tr_cont_key": res["body"]["tr_cont_key"]}
        return out

    def market_sell(self, code: str, qty: int, credit: bool, loan_date: str = "") -> dict:
        """시장가 매도. 장 시작 전(08:50)에 내면 시초가, 15:20~15:30 동시호가에 내면 종가에 체결된다 (사장님 계좌 전용 규칙에서 씀)."""
        common = {"iscd": "A" + code, "oder_unpr": 0, "odqt": int(qty), "oder_cls_code": "05", "oder_cond_cls_code": "0",
                  "exch_kind_code": "01", "warn_cnfr_yn": "N"}
        if credit:
            res = self.call("POST", "/trading/v1/credit-orders/sell", body={**common, "loan_oder_cls_code": "01", "loan_date": loan_date, "loan_srno": "1", "whol_amt_rdmp_yn": "N"})
        else:
            res = self.call("POST", "/trading/v1/orders/sell", body={**common, "orgl_oder_no": 0, "whol_rctf_cncl_yn": "N"})
        return _order_result(res)


# ── 사장님 계좌(.env 키) — 기존 이름 그대로 ──
_DEFAULT: Client | None = None


def default() -> Client:
    global _DEFAULT
    if _DEFAULT is None or _DEFAULT.key != (os.getenv("MERITZ_APP_KEY") or "").strip():
        _DEFAULT = Client(os.getenv("MERITZ_APP_KEY", ""), os.getenv("MERITZ_APP_SECRET", ""), "junp")
    return _DEFAULT


def enabled() -> bool:
    return default().enabled()


def call(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    return default().call(method, path, params, body)


def holdings() -> list[dict]:
    return default().holdings()


def stop_sell(code: str, qty: int, trigger: int, limit: int, credit: bool, loan_date: str = "") -> dict:
    return default().stop_sell(code, qty, trigger, limit, credit, loan_date)


def cancel(code: str, order_no, qty: int, trigger: int = 0, limit: int = 0) -> dict:
    return default().cancel(code, order_no, qty, trigger, limit)


def orders_today(yyyymmdd: str, side: str = "0") -> list[dict]:
    return default().orders_today(yyyymmdd, side)


def market_sell(code: str, qty: int, credit: bool, loan_date: str = "") -> dict:
    return default().market_sell(code, qty, credit, loan_date)
