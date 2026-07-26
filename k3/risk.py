"""K3 risk engine — sizing, TP ladders, portfolio caps.

Fixed-fractional kernel (Quantrex lineage): risk 1% of capital per trade,
stop = ATR x mult, scale-out ladder, trailing after TP1, time exit.
K3 adds: score-scaled risk (higher conviction -> up to 1.5x base risk),
correlation-aware portfolio cap, and suggested leverage with cap.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .config import Profile


def score_risk_multiplier(score: float, p: Profile) -> float:
    """Conviction scaling: WATCH -> 0.75x, ACTIVE -> 1.0x, elite (>=active+10) -> 1.25x."""
    if score >= p.tier_active + 10:
        return 1.25
    if score >= p.tier_active:
        return 1.0
    return 0.75


def build_trade_plan(
    *,
    direction: int,
    entry: float,
    atr: float,
    score: float,
    capital: float,
    p: Profile,
) -> Dict[str, Any]:
    r = p.risk
    atr = atr if atr > 0 else entry * 0.002
    stop_dist = r.atr_stop_mult * atr
    stop = entry - direction * stop_dist
    tps = [entry + direction * rr * stop_dist for rr in r.tp_r]

    mult = score_risk_multiplier(score, p)
    risk_usd = capital * r.risk_per_trade * mult
    qty = risk_usd / stop_dist
    notional = qty * entry
    leverage = notional / capital
    capped = False
    if leverage > r.max_leverage:
        leverage = r.max_leverage
        notional = capital * r.max_leverage
        qty = notional / entry
        capped = True

    # expected value snapshot: weighted R of ladder vs 1R risk
    ev_r = sum(rr * pct for rr, pct in zip(r.tp_r, r.tp_pct))

    return {
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "stop_distance_pct": round(stop_dist / entry * 100, 3),
        "tp_ladder": [
            {"R": rr, "close_pct": pct, "price": round(tp, 8)}
            for rr, pct, tp in zip(r.tp_r, r.tp_pct, tps)
        ],
        "risk_usd": round(risk_usd, 2),
        "risk_multiplier": mult,
        "quantity": round(qty, 6),
        "notional_usd": round(notional, 2),
        "leverage_suggested": round(leverage, 2),
        "leverage_capped": capped,
        "ladder_expected_R": round(ev_r, 2),
        "trail_after_tp1": r.trail_after_tp1,
        "trail_atr_mult": r.trail_atr_mult,
        "max_hold_bars": r.max_hold_bars,
    }


def portfolio_check(
    new_setup: Dict[str, Any],
    open_setups: List[Dict[str, Any]],
    p: Profile,
    btc_corr: float | None = None,
) -> Dict[str, Any]:
    """Portfolio-level admission: max concurrent, same-direction stacking, BTC corr clusters."""
    r = p.risk
    if len(open_setups) >= r.max_concurrent:
        return {"admit": False, "reason": f"max_concurrent={r.max_concurrent} reached"}
    same_dir = [s for s in open_setups if s.get("direction") == new_setup.get("direction")]
    if len(same_dir) >= max(1, r.max_concurrent - 1):
        return {"admit": False, "reason": "same-direction stack limit"}
    if btc_corr is not None and abs(btc_corr) > 0.9:
        btc_open = [s for s in open_setups if s.get("symbol") == "BTCUSDT" and s.get("direction") == new_setup.get("direction")]
        if btc_open:
            return {"admit": False, "reason": f"BTC-correlated duplicate (rho={btc_corr:.2f})"}
    return {"admit": True, "reason": "ok"}
