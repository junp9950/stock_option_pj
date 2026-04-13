"""
SQLite → Supabase(PostgreSQL) 데이터 이전 스크립트
집에서 실행하세요 (회사망에서는 Supabase 접속 차단됨)

실행 방법:
  .venv/Scripts/python migrate_to_supabase.py
"""
from __future__ import annotations

import os
import sys

# .env 로드 (DATABASE_URL 읽기 위해)
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

SQLITE_URL = f"sqlite:///{(Path(__file__).parent / 'data' / 'app.db').as_posix()}"
PG_URL = os.getenv("DATABASE_URL", "")

if not PG_URL or not PG_URL.startswith("postgresql"):
    print("❌ .env 파일에 DATABASE_URL이 설정되어 있지 않습니다.")
    sys.exit(1)

print(f"소스: {SQLITE_URL}")
print(f"대상: {PG_URL[:60]}...")
print()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 두 엔진 생성
sqlite_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
pg_engine = create_engine(PG_URL)

# PostgreSQL에 테이블 생성
print("[1] Supabase에 테이블 생성 중...")
sys.path.insert(0, str(Path(__file__).parent))
from backend.db.models import Base
Base.metadata.create_all(pg_engine)
print("  -> 테이블 생성 완료")
print()

SQLiteSession = sessionmaker(bind=sqlite_engine)
PgSession = sessionmaker(bind=pg_engine)

# SQLite boolean(0/1) → PostgreSQL boolean(True/False) 변환 대상 컬럼
BOOL_COLS = {
    "stocks": ["is_active"],
    "trading_calendar": ["is_trading_day"],
    "stock_signal_details": ["is_enabled"],
    "market_signal_details": ["is_enabled"],
}

# 이전할 테이블 목록 (순서 중요 - FK 의존성)
TABLES = [
    "stocks",
    "spot_daily_prices",
    "spot_investor_flows",
    "market_signals",
    "market_signal_details",
    "stock_signals",
    "job_logs",
]
# stock_signal_details (120만행) 제외 — 서버에서 signal-backfill로 재계산 가능

sqlite_conn = sqlite_engine.connect()
pg_conn = pg_engine.connect()

for table in TABLES:
    # 행 수 확인
    count = sqlite_conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
    if count == 0:
        print(f"  skip {table}: 비어있음")
        continue

    print(f"  {table}: {count:,}행 이전 중...", end="", flush=True)

    # 기존 데이터 삭제
    pg_conn.execute(text(f'DELETE FROM "{table}"'))
    pg_conn.commit()

    # SQLite에서 읽어서 PostgreSQL에 삽입 (배치 단위)
    rows = sqlite_conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
    cols = sqlite_conn.execute(text(f'SELECT * FROM "{table}" LIMIT 0')).keys()
    col_names = list(cols)

    BATCH = 1000
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i+BATCH]
        bool_cols = BOOL_COLS.get(table, [])
        col_str = ", ".join(f'"{c}"' for c in col_names)
        val_str = ", ".join(f":{c}" for c in col_names)

        def convert_row(row):
            d = dict(zip(col_names, row))
            for bc in bool_cols:
                if bc in d and d[bc] is not None:
                    d[bc] = bool(d[bc])
            return d

        pg_conn.execute(
            text(f'INSERT INTO "{table}" ({col_str}) VALUES ({val_str})'),
            [convert_row(row) for row in batch]
        )
        pg_conn.commit()

    print(" done")

sqlite_conn.close()
pg_conn.close()

print()
print("이전 완료! 이제 서버 실행하면 Supabase를 사용합니다.")
