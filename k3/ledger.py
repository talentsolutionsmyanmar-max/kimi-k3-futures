"""K3 exit-event ledger (Phase 7) — instrumentation, not tuning.

Fable5 brief (2026-07): this module produces MEASUREMENT ONLY. No parameter
may change as a result of it until the IC validity study returns a VALIDATED
group. Closing an adaptive loop on a -$7,056 baseline fits noise.

What it does:
  1. Drives backtest_symbol with a ledger collector — every position state
     transition (TP1/TP2/TP3/STOP/TIME_EXIT/SIGNAL_FLIP/TP_LADDER_DONE) emits
     a row with the entry snapshot (the five SEPARATED group scores, tier,
     direction, structure/HTF bias, killzone, ATR, stop distance in bps,
     funding rate/z, 24h quote volume) plus per-event R realized and causal
     MFE/MAE in R units.
  2. Publishes four analyses:
       A. MFE distribution (median / p75 / p90) vs the shipped ladder.
       B. MAE on eventual winners — are stops cutting future winners?
       C. TP1 -> TP2 -> TP3 conversion rates.
       D. Dumb baseline: the same entries with a flat 1R target, no ladder,
          no trailing, no time exit. A ladder that can't beat it is complexity
          for its own sake.
  3. The high-power edge test: MFE of ACTIVE-tier entries vs matched random
     entries (same symbol, same direction, same holding window), with a
     bootstrap null (1,000 iterations, no normality assumption).

MFE/MAE honesty constraint (stated per the brief):
  Excursions are computed from bar highs/lows forward from the entry bar only
  — never from the full frame. Intrabar path is unknown, so when a bar's
  range spans both stop and target, the conservative convention holds: the
  stop is checked first, and that bar's favorable extreme is NOT credited to
  MFE. This makes MFE slightly conservative on stop bars; it cannot become a
  look-ahead vector.

Known data limitations (stated, not hidden):
  - funding_rate / funding_z per entry bar come from Binance fundingRate
    history (8h prints, backward-filled) — covers ~30 days, older bars = null.
  - oi_delta history is not available from klines; column is null (live-only
    overlay, as in the engine).
  - quote_vol_24h is reconstructed causally as the rolling 24h sum of
    volume x close from the klines themselves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .backtest import backtest_symbol
from .config import Profile, TF_MINUTES
from .data import wilder_atr

BOOTSTRAP_ITERS = 1000
COST_ROUND_TRIP = 0.0015          # taker 0.075% x 2 (commission + slippage)


# ---------------------------------------------------------------- enrichment

def _funding_map(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-bar funding_rate and causal funding_z from 8h funding prints."""
    df = df.copy()
    df["funding_rate"] = np.nan
    df["funding_z"] = np.nan
    try:
        rows = data._get("/fundingRate", {"symbol": symbol.upper(), "limit": 200}, 15)
        if rows:
            fr = pd.DataFrame({
                "t": pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True),
                "rate": [float(r["fundingRate"]) for r in rows],
            }).sort_values("t")
            ts = df["timestamp"].astype("datetime64[ms, UTC]")
            m = pd.merge_asof(pd.DataFrame({"ts": ts}), fr, left_on="ts", right_on="t",
                              direction="backward")
            df["funding_rate"] = m["rate"].values
            # causal z-score: expanding window over past prints only
            z = []
            hist: List[float] = []
            for v in m["rate"].values:
                if np.isfinite(v):
                    hist.append(v)
                if len(hist) >= 20 and np.isfinite(v):
                    arr = np.asarray(hist[:-1])          # strictly past prints
                    sd = arr.std()
                    z.append((v - arr.mean()) / sd if sd > 0 else 0.0)
                else:
                    z.append(np.nan)
            df["funding_z"] = z
    except Exception:
        pass
    return df


def _enrich(symbol: str, p: Profile, df: pd.DataFrame) -> pd.DataFrame:
    df = _funding_map(symbol, df)
    tf_min = TF_MINUTES.get(p.timeframe, 15)
    bars_24h = max(1, (24 * 60) // tf_min)
    qv = (df["volume"].astype(float) * df["close"].astype(float))
    df["quote_vol_24h"] = qv.rolling(bars_24h, min_periods=1).sum().values
    df["oi_delta"] = np.nan                      # history not available from klines
    try:
        from .scalp2 import _context_struct_state
        df["ctx_state"] = _context_struct_state(df, p, symbol).values
    except Exception:
        df["ctx_state"] = np.nan
    return df


# ---------------------------------------------------------------- collection

def collect(symbols: List[str], p: Profile, limit: int = 1500) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    frames: Dict[str, pd.DataFrame] = {}
    results: Dict[str, Any] = {}
    for s in symbols:
        sym = s.upper().replace("/", "")
        try:
            raw = data.klines(sym, p.timeframe, limit)
            if len(raw) < 200:
                results[sym] = {"error": f"insufficient bars ({len(raw)})"}
                continue
            enriched = _enrich(sym, p, raw)
            res = backtest_symbol(sym, p, df=enriched, ledger=events)
            results[sym] = {k: v for k, v in res.items() if k != "trade_log"}
            frames[sym] = enriched
        except Exception as e:  # noqa: BLE001
            results[sym] = {"error": str(e)}
    return {"events": events, "frames": frames, "per_symbol": results}


# ------------------------------------------------------------------ analyses

def _trades(events: List[Dict[str, Any]]) -> pd.DataFrame:
    """One row per trade: the FINAL transition carries cumulative R, MFE, MAE."""
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df.sort_values(["symbol", "entry_bar", "event_bar"])
    final = df.groupby(["symbol", "entry_bar"], as_index=False).tail(1).copy()
    tps = df[df["event"].isin(["TP1", "TP2", "TP3"])]
    hit = tps.groupby(["symbol", "entry_bar"])["event"].agg(set).to_dict()
    keys = list(zip(final["symbol"], final["entry_bar"]))
    for tp in ("TP1", "TP2", "TP3"):
        final[tp.lower() + "_hit"] = [tp in hit.get(k, set()) for k in keys]
    return final


def analysis_mfe(trades: pd.DataFrame, p: Profile) -> Dict[str, Any]:
    mfe = trades["mfe_r"].dropna()
    if len(mfe) == 0:
        return {"error": "no trades"}
    q = mfe.quantile([0.5, 0.75, 0.9])
    ladder = list(p.risk.tp_r)
    return {
        "n_trades": int(len(mfe)),
        "median_r": round(float(q[0.5]), 3), "p75_r": round(float(q[0.75]), 3),
        "p90_r": round(float(q[0.9]), 3), "mean_r": round(float(mfe.mean()), 3),
        "shipped_ladder_r": ladder,
        "reading": (f"median MFE {q[0.5]:.2f}R vs ladder {ladder}: "
                    + ("TP2/TP3 sit beyond what the median trade ever reaches — decorative."
                       if q[0.5] < (ladder[1] if len(ladder) > 1 else 99)
                       else "ladder is within reach of the median trade.")),
    }


def analysis_mae_winners(trades: pd.DataFrame) -> Dict[str, Any]:
    w = trades[trades["r_realized_cum"] > 0]["mae_r"].dropna()
    if len(w) == 0:
        return {"error": "no winning trades"}
    return {
        "n_winners": int(len(w)),
        "median_mae_r": round(float(w.median()), 3),
        "p10_mae_r": round(float(w.quantile(0.1)), 3),       # deepest decile (most negative)
        "deepest_mae_r": round(float(w.min()), 3),
        "pct_winners_dipped_past_-0.8R": round(float((w <= -0.8).mean() * 100), 1),
        "pct_winners_dipped_past_-0.5R": round(float((w <= -0.5).mean() * 100), 1),
        "reading": ("winners routinely dip deep before paying — tight stops are cutting them; "
                    "the problem is entry location, not the stop."
                    if (w <= -0.8).mean() > 0.25 else
                    "most winners do not threaten the stop — stop width is not the binding issue."),
    }


def analysis_conversion(trades: pd.DataFrame) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"error": "no trades"}
    tp1 = int(trades["tp1_hit"].sum())
    tp2 = int(trades["tp2_hit"].sum())
    tp3 = int(trades["tp3_hit"].sum())
    c12 = tp2 / tp1 if tp1 else None
    c23 = tp3 / tp2 if tp2 else None
    return {
        "n_trades": n, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "conv_tp1_to_tp2": round(c12, 3) if c12 is not None else None,
        "conv_tp2_to_tp3": round(c23, 3) if c23 is not None else None,
        "reading": ("TP1->TP2 conversion below ~30% — the runner portion pays volatility for "
                    "nothing; a two-step ladder likely beats three."
                    if (c12 is not None and c12 < 0.30) else
                    "runner conversion is not in the dead zone."),
    }


def analysis_dumb_baseline(trades: pd.DataFrame, frames: Dict[str, pd.DataFrame],
                           p: Profile, actual_net_usd: Optional[float] = None) -> Dict[str, Any]:
    """Same entries, flat 1R target, no ladder / trail / time exit. Taker fees."""
    if len(trades) == 0:
        return {"error": "no trades"}
    r = p.risk
    pnls: List[float] = []
    for _, t in trades.iterrows():
        df = frames.get(t["symbol"])
        if df is None:
            continue
        h = df["high"].values; l = df["low"].values; c = df["close"].values
        atr = wilder_atr(df, r.atr_period).values
        side = 1 if t["side"] == "LONG" else -1
        entry = float(t["entry"])
        sd = float(t["stop_bps"]) / 1e4 * entry
        eb = int(t["entry_bar"])
        target, stop = entry + side * sd, entry - side * sd
        qty = (r.initial_capital * r.risk_per_trade) / sd
        fee = lambda x: abs(x) * (r.commission + r.slippage)  # noqa: E731
        exit_price = None
        for i in range(eb, len(df)):
            a = atr[i] if atr[i] > 0 else entry * 0.002
            if (side == 1 and l[i] <= stop) or (side == -1 and h[i] >= stop):
                exit_price = stop - side * 0.10 * a          # same gap convention
                break
            if (side == 1 and h[i] >= target) or (side == -1 and l[i] <= target):
                exit_price = target
                break
        if exit_price is None:
            exit_price = c[-1]
        pnls.append(side * (exit_price - entry) * qty - fee(entry * qty) - fee(exit_price * qty))
    out = {
        "n_trades": len(pnls),
        "dumb_total_usd": round(float(np.sum(pnls)), 2),
        "dumb_mean_usd": round(float(np.mean(pnls)), 2) if pnls else None,
        "note": "dumb = same entries, flat 1R target, no ladder/trail/time-exit, "
                "fixed 1% risk of initial capital, taker fees, same stop-gap convention. "
                "actual = the real backtest engine on the same bars (compounding, "
                "conviction multipliers) — sizing differs, compare directionally.",
    }
    if actual_net_usd is not None:
        out["actual_ladder_total_usd"] = round(actual_net_usd, 2)
        out["reading"] = ("the ladder LOSES to the flat 1R baseline — complexity for its own sake."
                          if out["dumb_total_usd"] > actual_net_usd else
                          "the ladder beats the flat 1R baseline on this sample.")
    return out


def analysis_conditional_mfe(trades: pd.DataFrame, frames: Dict[str, pd.DataFrame],
                             p: Profile, iters: int = BOOTSTRAP_ITERS,
                             seed: int = 11) -> Dict[str, Any]:
    """ACTIVE-entry MFE vs matched random entries — bootstrap null, no normality."""
    act = trades[trades["tier"] == "ACTIVE"].dropna(subset=["mfe_r"])
    if len(act) < 20:
        return {"error": f"too few ACTIVE trades ({len(act)})"}
    rng = np.random.default_rng(seed)
    r = p.risk
    obs_median = float(act["mfe_r"].median())
    obs_mean = float(act["mfe_r"].mean())

    # pre-build per-symbol random-entry MFE pools: (bar, atr) candidates
    pools: Dict[str, Dict[str, Any]] = {}
    for sym, df in frames.items():
        atr = wilder_atr(df, r.atr_period).values
        pools[sym] = {"h": df["high"].values, "l": df["low"].values,
                      "atr": atr, "n": len(df)}

    def random_mfe(sym: str, side: int, hold: int) -> Optional[float]:
        pl = pools.get(sym)
        if pl is None or pl["n"] < 120:
            return None
        eb = int(rng.integers(80, pl["n"] - max(2, hold) - 1))
        a = pl["atr"][eb]
        if not np.isfinite(a) or a <= 0:
            return None
        sd = r.atr_stop_mult * a
        entry = float(pl["h"][eb] + pl["l"][eb]) / 2.0      # mid of the random bar
        hh = pl["h"][eb:eb + hold + 1]; ll = pl["l"][eb:eb + hold + 1]
        mfe = float(np.max(hh - entry)) if side == 1 else float(np.max(entry - ll))
        return mfe / sd

    null_medians: List[float] = []
    rows = list(act.itertuples())
    for _ in range(iters):
        sample: List[float] = []
        for t in rows:
            side = 1 if t.side == "LONG" else -1
            hold = max(2, int(t.bars_since_entry))
            v = random_mfe(t.symbol, side, hold)
            if v is not None:
                sample.append(v)
        if sample:
            null_medians.append(float(np.median(sample)))
    if not null_medians:
        return {"error": "null construction failed"}
    null = np.asarray(null_medians)
    pct = float((null < obs_median).mean() * 100)
    return {
        "n_active": int(len(act)),
        "active_median_mfe_r": round(obs_median, 3),
        "active_mean_mfe_r": round(obs_mean, 3),
        "null_median_of_medians_r": round(float(np.median(null)), 3),
        "null_p95_r": round(float(np.quantile(null, 0.95)), 3),
        "observed_percentile_vs_null": round(pct, 1),
        "iters": iters,
        "reading": ("ACTIVE entries shift MFE right of the random-entry null (>=95th pct) — "
                    "path-level evidence the signal predicts."
                    if pct >= 95 else
                    "ACTIVE-entry MFE does NOT separate from random entries at the 95th "
                    "percentile — no path-level edge detected."),
        "caveat": ("MFE is direction-agnostic favorable excursion; separation can reflect "
                   "regime conditioning (ACTIVE fires in expansion regimes with longer "
                   "favorable runs even after ATR normalization), not directional skill. "
                   "This test does not replace the IC validity study."),
    }


# -------------------------------------------------------------------- driver

def run(symbols: List[str], p: Profile, limit: int = 1500,
        iters: int = BOOTSTRAP_ITERS) -> Dict[str, Any]:
    coll = collect(symbols, p, limit)
    events, frames = coll["events"], coll["frames"]
    trades = _trades(events)
    actual_net = float(sum(r.get("net_pnl_usd", 0.0)
                           for r in coll["per_symbol"].values() if r.get("trades", 0) > 0))
    analyses = {
        "A_mfe_distribution": analysis_mfe(trades, p) if len(trades) else {"error": "no trades"},
        "B_mae_on_winners": analysis_mae_winners(trades) if len(trades) else {"error": "no trades"},
        "C_tp_conversion": analysis_conversion(trades) if len(trades) else {"error": "no trades"},
        "D_dumb_baseline": analysis_dumb_baseline(trades, frames, p, actual_net_usd=actual_net)
        if len(trades) else {"error": "no trades"},
        "E_conditional_mfe": analysis_conditional_mfe(trades, frames, p, iters=iters)
        if len(trades) else {"error": "no trades"},
    }
    return {
        "profile": p.name, "timeframe": p.timeframe, "limit": limit,
        "n_events": len(events), "n_trades": int(len(trades)),
        "events": events, "analyses": analyses,
        "constraint": "MEASUREMENT ONLY — no parameter changes until the validity "
                      "study returns a VALIDATED group.",
    }


def print_report(res: Dict[str, Any]) -> None:
    a = res["analyses"]
    print(f"\n=== K3 EXIT-EVENT LEDGER | {res['profile']} {res['timeframe']} "
          f"trades={res['n_trades']} events={res['n_events']} ===")
    for key in ("A_mfe_distribution", "B_mae_on_winners", "C_tp_conversion",
                "D_dumb_baseline", "E_conditional_mfe"):
        blk = a[key]
        print(f"\n[{key}]")
        if "error" in blk:
            print(f"  {blk['error']}")
            continue
        for k, v in blk.items():
            if k in ("reading", "note"):
                continue
            print(f"  {k}: {v}")
        if "reading" in blk:
            print(f"  -> {blk['reading']}")
        if "note" in blk:
            print(f"  ({blk['note']})")
