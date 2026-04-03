from __future__ import annotations


def format_krw(value: float) -> str:
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:,.1f}억원"
    return f"{value:,.0f}원"


def format_contracts(value: float) -> str:
    return f"{value:,.0f}계약"

