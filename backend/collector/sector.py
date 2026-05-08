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
from backend.utils.retry import retry


logger = get_logger(__name__)

_CUSTOM_SECTORS_PATH = Path(__file__).resolve().parent.parent / "data" / "custom_sectors.json"

_NAVER_THEME_LIST_URL = "https://finance.naver.com/sise/theme.naver"
_NAVER_THEME_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}


def _get(url: str, timeout: int = 10) -> requests.Response:
    return retry(lambda: requests.get(url, headers=_HEADERS, timeout=timeout), attempts=3, delay_seconds=1.5)


def _parse_naver_theme_list() -> list[dict]:
    """네이버 금융 테마 목록 파싱 → [{"no": "...", "name": "..."}]"""
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
    except ImportError:
        logger.warning("beautifulsoup4 미설치 — 네이버 테마 크롤링 스킵")
        return []

    try:
        resp = _get(_NAVER_THEME_LIST_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        themes = []
        for a in soup.select("td.col_type1 a"):
            href = a.get("href", "")
            if "no=" not in href:
                continue
            no = href.split("no=")[-1].split("&")[0]
            name = a.get_text(strip=True)
            if no and name:
                themes.append({"no": no, "name": name})
        logger.info("네이버 테마 목록 %d개 수집", len(themes))
        return themes
    except Exception as exc:  # noqa: BLE001
        logger.warning("네이버 테마 목록 수집 실패: %s", exc)
        return []


def _parse_naver_theme_stocks(no: str) -> list[str]:
    """특정 테마 소속 종목코드 리스트 반환"""
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
    except ImportError:
        return []

    try:
        url = _NAVER_THEME_DETAIL_URL.format(no=no)
        resp = _get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        codes = []
        for a in soup.select("td.left a"):
            href = a.get("href", "")
            if "code=" in href:
                code = href.split("code=")[-1].split("&")[0].zfill(6)
                if code:
                    codes.append(code)
        return codes
    except Exception as exc:  # noqa: BLE001
        logger.warning("네이버 테마 %s 종목 수집 실패: %s", no, exc)
        return []


def _collect_naver_themes() -> dict[str, dict]:
    """네이버 테마 전체 수집 → {"sector_code": {"name": ..., "codes": [...]}}"""
    themes = _parse_naver_theme_list()
    result: dict[str, dict] = {}
    for i, theme in enumerate(themes):
        no = theme["no"]
        codes = _parse_naver_theme_stocks(no)
        if codes:
            result[f"naver_{no}"] = {"name": theme["name"], "codes": codes}
        if i > 0 and i % 10 == 0:
            logger.info("네이버 테마 수집 중: %d / %d", i, len(themes))
        time.sleep(1.0)  # 요청 간격 준수
    logger.info("네이버 테마 수집 완료: %d개", len(result))
    return result


def _collect_krx_industries() -> dict[str, dict]:
    """FDR에서 KRX 업종 분류 수집 → {"krx_{업종명}": {"name": ..., "codes": [...]}}"""
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        result: dict[str, dict] = {}
        for market in ("KOSPI", "KOSDAQ"):
            listing = fdr.StockListing(market)
            # Sector / Industry 컬럼 탐색
            sector_col = next((c for c in listing.columns if c.lower() in ("sector", "industry", "업종")), None)
            if sector_col is None:
                logger.warning("FDR %s 업종 컬럼 없음, KRX 업종 수집 스킵", market)
                continue
            listing["Code"] = listing["Code"].astype(str).str.zfill(6)
            for sector_name, group in listing.groupby(sector_col):
                if not sector_name or str(sector_name).strip() == "":
                    continue
                key = f"krx_{sector_name}"
                codes = group["Code"].tolist()
                if key not in result:
                    result[key] = {"name": str(sector_name), "codes": []}
                result[key]["codes"].extend(codes)
        logger.info("KRX 업종 수집 완료: %d개", len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("KRX 업종 수집 실패: %s", exc)
        return {}


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


def _source_of(sector_code: str) -> str:
    if sector_code.startswith("naver_"):
        return "naver_theme"
    if sector_code.startswith("krx_"):
        return "krx_industry"
    return "custom"


def refresh_sector_mapping(db: Session, include_naver: bool = True, include_krx: bool = True) -> dict:
    """섹터 매핑 전체 갱신.

    크롤링 실패해도 커스텀 섹터는 항상 반영.
    기존 데이터 삭제 없이 upsert 방식으로 추가/업데이트.
    """
    all_sectors: dict[str, dict] = {}

    # 1. 커스텀 섹터 (항상)
    all_sectors.update(_load_custom_sectors())

    # 2. 네이버 테마
    if include_naver:
        try:
            all_sectors.update(_collect_naver_themes())
        except Exception as exc:  # noqa: BLE001
            logger.error("네이버 테마 수집 오류 (기존 매핑 유지): %s", exc)

    # 3. KRX 업종
    if include_krx:
        try:
            all_sectors.update(_collect_krx_industries())
        except Exception as exc:  # noqa: BLE001
            logger.error("KRX 업종 수집 오류 (기존 매핑 유지): %s", exc)

    if not all_sectors:
        logger.warning("수집된 섹터 없음 — 기존 매핑 유지")
        return {"added": 0, "updated": 0, "skipped": 0}

    added = updated = skipped = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for sector_code, info in all_sectors.items():
        name = info["name"]
        codes: list[str] = list(dict.fromkeys(info["codes"]))  # 중복 제거
        source = _source_of(sector_code)

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
