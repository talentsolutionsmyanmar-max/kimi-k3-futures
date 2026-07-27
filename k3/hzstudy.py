"""K3 Phase 9 Stage 1 — 1h conditional validity study. Runs ONLY because Stage 0
returned PASS on the {1h x h=1} cell; every other timeframe/horizon is excluded
up front by standing power doctrine (see k3_hzgate_*.json).

Pre-registrations (Fable5 brief 2026-07-27), all honored:

  Grid       : {liquidity, momentum} x {all bars, killzone-restricted} x h=1
               (1h forward) x 8 symbols = 32 cells. Killzone is the ONLY
               conditioning dimension — no regime x session x group.
  Momentum   : tested RAW (g_momentum, signed) — NOT inverted. The sign of the
               relationship is reported explicitly; if 15m reversion flips to
               1h momentum that is a finding, not a weighting choice.
  IC         : non-overlapping Spearman (primary); Newey-West HAC t-stat
               (secondary); circular block-bootstrap null, 1000 iters.
  FDR        : Benjamini-Hochberg q=0.10 across the ENTIRE 32-cell grid.
  OOS        : chronological 60/40 split per cell; sign-consistency reported.
  Regimes    : DESCRIPTIVE only (trend/bear/chop IC), never enters the grid.
  Floors     : MEXC all-in 5 bps (range 4-6) — the stated venue; Binance taker
               16.5 bps reported for reference. Margin 2x: MEXC clearing bar
               = 10 bps median KZ quintile spread (8/12 bps for the range).
  Decision   : a group VALIDATES only if (i) FDR-significant in the KZ
               subsample, (ii) sign-stable OOS, (iii) median |KZ spread|
               clears the MEXC floor with 2x margin. Clearing only Binance is
               NOT validation. If nothing validates, systematic trading closes
               entirely — no further horizons, venues, or conditionings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .condvalid import _kz_mask
from .config import get_profile
from .signals import score_dataframe
from .structure import build_structure
from .validity import (SAMPLE, WARMUP, _bh_fdr, _circ_block_bootstrap_null,
                       _nw_tstat, _rank, _regimes, _spearman_np)

HORIZON = 1
TF = "1h"
BOOT_ITERS = 1000
FDR_Q = 0.10
MEXC_FLOOR_BPS = 5.0
MEXC_RANGE_BPS = (4.0, 6.0)
BINANCE_FLOOR_BPS = 16.5
MARGIN = 2.0
GROUPS = ("liquidity", "momentum")          # raw, signed — pre-registered


def _cell(scores: Dict[str, np.ndarray], fwd: np.ndarray, idx: np.ndarray,
          rng: np.random.Generator) -> List[Dict[str, Any]]:
    f = fwd[idx]
    oos_cut = idx[int(len(idx) * 0.6)]
    oos_mask = idx > oos_cut
    ranked: Dict[str, np.ndarray] = {}
    for g, s in scores.items():
        rg = _rank(s[idx]); rg -= rg.mean()
        nrm = float(np.sqrt(rg @ rg))
        ranked[g] = rg / max(nrm, 1e-12)
    nulls = _circ_block_bootstrap_null(ranked, f, 2, BOOT_ITERS, rng)
    out = []
    for g, s in scores.items():
        s_all = s[idx]
        ic = _spearman_np(s_all, f)
        ra = _rank(s_all); ra -= ra.mean(); sx = float(np.sqrt(ra @ ra))
        rb = _rank(f); rb -= rb.mean(); sy = float(np.sqrt(rb @ rb))
        nw = _nw_tstat((ra / max(sx, 1e-12)) * (rb / max(sy, 1e-12)), lag=HORIZON)
        null = nulls[g]
        pct_above = float((null >= ic).mean())
        p_boot = float(2.0 * min(pct_above, 1.0 - pct_above))
        ic_oos = (_spearman_np(s_all[oos_mask], f[oos_mask])
                  if oos_mask.sum() > 60 else None)
        try:
            q = pd.qcut(pd.Series(s_all).rank(method="first"), 5, labels=False)
            spread = float((pd.Series(f)[q == 4].mean()
                            - pd.Series(f)[q == 0].mean()) * 1e4)
        except ValueError:
            spread = None
        out.append({"group": g, "n": int(len(idx)), "ic": round(ic, 4),
                    "nw_t": round(nw, 2) if np.isfinite(nw) else None,
                    "boot_p": round(p_boot, 4),
                    "ic_oos": round(ic_oos, 4) if ic_oos is not None else None,
                    "quintile_spread_bps": round(spread, 1) if spread is not None else None})
    return out


def run(symbols: Optional[List[str]] = None, bars: int = 8000, seed: int = 23) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    symbols = [s.upper() for s in (symbols or SAMPLE)]
    day = get_profile("day")
    cells: List[Dict[str, Any]] = []
    regime_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for sym in symbols:
        try:
            df = data.klines_history(sym, TF, bars)
            if len(df) < 2000:
                errors.append({"symbol": sym, "error": f"only {len(df)} bars"})
                continue
            scored = score_dataframe(build_structure(df, day), day)
            close = scored["close"].astype(float)
            fwd = (close.shift(-HORIZON) / close - 1.0).values
            kz = _kz_mask(scored["timestamp"])
            scores = {"liquidity": scored["g_liquidity"].astype(float).values,
                      "momentum": scored["g_momentum"].astype(float).values}   # RAW
            base = np.arange(WARMUP, len(scored) - HORIZON)[::HORIZON]
            for cond, idx in (("all", base), ("kz", base[kz[base]])):
                if len(idx) < 120:
                    errors.append({"symbol": sym, "error": f"{cond} n={len(idx)} < 120"})
                    continue
                for c in _cell(scores, fwd, idx, rng):
                    cells.append({"symbol": sym, "condition": cond,
                                  "horizon_bars": HORIZON, **c})
            # --- regime breakdown, descriptive only, all-bars ---
            reg = _regimes(close).values
            for rname in ("trend", "bear", "chop"):
                ridx = base[reg[base] == rname]
                if len(ridx) < 200:
                    continue
                for g, s in scores.items():
                    regime_rows.append({"symbol": sym, "regime": rname, "group": g,
                                        "n": int(len(ridx)),
                                        "ic": round(_spearman_np(s[ridx], fwd[ridx]), 4)})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(e)})

    rejected = _bh_fdr([c["boot_p"] for c in cells], q=FDR_Q)
    for c, r in zip(cells, rejected):
        c["fdr_significant"] = bool(r)

    mexc_bar = MARGIN * MEXC_FLOOR_BPS
    verdicts: List[Dict[str, Any]] = []
    for g in GROUPS:
        kzc = [c for c in cells if c["group"] == g and c["condition"] == "kz"]
        allc = [c for c in cells if c["group"] == g and c["condition"] == "all"]
        if not kzc:
            verdicts.append({"group": g, "verdict": "NO KZ CELLS"})
            continue
        ics = [c["ic"] for c in kzc]
        mean_ic = float(np.mean(ics))
        orientation = "momentum" if mean_ic > 0 else "reversion"
        pos_frac = float(np.mean([x > 0 for x in ics]))
        sign_stable = pos_frac >= 0.6 or pos_frac <= 0.4
        fdr_hits = sum(1 for c in kzc if c["fdr_significant"])
        oos = [c for c in kzc if c["ic_oos"] is not None]
        oos_same = sum(1 for c in oos
                       if np.sign(c["ic_oos"]) == np.sign(c["ic"]) and c["ic_oos"] != 0)
        oos_ok = len(oos) > 0 and oos_same >= 0.6 * len(oos)
        spreads = [abs(c["quintile_spread_bps"]) for c in kzc if c["quintile_spread_bps"]]
        med_spread = float(np.median(spreads)) if spreads else None
        clears_mexc = med_spread is not None and med_spread >= mexc_bar
        clears_bin = (med_spread is not None
                      and med_spread >= MARGIN * BINANCE_FLOOR_BPS)
        validated = bool(fdr_hits > 0 and sign_stable and oos_ok and clears_mexc)
        verdicts.append({
            "group": g, "orientation_at_1h": orientation,
            "verdict": "VALIDATED" if validated else "NOT VALIDATED",
            "kz_mean_ic": round(mean_ic, 4),
            "all_mean_ic": round(float(np.mean([c["ic"] for c in allc])), 4) if allc else None,
            "kz_fdr_cells": f"{fdr_hits}/{len(kzc)}",
            "kz_sign_pos_frac": round(pos_frac, 2),
            "kz_oos_consistent": f"{oos_same}/{len(oos)}",
            "kz_median_abs_spread_bps": round(med_spread, 1) if med_spread is not None else None,
            "mexc_clearing_bar_bps": mexc_bar, "clears_mexc_2x": clears_mexc,
            "clears_binance_2x_reference": clears_bin,
        })

    any_valid = any(v["verdict"] == "VALIDATED" for v in verdicts)
    return {
        "kind": "k3_hzstudy", "phase": "9-stage1", "timeframe": TF,
        "horizon_bars": HORIZON, "symbols": symbols, "bars": bars,
        "grid_cells": len(cells), "fdr_q": FDR_Q, "boot_iters": BOOT_ITERS,
        "floors": {"mexc_bps": MEXC_FLOOR_BPS, "mexc_range_bps": list(MEXC_RANGE_BPS),
                   "binance_bps": BINANCE_FLOOR_BPS, "margin": MARGIN},
        "cells": cells, "regime_descriptive": regime_rows, "errors": errors,
        "verdicts": verdicts,
        "study_verdict": (
            f"{[v['group'] for v in verdicts if v['verdict'] == 'VALIDATED']} VALIDATED at 1h"
            if any_valid else
            "NOTHING VALIDATED at 1h — under the pre-registered Phase 9 rule, "
            "systematic trading closes entirely: no further horizons, venues, "
            "or conditionings will be tested."),
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 PHASE 9 STAGE 1 — 1h VALIDITY | h=1 | {res['grid_cells']} cells ===")
    print(f"floors: MEXC {res['floors']['mexc_bps']}bp x2 = "
          f"{res['floors']['mexc_bps'] * res['floors']['margin']}bp clearing bar | "
          f"Binance {res['floors']['binance_bps']}bp (reference)")
    if res["errors"]:
        print(f"symbol errors: {res['errors']}")
    print(f"\n{'group':<11}{'orient':<11}{'verdict':<15}{'kzIC':>8}{'allIC':>8}"
          f"{'FDR':>7}{'OOS':>7}{'|spread|':>9}{'MEXC?':>8}")
    for v in res["verdicts"]:
        if "kz_mean_ic" not in v:
            print(f"{v['group']:<11}{'-':<11}{v['verdict']:<15}")
            continue
        print(f"{v['group']:<11}{v['orientation_at_1h']:<11}{v['verdict']:<15}"
              f"{v['kz_mean_ic']:>8}{str(v['all_mean_ic']):>8}{v['kz_fdr_cells']:>7}"
              f"{v['kz_oos_consistent']:>7}"
              f"{(str(v['kz_median_abs_spread_bps']) + 'bp') if v['kz_median_abs_spread_bps'] else '-':>9}"
              f"{str(v['clears_mexc_2x']):>8}")
    print("\nper-cell (kz slice):")
    print(f"  {'symbol':<12}{'group':<11}{'ic':>8}{'nw_t':>7}{'p':>7}{'fdr':>5}"
          f"{'ic_oos':>8}{'spread':>8}")
    for c in res["cells"]:
        if c["condition"] != "kz":
            continue
        print(f"  {c['symbol']:<12}{c['group']:<11}{c['ic']:>8}{str(c['nw_t']):>7}"
              f"{c['boot_p']:>7}{('*' if c['fdr_significant'] else ''):>5}"
              f"{str(c['ic_oos']):>8}{str(c['quintile_spread_bps']):>8}")
    print("\nregime IC (descriptive only — not in the grid):")
    agg: Dict[str, List[float]] = {}
    for r in res["regime_descriptive"]:
        agg.setdefault(f"{r['group']}|{r['regime']}", []).append(r["ic"])
    for k, v in sorted(agg.items()):
        g, rname = k.split("|")
        print(f"  {g:<11}{rname:<7} mean IC {np.mean(v):+.4f} over {len(v)} symbols")
    print(f"\nSTUDY VERDICT: {res['study_verdict']}")
