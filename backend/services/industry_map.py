"""종목별 업종 (KIND 상장법인 목록의 표준산업분류). 차트 후보 업종 필터용.

하루 한 번 받아 data/industry_cache/industry.json에 저장하고, 화면 계산에서는 파일만 읽는다.
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)

PATH = Path(__file__).resolve().parents[2] / "data" / "industry_cache" / "industry.json"
URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"

# KRX 업종처럼 넓게 부르는 이름 → 표준산업분류 업종명에 들어가는 단어
GROUPS: dict[str, list[str]] = {
    "전기전자": ["반도체", "전자부품", "통신 및 방송 장비", "컴퓨터 및 주변장치", "영상 및 음향", "전동기",
             "전지", "절연선", "조명장치", "전기장비", "가정용 기기", "측정, 시험"],
    "제약바이오": ["의약품", "의료용 물질", "자연과학 및 공학 연구개발"],
    "의료기기": ["의료용 기기"],
    "2차전지": ["전지"],
    "화학": ["화학", "플라스틱", "고무"],
    "기계": ["기계 제조업"],
    "철강금속": ["철강", "금속"],
    "자동차": ["자동차"],
    "조선": ["선박"],
    "건설": ["건설", "건물"],
    "IT서비스": ["소프트웨어", "컴퓨터 프로그래밍", "정보서비스", "자료처리"],
    "금융": ["금융", "보험", "은행", "신탁"],
}


def refresh() -> None:
    try:
        r = requests.get(URL, params={"method": "download", "searchType": "13"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        df = pd.read_html(StringIO(r.content.decode("euc-kr")))[0]
        payload = {str(c).zfill(6): str(s) for c, s in zip(df["종목코드"], df["업종"]) if isinstance(s, str)}
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PATH)
        logger.info("업종 캐시 갱신: %d종목", len(payload))
    except Exception as exc:  # noqa: BLE001
        logger.error("업종 캐시 갱신 실패 (이전 캐시 유지): %s", exc)


def industries() -> dict[str, str]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
