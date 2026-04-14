"""공매도 데이터 백필 스크립트.

KIS API daily-short-sale (FHPST04830000)로 종목별 과거 공매도 데이터를 일괄 수집해서 DB에 저장.
실행: python scripts/backfill_short.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.database import SessionLocal
from backend.db.models import ShortSellingDaily, Stock
from backend.collector.spot import _get_kis_token
from sqlalchemy import select

START_DATE = "20260101"
END_DATE   = "20260412"   # 이미 04-13~04-14는 수집됨


def fetch_short_for_stock(token: str, app_key: str, app_secret: str, code: str) -> list[dict]:
    """종목 하나의 공매도 일별 데이터 조회. output2 리스트 반환."""
    r = requests.get(
        "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/daily-short-sale",
        headers={
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHPST04830000",
            "content-type": "application/json",
        },
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": START_DATE,
            "FID_INPUT_DATE_2": END_DATE,
        },
        timeout=10,
    )
    j = r.json()
    if j.get("rt_cd") != "0":
        return []
    return j.get("output2", [])


def main():
    app_key    = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        print("KIS_APP_KEY / KIS_APP_SECRET 없음")
        sys.exit(1)

    token = _get_kis_token()
    if not token:
        print("KIS 토큰 발급 실패")
        sys.exit(1)

    db = SessionLocal()
    try:
        codes = [s.code for s in db.scalars(select(Stock).where(Stock.is_active.is_(True)))]
        print(f"총 {len(codes)}종목 백필 시작 ({START_DATE} ~ {END_DATE})")

        total_rows = 0
        for idx, code in enumerate(codes, 1):
            try:
                rows = fetch_short_for_stock(token, app_key, app_secret, code)
                if rows:
                    records = []
                    for row in rows:
                        d = row.get("stck_bsop_date", "")
                        if not d or len(d) != 8:
                            continue
                        trading_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                        vol   = float(row.get("ssts_cntg_qty") or 0)
                        ratio = float(row.get("ssts_vol_rlim") or 0)
                        bal   = float(row.get("ssts_tr_pbmn") or 0)
                        records.append({
                            "trading_date": trading_date,
                            "stock_code":   code,
                            "short_volume": vol,
                            "short_ratio":  ratio,
                            "short_balance": bal,
                        })
                    if records:
                        stmt = pg_insert(ShortSellingDaily).values(records)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["trading_date", "stock_code"],
                            set_={
                                "short_volume":  stmt.excluded.short_volume,
                                "short_ratio":   stmt.excluded.short_ratio,
                                "short_balance": stmt.excluded.short_balance,
                            },
                        )
                        db.execute(stmt)
                        db.commit()
                        total_rows += len(records)
                        print(f"[{idx:3d}/{len(codes)}] {code}: {len(records)}일치 저장")
                    else:
                        print(f"[{idx:3d}/{len(codes)}] {code}: 공매도 데이터 없음")
                else:
                    print(f"[{idx:3d}/{len(codes)}] {code}: 응답 없음")
            except Exception as e:
                print(f"[{idx:3d}/{len(codes)}] {code}: 오류 - {e}")
                db.rollback()

            time.sleep(0.15)

        print(f"\n백필 완료: 총 {total_rows}개 레코드 저장")
    finally:
        db.close()


if __name__ == "__main__":
    main()
