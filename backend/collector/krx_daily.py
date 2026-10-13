"""KRX 공식 일별 시세(정규장)로 저장된 시세를 바로잡는다 (2026-10-13).

왜: 넥스트레이드(NXT, 2025-03-04~) 장 후 거래가 섞인 값이 DB에 들어가 있었다.
- 15:41·18:00 수집분 = NXT 장 후 진행 중 값, 07:30 'FDR 확정치 재수집' = NXT까지 합친 20시 최종값 → 둘 다 정규장 값이 아님.
- 2026-10-13 확인: 거래대금 상위 120종목 중 86종목 종가가 정규장 15:30 종가와 다름(최대 ±2.5%), 저가도 장 후 더 낮은 값.
  손절가(산 날 저가 −1%)·종가 점수·21일선 판단·차트·2025-03 이후 검증이 모두 영향.
어떻게: KRX OpenAPI 유가(stk_bydd_trd)·코스닥(ksq_bydd_trd) 일별매매정보 = 정규장 시가·고가·저가·종가·거래량·거래대금.
다음 날 아침에 받을 수 있다(그날 밤엔 빈 값). 키 = .env KRX_API_KEY (옮겨 적지 않는다).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
BASE = "https://data-dbg.krx.co.kr/svc/apis/sto/"
NXT_START = date(2025, 3, 4)
DIRTY_FROM = date(2026, 9, 14)     # 이 날부터 15:41·18:00 수집·07:30 FDR 재수집이 장 후 값을 넣음 (9/10 다른 종목 0% → 9/15 83%)


def _num(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def fetch(day: date) -> dict[str, tuple]:
    """{종목코드: (시, 고, 저, 종, 거래량, 거래대금, 등락률%)} — 거래 없는 종목(시가 0)은 뺀다. 자료가 아직 없으면 빈 dict."""
    key = os.getenv("KRX_API_KEY", "")
    if not key:
        raise RuntimeError("KRX_API_KEY 없음")
    out: dict[str, tuple] = {}
    for path in ("stk_bydd_trd", "ksq_bydd_trd"):
        for attempt in range(3):
            try:
                r = requests.get(BASE + path, params={"basDd": day.strftime("%Y%m%d")}, headers={"AUTH_KEY": key}, timeout=30)
                rows = (r.json() if r.status_code == 200 else {}).get("OutBlock_1") or []
                break
            except Exception:  # noqa: BLE001
                rows = []
                time.sleep(2 * (attempt + 1))
        for x in rows:
            o, h, l, c = (_num(x.get(k)) for k in ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC"))
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                continue
            out[str(x.get("ISU_CD"))] = (o, h, l, c, _num(x.get("ACC_TRDVOL")), _num(x.get("ACC_TRDVAL")), _num(x.get("FLUC_RT")))
        time.sleep(0.3)
    return out


def apply(db: Session, day: date, tables: tuple[str, ...] = ("spot_daily_prices",)) -> dict:
    """그날 KRX 공식값과 다른 행만 고친다. 반환 {table: 고친 수, 'krx': 받은 종목 수}."""
    krx = fetch(day)
    res = {"krx": len(krx)}
    if not krx:
        return res
    for t in tables:
        cols = "stock_code, open_price, high_price, low_price, close_price, volume, trading_value" + (", change_pct" if t == "spot_daily_prices" else "")
        rows = db.execute(text(f"select {cols} from {t} where trading_date = :d"), {"d": day}).all()
        fixed = 0
        for r in rows:
            k = krx.get(r[0])
            if not k:
                continue
            o, h, l, c, v, tv, chg = k
            old = [float(x or 0) for x in r[1:7]]
            if all(abs(a - b) <= max(1e-6, abs(b) * 1e-6) for a, b in zip(old[:4], (o, h, l, c))) and abs(old[4] - v) < 1:
                continue
            # 수정주가(유상·무상증자·분할)는 시·고·저·종이 같은 비율로 다름 → 오염이 아니라 정상, 덮어쓰면 과거 차트가 끊긴다 → 건너뜀
            rat = [a / b for a, b in zip(old[:4], (o, h, l, c)) if a > 0 and b > 0]
            if len(rat) == 4 and (max(rat) - min(rat)) / max(rat) < 0.01 and abs(sorted(rat)[1] - 1) > 0.002:
                # 수정주가 위에 장 후 값이 섞인 경우(042940 9/15: 시·고·저 0.9626 · 종가 0.9609)도 있어서 그냥 넘기지 않고
                # 'KRX 공식값 × 수정 비율(가운데 값)'로 맞춘다 — 비율은 시·고·저·종 중 가운데 두 개 평균 (2026-10-13 2차 검토)
                rm = sum(sorted(rat)[1:3]) / 2
                o, h, l, c = (round(x * rm, 2) for x in (o, h, l, c))
                v = old[4]; tv = old[5] or tv
                res["adjusted"] = res.get("adjusted", 0) + 1
                if all(abs(a2 - b2) <= max(0.5, abs(b2) * 1e-5) for a2, b2 in zip(old[:4], (o, h, l, c))):
                    continue
            if t == "spot_daily_prices":
                db.execute(text(f"update {t} set open_price=:o, high_price=:h, low_price=:l, close_price=:c, volume=:v, trading_value=:tv, change_pct=:chg "
                                "where stock_code=:s and trading_date=:d"), {"o": o, "h": h, "l": l, "c": c, "v": v, "tv": tv, "chg": chg, "s": r[0], "d": day})
            else:
                db.execute(text(f"update {t} set open_price=:o, high_price=:h, low_price=:l, close_price=:c, volume=:v, trading_value=:tv "
                                "where stock_code=:s and trading_date=:d"), {"o": o, "h": h, "l": l, "c": c, "v": v, "tv": tv, "s": r[0], "d": day})
            fixed += 1
        res[t] = fixed
    db.commit()
    return res


def fix_recent(db: Session, days: int = 10) -> str:
    """최근 거래일들을 KRX 공식값으로 (매일 아침). 자료가 아직 없는 날(오늘·어제 밤)은 건너뜀."""
    from datetime import timedelta  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    d, done, total, empty = date.today(), 0, 0, []
    while done < days:
        d -= timedelta(days=1)
        if not is_trading_day(d):
            continue
        done += 1
        r = apply(db, d)
        if not r.get("krx"):
            empty.append(str(d))
        total += r.get("spot_daily_prices", 0)
    if total:
        try:      # 날짜만 보는 메모리 캐시 비우기 (같은 프로세스의 스케줄러에서 돎)
            from backend.services.stock_signals import reset_price_caches  # noqa: PLC0415
            reset_price_caches()
        except Exception:  # noqa: BLE001
            pass
        from backend.db.models import JobLog  # noqa: PLC0415
        db.add(JobLog(trading_date=date.today(), stage="spot_price_fix", status="completed", message=f"KRX 공식 시세로 {total}건 바로잡음"))
        db.commit()
    msg = f"KRX 공식 시세 최근 {days}거래일: {total}건 바로잡음" + (f" · 아직 자료 없음 {', '.join(empty)}" if empty else "")
    logger.info(msg)
    return msg
