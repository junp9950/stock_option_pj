"""공시 포렌식 (2026-10-17 사용자: '사업보고서 포렌식 분석 프롬프트' PDF → "보고서 포렌식 분석할 수 있는 탭").

DART 정기보고서·주요사항·지분 공시와 KIS 종목 투자자 세부를 모아 문서의 단계별 재료를 만든다.
  STEP 2 시계열 병렬표 · STEP 3 이익의 질·운전자본·영업외 분해 · STEP 4 감사의견·핵심감사사항 ·
  STEP 5 메자닌(CB·BW·EB)·유상증자·자금 목적 · STEP 6 최대주주·내부자·5% · STEP 7 직원·보수 · STEP 8 수급 세부
자동으로 걸리는 '모순 후보'에는 긍정·부정 해석을 둘 다 붙이고 확인할 원문 위치를 단다 (문서 A-2-5, A-3).
결론·매수 추천·목표가는 만들지 않는다. AI 초안(서버 claude -p, 도구 끔)은 사장님 로그인에서만.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
API = "https://opendart.fss.or.kr/api/"
VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
TTL = 6 * 3600                 # 모은 자료 6시간 재사용 (공시는 하루 몇 번 안 바뀜)
VERSION = 4                    # 모으는 방식 바꾸면 올림 → 옛 캐시 무시 (2: 가격대 · 3: 정기보고서 따로·등급 · 4: 못 믿을 PER 가격대 뺌)
CLAUDE = "/home/junp/.local/bin/claude"
WORKDIR = Path("/home/junp/tmp_claude/review_cli")
_locks: dict[str, threading.Lock] = {}
_ai_busy: set[str] = set()
REPRT = {"사업": "11011", "반기": "11012", "1Q": "11013", "3Q": "11014"}


def _key() -> str:
    try:
        return open(os.path.expanduser("~/.dart_key")).read().strip()
    except OSError:
        return os.getenv("DART_API_KEY", "")


def _get(ep: str, corp: str, **p) -> list[dict]:
    """DART 한 번 부르기 — 자료 없으면(013) 빈 목록. 실패도 빈 목록(화면엔 '못 받음' 대신 빈칸)."""
    for i in range(2):
        try:
            j = requests.get(API + ep + ".json", params={"crtfc_key": _key(), "corp_code": corp, **p}, timeout=20).json()
            if j.get("status") == "000":
                return j.get("list") or []
            if j.get("status") == "020":          # 요청 한도 — 잠깐 쉬고 한 번 더
                time.sleep(1.0)
                continue
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("DART %s 실패: %s", ep, type(exc).__name__)
            time.sleep(0.5)
    return []


def _n(s) -> float | None:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "－"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def _kdate(s: str | None) -> str | None:
    m = re.match(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", (s or "").strip())
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


# ── 정기보고서 목록 → 기간 ─────────────────────────────────────────
def _periods(corp: str) -> tuple[list[dict], list[dict]]:
    """최근 3년 반 정기보고서(사업·반기·분기). 같은 기간 정정본은 최신 접수만. 반환: (기간 목록 오래된→최신, 공시 전체 목록)."""
    bgn = (date.today() - timedelta(days=365 * 3 + 200)).strftime("%Y%m%d")
    allrows: list[dict] = []
    for page in range(1, 8):
        try:
            j = requests.get(API + "list.json", params={"crtfc_key": _key(), "corp_code": corp, "bgn_de": bgn, "page_count": 100, "page_no": page},
                             timeout=20).json()
        except Exception:  # noqa: BLE001
            break
        allrows += j.get("list") or []
        if page >= int(j.get("total_page") or 1):
            break
    periodic: list[dict] = []
    for page in range(1, 4):       # 정기보고서만 따로 — 삼성전자처럼 공시가 많으면 전체 목록 7쪽 안에 옛 보고서가 안 들어옴 (10/17)
        try:
            j = requests.get(API + "list.json", params={"crtfc_key": _key(), "corp_code": corp, "bgn_de": bgn, "pblntf_ty": "A", "page_count": 100,
                                                        "page_no": page}, timeout=20).json()
        except Exception:  # noqa: BLE001
            break
        periodic += j.get("list") or []
        if page >= int(j.get("total_page") or 1):
            break
    reps: dict[tuple, dict] = {}
    fy_m = 12
    for r in periodic or allrows:
        nm = re.sub(r"\s+", "", r.get("report_nm") or "")
        m = re.search(r"(사업|반기|분기)보고서\((\d{4})\.(\d{2})\)", nm)
        if not m:
            continue
        kind, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
        if kind == "사업":
            fy_m = mo
        k = (y, mo)
        if k not in reps or r["rcept_no"] > reps[k]["rcept_no"]:
            reps[k] = {"y": y, "m": mo, "kind": kind, "rcept_no": r["rcept_no"], "rcept_dt": r.get("rcept_dt")}
    out = []
    for (y, mo), r in sorted(reps.items()):
        if r["kind"] == "분기":
            r["kind"] = "1Q" if (mo - fy_m) % 12 == 3 else "3Q"
        r["code"] = REPRT[r["kind"]]
        r["bsns_year"] = str(y)      # 12월 결산 기준. 3월 결산 등은 _fin에서 한 해 앞도 시도.
        r["label"] = f"{str(y)[2:]}.{mo:02d} " + {"사업": "사업", "반기": "반기", "1Q": "1분기", "3Q": "3분기"}[r["kind"]]
        out.append(r)
    return out[-7:], allrows


# ── 재무제표 ───────────────────────────────────────────────────────
ACC = {   # 키: (account_id 후보, account_nm 후보)
    "rev": (["ifrs-full_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"]),
    "op": (["dart_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)", "영업손실"]),
    "pbt": (["ifrs-full_ProfitLossBeforeTax"], ["법인세비용차감전순이익", "법인세비용차감전순이익(손실)"]),
    "ni": (["ifrs-full_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "분기순이익(손실)", "반기순이익(손실)"]),
    "ni_own": (["ifrs-full_ProfitLossAttributableToOwnersOfParent"], []),
    "fin_inc": (["ifrs-full_FinanceIncome"], ["금융수익"]),
    "fin_cost": (["ifrs-full_FinanceCosts"], ["금융비용", "금융원가"]),
    "eqm": (["ifrs-full_ShareOfProfitLossOfAssociatesAccountedForUsingEquityMethod"], ["지분법이익", "지분법손익", "관계기업투자관련손익"]),
    "oth_gain": (["dart_OtherGains"], ["기타수익", "기타영업외수익"]),
    "oth_loss": (["dart_OtherLosses"], ["기타비용", "기타영업외비용"]),
    "ocf": (["ifrs-full_CashFlowsFromUsedInOperatingActivities"], ["영업활동현금흐름", "영업활동으로인한현금흐름"]),
    "capex": (["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"], ["유형자산의취득"]),
    "cash": (["ifrs-full_CashAndCashEquivalents"], ["현금및현금성자산"]),
    "recv": (["ifrs-full_TradeAndOtherCurrentReceivables", "ifrs-full_CurrentTradeReceivables", "dart_ShortTermTradeReceivable"], ["매출채권", "매출채권및기타채권", "매출채권및기타유동채권"]),
    "inv": (["ifrs-full_Inventories"], ["재고자산"]),
    "intan": (["ifrs-full_IntangibleAssetsOtherThanGoodwill"], ["무형자산"]),
    "stdep": (["ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents", "dart_ShortTermDepositsNotClassifiedAsCashEquivalents"], ["단기금융상품"]),
    "fvpl": (["ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"], ["당기손익-공정가치측정금융자산", "당기손익공정가치측정금융자산"]),
    "assets": (["ifrs-full_Assets"], ["자산총계"]),
    "liab": (["ifrs-full_Liabilities"], ["부채총계"]),
    "equity": (["ifrs-full_Equity"], ["자본총계"]),
}
SJ = {"rev": "IS", "op": "IS", "pbt": "IS", "ni": "IS", "ni_own": "IS", "fin_inc": "IS", "fin_cost": "IS", "eqm": "IS", "oth_gain": "IS", "oth_loss": "IS",
      "ocf": "CF", "capex": "CF"}


def _pick(rows: list[dict], key: str) -> dict | None:
    ids, nms = ACC[key]
    want = SJ.get(key, "BS")
    rs = [r for r in rows if (r.get("sj_div") in ("IS", "CIS") if want == "IS" else r.get("sj_div") == want)]
    for i in ids:
        for r in rs:
            if r.get("account_id") == i:
                return r
    for nm in nms:
        for r in rs:
            if re.sub(r"\s+", "", r.get("account_nm") or "") == nm:
                return r
    return None


def _debt(rows: list[dict]) -> tuple[float | None, float | None]:
    """차입금·사채 (유동, 전체). 리스부채·전환권조정·할인발행차금 뺌. 같은 계정 두 번 세지 않게 (id, 이름)으로 중복 제거."""
    cur = tot = 0.0
    seen = set()
    hit = False
    for r in rows:
        if r.get("sj_div") != "BS":
            continue
        nm = re.sub(r"\s+", "", r.get("account_nm") or "")
        aid = r.get("account_id") or ""
        fv = "FinancialLiabilitiesAtFairValueThroughProfitOrLoss" in aid or nm == "공정가치측정금융부채"     # 공정가치로 잡은 CB 등 (HLB 같은 곳)
        if not (re.search(r"차입|사채", nm) or "Borrow" in aid or fv) or re.search(r"자산|조정|할인|리스|상환할증|이자|비용|충당|채권|매입", nm):
            continue
        if nm in ("차입금및사채", "총차입금"):
            continue
        k = (aid, nm)
        if k in seen:
            continue
        seen.add(k)
        v = _n(r.get("thstrm_amount"))
        if v is None:
            continue
        hit = True
        tot += v
        if re.search(r"Current|ShortTerm|Shortterm", aid) and "Noncurrent" not in aid or re.search(r"단기|유동", nm) and "비유동" not in nm:
            cur += v
    return (cur, tot) if hit else (None, None)


def _fin(corp: str, p: dict) -> dict:
    rows, fs = [], None
    years = [p["bsns_year"]] + ([str(int(p["bsns_year"]) - 1)] if p.get("m") != 12 else [])
    for y in years:
        for div in ("CFS", "OFS"):
            rows = _get("fnlttSinglAcntAll", corp, bsns_year=y, reprt_code=p["code"], fs_div=div)
            if rows:
                fs = div
                break
        if rows:
            break
    out: dict = {"fs": fs, "v": {}, "ytd": {}, "pq": {}, "pytd": {}, "p1": {}, "p2": {}}
    if not rows:
        return out
    annual = p["kind"] == "사업"
    for k in ACC:
        r = _pick(rows, k)
        if r is None:
            continue
        sj = SJ.get(k, "BS")
        th, add = _n(r.get("thstrm_amount")), _n(r.get("thstrm_add_amount"))
        if sj == "IS":
            if annual:
                out["ytd"][k] = th
                out["p1"][k], out["p2"][k] = _n(r.get("frmtrm_amount")), _n(r.get("bfefrmtrm_amount"))
            else:
                out["v"][k] = th                                   # 분기 3개월
                out["ytd"][k] = add if add is not None else th     # 누계 (1분기는 같음)
                out["pq"][k] = _n(r.get("frmtrm_q_amount")) if r.get("frmtrm_q_amount") is not None else _n(r.get("frmtrm_amount"))
                out["pytd"][k] = _n(r.get("frmtrm_add_amount")) if r.get("frmtrm_add_amount") is not None else _n(r.get("frmtrm_amount"))
        elif sj == "CF":
            out["ytd"][k] = th
            if annual:
                out["p1"][k], out["p2"][k] = _n(r.get("frmtrm_amount")), _n(r.get("bfefrmtrm_amount"))
            else:
                out["pytd"][k] = _n(r.get("frmtrm_amount"))
        else:
            out["v"][k] = th
            if annual:
                out["p1"][k] = _n(r.get("frmtrm_amount"))
    out["v"]["debt_cur"], out["v"]["debt"] = _debt(rows)
    return out


def _emp(corp: str, y: str, rc: str) -> dict | None:
    L = _get("empSttus", corp, bsns_year=y, reprt_code=rc)
    if not L:
        return None
    tot = sum(_n(x.get("sm")) or 0 for x in L)
    pay = sum(_n(x.get("fyer_salary_totamt")) or 0 for x in L)
    yrs = []
    for x in L:
        m = re.match(r"(?:(\d+)년)?\s*(?:(\d+)개월)?", (x.get("avrg_cnwk_sdytrn") or "").replace(" ", ""))
        w = _n(x.get("sm")) or 0
        if m and (m.group(1) or m.group(2)) and w:
            yrs.append(((int(m.group(1) or 0) + int(m.group(2) or 0) / 12), w))
        elif _n(x.get("avrg_cnwk_sdytrn")) is not None and w:
            yrs.append((_n(x.get("avrg_cnwk_sdytrn")), w))
    ten = sum(a * w for a, w in yrs) / sum(w for _, w in yrs) if yrs else None
    return {"n": tot or None, "tenure": round(ten, 1) if ten else None, "pay": pay or None, "avg_pay": pay / tot if tot and pay else None}


def _holders(corp: str, y: str, rc: str) -> dict | None:
    L = _get("hyslrSttus", corp, bsns_year=y, reprt_code=rc)
    if not L:
        return None
    com = [x for x in L if "보통" in (x.get("stock_knd") or "") and (x.get("nm") or "") not in ("계", "합계")]
    rows = [{"name": x.get("nm"), "rel": x.get("relate"), "begin": _n(x.get("bsis_posesn_stock_qota_rt")), "end": _n(x.get("trmend_posesn_stock_qota_rt")),
             "shares": _n(x.get("trmend_posesn_stock_co")), "note": (x.get("rm") or "").strip(" -")} for x in com]
    rows.sort(key=lambda r: -(r["end"] or 0))
    tot = sum(r["end"] or 0 for r in rows)
    return {"total": round(tot, 2), "rows": rows[:15], "n": len(rows)}


# ── 이벤트 공시 (5년) ───────────────────────────────────────────────
def _mezz(corp: str, shares: float | None) -> list[dict]:
    bgn, end = (date.today() - timedelta(days=365 * 5)).strftime("%Y%m%d"), date.today().strftime("%Y%m%d")
    out = []
    for ep, kind in (("cvbdIsDecsn", "CB"), ("bdwtIsDecsn", "BW"), ("exbdIsDecsn", "EB")):
        for x in _get(ep, corp, bgn_de=bgn, end_de=end):
            face = _n(x.get("bd_fta"))
            price = _n(x.get("cv_prc") or x.get("ex_prc"))
            floor = _n(x.get("act_mktprcfl_cvprc_lwtrsprc"))
            cnt = _n(x.get("cvisstk_cnt") or x.get("nstk_isstk_cnt") or x.get("extg_stkcnt"))
            pct = _n(x.get("cvisstk_tisstk_vs") or x.get("nstk_isstk_tisstk_vs") or x.get("extg_tisstk_vs"))
            mat = _kdate(x.get("bd_mtd"))
            purpose = {k: _n(x.get(f)) for k, f in (("시설", "fdpp_fclt"), ("영업양수", "fdpp_bsninh"), ("운영", "fdpp_op"), ("채무상환", "fdpp_dtrp"),
                                                   ("타법인 증권 취득", "fdpp_ocsa"), ("기타", "fdpp_etc")) if _n(x.get(f))}
            floor_cnt = face / floor if face and floor and kind != "EB" else None
            out.append({"kind": kind, "date": _kdate(x.get("bddd")), "pay": _kdate(x.get("pymd")), "face": face, "price": price, "floor": floor,
                        "shares": cnt, "pct": pct, "floor_pct": round(floor_cnt / shares * 100, 2) if floor_cnt and shares else None,
                        "maturity": mat, "live": bool(mat and mat >= date.today().isoformat()), "method": x.get("bdis_mthn"),
                        "rate": [_n(x.get("bd_intr_ex")), _n(x.get("bd_intr_sf"))], "purpose": purpose,
                        "call": (x.get("ex_sm_r") or "").strip(" -")[:120], "rcp": x.get("rcept_no")})
    out.sort(key=lambda r: r["date"] or "")
    return out


def _rights(corp: str) -> list[dict]:
    bgn, end = (date.today() - timedelta(days=365 * 5)).strftime("%Y%m%d"), date.today().strftime("%Y%m%d")
    out = []
    for x in _get("piicDecsn", corp, bgn_de=bgn, end_de=end):
        new, before = _n(x.get("nstk_ostk_cnt")), _n(x.get("bfic_tisstk_ostk"))
        purpose = {k: _n(x.get(f)) for k, f in (("시설", "fdpp_fclt"), ("영업양수", "fdpp_bsninh"), ("운영", "fdpp_op"), ("채무상환", "fdpp_dtrp"),
                                               ("타법인 증권 취득", "fdpp_ocsa"), ("기타", "fdpp_etc")) if _n(x.get(f))}
        out.append({"rcp": x.get("rcept_no"), "date": f"{x['rcept_no'][:4]}-{x['rcept_no'][4:6]}-{x['rcept_no'][6:8]}" if x.get("rcept_no") else None,
                    "method": x.get("ic_mthn"), "new": new, "pct": round(new / before * 100, 2) if new and before else None,
                    "amount": sum(purpose.values()) or None, "purpose": purpose})
    out.sort(key=lambda r: r["date"] or "")
    return out


def _insiders(corp: str) -> list[dict]:
    since = (date.today() - timedelta(days=730)).isoformat()
    out = []
    for x in _get("elestock", corp):
        d = x.get("rcept_dt") or ""
        if d < since:
            continue
        out.append({"date": d, "name": x.get("repror"), "pos": " ".join(v for v in (x.get("isu_exctv_ofcps"), x.get("isu_exctv_rgist_at"), x.get("isu_main_shrholdr"))
                                                                         if v and v != "-"),
                    "chg": _n(x.get("sp_stock_lmp_irds_cnt")), "after": _n(x.get("sp_stock_lmp_cnt")), "pct": _n(x.get("sp_stock_lmp_rate")), "rcp": x.get("rcept_no")})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def _blocks(corp: str) -> list[dict]:
    since = (date.today() - timedelta(days=365 * 3)).isoformat()
    out = [{"date": x.get("rcept_dt"), "name": x.get("repror"), "pct": _n(x.get("stkrt")), "chg": _n(x.get("stkrt_irds")), "why": (x.get("report_resn") or "")[:120],
            "rcp": x.get("rcept_no")} for x in _get("majorstock", corp) if (x.get("rcept_dt") or "") >= since]
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out


def _audit(corp: str, y: str) -> list[dict]:
    seen, out = set(), []
    for x in _get("accnutAdtorNmNdAdtOpinion", corp, bsns_year=y, reprt_code="11011"):
        k = (x.get("bsns_year"), x.get("adtor"), x.get("adt_opinion"))
        if k in seen:
            continue
        seen.add(k)
        out.append({"term": re.sub(r"\s+", " ", x.get("bsns_year") or ""), "auditor": x.get("adtor"), "opinion": x.get("adt_opinion"),
                    "emphasis": (x.get("adt_reprt_spcmnt_matter") or "").strip(" -"), "kam": (x.get("core_adt_matter") or "").strip(" -")})
    return out


def _payouts(corp: str, y: str) -> dict:
    """배당(3년) · 이사·감사 보수 · 자사주 변동 · 최대주주 변동 — 사업보고서 기준."""
    out: dict = {}
    div = {}
    for x in _get("alotMatter", corp, bsns_year=y, reprt_code="11011"):
        se = re.sub(r"\s+", "", x.get("se") or "")
        if se.startswith("현금배당금총액"):
            div = {"y0": _n(x.get("thstrm")), "y1": _n(x.get("frmtrm")), "y2": _n(x.get("lwfr"))}       # 백만원
        elif "(연결)당기순이익" in se:
            out["ni_cfs"] = {"y0": _n(x.get("thstrm")), "y1": _n(x.get("frmtrm")), "y2": _n(x.get("lwfr"))}
        elif "(별도)당기순이익" in se:
            out["ni_ofs"] = {"y0": _n(x.get("thstrm")), "y1": _n(x.get("frmtrm")), "y2": _n(x.get("lwfr"))}
        elif "현금배당성향" in se and "연결" in se:
            out["payout"] = _n(x.get("thstrm"))
    out["div"] = div
    h = _get("hmvAuditAllSttus", corp, bsns_year=y, reprt_code="11011")
    if h:
        out["exec"] = {"n": _n(h[0].get("nmpr")), "total": _n(h[0].get("mendng_totamt")), "avg": _n(h[0].get("jan_avrg_mendng_am"))}
    acq = dsp = burn = 0.0
    for x in _get("tesstkAcqsDspsSttus", corp, bsns_year=y, reprt_code="11011"):
        if "총계" in (x.get("acqs_mth1") or "") and "보통" in (x.get("stock_knd") or ""):
            acq, dsp, burn = _n(x.get("change_qy_acqs")) or 0, _n(x.get("change_qy_dsps")) or 0, _n(x.get("change_qy_incnr")) or 0
            out["treasury_end"] = _n(x.get("trmend_qy"))
    out["treasury"] = {"acq": acq, "dsp": dsp, "burn": burn}
    chg = [{"date": _kdate(x.get("change_on")) or x.get("change_on"), "name": x.get("mxmm_shrholdr_nm"), "pct": _n(x.get("qota_rt")), "why": (x.get("change_cause") or "").strip(" -")}
           for x in _get("hyslrChgSttus", corp, bsns_year=y, reprt_code="11011") if (x.get("mxmm_shrholdr_nm") or "-") != "-"]
    out["owner_changes"] = chg
    use = []
    for ep in ("prvsrpCptalUseDtls", "pssrpCptalUseDtls"):
        for x in _get(ep, corp, bsns_year=y, reprt_code="11011"):
            plan = (x.get("mtrpt_cptal_use_plan_useprps") or x.get("rs_cptal_use_plan_useprps") or x.get("cptal_use_plan") or "").strip(" -")
            real = (x.get("real_cptal_use_dtls_cn") or "").strip(" -")
            if plan or real:
                use.append({"kind": "사모" if ep.startswith("prv") else "공모", "when": (x.get("pay_de") or x.get("tm") or "").strip(" -"), "amount": _n(x.get("pay_amount")),
                            "plan": plan[:160], "real": real[:160], "diff": (x.get("dffrnc_occrrnc_resn") or "").strip(" -")[:160]})
    out["fund_use"] = use[:12]
    return out


def _shares(corp: str, y: str, rc: str) -> dict:
    for x in _get("stockTotqySttus", corp, bsns_year=y, reprt_code=rc):
        if (x.get("se") or "") in ("합계", "보통주"):
            return {"issued": _n(x.get("istc_totqy")), "treasury": _n(x.get("tesstk_co")), "float": _n(x.get("distb_stock_co"))}
    return {}


# ── 수급 세부 (KIS, 최근 약 120거래일) ────────────────────────────────
WHO = [("frgn", "외국인"), ("pe_fund", "사모"), ("fund", "연기금"), ("ivtr", "투신"), ("scrt", "금융투자"), ("insu", "보험"), ("bank", "은행"),
       ("etc_corp", "기타법인"), ("prsn", "개인")]


def _flows(code: str, days: int = 120) -> dict | None:
    try:
        from backend.collector.spot import _get_kis_token  # noqa: PLC0415
        tok = _get_kis_token()
    except Exception as exc:  # noqa: BLE001
        logger.warning("포렌식 수급: KIS 토큰 실패 %s", type(exc).__name__)
        return None
    h = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {tok}", "appkey": os.getenv("KIS_APP_KEY", ""),
         "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": "FHPTJ04160001", "custtype": "P"}
    rows: dict[str, dict] = {}
    end = date.today()
    for _ in range(12):
        try:
            r = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily", headers=h,
                             params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": end.strftime("%Y%m%d"), "FID_ORG_ADJ_PRC": "",
                                     "FID_ETC_CLS_CODE": "1"}, timeout=15).json()
        except Exception:  # noqa: BLE001
            break
        o = [x for x in r.get("output2") or [] if x.get("stck_bsop_date") and x["stck_bsop_date"] not in rows]
        if not o:
            if not rows and (date.today() - end).days < 5:     # 주말·휴일이면 빈 값 — 하루씩 앞으로
                end -= timedelta(days=1)
                time.sleep(0.2)
                continue
            break
        for x in o:
            rows[x["stck_bsop_date"]] = x
        end = datetime.strptime(min(x["stck_bsop_date"] for x in o), "%Y%m%d").date() - timedelta(days=1)
        if len(rows) >= days:
            break
        time.sleep(0.2)
    if not rows:
        return None
    L = [rows[k] for k in sorted(rows)][-days:]
    last = _n(L[-1].get("stck_clpr"))
    tv = sum(_n(x.get("acml_tr_pbmn")) or 0 for x in L) / 1e8           # 원 → 억
    out = {"from": L[0]["stck_bsop_date"], "to": L[-1]["stck_bsop_date"], "days": len(L), "close": last, "tv_eok": round(tv), "who": []}
    for k, nm in WHO:
        qk = f"{k}_ntby_vol" if k in ("pe_fund", "etc_corp") else f"{k}_ntby_qty"
        amt = [(_n(x.get(f"{k}_ntby_tr_pbmn")) or 0) / 100 for x in L]     # 백만원 → 억
        qty = [_n(x.get(qk)) or 0 for x in L]
        buy = sum((_n(x.get(f"{k}_shnu_tr_pbmn")) or 0) for x in L) / 100
        a20, a60, aall = sum(amt[-20:]), sum(amt[-60:]), sum(amt)
        q = sum(qty)
        avg = (aall * 1e8 / q) if q > 0 and aall > 0 else None                  # 순매수 쪽일 때만 평단 [추정]
        out["who"].append({"key": k, "name": nm, "d20": round(a20), "d60": round(a60), "all": round(aall), "qty": q,
                           "avg": round(avg) if avg else None, "pnl": round((last / avg - 1) * 100, 1) if avg and last else None,
                           "share": round(buy / tv * 100, 1) if tv else None})
    return out


# ── 모순 후보 (자동) ──────────────────────────────────────────────────
def _flag(level: str, title: str, fact: str, a: str, b: str, where: str, step: str, rcp: str | None = None) -> dict:
    return {"level": level, "title": title, "fact": fact, "a": a, "b": b, "where": where, "step": step, "rcp": rcp}


def _eok(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v / 1e12:,.2f}조" if abs(v) >= 1e12 else f"{v / 1e8:,.0f}억"


def _flags(d: dict) -> list[dict]:
    F: list[dict] = []
    P = d.get("periods") or []
    ann = [p for p in P if p["kind"] == "사업"]
    la = ann[-1] if ann else None
    lp = P[-1] if P else None
    rc_a = la["rcept_no"] if la else None
    src_a = f"[{la['label']} 연결/별도={la['fin'].get('fs') or '-'}]" if la else ""
    # 1) 실적 vs 현금 — 3개 사업연도 누적 (한 사업보고서에 당기·전기·전전기)
    if la:
        f = la["fin"]
        ni = [f["ytd"].get("ni"), f["p1"].get("ni"), f["p2"].get("ni")]
        cf = [f["ytd"].get("ocf"), f["p1"].get("ocf"), f["p2"].get("ocf")]
        if all(v is not None for v in ni + cf):
            sni, scf = sum(ni), sum(cf)
            d["quality"] = {"ni": ni, "ocf": cf, "sni": sni, "socf": scf}
            neg_cf = sum(1 for v in cf if v < 0)
            if sni > 0 and (scf < sni * 0.5 or neg_cf >= 2):
                F.append(_flag("⚠️", "실적 vs 현금 — 순이익만큼 현금이 안 들어옴",
                               f"3년 누적 순이익 {_eok(sni)} · 영업현금흐름 {_eok(scf)} (영업CF 적자 {neg_cf}년) {src_a} 현금흐름표",
                               "수주 증가로 매출채권·재고를 먼저 쌓는 성장기일 수 있다 (수주잔고·선수금이 같이 늘었는지)",
                               "매출 밀어내기나 회수 안 되는 채권일 수 있다 — '실적 좋은데 왜 안 가?'의 답 후보",
                               "사업보고서 III. 재무에 관한 사항 → 현금흐름표, 주석 '매출채권'(연령·대손충당금)", "STEP 3-1", rc_a))
    # 1-2) 적자 + 현금 소진
    if la and lp:
        ocf_y = la["fin"]["ytd"].get("ocf")
        v = lp["fin"]["v"]
        liq = sum(x for x in (v.get("cash"), v.get("stdep"), v.get("fvpl")) if x)
        op3 = [la["fin"]["ytd"].get("op"), la["fin"]["p1"].get("op"), la["fin"]["p2"].get("op")]
        if ocf_y is not None and ocf_y < 0 and liq:
            yrs = liq / -ocf_y
            F.append(_flag("⛔" if yrs < 1 else "⚠️" if yrs < 3 else "ℹ️", f"영업현금 적자 — 지금 돈으로 약 {yrs:.1f}년 [추정]",
                           f"{la['label']} 영업현금흐름 {_eok(ocf_y)} · {lp['label']} 현금+단기금융상품+단기 공정가치 금융자산 {_eok(liq)} (식: {_eok(liq)} ÷ {_eok(-ocf_y)})"
                           + (f" · 차입금·사채 {_eok(v.get('debt'))}" if v.get("debt") else ""),
                           "곧 매출이 붙는 단계(허가·양산 직전)라 버티기만 하면 될 수 있다", "추가 증자·메자닌 없이는 못 버틴다 — 주주 돈으로 메우는 구조일 수 있다",
                           "현금흐름표 · 주석 '금융상품' · 최근 증자·메자닌 공시", "STEP 3-1", lp["rcept_no"]))
        if all(x is not None and x < 0 for x in op3):
            F.append(_flag("ℹ️", "영업적자 3년 연속", " · ".join(_eok(x) for x in reversed(op3)) + f" {src_a}",
                           "바이오·신사업처럼 원래 적자를 감수하는 단계일 수 있다 — 그렇다면 펀더 분석은 제한적, 차트·매크로 중심 영역",
                           "본업 경쟁력이 없는데 테마로 버티는 것일 수 있다", "II. 사업의 내용 · IV. 경영진단 및 분석의견", "STEP 1", rc_a))
    # 2) 본업 vs 일회성
    if lp:
        f = lp["fin"]
        op, ni, pbt = f["ytd"].get("op"), f["ytd"].get("ni"), f["ytd"].get("pbt")
        if op is not None and ni is not None and op < 0 < ni:
            parts = ", ".join(f"{nm} {_eok(f['ytd'].get(k))}" for k, nm in (("fin_inc", "금융수익"), ("fin_cost", "금융비용"), ("eqm", "지분법"),
                                                                             ("oth_gain", "기타수익"), ("oth_loss", "기타비용")) if f["ytd"].get(k))
            F.append(_flag("⚠️", "본업 vs 일회성 — 영업적자인데 순이익 흑자",
                           f"{lp['label']} 누계 영업이익 {_eok(op)} · 순이익 {_eok(ni)} (영업외: {parts or '세부 없음'})",
                           "지분법 자회사 이익처럼 실체 있는 영업외 이익일 수 있다", "자산 처분·평가이익으로 흑자를 만든 것일 수 있다 ('땅 팔아 순이익형')",
                           "손익계산서 영업외 항목 → 주석 '기타수익·금융수익'(처분이익·평가이익)", "STEP 3-1", lp["rcept_no"]))
        if op is not None and pbt is not None and op > 0 and abs(pbt - op) > abs(op) * 0.5:
            F.append(_flag("ℹ️", "영업이익과 세전이익 차이가 큼", f"{lp['label']} 누계 영업이익 {_eok(op)} · 세전이익 {_eok(pbt)}",
                           "지분법·이자수익 등 꾸준한 영업외 이익일 수 있다", "일회성 평가·처분 손익이 숫자를 흔든 것일 수 있다 — 경상 이익을 다시 계산",
                           "손익계산서 영업외 항목 · 주석 금융수익/비용", "STEP 3-1", lp["rcept_no"]))
    # 3) 운전자본 — 같은 분기 1년 전과
    if lp:
        prev = next((p for p in P if p["y"] == lp["y"] - 1 and p["m"] == lp["m"]), None)
        f = lp["fin"]
        if prev:
            g = prev["fin"]
            r1, r0 = f["ytd"].get("rev"), f["pytd"].get("rev") if lp["kind"] != "사업" else f["p1"].get("rev")
            if r1 and r0:
                rg = (r1 / r0 - 1) * 100
                for k, nm in (("recv", "매출채권"), ("inv", "재고자산")):
                    a1, a0 = f["v"].get(k), g["v"].get(k)
                    if a1 and a0 and a0 > 0:
                        gk = (a1 / a0 - 1) * 100
                        if gk - rg > 25 and a1 > r1 * 0.1:
                            F.append(_flag("⚠️", f"{nm}가 매출보다 빨리 늘어남",
                                           f"{lp['label']} {nm} {_eok(a1)} (1년 전 {_eok(a0)}, {gk:+.0f}%) vs 누계 매출 {rg:+.0f}%",
                                           "다음 분기 큰 납품을 앞둔 선투입일 수 있다", "밀어내기·부실 채권·안 팔리는 재고일 수 있다 (충당금·평가손실 확인)",
                                           f"주석 '{nm}' — 연령 분석, 대손충당금/평가손실", "STEP 3-2", lp["rcept_no"]))
    # 4) 유동성
    if lp:
        v = lp["fin"]["v"]
        if v.get("debt_cur") and v.get("cash") is not None and v["debt_cur"] > max(v["cash"], 1) * 2 and v["debt_cur"] > 5e9:
            F.append(_flag("⚠️", "단기 차입이 현금의 2배 넘음", f"{lp['label']} 유동 차입금·사채 {_eok(v['debt_cur'])} · 현금 {_eok(v['cash'])}",
                           "만기 연장이 늘 되는 은행 차입이거나 정책성 저금리 대출일 수 있다", "차환이 막히면 증자·메자닌으로 메워야 하는 구조일 수 있다",
                           "주석 '차입금'(만기·금리·담보) · 우발부채", "STEP 3-4", lp["rcept_no"]))
    # 5) 감사
    for a in d.get("audit") or []:
        if "당기" not in (a.get("term") or ""):
            continue
        if a.get("opinion") and "적정" not in a["opinion"]:
            F.append(_flag("⛔", f"감사의견 {a['opinion']}", f"{a['term']} {a.get('auditor')} · {a['opinion']}", "-", "거래정지·상장폐지 사유가 될 수 있다",
                           "감사보고서 감사의견 근거 문단", "STEP 4", rc_a))
        if re.search(r"계속기업", a.get("emphasis") or ""):
            F.append(_flag("⛔", "계속기업 불확실성 기재", f"강조사항: {a['emphasis'][:120]}", "추가 자금이 확보되면 해소될 수 있다",
                           "추가 자금 수혈 없이는 위험하다는 뜻 — 증자·메자닌이 이어질 가능성", "감사보고서 강조사항 · 주석 '계속기업'", "STEP 4", rc_a))
        elif a.get("emphasis"):
            F.append(_flag("ℹ️", "감사보고서 강조사항 있음", a["emphasis"][:160], "의견에 영향 없는 설명일 수 있다", "투자자가 꼭 알아야 할 사건일 수 있다",
                           "감사보고서 강조사항", "STEP 4", rc_a))
        break
    terms = [(a.get("term"), a.get("auditor")) for a in d.get("audit") or [] if a.get("auditor")]
    if len({t[1] for t in terms}) > 1:
        F.append(_flag("⚠️", "최근 3년 안에 감사인이 바뀜", " → ".join(f"{t[0]} {t[1]}" for t in reversed(terms)),
                       "주기적 지정감사(6년 자유선임 뒤 3년 지정)라 자연스러운 교체일 수 있다", "회사와 감사인 사이 이견으로 바뀐 것일 수 있다",
                       "사업보고서 V. 회계감사인의 감사의견 등 — 감사인 변경 사유", "STEP 4", rc_a))
    # 6) 메자닌 잠재 물량
    sh = (d.get("shares") or {}).get("issued")
    live = [m for m in d.get("mezz") or [] if m.get("live") and m["kind"] in ("CB", "BW")]
    if live:
        tot = sum((m.get("shares") or 0) for m in live)
        fl = sum((m["face"] / m["floor"]) for m in live if m.get("face") and m.get("floor"))
        pct = tot / sh * 100 if sh else None
        lvl = "⛔" if pct and pct >= 10 else "⚠️"
        F.append(_flag(lvl, "만기 안 지난 CB·BW — 미래 주식 공급",
                       f"{len(live)}건 · 발행 때 전환 주식 {tot:,.0f}주" + (f" (지금 발행주식의 {pct:.1f}%)" if pct else "")
                       + (f" · 리픽싱 하한까지 내리면 최대 약 {fl:,.0f}주 [추정]" if fl else "") + " · 이미 전환·상환된 몫은 빠지지 않은 수 [추정]",
                       "이미 전환·상환됐거나 콜옵션으로 회사·대주주가 사 갔을 수 있다", "주가가 전환가 위로 가면 매물, 아래로 가면 리픽싱으로 물량이 늘어난다",
                       "사업보고서 '미상환 전환사채 등 발행현황' · 각 발행결정 공시(인수자·콜옵션)", "STEP 5-1", live[-1].get("rcp")))
    for m in d.get("mezz") or []:
        if m.get("purpose", {}).get("타법인 증권 취득"):
            F.append(_flag("⚠️", f"{m['kind']} 자금이 타법인 증권 취득으로", f"{m['date']} {m['kind']} {_eok(m.get('face'))} 중 타법인 증권 취득 {_eok(m['purpose']['타법인 증권 취득'])}",
                           "본업과 맞는 인수·투자일 수 있다", "외부로 돈이 빠지는 '자금 회전' 패턴일 수 있다 — 그 타법인과 그 대주주를 열어 볼 것",
                           "발행결정 공시 '자금조달의 목적' · 타법인 출자 현황", "STEP 5-2", m.get("rcp")))
            break
    # 6-2) 회사가 자기 CB를 만기 전에 사들임 · 최대주주 주식담보
    buyback = [e for e in (d.get("disc") or {}).get("events") or [] if "만기전사채취득" in re.sub(r"\s+", "", e["title"])]
    if buyback:
        F.append(_flag("⚠️", f"만기 전 사채 취득 {len(buyback)}건 (1년)", " · ".join(f"{e['date'][:4]}.{e['date'][4:6]}.{e['date'][6:]}" for e in buyback[:5]),
                       "사들인 CB를 소각하면 미래 물량이 줄어든다", "소각하지 않고 다시 팔거나(재매각) 대주주 콜옵션으로 넘기면 물량이 그대로 대기한다 — 처리 방법 확인",
                       "'전환사채 발행후 만기전 사채취득' 공시 — 취득 뒤 처리(소각/재매각) 항목", "STEP 5-1", buyback[0].get("rcp")))
    pledge = [b for b in d.get("blocks") or [] if "담보" in (b.get("why") or "")]
    if pledge:
        F.append(_flag("⚠️", "최대주주 쪽 주식담보 계약", " · ".join(f"{b['date']} {b['name']} ({b['why'][:30]})" for b in pledge[:3]),
                       "운영자금·세금용 단순 대출일 수 있다", "주가가 빠지면 반대매매 물량이 나올 수 있다 — 대주주가 주가를 높게 원할 유인(6-2)",
                       "대량보유상황보고서 '주식등에 관한 계약' — 담보 주식 수·대출 기관·담보 비율", "STEP 5-1", pledge[0].get("rcp")))
    # 7) 유상증자
    rs = d.get("rights") or []
    if len(rs) >= 2 or any("제3자" in (r.get("method") or "") for r in rs):
        F.append(_flag("⚠️", "유상증자 이력", " · ".join(f"{r['date']} {r.get('method') or ''} {('신주 ' + format(r['pct'], '.1f') + '%') if r.get('pct') else ''}" for r in rs[-4:]),
                       "성장 투자(시설) 목적이고 대주주도 참여했다면 다르게 볼 수 있다", "대주주는 자기 돈 안 넣고 주주 돈으로만 조달하는 구조일 수 있다",
                       "증권신고서·발행결정 공시 — 배정 대상자, 자금 목적, 대주주 참여 여부", "STEP 5-2", rs[-1].get("rcp")))
    # 8) 최대주주
    h = d.get("holders") or {}
    if h.get("total") is not None and 0 < h["total"] < 20:
        F.append(_flag("⚠️", "최대주주+특수관계인 지분 20% 아래", f"{h['total']:.1f}% {('[' + lp['label'] + ']') if lp else ''}",
                       "지분이 분산된 전문경영 회사일 수 있다", "경영권이 약해 최대주주 변경·무자본 M&A 대상이 되기 쉽다",
                       "VII. 주주에 관한 사항", "STEP 6-1", lp["rcept_no"] if lp else None))
    pay = d.get("payouts") or {}
    if pay.get("owner_changes"):
        F.append(_flag("⚠️", "최대주주 변동 이력", " · ".join(f"{c['date']} {c['name']} {c.get('pct') or ''}% ({c.get('why') or ''})" for c in pay["owner_changes"][:3]),
                       "상속·증여·지주 전환 같은 정리일 수 있다", "대주주 교체 뒤 사업목적 추가·증자·메자닌이 이어지는 패턴인지 확인",
                       "VII. 주주에 관한 사항 → 최대주주 변동현황 · 정관 사업목적 변경", "STEP 6-1", rc_a))
    # 9) 내부자
    ins = d.get("insiders") or []
    one = [x for x in ins if x["date"] >= (date.today() - timedelta(days=365)).isoformat()]
    buys = [x for x in one if (x.get("chg") or 0) > 0]
    sells = [x for x in one if (x.get("chg") or 0) < 0]
    if buys:
        F.append(_flag("ℹ️", f"임원·주요주주 지분 증가 보고 {len(buys)}건 (1년)", " · ".join(f"{x['date']} {x['name']} {x['chg']:+,.0f}주" for x in buys[:4]),
                       "대표·임원이 자기 돈으로 장내 매수했다면 1차 스크리닝 최우선 신호", "그룹 일괄 매수 지시(전시용)·작전주의 '사는 척'일 수 있다 — 규모가 보수 대비 의미 있는지, 이어지는지",
                       "임원·주요주주 특정증권등 소유상황보고서 (장내매수인지, 증여·주식보상인지)", "STEP 6-3", buys[0].get("rcp")))
    if len(sells) >= 3:
        F.append(_flag("⚠️", f"임원·주요주주 지분 감소 보고 {len(sells)}건 (1년)", " · ".join(f"{x['date']} {x['name']} {x['chg']:+,.0f}주" for x in sells[:4]),
                       "세금 납부·생활 자금·스톡옵션 행사 뒤 매도일 수 있다", "내부자가 지금 값을 비싸다고 보는 것일 수 있다 (연달아 나오면 청산 구간)",
                       "임원·주요주주 특정증권등 소유상황보고서", "STEP 6-3", sells[0].get("rcp")))
    # 10) 직원
    emp = d.get("employees") or []
    ea = [e for e in emp if e.get("kind") == "사업" and e.get("n")]
    if len(ea) >= 2 and ea[-2]["n"] and ea[-1]["n"] / ea[-2]["n"] - 1 <= -0.2:
        F.append(_flag("⚠️", "직원 수 급감", f"{ea[-2]['label']} {ea[-2]['n']:,.0f}명 → {ea[-1]['label']} {ea[-1]['n']:,.0f}명",
                       "사업 정리·자회사 분할로 인원이 옮겨 간 것일 수 있다", "핵심 인력 이탈 = 경쟁력 훼손 신호 (특히 연구개발 인력)",
                       "VIII. 임원 및 직원 등에 관한 사항 → 직원 등 현황(사업부문별)", "STEP 7", rc_a))
    # 11) 주주에게 오는가
    if la:
        ni0 = la["fin"]["ytd"].get("ni_own") or la["fin"]["ytd"].get("ni")
        dv = (pay.get("div") or {}).get("y0")
        tr = pay.get("treasury") or {}
        ex = pay.get("exec") or {}
        if ni0 and ni0 > 0 and not dv and not tr.get("acq"):
            F.append(_flag("ℹ️", "흑자인데 배당·자사주 매입 없음", f"{la['label']} 순이익 {_eok(ni0)} · 현금배당 없음 · 자사주 취득 없음"
                           + (f" · 등기임원 보수 {_eok(ex.get('total'))}" if ex.get("total") else ""),
                           "성장 투자에 돈이 필요한 시기일 수 있다", "실적이 좋아도 주주에게 오지 않는 구조일 수 있다 (보수·특수관계자 거래와 비교)",
                           "배당에 관한 사항 · 임원 보수 · 이해관계자와의 거래", "STEP 6-2", rc_a))
    # 12) 공시 습관
    di = d.get("disc") or {}
    if di.get("fix", 0) >= 6:
        F.append(_flag("ℹ️", f"정정공시 많음 ({di['fix']}건, 1년)", "같은 사실을 몇 번씩 고쳐 냄", "단순 오기 수정일 수 있다", "공시 관리가 허술하거나 숫자를 바꿔 가는 중일 수 있다",
                       "DART 공시 목록에서 [기재정정] 원본과 비교", "STEP 2-2"))
    if di.get("bad"):
        F.append(_flag("⛔", "불성실공시·투자주의 관련 공시", " · ".join(di["bad"][:3]), "-", "공시 신뢰도 자체를 다시 봐야 한다", "거래소 공시", "STEP 2-2"))
    order = {"⛔": 0, "⚠️": 1, "ℹ️": 2, "✅": 3}
    F.sort(key=lambda x: order.get(x["level"], 9))
    return F


def _disc_summary(allrows: list[dict]) -> dict:
    since = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
    one = [r for r in allrows if (r.get("rcept_dt") or "") >= since]
    nm = lambda r: re.sub(r"\s+", "", r.get("report_nm") or "")  # noqa: E731
    out = {"n": len(one), "fix": sum(1 for r in one if "정정" in nm(r)),
           "inquiry": [f"{r['rcept_dt']} {r['report_nm']}" for r in one if "조회공시" in nm(r)][:5],
           "bad": [f"{r['rcept_dt']} {r['report_nm']}" for r in one if re.search(r"불성실공시|투자주의환기|관리종목|상장적격성", nm(r))][:5],
           "valueup": [{"date": r["rcept_dt"], "title": r["report_nm"], "rcp": r["rcept_no"]} for r in allrows if "기업가치제고" in nm(r)][:3],
           "events": []}
    keys = ("유상증자", "전환사채", "신주인수권부사채", "교환사채", "최대주주변경", "자기주식", "단일판매", "공급계약", "타법인주식", "영업양수", "영업양도", "분할", "합병",
            "소송", "주식등의대량보유", "임원ㆍ주요주주", "기업가치제고", "감자", "무상증자", "조회공시", "횡령", "배임")
    for r in one:
        n = nm(r)
        if any(k in n for k in keys) and "임원ㆍ주요주주특정증권" not in n:
            out["events"].append({"date": r["rcept_dt"], "title": r["report_nm"].strip(), "by": r.get("flr_nm"), "rcp": r["rcept_no"]})
    out["events"] = out["events"][:40]
    return out


# ── 모으기 ───────────────────────────────────────────────────────────
def _ensure(db: Session) -> None:
    db.execute(text("create table if not exists forensic_cache (code varchar(12) primary key, data jsonb not null, built_at timestamptz default now())"))
    db.execute(text("""create table if not exists forensic_notes (owner varchar(40) not null, code varchar(12) not null, name varchar(80), verdict varchar(20),
        checks jsonb, checkpoints text, memo text, updated_at timestamptz default now(), primary key (owner, code))"""))
    db.execute(text("""create table if not exists forensic_ai (id serial primary key, owner varchar(40) not null, code varchar(12) not null, name varchar(80),
        status varchar(20), output text, created_at timestamptz default now(), done_at timestamptz)"""))
    db.commit()


def build(code: str) -> dict:
    from dart_analyzer.corp_code import find_corp  # noqa: PLC0415
    t0 = time.time()
    corp = find_corp(code)
    if corp is None:
        raise ValueError("DART에서 회사를 찾지 못했습니다")
    cc = corp.corp_code
    P, allrows = _periods(cc)
    d: dict = {"code": code, "name": corp.corp_name, "corp_code": cc, "v": VERSION, "built": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
    lp = P[-1] if P else None
    la = next((p for p in reversed(P) if p["kind"] == "사업"), None)
    pa = next((p for p in reversed(P) if p["kind"] == "사업" and la and p["y"] < la["y"]), None)
    with ThreadPoolExecutor(max_workers=4) as ex:
        fins = {p["rcept_no"]: ex.submit(_fin, cc, p) for p in P}
        hold = {p["rcept_no"]: ex.submit(_holders, cc, p["bsns_year"], p["code"]) for p in P}
        emps = {p["rcept_no"]: ex.submit(_emp, cc, p["bsns_year"], p["code"]) for p in P if p["kind"] in ("사업", "반기")}
        if pa is None and la:      # 기간 목록에 앞 사업보고서가 없으면 직원 수 비교용으로 한 해 앞을 따로
            emps["prev"] = ex.submit(_emp, cc, str(int(la["bsns_year"]) - 1), "11011")
        f_audit = ex.submit(_audit, cc, la["bsns_year"]) if la else None
        f_pay = ex.submit(_payouts, cc, la["bsns_year"]) if la else None
        f_sh = ex.submit(_shares, cc, lp["bsns_year"], lp["code"]) if lp else None
        f_ins = ex.submit(_insiders, cc)
        f_blk = ex.submit(_blocks, cc)
        f_rt = ex.submit(_rights, cc)
        f_fl = ex.submit(_flows, code)
        for p in P:
            p["fin"] = fins[p["rcept_no"]].result()
            p["holders"] = hold[p["rcept_no"]].result()
        d["shares"] = f_sh.result() if f_sh else {}
        d["mezz"] = _mezz(cc, (d["shares"] or {}).get("issued"))
        d["audit"] = f_audit.result() if f_audit else []
        d["payouts"] = f_pay.result() if f_pay else {}
        d["insiders"] = f_ins.result()
        d["blocks"] = f_blk.result()
        d["rights"] = f_rt.result()
        d["flows"] = f_fl.result()
        emp_rows = []
        if "prev" in emps:
            e = emps["prev"].result()
            if e:
                emp_rows.append({**e, "label": f"{str(int(la['y']) - 1)[2:]}.{la['m']:02d} 사업", "kind": "사업"})
        for p in P:
            if p["rcept_no"] in emps:
                e = emps[p["rcept_no"]].result()
                if e:
                    emp_rows.append({**e, "label": p["label"], "kind": p["kind"]})
        d["employees"] = emp_rows
    # 사업보고서 4분기 = 연간 − 3분기 누계
    for i, p in enumerate(P):
        if p["kind"] == "사업":
            q3 = next((q for q in P[:i] if q["kind"] == "3Q" and q["y"] == p["y"]), None)
            if q3:
                for k in ("rev", "op", "ni", "ni_own"):
                    a, b = p["fin"]["ytd"].get(k), q3["fin"]["ytd"].get(k)
                    if a is not None and b is not None:
                        p["fin"]["v"][k] = a - b
    d["periods"] = P
    d["holders"] = lp.get("holders") if lp else None
    d["disc"] = _disc_summary(allrows)
    d["flags"] = _flags(d)
    d["secs"] = round(time.time() - t0, 1)
    return d


def get(db: Session, code: str, refresh: bool = False) -> dict:
    _ensure(db)
    if not refresh:
        r = db.execute(text("select data, built_at from forensic_cache where code = :c"), {"c": code}).first()
        if r and r.data.get("v") == VERSION and (datetime.now(KST) - r.built_at).total_seconds() < TTL:
            return r.data
    lock = _locks.setdefault(code, threading.Lock())
    with lock:
        if not refresh:
            r = db.execute(text("select data, built_at from forensic_cache where code = :c"), {"c": code}).first()
            if r and r.data.get("v") == VERSION and (datetime.now(KST) - r.built_at).total_seconds() < 60:
                return r.data
        d = build(code)
        try:
            d["bands"] = _bands(db, d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("가격대 계산 실패 %s: %s", code, exc)
        try:
            d["grade"] = _grade(d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("등급 계산 실패 %s: %s", code, exc)
        db.execute(text("""insert into forensic_cache (code, data, built_at) values (:c, cast(:d as jsonb), now())
            on conflict (code) do update set data = excluded.data, built_at = now()"""), {"c": code, "d": json.dumps(d, ensure_ascii=False, default=str)})
        db.commit()
        return d


# ── 가격대 (문서 E-3, 2026-10-17 사용자 "왜 목표가 설정을 안해주노?") ─────────────────
def _bands(db: Session, d: dict) -> dict | None:
    """과거 3년 PER·PBR 배수 범위 × 지금 이익·순자산 = 하방·적정·리레이팅·극한 가격 구간 [추정].
    그날까지 공시된 연간 지배순이익·자본만 씀(사업보고서 접수일부터 적용). 주식 수는 지금 값으로 고정(증자·전환 반영 안 됨)."""
    import numpy as np  # noqa: PLC0415
    P = d.get("periods") or []
    sh = (d.get("shares") or {}).get("issued")
    if not P or not sh:
        return None
    ni_by_y, eq_pts = {}, []
    for p in P:
        f = p["fin"]
        if p["kind"] == "사업":
            for k, yy in (("ytd", p["y"]), ("p1", p["y"] - 1), ("p2", p["y"] - 2)):
                v = (f.get(k) or {}).get("ni_own") if k != "ytd" else f["ytd"].get("ni_own")
                v = v if v is not None else (f.get(k) or {}).get("ni")
                if v is not None and yy not in ni_by_y:
                    ni_by_y[yy] = v
        if f["v"].get("equity"):
            eq_pts.append((p["rcept_dt"], f["v"]["equity"]))
    # TTM 지배순이익 (지금)
    lp = P[-1]
    f = lp["fin"]
    if lp["kind"] == "사업":
        ttm = f["ytd"].get("ni_own") if f["ytd"].get("ni_own") is not None else f["ytd"].get("ni")
    else:
        y0 = f["ytd"].get("ni_own") if f["ytd"].get("ni_own") is not None else f["ytd"].get("ni")
        py = f["pytd"].get("ni_own") if f["pytd"].get("ni_own") is not None else f["pytd"].get("ni")
        prev = ni_by_y.get(lp["y"] - 1)
        ttm = y0 + prev - py if None not in (y0, py, prev) else None
    eq_now = f["v"].get("equity")
    rows = db.execute(text("select trading_date, close_price from spot_daily_prices where stock_code = :c and trading_date >= :a order by 1"),
                      {"c": d["code"], "a": date.today() - timedelta(days=365 * 3)}).all()
    if len(rows) < 120:
        return None
    ann = sorted((p["rcept_dt"], p["y"]) for p in P if p["kind"] == "사업")
    per, pbr, per_ni = [], [], []
    for dt, c in rows:
        ds = dt.strftime("%Y%m%d")
        known = [y for rd, y in ann if rd and rd <= ds]
        fy = known[-1] if known else (ann[0][1] - 1 if ann else None)       # 첫 사업보고서 전이면 그 앞 해
        ni = ni_by_y.get(fy) if fy else None
        if ni and ni > 0:
            per.append(c * sh / ni)
            per_ni.append(ni)
        eqs = [e for rd, e in eq_pts if rd and rd <= ds]
        if eqs and eqs[-1] > 0:
            pbr.append(c * sh / eqs[-1])
    last = float(rows[-1][1])
    out = {"close": last, "date": str(rows[-1][0]), "shares": sh, "ttm": ttm, "equity": eq_now, "rows": []}

    def band(name, arr, base, unit):
        if len(arr) < 120 or not base or base <= 0:
            return None
        a = np.array(arr)
        q = {"lo": float(np.percentile(a, 5)), "mid": float(np.median(a)), "hi": float(np.percentile(a, 80)), "max": float(a.max())}
        now = last * sh / base
        return {"name": name, "unit": unit, "now": round(now, 1), "pos": round(float((a < now).mean() * 100)),
                **{k: round(v, 1) for k, v in q.items()}, **{f"px_{k}": round(v * base / sh) for k, v in q.items()}}
    # PER 가격대를 못 믿는 경우 (2026-10-17 저스템: 흑자 전환 7개월치 PER 44~137배 × 이익 3배 → 하방 22,551원 > 지금 15,900원)
    why_no = ""
    if not ttm or ttm <= 0:
        why_no = "최근 4분기 지배순이익이 적자"
    elif len(per) < 250:
        why_no = f"흑자였던 기간이 {len(per)}거래일뿐(1년 미만)"
    elif float(np.median(per)) > 60:
        why_no = f"3년 PER 중앙값 {float(np.median(per)):.0f}배 — 이익이 너무 작던 때라 의미 없음"
    elif not 0.5 <= ttm / float(np.median(per_ni)) <= 2:
        why_no = f"지금 이익이 그 기간 이익의 {ttm / float(np.median(per_ni)):.1f}배로 급변(턴어라운드·사이클)"
    for b in ((None if why_no else band("PER", per, ttm, "배")), band("PBR", pbr, eq_now, "배")):
        if b:
            out["rows"].append(b)
    out["note"] = f"PER 가격대는 뺌 — {why_no}. PBR만 봄" if why_no else ""
    return out if out["rows"] else None


# ── 종합 등급 (2026-10-17 사용자 "문서에 나와있는 내용토대로 비중실어서 점수 매겨라 S A+ A A- B+ B- B") ──
GRADES = [(90, "S"), (85, "A+"), (80, "A"), (75, "A-"), (70, "B+"), (65, "B"), (60, "B-"), (55, "C+"), (50, "C"), (45, "C-"), (0, "D")]


def _grade(d: dict) -> dict:
    """문서 비중대로 100점: 이익의 질 20 · 재무 안정성 15 · 메자닌·희석 15 · 지배구조·대주주 15 · 감사 10 · 실적 추세 10 · 가격대 위치 10 · 인력 5.
    바이사이드(위험 찾기) 관점이라 위험이 적을수록 높음. 기계 규칙 점수 — 매수 추천 아님, 모르는 항목은 중간값."""
    F = {f["title"]: f for f in d.get("flags") or []}
    has = lambda kw: any(kw in t for t in F)  # noqa: E731
    lv = lambda kw: next((F[t]["level"] for t in F if kw in t), None)  # noqa: E731
    P = d.get("periods") or []
    lp = P[-1] if P else None
    items = []

    def add(name, mx, sc, why):
        items.append({"name": name, "max": mx, "score": max(0, min(mx, round(sc))), "why": why})
    # 이익의 질 20
    q = d.get("quality")
    if q and q["sni"] > 0:
        r = q["socf"] / q["sni"]
        add("이익의 질", 20, 20 if r >= 1 else 16 if r >= 0.8 else 10 if r >= 0.5 else 4, f"3년 영업현금 ÷ 순이익 {r:.2f}배")
    elif q:
        add("이익의 질", 20, 2, "3년 합 순손실")
    else:
        add("이익의 질", 20, 10, "자료 없음 (중간값)")
    # 재무 안정성 15
    v = (lp or {}).get("fin", {}).get("v", {}) if lp else {}
    dr = v["liab"] / v["equity"] * 100 if v.get("liab") is not None and v.get("equity") and v["equity"] > 0 else None
    sc = 15 if dr is not None and dr < 50 else 12 if dr is not None and dr < 100 else 7 if dr is not None and dr < 200 else 3 if dr is not None else 7
    why = [f"부채비율 {dr:.0f}%" if dr is not None else "부채비율 모름"]
    if has("단기 차입이 현금의 2배"):
        sc -= 5; why.append("단기차입 > 현금×2")
    c = lv("영업현금 적자")
    if c == "⛔":
        sc = 0; why.append("현금 1년 안 소진 [추정]")
    elif c == "⚠️":
        sc = min(sc, 5); why.append("현금 3년 안 소진 [추정]")
    add("재무 안정성", 15, sc, " · ".join(why))
    # 메자닌·희석 15
    sh = (d.get("shares") or {}).get("issued")
    live = [m for m in d.get("mezz") or [] if m.get("live") and m["kind"] in ("CB", "BW")]
    pct = sum(m.get("shares") or 0 for m in live) / sh * 100 if sh and live else 0
    sc = 15 if not live else 12 if pct < 3 else 7 if pct < 10 else 2
    why = [f"만기 전 CB·BW 잠재 {pct:.1f}%" if live else "만기 전 CB·BW 없음"]
    for kw, pen, t in (("타법인 증권 취득", 3, "자금이 타법인으로"), ("유상증자 이력", 3, "유상증자 반복·3자 배정"), ("만기 전 사채 취득", 2, "만기 전 사채 취득")):
        if has(kw):
            sc -= pen; why.append(t)
    add("메자닌·희석", 15, sc, " · ".join(why))
    # 지배구조·대주주 15
    h = (d.get("holders") or {}).get("total")
    B0 = d.get("bands") or {}
    mcap = (B0.get("close") or 0) * (sh or 0)
    sc = 15 if h and h >= 40 else 12 if h and h >= 30 else 9 if h and h >= 20 else (9 if mcap >= 10e12 else 4) if h else 8
    why = [f"최대주주+특관 {h:.1f}%" + (" (시총 10조↑ 대형주라 분산이 보통)" if h and h < 20 and mcap >= 10e12 else "") if h else "지분 모름"]
    for kw, pen, t in (("최대주주 변동", 3, "최대주주 변동"), ("주식담보", 3, "주식담보 계약"), ("지분 감소 보고", 2, "내부자 매도 이어짐"), ("배당·자사주 매입 없음", 2, "흑자인데 환원 없음")):
        if has(kw):
            sc -= pen; why.append(t)
    if (d.get("disc") or {}).get("valueup"):
        sc += 2; why.append("밸류업 공시 +")
    add("지배구조·대주주", 15, sc, " · ".join(why))
    # 감사 10
    sc, why = 10, []
    if any(f["level"] == "⛔" and ("감사의견" in f["title"] or "계속기업" in f["title"]) for f in d.get("flags") or []):
        sc = 0; why.append("비적정·계속기업")
    if has("감사인이 바뀜"):
        sc -= 3; why.append("감사인 변경")
    if has("강조사항"):
        sc -= 2; why.append("강조사항")
    add("감사", 10, sc, " · ".join(why) or "적정 · 특이사항 없음")
    # 실적 추세 10
    if lp:
        f = lp["fin"]
        op, op0 = f["ytd"].get("op"), (f["p1"] if lp["kind"] == "사업" else f["pytd"]).get("op")
        if has("영업적자 3년"):
            sc, w = 0, "영업적자 3년 연속"
        elif op is None:
            sc, w = 5, "자료 없음"
        elif op <= 0:
            sc, w = 2, f"{lp['label']} 누계 영업적자"
        elif op0 and op0 > 0 and op / op0 - 1 >= 0.1:
            sc, w = 10, f"누계 영업이익 전년 대비 {(op / op0 - 1) * 100:+.0f}%"
        elif op0 and op0 > 0:
            sc, w = 7 if op >= op0 else 5, f"누계 영업이익 전년 대비 {(op / op0 - 1) * 100:+.0f}%"
        else:
            sc, w = 8, "흑자 전환"
        if has("본업 vs 일회성"):
            sc = min(sc, 3); w += " · 순이익은 일회성"
        add("실적 추세", 10, sc, w)
    else:
        add("실적 추세", 10, 5, "자료 없음")
    # 가격대 위치 10 (3년 배수 중 지금 자리 — 높을수록 감점)
    B = d.get("bands")
    if B and B.get("rows"):
        pos = sum(r["pos"] for r in B["rows"]) / len(B["rows"])
        add("가격대 위치", 10, 10 if pos < 30 else 8 if pos < 50 else 6 if pos < 70 else 4 if pos < 90 else 2, f"3년 배수 중 하위 {pos:.0f}% 자리")
    else:
        add("가격대 위치", 10, 5, "계산 못 함 (중간값)")
    # 인력 5
    ea = [e for e in d.get("employees") or [] if e.get("kind") == "사업" and e.get("n")]
    if len(ea) >= 2:
        ch = ea[-1]["n"] / ea[-2]["n"] - 1
        add("인력", 5, 5 if ch >= 0 else 4 if ch > -0.1 else 2 if ch > -0.2 else 0, f"직원 {ch * 100:+.0f}% (1년)")
    else:
        add("인력", 5, 3, "비교 자료 없음")
    total = sum(i["score"] for i in items)
    g = next(gr for cut, gr in GRADES if total >= cut)
    return {"grade": g, "score": total, "items": items}


# ── 내 판단 (PART E-5·E-6·F) ─────────────────────────────────────────
def note_get(db: Session, owner: str, code: str) -> dict | None:
    _ensure(db)
    r = db.execute(text("select * from forensic_notes where owner = :o and code = :c"), {"o": owner, "c": code}).first()
    if not r:
        return None
    return {"verdict": r.verdict, "checks": r.checks or {}, "checkpoints": r.checkpoints or "", "memo": r.memo or "",
            "updated": r.updated_at.astimezone(KST).strftime("%m/%d %H:%M") if r.updated_at else None}


def note_save(db: Session, owner: str, code: str, name: str, verdict: str | None, checks: dict, checkpoints: str, memo: str) -> dict:
    _ensure(db)
    db.execute(text("""insert into forensic_notes (owner, code, name, verdict, checks, checkpoints, memo, updated_at)
        values (:o, :c, :n, :v, cast(:k as jsonb), :cp, :m, now())
        on conflict (owner, code) do update set name = excluded.name, verdict = excluded.verdict, checks = excluded.checks,
        checkpoints = excluded.checkpoints, memo = excluded.memo, updated_at = now()"""),
               {"o": owner, "c": code, "n": name, "v": verdict, "k": json.dumps(checks, ensure_ascii=False), "cp": checkpoints, "m": memo})
    db.commit()
    return note_get(db, owner, code) or {}


def notes_list(db: Session, owner: str) -> list[dict]:
    _ensure(db)
    rows = db.execute(text("select code, name, verdict, updated_at from forensic_notes where owner = :o order by updated_at desc limit 50"), {"o": owner}).all()
    return [{"code": c, "name": n, "verdict": v, "updated": u.astimezone(KST).strftime("%m/%d") if u else None} for c, n, v, u in rows]


# ── AI 초안 (PART E 형식) ─────────────────────────────────────────────
def _mdna(rcp: str) -> str:
    """사업보고서 원문에서 'IV. 이사의 경영진단 및 분석의견' 부분만 (문서 B-3-4: 가장 중요한 항목). 실패하면 빈 글."""
    try:
        r = requests.get(API + "document.xml", params={"crtfc_key": _key(), "rcept_no": rcp}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        best = ""
        for nm in z.namelist():
            raw = z.read(nm).decode("utf-8", errors="ignore")
            t = re.sub(r"<[^>]+>", " ", raw)
            t = re.sub(r"&nbsp;|&#160;", " ", t)
            t = re.sub(r"[ \t\r]+", " ", t)
            t = re.sub(r"\n\s*\n+", "\n", t)
            for m in re.finditer(r"이사의\s*경영진단\s*및\s*분석의견", t):      # 목차에도 같은 제목이 있음 → 가장 긴 구간(본문)을 고름
                end = re.search(r"(회계감사인의\s*감사의견\s*등|V\.\s*감사인의|V\.\s*회계감사인)", t[m.end():])
                seg = t[m.start(): m.end() + (end.start() if end else 20000)]
                if len(seg) > len(best):
                    best = seg
        return best.strip()[:14000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("경영진단 원문 실패 %s: %s", rcp, type(exc).__name__)
        return ""


def _data_text(d: dict) -> str:
    """AI에 줄 자료 — 숫자마다 어느 보고서인지 붙임."""
    L = [f"[회사] {d['name']} ({d['code']}) · 자료 모은 시각 {d['built']} KST"]
    L.append("[정기보고서 병렬표 — 금액 원 단위, '분기'=그 분기 3개월, '누계'=사업연도 시작부터, 연결이 없으면 별도]")
    for p in d.get("periods") or []:
        f = p["fin"]
        L.append(f"- {p['label']} (접수 {p['rcept_no']}, {f.get('fs') or '재무 없음'}): 분기 {json.dumps(f['v'], ensure_ascii=False)} · 누계 {json.dumps(f['ytd'], ensure_ascii=False)}"
                 + (f" · 전년 같은 분기 {json.dumps(f['pq'], ensure_ascii=False)} · 전년 누계 {json.dumps(f['pytd'], ensure_ascii=False)}" if f.get("pq") else "")
                 + (f" · 전기 {json.dumps(f['p1'], ensure_ascii=False)} · 전전기 {json.dumps(f['p2'], ensure_ascii=False)}" if f.get("p1") else "")
                 + (f" · 최대주주+특관 {p['holders']['total']}%" if p.get("holders") else ""))
    for k, title in (("employees", "직원"), ("audit", "감사의견(사업보고서)"), ("mezz", "CB·BW·EB 발행결정 5년"), ("rights", "유상증자 결정 5년"),
                     ("insiders", "임원·주요주주 소유 변동 2년"), ("blocks", "5% 대량보유 3년"), ("payouts", "배당(백만원)·보수·자사주·최대주주 변동·자금 사용"),
                     ("shares", "주식 총수"), ("holders", "최근 최대주주·특관 지분"), ("flows", "최근 수급 세부 (억 원, KIS) — 평단은 [추정]"), ("disc", "1년 공시 요약"), ("grade", "사이트 규칙 등급 (기계 점수)"), ("bands", "가격대 — 과거 3년 PER·PBR 배수(5%·중앙·80%·최고) × 지금 TTM 지배순이익·자본, 주당 가격 [추정]")):
        v = d.get(k)
        if v:
            L.append(f"[{title}] {json.dumps(v, ensure_ascii=False, default=str)[:6000]}")
    L.append("[자동 모순 후보 — 사이트 규칙이 기계적으로 건 것, 맞는지 네가 다시 봐야 함]")
    for f in d.get("flags") or []:
        L.append(f"- {f['level']} {f['title']}: {f['fact']}")
    return "\n".join(L)


AI_PROMPT = """너는 한국 상장사 전자공시(DART)를 바이사이드 관점에서 포렌식 분석하는 애널리스트다. 좋은 점을 파는 게 아니라 리스크를 집중 분석해 돈을 지키는 것이 목적이다.
종목을 추천하지 않고, 판단 재료와 판단 틀만 만든다. 한국어 존댓말, 영어 문장 금지.

[지킬 것 — 어기면 결과물 무효]
- 보고서는 사실이 아니라 회사가 <제시>한, 마사지된 1차 사료다. 회사가 무엇을 돋보이게 하고 무엇을 감추려 하는지 읽는다.
- 모든 숫자에 출처를 붙인다. 형식: [26.06 반기 / 연결] 처럼. 연결·별도, 전년 동기·전분기 등 비교 기준을 숫자 옆에 적는다.
- 아래 자료에 없는 것은 "보고서상 확인 불가"라고 쓴다. 외부 지식으로 메우지 않는다. 회사명·인명·금액을 지어내지 않는다.
- 추정·계산값은 [추정], 가설은 [가설]로 표시하고 계산은 식을 보여 준다.
- 모든 항목에서 긍정 해석과 부정 해석을 둘 다 세운다. "실적 좋음 = 상승"으로 쓰지 않는다. 내부자 매수를 무조건 호재로, 적정 감사의견을 우량의 근거로, 외국인 순매수를 시총 확인 없이 '진짜 외국인'으로 쓰지 않는다.
- 핵심 질문: "회사는 왜 스스로를 이렇게 보이게 하는가?" 대주주는 지금 주가가 높기를 원하는가, 낮기를 원하는가?
- 매수·매도 추천·타점은 금지. 가격대는 아래 [가격대] 자료(과거 3년 배수 × 지금 이익·순자산)를 근거로 '구간'으로 쓴다. 판정은 [거름] / [관심 종목 등록 – 추적 시작] / [판단 보류 – 추가 자료 필요] 중 하나와 이유만.
- 정치색으로 해석하지 않는다. 분석에 시간이 들었다고 억지로 좋게 해석하지 않는다.
- 사이트가 건 '자동 모순 후보'는 기계 규칙이라 틀릴 수 있다. 맞는지 다시 보고 틀리면 틀렸다고 쓴다.

[산출물 형식 — 이것만, 마크다운]
맨 위 한 줄: "⚠️ 이 글은 AI 초안입니다. 원문으로 검증하기 전까지 '정교한 쓰레기'일 수 있습니다."
## E-0. 종합 등급
문서 비중(이익의 질 20 · 재무 안정성 15 · 메자닌·희석 15 · 지배구조·대주주 어심 15 · 감사 10 · 실적 추세 10 · 가격대 위치 10 · 인력·비재무 5, 위험이 적을수록 높음)으로
네가 직접 100점을 매기고 등급(S 90↑ · A+ 85 · A 80 · A- 75 · B+ 70 · B 65 · B- 60 · C+ 55 · C 50 · C- 45 · D)을 준다. 항목별 점수와 한 줄 근거를 표로.
[사이트 규칙 등급]과 다르면 왜 다른지 적는다. 등급은 위험 판정이지 매수 추천이 아니다.
## E-1. 논증 요약 (한 줄 요약 금지)
가정 / 근거(출처) / 반론 / 현재 판단 / 판단이 뒤집히는 조건
## E-2. 모순 목록
표: # | 항목 | 회사의 설명 | 실제 숫자(출처) | 해석 A(긍정) | 해석 B(부정) | 확인 방법
(경영진단 원문이 있으면 회사가 든 실적 변동 원인을 인용하고 숫자로 뒷받침되는지, 지난해와 어조가 바뀌었는지 본다)
## E-3. 이익의 질 · 운전자본 · 메자닌 · 대주주 유인
각각 3~6줄. 미래 주식 공급 스케줄(만기 안 지난 CB·BW, 리픽싱 하한 기준 최대 물량 [추정])을 계산한다. 대주주 유인 판정: 올릴 유인 / 누를 유인 / 중립 + 근거.
## E-3b. 다섯 가지 가격대\n표: 구간(하방/적정/국내 리레이팅/글로벌 리레이팅/극한) | 가격(시총) 구간 | 전제 조건 | 근거. [가격대] 자료의 배수를 쓰고, 이익이 일회성이면 경상 이익으로 다시 계산해 둘 다 적는다. 리레이팅을 적으면 더 심한 디레이팅 가능성도 적는다. 글로벌 피어 배수는 자료에 없으면 '보고서상 확인 불가'.\n## E-4. 수급 — 세 색깔 안에 누가 숨어 있나
주체별 누적 순매수·평단 [추정]·승패. 사모·기타법인을 따로 본다. 시총 2,500억 이하면 '외국인'이 한국인 외국계 창구일 수 있음을 적는다.
## E-5. 괴리와 해소
괴리 / 해소 트리거(무엇이 일어나야 닫히나) / 해소 시점 [추정]
## E-6. 체크포인트 (다음 보고서에서 어긋나면 가설 폐기)
3~5개, 각각 "확인 보고서 항목"과 "허용 범위"
## E-7. 판정
## E-8. 확인하지 못한 것
사람이 원문을 직접 열어 확인할 항목과 위치(보고서 이름·장·주석). 정관 사업목적 변경, 특수관계자 거래, 개발비 자산화, 수주잔고, 인수자 이름처럼 이 자료에 없는 것은 여기에.
## E-9. 바이사이드 리스크 요약
공개 리포트가 다루지 않을 리스크만 표로.

[자료]
{data}

[사업보고서 'IV. 이사의 경영진단 및 분석의견' 원문 — 최근]
{mdna0}

[같은 항목 — 한 해 전 사업보고서 (어조 변화 비교용)]
{mdna1}
"""


def ai_latest(db: Session, owner: str, code: str) -> dict | None:
    _ensure(db)
    r = db.execute(text("select * from forensic_ai where owner = :o and code = :c order by id desc limit 1"), {"o": owner, "c": code}).first()
    if not r:
        return None
    return {"id": r.id, "status": r.status, "output": r.output, "created": r.created_at.astimezone(KST).strftime("%m/%d %H:%M"),
            "done": r.done_at.astimezone(KST).strftime("%m/%d %H:%M") if r.done_at else None}


def _ai_run(rid: int, code: str) -> None:
    from backend.db.database import SessionLocal  # noqa: PLC0415
    db = SessionLocal()
    try:
        db.execute(text("update forensic_ai set status = 'running' where id = :id"), {"id": rid}); db.commit()
        d = get(db, code)
        ann = [p for p in d.get("periods") or [] if p["kind"] == "사업"]
        m0 = _mdna(ann[-1]["rcept_no"]) if ann else ""
        m1 = _mdna(ann[-2]["rcept_no"]) if len(ann) >= 2 else ""
        prompt = AI_PROMPT.format(data=_data_text(d)[:60000], mdna0=m0 or "(원문을 못 받음 — 보고서상 확인 불가)", mdna1=m1 or "(없음)")
        WORKDIR.mkdir(parents=True, exist_ok=True)
        # 글이 길어(한글 10만 자 안팎) 명령줄 인자 한도(128KB)를 넘을 수 있어 표준입력으로 넘김
        p = subprocess.run([CLAUDE, "-p", "--output-format", "text", "--tools", ""], input=prompt, cwd=WORKDIR, capture_output=True, text=True, timeout=900)
        out = (p.stdout or "").strip()
        ok = p.returncode == 0 and len(out) > 200
        db.execute(text("update forensic_ai set output = :o, status = :s, done_at = now() where id = :id"),
                   {"o": out if ok else f"초안을 만들지 못했습니다 ({(p.stderr or '').strip()[:200] or p.returncode})", "s": "done" if ok else "failed", "id": rid})
        db.commit()
        if ok:
            try:
                from backend.services.telegram import SITE, owner_chats, send  # noqa: PLC0415
                for c in owner_chats(db):
                    send(db, f"🔍 기업 분석 AI 초안 완료 — {d['name']}\n{SITE}/#forensic", c)
            except Exception as exc:  # noqa: BLE001
                logger.warning("포렌식 알림 실패: %s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        logger.error("포렌식 AI 실패 %s: %s", code, exc)
        try:
            db.rollback()
            db.execute(text("update forensic_ai set status = 'failed', output = :o, done_at = now() where id = :id"), {"o": f"오류: {type(exc).__name__}", "id": rid})
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        _ai_busy.discard(code)
        db.close()


def ai_start(db: Session, owner: str, code: str, name: str) -> dict:
    _ensure(db)
    if code in _ai_busy:
        return {"ok": False, "msg": "이미 만드는 중입니다"}
    _ai_busy.add(code)
    rid = db.execute(text("insert into forensic_ai (owner, code, name, status) values (:o, :c, :n, 'waiting') returning id"),
                     {"o": owner, "c": code, "n": name}).scalar()
    db.commit()
    threading.Thread(target=_ai_run, args=(rid, code), daemon=True).start()
    return {"ok": True, "id": rid}
