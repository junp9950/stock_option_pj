from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.signal_engine.sector_signal import _percentile_rank, _calc_buy_streak


def test_percentile_rank_basic():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile_rank(values, 3.0) == 0.4  # 3보다 작은 값 2개 / 5 = 0.4
    assert _percentile_rank(values, 1.0) == 0.0   # 최솟값
    assert _percentile_rank(values, 5.0) == 0.8   # 5보다 작은 값 4개 / 5 = 0.8


def test_percentile_rank_empty():
    assert _percentile_rank([], 1.0) == 0.5


def test_percentile_rank_negative():
    values = [-100.0, 0.0, 100.0]
    assert _percentile_rank(values, 0.0) == pytest.approx(1 / 3)


def test_custom_sectors_json_valid():
    """custom_sectors.json 파일이 올바른 형식인지 확인."""
    path = Path(__file__).parent.parent / "backend" / "data" / "custom_sectors.json"
    assert path.exists(), "custom_sectors.json 파일이 없습니다"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for name, codes in data.items():
        assert isinstance(name, str) and name
        assert isinstance(codes, list) and len(codes) > 0
        for code in codes:
            assert len(code) == 6 and code.isdigit(), f"잘못된 종목코드: {code} in {name}"


def test_calc_buy_streak_zero_for_negative():
    """combined_net_buy가 0 이하이면 streak = 0."""
    db = MagicMock()
    result = _calc_buy_streak(db, sector_id=1, current_date=None, current_combined=-100)
    assert result == 0


def test_calc_buy_streak_counts_consecutive(mocker):
    """연속 양수 레코드를 올바르게 카운트하는지 확인."""
    from datetime import date
    from backend.db.models import SectorFlowDaily

    past_rows = []
    for combined in [500, 300, 200, -100, 400]:
        row = MagicMock(spec=SectorFlowDaily)
        row.combined_net_buy = combined
        past_rows.append(row)

    db = MagicMock()
    db.scalar.return_value = None
    db.scalars.return_value = iter(past_rows)

    result = _calc_buy_streak(db, sector_id=1, current_date=date(2026, 4, 29), current_combined=600)
    # 오늘(600) + 과거 연속: 500, 300, 200 → -100에서 끊김 → streak=4
    assert result == 4
