"""K3 group-level predictive study — does the 5-group fusion have edge at all?

Fable5 directive (2026-07): before touching another parameter, test each
fusion group INDIVIDUALLY against forward returns. Parameter sweeps on a
composite whose components carry no signal are numerology.

Method per symbol:
  - fetch klines on the profile timeframe
  - build_structure + score_dataframe -> per-bar signed group columns g_*
    (each in [-100,+100], + = bullish evidence) plus composite k3_dir/k3_score
  - forward N-bar close-to-close return
  - Spearman rank IC of each group (and composite signed score) vs fwd return,
    computed on ALL bars and on SIGNAL bars only (k3_dir != 0)
  - decile long-short spread: mean fwd return of top-decile group bars minus
    bottom-decile bars (annualization-free, per-bar %)

Aggregation across symbols: mean IC, fraction of symbols with IC > 0,
mean LS spread. Verdicts are blunt:
  |mean IC| >= 0.05 with >=60% sign agreement  -> "carries predictive power"
  |mean IC| >= 0.03 with >=60% sign agreement  -> "weak but present"
  otherwise                                     -> "no measurable edge"

No training, no fitting — this is a measurement, not an optimization.
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
WARMUP = 80


def _spearman(a: pd.Series, b: pd.Series) -> Optional[float]:
    m = a.notna() & b.notna()
    if int(m.sum()) < 60:
        return None
    if a[m].nunique() < 10 or b[m].nunique() < 5:
        return None
    # Spearman = Pearson on ranks (avoids the scipy dependency)
    v = a[m].rank().corr(b[m].rank())
    return None if pd.isna(v) else float(v)


def _decile_spread(g: pd.Series, fwd: pd.Series) -> Optional[float]:
    m = g.notna() & fwd.notna()
    if int(m.sum()) < 100:
        return None
    gg, ff = g[m], fwd[m]
    try:
        q = pd.qcut(gg.rank(method="first"), 10, labels=False)
    except ValueError:
        return None
    top, bot = ff[q == 9], ff[q == 0]
    if len(top) < 10 or len(bot) < 10:
        return None
    return float(top.mean() - bot.mean())


def study_symbol(symbol: str, p: Profile, limit: int, forward: int) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    df = data.klines(sym, p.timeframe, limit)
    if len(df) < WARMUP + forward + 60:
        return {"symbol": sym, "error": f"insufficient bars ({len(df)})"}
    df = score_dataframe(build_structure(df, p), p)

    close = df["close"].astype(float)
    fwd = (close.shift(-forward) / close - 1.0) * 100.0   # % forward return
    lo, hi = WARMUP, len(df) - forward
    df = df.iloc[lo:hi].copy()
    fwd = fwd.iloc[lo:hi]

    signed_score = (df["k3_dir"] * df["k3_score"]).astype(float)
    signal_bars = df["k3_dir"] != 0
    # directional payoff on signal bars: + means the composite called direction right
    dir_payoff = df["k3_dir"].astype(float) * fwd

    per_group: Dict[str, Any] = {}
    cols = {**{g: df[f"g_{g}"].astype(float) for g in GROUPS}, "composite": signed_score}
    for name, series in cols.items():
        per_group[name] = {
            "ic_all": _spearman(series, fwd),
            "ic_signal": _spearman(series[signal_bars], fwd[signal_bars]),
            "ls_spread_pct": _decile_spread(series, fwd),
        }
    out = {
        "symbol": sym,
        "bars": int(len(df)),
        "signal_bars": int(signal_bars.sum()),
        "forward_bars": forward,
        "groups": per_group,
        "signal_dir_accuracy_pct": round(float((dir_payoff[signal_bars] > 0).mean() * 100), 1)
        if int(signal_bars.sum()) > 30 else None,
        "mean_signal_payoff_pct": round(float(dir_payoff[signal_bars].mean()), 4)
        if int(signal_bars.sum()) > 30 else None,
    }
    return out


def _verdict(mean_ic: Optional[float], frac_pos: Optional[float]) -> str:
    if mean_ic is None or frac_pos is None:
        return "insufficient data"
    if abs(mean_ic) >= 0.05 and (frac_pos >= 0.6 or frac_pos <= 0.4):
        return "CARRIES PREDICTIVE POWER" + ("" if mean_ic > 0 else " (inverted)")
    if abs(mean_ic) >= 0.03 and (frac_pos >= 0.6 or frac_pos <= 0.4):
        return "weak but present" + ("" if mean_ic > 0 else " (inverted)"
)
    return "NO MEASURABLE EDGE"


def aggregate(per_symbol: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in per_symbol if "groups" in r]
    agg: Dict[str, Any] = {}
    for name in GROUPS + ["composite"]:
        ics = [r["groups"][name]["ic_all"] for r in ok if r["groups"][name]["ic_all"] is not None]
        sics = [r["groups"][name]["ic_signal"] for r in ok if r["groups"][name]["ic_signal"] is not None]
        ls = [r["groups"][name]["ls_spread_pct"] for r in ok if r["groups"][name]["ls_spread_pct"] is not None]
        mean_ic = float(np.mean(ics)) if ics else None
        frac_pos = float(np.mean([x > 0 for x in ics])) if ics else None
        agg[name] = {
            "mean_ic_all": round(mean_ic, 4) if mean_ic is not None else None,
            "frac_symbols_ic_pos": round(frac_pos, 2) if frac_pos is not None else None,
            "mean_ic_signal": round(float(np.mean(sics)), 4) if sics else None,
            "mean_ls_spread_pct": round(float(np.mean(ls)), 4) if ls else None,
            "verdict": _verdict(mean_ic, frac_pos),
        }
    accs = [r["signal_dir_accuracy_pct"] for r in ok if r.get("signal_dir_accuracy_pct") is not None]
    pays = [r["mean_signal_payoff_pct"] for r in ok if r.get("mean_signal_payoff_pct") is not None]
    agg["_signals"] = {
        "symbols_with_enough_signals": len(accs),
        "mean_dir_accuracy_pct": round(float(np.mean(accs)), 1) if accs else None,
        "mean_payoff_per_signal_bar_pct": round(float(np.mean(pays)), 4) if pays else None,
    }
    return agg


def groupstudy(symbols: List[str], p: Profile, limit: int = 1500,
               forward: Optional[int] = None) -> Dict[str, Any]:
    fwd = forward or (12 if p.timeframe == "5m" else 8)  # ~1h scalp / ~2h day
    per_symbol: List[Dict[str, Any]] = []
    for s in symbols:
        try:
            per_symbol.append(study_symbol(s, p, limit, fwd))
        except Exception as e:  # noqa: BLE001
            per_symbol.append({"symbol": s.upper(), "error": str(e)})
    return {
        "profile": p.name,
        "timeframe": p.timeframe,
        "forward_bars": fwd,
        "per_symbol": per_symbol,
        "aggregate": aggregate(per_symbol),
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 GROUP IC STUDY | {res['profile']} {res['timeframe']} "
          f"forward={res['forward_bars']} bars ===")
    hdr = f"{'symbol':<14}{'bars':>6}{'sig':>6}{'dirAcc%':>9}{'payoff/bp':>11}"
    print(hdr)
    for r in res["per_symbol"]:
        if "groups" not in r:
            print(f"{r['symbol']:<14} {r.get('error')}")
            continue
        acc = r.get("signal_dir_accuracy_pct")
        pay = r.get("mean_signal_payoff_pct")
        print(f"{r['symbol']:<14}{r['bars']:>6}{r['signal_bars']:>6}"
              f"{(f'{acc:.1f}' if acc is not None else '-'):>9}"
              f"{(f'{pay*100:.1f}' if pay is not None else '-'):>11}")
    print(f"\n{'group':<14}{'meanIC':>8}{'IC>0':>6}{'ICsig':>8}{'LSspr%':>8}  verdict")
    for name in GROUPS + ["composite"]:
        a = res["aggregate"][name]
        ic = a["mean_ic_all"]; fp = a["frac_symbols_ic_pos"]
        ics = a["mean_ic_signal"]; ls = a["mean_ls_spread_pct"]
        print(f"{name:<14}{(f'{ic:+.3f}' if ic is not None else '-'):>8}"
              f"{(f'{fp:.2f}' if fp is not None else '-'):>6}"
              f"{(f'{ics:+.3f}' if ics is not None else '-'):>8}"
              f"{(f'{ls:+.3f}' if ls is not None else '-'):>8}  {a['verdict']}")
    s = res["aggregate"]["_signals"]
    print(f"\nsignal-bar directional accuracy (mean across symbols): "
          f"{s['mean_dir_accuracy_pct']}%  (50% = coin flip)")
    print(f"mean payoff per signal bar: {s['mean_payoff_per_signal_bar_pct']}% "
          f"(before costs; taker round trip ~0.11%)")
