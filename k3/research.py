"""K3 research mode — walk-forward parameter validation.

Grid is intentionally SMALL (this is validation, not curve-fitting):
  atr_stop_mult x tier_active x tp ladder variant.
Each combo: train on first 60% of bars, keep it only if train PF >= 1.1,
then report OUT-OF-SAMPLE results on the last 40%. OOS is the number that matters.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List

import numpy as np

from . import data
from .backtest import backtest_symbol
from .config import Profile, clone_profile

GRID = {
    "atr_stop_mult": [1.0, 1.3, 1.6, 1.8, 2.2],
    "tier_active": [58, 62, 66, 70],
    "tp_variant": ["tight", "base", "wide"],
}
TP_LADDERS = {
    "tight": ([0.7, 1.4, 2.2], [0.50, 0.30, 0.20]),
    "base": ([1.0, 2.0, 3.0], [0.50, 0.30, 0.20]),
    "wide": ([1.5, 2.5, 4.0], [0.40, 0.35, 0.25]),
}


def _slice_df(df, frac_lo: float, frac_hi: float):
    n = len(df)
    return df.iloc[int(n * frac_lo): int(n * frac_hi)].reset_index(drop=True)


def research_symbol(symbol: str, base: Profile, limit: int = 1500) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    df = data.klines(sym, base.timeframe, limit)
    if len(df) < 400:
        return {"symbol": sym, "error": f"insufficient bars ({len(df)})"}

    results = []
    for atr_m in GRID["atr_stop_mult"]:
        for tier in GRID["tier_active"]:
            for tv in GRID["tp_variant"]:
                tp_r, tp_pct = TP_LADDERS[tv]
                p = clone_profile(base)
                p.risk.atr_stop_mult = atr_m
                p.risk.tp_r, p.risk.tp_pct = list(tp_r), list(tp_pct)
                p.tier_active = float(tier)
                train = backtest_symbol(sym, p, df=_slice_df(df, 0.0, 0.6))
                if train.get("trades", 0) < 5 or train.get("profit_factor", 0) < 1.1:
                    continue
                oos = backtest_symbol(sym, p, df=_slice_df(df, 0.6, 1.0))
                if oos.get("trades", 0) < 3:
                    continue
                results.append({
                    "params": {"atr_stop_mult": atr_m, "tier_active": tier, "tp_variant": tv},
                    "train": {"trades": train["trades"], "pf": train["profit_factor"],
                              "ret_pct": train["return_pct"]},
                    "oos": {"trades": oos["trades"], "pf": oos["profit_factor"],
                            "ret_pct": oos["return_pct"], "win_rate": oos["win_rate"],
                            "max_dd": oos["max_drawdown_pct"]},
                })
    results.sort(key=lambda x: (x["oos"]["pf"] if x["oos"]["pf"] != float("inf") else 99), reverse=True)
    return {"symbol": sym, "profile": base.name, "combos_passed_train": len(results),
            "top": results[:5]}


def research_universe(symbols: List[str], base: Profile, limit: int = 1500) -> Dict[str, Any]:
    per = [research_symbol(s, base, limit) for s in symbols]
    # consensus: params that appear in top-5 across most symbols
    from collections import Counter
    votes: Counter = Counter()
    for r in per:
        for t in r.get("top", [])[:3]:
            prm = t["params"]
            votes[(prm["atr_stop_mult"], prm["tier_active"], prm["tp_variant"])] += 1
    consensus = [
        {"atr_stop_mult": k[0], "tier_active": k[1], "tp_variant": k[2], "symbols_voting": v}
        for k, v in votes.most_common(5)
    ]
    return {"profile": base.name, "symbols": len(symbols), "consensus": consensus, "per_symbol": per}
