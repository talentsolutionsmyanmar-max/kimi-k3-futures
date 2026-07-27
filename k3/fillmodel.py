"""K3 fill-model validation (Phase 8b) — measure maker execution before using it.

Fable5 brief (2026-07): before any maker-cost claim is used anywhere, MEASURE it.
Honest limit-fill simulation for entries at the OTE 62–79 pocket, working an
8-bar window:

  - a fill occurs only when a subsequent bar trades THROUGH the level
    (low[k] < L STRICTLY for longs — touching is not a fill);
  - every non-fill is counted in the denominator, not silently dropped;
  - for each UNFILLED signal, the market-entry forward return is computed —
    that adverse-selection measurement is the whole point.

Pre-registered checks (honored before reporting):
  * fill rate above 60% on a retracement entry means the model is wrong —
    flagged MODEL_SUSPECT, results must not be used;
  * if unfilled signals would on average have outperformed filled ones, maker
    execution is selecting for losers and the fee saving is illusory —
    flagged ADVERSE_SELECTION regardless of the fee arithmetic;
  * the same simulation on random-walk data must lose (phantom-profit check,
    same doctrine as leaktest).

Effective round-trip cost construction (stated, defensible):
  effective_rt = maker fees RT (4 bps) + opportunity cost per executed trade,
  where opportunity cost = sum of net-of-taker forward returns of MISSED
  WINNING signals (bps) divided by the number of filled trades. Missed losers
  are not a cost.

Signals are the scalp2 hard gates (sweep + displacement + context struct_state
alignment + kill zone + volatility regime) so this measures the actual Phase 5
mechanics, not a strawman. On synthetic data the context series is the base
TF's own struct_state (no network) — documented deviation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .backtest import _tradable_now
from .config import Profile
from .data import atr_percentile
from .killzones import active_zones  # noqa: F401  (parity reference)
from .leaktest import random_walk_df
from .signals import score_dataframe
from .structure import build_structure

SETUP_LOOKBACK = 6
DEAD_ATR_PCTILE = 12.0
MAKER_RT_BPS = 4.0               # 0.02% x 2
TAKER_RT_BPS = 15.0              # 0.075% x 2
FILL_RATE_SUSPECT = 0.60
MAJORS5 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def _setups(df: pd.DataFrame, p: Profile, ctx: np.ndarray) -> List[Dict[str, Any]]:
    """Same hard gates as scalp2 (documented parity), returned as a list."""
    out: List[Dict[str, Any]] = []
    o = df["open"].values; c = df["close"].values
    sweep_lo = df["sweep_low"].values; sweep_hi = df["sweep_high"].values
    disp = df["displacement"].values
    ih = df["impulse_high"].values; il = df["impulse_low"].values
    atr = df["atr"].values
    atr_pct = atr_percentile(df, p.risk.atr_period, p.atr_pctile_window).values
    dts = pd.to_datetime(df["timestamp"], utc=True).values
    for i in range(80, len(df) - 1):
        if atr_pct[i] < DEAD_ATR_PCTILE or not _tradable_now(dts[i]):
            continue
        lb = slice(max(0, i - SETUP_LOOKBACK + 1), i + 1)
        bull = c[i] > o[i]
        for side in (1, -1):
            swept = bool(sweep_lo[lb].any()) if side == 1 else bool(sweep_hi[lb].any())
            disp_ok = bool(disp[lb].any()) and (bull if side == 1 else not bull)
            ctx_ok = (ctx[i] > 0) if side == 1 else (ctx[i] < 0)
            if not (swept and disp_ok and ctx_ok):
                continue
            rng_ = ih[i] - il[i]
            if not np.isfinite(rng_) or rng_ <= 0:
                continue
            out.append({"bar": i, "side": side, "ih": float(ih[i]), "il": float(il[i]),
                        "atr": float(atr[i]) if atr[i] > 0 else float(c[i] * 0.002)})
            break
    return out


def simulate(symbol: str, p: Profile, limit: int = 1500, ote_level: float = 0.705,
             window: int = 8, horizon: int = 24,
             df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    if df is None:
        df = data.klines(sym, p.timeframe, limit)
        synthetic = False
    else:
        synthetic = True
    if len(df) < 300:
        return {"symbol": sym, "error": f"insufficient bars ({len(df)})"}
    df = score_dataframe(build_structure(df, p), p)
    if synthetic:
        ctx = df["struct_state"].astype(float).values      # documented: no network on synthetic
    else:
        from .scalp2 import _context_struct_state
        ctx = _context_struct_state(df, p, sym).values

    c = df["close"].values; l = df["low"].values; h = df["high"].values
    setups = _setups(df, p, ctx)
    rows: List[Dict[str, Any]] = []
    for s in setups:
        i, side = s["bar"], s["side"]
        if side == 1:
            L = s["ih"] - (s["ih"] - s["il"]) * ote_level
        else:
            L = s["il"] + (s["ih"] - s["il"]) * ote_level
        # the limit must sit beyond current price (retracement entry)
        if (side == 1 and L >= c[i]) or (side == -1 and L <= c[i]):
            continue
        filled_at: Optional[int] = None
        for k in range(i + 1, min(i + 1 + window, len(df))):
            through = (l[k] < L) if side == 1 else (h[k] > L)   # STRICT — touching is not a fill
            if through:
                filled_at = k
                break
        if filled_at is not None:
            end = min(filled_at + horizon, len(df) - 1)
            ret_bps = side * (c[end] / L - 1.0) * 1e4
            rows.append({"bar": i, "side": side, "filled": True, "fill_bar": filled_at,
                         "ret_bps": float(ret_bps)})
        else:
            end = min(i + horizon, len(df) - 1)
            ret_bps = side * (c[end] / c[i] - 1.0) * 1e4       # hypothetical market entry
            rows.append({"bar": i, "side": side, "filled": False, "fill_bar": None,
                         "ret_bps": float(ret_bps)})
    if not rows:
        return {"symbol": sym, "setups": 0, "note": "no setups — gates very selective"}

    filled = [r for r in rows if r["filled"]]
    unfilled = [r for r in rows if not r["filled"]]
    fill_rate = len(filled) / len(rows)
    mean_f = float(np.mean([r["ret_bps"] for r in filled])) if filled else None
    mean_u = float(np.mean([r["ret_bps"] for r in unfilled])) if unfilled else None
    adverse_delta = (mean_u - mean_f) if (mean_f is not None and mean_u is not None) else None

    # missed winners: unfilled signals that would have earned net of taker costs
    missed_win_bps = sum(r["ret_bps"] - TAKER_RT_BPS for r in unfilled
                         if r["ret_bps"] - TAKER_RT_BPS > 0)
    opp_cost_per_fill = missed_win_bps / len(filled) if filled else None
    effective_rt = MAKER_RT_BPS + (opp_cost_per_fill or 0.0)

    # per-signal strategy economics (bps per SIGNAL, unfilled = 0 position)
    maker_per_signal = float(np.mean([r["ret_bps"] - MAKER_RT_BPS if r["filled"] else 0.0
                                      for r in rows]))
    market_per_signal = float(np.mean([r["ret_bps"] - TAKER_RT_BPS for r in rows]))

    checks = {
        "fill_rate_suspect": bool(fill_rate > FILL_RATE_SUSPECT),
        "adverse_selection": bool(adverse_delta is not None and adverse_delta > 0),
    }
    verdict_parts = []
    if checks["fill_rate_suspect"]:
        verdict_parts.append("MODEL_SUSPECT (fill rate > 60% — fix before using)")
    if checks["adverse_selection"]:
        verdict_parts.append("ADVERSE_SELECTION (unfilled signals outperform filled — "
                             "maker fee saving is illusory)")
    if not verdict_parts:
        verdict_parts.append("fill model passes pre-registered checks")
    return {
        "symbol": sym, "setups": len(rows), "filled": len(filled),
        "fill_rate": round(fill_rate, 3),
        "mean_ret_filled_bps": round(mean_f, 1) if mean_f is not None else None,
        "mean_ret_unfilled_market_bps": round(mean_u, 1) if mean_u is not None else None,
        "adverse_selection_delta_bps": round(adverse_delta, 1) if adverse_delta is not None else None,
        "opp_cost_per_filled_trade_bps": round(opp_cost_per_fill, 1) if opp_cost_per_fill is not None else None,
        "effective_maker_rt_bps": round(effective_rt, 1),
        "maker_strategy_bps_per_signal": round(maker_per_signal, 2),
        "market_strategy_bps_per_signal": round(market_per_signal, 2),
        "checks": checks, "verdict": "; ".join(verdict_parts),
        "params": {"ote_level": ote_level, "window": window, "horizon": horizon},
    }


def leak_check(p: Profile, seeds: int = 8, bars: int = 1200, ote_level: float = 0.705,
               window: int = 8, horizon: int = 24) -> Dict[str, Any]:
    """Phantom-profit check: the fill model on random walks must lose per signal."""
    tf_min = 15 if p.timeframe == "15m" else 5
    per: List[Dict[str, Any]] = []
    for seed in range(seeds):
        df = random_walk_df(seed, bars, tf_min)
        res = simulate(f"RW{seed}", p, df=df, ote_level=ote_level, window=window, horizon=horizon)
        per.append({"seed": seed, "setups": res.get("setups", 0),
                    "fill_rate": res.get("fill_rate"),
                    "maker_bps_per_signal": res.get("maker_strategy_bps_per_signal")})
    vals = [x["maker_bps_per_signal"] for x in per if x["maker_bps_per_signal"] is not None]
    total = float(np.sum(vals)) if vals else 0.0
    passed = total < 0
    return {
        "seeds": seeds, "runs": per, "sum_maker_bps_per_signal": round(total, 2),
        "passed": passed,
        "verdict": ("PASS — fill model loses on random walks (cost drag only)"
                    if passed else
                    "FAIL — fill model prints on random walks; phantom fills suspected"),
    }


def run(symbols: List[str], p: Profile, limit: int = 1500, ote_level: float = 0.705,
        window: int = 8, horizon: int = 24, seeds: int = 8) -> Dict[str, Any]:
    per_symbol = [simulate(s, p, limit=limit, ote_level=ote_level,
                           window=window, horizon=horizon) for s in symbols]
    ok = [r for r in per_symbol if r.get("setups", 0) > 0]
    agg: Dict[str, Any] = {}
    if ok:
        tot = sum(r["setups"] for r in ok)
        fills = sum(r["filled"] for r in ok)
        agg = {
            "setups": tot, "filled": fills, "fill_rate": round(fills / tot, 3),
            "mean_ret_filled_bps": round(float(np.average(
                [r["mean_ret_filled_bps"] for r in ok if r["mean_ret_filled_bps"] is not None],
                weights=[r["filled"] for r in ok if r["mean_ret_filled_bps"] is not None])), 1)
            if any(r["mean_ret_filled_bps"] is not None for r in ok) else None,
            "mean_ret_unfilled_market_bps": round(float(np.average(
                [r["mean_ret_unfilled_market_bps"] for r in ok if r["mean_ret_unfilled_market_bps"] is not None],
                weights=[r["setups"] - r["filled"] for r in ok if r["mean_ret_unfilled_market_bps"] is not None])), 1)
            if any(r["mean_ret_unfilled_market_bps"] is not None for r in ok) else None,
            "effective_maker_rt_bps": round(float(np.mean([r["effective_maker_rt_bps"] for r in ok])), 1),
            "maker_strategy_bps_per_signal": round(float(np.mean([r["maker_strategy_bps_per_signal"] for r in ok])), 2),
            "market_strategy_bps_per_signal": round(float(np.mean([r["market_strategy_bps_per_signal"] for r in ok])), 2),
        }
        fr = fills / tot
        mf, mu = agg["mean_ret_filled_bps"], agg["mean_ret_unfilled_market_bps"]
        agg["checks"] = {
            "fill_rate_suspect": bool(fr > FILL_RATE_SUSPECT),
            "adverse_selection": bool(mf is not None and mu is not None and mu > mf),
        }
        agg["verdict"] = ("MODEL_SUSPECT — fill rate above 60%, do not use these numbers"
                          if agg["checks"]["fill_rate_suspect"] else
                          "ADVERSE_SELECTION — unfilled signals outperform filled; maker saving illusory"
                          if agg["checks"]["adverse_selection"] else
                          "fill model passes pre-registered checks")
    leak = leak_check(p, seeds=seeds, ote_level=ote_level, window=window, horizon=horizon)
    return {"profile": p.name, "timeframe": p.timeframe,
            "params": {"ote_level": ote_level, "window": window, "horizon": horizon},
            "per_symbol": per_symbol, "aggregate": agg, "leak_check": leak}


def print_report(res: Dict[str, Any]) -> None:
    pa = res["params"]
    print(f"\n=== K3 FILL-MODEL VALIDATION | {res['profile']} {res['timeframe']} "
          f"OTE={pa['ote_level']} window={pa['window']} horizon={pa['horizon']} ===")
    print(f"{'symbol':<12}{'setups':>7}{'fill%':>7}{'filled':>8}{'unfill':>8}{'advΔ':>7}{'effRT':>7}")
    for r in res["per_symbol"]:
        if r.get("setups", 0) == 0:
            print(f"{r['symbol']:<12} {r.get('note') or r.get('error')}")
            continue
        print(f"{r['symbol']:<12}{r['setups']:>7}{r['fill_rate']*100:>6.0f} "
              f"{str(r['mean_ret_filled_bps']):>8}{str(r['mean_ret_unfilled_market_bps']):>8}"
              f"{str(r['adverse_selection_delta_bps']):>7}{str(r['effective_maker_rt_bps']):>7}")
    a = res["aggregate"]
    if a:
        print(f"\nAGGREGATE: setups={a['setups']} fill_rate={a['fill_rate']:.1%} "
              f"filled={a['mean_ret_filled_bps']}bp unfilled={a['mean_ret_unfilled_market_bps']}bp "
              f"effective_maker_rt={a['effective_maker_rt_bps']}bp")
        print(f"per-signal economics: maker={a['maker_strategy_bps_per_signal']}bp "
              f"vs market={a['market_strategy_bps_per_signal']}bp")
        print(f"VERDICT: {a['verdict']}")
    lk = res["leak_check"]
    print(f"\nfill-model leak check: sum maker bps/signal across seeds = {lk['sum_maker_bps_per_signal']} "
          f"-> {lk['verdict']}")
