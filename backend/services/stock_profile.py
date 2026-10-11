"""종목 탭 (2026-10-11 사용자 "개별 종목 조회 — 차트, PER·PBR·PSR, 실적 추이, 수급 같은 것").

- 투자 지표·실적(분기·연간, 컨센서스 포함)·안정성: 네이버 증권 모바일 API
- 업종 PER · 주요 제품 매출 구성: 와이즈리포트(네이버 기업정보) 화면
- 수급(개인·외국인·기관·기관 세부·기타법인·외국인 보유율) · 공매도: 토스 API
- PSR = 시가총액(DB) ÷ 최근 4분기 매출 합
지표는 6시간, 수급은 10분 메모리 캐시.
"""
from __future__ import annotations

import html
import logging
import re
import time

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0"}
_P: dict = {}
_F: dict = {}


def _num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").replace("배", "").replace("원", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _finance(code: str, kind: str) -> dict | None:
    try:
        j = requests.get(f"https://m.stock.naver.com/api/stock/{code}/finance/{kind}", headers=UA, timeout=8).json()
        fi = j.get("financeInfo") or {}
    except Exception:  # noqa: BLE001
        return None
    periods = [{"key": t["key"], "title": t["title"].rstrip("."), "est": t.get("isConsensus") == "Y"} for t in fi.get("trTitleList") or []]
    rows = {}
    for r in fi.get("rowList") or []:
        rows[r["title"]] = [_num((r.get("columns") or {}).get(p["key"], {}).get("value")) for p in periods]
    return {"periods": periods, "rows": rows} if periods else None


def _wise(code: str) -> tuple[float | None, list[dict]]:
    ind_per, mix = None, []
    try:
        t = requests.get(f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}", headers=UA, timeout=8).text
        m = re.search(r"업종PER</[^>]+>\s*<[^>]+>\s*([-\d.,]+)", t) or re.search(r"업종PER\D{0,80}?([-\d.,]+)", re.sub(r"<[^>]+>", " ", t))
        ind_per = _num(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        pass
    try:
        t = requests.get(f"https://navercomp.wisereport.co.kr/v2/company/c1020001.aspx?cmp_cd={code}", headers=UA, timeout=8).text
        i = t.find("주요제품 매출구성</caption>")
        if i > 0:
            seg = t[i:t.find("</table>", i)]
            for name, pct in re.findall(r'<span class="cut">([^<]+)</span>\s*</th>\s*<td class="c2 num[^"]*">\s*([-\d.]+)\s*</td>', seg):
                mix.append({"name": html.unescape(name.strip()), "pct": float(pct)})
    except Exception:  # noqa: BLE001
        pass
    return ind_per, mix


def profile(db: Session, code: str) -> dict:
    hit = _P.get(code)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    out: dict = {"code": code}
    row = db.execute(text("select name, market, market_cap from stocks where code = :c"), {"c": code}).one_or_none()
    if row:
        out.update(name=row[0], market=row[1], market_cap=float(row[2]) if row[2] else None)
    try:
        j = requests.get(f"https://m.stock.naver.com/api/stock/{code}/integration", headers=UA, timeout=8).json()
        info = {x["code"]: x["value"] for x in j.get("totalInfos") or []}
        out["name"] = out.get("name") or j.get("stockName")
        out["metrics"] = {"per": _num(info.get("per")), "eps": _num(info.get("eps")), "cns_per": _num(info.get("cnsPer")), "cns_eps": _num(info.get("cnsEps")),
                          "pbr": _num(info.get("pbr")), "bps": _num(info.get("bps")), "div_yield": _num(info.get("dividendYieldRatio")),
                          "dividend": _num(info.get("dividend")), "high52": _num(info.get("highPriceOf52Weeks")), "low52": _num(info.get("lowPriceOf52Weeks")),
                          "foreign_rate": _num(info.get("foreignRate"))}
        cs = j.get("consensusInfo") or {}
        out["target"] = {"price": _num(cs.get("priceTargetMean")), "opinion": _num(cs.get("recommMean")), "date": cs.get("createDate")}
        out["researches"] = [{"title": r.get("tit"), "broker": r.get("bnm"), "date": r.get("wdt"), "id": r.get("id")} for r in (j.get("researches") or [])[:6]]
        out["peers"] = [{"code": p.get("itemCode"), "name": p.get("stockName"), "chg": _num(p.get("fluctuationsRatio")),
                         "cap": _num(p.get("marketValue"))} for p in (j.get("industryCompareInfo") or [])[:6] if p.get("itemCode") != code]
    except Exception as exc:  # noqa: BLE001
        logger.warning("종목 지표 실패 %s: %s", code, type(exc).__name__)
    out["quarter"] = _finance(code, "quarter")
    out["annual"] = _finance(code, "annual")
    out["industry_per"], out["mix"] = _wise(code)
    # PSR = 시총 ÷ 최근 4분기(발표된 것) 매출 합 (매출은 억원)
    q = out.get("quarter")
    if q and out.get("market_cap"):
        sales = [v for v, p in zip(q["rows"].get("매출액", []), q["periods"]) if not p["est"] and v is not None][-4:]
        if len(sales) == 4 and sum(sales) > 0:
            out.setdefault("metrics", {})["psr"] = round(out["market_cap"] / (sum(sales) * 1e8), 2)
    _P[code] = (time.time(), out)
    if len(_P) > 300:
        _P.clear()
    return out


def flows(db: Session, code: str, days: int = 40) -> dict:
    hit = _F.get(code)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    from backend.services import toss_client  # noqa: PLC0415
    out: dict = {"code": code, "records": [], "short": []}
    try:
        r = toss_client.fetch_investor_trading(code, count=days)
        recs = ((r.json() if r is not None and r.status_code == 200 else {}).get("result") or {}).get("records") or []
        nb = lambda x: int(float((x or {}).get("netBuyVolume") or 0))  # noqa: E731
        px = {str(d): float(c) for d, c in db.execute(text("select trading_date, close_price from spot_daily_prices where stock_code = :c "
                                                           "and trading_date >= current_date - 90"), {"c": code}).all()}
        for x in recs:
            inst = x.get("institution") or {}
            bd = inst.get("breakdown") or {}
            out["records"].append({"date": x["date"], "close": px.get(x["date"]), "individual": nb(x.get("individual")), "foreigner": nb(x.get("foreigner")),
                                   "institution": nb(inst), "other_corp": nb(x.get("otherCorporation")),
                                   "fin": nb(bd.get("financialInvestment")), "insu": nb(bd.get("insurance")), "trust": nb(bd.get("trust")),
                                   "pef": nb(bd.get("privateEquityFund")), "bank": nb(bd.get("bank")), "etc_fin": nb(bd.get("otherFinancialInstitution")),
                                   "pension": nb(bd.get("pensionFund")),
                                   "f_hold": _num((x.get("foreignerHolding") or {}).get("holdingRate"))})
    except Exception as exc:  # noqa: BLE001
        logger.warning("종목 수급 실패 %s: %s", code, type(exc).__name__)
    try:
        r = toss_client._get(f"/stocks/{code}/short-selling", {"count": 20})  # noqa: SLF001
        for x in ((r.json() if r is not None and r.status_code == 200 else {}).get("result") or {}).get("records") or []:
            out["short"].append({"date": x["date"], "volume": int(float(x.get("shortSellingVolume") or 0)),
                                 "amount": float(x.get("shortSellingAmount") or 0), "ratio": _num(x.get("shortSellingVolumeRate"))})
    except Exception:  # noqa: BLE001
        pass
    _F[code] = (time.time(), out)
    if len(_F) > 300:
        _F.clear()
    return out


# ── 최근 공시 (DART, 2026-10-11 "유상증자·CB 같은 위험 공시를 차트 보고 들어가기 전에") ──
_D: dict = {}
RISK_KW = ["유상증자", "전환사채", "신주인수권부사채", "교환사채", "감자", "최대주주변경", "최대주주 변경", "소송", "횡령", "배임", "불성실공시",
           "관리종목", "상장폐지", "매매거래정지", "거래정지", "투자주의환기", "자기주식처분", "주식관련사채", "회생", "부도", "영업정지", "감사의견"]
GOOD_KW = ["자기주식취득", "자기주식 취득", "자기주식소각", "주식소각", "무상증자", "단일판매", "공급계약", "현금ㆍ현물배당", "현금배당", "특허권취득"]


def disclosures(code: str, days: int = 90) -> dict:
    hit = _D.get(code)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    import os  # noqa: PLC0415
    from datetime import date, timedelta  # noqa: PLC0415
    out: dict = {"code": code, "items": []}
    try:
        key = open(os.path.expanduser("~/.dart_key")).read().strip()
    except OSError:
        key = os.getenv("DART_API_KEY", "")
    try:
        from dart_analyzer.corp_code import find_corp  # noqa: PLC0415
        corp = find_corp(code)
        j = requests.get("https://opendart.fss.or.kr/api/list.json", timeout=10, params={
            "crtfc_key": key, "corp_code": corp.corp_code, "bgn_de": (date.today() - timedelta(days=days)).strftime("%Y%m%d"),
            "end_de": date.today().strftime("%Y%m%d"), "page_count": 100}).json()
        for r in j.get("list") or []:
            nm = re.sub(r"\s+", " ", r.get("report_nm") or "").strip()
            kind = "risk" if any(k in nm.replace(" ", "") or k in nm for k in RISK_KW) else "good" if any(k in nm for k in GOOD_KW) else ""
            if "[기재정정]" in nm or "[첨부정정]" in nm:
                kind = kind or ""
            out["items"].append({"date": r.get("rcept_dt"), "title": nm, "kind": kind, "by": r.get("flr_nm"), "rcp": r.get("rcept_no")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("공시 실패 %s: %s", code, type(exc).__name__)
        out["error"] = True
    _D[code] = (time.time(), out)
    if len(_D) > 300:
        _D.clear()
    return out
