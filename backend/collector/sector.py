from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Sector, SectorStock
from backend.utils.logger import get_logger


logger = get_logger(__name__)

_CUSTOM_SECTORS_PATH = Path(__file__).resolve().parent.parent / "data" / "custom_sectors.json"

# 네이버 증권 모바일 API (옛 finance.naver.com 테마 페이지는 stock.naver.com으로 옮겨가 HTML 파싱이 막힘)
_NAVER_THEME_LIST_URL = "https://m.stock.naver.com/api/stocks/theme"
_NAVER_THEME_DETAIL_URL = "https://m.stock.naver.com/api/stocks/theme/{no}"
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_NAVER_PAGE_SIZE = 100


def _naver_json(url: str, params: dict) -> dict | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=_NAVER_HEADERS, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("네이버 테마 API %s → HTTP %s", url, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("네이버 테마 API %s 실패: %s", url, exc)
        time.sleep(2 * (attempt + 1))
    return None


def _paged(url: str, key: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        data = _naver_json(url, {"page": page, "pageSize": _NAVER_PAGE_SIZE})
        batch = (data or {}).get(key) or []
        items.extend(batch)
        if not batch or len(items) >= (data.get("totalCount") or 0):
            return items
        page += 1
        time.sleep(0.3)


def _collect_naver_themes() -> dict[str, dict]:
    """네이버 테마 전체 → {"naver_{번호}": {"name": 테마명, "codes": [...]}}. 테마 목록과 테마별 소속 종목만 읽는다."""
    themes = _paged(_NAVER_THEME_LIST_URL, "groups")
    result: dict[str, dict] = {}
    for theme in themes:
        stocks = _paged(_NAVER_THEME_DETAIL_URL.format(no=theme["no"]), "stocks")
        codes = [s["itemCode"] for s in stocks if s.get("stockType") == "domestic" and s.get("itemCode")]
        if codes:
            result[f"naver_{theme['no']}"] = {"name": theme["name"], "codes": codes}
        time.sleep(0.3)
    logger.info("네이버 테마 수집 완료: %d / %d개", len(result), len(themes))
    return result


def _load_custom_sectors() -> dict[str, dict]:
    """custom_sectors.json 로드 → {"sector_name": {"name": ..., "codes": [...]}}"""
    if not _CUSTOM_SECTORS_PATH.exists():
        return {}
    try:
        raw: dict[str, list[str]] = json.loads(_CUSTOM_SECTORS_PATH.read_text(encoding="utf-8"))
        result = {
            f"custom_{name}": {"name": name, "codes": codes}
            for name, codes in raw.items()
        }
        logger.info("커스텀 섹터 %d개 로드", len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("커스텀 섹터 로드 실패: %s", exc)
        return {}


def refresh_sector_mapping(db: Session, include_naver: bool = True) -> dict:
    """커스텀 섹터 + 네이버 테마 매핑 갱신. 기존 데이터 삭제 없이 upsert (네이버 수집 실패 시 기존 테마 유지)."""
    all_sectors = _load_custom_sectors()
    if include_naver:
        all_sectors.update(_collect_naver_themes())

    if not all_sectors:
        logger.warning("수집된 섹터 없음 — 기존 매핑 유지")
        return {"added": 0, "updated": 0, "skipped": 0}

    added = updated = skipped = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for sector_code, info in all_sectors.items():
        name = info["name"]
        codes: list[str] = list(dict.fromkeys(info["codes"]))  # 중복 제거
        source = "naver_theme" if sector_code.startswith("naver_") else "custom"

        sector = db.scalar(select(Sector).where(Sector.sector_code == sector_code))
        if sector is None:
            sector = Sector(sector_code=sector_code, sector_name=name, source=source, is_active=True)
            db.add(sector)
            db.flush()
            added += 1
        else:
            old_name = sector.sector_name
            sector.sector_name = name
            sector.updated_at = now
            updated += 1
            if old_name != name:
                logger.info("섹터명 변경: %s → %s (%s)", old_name, name, sector_code)

        # 종목 매핑: 기존 조회 후 신규만 추가 (삭제 안 함)
        existing_codes = {
            row.stock_code
            for row in db.scalars(select(SectorStock).where(SectorStock.sector_id == sector.id))
        }
        new_codes = set(codes) - existing_codes
        removed_codes = existing_codes - set(codes)

        for code in new_codes:
            db.add(SectorStock(sector_id=sector.id, stock_code=code))
        # 제거된 종목은 로그만 남기고 실제로 삭제하지 않음 (수급 히스토리 보존)
        if removed_codes:
            logger.info("섹터 %s에서 종목 %d개 제거됨 (매핑만 로그, DB는 유지)", sector_code, len(removed_codes))

        if not new_codes and not removed_codes:
            skipped += 1

    db.commit()
    logger.info("섹터 매핑 갱신 완료: added=%d updated=%d skipped=%d", added, updated, skipped)
    return {"added": added, "updated": updated, "skipped": skipped}


def needs_refresh(db: Session, max_age_days: int = 7) -> bool:
    """마지막 갱신이 max_age_days 이상 지났거나 데이터가 없으면 True."""
    sector = db.scalar(select(Sector).limit(1))
    if sector is None:
        return True
    cutoff = datetime.utcnow().replace(tzinfo=None)
    from datetime import timedelta  # noqa: PLC0415
    age = cutoff - sector.updated_at.replace(tzinfo=None) if sector.updated_at else None
    if age is None or age.days >= max_age_days:
        return True
    return False
