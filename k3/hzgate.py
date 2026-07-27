"""K3 Phase 9 Stage 0 — 1h/4h feasibility gate. Measurement only; hard stop after.

Fable5 brief (2026-07-27), honored in full. This module runs NO validity study.
It computes the arithmetic that decides whether Stage 1 may run:

  (b) POWER — per timeframe {1h, 4h} x horizon {1,4,8,24} bars x symbol:
      available bars, non-overlapping event counts (all-bars and
      killzone-restricted), chronological 60/40 OOS counts, and detectable IC
      at 80% power = 2.802/sqrt(n_oos - 1) (same construction as condvalid).
      Also the signal-firing rate (share of bars with k3_dir != 0 and ACTIVE)
      under DAY-profile geometry, for future event-based studies.

  (c) REQUIRED IC — typical move sigma(w) in bps per symbol per horizon, and
      the spread-per-IC slope c calibrated from the Phase 8c DAY artifact's
      all-bars cells (c = median over cells of (spread/|IC|) / sigma_w).
      Required IC to clear a floor with 2x margin = (2 x floor) / (c x sigma(w)).
      Floors: Binance taker 16.5 bps; MEXC all-in 5 bps (range 4-6 reported).

  Gate rule (pre-registered): a timeframe x horizon cell is POWERED iff the
  median KZ-slice OOS detectable IC <= required IC at the MEXC floor (the
  binding venue per the Phase 9 decision rule). Binance is reported alongside.
  If no cell is powered, Stage 1 does not run; report and stop.

  4h KZ caveat: killzone membership is computed from bar-open minute-of-day
  (condvalid._kz_mask). At 4h each bar spans four hours, so zone membership is
  a coarse proxy with edge mislabels (e.g. the 20:00 bar is NY_PM-labeled but
  covers 20:00-24:00). 1h is the primary conditioning timeframe.
"""

from __future__ import annotations

import glob
import json
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .condvalid import _detectable_ic, _kz_mask
from .config import get_profile
from .signals import score_dataframe
from .structure import build_structure
from .validity import HORIZONS, SAMPLE, WARMUP

TF_HOURS = {"1h": 1.0, "4h": 4.0}
BINANCE_FLOOR_BPS = 16.5
MEXC_FLOOR_BPS = 5.0
MEXC_FLOOR_RANGE = (4.0, 6.0)
MARGIN = 2.0
CAL_15M_BARS = 6000            # 15m history for sigma calibration of the 8c cells
CAL_WINDOWS_H = {1: 0.25, 4: 1.0, 8: 2.0, 24: 6.0}   # 8c horizons (15m bars) -> hours


# ------------------------------------------------------------------ helpers

def _sigma_bps(close: pd.Series, idx: np.ndarray, h: int) -> Optional[float]:
    """Median |forward h-bar move| in bps over the given bar indices."""
    if len(idx) < 30:
        return None
    fwd = (close.shift(-h) / close - 1.0).values[idx]
    fwd = fwd[np.isfinite(fwd)]
    return float(np.median(np.abs(fwd)) * 1e4) if len(fwd) >= 30 else None


def _idx(n_bars: int, h: int) -> np.ndarray:
    return np.arange(WARMUP, n_bars - h)[::h]


def _oos_count(n: int) -> int:
    return max(0, n - (int(n * 0.6) + 1))


def _calibrate_c(symbols: List[str]) -> Dict[str, Any]:
    """Spread-per-IC slope from the Phase 8c DAY all-bars cells, per unit sigma."""
    files = sorted(glob.glob("reports/k3_condvalid_DAY_*.json"))
    if not files:
        return {"c": None, "reason": "no k3_condvalid_DAY_*.json artifact found"}
    art = json.load(open(files[-1]))
    cells = [c for c in art.get("cells", [])
             if c.get("condition") == "all" and c.get("quintile_spread_bps")
             and abs(c.get("ic") or 0) > 1e-9]
    if not cells:
        return {"c": None, "reason": "no usable all-bars cells in artifact"}
    sig: Dict[str, Dict[int, float]] = {}
    for sym in {c["symbol"] for c in cells}:
        df = data.klines_history(sym, "15m", CAL_15M_BARS)
        close = df["close"].astype(float)
        sig[sym] = {h: _sigma_bps(close, _idx(len(df), h), h) for h in CAL_WINDOWS_H}
    ratios: List[float] = []
    per_cell: List[Dict[str, Any]] = []
    for c in cells:
        s = sig.get(c["symbol"], {}).get(c["horizon"])
        if not s:
            continue
        k = abs(c["quintile_spread_bps"]) / abs(c["ic"])       # bps per unit IC
        ratios.append(k / s)                                    # c: per-sigma slope
        per_cell.append({"symbol": c["symbol"], "group": c["group"],
                         "window_h": CAL_WINDOWS_H.get(c["horizon"]),
                         "k_bps_per_ic": round(k, 1), "sigma_bps": round(s, 1)})
    return {"c": float(np.median(ratios)) if ratios else None,
            "n_cells": len(ratios), "artifact": files[-1], "cells": per_cell}


# ------------------------------------------------------------------ main gate

def run(symbols: Optional[List[str]] = None, bars: int = 8000,
        timeframes: Optional[List[str]] = None) -> Dict[str, Any]:
    symbols = [s.upper() for s in (symbols or SAMPLE)]
    timeframes = timeframes or list(TF_HOURS)
    day = get_profile("day")

    cal = _calibrate_c(symbols)
    c_slope = cal.get("c")

    tf_results: List[Dict[str, Any]] = []
    for tf in timeframes:
        tf_h = TF_HOURS[tf]
        sym_rows: List[Dict[str, Any]] = []
        for sym in symbols:
            row: Dict[str, Any] = {"symbol": sym, "timeframe": tf}
            try:
                df = data.klines_history(sym, tf, bars)
                n = len(df)
                if n < WARMUP + 250:
                    row["error"] = f"only {n} bars"
                    sym_rows.append(row)
                    continue
                close = df["close"].astype(float)
                kz = _kz_mask(df["timestamp"])
                span_days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 86400
                row["bars"] = n
                row["span_days"] = round(span_days, 1)
                row["kz_bar_frac"] = round(float(kz.mean()), 3)

                # --- signal firing rate under DAY geometry (event-studies input) ---
                try:
                    scored = score_dataframe(build_structure(df, day), day)
                    row["fire_rate_dir"] = round(float((scored["k3_dir"] != 0).mean()), 4)
                    row["fire_rate_active"] = round(float((scored["k3_tier"] == "ACTIVE").mean()), 4)
                except Exception as e:  # noqa: BLE001
                    row["fire_error"] = str(e)

                # --- per-horizon power + typical move ---
                hz: List[Dict[str, Any]] = []
                for h in HORIZONS:
                    idx = _idx(n, h)
                    n_all = len(idx)
                    n_kz = int(kz[idx].sum())
                    n_oos_all, n_oos_kz = _oos_count(n_all), _oos_count(n_kz)
                    hz.append({
                        "horizon_bars": h, "window_h": h * tf_h,
                        "n_all": n_all, "n_kz": n_kz,
                        "n_oos_all": n_oos_all, "n_oos_kz": n_oos_kz,
                        "detectable_ic_oos_all": round(_detectable_ic(n_oos_all + 1), 4),
                        "detectable_ic_oos_kz": round(_detectable_ic(n_oos_kz + 1), 4),
                        "sigma_bps": (lambda s: round(s, 1) if s else None)(_sigma_bps(close, idx, h)),
                    })
                row["horizons"] = hz
            except Exception as e:  # noqa: BLE001
                row["error"] = str(e)
            sym_rows.append(row)

        # --- required IC + gate per horizon (median across symbols) ---
        gate_rows: List[Dict[str, Any]] = []
        for h in HORIZONS:
            cells = [r for r in sym_rows if "horizons" in r]
            det_kz = [x["detectable_ic_oos_kz"] for r in cells
                      for x in r["horizons"] if x["horizon_bars"] == h and x["n_oos_kz"] >= 30]
            det_all = [x["detectable_ic_oos_all"] for r in cells
                       for x in r["horizons"] if x["horizon_bars"] == h and x["n_oos_all"] >= 30]
            sigs = [x["sigma_bps"] for r in cells
                    for x in r["horizons"] if x["horizon_bars"] == h and x["sigma_bps"]]
            det_kz_m = float(np.median(det_kz)) if det_kz else None
            det_all_m = float(np.median(det_all)) if det_all else None
            sig_m = float(np.median(sigs)) if sigs else None
            k_w = c_slope * sig_m if (c_slope and sig_m) else None
            req = {}
            for venue, floor in (("binance", BINANCE_FLOOR_BPS), ("mexc", MEXC_FLOOR_BPS)):
                need_spread = MARGIN * floor
                req[venue] = {"floor_bps": floor, "required_spread_bps": need_spread,
                              "required_ic": round(need_spread / k_w, 4) if k_w else None}
            powered_mexc = bool(det_kz_m is not None and req["mexc"]["required_ic"] is not None
                                and det_kz_m <= req["mexc"]["required_ic"])
            powered_bin = bool(det_kz_m is not None and req["binance"]["required_ic"] is not None
                               and det_kz_m <= req["binance"]["required_ic"])
            grow: Dict[str, Any] = {}
            if not powered_mexc and req["mexc"]["required_ic"]:
                r = req["mexc"]["required_ic"]
                n_need = math.ceil((2.802 / r) ** 2) + 1
                kz_frac = (float(np.median([r2["kz_bar_frac"] for r2 in cells
                                            if "kz_bar_frac" in r2])) if cells else 0.5)
                per_bar = 0.4 * max(kz_frac, 0.05) / h       # OOS KZ events per bar
                bars_need = math.ceil(n_need / per_bar) + WARMUP + h
                grow = {"n_oos_kz_needed": n_need,
                        "bars_needed": bars_need,
                        "years_needed": round(bars_need * tf_h / (24 * 365), 2)}
            gate_rows.append({"horizon_bars": h, "window_h": h * tf_h,
                              "median_detectable_ic_oos_kz": round(det_kz_m, 4) if det_kz_m else None,
                              "median_detectable_ic_oos_all": round(det_all_m, 4) if det_all_m else None,
                              "median_sigma_bps": round(sig_m, 1) if sig_m else None,
                              "k_bps_per_ic": round(k_w, 1) if k_w else None,
                              "required": req, "powered_mexc": powered_mexc,
                              "powered_binance": powered_bin,
                              "if_underpowered": grow or None})
        tf_results.append({"timeframe": tf, "symbols": sym_rows, "gate": gate_rows})

    any_powered = any(g["powered_mexc"] for t in tf_results for g in t["gate"])
    verdict = ("STAGE 0 PASS — at least one timeframe x horizon cell is powered at "
               "the MEXC floor; Stage 1 may run on the powered cells only."
               if any_powered else
               "STAGE 0 STOP — no timeframe x horizon cell can detect the IC required "
               "to clear the MEXC floor with 2x margin. Do not run Stage 1. Fix by "
               "breadth (75-symbol screener) or history, then re-run this gate.")
    return {"kind": "k3_hzgate", "phase": "9-stage0", "symbols": symbols,
            "bars_requested": bars, "calibration": cal,
            "floors": {"binance_taker_bps": BINANCE_FLOOR_BPS,
                       "mexc_allin_bps": MEXC_FLOOR_BPS,
                       "mexc_range_bps": list(MEXC_FLOOR_RANGE), "margin": MARGIN},
            "timeframes": tf_results, "any_powered_mexc": any_powered,
            "verdict": verdict}


# ------------------------------------------------------------------ report

def print_report(res: Dict[str, Any]) -> None:
    print("\n=== K3 PHASE 9 STAGE 0 — 1h/4h FEASIBILITY GATE ===")
    cal = res["calibration"]
    print(f"spread-per-IC slope c = {cal.get('c')} (from {cal.get('n_cells')} cells of "
          f"{cal.get('artifact', 'n/a')})")
    fl = res["floors"]
    print(f"floors: Binance {fl['binance_taker_bps']}bp | MEXC {fl['mexc_allin_bps']}bp "
          f"(range {fl['mexc_range_bps']}) | margin x{fl['margin']}")
    for t in res["timeframes"]:
        print(f"\n--- {t['timeframe']} ---")
        for r in t["symbols"]:
            if "error" in r:
                print(f"  {r['symbol']:<12} ERROR: {r['error']}")
                continue
            print(f"  {r['symbol']:<12} bars={r['bars']} span={r['span_days']}d "
                  f"kz%={r['kz_bar_frac']} fire(dir)={r.get('fire_rate_dir')} "
                  f"fire(ACTIVE)={r.get('fire_rate_active')}")
        print(f"  {'win':>5}{'sigma':>8}{'k(w)':>8}{'detIC_kz':>9}{'reqIC_M':>8}"
              f"{'reqIC_B':>8}{'MEXC':>10}{'BIN':>10}")
        for g in t["gate"]:
            print(f"  {g['window_h']:>4}h{str(g['median_sigma_bps']):>8}"
                  f"{str(g['k_bps_per_ic']):>8}{str(g['median_detectable_ic_oos_kz']):>9}"
                  f"{str(g['required']['mexc']['required_ic']):>8}"
                  f"{str(g['required']['binance']['required_ic']):>8}"
                  f"{('POWERED' if g['powered_mexc'] else 'no'):>10}"
                  f"{('POWERED' if g['powered_binance'] else 'no'):>10}")
            if g.get("if_underpowered"):
                u = g["if_underpowered"]
                print(f"        to power: n_oos_kz={u['n_oos_kz_needed']} -> "
                      f"{u['bars_needed']} bars ~= {u['years_needed']}y")
    print(f"\nGATE VERDICT: {res['verdict']}")
