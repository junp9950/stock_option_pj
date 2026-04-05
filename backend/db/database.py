from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import get_config


config = get_config()

_connect_args = {}
if config.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    config.database_url,
    future=True,
    echo=False,
    connect_args=_connect_args,
)

# SQLite WAL 모드: 동시 읽기/쓰기 허용 (백필 + 서버 동시 실행 가능)
if config.database_url.startswith("sqlite"):
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode=WAL"))
        conn.execute(__import__("sqlalchemy").text("PRAGMA busy_timeout=10000"))

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

