from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import get_config
from backend.db.database import Base, SessionLocal, engine
from backend.db.seed import seed_reference_data
from backend.scheduler import start_scheduler
from backend.services.daily_pipeline import run_daily_pipeline


config = get_config()
app = FastAPI(title=config.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=config.api_prefix)


@app.on_event("startup")
def startup_event() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        run_daily_pipeline(db)
    finally:
        db.close()
    start_scheduler()

