"""토스증권 Open API — 초대 사용자 계좌의 잔고·조건주문(손절) (2026-10-13).

- 키 = 그 사람이 토스증권 앱(설정 > Open API)에서 발급한 client id · secret. 허용 IP에 이 서버(20.196.212.146)를 등록해야 한다(아니면 403).
- 계좌·자산·주문·조건주문은 토큰에 더해 X-Tossinvest-Account: accountSeq 헤더 필요 (/api/v1/accounts 로 얻음).
- 조건주문(SINGLE·SELL·MARKET): 현재가가 감시가에 닿으면 시장가 매도. KRX 정규장에서만 발동. 만료일 최대 1년 → 매일 다시 걸 필요 없음.
- 호출 제한: ACCOUNT 초당 1회, ASSET 5회 등 — 호출 사이 1.1초 쉼(넉넉히).
명세: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

BASE = "https://openapi.tossinvest.com"


def _err(j) -> str:
    e = (j or {}).get("error")
    if isinstance(e, dict):
        return " ".join(str(e.get(k)) for k in ("code", "message") if e.get(k))
    return str(e or (j or {}).get("message") or "")


class TossClient:
    def __init__(self, app_key: str, app_secret: str, tag: str, account_seq: str | int | None = None):
        self.key, self.secret, self.tag = (app_key or "").strip(), (app_secret or "").strip(), tag
        self.account_seq = str(account_seq) if account_seq not in (None, "") else None
        self.token_file = Path.home() / f".toss_token_{tag}.json"
        self._lock, self._last = threading.Lock(), 0.0

    def _token(self) -> str:
        try:
            d = json.loads(self.token_file.read_text())
            if d.get("exp", 0) > time.time() + 120 and d.get("key") == self.key[-6:]:
                return d["token"]
        except (OSError, ValueError, KeyError):
            pass
        r = requests.post(f"{BASE}/oauth2/token", timeout=15,
                          data={"grant_type": "client_credentials", "client_id": self.key, "client_secret": self.secret})
        if r.status_code != 200:
            raise RuntimeError(f"토스 토큰 발급 실패 HTTP {r.status_code}")
        d = r.json()
        self.token_file.write_text(json.dumps({"token": d["access_token"], "exp": time.time() + float(d.get("expires_in", 3600)) - 60, "key": self.key[-6:]}))
        os.chmod(self.token_file, 0o600)
        return d["access_token"]

    def _req(self, method: str, path: str, params: dict | None = None, body: dict | None = None, account: bool = True) -> tuple[int, dict]:
        with self._lock:
            wait = 1.1 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        h = {"Authorization": f"Bearer {self._token()}"}
        if account:
            if not self.account_seq:
                self.account_seq = self.first_account()
            h["X-Tossinvest-Account"] = self.account_seq
        try:
            r = requests.request(method, BASE + path, headers=h, params=params, json=body, timeout=15)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {}
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": type(exc).__name__}

    def first_account(self) -> str:
        code, j = self._req("GET", "/api/v1/accounts", account=False)
        rows = (j or {}).get("result") or []
        if code != 200 or not rows:
            raise RuntimeError(f"토스 계좌 조회 실패 HTTP {code}" + (" (허용 IP에 서버 20.196.212.146 등록 필요)" if code == 403 else ""))
        acc = next((x for x in rows if x.get("accountType") == "BROKERAGE"), rows[0])
        return str(acc.get("accountSeq"))

    def holdings(self) -> list[dict]:
        code, j = self._req("GET", "/api/v1/holdings")
        if code != 200:
            raise RuntimeError(f"토스 잔고 조회 실패 HTTP {code}" + (" (허용 IP 확인)" if code == 403 else ""))
        out = []
        for x in ((j or {}).get("result") or {}).get("items") or []:
            if x.get("marketCountry") != "KR":
                continue
            q = int(float(x.get("quantity") or 0))
            if q > 0:
                out.append({"code": str(x.get("symbol")), "name": x.get("name"), "credit": False, "loan_date": "",
                            "qty": q, "avg": float(x.get("averagePurchasePrice") or 0)})
        return out

    def stop_create(self, code: str, qty: int, trigger: int, expire: str) -> dict:
        body = {"symbol": code, "type": "SINGLE", "quantity": str(int(qty)), "orderType": "MARKET", "expireDate": expire,
                "first": {"orderSide": "SELL", "triggerPrice": str(int(trigger))}}
        status, j = self._req("POST", "/api/v1/conditional-orders", body=body)
        res = (j or {}).get("result") or {}
        oid = res.get("conditionalOrderId") or res.get("id")
        ok = status in (200, 201) and bool(oid)
        msg = "" if ok else f"HTTP {status} {_err(j)}".strip()
        return {"ok": ok, "order_no": oid, "warn": "", "msg": msg}

    def market_sell(self, code: str, qty: int, opening: bool, client_id: str | None = None) -> dict:
        """시장가 매도. opening=True면 OPG(국내 시가단일가 — 08:50에 내면 시초가), 아니면 DAY(장중 바로).
        client_id = 멱등 키(10분) — 같은 날 같은 종목 두 번 나가지 않게."""
        body = {"symbol": code, "side": "SELL", "orderType": "MARKET", "quantity": str(int(qty)), "timeInForce": "OPG" if opening else "DAY"}
        if client_id:
            body["clientOrderId"] = client_id[:36]
        status, j = self._req("POST", "/api/v1/orders", body=body)
        oid = ((j or {}).get("result") or {}).get("orderId")
        ok = status in (200, 201) and bool(oid)
        msg = "" if ok else f"HTTP {status} {_err(j)}".strip()
        return {"ok": ok, "order_no": oid, "warn": "", "msg": msg}

    def stop_cancel(self, order_id) -> dict:
        status, j = self._req("DELETE", f"/api/v1/conditional-orders/{order_id}")
        return {"ok": status in (200, 204), "msg": "" if status in (200, 204) else f"HTTP {status}"}

    def stops(self) -> list[dict]:
        status, j = self._req("GET", "/api/v1/conditional-orders")
        r = (j or {}).get("result")
        return (r.get("items") if isinstance(r, dict) else r) or [] if status == 200 else []
