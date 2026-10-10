"""Daily account events shared by forward logs and the tracking screen."""
from __future__ import annotations

from backend.services.trading_rules import locked_down, net_return, positive, size_multiplier, tradable_bar


def ema21(closes):
    value = closes[0]
    for close in closes[1:]:
        value += (close - value) / 11
    return value


def new_account():
    return {"cash": 1., "pos": {}, "pending": [], "eq": [], "trades": [], "peak": 1.}


def day_context(bars, day):
    """Scan each history once; share this immutable view across all accounts."""
    today, opening, closing, lines = {}, {}, {}, {}
    for code, history in bars.items():
        eligible = [b for b in history if b[0] <= day]
        if not eligible:
            continue
        bar = eligible[-1] if eligible[-1][0] == day else None
        if bar:
            today[code] = bar
        prior = next((b[4] for b in reversed(eligible) if b[0] < day and positive(b[4])), None)
        closes = [b[4] for b in eligible if positive(b[4])]
        if closes:
            closing[code] = closes[-1]
        if bar and positive(bar[1]):
            opening[code] = bar[1]
        elif prior is not None:
            opening[code] = prior
        if bar and tradable_bar(bar) and len(closes) >= 30:
            lines[code] = ema21(closes[-130:])
    return {"today": today, "open": opening, "close": closing, "ema": lines}


def equity(account, marks):
    return account["cash"] + sum(p["sh"] * marks.get(c, p["px0"]) for c, p in account["pos"].items())


def advance(account, name, day, context, candidates, entry, *, slots=10, risk=.005, cost_buy=.0005, cost_sell=.0025):
    if entry not in ("close", "next_open"):
        raise ValueError(f"Unsupported entry: {entry}")
    if slots < 0 or risk < 0:
        raise ValueError("slots and risk must be nonnegative")
    stamp = str(day)
    if account["eq"] and account["eq"][-1][0] >= stamp:
        raise ValueError("Account dates must advance strictly; replay on a new account")
    today = context["today"]
    notes, selected, skipped = [], [], []

    def sell(code, price, reason):
        p = account["pos"].pop(code)
        p["hi"] = max(p["hi"], price)
        p["lo"] = min(p["lo"], price)
        net = net_return(p["px0"], price, cost_buy, cost_sell)
        account["cash"] += p["sh"] * price * (1 - cost_sell)
        account["trades"].append({"code": code, "d0": p["d0"], "px0": p["px0"], "d1": stamp,
            "px1": price, "why": reason, "R": round(net / p["risk0"], 6), "net": round(net, 8),
            "mfe": round(p["hi"] / p["px0"] - 1, 4), "mae": round(p["lo"] / p["px0"] - 1, 4),
            "rs": p.get("rs"), "size_mult": p.get("size_mult", 1.),
            "excursion_note": "Daily bars cannot resolve intraday pre-exit high/low"})

    def buy(order, price, capital):
        code, stop = order["code"], order["stop"]
        if code in account["pos"]:
            return
        if len(account["pos"]) >= slots:
            skipped.append(code); notes.append(f"칸 없음 {code}"); return
        if not positive(price) or not positive(stop) or price <= stop:
            skipped.append(code); notes.append(f"유효 진입가/손절 없음 {code}"); return
        real_risk = 1 - stop / price
        plan_risk = order.get("risk") if entry == "close" else real_risk
        plan_risk = plan_risk if positive(plan_risk) else real_risk
        mult = size_multiplier(order)
        if not positive(capital) or risk == 0 or not positive(mult):
            skipped.append(code); return
        if "planned_shares" in order:
            if not positive(order["planned_shares"]):
                skipped.append(code); return
            value = order["planned_shares"] * price
        else:
            value = risk * capital * mult / max(plan_risk, .003)
        account["cash"] -= value * (1 + cost_buy)
        account["pos"][code] = {"sh": value / price, "px0": price, "d0": stamp, "stop": stop,
            "risk0": real_risk, "risk_plan": plan_risk, "rs": order.get("rs"), "hi": price, "lo": price,
            "exit_next": False, "size_mult": mult, "tag": order.get("tag", order.get("score")),
            "heat": value * real_risk / capital}
        selected.append(code)

    # Only exits already known at the open release slots for opening buys.
    for code, p in list(account["pos"].items()):
        bar = today.get(code)
        if not tradable_bar(bar):
            notes.append(f"시세 결측/정지 이월 {code}"); continue
        if locked_down(bar):
            if p["exit_next"] or bar[3] <= p["stop"]:
                p["exit_next"] = True
            notes.append(f"하한가 잠김 이월 {code}"); continue
        if p["exit_next"] or bar[1] <= p["stop"]:
            sell(code, bar[1], "21선/이월" if p["exit_next"] else "손절")

    if entry == "next_open":
        capital = equity(account, context["open"])
        for order in account["pending"]:
            bar = today.get(order["code"])
            if not tradable_bar(bar) or locked_down(bar) or (bar[2] == bar[3] and bar[5] >= 29):
                skipped.append(order["code"]); notes.append(f"시가 주문 미체결 {order['code']}"); continue
            buy(order, bar[1], capital)
        account["pending"] = []

    # Stops include positions bought at today's open, never today's close buys.
    for code, p in list(account["pos"].items()):
        bar = today.get(code)
        if not tradable_bar(bar) or locked_down(bar):
            continue
        if bar[3] <= p["stop"]:
            sell(code, min(bar[1], p["stop"]), "손절")
        else:
            p["hi"] = max(p["hi"], bar[2]); p["lo"] = min(p["lo"], bar[3])

    if entry == "close":
        capital = equity(account, context["close"])
        for order in candidates:
            bar = today.get(order["code"])
            if not tradable_bar(bar) or locked_down(bar) or (bar[2] == bar[3] and bar[5] >= 29):
                skipped.append(order["code"]); continue
            buy(order, bar[4], capital)
    else:
        # Preserve size/stop/RS from the signal date, including half-size flags.
        account["pending"] = [dict(x) for x in candidates if x["code"] not in account["pos"]]

    for code, p in account["pos"].items():
        if code in context["ema"] and context["close"][code] < context["ema"][code]:
            p["exit_next"] = True
    total = equity(account, context["close"])
    account["peak"] = max(account.get("peak", 1.), total)
    account["eq"].append([stamp, round(total, 8)])
    heat = sum(p["sh"] * p["px0"] * p["risk0"] for p in account["pos"].values()) / total if total > 0 else 0
    return {"acct": name, "equity": round(total, 8), "dd": round(total / account["peak"] - 1, 4),
            "npos": len(account["pos"]), "heat": round(heat, 4), "selected": selected, "skipped": skipped, "notes": notes}
