"""K3 leak test — random-walk regression harness (Fable5 audit Phase 2).

A correct, look-ahead-free backtester CANNOT profit on pure random-walk data:
there is no structure to exploit, so expected P&L is exactly the cost drag
(negative). If the engine prints money on coin flips, the "edge" is a leak.

This is a permanent regression test:
    python3 k3.py leaktest [--seeds 8] [--bars 1200]
Exit code 0 = PASS (total random-walk P&L < 0), 1 = FAIL (leak suspected).

The Fable5 audit ran this against the pre-fix engine and got 58% win rate,
+$1,578 net on 8 seeds — proof of the shift(-2) FVG look-ahead. After the
Phase 1 fixes (causal FVG + confirmation-delayed swings) this must lose.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .backtest import backtest_symbol
from .config import Profile


def random_walk_df(seed: int, bars: int = 1200, tf_min: int = 15,
                   start_price: float = 100.0) -> pd.DataFrame:
    """Geometric random walk OHLCV with realistic bar geometry."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.0015, bars)                 # ~15m crypto-scale vol
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0.0, 0.0008, bars)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(12.0, 0.4, bars)
    taker_buy = volume * rng.uniform(0.35, 0.65, bars)
    ts = pd.date_range("2026-01-01", periods=bars, freq=f"{tf_min}min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "taker_buy": taker_buy,
    })


def leaktest(p: Profile, seeds: int = 8, bars: int = 1200) -> Dict[str, Any]:
    tf_min = 15 if p.timeframe == "15m" else 5
    runs: List[Dict[str, Any]] = []
    for seed in range(seeds):
        df = random_walk_df(seed, bars, tf_min)
        res = backtest_symbol(f"RW{seed}", p, df=df)
        runs.append({
            "seed": seed,
            "trades": res.get("trades", 0),
            "win_rate": res.get("win_rate"),
            "net_pnl_usd": res.get("net_pnl_usd", 0.0),
            "profit_factor": res.get("profit_factor"),
        })
    traded = [r for r in runs if r["trades"] > 0]
    total_pnl = round(sum(r["net_pnl_usd"] for r in traded), 2)
    avg_win = round(float(np.mean([r["win_rate"] for r in traded])), 1) if traded else 0.0
    # PASS = the engine LOSES on random walks (only the cost drag remains)
    passed = total_pnl < 0
    return {
        "profile": p.name, "seeds": seeds, "bars": bars,
        "runs": runs, "total_pnl_usd": total_pnl, "avg_win_rate": avg_win,
        "profitable_seeds": sum(1 for r in traded if r["net_pnl_usd"] > 0),
        "verdict": "PASS — no exploitable phantom edge (loses cost drag as required)"
        if passed else
        "FAIL — engine profits on random walks; look-ahead or data leak still present",
        "passed": passed,
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\nK3 LEAK TEST — {res['profile']} on {res['seeds']} random walks "
          f"({res['bars']} bars each)")
    for r in res["runs"]:
        print(f"  seed {r['seed']}: trades={r['trades']:<3} win={r['win_rate']}% "
              f"pnl=${r['net_pnl_usd']:>9,.2f} PF={r['profit_factor']}")
    print(f"  TOTAL pnl=${res['total_pnl_usd']:,.2f}  avg win={res['avg_win_rate']}%  "
          f"profitable seeds={res['profitable_seeds']}/{res['seeds']}")
    print(f"  {res['verdict']}")
