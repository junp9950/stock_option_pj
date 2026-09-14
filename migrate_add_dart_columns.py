"""
recommendations 테이블에 DART 실적 점수 컬럼 추가 (Alembic 미사용 - 1회성 수동 마이그레이션)

실행 방법:
  .venv/bin/python migrate_add_dart_columns.py   (VM)
  .venv/Scripts/python migrate_add_dart_columns.py  (Windows)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text

DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    raise SystemExit(".env에 DATABASE_URL이 설정되어 있지 않습니다")

engine = create_engine(DB_URL)

STATEMENTS = [
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS earnings_score DOUBLE PRECISION",
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS earnings_max DOUBLE PRECISION",
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS earnings_note TEXT",
]

with engine.begin() as conn:
    for stmt in STATEMENTS:
        print(f"실행: {stmt}")
        conn.execute(text(stmt))

print("완료")
