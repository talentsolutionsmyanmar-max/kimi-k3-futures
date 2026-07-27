"""K3 combined conditional validity (Phase 8c) — one pass, pre-registered.

Fable5 brief (2026-07), honored in full:

  Grid       : {liquidity, momentum-inverted} x {all bars, killzone-restricted}
               x horizons {1,4,8,24} x symbols. Killzone is the ONE registered
               structural hypothesis — no other conditioning dimension is tested.
  FDR        : Benjamini-Hochberg q=0.10 across the ENTIRE expanded grid
               (killzone cells included) — not per-slice, so conditioning
               cannot buy significance for free.
  Power check: computed BEFORE running, per profile x horizon on the killzone
               subsample. Detectable IC at 80% power ~= 2.8/sqrt(n-1). The
               economically-required IC is derived from the measured
               spread-per-IC ratio of the SAME run's all-bars slice
               (construction stated here, pre-registered by code, not by eye).
               Underpowered horizons are excluded up front and reported —
               if ALL are underpowered the profile is not run.
  Floors     : taker 16.5 bps (11 bps RT x 1.5 margin, Phase 6 convention);
               maker = 1.5 x the Phase 8b validated effective maker RT.
               SCALP's maker model FAILED 8b (adverse selection + leak), so no
               maker floor exists for SCALP — taker only, by construction.
  Decision   : a group is CONDITIONAL-VALIDATED only if its killzone cells are
               FDR-significant, sign-stable, OOS-consistent, AND the median
               killzone quintile spread clears a validated floor with margin.
               Breakeven is not validation. One shot.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .config import Profile
from .killzones import ZONES
from .signals import score_dataframe
from .structure import build_structure
from .validity import (HORIZONS, SAMPLE, WARMUP, _bh_fdr,
                       _circ_block_bootstrap_null, _rank, _spearman_np)

STUDY_GROUPS = {"liquidity": "liquidity", "momentum_inv": "momentum"}
TAKER_FLOOR_BPS = 16.5
MAKER_MARGIN = 1.5
BOOT_ITERS = 1000
FDR_Q = 0.10


def _kz_mask(ts: pd.Series) -> np.ndarray:
    """True on bars inside a NON-caution kill zone (vectorized by minute-of-day)."""
    mins = (ts.dt.hour * 60 + ts.dt.minute).values
    mask = np.zeros(len(ts), dtype=bool)
    for z in ZONES:
        if z["caution"]:
            continue
        s = z["start"][0] * 60 + z["start"][1]
        e = z["end"][0] * 60 + z["end"][1]
        mask |= (mins >= s) & (mins <= e) if s <= e else (mins >= s) | (mins <= e)
    return mask


def _detectable_ic(n: int) -> float:
    """Min |IC| detectable at 80% power, alpha=0.05 two-sided (normal approx)."""
    return float(2.802 / np.sqrt(max(n - 1, 10)))


def study_profile(symbols: List[str], p: Profile, bars: int = 6000,
                  maker_rt_bps: Optional[float] = None, seed: int = 23) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    maker_floor = maker_rt_bps * MAKER_MARGIN if maker_rt_bps else None
    cells: List[Dict[str, Any]] = []
    power_rows: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    for sym_in in symbols:
        sym = sym_in.upper().replace("/", "")
        try:
            raw = data.klines_history(sym, p.timeframe, bars)
            if len(raw) < 2000:
                power_rows.append({"symbol": sym, "error": f"only {len(raw)} bars"})
                continue
            df = score_dataframe(build_structure(raw, p), p)
            close = df["close"].astype(float)
            kz = _kz_mask(df["timestamp"])
            scores = {"liquidity": df["g_liquidity"].astype(float).values,
                      "momentum_inv": (-df["g_momentum"].astype(float)).values}

            for h in HORIZONS:
                fwd = (close.shift(-h) / close - 1.0).values
                base_idx = np.arange(WARMUP, len(df) - h)[::h]
                cond_idx = {"all": base_idx, "kz": base_idx[kz[base_idx]]}
                # ---- power check on the KZ slice BEFORE any IC is computed ----
                n_kz = int(len(cond_idx["kz"]))
                det = _detectable_ic(n_kz)
                power_rows.append({"symbol": sym, "horizon": h, "n_kz_nonoverlap": n_kz,
                                   "detectable_ic_80pct": round(det, 4)})
                for cond, idx in cond_idx.items():
                    if len(idx) < 120:
                        excluded.append({"symbol": sym, "horizon": h, "condition": cond,
                                         "reason": f"n={len(idx)} < 120"})
                        continue
                    f_all = fwd[idx]
                    oos_cut = idx[int(len(idx) * 0.6)]
                    oos_mask = idx > oos_cut
                    ranked_all: Dict[str, np.ndarray] = {}
                    for g, s in scores.items():
                        rg = _rank(s[idx]); rg -= rg.mean()
                        nrm = float(np.sqrt(rg @ rg))
                        ranked_all[g] = rg / max(nrm, 1e-12)
                    nulls = _circ_block_bootstrap_null(ranked_all, f_all, 2, BOOT_ITERS, rng)
                    for g, s in scores.items():
                        s_all = s[idx]
                        ic = _spearman_np(s_all, f_all)
                        null = nulls[g]
                        pct_above = float((null >= ic).mean())
                        p_boot = float(2.0 * min(pct_above, 1.0 - pct_above))
                        ic_oos = (_spearman_np(s_all[oos_mask], f_all[oos_mask])
                                  if oos_mask.sum() > 60 else None)
                        try:
                            q = pd.qcut(pd.Series(s_all).rank(method="first"), 5, labels=False)
                            spread = float((pd.Series(f_all)[q == 4].mean()
                                            - pd.Series(f_all)[q == 0].mean()) * 1e4)
                        except ValueError:
                            spread = None
                        cells.append({
                            "symbol": sym, "group": g, "horizon": h, "condition": cond,
                            "n": int(len(idx)), "ic": round(ic, 4),
                            "ic_oos": round(ic_oos, 4) if ic_oos is not None else None,
                            "boot_p": round(p_boot, 4),
                            "quintile_spread_bps": round(spread, 1) if spread is not None else None,
                        })
        except Exception as e:  # noqa: BLE001
            power_rows.append({"symbol": sym, "error": str(e)})

    # ---- economically-required IC per group, from the all-bars slice of THIS run ----
    req_ic: Dict[str, Optional[float]] = {}
    for g in STUDY_GROUPS:
        gcells = [c for c in cells if c["group"] == g and c["condition"] == "all"
                  and c["quintile_spread_bps"] and abs(c["ic"]) > 1e-9]
        ratios = [abs(c["quintile_spread_bps"]) / abs(c["ic"]) for c in gcells]
        k = float(np.median(ratios)) if ratios else None
        req_ic[g] = (TAKER_FLOOR_BPS / k) if k else None

    # ---- power verdict per horizon (KZ slice, median across symbols) ----
    power_summary: List[Dict[str, Any]] = []
    powered_horizons: List[int] = []
    for h in HORIZONS:
        dets = [r["detectable_ic_80pct"] for r in power_rows
                if r.get("horizon") == h and "detectable_ic_80pct" in r]
        det = float(np.median(dets)) if dets else None
        req = max([v for v in req_ic.values() if v is not None], default=None)
        ok = bool(det is not None and req is not None and det <= req)
        power_summary.append({"horizon": h, "median_detectable_ic": round(det, 4) if det else None,
                              "required_ic_max": round(req, 4) if req else None,
                              "powered": ok})
        if ok:
            powered_horizons.append(h)

    if not powered_horizons:
        return {"profile": p.name, "timeframe": p.timeframe, "ran": False,
                "power_summary": power_summary, "power_rows": power_rows,
                "verdict": "NOT RUN — killzone subsample cannot detect an economically "
                           "meaningful IC at any horizon (standing power doctrine)."}

    grid = [c for c in cells if c["horizon"] in powered_horizons]
    rejected = _bh_fdr([c["boot_p"] for c in grid], q=FDR_Q)
    for c, r in zip(grid, rejected):
        c["fdr_significant"] = bool(r)

    verdicts: List[Dict[str, Any]] = []
    for g in STUDY_GROUPS:
        kz_cells = [c for c in grid if c["group"] == g and c["condition"] == "kz"]
        all_cells = [c for c in grid if c["group"] == g and c["condition"] == "all"]
        if not kz_cells:
            verdicts.append({"group": g, "verdict": "NO KZ CELLS"})
            continue
        ics = [c["ic"] for c in kz_cells]
        pos_frac = float(np.mean([x > 0 for x in ics]))
        sign_stable = pos_frac >= 0.6 or pos_frac <= 0.4
        fdr_hits = sum(1 for c in kz_cells if c["fdr_significant"])
        oos = [c for c in kz_cells if c["ic_oos"] is not None]
        oos_same = sum(1 for c in oos if np.sign(c["ic_oos"]) == np.sign(c["ic"]) and c["ic_oos"] != 0)
        oos_ok = len(oos) > 0 and oos_same >= 0.6 * len(oos)
        spreads = [abs(c["quintile_spread_bps"]) for c in kz_cells if c["quintile_spread_bps"]]
        med_spread = float(np.median(spreads)) if spreads else None
        clears_taker = med_spread is not None and med_spread >= TAKER_FLOOR_BPS
        clears_maker = (med_spread is not None and maker_floor is not None
                        and med_spread >= maker_floor)
        validated = bool(fdr_hits > 0 and sign_stable and oos_ok and (clears_taker or clears_maker))
        verdicts.append({
            "group": g,
            "verdict": "CONDITIONAL-VALIDATED" if validated else "NOT VALIDATED",
            "kz_mean_ic": round(float(np.mean(ics)), 4),
            "all_mean_ic": round(float(np.mean([c['ic'] for c in all_cells])), 4) if all_cells else None,
            "kz_fdr_cells": f"{fdr_hits}/{len(kz_cells)}",
            "kz_sign_pos_frac": round(pos_frac, 2),
            "kz_oos_consistent": f"{oos_same}/{len(oos)}",
            "kz_median_spread_bps": round(med_spread, 1) if med_spread is not None else None,
            "taker_floor_bps": TAKER_FLOOR_BPS, "clears_taker": clears_taker,
            "maker_floor_bps": round(maker_floor, 1) if maker_floor else None,
            "clears_maker": clears_maker,
        })
    any_valid = any(v["verdict"] == "CONDITIONAL-VALIDATED" for v in verdicts)
    return {
        "profile": p.name, "timeframe": p.timeframe, "ran": True,
        "powered_horizons": powered_horizons, "power_summary": power_summary,
        "required_ic_by_group": {k: (round(v, 4) if v else None) for k, v in req_ic.items()},
        "maker_floor_bps": round(maker_floor, 1) if maker_floor else None,
        "taker_floor_bps": TAKER_FLOOR_BPS,
        "excluded": excluded, "cells": grid, "verdicts": verdicts,
        "study_verdict": ("at least one group CONDITIONAL-VALIDATED" if any_valid else
                          "NO GROUP CONDITIONAL-VALIDATED — K3 systematic track closes "
                          "under this protocol"),
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 CONDITIONAL VALIDITY (Phase 8c) | {res['profile']} {res['timeframe']} ===")
    print("power check (KZ slice, median across symbols):")
    for r in res.get("power_summary", []):
        print(f"  h={r['horizon']:<3} detectable_IC={r['median_detectable_ic']} "
              f"required<={r['required_ic_max']}  -> {'POWERED' if r['powered'] else 'UNDERPOWERED — excluded'}")
    if not res.get("ran"):
        print(f"\n{res['verdict']}")
        return
    print(f"powered horizons: {res['powered_horizons']}  "
          f"maker_floor={res['maker_floor_bps']}bp  taker_floor={res['taker_floor_bps']}bp")
    print(f"\n{'group':<14}{'verdict':<22}{'kzIC':>8}{'allIC':>8}{'FDR':>7}{'OOS':>7}"
          f"{'spread':>8}{'taker?':>8}{'maker?':>8}")
    for v in res["verdicts"]:
        print(f"{v['group']:<14}{v['verdict']:<22}{str(v.get('kz_mean_ic')):>8}"
              f"{str(v.get('all_mean_ic')):>8}{v.get('kz_fdr_cells', '-'):>7}"
              f"{v.get('kz_oos_consistent', '-'):>7}"
              f"{(str(v.get('kz_median_spread_bps')) + 'bp') if v.get('kz_median_spread_bps') else '-':>8}"
              f"{str(v.get('clears_taker')):>8}{str(v.get('clears_maker')):>8}")
    print(f"\nSTUDY VERDICT: {res['study_verdict']}")
