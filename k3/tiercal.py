"""K3 tier recalibration — train-slice thresholds, out-of-sample verdict.

Fable5 directive (2026-07): the shipped tier_active / tier_watch values were
calibrated in-sample on the leaked engine, so they are meaningless. Redo it
properly:

  1. TRAIN (first 60% of bars): compute the distribution of k3_score on
     signal bars -> candidate tier_active values = score quantiles
     (q50/q60/q70/q80/q90) plus the shipped value as a control.
  2. OOS (last 40%, signals computed on full causal history, trades only
     opened after the cut): backtest each candidate.
  3. ADOPT only if a candidate beats the shipped value in aggregate OOS net
     P&L AND is non-negative on >= 60% of symbols with trades.
     Otherwise keep the shipped tiers and say so.

Given the group-IC study shows the composite has no demonstrable edge, the
expected honest outcome is that NO threshold rescues it — this module exists
to prove or refute that, not to find a number that looks good.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List

import numpy as np

from . import data
from .backtest import backtest_symbol
from .config import Profile
from .signals import score_dataframe
from .structure import build_structure

TRAIN_FRAC = 0.60
QUANTILES = [0.50, 0.60, 0.70, 0.80, 0.90]


def tiercal(symbols: List[str], p: Profile, limit: int = 1500) -> Dict[str, Any]:
    candidates: List[float] = sorted({round(float(p.tier_active), 1)})
    per_symbol_rows: List[Dict[str, Any]] = []
    # candidate -> list of per-symbol OOS results
    oos_by_cand: Dict[float, List[Dict[str, Any]]] = {}

    for sym in symbols:
        sym = sym.upper().replace("/", "")
        try:
            raw = data.klines(sym, p.timeframe, limit)
            if len(raw) < 300:
                per_symbol_rows.append({"symbol": sym, "error": f"insufficient bars ({len(raw)})"})
                continue
            train_end = int(len(raw) * TRAIN_FRAC)
            scored = score_dataframe(build_structure(raw, p), p)
            sig = scored["k3_score"][(scored["k3_dir"] != 0)].iloc[80:train_end]
            if len(sig) < 40:
                per_symbol_rows.append({"symbol": sym, "error": "too few train signal bars"})
                continue
            qs = {q: round(float(np.quantile(sig, q)), 1) for q in QUANTILES}
            for v in qs.values():
                if v not in candidates:
                    candidates.append(v)
            row: Dict[str, Any] = {"symbol": sym, "train_end_bar": train_end,
                                   "train_signal_bars": int(len(sig)),
                                   "train_score_quantiles": qs, "oos": {}}
            for cand in sorted(set(qs.values()) | {round(float(p.tier_active), 1)}):
                pc = replace(p, tier_active=cand)
                res = backtest_symbol(sym, pc, df=raw, start_bar=train_end)
                row["oos"][str(cand)] = {
                    "trades": res.get("trades", 0),
                    "net_pnl_usd": res.get("net_pnl_usd", 0.0),
                    "profit_factor": res.get("profit_factor"),
                }
                oos_by_cand.setdefault(cand, []).append({"symbol": sym, **row["oos"][str(cand)]})
            per_symbol_rows.append(row)
        except Exception as e:  # noqa: BLE001
            per_symbol_rows.append({"symbol": sym, "error": str(e)})

    candidates = sorted(candidates)
    summary: List[Dict[str, Any]] = []
    for cand in candidates:
        rows = oos_by_cand.get(cand, [])
        traded = [r for r in rows if r["trades"] > 0]
        total = float(sum(r["net_pnl_usd"] for r in traded))
        nonneg = float(np.mean([r["net_pnl_usd"] >= 0 for r in traded])) if traded else 0.0
        summary.append({
            "tier_active": cand,
            "symbols_traded": len(traded),
            "total_trades": int(sum(r["trades"] for r in traded)),
            "oos_net_pnl_usd": round(total, 2),
            "frac_symbols_nonneg": round(nonneg, 2),
        })
    summary.sort(key=lambda x: x["oos_net_pnl_usd"], reverse=True)

    shipped = round(float(p.tier_active), 1)
    # Thin candidates (traded on <3 symbols) are multiple-comparisons noise —
    # a threshold validated on one symbol proves nothing about the universe.
    min_breadth = max(3, int(np.ceil(0.5 * len(symbols))))
    best = next((s for s in summary if s["symbols_traded"] >= min_breadth), None)
    shipped_row = next((s for s in summary if s["tier_active"] == shipped), None)
    adopt = None
    if (best and shipped_row and best["oos_net_pnl_usd"] > 0
            and best["oos_net_pnl_usd"] > shipped_row["oos_net_pnl_usd"]
            and best["frac_symbols_nonneg"] >= 0.6):
        adopt = best["tier_active"]
    verdict = (
        f"ADOPT tier_active={adopt} (validated on {best['symbols_traded']} symbols)" if adopt is not None
        else f"KEEP shipped tier_active={shipped} — no candidate cleared the OOS adoption gate "
             f"(requires breadth >= {min_breadth} symbols, OOS net > 0, >=60% symbols non-negative, "
             f"and must beat shipped)"
    )
    return {
        "profile": p.name, "timeframe": p.timeframe, "train_frac": TRAIN_FRAC,
        "shipped_tier_active": shipped, "adopted_tier_active": adopt,
        "verdict": verdict, "candidate_summary": summary,
        "per_symbol": per_symbol_rows,
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 TIER RECALIBRATION | {res['profile']} {res['timeframe']} "
          f"train={res['train_frac']:.0%} / OOS={1-res['train_frac']:.0%} ===")
    print(f"{'tier_active':>12}{'symbols':>9}{'trades':>8}{'OOS net $':>12}{'frac>=0':>9}")
    for s in res["candidate_summary"]:
        mark = " <- shipped" if s["tier_active"] == res["shipped_tier_active"] else ""
        if s["symbols_traded"] < 3:
            mark += " (thin: no decision)"
        print(f"{s['tier_active']:>12.1f}{s['symbols_traded']:>9}{s['total_trades']:>8}"
              f"{s['oos_net_pnl_usd']:>12,.2f}{s['frac_symbols_nonneg']:>9.2f}{mark}")
    print(f"\nVERDICT: {res['verdict']}")
