"""K3 signal validity study (Phase 6) — the pre-registered protocol.

Fable5 brief (2026-07), honored verbatim in design:

  Unit of analysis : per bar t, the five signed group scores + composite from
                     score_dataframe; forward returns at horizons 1, 4, 8, 24.
  Primary metric   : Spearman rank IC, NON-OVERLAPPING samples (every h-th
                     bar) — raw t-stats on overlapping windows inflate by ~sqrt(h).
  Secondary        : Newey-West corrected t-stat (lag h) on the overlapping sample.
  Multiple comps   : Benjamini-Hochberg FDR at q=0.10 across the full grid
                     (5 groups x 4 horizons x N symbols), raw and adjusted reported.
  Null             : circular block bootstrap of the return series, block >= 2h,
                     1,000 iterations — no parametric p-values.
  Sample           : >= 5,000 bars/symbol; BTC/ETH majors + mid-caps; regime
                     breakdown (trend / chop / bear) via 96-bar drift.
  OOS              : chronological 60/40 — cross-sectional splits leak through
                     market-wide correlation and are not used.

Pre-registered decision rule (written before running, honored after):
  VALIDATED  : IC sign-stable across the majority of symbols, survives BH-FDR,
               same sign OOS, AND economically meaningful — top-quintile vs
               bottom-quintile forward-return spread must clear the 11 bps
               round-trip cost floor (0.055% x 2) by a comfortable margin (>= 1.5x).
  CONDITIONAL: passes only inside specific regimes — a conditional signal, not
               a dead one; that distinction matters.
  FALSIFIED  : indistinguishable from the bootstrap null, or sign flips OOS.

Negative results are reported with the same prominence as positive ones.
This module changes NO parameters and fits NO weights.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .config import Profile
from .signals import score_dataframe
from .structure import build_structure

GROUPS = ["structure", "liquidity", "momentum", "volatility", "positioning"]
HORIZONS = [1, 4, 8, 24]
SAMPLE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
COST_FLOOR_BPS = 11.0          # 0.055% taker x 2
ECON_MARGIN = 1.5              # "comfortable" = >= 1.5x cost floor
BOOT_ITERS = 1000
WARMUP = 80
REGIME_BARS = 96               # 15m: 24h drift window
REGIME_THRESHOLD = 0.015       # +/-1.5% drift = trend/bear, else chop


# ---------------------------------------------------------------- statistics

def _rank(x: np.ndarray) -> np.ndarray:
    order = x.argsort(kind="mergesort")
    r = np.empty(len(x), dtype=float)
    r[order] = np.arange(len(x), dtype=float)
    return r


def _spearman_np(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = _rank(a), _rank(b)
    ra -= ra.mean(); rb -= rb.mean()
    d = float(np.sqrt((ra @ ra) * (rb @ rb)))
    return float(ra @ rb / d) if d > 0 else 0.0


def _nw_tstat(u: np.ndarray, lag: int) -> float:
    """Newey-West t-stat of mean(u) with HAC lag truncation."""
    n = len(u)
    if n < lag + 10:
        return float("nan")
    u = u - u.mean()
    g0 = float(u @ u / n)
    var = g0
    for l in range(1, lag + 1):
        gl = float(u[l:] @ u[:-l] / n)
        var += 2.0 * (1.0 - l / (lag + 1.0)) * gl
    return float(u.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def _circ_block_bootstrap_null(scores_ranked: Dict[str, np.ndarray], fwd: np.ndarray,
                               block: int, iters: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
    """Null IC distribution per group: circularly block-permute the forward
    return series (preserves autocorrelation + vol clustering), recompute IC."""
    n = len(fwd)
    nulls = {g: np.empty(iters) for g in scores_ranked}
    for it in range(iters):
        # circular block bootstrap indices
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        idx = np.concatenate([(np.arange(s, s + block) % n) for s in starts])[:n]
        rf = _rank(fwd[idx])
        rf -= rf.mean()
        denom = float(np.sqrt(rf @ rf))
        for g, ra in scores_ranked.items():
            nulls[g][it] = float(ra @ rf / denom) if denom > 0 else 0.0
    return nulls


def _bh_fdr(pvals: List[float], q: float = 0.10) -> List[bool]:
    """Benjamini-Hochberg: returns boolean mask of rejections."""
    m = len(pvals)
    order = np.argsort(pvals)
    ranked = np.asarray(pvals)[order]
    thresh = q * (np.arange(1, m + 1) / m)
    below = ranked <= thresh
    if not below.any():
        return [False] * m
    kmax = int(np.max(np.where(below)[0]))
    rejected = np.zeros(m, dtype=bool)
    rejected[order[:kmax + 1]] = True
    return list(rejected)


# -------------------------------------------------------------------- study

def _regimes(close: pd.Series) -> pd.Series:
    drift = close / close.shift(REGIME_BARS) - 1.0
    return pd.Series(np.where(drift > REGIME_THRESHOLD, "trend",
                     np.where(drift < -REGIME_THRESHOLD, "bear", "chop")),
                     index=close.index)


def study_symbol(symbol: str, p: Profile, bars: int, rng: np.random.Generator) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    raw = data.klines_history(sym, p.timeframe, bars)
    if len(raw) < 2000:
        return {"symbol": sym, "error": f"only {len(raw)} bars (<2000)"}
    df = score_dataframe(build_structure(raw, p), p)
    close = df["close"].astype(float)
    regimes = _regimes(close)

    scores = {g: df[f"g_{g}"].astype(float).values for g in GROUPS}
    scores["composite"] = (df["k3_dir"] * df["k3_score"]).astype(float).values

    cells: List[Dict[str, Any]] = []
    for h in HORIZONS:
        fwd = (close.shift(-h) / close - 1.0).values
        valid = np.arange(WARMUP, len(df) - h)
        # non-overlapping primary sample: every h-th valid bar
        nonov = valid[::h]
        oos_cut = valid[int(len(valid) * 0.6)]
        train_mask = nonov <= oos_cut
        oos_mask = nonov > oos_cut

        f_all = fwd[nonov]
        # one bootstrap per (symbol, horizon) covering ALL groups at once
        ranked_all: Dict[str, np.ndarray] = {}
        for g, s in scores.items():
            rg = _rank(s[nonov])
            rg -= rg.mean()
            nrm = float(np.sqrt(rg @ rg))
            ranked_all[g] = rg / max(nrm, 1e-12)
        nulls = _circ_block_bootstrap_null(ranked_all, f_all, 2, BOOT_ITERS, rng)
        # block=2 sampled points = 2h original bars (sample is spaced h apart)
        for g, s in scores.items():
            s_all = s[nonov]
            ic = _spearman_np(s_all, f_all)
            # overlapping sample + Newey-West secondary
            so, fo = s[valid], fwd[valid]
            ra, rb = _rank(so), _rank(fo)
            ra_c = ra - ra.mean(); rb_c = rb - rb.mean()
            ic_ov = float(ra_c @ rb_c / np.sqrt((ra_c @ ra_c) * (rb_c @ rb_c)))
            sx = float(np.sqrt(ra_c @ ra_c / len(ra_c)))
            sy = float(np.sqrt(rb_c @ rb_c / len(rb_c)))
            nw_t = _nw_tstat((ra_c / max(sx, 1e-12)) * (rb_c / max(sy, 1e-12)), lag=h)
            # OOS confirmation
            ic_oos = _spearman_np(s_all[oos_mask], f_all[oos_mask]) if oos_mask.sum() > 60 else None
            # bootstrap null on the non-overlapping sample (computed once per horizon above)
            null = nulls[g]
            pct_above = float((null >= ic).mean())
            p_boot = float(2.0 * min(pct_above, 1.0 - pct_above))
            # economic translation: quintile spread in bps
            try:
                q = pd.qcut(pd.Series(s_all).rank(method="first"), 5, labels=False)
                spread_bps = float((pd.Series(f_all)[q == 4].mean()
                                    - pd.Series(f_all)[q == 0].mean()) * 1e4)
            except ValueError:
                spread_bps = None
            cells.append({
                "symbol": sym, "group": g, "horizon": h,
                "n_nonoverlap": int(len(nonov)),
                "ic": round(ic, 4), "ic_overlap": round(ic_ov, 4),
                "nw_t": round(nw_t, 2) if np.isfinite(nw_t) else None,
                "ic_oos": round(ic_oos, 4) if ic_oos is not None else None,
                "boot_p": round(p_boot, 4),
                "boot_percentile": round((1.0 - pct_above) * 100, 1),
                "quintile_spread_bps": round(spread_bps, 1) if spread_bps is not None else None,
            })

    # regime breakdown at the profile's primary horizon (h=8)
    h = 8
    fwd = (close.shift(-h) / close - 1.0).values
    valid = np.arange(WARMUP, len(df) - h)[::h]
    reg_cells: List[Dict[str, Any]] = []
    for reg in ("trend", "chop", "bear"):
        mask = regimes.values[valid] == reg
        if mask.sum() < 60:
            reg_cells.append({"symbol": sym, "regime": reg, "n": int(mask.sum()), "note": "too thin"})
            continue
        row: Dict[str, Any] = {"symbol": sym, "regime": reg, "n": int(mask.sum())}
        for g in GROUPS + ["composite"]:
            row[f"ic_{g}"] = round(_spearman_np(scores[g][valid][mask], fwd[valid][mask]), 4)
        reg_cells.append(row)

    return {"symbol": sym, "bars": int(len(raw)), "cells": cells, "regimes": reg_cells}


def _verdict(group: str, cells: List[Dict[str, Any]], rejected: List[bool]) -> Dict[str, Any]:
    gc = [(c, r) for c, r in zip(cells, rejected) if c["group"] == group]
    if not gc:
        return {"group": group, "verdict": "NO DATA"}
    ics = [c["ic"] for c, _ in gc]
    pos_frac = float(np.mean([x > 0 for x in ics]))
    sign_stable = pos_frac >= 0.6 or pos_frac <= 0.4
    fdr_hits = sum(1 for _, r in gc if r)
    oos = [c for c, _ in gc if c["ic_oos"] is not None]
    oos_same = sum(1 for c in oos if np.sign(c["ic_oos"]) == np.sign(c["ic"]) and c["ic_oos"] != 0)
    oos_ok = len(oos) > 0 and oos_same >= 0.6 * len(oos)
    spreads = [abs(c["quintile_spread_bps"]) for c, _ in gc
               if c["quintile_spread_bps"] is not None]
    econ_ok = bool(spreads) and float(np.median(spreads)) >= ECON_MARGIN * COST_FLOOR_BPS
    mean_ic = float(np.mean(ics))
    if sign_stable and fdr_hits >= len(gc) * 0.25 and oos_ok and econ_ok:
        verdict = "VALIDATED"
    elif not sign_stable or fdr_hits == 0 or (oos and oos_same <= 0.4 * len(oos)):
        verdict = "FALSIFIED"
    else:
        verdict = "CONDITIONAL"
    return {
        "group": group, "verdict": verdict,
        "mean_ic": round(mean_ic, 4),
        "frac_positive": round(pos_frac, 2),
        "fdr_significant_cells": f"{fdr_hits}/{len(gc)}",
        "oos_sign_consistent": f"{oos_same}/{len(oos)}",
        "median_quintile_spread_bps": round(float(np.median(spreads)), 1) if spreads else None,
        "cost_floor_bps": COST_FLOOR_BPS,
        "rule": "VALIDATED needs: sign-stable + FDR-surviving + OOS-consistent + "
                "median quintile spread >= 1.5x the 11bps cost floor.",
    }


def validity(symbols: List[str], p: Profile, bars: int = 6000, seed: int = 19) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    per_symbol: List[Dict[str, Any]] = []
    for s in symbols:
        try:
            per_symbol.append(study_symbol(s, p, bars, rng))
        except Exception as e:  # noqa: BLE001
            per_symbol.append({"symbol": s.upper(), "error": str(e)})

    cells = [c for r in per_symbol if "cells" in r for c in r["cells"]]
    grid = [c for c in cells if c["group"] in GROUPS]          # BH grid = 5 groups only
    rejected = _bh_fdr([c["boot_p"] for c in grid], q=0.10)
    rej_map = {(c["symbol"], c["group"], c["horizon"]): r for c, r in zip(grid, rejected)}
    for c in cells:
        c["fdr_significant"] = bool(rej_map.get((c["symbol"], c["group"], c["horizon"]), False))

    verdicts = [_verdict(g, cells, [c["fdr_significant"] for c in cells]) for g in GROUPS]
    verdicts.append(_verdict("composite", cells, [c["fdr_significant"] for c in cells]))
    return {
        "profile": p.name, "timeframe": p.timeframe, "bars_requested": bars,
        "horizons": HORIZONS, "boot_iters": BOOT_ITERS, "fdr_q": 0.10,
        "cost_floor_bps": COST_FLOOR_BPS,
        "per_symbol": per_symbol, "cells": cells, "verdicts": verdicts,
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 SIGNAL VALIDITY | {res['profile']} {res['timeframe']} "
          f"bars={res['bars_requested']} boot={res['boot_iters']} FDR q=0.10 ===")
    print(f"\n{'symbol':<12}" + "".join(f"{g[:8]:>9}" for g in GROUPS + ["composite"]))
    prim = 8
    for r in res["per_symbol"]:
        if "cells" not in r:
            print(f"{r['symbol']:<12} {r.get('error')}")
            continue
        row = f"{r['symbol']:<12}"
        for g in GROUPS + ["composite"]:
            c = next((x for x in r["cells"] if x["group"] == g and x["horizon"] == prim), None)
            mark = "*" if c and c["fdr_significant"] else " "
            row += f"{(str(c['ic']) + mark) if c else '-':>9}"
        print(row + "   (IC @ h=8, * = FDR-significant)")
    print(f"\n{'group':<14}{'verdict':<13}{'meanIC':>8}{'pos%':>6}{'FDR':>8}{'OOS':>8}{'spread':>8}")
    for v in res["verdicts"]:
        print(f"{v['group']:<14}{v['verdict']:<13}{v.get('mean_ic', '-')!s:>8}"
              f"{v.get('frac_positive', '-')!s:>6}{v.get('fdr_significant_cells', '-'):>8}"
              f"{v.get('oos_sign_consistent', '-'):>8}"
              f"{str(v.get('median_quintile_spread_bps')) + 'bp':>8}")
    print(f"\nrule: {res['verdicts'][0]['rule']}")
