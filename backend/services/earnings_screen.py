"""실적 개선 탭: DART 분기 실적 → 공시일 기준 실적표 → 후보 스냅샷 (data/earnings_screen/latest.json).

조건(arena/submissions/claude/earnings 검증 기준): 당분기 영업이익이 전년 동기보다 +30% 이상, 매출 +10% 이상,
전년 동기와 당분기 모두 영업이익 흑자. 최근 공시(120일 이내)만 보여 준다. 순위는 화면에서 두 방식으로 고른다.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sqlalchemy import text

from backend.config import get_config
from backend.db.database import SessionLocal, engine
from backend.screener.market_regime import current_regime
from backend.utils.logger import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2] / "data" / "earnings_screen"
RAW = ROOT / "raw"
DART = "https://opendart.fss.or.kr/api"
REPORTS = {"11013": ("Q1", 1), "11012": ("H1", 2), "11014": ("Q3", 3), "11011": ("FY", 4)}
ACC = {"매출액": "revenue", "영업이익": "op_income", "당기순이익(손실)": "net_income"}
RECENT_DAYS = 120            # 이 기간 안에 공시된 분기만 후보로 본다
MIN_TV20, MIN_PRICE = 5e9, 1000
SEMI_SOBU = re.compile(r"^반도체 ?장비$|반도체 재료/부품|HBM|반도체 기판")
SEMI_AI = re.compile(r"반도체|HBM|CXL|유리기판|온디바이스|데이터센터|NPU|칩렛|뉴로모픽|AI반도체|인공지능|AI 챗봇|피지컬 AI|퓨리오사")


def _key() -> str:
    key = get_config().dart_api_key
    if key:
        return key
    path = Path.home() / ".dart_key"
    return path.read_text().strip() if path.exists() else ""


def _corp_codes(key: str) -> list[str]:
    path = ROOT / "corp_codes.csv"
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return pd.read_csv(path, dtype=str).corp_code.tolist()
    r = requests.get(f"{DART}/corpCode.xml", params={"crtfc_key": key}, timeout=120)
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml"))
    df = pd.DataFrame([{c.tag: (c.text or "").strip() for c in item} for item in root.iter("list")])
    df = df[df.stock_code.str.len() == 6]
    df.to_csv(path, index=False)
    return df.corp_code.tolist()


def _due(year: int, name: str) -> date:
    return {"Q1": date(year, 5, 15), "H1": date(year, 8, 14), "Q3": date(year, 11, 14), "FY": date(year + 1, 3, 31)}[name]


def collect(today: date | None = None) -> int:
    """최근 3개 사업연도 주요계정을 받는다. 공시 기간 전후(마감 45일 전~120일 후)인 보고서는 매번 다시 받고, 나머지는 없을 때만 받는다."""
    today = today or date.today()
    key = _key()
    if not key:
        raise RuntimeError("DART 키가 없습니다 (DART_API_KEY 또는 ~/.dart_key)")
    RAW.mkdir(parents=True, exist_ok=True)
    codes = _corp_codes(key)
    calls = 0
    for year in (today.year - 2, today.year - 1, today.year):
        for rc, (name, _) in REPORTS.items():
            due = _due(year, name)
            if due - timedelta(days=45) > today:
                continue
            active = due - timedelta(days=45) <= today <= due + timedelta(days=120)
            for b in range(0, len(codes), 100):
                out = RAW / f"{year}_{name}_{b // 100:03d}.json"
                if out.exists() and not active:
                    continue
                try:
                    j = requests.get(f"{DART}/fnlttMultiAcnt.json", timeout=60, params={
                        "crtfc_key": key, "corp_code": ",".join(codes[b:b + 100]), "bsns_year": str(year), "reprt_code": rc}).json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("DART 조회 실패 %s %s %s: %s", year, name, b, exc)
                    continue
                calls += 1
                if j.get("status") == "020":
                    raise RuntimeError("DART 일일 한도 초과")
                if j.get("status") in ("000", "013"):
                    out.write_text(json.dumps(j.get("list", []), ensure_ascii=False), encoding="utf-8")
                time.sleep(0.12)
    return calls


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def build_pit() -> pd.DataFrame:
    """raw → 회사·분기별 매출/영업이익/순이익과 공시일, 전년 동기 값 (arena/data/dart/build_pit.py와 같은 규칙)."""
    rows = []
    for f in RAW.glob("*.json"):
        name = f.stem.split("_")[1]
        for x in json.loads(f.read_text(encoding="utf-8")):
            if x.get("account_nm") in ACC:
                x["report"] = name
                rows.append(x)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["corp_code", "bsns_year", "report", "fs_div", "account_nm", "sj_div"]).drop_duplicates(
        ["corp_code", "bsns_year", "report", "fs_div", "account_nm"])
    cfs = df[df.fs_div == "CFS"][["corp_code", "bsns_year", "report"]].drop_duplicates().assign(cfs=True)
    df = df.merge(cfs, how="left", on=["corp_code", "bsns_year", "report"])
    df = df[(df.fs_div == "CFS") | df.cfs.isna()]
    df["q"] = _num(df.thstrm_amount)
    df["cum"] = _num(df.get("thstrm_add_amount", pd.Series(index=df.index, dtype=object)))
    df["acc"] = df.account_nm.map(ACC)
    df["filed"] = pd.to_datetime(df.rcept_no.str[:8], format="%Y%m%d", errors="coerce")
    wide = df.pivot_table(index=["corp_code", "stock_code", "bsns_year", "report", "fs_div", "filed"], columns="acc",
                          values=["q", "cum"], aggfunc="first")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.reset_index()
    out = []
    for (corp, year), g in wide.groupby(["corp_code", "bsns_year"]):
        g = g.drop_duplicates("report").set_index("report")
        for rep, qn in (("Q1", 1), ("H1", 2), ("Q3", 3)):
            if rep in g.index:
                r = g.loc[rep]
                out.append(dict(corp_code=corp, stock_code=r.stock_code, year=int(year), quarter=qn, fs_div=r.fs_div, filed=r.filed,
                                **{k: r.get(f"q_{k}") for k in ACC.values()}))
        if "FY" in g.index and "Q3" in g.index and g.loc["FY"].fs_div == g.loc["Q3"].fs_div:
            fy, q3 = g.loc["FY"], g.loc["Q3"]
            out.append(dict(corp_code=corp, stock_code=fy.stock_code, year=int(year), quarter=4, fs_div=fy.fs_div, filed=fy.filed,
                            **{k: fy.get(f"q_{k}") - q3.get(f"cum_{k}") for k in ACC.values()}))
    q = pd.DataFrame(out)
    prev = q[["corp_code", "year", "quarter", "fs_div", *ACC.values()]].copy()
    prev["year"] += 1
    return q.merge(prev, on=["corp_code", "year", "quarter", "fs_div"], how="left", suffixes=("", "_base"))


def snapshot(pit: pd.DataFrame, today: date | None = None) -> dict:
    today = today or date.today()
    recent = pit[pit.filed >= pd.Timestamp(today - timedelta(days=RECENT_DAYS))]
    latest = recent.sort_values("filed").groupby("stock_code").tail(1).copy()
    op, base, rev, rbase = latest.op_income, latest.op_income_base, latest.revenue, latest.revenue_base
    latest["op_yoy"] = (op - base) / base.abs() * 100
    latest["rev_yoy"] = (rev / rbase - 1) * 100
    up = latest[(op > 0) & (base > 0) & (rbase > 0) & (latest.op_yoy >= 30) & (latest.rev_yoy >= 10)]
    codes = up.stock_code.tolist()
    if not codes:
        return {"status": "ready", "rows": [], "generated_at": datetime.now(timezone.utc).isoformat()}
    with engine.connect() as con:
        px = pd.read_sql(text("select stock_code, trading_date, close_price, trading_value from spot_daily_prices "
                              "where trading_date >= :d and stock_code = any(:c)"), con,
                         params={"d": today - timedelta(days=420), "c": codes})
        names = pd.read_sql(text("select code, name from stocks"), con).set_index("code").name
        themes = pd.read_sql(text("select ss.stock_code, s.sector_name from sector_stocks ss join sectors s on s.id = ss.sector_id "
                                  "where s.is_active"), con)
    px["trading_date"] = pd.to_datetime(px.trading_date)
    cl = px.pivot(index="trading_date", columns="stock_code", values="close_price").sort_index()
    tv20 = px.pivot(index="trading_date", columns="stock_code", values="trading_value").sort_index().reindex_like(cl).rolling(20, min_periods=20).mean()
    theme_of = themes.groupby("stock_code").sector_name.apply(lambda x: sorted(set(x))).to_dict()
    dates = cl.index
    rows = []
    for r in up.itertuples():
        c = r.stock_code
        if c not in cl.columns:
            continue
        s = cl[c].dropna()
        if len(s) < 121 or not np.isfinite(tv20[c].iloc[-1]):
            continue
        now = float(s.iloc[-1])
        if tv20[c].iloc[-1] < MIN_TV20 or now < MIN_PRICE:
            continue
        pre = s[s.index < r.filed]
        th = theme_of.get(c, [])
        rows.append({
            "code": c, "name": names.get(c, c), "filed": r.filed.date().isoformat(), "period": f"{r.year} {r.quarter}분기",
            "days_since": int((dates > r.filed).sum()), "close": now,
            "ret5": (now / s.iloc[-6] - 1) * 100, "ret20": (now / s.iloc[-21] - 1) * 100,
            "ret60": (now / s.iloc[-61] - 1) * 100, "ret120": (now / s.iloc[-121] - 1) * 100,
            "pre60": (pre.iloc[-1] / pre.iloc[-61] - 1) * 100 if len(pre) > 60 else None,
            "from_low60": (now / s.iloc[-60:].min() - 1) * 100, "from_high": (now / s.iloc[-250:].max() - 1) * 100,
            "op": float(r.op_income), "op_base": float(r.op_income_base), "op_yoy": float(r.op_yoy), "rev_yoy": float(r.rev_yoy),
            "margin": float(r.op_income / r.revenue * 100) if r.revenue else None,
            "thin": bool(r.op_income / r.revenue < 0.05 or r.op_income_base / r.revenue_base < 0.01),
            "tv20": float(tv20[c].iloc[-1]), "themes": th[:6],
            "semi_sobu": any(SEMI_SOBU.search(t) for t in th), "semi_ai": any(SEMI_AI.search(t) and "방역" not in t for t in th),
        })
    db = SessionLocal()
    try:
        regime = current_regime(db)
    finally:
        db.close()
    clean = lambda v: None if isinstance(v, float) and not np.isfinite(v) else (round(v, 2) if isinstance(v, float) else v)  # noqa: E731
    return {"status": "ready", "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of": dates[-1].date().isoformat(), "regime": regime, "recent_days": RECENT_DAYS,
            "rows": [{k: clean(v) for k, v in row.items()} for row in rows]}


def refresh() -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        calls = collect()
        snap = snapshot(build_pit())
        snap["dart_calls"] = calls
        tmp = ROOT / "latest.json.tmp"
        tmp.write_text(json.dumps(snap, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(ROOT / "latest.json")
        logger.info("실적 개선 스냅샷 갱신: %d종목, DART 호출 %d회", len(snap["rows"]), calls)
    except Exception as exc:  # noqa: BLE001
        logger.error("실적 개선 스냅샷 갱신 실패: %s", exc)


def read_snapshot() -> dict:
    path = ROOT / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "preparing", "rows": []}
