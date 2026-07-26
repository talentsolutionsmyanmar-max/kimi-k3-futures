"""K3 causal test — truncation-invariance regression harness (Fable5 audit Phase 2b).

A correct, look-ahead-free signal engine must produce the SAME decision-bar
outputs whether it sees the full historical frame or only candles available at
that bar's close. Random-walk P&L asks the economic question: "does the engine
profit on noise?" This asks the stricter causal question: "did any decision use
future rows at all?"

This is a permanent regression test:
    python3 k3.py causaltest [--profile both] [--seed 7] [--bars 600]
Exit code 0 = PASS (full-frame signals match truncated signals), 1 = FAIL
(look-ahead violation found).
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .config import Profile
from .signals import score_dataframe
from .structure import build_structure


SIGNALS = [
    "k3_dir",
    "k3_score",
    "k3_tier",
    "fvg_bull",
    "fvg_bear",
    "sweep_low",
    "sweep_high",
    "bos_up",
    "bos_dn",
    "choch_up",
    "choch_dn",
    "struct_state",
    "displacement",
    "near_bull_ob",
    "near_bear_ob",
]


def synthetic_df(seed: int, bars: int = 600, tf_min: int = 15,
                 start_price: float = 100.0) -> pd.DataFrame:
    """Geometric random walk OHLCV with deterministic bar geometry."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.0015, bars)
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


def _pipeline(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    return score_dataframe(build_structure(df, p), p)


def _same(a: Any, b: Any) -> bool:
    try:
        if bool(pd.isna(a)) and bool(pd.isna(b)):
            return True
    except (TypeError, ValueError):
        pass
    return bool(a == b)


def _json_value(v: Any) -> Any:
    if pd.isna(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def causaltest(p: Profile, seed: int = 7, bars: int = 600, step: int = 4) -> Dict[str, Any]:
    tf_min = 15 if p.timeframe == "15m" else 5
    df = synthetic_df(seed, bars, tf_min)
    full = _pipeline(df, p)
    counts = {c: 0 for c in SIGNALS}
    examples: List[Dict[str, Any]] = []
    checked = 0

    for i in range(bars // 2, bars, max(1, int(step))):
        trunc = _pipeline(df.iloc[:i + 1].copy(), p)
        full_row = full.iloc[i]
        trunc_row = trunc.iloc[-1]
        checked += 1
        for col in SIGNALS:
            full_value = full_row[col]
            trunc_value = trunc_row[col]
            if _same(full_value, trunc_value):
                continue
            counts[col] += 1
            if len(examples) < 5:
                examples.append({
                    "bar": int(i),
                    "timestamp": _json_value(full_row["timestamp"]),
                    "column": col,
                    "full_frame": _json_value(full_value),
                    "truncated_at_close": _json_value(trunc_value),
                })

    total = int(sum(counts.values()))
    failed_cols = {c: n for c, n in counts.items() if n}
    passed = total == 0
    return {
        "profile": p.name, "seed": seed, "bars": bars, "step": step,
        "checked_bars": checked, "signals": SIGNALS,
        "violations": total, "violations_by_column": counts,
        "failed_columns": failed_cols, "examples": examples,
        "verdict": "PASS — full-frame signals are truncation-invariant"
        if passed else
        "FAIL — full-frame signals differ from truncate-at-close recomputation",
        "passed": passed,
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\nK3 CAUSAL TEST — {res['profile']} seed={res['seed']} "
          f"({res['bars']} bars, step={res['step']})")
    print(f"  checked decision bars: {res['checked_bars']}")
    print(f"  violations={res['violations']}")
    failed = res.get("failed_columns", {})
    if failed:
        print("  violations by column: " + "  ".join(f"{k}={v}" for k, v in failed.items()))
        print("  examples:")
        for ex in res["examples"]:
            print(f"    bar {ex['bar']} {ex['timestamp']} {ex['column']}: "
                  f"full={ex['full_frame']!r} truncated={ex['truncated_at_close']!r}")
    print(f"  {res['verdict']}")
