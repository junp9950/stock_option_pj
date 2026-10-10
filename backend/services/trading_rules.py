"""Shared, deterministic rules. No database, clock, network or account state."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

RULE_VERSION = "2026-10-11.1"


def positive(value):
    return value is not None and math.isfinite(float(value)) and value > 0


def tradable_bar(bar):
    if not bar or not all(positive(x) for x in bar[1:5]):
        return False
    _, o, h, l, c, *_ = bar
    return l <= min(o, c) <= max(o, c) <= h


def locked_down(bar):
    return tradable_bar(bar) and bar[2] == bar[3] and bar[5] <= -29


def net_return(entry, exit_price, cost_buy=.0005, cost_sell=.0025):
    """PnL per unit entry notional, matching the cash ledger exactly."""
    return exit_price / entry * (1 - cost_sell) - (1 + cost_buy)


def size_multiplier(order):
    return float(order.get("size_mult", .5 if order.get("hot") or order.get("semi") else 1.))


def relative_strength(close, turnover):
    raw = sum(w * (close / close.shift(lag) - 1)
              for lag, w in ((63, .4), (126, .2), (189, .2), (252, .2)))
    return raw.where(turnover.rolling(20).mean() >= 3e9).rank(axis=1, pct=True) * 98 + 1


def market_returns(close, turnover):
    """Equal weight, 20-session average turnover >= 1e9; decimal returns."""
    return (close / close.shift(1) - 1).clip(-.3, .3).where(
        turnover.rolling(20).mean() >= 1e9).mean(axis=1).fillna(0.)


def entry_masks(trend, rs, risk, flags, breakout, parts=("score", "ema", "hot"), rs_range=(70, 95)):
    """Works with both pandas Series and numpy arrays; no sector exceptions."""
    score = sum(f.astype(np.int8) for f in flags)
    base = trend & (rs >= rs_range[0]) & (rs < rs_range[1]) & (risk > 0) & (risk <= .08)
    hot = base & (score == 5) & ~flags[5] & ~flags[6] & flags[0] & flags[2] & flags[3] & flags[4]
    buy = base & False
    if "score" in parts:
        buy |= base & (score >= 6)
    if "ema" in parts:
        buy |= base & breakout
    if "hot" in parts:
        buy |= hot
    return buy, hot & ~breakout
